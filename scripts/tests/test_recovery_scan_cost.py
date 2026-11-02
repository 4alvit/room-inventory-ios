"""Bounded scan-cost observations; all CPU/native operations are injected."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_recovery_controller as fixtures
import test_recovery_device_service as device

C = fixtures.controller


def cpu(user, system):
    return SimpleNamespace(ru_utime=user, ru_stime=system)


class ScanCostTests(fixtures.ControllerCase):
    def setUp(self):
        super().setUp()
        self.run = self.run_fixture(output=False)
        patcher = patch.object(C.resource, "getrusage", return_value=cpu(1, 2))
        self.cpu = patcher.start()
        self.addCleanup(patcher.stop)
        self.real_tree = C.tree_size
        patcher = patch.object(C, "tree_size", return_value={"entries": 0})
        self.tree = patcher.start()
        self.addCleanup(patcher.stop)

    def scan(self, category="logs"):
        return self.run.resource_size(category, self.run.output / category, C.LOG_CAP)

    def bucket(self, target=None, category="logs"):
        return (self.run.record if target is None else target)["resource_scan_cost"]["categories"][category]

    def test_success_uses_existing_wall_span_and_two_self_cpu_samples(self):
        self.cpu.side_effect = [cpu(10, 2), cpu(10.25, 2.125)]
        self.tree.side_effect = lambda *a, **k: setattr(self.clock, "now", self.clock.now + 3) or {"entries": 4}
        self.assertEqual(self.scan(), {"entries": 4})
        b = self.bucket()
        self.assertEqual((b["started"], b["returned"], b["failed"]), (1, 1, 0))
        self.assertEqual((b["wall_measured"], b["cpu_measured"], b["wall_missing"], b["cpu_missing"]), (1, 1, 0, 0))
        self.assertEqual(b["wall_seconds"], {"sum": 3, "max": 3})
        self.assertEqual(b["self_user_seconds"], {"sum": .25, "max": .25})
        self.assertEqual(b["self_system_seconds"], {"sum": .125, "max": .125})
        self.assertFalse(b["capture_incomplete"])
        self.assertEqual([call.args for call in self.cpu.call_args_list], [(C.resource.RUSAGE_SELF,)] * 2)
        span = self.run.record["resource_scan"]["last"]
        self.assertEqual(set(span), {"category", "state", "start_elapsed", "end_elapsed", "duration_seconds"})
        self.assertEqual(span["duration_seconds"], b["wall_seconds"]["sum"])

    def test_failed_scan_preserves_error_and_measures_returning_failure(self):
        primary = OSError("injected filesystem failure")
        def fail(*args, **kwargs):
            self.clock.now += 4
            raise primary
        self.tree.side_effect = fail
        with self.assertRaises(OSError) as caught:
            self.scan()
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.cpu.call_count, 2)
        b = self.bucket()
        self.assertEqual((b["started"], b["returned"], b["failed"]), (1, 0, 1))
        self.assertEqual(b["wall_seconds"], {"sum": 4, "max": 4})
        self.assertEqual(self.run.record["resource_scan"]["last"]["state"], "failed")

    def test_missing_wall_clock_does_not_invent_zero_measurement(self):
        self.run.diagnostic_elapsed = Mock(return_value=None)
        self.scan()
        b = self.bucket()
        self.assertEqual((b["wall_missing"], b["wall_measured"], b["cpu_measured"]), (1, 0, 1))
        self.assertTrue(b["capture_incomplete"])
        self.assertEqual(self.run.diagnostic_elapsed.call_count, 2)

    def test_regressing_existing_wall_span_is_missing(self):
        self.run.diagnostic_elapsed = Mock(side_effect=[3, 2])
        self.scan()
        self.assertEqual(self.bucket()["wall_missing"], 1)
        self.assertEqual(self.bucket()["wall_measured"], 0)

    def test_cpu_syscall_failures_at_either_boundary_remain_observational(self):
        for samples in ([OSError("unavailable"), cpu(1, 2)], [cpu(1, 2), OSError("unavailable")]):
            with self.subTest(samples=samples):
                before = self.cpu.call_count
                self.cpu.side_effect = samples
                self.assertEqual(self.scan(), {"entries": 0})
                self.assertEqual(self.cpu.call_count - before, 2)
        b = self.bucket()
        self.assertEqual((b["cpu_missing"], b["cpu_measured"], b["returned"]), (2, 0, 2))
        self.assertTrue(b["capture_incomplete"])

    def test_invalid_nonfinite_and_regressing_cpu_are_missing(self):
        cases = [(cpu(float("nan"), 0), cpu(1, 2)),
                 (cpu(1, 2), cpu(float("inf"), 3)),
                 (cpu(-1, 2), cpu(1, 2)), (cpu(True, 2), cpu(1, 2)),
                 (cpu(1 << 10000, 2), cpu(1, 2)),
                 (cpu(2, 3), cpu(1, 4)), (cpu(2, 3), cpu(3, 2)),
                 (cpu(0, 0), cpu(86401, 0))]
        for samples in cases:
            with self.subTest(types=[type(x.ru_utime).__name__ for x in samples]):
                self.cpu.side_effect = samples
                self.scan()
        b = self.bucket()
        self.assertEqual((b["cpu_missing"], b["cpu_measured"]), (len(cases), 0))
        self.assertEqual(b["self_user_seconds"]["sum"], 0)
        json.dumps(self.run.record, allow_nan=False)

    @staticmethod
    def controls():
        return (C.DeadlineFailure("alarm"), KeyboardInterrupt("interrupt"), SystemExit(9))

    def test_cpu_controls_on_normal_entry_and_exit_remain_fatal(self):
        for boundary in (0, 1):
            for primary in self.controls():
                with self.subTest(boundary=boundary, error=type(primary).__name__):
                    samples = [cpu(1, 2), cpu(2, 3)]
                    samples[boundary] = primary
                    self.cpu.side_effect = samples
                    self.cpu.reset_mock()
                    self.tree.reset_mock()
                    with self.assertRaises(type(primary)) as caught:
                        self.scan()
                    self.assertIs(caught.exception, primary)
                    self.assertEqual(self.cpu.call_count, 2)
                    self.assertEqual(self.tree.call_count, boundary)

    def test_end_cpu_control_cannot_replace_existing_error(self):
        for secondary in self.controls():
            primary = C.ResourceAccountingFailure("original cap/metadata failure")
            self.tree.side_effect = primary
            self.cpu.side_effect = [cpu(1, 2), secondary]
            with self.assertRaises(C.ResourceAccountingFailure) as caught:
                self.scan()
            self.assertIs(caught.exception, primary)
        self.assertEqual(self.bucket()["cpu_missing"], 3)

    def test_control_during_private_handoff_is_not_swallowed(self):
        for handoff in (C._DeviceScanDeferred(), C._DerivedScanDeferred()):
            primary = C.DeadlineFailure("alarm during handoff observation")
            self.tree.side_effect = handoff
            self.cpu.side_effect = [cpu(1, 2), primary]
            with self.assertRaises(C.DeadlineFailure) as caught:
                self.scan()
            self.assertIs(caught.exception, primary)

    def test_finish_observer_entry_cannot_replace_primary(self):
        for secondary in (*self.controls(), ValueError("broken observer")):
            primary = OSError("original tree error")
            self.tree.side_effect = primary
            with patch.object(self.run, "observe_scan_cost", wraps=self.run.observe_scan_cost) as observe:
                original = observe._mock_wraps
                def injected(event, **kwargs):
                    if event == "finish":
                        raise secondary
                    return original(event, **kwargs)
                observe.side_effect = injected
                with self.assertRaises(OSError) as caught:
                    self.scan()
            self.assertIs(caught.exception, primary)
            self.assertTrue(self.bucket()["capture_incomplete"])

    def test_fixed_categories_saturation_and_serialized_size(self):
        self.scan()
        b = self.bucket()
        for key in ("started", "returned", "failed", "wall_measured", "cpu_measured"):
            b[key] = 2**31 - 1
        for key in ("wall_seconds", "self_user_seconds", "self_system_seconds"):
            b[key] = {"sum": 86400.0, "max": 86400.0}
        self.cpu.side_effect = [cpu(0, 0), cpu(1, 1)]
        self.tree.side_effect = lambda *a, **k: setattr(self.clock, "now", self.clock.now + 1) or {}
        self.scan()
        self.assertTrue(b["saturated"])
        self.assertTrue(b["capture_incomplete"])
        self.assertEqual(b["started"], 2**31 - 1)
        self.assertTrue(all(b[k]["sum"] == 86400 for k in ("wall_seconds", "self_user_seconds", "self_system_seconds")))
        self.scan("untrusted-path-or-command")
        aggregate = self.run.record["resource_scan_cost"]
        self.assertEqual(set(aggregate["categories"]), C.SCAN_CATEGORIES)
        self.assertTrue(aggregate["capture_incomplete"])
        self.assertLess(len(json.dumps(aggregate, allow_nan=False)), 8192)

    def test_aggregate_updates_make_no_clock_filesystem_or_process_query(self):
        self.run.clock = Mock(side_effect=AssertionError("unexpected clock"))
        self.run.disk_usage = Mock(side_effect=AssertionError("unexpected disk query"))
        with patch.object(C, "write_json", side_effect=AssertionError("unexpected write")):
            b = self.run.observe_scan_cost("start", category="device")
            self.run.observe_scan_cost("finish", bucket=b, span={"duration_seconds": 2},
                                       cpu_start=(1, 2), cpu_end=(2, 3))
        self.cpu.assert_not_called()
        self.run.clock.assert_not_called()
        self.run.disk_usage.assert_not_called()

    def test_direct_nested_walk_is_inclusive_not_double_counted(self):
        calls = []
        def scan(root, *args, **kwargs):
            calls.append(root)
            self.clock.now += 1
            if root == self.run.derived:
                C.tree_size(self.run.output / "logs", C.LOG_CAP, self.run.tick)
            return {"entries": 1}
        self.tree.side_effect = scan
        self.run.resource_size("derived_data", self.run.derived, C.DERIVED_CAP)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.cpu.call_count, 2)
        self.assertEqual(self.bucket(category="derived_data")["wall_seconds"]["sum"], 2)
        self.assertEqual(self.bucket()["started"], 0)

    def test_command_scope_includes_terminal_barrier_and_restores_on_error(self):
        # Undo this test's tree mock, without touching any native guard.
        with patch.object(C, "tree_size", self.real_tree):
            with device.runtime_guard() as denied, device.World(module=C, count=128, actual_guard=True) as w:
                w.invoke()
                record = w.record
                self.assertGreater(record["resource_scan_cost"]["categories"]["device"]["started"], 0)
                self.assertGreater(w.run.record["resource_scan_cost"]["categories"]["device"]["started"], 0)
                self.assertEqual(record["post_command_accounting"]["status"], "COMPLETED")
                self.assertIsNone(w.run._scan_cost_command)
                self.assertEqual(denied, [])
        previous = {}
        self.run._scan_cost_command = previous
        with patch.object(self.run, "_command", side_effect=OSError("before spawn")):
            with self.assertRaises(OSError):
                self.run.command(["not-spawned"], "injected")
        self.assertIs(self.run._scan_cost_command, previous)
