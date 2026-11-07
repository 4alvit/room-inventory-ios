"""Bridge responsiveness through actual guarded walks; all runtime I/O injected."""
import contextlib
from pathlib import Path
import unittest
from unittest.mock import patch

import test_recovery_device_service as fixtures
from test_recovery_vanished_xcresult import ResultWorld, info

C = fixtures.C


class BridgeWorld(ResultWorld):
    def __init__(self):
        super().__init__()
        self.count = 240
        self.walked = 0
        self.pending = self.acknowledged = False
        self.calls = []
        self.barriers = []
        self.callback_fault = self.entry_fault = None
        self.run.collector = self
        self.run.guard = lambda force=False: C.RecoveryRun.guard(self.run, force=force)
        self.stat_action = self.visit
        self.poll_action = lambda: 0 if len(self.run.last_samples) >= 2 else None
        self.read_action = self.read_pipe

    def __enter__(self):
        super().__enter__()
        self.run.device_root = self.root
        self.run.device_id = self.root.name
        self.run._owned_device_identity = None
        self.run.bind_device_resource_root()
        self.children[self.root] = []
        for index in range(self.count):
            child = self.root / str(index)
            self.children[self.root].append(child)
            self.infos[child] = info(size=1, blocks=1, inode=index + 100)
        return self

    def visit(self, path):
        if path.parent == self.root and self.stage == "active":
            self.walked += 1
            self.clock.now += .4
            if self.walked == 8:
                self.pending = True
                self.request_time = self.clock.now
            if self.entry_fault:
                self.entry_fault(path)

    def read_pipe(self, fd):
        if self.poll_action() is None:
            raise BlockingIOError()
        return b""

    def has_pending_bridge_request(self):
        return self.pending

    def poll_bridge(self):
        if not self.pending:
            return
        self.calls.append((self.clock.now, self.walked, len(self.run.last_samples)))
        assert self.run._resource_census is not None
        assert self.run._bridge_scan_guard is not None
        # Real collector reads/writes and _publish_ack all call this same guard.
        self.run.guard()
        self.clock.now += 2.1
        self.run.guard()
        if self.callback_fault:
            self.callback_fault()
        self.acknowledged = True
        self.barriers.append({"sequence": len(self.barriers) + 1})
        self.pending = False

    def invoke(self):
        args = ["xcodebuild", "test-without-building", "-xctestrun", self.run.xctestrun,
                "-only-testing:" + C.CASE, "-resultBundlePath", self.result]
        return self.run.command(args, "ui-test", cap=300, xcresult_producer=True,
                                on_poll=self.poll_bridge)


class BridgeServiceTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))

    def assert_closed(self, world):
        self.assertTrue(world.cleaned)
        self.assertIsNone(world.run._resource_census)
        self.assertIsNone(world.run._bridge_scan_guard)
        self.assertEqual(sum(e[0] == "cleanup" for e in world.events), 1)

    def test_request_during_slow_census_is_acknowledged_once_before_full_completion(self):
        with BridgeWorld() as w:
            self.assertEqual(w.invoke(), b"")
            self.assertTrue(w.acknowledged)
            self.assertEqual(len(w.calls), 1)
            at, visited, completed = w.calls[0]
            self.assertLess(at - w.request_time, 1)
            self.assertLess(visited, w.count)
            self.assertEqual(completed, 1)
            self.assertGreater(w.record["elapsed_seconds"], 60)
            self.assertGreaterEqual(len(w.run.last_samples), 3)
            self.assertEqual(w.run.last_samples[-1]["device"]["entries"], w.count)
            trace = w.record["bridge_scan_service"]["records"]
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0]["state"], "completed")
            self.assertEqual(trace[0]["sequence"], 1)
            self.assertEqual(trace[0]["incomplete_census"], "device")
            self.assertGreater(trace[0]["finished_elapsed"], trace[0]["started_elapsed"])
            self.assert_closed(w)

    def test_later_device_cap_crossing_fails_even_after_acknowledgement(self):
        with BridgeWorld() as w:
            def cross(path):
                if w.walked == 200:
                    w.infos[path].st_blocks = C.DEVICE_CAP // 512 + 1
            w.entry_fault = cross
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("cap reached", str(error))
            self.assertTrue(w.acknowledged)
            self.assertEqual(len(w.run.last_samples), 1)
            self.assert_closed(w)

    def test_owned_derived_walk_services_once_and_requires_final_census(self):
        for replace_owner in (False, True):
            with self.subTest(replace_owner=replace_owner), BridgeWorld() as w:
                w.children[w.root] = []
                w.root = w.run.derived
                w.children[w.root] = []
                for index in range(w.count):
                    child = w.root / str(index)
                    w.children[w.root].append(child)
                    w.infos[child] = info(size=1, blocks=1, inode=index + 500)
                # Use the production create/bind/validate path; only filesystem
                # syscalls are injected by the shared owned-directory fixture.
                w.run.prepare_derived_resource_root()
                if replace_owner:
                    def change_owner():
                        w.infos[w.root].st_ino += 1
                        w.run.guard()
                    w.callback_fault = change_owner
                    error = fixtures.failure(w.invoke)
                    self.assertIsInstance(error, C.ResourceAccountingFailure)
                    self.assertIn("DerivedData root replaced", str(error))
                    self.assertFalse(w.acknowledged)
                    self.assertEqual(len(w.run.last_samples), 1)
                else:
                    self.assertEqual(w.invoke(), b"")
                    self.assertTrue(w.acknowledged)
                    at, visited, completed = w.calls[0]
                    self.assertLess(at - w.request_time, 1)
                    self.assertLess(visited, w.count)
                    self.assertEqual(completed, 1)
                    self.assertGreater(w.record["elapsed_seconds"], 60)
                    self.assertGreaterEqual(len(w.run.last_samples), 3)
                    final = w.run.last_samples[-1]["derived_data"]
                    self.assertEqual(final["entries"], w.count)
                    self.assertEqual(final["logical_bytes"], w.count)
                    self.assertEqual(w.record["post_command_accounting"]["status"], "COMPLETED")
                self.assertEqual(len(w.calls), 1)
                trace = w.record["bridge_scan_service"]["records"]
                self.assertEqual(len(trace), 1)
                self.assertEqual(trace[0]["incomplete_census"], "derived_data")
                self.assertEqual(trace[0]["state"], "failed" if replace_owner else "completed")
                self.assertIsNone(w.run._derived_scan_service)
                self.assertIsNone(w.run._derived_scan_context)
                self.assert_closed(w)

    def test_callback_deadline_cancellation_and_io_errors_remain_primary(self):
        for mode in ("deadline", "cancel", "io"):
            with self.subTest(mode=mode), BridgeWorld() as w:
                def fail():
                    if mode == "deadline":
                        w.clock.now = w.run.command_deadline
                        w.run.guard()
                    raise KeyboardInterrupt("cancel") if mode == "cancel" else OSError("injected bridge I/O")
                w.callback_fault = fail
                error = fixtures.failure(w.invoke)
                self.assertIsInstance(error, C.DeadlineFailure if mode == "deadline" else KeyboardInterrupt if mode == "cancel" else OSError)
                self.assertFalse(w.acknowledged)
                self.assertEqual(len(w.calls), 1)
                self.assertEqual(len(w.run.last_samples), 1)
                self.assert_closed(w)

    def test_forced_nested_census_is_rejected_without_callback_replay(self):
        with BridgeWorld() as w:
            w.callback_fault = lambda: w.run.guard(force=True)
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.ConfigurationFailure)
            self.assertIn("Full census requested", str(error))
            self.assertEqual(len(w.calls), 1)
            self.assert_closed(w)

    def test_fresh_callback_output_cap_prevents_acknowledgement(self):
        with BridgeWorld() as w:
            def cross(path):
                if w.walked == 8:
                    w.infos[w.payload].st_blocks = C.OUTPUT_CAP // 512 + 1
            w.entry_fault = cross
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertFalse(w.acknowledged)
            self.assertEqual(w.calls, [])
            self.assert_closed(w)

    def test_recursive_service_and_changed_device_owner_fail_without_second_callback(self):
        for mode in ("recursive", "owner"):
            with self.subTest(mode=mode), BridgeWorld() as w:
                def fail():
                    if mode == "recursive":
                        w.run._device_scan_service[1]()
                    else:
                        w.run.device_root = Path("/foreign/device")
                        w.run.guard()
                w.callback_fault = fail
                error = fixtures.failure(w.invoke)
                self.assertIsInstance(error, C.ConfigurationFailure)
                self.assertEqual(len(w.calls), 1)
                self.assertFalse(w.acknowledged)
                self.assert_closed(w)

    def test_original_free_floor_remains_live_inside_callback(self):
        with BridgeWorld() as w:
            def low_disk():
                w.run.disk_usage = lambda path: type("Disk", (), {"free": C.ABORT_BYTES - 1})()
                w.run.guard()
            w.callback_fault = low_disk
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("Free disk", str(error))
            self.assertFalse(w.acknowledged)
            self.assert_closed(w)

    def test_actual_ack_publisher_checks_guard_after_fsync_before_link(self):
        collector = fixtures.load(Path(__file__).resolve().parents[1] / "recovery_collector.py",
                                  "recovery_bridge_publisher_under_test")
        for late in (False, True):
            with self.subTest(late=late), BridgeWorld() as w:
                w.bridge = Path("/owned/bridge")
                w._plain = lambda path: (w.run.guard(), path)[1]
                w.guard = w.run.guard
                w._sync = lambda path: None
                events = []
                stream = fixtures.Mock()
                stream.__enter__ = fixtures.Mock(return_value=stream)
                stream.__exit__ = fixtures.Mock(return_value=False)
                stream.fileno.return_value = 321
                def sync(fd):
                    events.append("fsync")
                    if late:
                        w.clock.now = w.run.command_deadline
                def publish():
                    with contextlib.ExitStack() as stack:
                        stack.enter_context(patch.object(collector.os, "open", return_value=321))
                        stack.enter_context(patch.object(collector.os, "fdopen", return_value=stream))
                        stack.enter_context(patch.object(collector.os, "fsync", side_effect=sync))
                        stack.enter_context(patch.object(collector.os, "link", side_effect=lambda *a, **k: events.append("link")))
                        stack.enter_context(patch.object(Path, "unlink"))
                        collector.Collector._publish_ack(w, "ack-02.json", b'{"success":true}\n')
                w.callback_fault = publish
                if late:
                    self.assertIsInstance(fixtures.failure(w.invoke), C.DeadlineFailure)
                    self.assertEqual(events, ["fsync"])
                else:
                    self.assertEqual(w.invoke(), b"")
                    self.assertEqual(events, ["fsync", "link"])
                    self.assertTrue(w.acknowledged)
                self.assertEqual(len(w.calls), 1)
                self.assert_closed(w)

    def test_pending_hint_is_post_installation_and_still_detects_untrusted_entries(self):
        collector = fixtures.load(Path(__file__).resolve().parents[1] / "recovery_collector.py",
                                  "recovery_bridge_hint_under_test")
        value = collector.Collector.__new__(collector.Collector)
        value.bridge = Path("/owned/bridge")
        value.barriers = []
        value.installation_state = "waiting"
        with patch.object(collector.os.path, "lexists", return_value=True) as exists:
            self.assertFalse(value.has_pending_bridge_request())
            exists.assert_not_called()
            value.installation_state = "accepted"
            self.assertTrue(value.has_pending_bridge_request())
            exists.assert_called_once_with(value.bridge / "request-01.json")
            # Presence is only a scheduling hint; poll_bridge must reject a
            # symlink/malformed request rather than silently ignoring it here.
            value.barriers = [{}] * 6
            self.assertFalse(value.has_pending_bridge_request())
            self.assertEqual(exists.call_count, 1)


if __name__ == "__main__":
    unittest.main()
