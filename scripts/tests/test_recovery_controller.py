"""Injected failure-boundary tests. No Xcode, simulator, CI or native grant execution."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import datetime as dt
import errno
import importlib.util
import json
import plistlib
from pathlib import Path
import signal
import stat
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


def resource_info(size=0, blocks=0, mode=stat.S_IFREG, inode=1):
    return SimpleNamespace(st_size=size, st_blocks=blocks, st_mode=mode,
                           st_dev=1, st_ino=inode)


@contextmanager
def injected_resource_tree(trees, *, root_infos=None):
    """Injected root/DirEntry metadata only: no real allocation, walk or stat."""
    entries = {}
    root_infos = {} if root_infos is None else root_infos
    for root, children in trees.items():
        for name, info in children:
            entry = SimpleNamespace(path=str(root / name), stat=Mock(return_value=info))
            entries[Path(entry.path)] = entry

    @contextmanager
    def scan(root):
        yield iter(entries[Path(root) / name] for name, _ in trees.get(Path(root), []))

    with (patch.object(Path, "exists", return_value=True),
          patch.object(Path, "is_dir", return_value=True),
          patch.object(Path, "is_symlink", return_value=False),
          patch.object(Path, "stat", side_effect=AssertionError("extra stat forbidden")) as extra_stat,
          patch.object(Path, "lstat", autospec=True,
                       side_effect=lambda path: root_infos.get(path, resource_info(mode=stat.S_IFDIR))) as extra_lstat,
          patch.object(controller.os, "scandir", side_effect=scan) as scans):
        yield SimpleNamespace(entries=entries, scans=scans, extra_stat=extra_stat, extra_lstat=extra_lstat)


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
        process = FakeProcess(running=True)
        calls = []

        def signal_denied(pgid, sig):
            calls.append(sig)
            if sig == signal.SIGTERM:
                raise PermissionError(errno.EPERM, "cannot signal")
            if len(calls) > 2:
                process.running = False
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
                run.device_base = Path(temp)
                run.device_id = "44444444-4444-4444-8444-444444444444"
                run.device_root = run.device_base / run.device_id
                run.device_root.mkdir()
                run.bind_device_resource_root()
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


class ResourceCapObservationTests(ControllerCase):
    def crossing(self, run, root, cap, category="derived_data", **kwargs):
        with self.assertRaises(controller.RunFailure) as caught:
            run.resource_size(category, root, cap, **kwargs)
        self.assertIs(type(caught.exception), controller.RunFailure)
        self.assertEqual(str(caught.exception), "Owned resource byte cap reached: " + str(root))
        return run.record.get("resource_cap_crossing")

    def test_logical_equality_crossing_is_partial_and_uses_already_read_info(self):
        run = self.run_fixture()
        run.tick = Mock()
        run.disk_usage = Mock(side_effect=AssertionError("extra disk query forbidden"))
        info = resource_info(size=1024, blocks=0)
        with injected_resource_tree({run.derived: [("sparse", info)]}) as tree:
            observation = self.crossing(run, run.derived, 1024)
            tree.scans.assert_called_once_with(run.derived)
            tree.entries[run.derived / "sparse"].stat.assert_called_once_with(follow_symlinks=False)
            tree.extra_stat.assert_not_called()
            tree.extra_lstat.assert_not_called()
        self.assertEqual(run.tick.call_count, 2)  # Existing directory and entry ticks only.
        run.disk_usage.assert_not_called()
        self.popen.assert_not_called()
        self.assertEqual(observation["traversal"], "partial")
        self.assertEqual(observation["category"], "derived_data")
        self.assertEqual((observation["cap_bytes"], observation["logical_bytes"], observation["allocated_bytes"], observation["entries"]),
                         (1024, 1024, 0, 1))
        self.assertEqual(observation["current_entry"]["type"], "regular_file")
        self.assertEqual(observation["current_entry"]["size_bytes"], 1024)
        self.assertEqual(observation["current_entry"]["blocks_512"], 0)

    def test_allocated_directory_equality_crosses_without_counting_directory_size_or_descending(self):
        run = self.run_fixture()
        directory = resource_info(size=99999, blocks=2, mode=stat.S_IFDIR)
        child = run.derived / "directory"
        with injected_resource_tree({run.derived: [("directory", directory)], child: [("never-read", resource_info(1))]}) as tree:
            observation = self.crossing(run, run.derived, 1024)
            tree.scans.assert_called_once_with(run.derived)
            tree.entries[child / "never-read"].stat.assert_not_called()
        self.assertEqual((observation["logical_bytes"], observation["allocated_bytes"]), (0, 1024))
        self.assertEqual(observation["current_entry"]["type"], "directory")
        self.assertEqual(observation["current_entry"]["size_bytes"], 99999)

    def test_crossing_accumulates_prior_entries_and_stops_before_next_entry(self):
        run = self.run_fixture()
        first, second, third = resource_info(4), resource_info(6), resource_info(999)
        with injected_resource_tree({run.derived: [("first", first), ("second", second), ("third", third)]}) as tree:
            observation = self.crossing(run, run.derived, 10)
            tree.entries[run.derived / "first"].stat.assert_called_once_with(follow_symlinks=False)
            tree.entries[run.derived / "second"].stat.assert_called_once_with(follow_symlinks=False)
            tree.entries[run.derived / "third"].stat.assert_not_called()
        self.assertEqual((observation["logical_bytes"], observation["entries"]), (10, 2))
        self.assertEqual(observation["current_entry"]["relative_path"], "second")
        self.assertEqual(observation["current_entry"]["size_bytes"], 6)

    def test_symlink_is_counted_without_following_its_target(self):
        run = self.run_fixture()
        with injected_resource_tree({run.derived: [("external-link", resource_info(8, 0, stat.S_IFLNK))]}) as tree:
            observation = self.crossing(run, run.derived, 8)
            tree.scans.assert_called_once_with(run.derived)
            tree.entries[run.derived / "external-link"].stat.assert_called_once_with(follow_symlinks=False)
        self.assertEqual(observation["current_entry"]["type"], "symlink")
        self.assertEqual(observation["logical_bytes"], 8)

    def test_hardlinks_keep_existing_per_entry_allocation_accounting(self):
        run = self.run_fixture()
        same_inode = resource_info(7, 1, inode=101)
        with injected_resource_tree({run.derived: [("original", same_inode), ("hardlink", same_inode)]}):
            observation = self.crossing(run, run.derived, 1024)
        self.assertEqual((observation["logical_bytes"], observation["allocated_bytes"], observation["entries"]), (14, 1024, 2))

    def test_sparse_file_keeps_logical_length_even_when_no_blocks_are_allocated(self):
        run = self.run_fixture()
        with injected_resource_tree({run.derived: [("sparse", resource_info(controller.GIB, 0))]}):
            observation = self.crossing(run, run.derived, controller.GIB)
        self.assertEqual(observation["logical_bytes"], controller.GIB)
        self.assertEqual(observation["allocated_bytes"], 0)

    def test_excluded_entry_is_not_statted_counted_or_descended(self):
        run = self.run_fixture()
        excluded = run.output / "DerivedData"
        run.tick = Mock()
        with injected_resource_tree({run.output: [("DerivedData", resource_info(99999, 999, stat.S_IFDIR)),
                                                  ("kept", resource_info(3))]}) as tree:
            observation = self.crossing(run, run.output, 3, "output", excluded=(excluded,))
            tree.entries[excluded].stat.assert_not_called()
            tree.scans.assert_called_once_with(run.output)
        self.assertEqual(observation["entries"], 1)
        self.assertEqual(observation["allocated_bytes"], 0)
        self.assertEqual(run.tick.call_count, 3)

    def test_callback_gets_exact_already_read_metadata_only_on_byte_crossing(self):
        root = self.root / "virtual"
        info = resource_info(11, 0)
        callback, tick = Mock(), Mock()
        with injected_resource_tree({root: [("entry", info)]}):
            with self.assertRaises(controller.RunFailure):
                controller.tree_size(root, 11, tick, on_cap=callback)
        callback.assert_called_once_with(root, 11, 11, 0, 1, root / "entry", info)
        self.assertIs(callback.call_args.args[-1], info)
        self.assertEqual(tick.call_count, 2)
        callback.reset_mock()
        with injected_resource_tree({root: [("entry", info)]}):
            self.assertEqual(controller.tree_size(root, 12, lambda: None, on_cap=callback)["logical_bytes"], 11)
        callback.assert_not_called()

    def test_entry_count_and_deadline_failures_do_not_create_byte_crossing_observations(self):
        root = self.root / "virtual"
        for mode in ("entry", "deadline"):
            callback = Mock()
            tick = Mock(side_effect=[None, controller.DeadlineFailure("scan expired")]) if mode == "deadline" else Mock()
            with self.subTest(mode=mode), injected_resource_tree({root: [("large", resource_info(999))]}) as tree:
                with self.assertRaises(controller.RunFailure) as caught:
                    controller.tree_size(root, 1, tick, max_entries=0 if mode == "entry" else 10, on_cap=callback)
                self.assertIn("entry-count" if mode == "entry" else "scan expired", str(caught.exception))
                callback.assert_not_called()
                if mode == "deadline":
                    tree.entries[root / "large"].stat.assert_not_called()

    def test_callback_base_exceptions_preserve_original_failure_type_and_message(self):
        root = self.root / "virtual"
        for secondary in (ValueError("format failed"), KeyboardInterrupt("cancel formatting"), SystemExit(91)):
            with self.subTest(secondary=type(secondary).__name__), injected_resource_tree({root: [("entry", resource_info(1))]}):
                with self.assertRaises(controller.RunFailure) as caught:
                    controller.tree_size(root, 1, lambda: None, on_cap=Mock(side_effect=secondary))
            self.assertIs(type(caught.exception), controller.RunFailure)
            self.assertEqual(str(caught.exception), "Owned resource byte cap reached: " + str(root))

    def test_first_observation_is_retained_after_later_crossings(self):
        run = self.run_fixture()
        with injected_resource_tree({run.derived: [("first", resource_info(10))], run.output: [("later", resource_info(20))]}):
            first = self.crossing(run, run.derived, 10)
            self.crossing(run, run.output, 20, "output")
        self.assertTrue(run.resource_cap_observed)
        self.assertIs(run.record["resource_cap_crossing"], first)
        self.assertEqual(first["current_entry"]["relative_path"], "first")

    def test_failed_first_formatting_claims_slot_and_is_never_retried(self):
        run = self.run_fixture()
        with injected_resource_tree({run.derived: [("too-wide-integer", resource_info(1 << 128))],
                                     run.output: [("later-valid", resource_info(2))]}):
            self.assertIsNone(self.crossing(run, run.derived, 1))
            self.assertTrue(run.resource_cap_observed)
            self.assertIsNone(self.crossing(run, run.output, 2, "output"))
        self.assertNotIn("resource_cap_crossing", run.record)

    def test_128_bit_integer_boundary_is_serialized_within_whole_wrapper_cap(self):
        run = self.run_fixture()
        value = (1 << 128) - 1
        with injected_resource_tree({run.derived: [("max-integer", resource_info(value))]}):
            observation = self.crossing(run, run.derived, value)
        self.assertEqual(observation["logical_bytes"], value)
        raw = json.dumps({"resource_cap_crossing": observation}, indent=2, ensure_ascii=True, allow_nan=False).encode("ascii")
        self.assertLessEqual(len(raw), 4096)

    def test_hostile_unicode_and_surrogate_path_is_escaped_relative_and_bounded(self):
        run = self.run_fixture()
        name = "\x1b[31m\n\r\t\\\u202e\ud800\U0001f600" + "界" * 300
        with injected_resource_tree({run.derived: [(name, resource_info(1))]}):
            observation = self.crossing(run, run.derived, 1)
        entry = observation["current_entry"]
        self.assertTrue(entry["path_truncated"])
        self.assertEqual(entry["path_encoding"], "unicode_escape")
        self.assertTrue(entry["relative_path"].isascii())
        self.assertLessEqual(len(entry["relative_path"]), 1024)
        self.assertEqual(entry["relative_path"], name[:256].encode("unicode_escape").decode("ascii")[:1024])
        self.assertNotIn("\n", entry["relative_path"])
        self.assertNotIn("\x1b", entry["relative_path"])
        self.assertNotIn(str(run.derived), entry["relative_path"])
        self.assertLessEqual(len(json.dumps({"resource_cap_crossing": observation}, indent=2, ensure_ascii=True).encode("ascii")), 4096)

    def test_serialization_error_or_cancellation_never_replaces_cap_failure(self):
        for secondary in (TypeError("cannot serialize"), KeyboardInterrupt("cancel serialization")):
            run = self.run_fixture(output=False)
            with self.subTest(secondary=type(secondary).__name__), injected_resource_tree({run.derived: [("entry", resource_info(1))]}), \
                    patch.object(controller.json, "dumps", side_effect=secondary):
                self.assertIsNone(self.crossing(run, run.derived, 1))
                self.assertTrue(run.resource_cap_observed)

    def test_oversized_serialized_observation_is_discarded_without_changing_cap_failure(self):
        run = self.run_fixture()
        with injected_resource_tree({run.derived: [("entry", resource_info(1))]}), \
                patch.object(controller.json, "dumps", return_value="x" * 4097):
            self.assertIsNone(self.crossing(run, run.derived, 1))
        self.assertTrue(run.resource_cap_observed)

    def test_relative_path_formatting_error_preserves_cap_failure(self):
        run = self.run_fixture()
        with injected_resource_tree({run.derived: [("entry", resource_info(1))]}), \
                patch.object(Path, "relative_to", side_effect=ValueError("bad relative path")):
            self.assertIsNone(self.crossing(run, run.derived, 1))
        self.assertTrue(run.resource_cap_observed)

    def test_guard_records_derived_category_without_a_failure_path_write_or_extra_disk_query(self):
        run = self.run_fixture()
        run.disk_usage = Mock(return_value=SimpleNamespace(free=24 * controller.GIB))
        with injected_resource_tree({run.output: [("DerivedData", resource_info(0, 0, stat.S_IFDIR))],
                                     run.derived: [("crossing", resource_info(1, controller.DERIVED_CAP // 512))]}) as tree, \
                patch.object(controller, "write_json") as write:
            with self.assertRaises(controller.RunFailure):
                run.guard(force=True)
            tree.entries[run.derived].stat.assert_not_called()  # Excluded during output scan.
            self.assertEqual(tree.scans.call_args_list, [((run.output,),), ((run.derived,),)])
            write.assert_not_called()
        self.assertEqual(run.disk_usage.call_count, 2)
        self.assertEqual(run.record["resource_cap_crossing"]["category"], "derived_data")
        self.assertEqual(run.record["resource_cap_crossing"]["cap_metric"], "allocated")
        self.assertEqual(run.last_samples, [])
        self.popen.assert_not_called()


class DerivedDataAccountingTests(ControllerCase):
    def test_empty_root_allocation_is_charged_without_inventing_logical_content(self):
        run = self.run_fixture()
        info = resource_info(99999, 2, stat.S_IFDIR)
        with injected_resource_tree({run.derived: []}, root_infos={run.derived: info}) as tree:
            total = run.resource_size("derived_data", run.derived, 4096, cap_metric="allocated")
        self.assertEqual(total, {"logical_bytes": 0, "allocated_bytes": 1024,
                                 "entries": 0, "cap_metric": "allocated"})
        tree.extra_lstat.assert_called_once_with(run.derived)
        tree.scans.assert_called_once_with(run.derived)

    def test_root_only_equality_and_overage_cross_before_scandir_with_partial_receipt(self):
        for blocks in (8, 9):
            run = self.run_fixture(output=False)
            info = resource_info(99999, blocks, stat.S_IFDIR)
            with self.subTest(blocks=blocks), injected_resource_tree({run.derived: []}, root_infos={run.derived: info}) as tree, \
                    patch.object(controller, "DERIVED_CAP", 4096), patch.object(controller, "write_json") as write:
                with self.assertRaisesRegex(controller.RunFailure, "byte cap"):
                    run.guard(force=True)
            observation = run.record["resource_cap_crossing"]
            self.assertEqual(observation["cap_metric"], "allocated")
            self.assertEqual((observation["logical_bytes"], observation["allocated_bytes"], observation["entries"]),
                             (0, blocks * 512, 0))
            self.assertEqual(observation["traversal"], "partial")
            self.assertEqual(observation["current_entry"], {
                "relative_path": ".", "path_encoding": "unicode_escape", "path_truncated": False,
                "type": "directory", "size_bytes": 99999, "blocks_512": blocks})
            tree.extra_lstat.assert_called_once_with(run.derived)
            tree.scans.assert_called_once_with(run.output)
            self.assertEqual(run.last_samples, [])
            write.assert_not_called()

    def test_unknown_empty_root_allocation_fails_before_traversal(self):
        missing = resource_info(mode=stat.S_IFDIR)
        del missing.st_blocks
        infos = [missing] + [resource_info(0, value, stat.S_IFDIR)
                             for value in (None, -1, True, False, 1.0, float("nan"), "8", object())]
        run = self.run_fixture()
        for info in infos:
            with self.subTest(blocks=getattr(info, "st_blocks", "missing")), \
                    injected_resource_tree({run.derived: []}, root_infos={run.derived: info}) as tree:
                with self.assertRaisesRegex(controller.ResourceAccountingFailure, "accounting unavailable"):
                    run.resource_size("derived_data", run.derived, controller.DERIVED_CAP, cap_metric="allocated")
            tree.extra_lstat.assert_called_once_with(run.derived)
            tree.scans.assert_not_called()
            self.assertNotIn("resource_cap_crossing", run.record)

    def test_root_allocation_is_added_to_children_and_remeasured_on_later_sample(self):
        run = self.run_fixture()
        info = resource_info(99999, 2, stat.S_IFDIR)
        with injected_resource_tree({run.derived: [("child", resource_info(1, 2))]}, root_infos={run.derived: info}) as tree, \
                patch.object(controller, "DERIVED_CAP", 4096), patch.object(controller, "write_json"):
            run.guard(force=True)
            self.assertEqual(run.last_samples[0]["derived_data"]["allocated_bytes"], 2048)
            info.st_blocks = 8
            self.clock.now += 2
            with self.assertRaisesRegex(controller.RunFailure, "byte cap"):
                run.guard()
        self.assertEqual(len(run.last_samples), 1)
        self.assertEqual(run.record["resource_cap_crossing"]["allocated_bytes"], 4096)
        self.assertEqual(run.record["resource_cap_crossing"]["entries"], 0)
        self.assertEqual(tree.extra_lstat.call_count, 2)
        tree.entries[run.derived / "child"].stat.assert_called_once_with(follow_symlinks=False)

    def test_root_lstat_rejects_symlink_and_content_mode_does_not_change_root_policy(self):
        root = self.root / "virtual"
        with injected_resource_tree({root: []}, root_infos={root: resource_info(0, 0, stat.S_IFLNK)}) as tree:
            with self.assertRaisesRegex(controller.RunFailure, "ordinary directory"):
                controller.tree_size(root, 4096, lambda: None, cap_metric="allocated")
        tree.scans.assert_not_called()
        missing = resource_info(mode=stat.S_IFDIR)
        del missing.st_blocks
        with injected_resource_tree({root: []}, root_infos={root: missing}) as tree:
            total = controller.tree_size(root, 4096, lambda: None)
        tree.extra_lstat.assert_not_called()
        self.assertEqual(total, {"logical_bytes": 0, "allocated_bytes": 0,
                                 "entries": 0, "cap_metric": "max_logical_allocated"})

    def test_derived_guard_accepts_sparse_logical_reservation_within_allocated_cap(self):
        """Regression: the old guard aborts this same 8 GiB/zero-block stat."""
        run = self.run_fixture()
        with injected_resource_tree({run.derived: [("sparse-cache", resource_info(8 * controller.GIB, 0))]}) as tree, \
                patch.object(controller, "write_json") as write:
            run.guard(force=True)
            tree.entries[run.derived / "sparse-cache"].stat.assert_called_once_with(follow_symlinks=False)
        sample = run.last_samples[0]["derived_data"]
        self.assertEqual(sample["logical_bytes"], 8 * controller.GIB)
        self.assertEqual(sample["allocated_bytes"], 0)
        self.assertEqual(sample["cap_metric"], "allocated")
        self.assertEqual(write.call_args.args[1][0]["derived_data"], sample)
        self.assertNotIn("resource_cap_crossing", run.record)
        self.assertEqual(controller.DERIVED_CAP, 4 * controller.GIB)

    def test_allocated_equality_and_overage_abort_even_with_tiny_logical_content(self):
        for blocks in (8, 9):
            run = self.run_fixture(output=False)
            with self.subTest(blocks=blocks), injected_resource_tree({run.derived: [("allocated", resource_info(1, blocks))]}), \
                    patch.object(controller, "DERIVED_CAP", 4096), patch.object(controller, "write_json") as write:
                with self.assertRaisesRegex(controller.RunFailure, "byte cap"):
                    run.guard(force=True)
            observation = run.record["resource_cap_crossing"]
            self.assertEqual(observation["cap_metric"], "allocated")
            self.assertEqual(observation["logical_bytes"], 1)
            self.assertEqual(observation["allocated_bytes"], blocks * 512)
            self.assertEqual(run.last_samples, [])
            write.assert_not_called()

    def test_unknown_or_invalid_blocks_fail_closed_without_invented_allocation(self):
        values = [None, -1, True, False, 1.0, float("nan"), "8", object()]
        missing = resource_info(1)
        del missing.st_blocks
        for info in [missing] + [resource_info(1, value) for value in values]:
            for mode in (stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
                info.st_mode = mode
                run = self.run_fixture(output=False)
                with self.subTest(blocks=getattr(info, "st_blocks", "missing"), mode=mode), \
                        injected_resource_tree({run.derived: [("unknown", info)]}) as tree, \
                        patch.object(controller, "write_json") as write:
                    with self.assertRaisesRegex(controller.ResourceAccountingFailure, "accounting unavailable"):
                        run.guard(force=True)
                self.assertEqual(run.last_samples, [])
                self.assertNotIn("resource_cap_crossing", run.record)
                tree.entries[run.derived / "unknown"].stat.assert_called_once_with(follow_symlinks=False)
                write.assert_not_called()

    def test_artifact_output_and_device_logical_caps_are_not_relaxed(self):
        cases = [("output", "", "OUTPUT_CAP"), ("device", None, "DEVICE_CAP"),
                 ("original_xcresult", "original.xcresult", "XCRESULT_CAP"),
                 ("verified_xcresult", "evidence/collection/xcresult/verified.xcresult", "XCRESULT_CAP"),
                 ("attachments", "evidence/collection/xcresult/attachments", "ATTACHMENT_CAP"),
                 ("logs", "logs", "LOG_CAP")]
        for category, relative, constant in cases:
            run = self.run_fixture(output=False)
            run.device_id = "44444444-4444-4444-8444-444444444444"
            run.device_root = self.devices / run.device_id
            root = run.device_root if relative is None else run.output / relative
            with self.subTest(category=category), injected_resource_tree({root: [("sparse-content", resource_info(getattr(controller, constant), 0))]}), \
                    patch.object(controller, "write_json"):
                run.bind_device_resource_root()  # Uses the injected root metadata.
                with self.assertRaisesRegex(controller.RunFailure, "byte cap"):
                    run.guard(force=True)
            crossing = run.record["resource_cap_crossing"]
            self.assertEqual(crossing["category"], category)
            self.assertEqual(crossing["cap_metric"], "max_logical_allocated")
            self.assertEqual(crossing["allocated_bytes"], 0)

    def test_hardlink_growth_is_charged_per_entry_without_stale_inode_cache(self):
        run = self.run_fixture()
        before, after = resource_info(1, 2, inode=101), resource_info(1, 6, inode=101)
        with injected_resource_tree({run.derived: [("first-link", before), ("grown-link", after)]}) as tree:
            with self.assertRaisesRegex(controller.RunFailure, "byte cap"):
                run.resource_size("derived_data", run.derived, 4096, cap_metric="allocated")
        crossing = run.record["resource_cap_crossing"]
        self.assertEqual((crossing["allocated_bytes"], crossing["logical_bytes"], crossing["entries"]), (4096, 2, 2))
        for entry in tree.entries.values():
            entry.stat.assert_called_once_with(follow_symlinks=False)

    def test_growth_is_remeasured_at_next_scheduled_guard_sample(self):
        run = self.run_fixture()
        path = run.derived / "growing"
        with injected_resource_tree({run.derived: [("growing", resource_info(8 * controller.GIB, 1))]}) as tree, \
                patch.object(controller, "DERIVED_CAP", 4096), patch.object(controller, "write_json"):
            tree.entries[path].stat.side_effect = [resource_info(8 * controller.GIB, 1), resource_info(8 * controller.GIB, 8)]
            run.guard(force=True)
            self.clock.now += 2
            with self.assertRaisesRegex(controller.RunFailure, "byte cap"):
                run.guard()
        self.assertEqual(len(run.last_samples), 1)
        self.assertEqual(run.last_samples[0]["derived_data"]["allocated_bytes"], 512)
        self.assertEqual(run.record["resource_cap_crossing"]["allocated_bytes"], 4096)
        self.assertEqual(tree.entries[path].stat.call_count, 2)

    def test_allocated_mode_counts_directory_and_link_metadata_without_following_link(self):
        run = self.run_fixture()
        nested = run.derived / "nested"
        with injected_resource_tree({run.derived: [("nested", resource_info(9000, 1, stat.S_IFDIR)),
                                                  ("outside-link", resource_info(17, 1, stat.S_IFLNK))],
                                     nested: [("sparse", resource_info(99999, 0))]}) as tree:
            total = run.resource_size("derived_data", run.derived, 1025, cap_metric="allocated")
        self.assertEqual((total["allocated_bytes"], total["logical_bytes"], total["entries"]), (1024, 100016, 3))
        self.assertEqual(tree.scans.call_args_list, [((run.derived,),), ((nested,),)])
        for entry in tree.entries.values():
            entry.stat.assert_called_once_with(follow_symlinks=False)

    def test_zero_block_entries_do_not_bypass_entry_or_deadline_bounds(self):
        root = self.root / "virtual"
        trees = {root: [("one", resource_info(99999, 0)), ("two", resource_info(99999, 0))]}
        with injected_resource_tree(trees):
            with self.assertRaisesRegex(controller.RunFailure, "entry-count"):
                controller.tree_size(root, 4096, lambda: None, max_entries=1, cap_metric="allocated")
        tick = Mock(side_effect=[None, controller.DeadlineFailure("deadline during walk")])
        with injected_resource_tree(trees) as tree:
            with self.assertRaisesRegex(controller.DeadlineFailure, "deadline during walk"):
                controller.tree_size(root, 4096, tick, cap_metric="allocated")
        tree.entries[root / "one"].stat.assert_not_called()

    def test_small_real_sparse_file_and_external_symlink_keep_distinct_budgets(self):
        root = self.root / "small-real-tree"
        root.mkdir()
        sparse = root / "sparse"
        with sparse.open("wb") as stream:
            stream.truncate(128 * 1024)
        external = self.root / "external"
        external.mkdir()
        (external / "not-owned").write_bytes(b"x" * 1024)
        link = root / "link"
        link.symlink_to(external, target_is_directory=True)
        blocks = root.lstat().st_blocks + sparse.lstat().st_blocks + link.lstat().st_blocks
        if blocks * 512 >= 64 * 1024:
            self.skipTest("Fixture filesystem does not expose a sparse allocation below 64 KiB")
        total = controller.tree_size(root, 64 * 1024, lambda: None, cap_metric="allocated")
        self.assertEqual(total["entries"], 2)
        self.assertEqual(total["allocated_bytes"], blocks * 512)
        self.assertEqual(total["logical_bytes"], sparse.lstat().st_size + link.lstat().st_size)
        with self.assertRaisesRegex(controller.RunFailure, "byte cap"):
            controller.tree_size(root, 64 * 1024, lambda: None)


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
                stream.write.side_effect = len
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

    def test_unknown_allocation_after_acquisition_preserves_failure_and_cleans_owned_group(self):
        run = self.run_fixture()
        info = resource_info(1)
        del info.st_blocks

        def after_acquisition():
            if run.groups:
                run.resource_size("derived_data", run.derived, controller.DERIVED_CAP, cap_metric="allocated")

        run.guard = Mock(side_effect=after_acquisition)
        with self.fake_child(active=True) as child, injected_resource_tree({run.derived: [("unknown", info)]}):
            with self.assertRaisesRegex(controller.ResourceAccountingFailure, "accounting unavailable"):
                run.command(["never-executed"], "fake-build", cap=30)
        child.stop.assert_called_once()
        self.assertTrue(run.record["commands"][0]["cleanup"]["success"])
        self.assertNotIn("resource_cap_crossing", run.record)

    def assert_cap_cleanup_precedes_receipt(self, receipt_error=None):
        run = self.run_fixture()
        original_errors, receipts = [], []
        def guard_after_spawn():
            if run.groups:
                try:
                    run.resource_size("derived_data", run.derived, 10)
                except controller.RunFailure as error:
                    original_errors.append(error)
                    raise
        run.guard = Mock(side_effect=guard_after_spawn)
        with self.fake_child(active=True) as child, \
                injected_resource_tree({run.derived: [("crossing", resource_info(10))]}):
            def receipt():
                crossing = run.record.get("resource_cap_crossing")
                receipts.append(deepcopy(crossing))
                if crossing is not None:
                    child.stop.assert_called_once()
                    self.assertTrue(run.record["commands"][0]["cleanup"]["success"])
                    if receipt_error is not None:
                        raise receipt_error
                    json.dumps(run.record, ensure_ascii=True, allow_nan=False)
            run.flush = Mock(side_effect=receipt)
            with self.assertRaises(controller.RunFailure) as caught:
                run.command(["injected-child"], "cap-during-build", cap=20)
            child.start.assert_called_once()
            child.stop.assert_called_once()
            child.process.stdout.close.assert_called_once()
            child.process.stderr.close.assert_called_once()
        self.assertEqual(len(original_errors), 1)
        self.assertIs(caught.exception, original_errors[0])
        self.assertIs(type(caught.exception), controller.RunFailure)
        self.assertEqual(str(caught.exception), "Owned resource byte cap reached: " + str(run.derived))
        self.assertIsNone(receipts[0])
        self.assertEqual(receipts[1]["category"], "derived_data")
        self.assertEqual(run.record["commands"][0]["primary_error"],
                         {"type": "RunFailure", "message": str(caught.exception)})
        if receipt_error is not None:
            self.assertTrue(any(item["operation"] == "command_receipt" for item in run.record["cleanup_errors"]))

    def test_cap_observation_is_only_written_after_owned_group_cleanup(self):
        self.assert_cap_cleanup_precedes_receipt()

    def test_cap_primary_survives_receipt_oserror_after_required_cleanup(self):
        self.assert_cap_cleanup_precedes_receipt(OSError("crossing receipt unavailable"))

    def test_cap_primary_survives_receipt_serialization_error_after_required_cleanup(self):
        self.assert_cap_cleanup_precedes_receipt(TypeError("crossing receipt cannot serialize"))

    def test_cap_primary_survives_receipt_cancellation_after_required_cleanup(self):
        self.assert_cap_cleanup_precedes_receipt(KeyboardInterrupt("cancel crossing receipt"))

    def test_active_cap_keeps_primary_through_diagnostic_deadline_and_receipt_error(self):
        run = self.run_fixture()
        original_errors, format_attempts, final_attempts = [], [], []
        real_dumps = json.dumps
        def diagnostic_serialization(value, *args, **kwargs):
            if isinstance(value, dict) and set(value) == {"resource_cap_crossing"}:
                format_attempts.append(value)
                raise controller.DeadlineFailure("diagnostic formatting deadline")
            return real_dumps(value, *args, **kwargs)
        def guard_after_spawn():
            if run.groups:
                try:
                    run.resource_size("derived_data", run.derived, 10)
                except controller.RunFailure as error:
                    original_errors.append(error)
                    raise
        run.guard = Mock(side_effect=guard_after_spawn)
        with self.fake_child(active=True) as child, \
                injected_resource_tree({run.derived: [("crossing", resource_info(10))]}), \
                patch.object(controller.json, "dumps", side_effect=diagnostic_serialization):
            def receipt():
                if run.groups:
                    child.stop.assert_called_once()
                    final_attempts.append(True)
                    raise OSError("secondary receipt unavailable")
            run.flush = Mock(side_effect=receipt)
            with self.assertRaises(controller.RunFailure) as caught:
                run.command(["injected-child"], "cap-diagnostic-failure", cap=20)
            child.start.assert_called_once()
            child.stop.assert_called_once()
        self.assertEqual(len(format_attempts), 1)
        self.assertEqual(final_attempts, [True])
        self.assertEqual(len(original_errors), 1)
        self.assertIs(caught.exception, original_errors[0])
        self.assertIs(type(caught.exception), controller.RunFailure)
        self.assertEqual(str(caught.exception), "Owned resource byte cap reached: " + str(run.derived))
        self.assertTrue(run.resource_cap_observed)
        self.assertNotIn("resource_cap_crossing", run.record)
        self.assertEqual(run.record["commands"][0]["primary_error"],
                         {"type": "RunFailure", "message": str(caught.exception)})
        self.assertTrue(any(item["operation"] == "command_receipt" for item in run.record["cleanup_errors"]))

    def test_in_command_log_scan_uses_observation_wrapper_and_cleans_before_receipt(self):
        run = self.run_fixture()
        run.guard = Mock()
        logs = run.output / "logs"
        with self.fake_child(active=True) as child, \
                injected_resource_tree({logs: [("large-log", resource_info(controller.LOG_CAP))]}):
            child.selector.select.return_value = []
            def receipt():
                if "resource_cap_crossing" in run.record:
                    child.stop.assert_called_once()
            run.flush = Mock(side_effect=receipt)
            with self.assertRaises(controller.RunFailure) as caught:
                run.command(["injected-child"], "cap-in-logs", cap=20)
            child.stop.assert_called_once()
        self.assertIs(type(caught.exception), controller.RunFailure)
        self.assertEqual(str(caught.exception), "Owned resource byte cap reached: " + str(logs))
        self.assertEqual(run.record["resource_cap_crossing"]["category"], "logs")
        self.assertEqual(run.record["resource_cap_crossing"]["cap_bytes"], controller.LOG_CAP)

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

    def test_one_case_no_parallel_and_simulator_paths_preserve_generated_products(self):
        result = controller.configure_xctestrun(self.generated(), self.ids(), device_id="44444444-4444-4444-8444-444444444444")
        targets = result["TestConfigurations"][0]["TestTargets"]
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target["OnlyTestIdentifiers"], [controller.CASE.split("/", 1)[1]])
        self.assertEqual(target["SkipTestIdentifiers"], [])
        self.assertIs(target["ParallelizationEnabled"], False)
        self.assertIs(target["UseDestinationArtifacts"], False)
        generated = self.generated()["TestConfigurations"][0]["TestTargets"][1]
        for key in ("TestHostPath", "TestBundlePath", "UITargetAppPath"):
            self.assertEqual(target[key], generated[key])
        self.assertNotIn("TestBundleDestinationRelativePath", target)
        self.assertEqual(target["TestHostBundleIdentifier"], controller.RUNNER_BUNDLE)
        self.assertEqual(target["UITargetAppBundleIdentifier"], controller.BUNDLE)
        self.assertEqual(target["SystemAttachmentLifetime"], "keepAlways")
        self.assertEqual(target["UserAttachmentLifetime"], "keepAlways")
        self.assertEqual(target["EnvironmentVariables"]["GENERATED_VALUE"], "keep")
        self.assertEqual(target["EnvironmentVariables"]["RECOVERY_SIMULATOR_UDID"], "44444444-4444-4444-8444-444444444444")
        self.assertEqual(target["EnvironmentVariables"]["RECOVERY_SOURCE_RUN_ID"], self.ids()["source_run_id"])
        self.assertEqual(target["EnvironmentVariables"]["RUN_INVENTORY_RECOVERY_JOURNEY"], "1")
        self.assertEqual(target["UITargetAppEnvironmentVariables"], {"APP_GENERATED": "keep"})
        self.assertEqual((target["TestLanguage"], target["TestRegion"]), ("en", "US"))

    def test_build_writes_simulator_paths_beside_original_and_keeps_original_unchanged(self):
        run = self.run_fixture()
        run.device_id = "44444444-4444-4444-8444-444444444444"
        run.phase = Mock()
        run.prepare_derived_resource_root = Mock()
        products = run.derived / "Build/Products"
        products.mkdir(parents=True)
        generated = self.generated()
        target = generated["TestConfigurations"][0]["TestTargets"][1]
        # Even a preexisting destination-artifacts override must not restore
        # the Xcode 16.4 physical-device-only path that failed in hosted CI.
        target["UseDestinationArtifacts"] = True
        target["TestBundleDestinationRelativePath"] = "__TESTHOST__/PlugIns/RoomInventoryUITests.xctest"
        original = products / "RoomInventory_iphonesimulator.xctestrun"
        raw = plistlib.dumps(generated)
        original.write_bytes(raw)
        for name, bundle in (("RoomInventory.app", controller.BUNDLE),
                             ("RoomInventoryUITests-Runner.app", controller.RUNNER_BUNDLE)):
            app = products / "Debug-iphonesimulator" / name
            app.mkdir(parents=True)
            info = {"CFBundleIdentifier": bundle}
            if bundle == controller.RUNNER_BUNDLE:
                info["NSPhotoLibraryUsageDescription"] = "Automated test runner control"
            (app / "Info.plist").write_bytes(plistlib.dumps(info))
        run.command = Mock(return_value=b"")

        run.build()

        self.assertEqual(run.xctestrun.parent, original.parent)
        self.assertEqual(original.read_bytes(), raw)
        self.assertEqual((run.output / "generated.xctestrun.plist").read_bytes(), raw)
        selected = run.xctestrun.read_bytes()
        self.assertEqual((run.output / "selected.xctestrun.plist").read_bytes(), selected)
        self.assertEqual(run.xctestrun_sha, controller.sha(selected))
        selected_target = plistlib.loads(selected)["TestConfigurations"][0]["TestTargets"][0]
        self.assertIs(selected_target["UseDestinationArtifacts"], False)
        self.assertNotIn("TestBundleDestinationRelativePath", selected_target)
        for key in ("TestHostPath", "UITargetAppPath", "TestBundlePath"):
            self.assertEqual(selected_target[key], target[key])
        self.assertEqual(selected_target["OnlyTestIdentifiers"], [controller.CASE.split("/", 1)[1]])
        self.assertEqual(run.record["build_count"], 1)
        self.assertEqual(run.command.call_count, 1)
        args, label = run.command.call_args.args
        self.assertEqual(args[:2], ["xcodebuild", "build-for-testing"])
        self.assertEqual(label, "build")
        self.popen.assert_not_called()

    def test_one_ui_invocation_uses_default_iteration_and_preserves_failure(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                run = self.run_fixture(output=False)
                run.output = self.root / ("failed-output" if failed else "success-output")
                run.output.mkdir()
                run.device_id = "44444444-4444-4444-8444-444444444444"
                run.xctestrun = run.output / "selected.xctestrun"
                run.xctestrun.write_bytes(b"approved selection")
                run.xctestrun_sha = controller.sha(run.xctestrun.read_bytes())
                run.pin_sources = Mock()
                run.guard = Mock()
                run.collector = Mock()
                copied = run.output / "verified.xcresult"
                collected = run.output / "collection.json"
                run.collector.capture_xcresult.return_value = copied
                run.collector.collect.return_value = collected
                failure = controller.RunFailure("injected UI failure")

                def command(args, name, **options):
                    if name == "ui-test":
                        self.assertEqual(args[:2], ["xcodebuild", "test-without-building"])
                        # Xcode 16.4 rejects -test-iterations 1 before XCTest starts.
                        for flag in ("-test-iterations", "-retry-tests-on-failure",
                                     "-run-tests-until-failure", "-test-repetition-relaunch-enabled"):
                            self.assertNotIn(flag, args)
                        self.assertEqual([a for a in args if isinstance(a, str) and a.startswith("-only-testing:")],
                                         ["-only-testing:" + controller.CASE])
                        for flag, value in (("-xctestrun", run.xctestrun),
                                            ("-destination", "platform=iOS Simulator,id=" + run.device_id),
                                            ("-resultBundlePath", run.output / "original.xcresult"),
                                            ("-parallel-testing-enabled", "NO"),
                                            ("-maximum-concurrent-test-simulator-destinations", "1"),
                                            ("-test-timeouts-enabled", "YES"),
                                            ("-maximum-test-execution-time-allowance", "420")):
                            self.assertEqual(args.count(flag), 1)
                            self.assertEqual(args[args.index(flag) + 1], value)
                        self.assertEqual(options, {"cap": 480, "on_poll": run.collector.poll_bridge})
                        if failed:
                            raise failure
                    else:
                        self.assertEqual(name, "verify-artifacts")
                    return b""

                run.command = Mock(side_effect=command)
                if failed:
                    with self.assertRaises(controller.RunFailure) as caught:
                        run.test_and_collect()
                    self.assertIs(caught.exception, failure)
                    run.collector.collect.assert_not_called()
                    run.guard.assert_not_called()
                else:
                    run.test_and_collect()
                    run.collector.collect.assert_called_once_with(copied)
                    run.guard.assert_called_once_with(force=True)
                names = [call.args[1] for call in run.command.call_args_list]
                self.assertEqual(names, ["ui-test"] if failed else ["ui-test", "verify-artifacts"])
                self.assertEqual(run.record["test_count"], 1)
                run.pin_sources.assert_called_once_with("-pretest")
                run.collector.capture_xcresult.assert_called_once_with(run.output / "original.xcresult")
                self.popen.assert_not_called()

    def test_commerce_settings_are_rejected_even_inside_discarded_target(self):
        for key, value in [("StoreKitConfigurationFileReference", "anything"), ("Other", "path/LOCAL.STOREKIT")]:
            generated = self.generated()
            generated["TestConfigurations"][0]["TestTargets"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(controller.ConfigurationFailure, "StoreKit"):
                controller.configure_xctestrun(generated, self.ids(), device_id="44444444-4444-4444-8444-444444444444")

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
                controller.configure_xctestrun(value, self.ids(), device_id="44444444-4444-4444-8444-444444444444")


class ActiveTimerTests(ControllerCase):
    def staged_run(self):
        run = self.run_fixture()
        for name in ("prepare", "build", "prepare_device", "test_and_collect", "cleanup"):
            setattr(run, name, Mock())
        return run

    def assert_cap_primary_survives_finalization(self, secondary):
        run = self.staged_run()
        def cap_during_build():
            run.resource_size("derived_data", run.derived, 10)
        run.build.side_effect = cap_during_build
        final_receipts = []
        def final_receipt():
            run.cleanup.assert_called_once()
            final_receipts.append(deepcopy(run.record))
            raise secondary
        run.flush = Mock(side_effect=final_receipt)
        with injected_resource_tree({run.derived: [("entry", resource_info(10))]}):
            code = run.execute()
        self.assertEqual(code, 1)
        self.assertEqual(run.record["primary_error"], {"type": "RunFailure", "message": "Owned resource byte cap reached: " + str(run.derived)})
        self.assertEqual(run.record["status"], "FAIL")
        self.assertEqual(run.record["exit_code"], 1)
        self.assertEqual(final_receipts[0]["status"], "FAIL")
        self.assertEqual(final_receipts[0]["resource_cap_crossing"]["category"], "derived_data")
        self.assertEqual(run.record["finalization_error"]["type"], type(secondary).__name__)
        run.prepare_device.assert_not_called()
        run.test_and_collect.assert_not_called()
        self.popen.assert_not_called()
        self.assertFalse(run.timer_enabled)
        self.assertEqual(self.handlers.call_args.args, (signal.SIGALRM, self.previous_handler))

    def test_cap_failure_cannot_become_success_after_final_receipt_oserror(self):
        self.assert_cap_primary_survives_finalization(OSError("final crossing receipt unavailable"))

    def test_cap_failure_cannot_become_success_after_final_serialization_error(self):
        self.assert_cap_primary_survives_finalization(TypeError("final crossing receipt cannot serialize"))

    def test_cap_failure_cannot_become_success_after_final_receipt_cancellation(self):
        self.assert_cap_primary_survives_finalization(KeyboardInterrupt("cancel final crossing receipt"))

    def test_cap_observation_reaches_real_result_json_through_existing_flush(self):
        run = self.staged_run()
        run.build.side_effect = lambda: run.resource_size("derived_data", run.derived, 10)
        with injected_resource_tree({run.derived: [("entry", resource_info(10))]}):
            code = run.execute()
        self.assertEqual(code, 1)
        run.cleanup.assert_called_once()
        run.prepare_device.assert_not_called()
        run.test_and_collect.assert_not_called()
        saved = json.loads((run.output / "result.json").read_text())
        self.assertEqual(saved["status"], "FAIL")
        self.assertEqual(saved["exit_code"], 1)
        self.assertEqual(saved["primary_error"],
                         {"type": "RunFailure", "message": "Owned resource byte cap reached: " + str(run.derived)})
        self.assertEqual(saved["resource_cap_crossing"], run.record["resource_cap_crossing"])
        self.assertEqual(saved["resource_cap_crossing"]["traversal"], "partial")
        self.assertEqual(saved["resource_cap_crossing"]["category"], "derived_data")
        self.assertEqual(saved["resource_cap_crossing"]["logical_bytes"], 10)
        self.assertEqual(saved["resource_cap_crossing"]["current_entry"]["relative_path"], "entry")
        self.assertEqual(saved["cleanup_errors"], [])
        self.popen.assert_not_called()

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
        run.bind_device_resource_root()
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
