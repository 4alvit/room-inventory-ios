"""Injected aggregate wall-cost tests. No native commands, probes or timers."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_recovery_controller as fixtures
import test_recovery_device_service as device

C = fixtures.controller


class ScanBreakdownTests(unittest.TestCase):
    def setUp(self):
        self.clock = fixtures.FakeClock()
        self.record = {"operations": {}, "capture_incomplete": False}
        self.cost = C.ScanCostBreakdown(self.clock, self.record)

    def bucket(self, label="walker.entry_stat"):
        return self.record["operations"][label]

    def test_one_underlying_call_preserves_arguments_and_return_identity(self):
        result = object()
        def operation(*args, **kwargs):
            self.clock.now += 3
            return result
        operation = Mock(side_effect=operation)
        self.assertIs(self.cost.call("walker.entry_stat", operation, 7, follow_symlinks=False), result)
        operation.assert_called_once_with(7, follow_symlinks=False)
        self.assertEqual(self.bucket()["wall_seconds"], {"sum": 3, "max": 3})
        self.assertEqual([self.bucket()[k] for k in ("started", "returned", "failed", "active", "measured")],
                         [1, 1, 0, 0, 1])

    def test_nested_operation_cost_keyword_is_forwarded_once(self):
        operation = Mock(return_value=17)
        self.assertEqual(C.measured_scan_call(self.cost, "service.log_walk_inclusive",
                                             operation, cost=self.cost), 17)
        operation.assert_called_once_with(cost=self.cost)

    def test_scandir_acquisition_interruption_releases_acquired_iterator_once(self):
        for control in self.controls():
            iterator = Mock()
            self.cost.clock = Mock(side_effect=[100, control])
            with patch.object(C.os, "scandir", return_value=iterator) as scan:
                with self.assertRaises(type(control)) as caught:
                    C.measured_scandir_open(self.cost, Path("/owned/tree"))
            self.assertIs(caught.exception, control)
            scan.assert_called_once_with(Path("/owned/tree"))
            iterator.close.assert_called_once_with()

    def test_context_entry_timing_interruption_exits_original_context_once(self):
        for control in self.controls():
            context = Mock()
            context.__enter__ = Mock(return_value=iter(()))
            context.__exit__ = Mock(return_value=False)
            self.cost.clock = Mock(side_effect=[100, control])
            with self.assertRaises(type(control)) as caught:
                with C.MeasuredScandir(context, self.cost):
                    self.fail("interrupted entry cannot reach body")
            self.assertIs(caught.exception, control)
            context.__enter__.assert_called_once_with()
            self.assertEqual(context.__exit__.call_count, 1)
            self.assertIs(context.__exit__.call_args.args[1], control)

    def test_before_context_entry_control_closes_acquired_iterator_without_enter_or_exit(self):
        for control in self.controls():
            context = Mock()
            context.__enter__ = Mock()
            context.__exit__ = Mock()
            self.cost.clock = Mock(side_effect=control)
            with self.assertRaises(type(control)) as caught:
                with C.MeasuredScandir(context, self.cost):
                    self.fail("interrupted entry cannot reach body")
            self.assertIs(caught.exception, control)
            context.close.assert_called_once_with()
            context.__enter__.assert_not_called()
            context.__exit__.assert_not_called()

    def test_before_normal_context_exit_control_still_exits_once(self):
        for control in self.controls():
            self.cost.clock = self.clock
            context = Mock()
            context.__enter__ = Mock(return_value=iter(()))
            context.__exit__ = Mock(return_value=False)
            with self.assertRaises(type(control)) as caught:
                with C.MeasuredScandir(context, self.cost):
                    self.cost.clock = Mock(side_effect=control)
            self.assertIs(caught.exception, control)
            context.__exit__.assert_called_once_with(None, None, None)
            context.close.assert_not_called()

    def test_actual_underlying_context_entry_failure_keeps_original_protocol(self):
        primary = OSError("underlying enter failed")
        context = Mock()
        context.__enter__ = Mock(side_effect=primary)
        context.__exit__ = Mock()
        with self.assertRaises(OSError) as caught:
            with C.MeasuredScandir(context, self.cost):
                self.fail("failed entry cannot reach body")
        self.assertIs(caught.exception, primary)
        context.__enter__.assert_called_once_with()
        context.__exit__.assert_not_called()
        context.close.assert_not_called()

    def test_nested_checkpoint_is_explicitly_inclusive_not_an_exclusive_total(self):
        def advance(seconds):
            self.clock.now += seconds
        def checkpoint():
            self.cost.call("service.disk_usage_output", advance, 3)
            self.cost.call("service.select", advance, 2)
            self.cost.call("service.poll", advance, 1)
            advance(4)  # Existing control work is not assigned to a syscall.
        self.cost.call("walker.checkpoint_inclusive", checkpoint)
        self.cost.call("walker.entry_stat", advance, 5)
        self.assertEqual(self.bucket("walker.checkpoint_inclusive")["wall_seconds"]["sum"], 10)
        self.assertEqual(self.bucket("service.disk_usage_output")["wall_seconds"]["sum"], 3)
        self.assertEqual(self.bucket("service.select")["wall_seconds"]["sum"], 2)
        self.assertEqual(self.bucket("service.poll")["wall_seconds"]["sum"], 1)
        self.assertEqual(self.bucket()["wall_seconds"]["sum"], 5)
        self.assertEqual(self.clock.now, 115)

    def test_missing_nonfinite_or_regressing_samples_are_not_zero_cost(self):
        cases = [(None, 101), (100, None), (101, 100), (False, 101),
                 (float("nan"), 101), (100, float("inf")), (0, 86401), (2**10000, 101)]
        for samples in cases:
            with self.subTest(types=[type(x).__name__ for x in samples]):
                self.cost.clock = Mock(side_effect=samples)
                op = Mock(return_value=17)
                self.assertEqual(self.cost.call("walker.entry_stat", op), 17)
                op.assert_called_once_with()
        self.assertEqual(self.bucket()["missing"], len(cases))
        self.assertEqual(self.bucket()["measured"], 0)
        self.assertTrue(self.bucket()["capture_incomplete"])
        json.dumps(self.record, allow_nan=False)

    @staticmethod
    def controls():
        return (C.DeadlineFailure("deadline"), KeyboardInterrupt("cancel"), SystemExit(7))

    def test_entry_control_does_not_start_underlying_operation(self):
        for control in self.controls():
            self.cost.clock = Mock(side_effect=control)
            op = Mock()
            with self.assertRaises(type(control)) as caught:
                self.cost.call("walker.entry_stat", op)
            self.assertIs(caught.exception, control)
            op.assert_not_called()
        self.assertEqual(self.bucket()["interrupted_before_call"], 3)
        self.assertEqual(self.bucket()["active"], 0)
        self.assertEqual(self.bucket()["missing"], 3)

    def test_exit_control_after_success_remains_fatal(self):
        for control in self.controls():
            self.cost.clock = Mock(side_effect=[100, control])
            op = Mock(return_value=17)
            with self.assertRaises(type(control)) as caught:
                self.cost.call("walker.entry_stat", op)
            self.assertIs(caught.exception, control)
            op.assert_called_once_with()
        self.assertEqual(self.bucket()["returned"], 3)
        self.assertEqual(self.bucket()["active"], 0)
        self.assertEqual(self.bucket()["missing"], 3)

    def test_finish_failure_never_replaces_existing_native_or_control_error(self):
        for primary in (OSError("native"), *self.controls()):
            for secondary in (ValueError("clock"), *self.controls()):
                self.cost.clock = Mock(side_effect=[100, secondary])
                with self.assertRaises(type(primary)) as caught:
                    self.cost.call("walker.entry_stat", Mock(side_effect=primary))
                self.assertIs(caught.exception, primary)
        self.assertEqual(self.bucket()["failed"], 16)
        self.assertEqual(self.bucket()["missing"], 16)
        self.assertEqual(self.bucket()["active"], 0)

    def test_ordinary_clock_errors_do_not_prevent_or_replace_success(self):
        for samples in ([ValueError("start"), 101], [100, ValueError("end")]):
            self.cost.clock = Mock(side_effect=samples)
            op = Mock(return_value=17)
            self.assertEqual(self.cost.call("walker.entry_stat", op), 17)
            op.assert_called_once_with()
        self.assertEqual(self.bucket()["missing"], 2)

    def test_iterator_exhaustion_recorded_once_and_exit_control_not_swallowed(self):
        iterator = iter([17])
        self.assertEqual(self.cost.call("walker.iterator_next", next, iterator), 17)
        with self.assertRaises(StopIteration):
            self.cost.call("walker.iterator_next", next, iterator)
        b = self.bucket("walker.iterator_next")
        self.assertEqual((b["returned"], b["exhausted"], b["failed"]), (1, 1, 0))
        control = C.DeadlineFailure("after exhausted iterator")
        self.cost.clock = Mock(side_effect=[100, control])
        with self.assertRaises(C.DeadlineFailure) as caught:
            self.cost.call("walker.iterator_next", next, iterator)
        self.assertIs(caught.exception, control)

    def test_handoff_cannot_swallow_control_from_optional_accounting(self):
        for handoff in (C._DeviceScanDeferred(), C._DerivedScanDeferred()):
            control = C.DeadlineFailure("handoff interrupted")
            self.cost.clock = Mock(side_effect=[100, control])
            with self.assertRaises(C.DeadlineFailure) as caught:
                self.cost.call("walker.checkpoint_inclusive", Mock(side_effect=handoff))
            self.assertIs(caught.exception, control)

    def test_whitelist_and_saturation_bound_output_without_skipping_operation(self):
        op = Mock()
        self.cost.call("walker.entry_stat", op)
        b = self.bucket()
        for key in ("started", "returned", "measured"):
            b[key] = C.ScanCostBreakdown.COUNT_LIMIT
        b["wall_seconds"] = {"sum": 86400.0, "max": 86400.0}
        self.cost.clock = Mock(side_effect=[100, 101])
        self.cost.call("walker.entry_stat", op)
        self.assertTrue(b["saturated"])
        self.assertEqual(b["wall_seconds"]["sum"], 86400)
        for number in range(1000):
            self.cost.call("/private/untrusted/" + str(number), op)
        self.assertEqual(op.call_count, 1002)
        self.assertEqual(set(self.record["operations"]), {"walker.entry_stat"})
        self.assertLess(len(json.dumps(self.record)), 1024)

    def test_context_closes_once_and_preserves_body_error_when_clock_fails(self):
        for sample in (0, 1):
            for secondary in self.controls():
                primary = OSError("body")
                context = Mock()
                context.__enter__ = Mock(return_value=iter(()))
                context.__exit__ = Mock(return_value=False)
                wrapped = C.MeasuredScandir(context, self.cost)
                samples = [100, 101]
                samples[sample] = secondary
                with self.assertRaises(OSError) as caught:
                    with wrapped:
                        self.cost.clock = Mock(side_effect=samples)
                        raise primary
                self.assertIs(caught.exception, primary)
                self.assertEqual(context.__exit__.call_count, 1)
                self.assertIs(context.__exit__.call_args.args[1], primary)
                self.cost.clock = self.clock

    def test_context_retains_native_close_error_and_suppression_protocol(self):
        primary = OSError("close")
        context = Mock()
        context.__enter__ = Mock(return_value=iter(()))
        context.__exit__ = Mock(side_effect=primary)
        with self.assertRaises(OSError) as caught:
            with C.MeasuredScandir(context, self.cost):
                pass
        self.assertIs(caught.exception, primary)
        context.__exit__.assert_called_once_with(None, None, None)
        context.__exit__ = Mock(return_value=True)
        with C.MeasuredScandir(context, self.cost):
            raise ValueError("suppressed by original context")
        self.assertEqual(context.__exit__.call_count, 1)


class ScanBreakdownIntegrationTests(fixtures.ControllerCase):
    def setUp(self):
        super().setUp()
        self.run = self.run_fixture(output=False)
        self.cpu = patch.object(C.resource, "getrusage", return_value=SimpleNamespace(ru_utime=1, ru_stime=2))
        self.cpu.start()
        self.addCleanup(self.cpu.stop)

    def test_walker_measures_single_existing_calls_and_preserves_trace(self):
        traces = []
        for measured in (False, True):
            root = Path("/owned/derived")
            trace = []
            entries = [SimpleNamespace(path=str(root / "one"), stat=Mock(
                side_effect=lambda **kw: trace.append(("stat", kw)) or fixtures.resource_info(size=3, blocks=1)))]
            class Iterator:
                def __enter__(self):
                    trace.append(("enter",))
                    return self
                def __iter__(self):
                    trace.append(("iter",))
                    return self
                def __next__(self):
                    trace.append(("next",))
                    if entries:
                        return entries.pop()
                    raise StopIteration
                def __exit__(self, *args):
                    trace.append(("close", args[0]))
            def scan(path):
                trace.append(("scan", path))
                return Iterator()
            record = {"operations": {}, "capture_incomplete": False}
            cost = C.ScanCostBreakdown(self.clock, record) if measured else None
            with (patch.object(Path, "exists", side_effect=lambda: trace.append(("exists",)) or True),
                  patch.object(Path, "is_dir", side_effect=lambda: trace.append(("is_dir",)) or True),
                  patch.object(Path, "is_symlink", side_effect=lambda: trace.append(("is_symlink",)) or False),
                  patch.object(C.os, "scandir", side_effect=scan)):
                result = C.tree_size(root, 1024, lambda: trace.append(("tick",)), cost=cost)
            self.assertEqual(result["logical_bytes"], 3)
            traces.append(trace)
            if measured:
                ops = record["operations"]
                self.assertEqual(ops["walker.scandir_open"]["started"], 1)
                self.assertEqual(ops["walker.entry_stat"]["returned"], 1)
                self.assertEqual(ops["walker.iterator_next"]["returned"], 1)
                self.assertEqual(ops["walker.iterator_next"]["exhausted"], 1)
                self.assertEqual(ops["walker.iterator_close"]["returned"], 1)
        self.assertEqual(traces[0], traces[1])

    def test_failed_walk_retains_partial_buckets_and_restores_active_observer(self):
        root = self.run.derived
        primary = C.DeadlineFailure("late second stat")
        info = fixtures.resource_info(size=3, blocks=1)
        with fixtures.injected_resource_tree({root: [("one", info), ("two", info)]}) as tree:
            tree.entries[root / "two"].stat.side_effect = primary
            with self.assertRaises(C.DeadlineFailure) as caught:
                self.run.resource_size("derived_data", root, 1024)
        self.assertIs(caught.exception, primary)
        ops = self.run.record["resource_scan_breakdown"]["categories"]["derived_data"]["operations"]
        self.assertEqual((ops["walker.entry_stat"]["returned"], ops["walker.entry_stat"]["failed"]), (1, 1))
        self.assertEqual(ops["walker.iterator_close"]["returned"], 1)
        self.assertIsNone(self.run._scan_breakdown)

    def test_no_callback_post_command_walk_is_recorded_in_command_scope(self):
        self.run._scan_cost_command = {}
        root = self.run.derived
        with fixtures.injected_resource_tree({root: [("one", fixtures.resource_info(size=1, blocks=1))]}):
            self.run.resource_size("derived_data", root, 1024)
        breakdown = self.run._scan_cost_command["resource_scan_breakdown"]
        ops = breakdown["categories"]["derived_data"]["operations"]
        self.assertEqual(ops["walker.entry_stat"]["returned"], 1)
        self.assertFalse(any(key.startswith("service.") for key in ops))
        self.assertEqual(breakdown["attribution"], "inclusive_named_spans_do_not_sum_nested_buckets")
        self.assertNotIn("resource_scan_breakdown", self.run.record)

    def test_service_and_terminal_walk_keep_identical_injected_operation_trace(self):
        traces = []
        for measured in (False, True):
            with device.runtime_guard() as denied, device.World(module=C, count=128) as world:
                if not measured:
                    world.run.start_scan_breakdown = Mock(return_value=None)
                world.invoke()
                traces.append(world.events)
                self.assertEqual(denied, [])
                if measured:
                    ops = world.record["resource_scan_breakdown"]["categories"]["device"]["operations"]
                    for label in ("service.disk_usage_output", "service.disk_usage_device", "service.select",
                                  "service.read", "service.poll", "walker.entry_stat"):
                        self.assertGreater(ops[label]["returned"], 0)
                    self.assertGreater(ops["walker.entry_stat"]["returned"], world.count)
                    self.assertTrue(all(bucket["active"] == 0 for bucket in ops.values()))
                    self.assertEqual(world.record["post_command_accounting"]["status"], "COMPLETED")
        self.assertEqual(traces[0], traces[1])

    def test_fixed_categories_do_not_store_paths_or_create_unknown_buckets(self):
        for category in C.SCAN_CATEGORIES:
            observer = self.run.start_scan_breakdown(category)
            for label in C.ScanCostBreakdown.LABELS:
                observer.call(label, lambda: None)
        self.assertIsNone(self.run.start_scan_breakdown("/untrusted/new-category"))
        aggregate = self.run.record["resource_scan_breakdown"]
        self.assertEqual(set(aggregate["categories"]), C.SCAN_CATEGORIES)
        encoded = json.dumps(aggregate, allow_nan=False)
        self.assertNotIn(str(self.run.output), encoded)
        self.assertNotIn("untrusted", encoded)
        self.assertLess(len(encoded), 40000)
