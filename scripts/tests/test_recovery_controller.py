"""Injected failure-boundary tests. No Xcode, simulator, CI or native grant execution."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import datetime as dt
import errno
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    "recovery_controller_under_test", Path(__file__).resolve().parents[1] / "run-recovery-journey.py"
)
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class FakeProcess:
    pid = 43210

    def __init__(self, running=False):
        self.running = running
        self.waits = 0

    def wait(self, timeout):
        self.waits += 1
        if self.running:
            raise subprocess.TimeoutExpired("fake-owned-process", timeout)
        return 0


class ControllerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="recovery-controller-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "checkout"
        self.repo.mkdir()
        self.devices = self.root / "owned-devices"
        self.devices.mkdir()
        self.clock = FakeClock()
        # Any accidental native dispatch fails the test before a child can start.
        popen = patch.object(controller.subprocess, "Popen", side_effect=AssertionError("Popen forbidden in injected test"))
        self.popen = popen.start()
        self.addCleanup(popen.stop)
        # Signal APIs are all injected; even execute() cannot arm or install a
        # real process handler while these tests are running.
        self.previous_handler = object()
        for attribute, options, handle in [
            ("getsignal", {"return_value": self.previous_handler}, "get_handler"),
            ("getitimer", {"return_value": (0.0, 0.0)}, "get_timer"),
            ("signal", {}, "handlers"),
            ("setitimer", {}, "timers"),
            ("pthread_sigmask", {"return_value": set()}, "signal_mask"),
        ]:
            replacement = patch.object(controller.signal, attribute, **options)
            setattr(self, handle, replacement.start())
            self.addCleanup(replacement.stop)

    def grant(self):
        now = dt.datetime(2026, 10, 25, tzinfo=dt.timezone.utc)
        return {
            "schema_version": 1, "native_execution_authorized": True,
            "not_before": now.isoformat(), "expires_at": (now + dt.timedelta(hours=1)).isoformat(),
            "source_commit": "a" * 40, "source_tree": "b" * 40,
            "controller_sha256": "c" * 64, "collector_sha256": "d" * 64,
            "worktree": str(self.repo), "output_root": str(self.root / "output"),
            "device_type": "com.apple.CoreSimulator.SimDeviceType.iPhone-17",
            "runtime": "com.apple.CoreSimulator.SimRuntime.iOS-27-0",
            "xcodegen_path": str(self.root / "fake-xcodegen"), "xcodegen_sha256": "e" * 64,
            "developer_dir": str(self.root / "fake-developer-dir"),
            "journey_run_id": "12345678-1234-4234-8234-123456789ABC",
        }

    def run_fixture(self, *, output=True, free=None):
        free = 24 * controller.GIB if free is None else free
        run = controller.RecoveryRun(self.grant(), clock=self.clock, disk_usage=lambda _: SimpleNamespace(free=free))
        run.device_base = self.devices
        if output:
            run.output.mkdir()
            run.owns_output = True
        return run


class OwnedGroupTests(ControllerCase):
    def test_terminal_esrch_is_sticky_and_recycled_pgid_is_never_signalled(self):
        process = FakeProcess()
        calls = []

        def absent(pgid, sig):
            calls.append((pgid, sig))
            raise ProcessLookupError(errno.ESRCH, "absent")

        state = {}
        first = controller.kill_owned(process, self.clock() + 20, state=state,
                                      clock=self.clock, sleep=self.clock.sleep, killpg=absent)
        self.assertTrue(first["success"])
        self.assertEqual(calls, [(process.pid, 0)])
        self.clock.now += 1
        recycled = Mock(side_effect=AssertionError("numeric PGID has been reused"))
        second = controller.kill_owned(process, self.clock() + 20, state=state,
                                       clock=self.clock, sleep=self.clock.sleep, killpg=recycled)
        self.assertTrue(second["success"])
        recycled.assert_not_called()
        self.assertEqual(process.waits, 1)

    def test_probe_eperm_remains_failure_even_after_absence_and_later_cleanup(self):
        process = FakeProcess()
        calls = []

        def denied_then_absent(pgid, sig):
            calls.append(sig)
            if len(calls) == 1:
                raise PermissionError(errno.EPERM, "denied")
            raise ProcessLookupError(errno.ESRCH, "now absent")

        state = {}
        result = controller.kill_owned(process, self.clock() + 10, state=state,
                                       clock=self.clock, sleep=self.clock.sleep, killpg=denied_then_absent)
        self.assertFalse(result["success"])
        self.assertEqual(state["group_state"], "absent")
        self.assertEqual(state["observation_errors"][0]["errno"], errno.EPERM)
        no_reprobe = Mock(side_effect=AssertionError("must retain terminal absence"))
        later = controller.kill_owned(process, self.clock() + 30, state=state,
                                      clock=self.clock, sleep=self.clock.sleep, killpg=no_reprobe)
        self.assertFalse(later["success"])
        no_reprobe.assert_not_called()

    def test_signal_eperm_is_not_erased_by_following_successful_probe(self):
        process = FakeProcess()
        calls = []

        def signal_denied(pgid, sig):
            calls.append(sig)
            if sig == signal.SIGTERM:
                raise PermissionError(errno.EPERM, "cannot signal")
            if len(calls) > 2:
                raise ProcessLookupError(errno.ESRCH, "gone")

        state = {}
        result = controller.kill_owned(process, self.clock() + 10, state=state,
                                       clock=self.clock, sleep=self.clock.sleep, killpg=signal_denied)
        self.assertFalse(result["success"])
        self.assertEqual(state["observation_errors"][0]["operation"], "group_signal_SIGTERM")
        self.assertNotIn(signal.SIGKILL, calls)

    def test_esrch_during_term_prevents_kill_after_leader_is_reaped(self):
        process = FakeProcess(running=True)
        calls = []

        def disappears(pgid, sig):
            calls.append(sig)
            if sig == signal.SIGTERM:
                process.running = False
                raise ProcessLookupError(errno.ESRCH, "gone")

        result = controller.kill_owned(process, self.clock() + 10, state={},
                                       clock=self.clock, sleep=self.clock.sleep, killpg=disappears)
        self.assertTrue(result["success"])
        self.assertEqual(calls, [0, signal.SIGTERM])

    def test_cleanup_retry_cannot_renew_exhausted_group_deadline(self):
        process = FakeProcess(running=True)
        probe = Mock()
        state = {}
        start = self.clock()
        first = controller.kill_owned(process, start + 100, state=state,
                                      clock=self.clock, sleep=self.clock.sleep, killpg=probe)
        self.assertFalse(first["success"])
        self.assertTrue(first["budget_exhausted"])
        self.assertEqual(state["cleanup_deadline_monotonic"], start + 4)
        original_calls = probe.call_count
        later = controller.kill_owned(process, start + 1000, state=state,
                                      clock=self.clock, sleep=self.clock.sleep, killpg=probe)
        self.assertFalse(later["success"])
        self.assertTrue(later["budget_exhausted"])
        self.assertEqual(probe.call_count, original_calls)
        self.assertEqual(self.clock(), start + 4)

    def test_expired_deadline_does_not_reap_or_probe(self):
        process = FakeProcess(running=True)
        probe = Mock()
        result = controller.kill_owned(process, self.clock(), state={}, clock=self.clock,
                                       sleep=self.clock.sleep, killpg=probe)
        self.assertFalse(result["success"])
        self.assertTrue(result["budget_exhausted"])
        self.assertEqual(process.waits, 0)
        probe.assert_not_called()


class ResourceAndDeadlineTests(ControllerCase):
    def test_insufficient_command_budget_starts_no_child_or_logs(self):
        run = self.run_fixture()
        run.guard = Mock()
        run.phase_end = self.clock() + 7.99
        with self.assertRaises(controller.DeadlineFailure):
            run.command(["never-native"], "too-late", cap=30)
        self.popen.assert_not_called()
        self.assertFalse((run.output / "logs").exists())
        self.assertEqual(run.record["commands"], [])

    def test_late_phase_cannot_extend_outer_or_cleanup_reserve(self):
        run = self.run_fixture()
        original_outer = run.outer_end
        original_work = run.work_end
        self.clock.now = run.work_end - 1
        run.phase("collect")
        self.assertEqual(run.phase_end, original_work)
        self.assertEqual(run.outer_end, original_outer)
        self.clock.now = original_work
        with self.assertRaises(controller.DeadlineFailure):
            run.tick()
        with self.assertRaises(controller.DeadlineFailure):
            run.phase("build")
        self.assertEqual(run.outer_end, original_outer)
        self.popen.assert_not_called()

    def test_existing_output_is_preserved_before_admission_or_native_work(self):
        run = self.run_fixture()
        keep = run.output / "preserved.bin"
        keep.write_bytes(b"original evidence")
        run.disk_usage = Mock(side_effect=AssertionError("should reject existing output first"))
        with self.assertRaises(controller.ConfigurationFailure):
            run.prepare()
        self.assertEqual(keep.read_bytes(), b"original evidence")
        self.assertEqual(list(run.output.iterdir()), [keep])
        self.popen.assert_not_called()
        run.disk_usage.assert_not_called()
        self.assertFalse(run.record["native_started"])

    def test_admission_rejects_just_below_24_gib_without_creating_output(self):
        run = self.run_fixture(output=False, free=24 * controller.GIB - 1)
        with self.assertRaisesRegex(controller.ConfigurationFailure, "24 GiB"):
            run.prepare()
        self.assertFalse(run.output.exists())
        self.assertFalse(run.owns_output)
        self.popen.assert_not_called()

    def test_admission_uses_both_filesystems_and_accepts_exact_24_gib(self):
        run = self.run_fixture(output=False)
        run.disk_usage = Mock(side_effect=[SimpleNamespace(free=30 * controller.GIB), SimpleNamespace(free=24 * controller.GIB - 1)])
        with self.assertRaises(controller.ConfigurationFailure):
            run.prepare()
        self.assertFalse(run.output.exists())
        run.disk_usage = Mock(return_value=SimpleNamespace(free=24 * controller.GIB))
        run.pin_sources = Mock(side_effect=controller.ConfigurationFailure("intentional source pin stop"))
        with self.assertRaisesRegex(controller.ConfigurationFailure, "intentional source pin stop"):
            run.prepare()
        self.assertTrue(run.owns_output)
        self.assertTrue(run.output.is_dir())
        self.assertFalse(run.record["native_started"])
        self.popen.assert_not_called()

    def test_runtime_abort_floor_is_8_gib_and_cleanup_still_has_time_budget(self):
        run = self.run_fixture(free=8 * controller.GIB)
        run.guard(force=True)
        run.disk_usage = Mock(return_value=SimpleNamespace(free=8 * controller.GIB - 1))
        with self.assertRaisesRegex(controller.RunFailure, "8 GiB"):
            run.guard(force=True)
        run.cleanup_mode = True
        run.disk_usage = Mock(side_effect=AssertionError("disk abort must not prevent cleanup"))
        run.guard(force=True)
        self.clock.now = run.outer_end
        with self.assertRaises(controller.DeadlineFailure):
            run.guard()

    def test_oversized_owned_output_derived_data_and_device_each_abort(self):
        for category in ("output", "derived", "device"):
            with self.subTest(category=category), tempfile.TemporaryDirectory(dir=self.root) as temp:
                run = self.run_fixture(output=False)
                run.output = Path(temp) / "out"
                run.output.mkdir()
                run.derived = run.output / "DerivedData"
                run.device_root = Path(temp) / "device"
                target = {"output": run.output, "derived": run.derived, "device": run.device_root}[category]
                target.mkdir(exist_ok=True)
                (target / "oversized").write_bytes(b"x" * 8193)
                key = {"output": "OUTPUT_CAP", "derived": "DERIVED_CAP", "device": "DEVICE_CAP"}[category]
                with patch.object(controller, key, 4096), self.assertRaisesRegex(controller.RunFailure, "byte cap"):
                    run.guard(force=True)
        self.popen.assert_not_called()

    def test_tree_size_does_not_follow_external_links_and_excludes_derived_tree(self):
        owned = self.root / "owned"
        owned.mkdir()
        external = self.root / "outside"
        external.mkdir()
        (external / "large").write_bytes(b"x" * 100_000)
        (owned / "external-link").symlink_to(external, target_is_directory=True)
        excluded = owned / "DerivedData"
        excluded.mkdir()
        (excluded / "also-large").write_bytes(b"y" * 100_000)
        result = controller.tree_size(owned, 32_768, lambda: None, excluded=(excluded,))
        self.assertEqual(result["entries"], 1)
        self.assertLess(result["logical_bytes"], 100_000)
        self.assertEqual((external / "large").stat().st_size, 100_000)

    def test_dangling_resource_root_is_not_misreported_as_zero_usage(self):
        root = self.root / "dangling"
        root.symlink_to(self.root / "missing")
        with self.assertRaises(controller.RunFailure):
            controller.tree_size(root, controller.GIB, lambda: None)

    def test_timer_rearm_uses_remaining_absolute_budget_and_expiry_does_not_renew(self):
        run = self.run_fixture()
        run.timer_enabled = True
        deadline = self.clock() + 20
        with patch.object(controller.signal, "setitimer") as timer:
            run.arm(deadline)
            self.assertEqual(timer.call_args.args, (signal.ITIMER_REAL, 20))
            self.clock.now += 5
            run.arm(deadline)
            self.assertEqual(timer.call_args.args, (signal.ITIMER_REAL, 15))
            self.clock.now = deadline
            timer.reset_mock()
            with self.assertRaises(controller.DeadlineFailure):
                run.arm(deadline)
            timer.assert_not_called()
            run.disarm()
            timer.assert_called_once_with(signal.ITIMER_REAL, 0)

    def test_xcresult_attachment_and_log_suballocations_abort_before_total_output_cap(self):
        cases = [
            ("original.xcresult", "XCRESULT_CAP"),
            ("evidence/collection/xcresult/verified.xcresult", "XCRESULT_CAP"),
            ("evidence/collection/xcresult/attachments", "ATTACHMENT_CAP"),
            ("logs", "LOG_CAP"),
        ]
        for relative, constant in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory(dir=self.root) as temp:
                run = self.run_fixture(output=False)
                run.output = Path(temp) / "out"
                run.output.mkdir()
                run.derived = run.output / "DerivedData"
                target = run.output / relative
                target.mkdir(parents=True)
                (target / "oversized").write_bytes(b"x" * 8193)
                with patch.object(controller, constant, 4096), self.assertRaisesRegex(controller.RunFailure, "byte cap"):
                    run.guard(force=True)
        self.popen.assert_not_called()

    def test_tree_at_exact_byte_cap_aborts_instead_of_allowing_another_write(self):
        root = self.root / "exact-cap"
        root.mkdir()
        payload = root / "payload"
        payload.write_bytes(b"x" * 8192)
        info = payload.stat()
        exact = max(info.st_size, info.st_blocks * 512)
        with self.assertRaisesRegex(controller.RunFailure, "byte cap"):
            controller.tree_size(root, exact, lambda: None)
        accepted = controller.tree_size(root, exact + 1, lambda: None)
        self.assertEqual(max(accepted["logical_bytes"], accepted["allocated_bytes"]), exact)

    def test_tree_scan_entry_and_time_budgets_fail_closed(self):
        root = self.root / "tree"
        root.mkdir()
        for index in range(3):
            (root / str(index)).write_bytes(b"x")
        with self.assertRaisesRegex(controller.RunFailure, "entry-count"):
            controller.tree_size(root, controller.GIB, lambda: None, max_entries=2)
        tick = Mock(side_effect=controller.DeadlineFailure("scan deadline"))
        with self.assertRaises(controller.DeadlineFailure):
            controller.tree_size(root, controller.GIB, tick)
        tick.assert_called_once()


class CommandFailureTests(ControllerCase):
    @contextmanager
    def fake_child(self, *, active=False):
        process = Mock(pid=43210)
        process.stdout.fileno.return_value = 111
        process.stderr.fileno.return_value = 112
        process.poll.return_value = None if active else 0
        process.wait.return_value = 0
        selector = Mock()
        selector.get_map.return_value = {111: object()} if active else {}
        cleanup = {"success": True, "group_state": "absent", "leader_reaped": True,
                   "returncode": 0, "errors": [], "signals": []}
        real_open = Path.open
        log_streams = []

        def open_stream(path, mode="r", *args, **kwargs):
            if mode == "xb":
                stream = Mock(name="injected-command-log")
                log_streams.append(stream)
                return stream
            return real_open(path, mode, *args, **kwargs)

        with (patch.object(controller.subprocess, "Popen", return_value=process) as start,
              patch.object(Path, "open", open_stream),
              patch.object(controller.selectors, "DefaultSelector", return_value=selector),
              patch.object(controller.os, "set_blocking"),
              patch.object(controller, "kill_owned", return_value=cleanup) as stop):
            yield SimpleNamespace(process=process, selector=selector, start=start, stop=stop,
                                  log_streams=log_streams, cleanup=cleanup)

    def test_expired_phase_skips_command_receipt_write(self):
        run = self.run_fixture()
        run.guard = Mock()
        run.flush = Mock()
        run.phase_end = self.clock() + 20
        with self.fake_child() as child:
            def cleanup_exhausts_phase(*_args, **_kwargs):
                self.clock.now = run.phase_end + 0.01
                return child.cleanup

            child.stop.side_effect = cleanup_exhausts_phase
            with self.assertRaises(controller.DeadlineFailure):
                run.command(["injected-child"], "expired-receipt", cap=20)
        run.flush.assert_called_once()  # Initial receipt only; final I/O is forbidden.
        self.assertTrue(any(e["operation"] == "command_receipt" for e in run.record["cleanup_errors"]))

    def test_one_close_consuming_deadline_skips_subsequent_closes(self):
        run = self.run_fixture()
        run.guard = Mock()
        end = self.clock() + 20
        with self.fake_child() as child:
            def close_consumes_remaining_time():
                self.clock.now = end + 0.01

            def arm_first_stream_close(_args, **_kwargs):
                child.log_streams[0].close.side_effect = close_consumes_remaining_time
                return child.process

            child.start.side_effect = arm_first_stream_close
            with self.assertRaises(controller.RunFailure):
                run.command(["injected-child"], "slow-close", cap=20)
            child.log_streams[0].close.assert_called_once()
            child.log_streams[1].close.assert_not_called()
            child.process.stdout.close.assert_not_called()
            child.process.stderr.close.assert_not_called()
            self.assertEqual(child.stop.call_args.args[1], end)
        self.assertTrue(any(e["operation"] == "stream_close" for e in run.record["cleanup_errors"]))

    def test_nested_command_is_rejected_before_dispatch_or_new_log_files(self):
        run = self.run_fixture()
        run.guard = Mock()
        with self.fake_child(active=True) as child:
            def nested_poll():
                run.command(["nested-child"], "nested", cap=20)

            with self.assertRaisesRegex(controller.ConfigurationFailure, "Nested"):
                run.command(["injected-child"], "outer", cap=20, on_poll=nested_poll)
            child.start.assert_called_once()
            child.selector.select.assert_not_called()
        self.assertEqual([record["name"] for record in run.record["commands"]], ["outer"])
        self.assertFalse((run.output / "logs/nested.stdout").exists())
        self.assertIsNone(run.command_deadline)

    def test_slow_on_poll_stops_before_reading_pipes_and_retains_original_deadline(self):
        run = self.run_fixture()
        run.guard = Mock()
        deadline = self.clock() + 20

        def slow_poll():
            self.clock.now = deadline + 1

        with self.fake_child(active=True) as child:
            with self.assertRaises(controller.DeadlineFailure):
                run.command(["injected-child"], "slow-poll", cap=20, on_poll=slow_poll)
            child.selector.select.assert_not_called()
            self.assertEqual(child.stop.call_args.args[1], deadline)
        self.assertEqual(run.record["commands"][0]["primary_error"]["type"], "DeadlineFailure")
        self.assertIsNone(run.command_deadline)

    def test_slow_guard_does_not_start_ui_poll_after_command_deadline(self):
        run = self.run_fixture()
        deadline = self.clock() + 20

        def slow_guard():
            if run.groups:
                self.clock.now = deadline + 1

        run.guard = Mock(side_effect=slow_guard)
        on_poll = Mock()
        with self.fake_child(active=True) as child:
            with self.assertRaises(controller.DeadlineFailure):
                run.command(["injected-child"], "slow-guard", cap=20, on_poll=on_poll)
            child.selector.select.assert_not_called()
            self.assertEqual(child.stop.call_args.args[1], deadline)
        on_poll.assert_not_called()

    def test_popen_error_is_retained_when_selector_close_and_receipt_also_fail(self):
        run = self.run_fixture()
        run.guard = Mock()
        original = PermissionError(errno.EPERM, "injected spawn denied")
        run.flush = Mock(side_effect=[None, OSError("receipt storage unavailable")])
        selector = Mock()
        selector.close.side_effect = OSError("selector close failed")
        with (patch.object(controller.subprocess, "Popen", side_effect=original),
              patch.object(controller.selectors, "DefaultSelector", return_value=selector),
              patch.object(controller, "kill_owned") as stop):
            with self.assertRaises(PermissionError) as caught:
                run.command(["injected-child"], "spawn-error", cap=20)
        self.assertIs(caught.exception, original)
        stop.assert_not_called()
        self.assertEqual(run.groups, [])
        self.assertEqual(run.record["commands"][0]["primary_error"]["type"], "PermissionError")
        self.assertEqual({e["operation"] for e in run.record["cleanup_errors"]},
                         {"selector_close", "command_receipt"})
        self.assertIsNone(run.command_deadline)

    def test_stream_close_failure_still_reaps_group_and_never_returns_success(self):
        run = self.run_fixture()
        run.guard = Mock()
        with self.fake_child() as child:
            child.process.stdout.close.side_effect = OSError("stdout close failed")
            with self.assertRaisesRegex(controller.RunFailure, "cleanup or receipt failed"):
                run.command(["injected-child"], "stream-close-error", cap=20)
            child.process.stderr.close.assert_called_once()
            child.stop.assert_called_once()
        self.assertTrue(any(e["operation"] == "stream_close" for e in run.record["cleanup_errors"]))

    def test_command_receipt_failure_after_exit_zero_is_not_success(self):
        run = self.run_fixture()
        run.guard = Mock()
        original = OSError("receipt fsync failed")
        run.flush = Mock(side_effect=[None, original])
        with self.fake_child() as child:
            with self.assertRaises(OSError) as caught:
                run.command(["injected-child"], "receipt-error", cap=20)
            child.stop.assert_called_once()
        self.assertIs(caught.exception, original)
        self.assertTrue(any(e["operation"] == "command_receipt" for e in run.record["cleanup_errors"]))

    def test_initial_receipt_error_starts_no_process(self):
        run = self.run_fixture()
        run.guard = Mock()
        run.flush = Mock(side_effect=OSError("initial receipt unavailable"))
        with self.assertRaises(OSError):
            run.command(["injected-child"], "initial-receipt-error", cap=20)
        self.assertEqual(run.groups, [])
        self.popen.assert_not_called()

    def test_primary_guard_error_survives_uncertain_process_cleanup(self):
        run = self.run_fixture()
        original = controller.DeadlineFailure("primary command deadline")
        def abort_after_registration():
            if run.groups:
                raise original

        run.guard = Mock(side_effect=abort_after_registration)
        process = Mock(pid=43210)
        process.stdout.fileno.return_value = 111
        process.stderr.fileno.return_value = 112
        process.poll.return_value = None
        selector = Mock()
        selector.get_map.return_value = {111: object()}
        cleanup = {"success": False, "group_state": "unknown", "leader_reaped": False,
                   "errors": [{"errno": errno.EPERM}], "signals": []}
        with (patch.object(controller.subprocess, "Popen", return_value=process) as start,
              patch.object(controller.selectors, "DefaultSelector", return_value=selector),
              patch.object(controller.os, "set_blocking"),
              patch.object(controller, "kill_owned", return_value=cleanup) as stop):
            with self.assertRaises(controller.DeadlineFailure) as caught:
                run.command(["injected-child"], "injected-command", cap=20)
        self.assertIs(caught.exception, original)
        self.assertTrue(start.call_args.kwargs["start_new_session"])
        stop.assert_called_once()
        self.assertIs(stop.call_args.kwargs["state"], run.groups[0]["state"])
        self.assertEqual(run.record["commands"][0]["primary_error"]["message"], str(original))
        self.assertFalse(run.record["commands"][0]["cleanup"]["success"])
        self.assertTrue(run.record["cleanup_errors"])
        self.assertIsNone(run.command_deadline)
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()
        self.popen.assert_not_called()

    def test_successful_exit_with_unconfirmed_group_is_still_failure(self):
        run = self.run_fixture()
        run.guard = Mock()
        process = Mock(pid=43210)
        process.stdout.fileno.return_value = 111
        process.stderr.fileno.return_value = 112
        process.poll.return_value = 0
        process.wait.return_value = 0
        selector = Mock()
        selector.get_map.return_value = {}
        cleanup = {"success": False, "group_state": "unknown", "leader_reaped": True,
                   "errors": [{"errno": errno.EPERM}], "signals": []}
        with (patch.object(controller.subprocess, "Popen", return_value=process),
              patch.object(controller.selectors, "DefaultSelector", return_value=selector),
              patch.object(controller.os, "set_blocking"),
              patch.object(controller, "kill_owned", return_value=cleanup)):
            with self.assertRaisesRegex(controller.RunFailure, "cleanup uncertain"):
                run.command(["injected-child"], "uncertain-command", cap=20)
        self.assertTrue(run.record["cleanup_errors"])
        self.popen.assert_not_called()


class SourceAndGrantTests(ControllerCase):
    def test_grant_expiry_and_source_path_pins_are_validated_without_execution(self):
        now = dt.datetime(2026, 10, 25, tzinfo=dt.timezone.utc)
        grant = self.grant()
        self.assertIs(controller.validate_grant(grant, now=now, script_root=self.repo), grant)
        mutations = [
            {"native_execution_authorized": False}, {"native_execution_authorized": 1},
            {"expires_at": (now + dt.timedelta(seconds=1799)).isoformat()},
            {"not_before": (now + dt.timedelta(seconds=1)).isoformat()},
            {"expires_at": "2026-10-25T01:00:00"}, {"source_tree": "B" * 40},
            {"collector_sha256": "short"}, {"worktree": str(self.root / "other")},
            {"journey_run_id": grant["journey_run_id"].lower()}, {"unexpected": True},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(controller.ConfigurationFailure):
                controller.validate_grant({**grant, **mutation}, now=now, script_root=self.repo)
        self.popen.assert_not_called()

    def test_source_commit_tree_or_dirty_checkout_stops_before_tools(self):
        run = self.run_fixture()
        for output in [b"wrong\nwrong\n", (run.grant["source_commit"] + "\n" + "f" * 40 + "\n").encode()]:
            run.command = Mock(return_value=output)
            with self.assertRaisesRegex(controller.ConfigurationFailure, "commit/tree"):
                run.pin_sources()
            self.assertEqual(run.command.call_count, 1)
        head = (run.grant["source_commit"] + "\n" + run.grant["source_tree"] + "\n").encode()
        run.command = Mock(side_effect=[head, b" M App/RoomInventoryApp.swift\n"])
        with self.assertRaisesRegex(controller.ConfigurationFailure, "clean"):
            run.pin_sources()
        self.assertEqual(run.command.call_count, 2)
        self.assertFalse((run.output / "source-pin.json").exists())
        self.popen.assert_not_called()

    def test_changed_controller_pin_stops_before_generator_or_fixture(self):
        run = self.run_fixture()
        scripts = run.repo / "scripts"
        scripts.mkdir()
        (scripts / "run-recovery-journey.py").write_bytes(b"changed controller")
        head = (run.grant["source_commit"] + "\n" + run.grant["source_tree"] + "\n").encode()
        run.command = Mock(side_effect=[head, b"", b"tree listing"])
        with self.assertRaisesRegex(controller.ConfigurationFailure, "Executable source pin"):
            run.pin_sources()
        self.assertEqual(run.command.call_count, 3)
        self.assertFalse((run.output / "source-pin.json").exists())

    def test_changed_xctestrun_is_rejected_before_ui_dispatch(self):
        run = self.run_fixture()
        run.xctestrun = run.output / "selected.xctestrun"
        run.xctestrun.write_bytes(b"changed selection")
        run.xctestrun_sha = controller.sha(b"approved selection")
        run.collector = Mock()
        run.pin_sources = Mock()
        run.command = Mock(side_effect=AssertionError("changed configuration must not execute"))
        with self.assertRaises(controller.ConfigurationFailure):
            run.test_and_collect()
        run.command.assert_not_called()
        run.collector.poll_bridge.assert_not_called()


class XctestrunTests(ControllerCase):
    def generated(self):
        return {
            "__xctestrun_metadata__": {"FormatVersion": 2},
            "TestConfigurations": [{"Name": "Generated", "TestTargets": [
                {"BlueprintName": "RoomInventoryTests", "TestHostPath": "unit-host"},
                {"BlueprintName": "RoomInventoryUITests", "IsUITestBundle": True,
                 "UITargetAppBundleIdentifier": controller.BUNDLE,
                 "TestHostBundleIdentifier": controller.RUNNER_BUNDLE,
                 "TestHostPath": "__TESTROOT__/Debug-iphonesimulator/RoomInventoryUITests-Runner.app",
                 "UITargetAppPath": "__TESTROOT__/Debug-iphonesimulator/RoomInventory.app",
                 "TestBundlePath": "__TESTHOST__/PlugIns/RoomInventoryUITests.xctest",
                 "EnvironmentVariables": {"GENERATED_VALUE": "keep"},
                 "UITargetAppEnvironmentVariables": {"APP_GENERATED": "keep"},
                 "OnlyTestIdentifiers": ["WrongTests/testCommerce"],
                 "SkipTestIdentifiers": ["InventoryRecoveryJourneyTests"],
                 "ParallelizationEnabled": True, "UseDestinationArtifacts": False},
            ]}],
        }

    def ids(self):
        return {"journey_run_id": "11111111-1111-4111-8111-111111111111",
                "source_run_id": "22222222-2222-4222-8222-222222222222",
                "target_run_id": "33333333-3333-4333-8333-333333333333"}

    def test_one_case_no_parallel_and_destination_artifacts_pin_installed_bundles(self):
        result = controller.configure_xctestrun(self.generated(), self.ids())
        targets = result["TestConfigurations"][0]["TestTargets"]
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target["OnlyTestIdentifiers"], [controller.CASE.split("/", 1)[1]])
        self.assertEqual(target["SkipTestIdentifiers"], [])
        self.assertIs(target["ParallelizationEnabled"], False)
        self.assertIs(target["UseDestinationArtifacts"], True)
        self.assertNotIn("TestHostPath", target)
        self.assertNotIn("TestBundlePath", target)
        self.assertNotIn("UITargetAppPath", target)
        self.assertEqual(target["TestBundleDestinationRelativePath"], "__TESTHOST__/PlugIns/RoomInventoryUITests.xctest")
        self.assertEqual(target["TestHostBundleIdentifier"], controller.RUNNER_BUNDLE)
        self.assertEqual(target["UITargetAppBundleIdentifier"], controller.BUNDLE)
        self.assertEqual(target["SystemAttachmentLifetime"], "keepAlways")
        self.assertEqual(target["UserAttachmentLifetime"], "keepAlways")
        self.assertEqual(target["EnvironmentVariables"]["GENERATED_VALUE"], "keep")
        self.assertEqual(target["EnvironmentVariables"]["RECOVERY_SOURCE_RUN_ID"], self.ids()["source_run_id"])
        self.assertEqual(target["EnvironmentVariables"]["RUN_INVENTORY_RECOVERY_JOURNEY"], "1")
        self.assertEqual(target["UITargetAppEnvironmentVariables"], {"APP_GENERATED": "keep"})
        self.assertEqual((target["TestLanguage"], target["TestRegion"]), ("en", "US"))

    def test_commerce_settings_are_rejected_even_inside_discarded_target(self):
        for key, value in [("StoreKitConfigurationFileReference", "anything"), ("Other", "path/LOCAL.STOREKIT")]:
            generated = self.generated()
            generated["TestConfigurations"][0]["TestTargets"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(controller.ConfigurationFailure, "StoreKit"):
                controller.configure_xctestrun(generated, self.ids())

    def test_ambiguous_targets_or_preexisting_opt_in_cannot_widen_test_scope(self):
        for mutation in ("duplicate", "configurations", "test-env", "app-env", "wrong-app"):
            value = self.generated()
            config = value["TestConfigurations"][0]
            target = config["TestTargets"][1]
            if mutation == "duplicate":
                config["TestTargets"].append(deepcopy(target))
            elif mutation == "configurations":
                value["TestConfigurations"].append(deepcopy(config))
            elif mutation == "test-env":
                target["EnvironmentVariables"]["RECOVERY_SOURCE_RUN_ID"] = "stale"
            elif mutation == "app-env":
                target["UITargetAppEnvironmentVariables"]["UITEST_RUN_ID"] = "stale"
            else:
                target["TestHostBundleIdentifier"] = "foreign.runner"
            with self.subTest(mutation=mutation), self.assertRaises(controller.ConfigurationFailure):
                controller.configure_xctestrun(value, self.ids())


class ActiveTimerTests(ControllerCase):
    def staged_run(self):
        run = self.run_fixture()
        for name in ("prepare", "build", "prepare_device", "test_and_collect", "cleanup"):
            setattr(run, name, Mock())
        return run

    def test_execute_arms_timer_and_restores_previous_handler_after_success(self):
        run = self.staged_run()
        self.assertEqual(run.execute(), 0)
        installed = self.handlers.call_args_list[0].args
        self.assertEqual(installed[0], signal.SIGALRM)
        self.assertTrue(callable(installed[1]))
        self.assertEqual(self.handlers.call_args_list[-1].args, (signal.SIGALRM, self.previous_handler))
        timer_values = [call.args[1] for call in self.timers.call_args_list]
        self.assertTrue(any(value > 0 for value in timer_values))
        self.assertEqual(timer_values[-1], 0)
        self.assertFalse(run.timer_enabled)
        self.assertTrue(run.record["requires_process_exit_code_zero"])
        self.popen.assert_not_called()

    def test_existing_active_timer_is_rejected_without_overwriting_it(self):
        run = self.staged_run()
        self.get_timer.return_value = (12.0, 0.0)
        with self.assertRaisesRegex(controller.ConfigurationFailure, "timer is active"):
            run.execute()
        run.prepare.assert_not_called()
        self.handlers.assert_not_called()
        self.timers.assert_not_called()
        self.assertFalse(run.timer_enabled)

    def test_injected_sigalrm_becomes_deadline_failure_and_handler_is_restored(self):
        run = self.staged_run()

        def alarm_during_prepare():
            callback = self.handlers.call_args_list[0].args[1]
            callback(signal.SIGALRM, None)

        run.prepare.side_effect = alarm_during_prepare
        self.assertEqual(run.execute(), 124)
        self.assertEqual(run.record["primary_error"]["type"], "DeadlineFailure")
        run.build.assert_not_called()
        run.cleanup.assert_called_once()
        self.assertEqual(self.handlers.call_args_list[-1].args, (signal.SIGALRM, self.previous_handler))
        self.assertFalse(run.timer_enabled)

    def test_cleanup_exception_preserves_primary_error_and_exit_code(self):
        run = self.staged_run()
        original = controller.ConfigurationFailure("source identity changed")
        run.prepare.side_effect = original
        run.cleanup.side_effect = OSError("cleanup receipt write failed")
        self.assertEqual(run.execute(), original.exit_code)
        self.assertEqual(run.record["primary_error"]["message"], str(original))
        self.assertTrue(any(e["operation"] == "cleanup" for e in run.record["cleanup_errors"]))
        self.assertEqual(run.record["status"], "FAIL")
        self.assertEqual(self.handlers.call_args_list[-1].args, (signal.SIGALRM, self.previous_handler))

    def test_cleanup_exception_after_success_prevents_zero_exit(self):
        run = self.staged_run()
        run.cleanup.side_effect = OSError("shutdown observation unavailable")
        self.assertNotEqual(run.execute(), 0)
        self.assertEqual(run.record["status"], "FAIL")
        self.assertIsNone(run.record["primary_error"])
        self.assertTrue(run.record["cleanup_errors"])

    def test_final_flush_crossing_outer_deadline_never_returns_zero(self):
        run = self.staged_run()
        provisional = []

        def late_flush():
            provisional.append(deepcopy(run.record))
            self.clock.now = run.outer_end + 0.01

        run.flush = Mock(side_effect=late_flush)
        self.assertEqual(run.execute(), 124)
        self.assertEqual(len(provisional), 1)
        self.assertTrue(provisional[0]["requires_process_exit_code_zero"])
        self.assertEqual(run.record["status"], "FAIL")
        self.assertEqual(run.record["finalization_error"]["type"], "DeadlineFailure")
        self.assertFalse(run.timer_enabled)
        self.assertEqual(self.handlers.call_args_list[-1].args, (signal.SIGALRM, self.previous_handler))

    def test_final_flush_storage_error_never_returns_zero_and_restores_timer(self):
        run = self.staged_run()
        run.flush = Mock(side_effect=OSError("final fsync denied"))
        self.assertNotEqual(run.execute(), 0)
        self.assertEqual(run.record["status"], "FAIL")
        self.assertEqual(run.record["finalization_error"]["message"], "final fsync denied")
        self.assertFalse(run.timer_enabled)
        self.assertEqual(self.timers.call_args.args, (signal.ITIMER_REAL, 0))


class FailurePreservationTests(ControllerCase):
    def test_failed_cleanup_listing_still_attempts_owned_shutdown_and_final_state(self):
        run = self.run_fixture()
        run.device_id = "44444444-4444-4444-8444-444444444444"
        run.device_root = self.devices / run.device_id
        run.device_root.mkdir()
        names = []

        def command(_args, name, **_kwargs):
            names.append(name)
            if name == "device-cleanup-before":
                raise controller.RunFailure("listing failed")
            if name == "device-final-state":
                return json.dumps({"devices": {"runtime": [{"udid": run.device_id, "state": "Shutdown"}]}}).encode()
            return b""

        run.command = command
        run.cleanup()
        self.assertIn("shutdown-owned-device", names)
        self.assertIn("device-final-state", names)
        self.assertEqual(run.record.get("device_final_state"), "Shutdown")
        self.assertTrue(run.record["cleanup_errors"], "Earlier cleanup failure stays sticky")
        self.assertTrue(run.device_root.is_dir())

    def test_test_failure_is_primary_when_xcresult_capture_also_fails(self):
        run = self.run_fixture()
        run.device_id = "44444444-4444-4444-8444-444444444444"
        run.xctestrun = run.output / "selected.xctestrun"
        run.xctestrun.write_bytes(b"approved selection")
        run.xctestrun_sha = controller.sha(run.xctestrun.read_bytes())
        original = controller.RunFailure("primary UI failure")
        run.command = Mock(side_effect=original)
        run.pin_sources = Mock()
        run.collector = Mock()
        run.collector.capture_xcresult.side_effect = OSError("result copy failed")
        with self.assertRaises(controller.RunFailure) as caught:
            run.test_and_collect()
        self.assertIs(caught.exception, original)
        self.assertIn("result copy failed", str(run.record.get("preservation_error")))
        run.collector.collect.assert_not_called()

    def test_collection_phase_timeout_does_not_replace_primary_test_failure(self):
        run = self.run_fixture()
        run.device_id = "44444444-4444-4444-8444-444444444444"
        run.xctestrun = run.output / "selected.xctestrun"
        run.xctestrun.write_bytes(b"approved selection")
        run.xctestrun_sha = controller.sha(run.xctestrun.read_bytes())
        original = controller.RunFailure("primary UI failure")
        run.command = Mock(side_effect=original)
        run.pin_sources = Mock()
        run.collector = Mock()
        run.phase = Mock(side_effect=[None, controller.DeadlineFailure("collection phase expired")])
        with self.assertRaises(controller.RunFailure) as caught:
            run.test_and_collect()
        self.assertIs(caught.exception, original)
        run.collector.collect.assert_not_called()

    def test_execute_retains_primary_error_when_cleanup_is_uncertain(self):
        run = self.run_fixture()
        original = controller.ConfigurationFailure("primary source mismatch")
        run.prepare = Mock(side_effect=original)
        run.build = Mock(side_effect=AssertionError("must not build"))
        run.prepare_device = Mock(side_effect=AssertionError("must not prepare device"))
        run.test_and_collect = Mock(side_effect=AssertionError("must not test"))

        def cleanup():
            run.record["cleanup_errors"].append({"injected": "cannot confirm owned group exit"})

        run.cleanup = Mock(side_effect=cleanup)
        # The timer only observes time in production; it is not needed by an
        # entirely injected orchestration failure that launches no processes.
        with patch.object(controller.signal, "setitimer"), patch.object(controller.signal, "signal"):
            code = run.execute()
        self.assertEqual(code, original.exit_code)
        self.assertEqual(run.record["primary_error"]["message"], "primary source mismatch")
        self.assertTrue(run.record["cleanup_errors"])
        self.assertEqual(run.record["status"], "FAIL")
        run.build.assert_not_called()
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
