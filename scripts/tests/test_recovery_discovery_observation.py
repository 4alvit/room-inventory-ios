"""Six paired/fault groups; all subprocess/selector/signal/filesystem work is fake.

Frozen Alarm/Discovery class source below is the exact 3876cda baseline, for
operation/clock parity without executing git or depending on local artifacts.
"""
from contextlib import ExitStack
from copy import deepcopy
import errno
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("discovery_observation_candidate", Path(__file__).resolve().parents[1] / "recovery_hosted.py")
H = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = H
SPEC.loader.exec_module(H)
BASELINE_COMMIT = "3876cda353e7a664b4184be07454ed8d126e7b5e"
BASELINE_SOURCE = 'class Alarm:\n    """Non-renewing operation deadline; relinquished before the base controller."""\n    def __init__(self, end, clock=time.monotonic):\n        self.end, self.clock = end, clock\n\n    def check(self):\n        require(self.clock() < self.end, "Hosted absolute deadline reached", Deadline)\n\n    def arm(self, end=None):\n        remaining = min(self.end, end if end is not None else self.end) - self.clock()\n        require(remaining > 0, "Hosted deadline exhausted", Deadline)\n        signal.setitimer(signal.ITIMER_REAL, remaining)\n\n    def __enter__(self):\n        require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "Existing process timer is active", Failure)\n        self.previous = signal.getsignal(signal.SIGALRM)\n        signal.signal(signal.SIGALRM, self.expired)\n        try:\n            self.arm()\n        except BaseException:\n            signal.signal(signal.SIGALRM, self.previous)\n            raise\n        return self\n\n    def expired(self, *_):\n        raise Deadline("Hosted absolute deadline reached")\n\n    def __exit__(self, *_):\n        signal.setitimer(signal.ITIMER_REAL, 0)\n        signal.signal(signal.SIGALRM, self.previous)\n\n\nclass Discovery:\n    """Bounded one-pass commands with the controller\'s owned-group cleanup."""\n    def __init__(self, root, output, env, alarm, *, disk_usage=shutil.disk_usage):\n        self.root, self.output, self.env, self.alarm = root, output, dict(env), alarm\n        self.disk_usage = disk_usage\n        self.records, self.cleanup_errors = [], []\n\n    def check(self):\n        self.alarm.check()\n        require(self.disk_usage(self.output).free >= POLICY["abort_free_bytes"], "Hosted disk abort floor reached")\n        self.alarm.check()\n\n    def command(self, args, name, cap=20, *, retain_output=True):\n        self.check()\n        start = self.alarm.clock()\n        end = min(self.alarm.end, start + cap)\n        require(end - self.alarm.clock() >= 8, "Insufficient discovery/cleanup budget", Deadline)\n        record = {"name": name, "args": [str(a) for a in args], "exit_code": None, "primary_error": None,\n                  "timing": {"start": start, "work_deadline": end - 4,\n                             "command_deadline": end, "requested_cap": cap}}\n        self.records.append(record)\n        buffers, process, selector, primary = [bytearray(), bytearray()], None, None, None\n        state = {}\n        def tick():\n            self.check()\n            require(self.alarm.clock() < end - 4, "Discovery command deadline reached", Deadline)\n        try:\n            self.alarm.arm(end - 4)\n            selector = selectors.DefaultSelector()\n            oldmask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})\n            try:\n                tick()\n                process = subprocess.Popen(record["args"], cwd=self.root, env=self.env, start_new_session=True,\n                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)\n            finally:\n                signal.pthread_sigmask(signal.SIG_SETMASK, oldmask)\n            for index, pipe in enumerate((process.stdout, process.stderr)):\n                os.set_blocking(pipe.fileno(), False)\n                selector.register(pipe, selectors.EVENT_READ, index)\n            while selector.get_map() or process.poll() is None:\n                tick()\n                for key, _ in selector.select(min(.1, max(0, end - 4 - self.alarm.clock()))):\n                    tick()\n                    try:\n                        data = os.read(key.fileobj.fileno(), 65536)\n                    except BlockingIOError:\n                        continue\n                    if not data:\n                        selector.unregister(key.fileobj)\n                    else:\n                        require(len(buffers[key.data]) + len(data) <= 4 * controller.MIB, "Discovery stream cap reached")\n                        buffers[key.data].extend(data)\n            tick()\n            record["exit_code"] = process.wait(timeout=0)\n            require(record["exit_code"] == 0, "Discovery command failed: " + name)\n        except BaseException as error:\n            primary = error\n            record["primary_error"] = {"type": type(error).__name__, "message": str(error)}\n        finally:\n            signal.setitimer(signal.ITIMER_REAL, 0)\n            # Kill/reap before closing pipes, and never renew the absolute end.\n            operations = []\n            if process is not None:\n                operations.append(("owned_group", lambda: controller.kill_owned(process, end, state=state, clock=self.alarm.clock)))\n            if selector is not None:\n                operations.append(("selector_close", selector.close))\n            if process is not None:\n                operations.extend(("pipe_close", p.close) for p in (process.stdout, process.stderr))\n            for operation, action in operations:\n                try:\n                    require(self.alarm.clock() < end, "Discovery cleanup deadline reached", Deadline)\n                    self.alarm.arm(end)\n                    result = action()\n                    if operation == "owned_group":\n                        record["cleanup"] = result\n                        require(result["success"], "Discovery owned-group cleanup uncertain")\n                except BaseException as error:\n                    self.cleanup_errors.append({"command": name, "operation": operation, "error": str(error)})\n            signal.setitimer(signal.ITIMER_REAL, 0)\n            try:\n                # Sample only after owned-group cleanup. Receipt failures must\n                # not prevent cleanup or replace an existing command error.\n                record["timing"]["finish"] = self.alarm.clock()\n                self.alarm.arm()\n                self.check()\n                for suffix, data in zip(("stdout", "stderr"), buffers):\n                    self.check()\n                    if retain_output:\n                        (self.output / (name + "." + suffix)).write_bytes(data)\n                        record[suffix + "_sha256"] = controller.sha(data)\n                    else:\n                        # Raw commit output includes names, email and message.\n                        record[suffix + "_bytes"] = len(data)\n                record["output_retained"] = retain_output\n                controller.write_json(self.output / "commands.json", self.records)\n                controller.tree_size(self.output, 16 * controller.MIB, self.check, max_entries=128)\n                self.check()\n            except BaseException as error:\n                self.cleanup_errors.append({"command": name, "operation": "receipt", "error": str(error)})\n                primary = primary or error\n        if primary:\n            raise primary\n        require(not any(e["command"] == name for e in self.cleanup_errors), "Discovery cleanup/receipt incomplete")\n        return bytes(buffers[0])\n\n'
BASELINE = dict(vars(H))
exec(compile(BASELINE_SOURCE, "frozen_discovery_3876.py", "exec"), BASELINE)
VALIDATION_CASES = []


class World:
    def __init__(self, candidate=True, mode="success"):
        self.candidate, self.mode = candidate, mode
        self.events, self.saved, self.now = [], [], 100.0
        self.maps, self.disk_calls, self.poll_calls, self.select_calls = {}, 0, 0, 0
        self.reads = {11: [b"a", b""], 12: [b"b", b""]}
        self.primary = None
        self.stop_calls = 0
        self.close_calls = []
        self.output = Path("/fake/output")
        alarm_class = H.Alarm if candidate else BASELINE["Alarm"]
        discovery_class = H.Discovery if candidate else BASELINE["Discovery"]
        self.alarm = alarm_class(220.0, self.clock)
        self.discovery = discovery_class(Path("/fake/repo"), self.output, {"PATH": "/fake/bin"}, self.alarm, disk_usage=self.disk)
        self.process = SimpleNamespace(pid=12345, stdout=self.pipe(11), stderr=self.pipe(12), poll=self.poll, wait=self.wait)
        self.selector = SimpleNamespace(register=self.register, unregister=self.unregister, get_map=self.get_map, select=self.select, close=lambda: self.close("selector"))
        self.cleanup_report = {"success": True, "group_state": "absent", "leader_reaped": True, "returncode": 0, "errors": [], "signals": []}

    def log(self, *event):
        self.events.append(list(event))

    def clock(self):
        self.log("clock", self.now)
        return self.now

    def disk(self, path):
        self.disk_calls += 1
        self.log("disk", str(path))
        if self.disk_calls == 2 and self.mode in ("slow_disk", "absolute_disk"):
            self.now += 56 if self.mode == "slow_disk" else 121
        return SimpleNamespace(free=24 * H.controller.GIB)

    def pipe(self, fd):
        def fileno():
            self.log("fileno", fd)
            return fd
        return SimpleNamespace(fileno=fileno, close=lambda: self.close(fd))

    def close(self, label):
        self.close_calls.append(label)
        self.log("close", label)

    def spawn(self, args, **kwargs):
        self.log("Popen", args, {key: str(value) if isinstance(value, Path) else value for key, value in kwargs.items()})
        if self.mode == "slow_spawn":
            self.now += 56
        return self.process

    def register(self, pipe, events, index):
        self.log("register", index, events)
        self.maps[11 + index] = SimpleNamespace(fileobj=pipe, data=index)

    def unregister(self, pipe):
        fd = 11 if pipe is self.process.stdout else 12
        self.log("unregister", fd)
        del self.maps[fd]

    def get_map(self):
        self.log("get_map")
        return self.maps

    def select(self, timeout):
        self.select_calls += 1
        self.log("select", timeout)
        if self.mode in ("timeout", "exit_open_pipe") or self.mode == "running_poll" and not self.maps:
            self.now += 56
            return []
        return [(key, 1) for key in self.maps.values()]

    def read(self, fd, cap):
        self.log("read", fd, cap)
        item = self.reads[fd].pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def poll(self):
        self.poll_calls += 1
        self.log("poll")
        if self.mode == "final_tick":
            self.now += 56
        return None if self.mode == "running_poll" else 0

    def wait(self, timeout):
        self.log("wait", timeout)
        return 0

    def stop(self, process, end, *, state, clock):
        self.stop_calls += 1
        self.log("cleanup", process.pid, end)
        return self.cleanup_report

    def mask(self, how, mask):
        self.log("mask", int(how), sorted(int(item) for item in mask))
        return set()

    def write(self, path, data):
        self.log("write", str(path), bytes(data).hex())
        return len(data)

    def write_json(self, path, data):
        self.saved.append(deepcopy(data))
        # The additive field necessarily changes JSON bytes; all old receipt
        # content and the external write boundary remain paired exactly.
        plain = [{key: value for key, value in row.items() if key != "discovery_observation"} for row in data]
        self.log("write_json", str(path), plain)

    def tree(self, path, cap, check, **kwargs):
        self.log("tree", str(path), cap, kwargs)
        check()
        return {}

    def __enter__(self):
        self.stack = ExitStack()
        def selector():
            self.log("selector")
            return self.selector
        replacements = [(H.subprocess, "Popen", self.spawn), (H.selectors, "DefaultSelector", selector),
            (H.os, "set_blocking", lambda fd, block: self.log("set_blocking", fd, block)), (H.os, "read", self.read),
            (H.signal, "pthread_sigmask", self.mask),
            (H.signal, "setitimer", lambda which, duration: self.log("timer", int(which), duration)),
            (H.controller, "kill_owned", self.stop), (H.controller, "write_json", self.write_json),
            (H.controller, "tree_size", self.tree), (Path, "write_bytes", lambda path, data: self.write(path, data))]
        for owner, name, value in replacements:
            self.stack.enter_context(patch.object(owner, name, value))
        return self

    def __exit__(self, *args):
        self.stack.close()

    def run(self):
        try:
            self.value = self.discovery.command(["xcrun", "simctl", "list", "--json"], "simulator-inventory", cap=60)
        except BaseException as error:
            self.primary = error
        self.record = self.discovery.records[0]
        return self


class DiscoveryObservationTests(unittest.TestCase):
    def pair(self, mode="success", setup=None):
        worlds = []
        for candidate in (False, True):
            with World(candidate, mode) as w:
                if setup:
                    setup(w)
                w.run()
            worlds.append(w)
        old, new = worlds
        self.assertEqual(old.events, new.events)
        self.assertEqual(type(old.primary), type(new.primary))
        self.assertEqual(str(old.primary), str(new.primary))
        self.assertEqual(old.stop_calls, new.stop_calls)
        VALIDATION_CASES.append({"mode": mode, "setup": None if setup is None else setup.__name__,
            "external_trace_equal": True, "baseline_external_calls": len(old.events),
            "candidate_external_calls": len(new.events),
            "clock_calls_each": sum(event[0] == "clock" for event in new.events),
            "trace_sha256": hashlib.sha256(json.dumps(new.events, sort_keys=True).encode()).hexdigest(),
            "outcome": None if new.primary is None else type(new.primary).__name__,
            "baseline_observation_absent": "discovery_observation" not in old.record,
            "candidate_observation": new.record.get("discovery_observation"),
            "events": new.events})
        return old, new

    def observation(self, w):
        value = w.record["discovery_observation"]
        self.assertLessEqual(len(json.dumps({"commands": [{"discovery_observation": value}]}, indent=2).encode()), 2048)
        return value

    def test_1_success_timeout_exact_external_clock_and_signal_trace(self):
        for mode in ("success", "timeout"):
            with self.subTest(mode=mode):
                old, new = self.pair(mode)
                self.assertEqual(new.stop_calls, 1)
                self.assertEqual(new.close_calls, ["selector", 11, 12])
                self.assertNotIn("discovery_observation", old.record)  # Negative control: no localization.
                obs = self.observation(new)
                self.assertEqual(obs["capture_incomplete"], mode == "timeout")
                self.assertEqual(new.record["timing"]["work_deadline"], 156)
                self.assertEqual(new.record["timing"]["command_deadline"], 160)
                self.assertEqual(new.alarm.end, 220)
                self.assertTrue(obs["popen_assigned"])
                if mode == "success":
                    self.assertIsNone(new.primary)
                    self.assertEqual(obs["stdout"]["returned_bytes"], 1)
                    self.assertEqual(obs["stdout"]["retained_bytes"], 1)
                    self.assertEqual(obs["last_completed"], "wait")
                else:
                    self.assertIsInstance(new.primary, H.Deadline)
                    self.assertEqual(obs["tick_site"], "loop_head")
                    self.assertEqual(obs["clock_sample"], {"source": "work_compare", "elapsed": 56.0})

    def test_2_no_output_open_pipe_and_returned_none_are_distinct(self):
        for mode in ("timeout", "exit_open_pipe", "running_poll"):
            with self.subTest(mode=mode):
                _, w = self.pair(mode)
                obs = self.observation(w)
                self.assertIsInstance(w.primary, H.Deadline)
                self.assertEqual(obs["last_poll_result"], None)
                self.assertEqual(obs["poll_seen"], mode == "running_poll")
                self.assertEqual(obs["poll_returns"], w.poll_calls)
                if mode != "running_poll":
                    self.assertEqual(w.poll_calls, 0)  # Open map short-circuits poll even if child would return zero.
                    self.assertFalse(obs["stdout"]["eof"])
                    self.assertEqual(obs["stdout"]["read_returns"], 0)

    def test_3_delayed_disk_spawn_and_final_tick_keep_original_bounds(self):
        for mode, stage, substage, source, spawned in (
            ("slow_disk", "pre_spawn", "work_compare", "work_compare", False),
            ("absolute_disk", "pre_spawn", "post_alarm", "alarm_check", False),
            ("slow_spawn", "loop_head", "work_compare", "work_compare", True),
            ("final_tick", "final", "work_compare", "work_compare", True)):
            with self.subTest(mode=mode):
                _, w = self.pair(mode)
                obs = self.observation(w)
                self.assertIsInstance(w.primary, H.Deadline)
                self.assertEqual((obs["tick_site"], obs["check_substage"]), (stage, substage))
                self.assertEqual(obs["clock_sample"]["source"], source)
                self.assertEqual(obs["popen_assigned"], spawned)
                self.assertEqual(w.stop_calls, int(spawned))
                self.assertEqual(obs["last_entered"], "tick")

    def test_4_after_return_before_marker_is_incomplete_and_preserves_primary(self):
        for stage in ("mask", "spawn", "select", "read", "read_eof", "poll", "wait"):
            for exception in (H.Deadline("injected boundary"), KeyboardInterrupt(), SystemExit(7)):
                with self.subTest(stage=stage, error=type(exception).__name__), World() as w:
                    observe = w.discovery.observe
                    target = "read" if stage == "read_eof" else stage
                    if stage == "read_eof":
                        w.reads[11] = [b""]
                    fired = []
                    def interrupt(current, *, completed=False):
                        if current == target and completed and not fired:
                            fired.append(True)
                            raise exception
                        return observe(current, completed=completed)
                    w.discovery.observe = interrupt
                    w.run()
                    self.assertTrue(fired)
                    self.assertIs(w.primary, exception)
                    obs = self.observation(w)
                    self.assertTrue(obs["capture_incomplete"])
                    self.assertEqual(obs["last_entered"], target)
                    self.assertNotEqual(obs["last_completed"], target)
                    if stage == "read_eof":
                        self.assertFalse(obs["stdout"]["eof"])
                        self.assertEqual(obs["stdout"]["read_returns"], 1)
                    self.assertEqual(w.stop_calls, int(stage != "mask"))
                    mask_calls = [event for event in w.events if event[0] == "mask"]
                    self.assertEqual(len(mask_calls), 2)  # Completion-marker failure cannot leave SIGALRM blocked.

    def test_5_eagain_eof_cap_and_saturating_returned_vs_retained_bytes(self):
        def eagain(w):
            w.reads[11].insert(0, BlockingIOError())
        _, w = self.pair(setup=eagain)
        obs = self.observation(w)
        self.assertEqual(obs["stdout"], {"read_returns": 2, "returned_bytes": 1, "retained_bytes": 1, "eof": True, "would_block": 1})
        def cap(w):
            w.reads[11] = [b"x" * (4 * H.controller.MIB + 1)]
        _, w = self.pair(setup=cap)
        obs = self.observation(w)
        self.assertIsInstance(w.primary, H.controller.RunFailure)
        self.assertEqual(obs["stdout"]["returned_bytes"], 4 * H.controller.MIB + 1)
        self.assertEqual(obs["stdout"]["retained_bytes"], 0)
        self.assertFalse(obs["stdout"]["eof"])
        with World() as w:
            observe = w.discovery.observe
            def saturate(stage, *, completed=False):
                if stage == "arm" and not completed:
                    obs = w.discovery._observation
                    obs["select_returns"] = obs["poll_returns"] = 2**31 - 1
                    for pipe in (obs["stdout"], obs["stderr"]):
                        for key in ("read_returns", "returned_bytes", "retained_bytes", "would_block"):
                            pipe[key] = 2**31 - 1
                return observe(stage, completed=completed)
            w.discovery.observe = saturate
            w.run()
            obs = self.observation(w)
            self.assertIsNone(w.primary)
            self.assertTrue(obs["saturated"] and obs["capture_incomplete"])
            self.assertEqual(obs["stdout"]["retained_bytes"], 2**31 - 1)
            self.assertEqual(w.value, b"a")  # Saturation never expands real buffers.
            frozen_trace = list(w.events)
            for sample in (None, ("select_timeout", float("nan")), ("alarm_check", float("inf")),
                           ("alarm_arm", True), ("work_compare", 99.0), ("work_compare", 86500.1)):
                w.alarm.last_sample = sample
                target = deepcopy(obs)
                target["clock_sample"] = None
                captured = w.discovery.capture_observation(target, 100.0)
                self.assertIsNone(None if captured["clock_sample"] is None else captured["clock_sample"]["elapsed"])
            worst = deepcopy(obs)
            worst.update(last_entered="pipe_setup", last_completed="pipe_setup", tick_site="read_ready",
                         check_substage="work_compare", last_poll_result=-255,
                         clock_sample={"source": "select_timeout", "elapsed": 86399.999999})
            self.assertLessEqual(len(json.dumps({"commands": [{"discovery_observation": worst}]}, indent=2).encode()), 2048)
            self.assertEqual(w.events, frozen_trace)  # No clock/query/operation in capture.

    def test_6_sticky_eperm_capture_and_serialization_faults_preserve_cleanup(self):
        real_cleanup = H.controller.kill_owned
        def sticky(w):
            def stop(process, end, *, state, clock):
                w.stop_calls += 1
                w.log("cleanup", process.pid, end)
                probes = [errno.EPERM, errno.ESRCH]
                def killpg(pid, sig):
                    w.log("killpg", pid, int(sig))
                    if sig == 0:
                        raise OSError(probes.pop(0), "injected group probe")
                report = real_cleanup(process, end, state=state, clock=clock, killpg=killpg,
                                      sleep=lambda seconds: (_ for _ in ()).throw(AssertionError("no sleeping")))
                self.assertFalse(report["success"])
                self.assertEqual(report["group_state"], "absent")
                self.assertTrue(report["leader_reaped"])
                self.assertEqual(state["observation_errors"][0]["errno"], errno.EPERM)
                return report
            # Replace the already-installed World stop fake, not a real syscall.
            w.stack.enter_context(patch.object(H.controller, "kill_owned", stop))
        _, w = self.pair(setup=sticky)
        self.assertIsInstance(w.primary, H.controller.RunFailure)
        self.assertEqual(w.discovery.cleanup_errors[0]["operation"], "owned_group")
        for mode in ("success", "timeout"):
            for point in ("capture", "serialization"):
                with self.subTest(mode=mode, point=point), World(mode=mode) as w:
                    sticky(w)
                    error = KeyboardInterrupt("diagnostic injection")
                    if point == "capture":
                        w.discovery.capture_observation = lambda *args: (_ for _ in ()).throw(error)
                    else:
                        w.stack.enter_context(patch.object(H.json, "dumps", side_effect=error))
                    w.run()
                    self.assertEqual(w.stop_calls, 1)
                    self.assertEqual(w.close_calls, ["selector", 11, 12])
                    self.assertFalse(w.record["cleanup"]["success"])
                    self.assertEqual(w.record["cleanup"]["group_state"], "absent")
                    self.assertTrue(any(item["operation"] == "owned_group" for item in w.discovery.cleanup_errors))
                    if mode == "timeout":
                        self.assertIsInstance(w.primary, H.Deadline)
                        self.assertEqual(w.record["primary_error"]["type"], "DeadlineFailure")
                    else:
                        self.assertIs(w.primary, error)
                    if point == "capture":
                        self.assertNotIn("discovery_observation", w.record)
                    else:
                        self.assertTrue(w.record["discovery_observation"]["capture_incomplete"])
                        self.assertFalse(w.saved)


if __name__ == "__main__":
    unittest.main()
