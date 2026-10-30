"""Pure device-telemetry regressions using denied/injected runtime operations."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

import test_recovery_device_service as device

C = device.C


def without_origin_lines(value):
    """Retain origin reasons/flags/frame sources, ignoring physical line moves."""
    if isinstance(value, list):
        return [without_origin_lines(item) for item in value]
    if isinstance(value, dict):
        result = {key: without_origin_lines(item) for key, item in value.items()}
        origin = result.get("exception_origin")
        if isinstance(origin, dict) and "frames" in origin:
            origin["frames"] = [{key: item for key, item in frame.items() if key != "line"}
                                for frame in origin["frames"]]
        return result
    return value


class DeviceObservationTests(unittest.TestCase):
    setUp = device.DeviceTests.setUp
    assert_finished = device.DeviceTests.assert_finished

    @staticmethod
    def configure(w, scenario):
        if scenario == "data":
            w.read_action = lambda fd: b"abc" if w.walked < 180 else b""
        elif scenario == "running_no_output":
            def read(fd):
                if w.scanning:
                    raise BlockingIOError()
                return b""
            w.read_action = read
            w.poll_action = lambda: None if w.scanning else 0
        elif scenario == "eof_without_exit":
            w.poll_action = lambda: None if w.scanning else 0
        elif scenario == "one_eof":
            w.read_action = lambda fd: b"" if fd == 111 or not w.scanning else b"abc"
        elif scenario == "late_poll":
            def late():
                w.clock.now = w.run.command_deadline
                return 0
            w.poll_action = late
        elif scenario == "bad_exit":
            w.poll_action = lambda: 3
        elif scenario == "interrupted_select":
            def interrupted(timeout):
                w.events.append(("select", w.walked, timeout))
                raise C.DeadlineFailure("select interrupted")
            w.selector.select.side_effect = interrupted
        elif scenario == "partial_write":
            w.read_action = lambda fd: b"abc"
            w.write_action = lambda index, data: 1
        elif scenario == "unknown_cleanup":
            w.cleanup.update(success=False, group_state="unknown", errors=["unknown group"])
        elif scenario == "failed_barrier":
            def fail():
                raise C.RunFailure("terminal accounting failure")
            w.barrier_action = fail
        elif scenario != "success":
            raise AssertionError(scenario)

    def trace(self, scenario, *, enabled=True, module=C):
        with device.World(module=module, count=200) as w:
            self.configure(w, scenario)
            original_clock = w.clock
            def clock():
                w.events.append(("clock", original_clock.now))
                return original_clock()
            w.run.clock = clock
            # Disabling only optional device telemetry must leave work, clocks,
            # prior receipts and errors unchanged.
            if not enabled:
                w.run.observe_device_service = lambda *args, **kwargs: None
            w.run.flush.side_effect = lambda: w.events.append(("flush",))
            result, error = None, None
            try:
                result = w.invoke()
            except BaseException as caught:
                error = (type(caught).__name__, str(caught))
            self.assert_finished(w)
            command = deepcopy(w.record)
            observation = command.pop("device_service", None)
            # Keep failure origin metadata and frame identities; only physical
            # source line numbers change with optional instrumentation.
            command = without_origin_lines(command)
            calls = {
                "lstat": Path.lstat.call_count, "exists": Path.exists.call_count,
                "mkdir": Path.mkdir.call_count, "is_dir": Path.is_dir.call_count,
                "is_symlink": Path.is_symlink.call_count,
                "spawn": module.subprocess.Popen.call_count, "read": module.os.read.call_count,
                "scandir": module.os.scandir.call_count, "set_blocking": module.os.set_blocking.call_count,
                "write_json": module.write_json.call_count, "select": w.selector.select.call_count,
                "selector_close": w.selector.close.call_count, "register": w.selector.register.call_count,
                "unregister": w.selector.unregister.call_count, "get_map": w.selector.get_map.call_count,
                "wait": w.process.wait.call_count, "poll": w.process.poll.call_count,
                "stream_close": [s.close.call_count for s in w.logs],
                "pipe_close": [w.process.stdout.close.call_count, w.process.stderr.close.call_count],
            }
            return {"events": w.events, "calls": calls, "result": result, "error": error,
                    "command": command, "cleanup_errors": without_origin_lines(w.run.record["cleanup_errors"]),
                    "observation": observation}

    def test_optional_device_observation_preserves_work_and_clock_trace(self):
        for scenario in ("success", "data", "running_no_output", "eof_without_exit", "one_eof",
                         "late_poll", "bad_exit", "interrupted_select", "partial_write",
                         "unknown_cleanup", "failed_barrier"):
            with self.subTest(scenario=scenario):
                before, after = self.trace(scenario, enabled=False), self.trace(scenario)
                before.pop("observation")
                after.pop("observation")
                self.assertEqual(after, before)

    def test_success_records_both_pipes_and_existing_completion_sample(self):
        result = self.trace("data")
        o = result["observation"]
        self.assertEqual((o["quanta_started"], o["quanta_completed"], o["polls_returned"]), (3, 3, 3))
        for stream in ("stdout", "stderr"):
            self.assertEqual(o[stream], {"read_returns": 3, "read_bytes": 6,
                                         "eof_returns": 1, "would_block": 0})
        self.assertEqual(o["first_completed_checkpoint_elapsed"], 0)
        self.assertEqual(o["last_completed_checkpoint_elapsed"], 0)
        self.assertEqual(o["terminal_barrier"], {"reached": True, "completed": True})
        self.assertFalse(o["capture_incomplete"])
        self.assertEqual(result["command"]["derived_service"]["quanta_started"], 0)

    def test_poll_none_and_would_block_are_visible_without_fabricated_exit(self):
        result = self.trace("running_no_output")
        o = result["observation"]
        self.assertEqual((o["quanta_started"], o["quanta_completed"], o["polls_returned"]), (3, 3, 3))
        self.assertEqual(o["stdout"], {"read_returns": 0, "read_bytes": 0,
                                        "eof_returns": 0, "would_block": 3})
        self.assertEqual(o["stderr"], o["stdout"])
        self.assertNotIn("device_scan_handoff", result["command"])

    def test_incomplete_eof_or_exit_cannot_authorize_handoff(self):
        for scenario in ("one_eof", "eof_without_exit"):
            with self.subTest(scenario=scenario):
                result = self.trace(scenario)
                self.assertIsNone(result["error"])
                self.assertNotIn("device_scan_handoff", result["command"])
                self.assertEqual(result["observation"]["quanta_completed"], 3)

    def test_late_poll_is_counted_but_cannot_complete_or_pass(self):
        result = self.trace("late_poll")
        o = result["observation"]
        self.assertEqual(result["error"][0], "DeadlineFailure")
        self.assertEqual((o["quanta_started"], o["quanta_completed"], o["polls_returned"]), (1, 0, 1))
        self.assertIsNone(o["last_completed_checkpoint_elapsed"])
        self.assertTrue(o["capture_incomplete"])
        self.assertNotIn("device_scan_handoff", result["command"])
        self.assertEqual(o["terminal_barrier"], {"reached": False, "completed": False})
        self.assertEqual(result["command"]["end_deadline_elapsed"], 90)

    def test_interrupted_quantum_has_no_fictitious_reads_or_completion(self):
        o = self.trace("interrupted_select")["observation"]
        self.assertEqual((o["quanta_started"], o["quanta_completed"], o["polls_returned"]), (1, 0, 0))
        self.assertEqual(o["stdout"]["read_returns"], 0)
        self.assertEqual(o["stderr"]["read_returns"], 0)
        self.assertTrue(o["capture_incomplete"])

    def test_partial_write_keeps_returned_bytes_distinct_from_retained(self):
        result = self.trace("partial_write")
        o = result["observation"]
        self.assertEqual(result["error"][0], "RunFailure")
        self.assertEqual(o["stderr"]["read_bytes"], 3)
        self.assertEqual(result["command"]["stderr_sha256"], C.sha(b""))
        self.assertEqual(o["polls_returned"], 0)
        self.assertTrue(o["capture_incomplete"])

    def test_failed_cleanup_and_accounting_never_show_completed_barrier(self):
        for scenario, reached in (("unknown_cleanup", False), ("failed_barrier", True)):
            with self.subTest(scenario=scenario):
                result = self.trace(scenario)
                self.assertIsNotNone(result["error"])
                self.assertEqual(result["observation"]["terminal_barrier"],
                                 {"reached": reached, "completed": False})
                self.assertEqual(result["observation"]["quanta_completed"], 1)

    def test_supplied_values_only_and_bounded_independent_schema(self):
        with device.World() as w:
            w.run.clock = Mock(side_effect=AssertionError("new clock call"))
            w.run.disk_usage = Mock(side_effect=AssertionError("new disk call"))
            target = {}
            w.run.observe_derived_service(target, "init")
            original = deepcopy(target["derived_service"])
            w.run.observe_device_service(target, "init")
            o = target["device_service"]
            self.assertEqual(o, original)
            self.assertIsNot(o["stdout"], target["derived_service"]["stdout"])
            for key in ("quanta_started", "quanta_completed", "polls_returned"):
                o[key] = 2**31 - 1
            for stream in ("stdout", "stderr"):
                for key in o[stream]:
                    o[stream][key] = 2**31 - 1
            for event in ("quantum_started", "quantum_completed", "poll_return"):
                w.run.observe_device_service(target, event, value=w.run.start + .75)
            for index in (0, 1):
                w.run.observe_device_service(target, "read_return", index=index, value=1 << 10000)
                w.run.observe_device_service(target, "read_return", index=index, value=0)
                w.run.observe_device_service(target, "would_block", index=index)
            self.assertTrue(o["saturated"])
            self.assertTrue(o["capture_incomplete"])
            self.assertEqual(o["last_completed_checkpoint_elapsed"], .75)
            self.assertTrue(all(v == 2**31 - 1 for stream in ("stdout", "stderr") for v in o[stream].values()))
            self.assertEqual(target["derived_service"], original)
            self.assertLess(len(json.dumps(target, allow_nan=False)), 4096)
            w.run.clock.assert_not_called()
            w.run.disk_usage.assert_not_called()

    def test_invalid_completion_is_unknown_without_replacing_previous_first(self):
        with device.World() as w:
            for value in (None, float("nan"), float("inf"), w.run.start - 1, w.run.start + 86401):
                target = {}
                w.run.observe_device_service(target, "quantum_completed", value=w.run.start + 2)
                w.run.observe_device_service(target, "quantum_completed", value=value)
                o = target["device_service"]
                self.assertEqual(o["first_completed_checkpoint_elapsed"], 2)
                self.assertIsNone(o["last_completed_checkpoint_elapsed"])
                self.assertTrue(o["capture_incomplete"])

    def test_generic_observer_error_does_not_change_work_or_cleanup(self):
        with device.World() as w:
            original = w.run.observe_device_service
            class BrokenCounter(dict):
                def __getitem__(self, key):
                    if key == "quanta_started":
                        raise ValueError("counter unavailable")
                    return super().__getitem__(key)
            def observe(target, event, **kwargs):
                if event == "quantum_started":
                    target["device_service"] = BrokenCounter(target["device_service"])
                return original(target, event, **kwargs)
            w.run.observe_device_service = observe
            self.assertEqual(w.invoke(), b"")
            self.assertTrue(w.record["device_service"]["capture_incomplete"])
            self.assertTrue(w.record["device_service"]["terminal_barrier"]["completed"])
            self.assert_finished(w)

    def test_controls_propagate_and_post_primary_markers_cannot_replace_them(self):
        for secondary in (C.DeadlineFailure("secondary alarm"), KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(secondary=type(secondary).__name__), device.World() as w:
                primary = C.DeadlineFailure("original service interruption")
                original = w.run.observe_device_service
                attempted = []
                def observe(target, event, **kwargs):
                    if event == "quantum_started":
                        raise primary
                    if event == "incomplete":
                        attempted.append(event)
                        raise secondary
                    return original(target, event, **kwargs)
                w.run.observe_device_service = observe
                self.assertIs(device.failure(w.invoke), primary)
                self.assertEqual(attempted, ["incomplete"])
                self.assertEqual(w.record["primary_error"]["message"], str(primary))
                self.assertTrue(w.record["derived_service"]["capture_incomplete"])
                self.assert_finished(w)

    def test_cleanup_mode_and_missing_device_create_no_device_observation(self):
        for cleanup in (False, True):
            with self.subTest(cleanup=cleanup), device.World() as w:
                w.run.cleanup_mode = cleanup
                if not cleanup:
                    w.run.device_root = None
                    w.run.device_id = None
                    w.run.guard = lambda force=False: w.run.tick()
                w.invoke()
                self.assertNotIn("device_service", w.record)

    def test_device_completion_uses_advancing_device_sample_not_derived_sample(self):
        with device.World(count=4) as w:
            def advancing(info, active):
                if active:
                    w.clock.now += .051
                return info
            w.stat_action = advancing
            w.poll_action = lambda: None if w.scanning else 0
            w.invoke()
            o = w.record["device_service"]
            self.assertGreater(o["first_completed_checkpoint_elapsed"], 0)
            self.assertGreater(o["last_completed_checkpoint_elapsed"], o["first_completed_checkpoint_elapsed"])
            self.assertLessEqual(o["last_completed_checkpoint_elapsed"], .204)
            self.assertIsNone(w.record["derived_service"]["last_completed_checkpoint_elapsed"])

    def test_zero_quanta_does_not_invent_device_service_work(self):
        with device.World(count=1) as w:
            w.invoke()
            o = w.record["device_service"]
            self.assertEqual((o["quanta_started"], o["quanta_completed"], o["polls_returned"]), (0, 0, 0))
            self.assertIsNone(o["first_completed_checkpoint_elapsed"])
            self.assertEqual(o["terminal_barrier"], {"reached": True, "completed": True})

    def test_failed_derived_error_marker_cannot_skip_device_error_marker(self):
        for phase in ("command", "accounting"):
            for secondary in (C.DeadlineFailure("secondary"), KeyboardInterrupt(), SystemExit(9)):
                with self.subTest(phase=phase, secondary=type(secondary).__name__), device.World() as w:
                    primary = C.RunFailure("original failure")
                    def fail(*args):
                        raise primary
                    if phase == "command":
                        w.selector.select.side_effect = fail
                    else:
                        w.barrier_action = fail
                    original = w.run.observe_derived_service
                    def observe(target, event, **kwargs):
                        if event == "incomplete":
                            raise secondary
                        return original(target, event, **kwargs)
                    w.run.observe_derived_service = observe
                    self.assertIs(device.failure(w.invoke), primary)
                    self.assertTrue(w.record["device_service"]["capture_incomplete"])
                    self.assertEqual(w.record["primary_error"]["message"], str(primary))
                    self.assert_finished(w)


if __name__ == "__main__":
    unittest.main()
