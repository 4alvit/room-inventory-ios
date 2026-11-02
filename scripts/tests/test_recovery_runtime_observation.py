"""Bounded scan/child/pipe diagnostics, with no live process or timer probes."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_recovery_controller as fixtures

C = fixtures.controller


class RuntimeObservationTests(fixtures.ControllerCase):
    fake_child = fixtures.CommandFailureTests.fake_child

    def setUp(self):
        super().setUp()
        for owner, name in [(C.os, "killpg"), (C.os, "kill"), (C.time, "sleep")]:
            guard = patch.object(owner, name, side_effect=AssertionError("live operation forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    @staticmethod
    def preserve_exit(child, code=0):
        def stop(process, end, *, state, clock):
            state["returncode"] = code
            return {**child.cleanup, "returncode": code}
        child.stop.side_effect = stop

    def command_run(self):
        run = self.run_fixture()
        run.guard = Mock()
        run.flush = Mock()
        return run

    def test_scan_records_category_span_without_extra_traversals(self):
        run = self.run_fixture()
        result = {"logical_bytes": 17, "allocated_bytes": 512}
        def scan(*args, **kwargs):
            current = run.record["resource_scan"]["current"]
            self.assertEqual(current["category"], "derived_data")
            self.assertEqual(current["state"], "started")
            self.assertEqual(current["start_elapsed"], 0)
            self.assertIsNone(current["end_elapsed"])
            self.clock.now += 2.5
            return result
        with patch.object(C, "tree_size", side_effect=scan) as tree:
            self.assertIs(run.resource_size("derived_data", run.derived, C.DERIVED_CAP, cap_metric="allocated"), result)
        tree.assert_called_once()
        self.assertEqual(tree.call_args.args, (run.derived, C.DERIVED_CAP, run.tick))
        self.assertEqual(tree.call_args.kwargs["cap_metric"], "allocated")
        self.assertIsNone(run.record["resource_scan"]["current"])
        self.assertEqual(run.record["resource_scan"]["last"], {"category": "derived_data", "state": "returned",
                         "start_elapsed": 0, "end_elapsed": 2.5, "duration_seconds": 2.5})
        self.popen.assert_not_called()

    def test_scan_has_only_last_and_current_and_preserves_failure_snapshot(self):
        run = self.run_fixture()
        original = C.DeadlineFailure("original")
        with patch.object(C, "tree_size", return_value={}):
            for _ in range(50):
                run.resource_size("logs", run.output, 1024)
        with patch.object(C, "tree_size", side_effect=original):
            with self.assertRaises(C.DeadlineFailure) as caught:
                run.resource_size("device", self.devices, C.DEVICE_CAP)
        self.assertIs(caught.exception, original)
        target = {}
        run.record_exception_origin(target, original, "command")
        snapshot = deepcopy(target["process_observation"]["resource_scan_at_failure"])
        self.assertEqual(snapshot["last"]["state"], "failed")
        with patch.object(C, "tree_size", return_value={}):
            run.resource_size("output", run.output, C.OUTPUT_CAP)
        self.assertEqual(set(run.record["resource_scan"]), {"current", "last"})
        self.assertEqual(target["process_observation"]["resource_scan_at_failure"], snapshot)
        self.assertEqual(run.record["resource_scan"]["last"]["category"], "output")

    def test_completed_scan_without_finish_clock_does_not_claim_duration(self):
        run = self.run_fixture()
        with patch.object(C, "tree_size", return_value={}), patch.object(run, "diagnostic_elapsed", side_effect=[0, None]):
            run.resource_size("logs", run.output, 1024)
        span = run.record["resource_scan"]["last"]
        self.assertEqual(span["state"], "returned")
        self.assertIsNone(span["end_elapsed"])
        self.assertIsNone(span["duration_seconds"])

    def test_deadline_in_finish_observer_preserves_known_tree_return_but_fails_wrapper(self):
        run = self.run_fixture()
        deadline = C.DeadlineFailure("finish observation")
        with patch.object(C, "tree_size", return_value={}) as tree, \
                patch.object(run, "diagnostic_elapsed", side_effect=[0, deadline]):
            with self.assertRaises(C.DeadlineFailure) as caught:
                run.resource_size("logs", run.output, 1024)
        tree.assert_called_once()
        self.assertIs(caught.exception, deadline)
        self.assertEqual(run.record["resource_scan"]["current"]["state"], "returned")
        self.assertIsNone(run.record["resource_scan"]["current"]["end_elapsed"])
        self.assertIsNone(run.record["resource_scan"]["last"])

    def test_observer_interruptions_cannot_replace_existing_scan_failure(self):
        run = self.run_fixture()
        original = C.RunFailure("original resource failure")
        for secondary in [C.DeadlineFailure("secondary"), KeyboardInterrupt(), SystemExit(3), RuntimeError("observer")]:
            with self.subTest(secondary=type(secondary).__name__), \
                    patch.object(C, "tree_size", side_effect=original) as tree, \
                    patch.object(run, "diagnostic_elapsed", side_effect=[0, secondary]):
                with self.assertRaises(C.RunFailure) as caught:
                    run.resource_size("logs", run.output, 1024)
                self.assertIs(caught.exception, original)
                tree.assert_called_once()
            self.assertEqual(run.record["resource_scan"]["current"]["state"], "failed")

    def test_normal_path_control_interruptions_are_not_swallowed(self):
        run = self.run_fixture()
        for error in [C.DeadlineFailure("alarm"), KeyboardInterrupt(), SystemExit(3)]:
            with self.subTest(error=type(error).__name__), \
                    patch.object(run, "diagnostic_elapsed", side_effect=error), \
                    patch.object(C, "tree_size") as tree:
                with self.assertRaises(type(error)) as caught:
                    run.resource_size("logs", run.output, 1024)
                self.assertIs(caught.exception, error)
                tree.assert_not_called()

    def test_clock_failures_and_nonfinite_or_out_of_range_values_are_unknown(self):
        run = self.run_fixture()
        for value in [float("nan"), float("inf"), float("-inf"), True, "secret", 99, 86501, 10**1000]:
            with self.subTest(value_type=type(value).__name__), patch.object(run, "clock", return_value=value) as clock:
                self.assertIsNone(run.diagnostic_elapsed())
                clock.assert_called_once()
        with patch.object(run, "clock", side_effect=RuntimeError("clock secret")), patch.object(C, "tree_size", return_value={}) as tree:
            run.resource_size("logs", run.output, 1024)
        tree.assert_called_once()
        span = run.record["resource_scan"]["last"]
        self.assertEqual(span["state"], "returned")
        self.assertIsNone(span["start_elapsed"])
        self.assertIsNone(span["end_elapsed"])
        self.assertIsNone(span["duration_seconds"])
        json.dumps(run.record, allow_nan=False)

    def test_exit_zero_seen_only_in_cleanup_does_not_hide_scan_deadline(self):
        run = self.command_run()
        original = C.DeadlineFailure("scan deadline")
        def guard():
            if run.groups:
                run.resource_size("device", self.devices, C.DEVICE_CAP)
        def scan(*args, **kwargs):
            self.clock.now += 26
            raise original
        run.guard.side_effect = guard
        receipts = []
        run.flush.side_effect = lambda: receipts.append(deepcopy(run.record))
        with self.fake_child(active=True) as child, patch.object(C, "tree_size", side_effect=scan) as tree:
            child.process.poll.return_value = 0
            self.preserve_exit(child)
            with self.assertRaises(C.DeadlineFailure) as caught:
                run.command(["injected-child"], "fake-boot", cap=30)
            self.assertIs(caught.exception, original)
            child.process.poll.assert_not_called()
            child.process.wait.assert_not_called()
            child.start.assert_called_once()
            child.stop.assert_called_once()
            tree.assert_called_once()
        command = run.record["commands"][0]
        observation = command["process_observation"]
        self.assertEqual(observation["first_observed_exit"], {"source": "cleanup_return", "returncode": 0, "elapsed": 26})
        self.assertEqual(observation["selector_state"], "nonempty")
        self.assertNotIn("stdout_eof", observation)
        self.assertNotIn("stderr_eof", observation)
        self.assertEqual(observation["resource_scan_at_failure"]["last"], {"category": "device", "state": "failed",
                         "start_elapsed": 0, "end_elapsed": 26, "duration_seconds": 26})
        self.assertEqual(command["primary_error"], {"type": "DeadlineFailure", "message": "scan deadline"})
        self.assertEqual(command["exit_code"], 0)
        self.assertTrue(command["cleanup"]["success"])
        self.assertEqual(command["end_deadline_elapsed"], 30)
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[-1]["commands"][0]["process_observation"], observation)

    def test_existing_short_circuit_and_empty_reads_supply_eof_without_extra_queries(self):
        run = self.command_run()
        run.resource_size = Mock(return_value={})
        with self.fake_child() as child:
            self.preserve_exit(child)
            child.selector.get_map.side_effect = [{111: object(), 112: object()}, {}]
            keys = [SimpleNamespace(fileobj=child.process.stdout, data=0), SimpleNamespace(fileobj=child.process.stderr, data=1)]
            child.selector.select.return_value = [(key, 1) for key in keys]
            def empty_read(*args):
                self.clock.now += .5
                return b""
            with patch.object(C.os, "read", side_effect=empty_read) as read:
                self.assertEqual(run.command(["injected-child"], "fake", cap=30), b"")
                self.assertEqual(read.call_count, 2)
            self.assertEqual(child.selector.get_map.call_count, 2)
            child.selector.select.assert_called_once()
            self.assertEqual(child.selector.unregister.call_count, 2)
            child.process.poll.assert_called_once_with()
            child.process.wait.assert_called_once_with(timeout=0)
            child.stop.assert_called_once()
        observation = run.record["commands"][0]["process_observation"]
        self.assertEqual(observation["selector_state"], "empty")
        self.assertEqual(observation["stdout_eof"], {"observed": True, "elapsed": .5})
        self.assertEqual(observation["stderr_eof"], {"observed": True, "elapsed": 1})
        self.assertEqual(observation["first_observed_exit"], {"source": "poll", "returncode": 0, "elapsed": 1})
        self.assertEqual(run.flush.call_count, 2)

    def test_real_traversal_tick_deadline_retains_partial_span_and_stops_second_stat(self):
        run = self.command_run()
        run.guard.side_effect = lambda: run.resource_size("derived_data", run.derived, C.DERIVED_CAP, cap_metric="allocated") if run.groups else None
        with self.fake_child(active=True) as child, fixtures.injected_resource_tree({
                run.derived: [("first", fixtures.resource_info(1)), ("second", fixtures.resource_info(1))]}) as fs:
            self.preserve_exit(child)
            def first_stat(*args, **kwargs):
                self.clock.now += 26
                return fixtures.resource_info(1)
            fs.entries[run.derived / "first"].stat.side_effect = first_stat
            with self.assertRaises(C.DeadlineFailure) as caught:
                run.command(["injected-child"], "fake-boot", cap=30)
            self.assertEqual(str(caught.exception), "Absolute phase/outer deadline exceeded")
            fs.scans.assert_called_once_with(run.derived)
            fs.extra_lstat.assert_called_once_with(run.derived)
            fs.entries[run.derived / "first"].stat.assert_called_once_with(follow_symlinks=False)
            fs.entries[run.derived / "second"].stat.assert_not_called()
            child.process.poll.assert_not_called()
            child.stop.assert_called_once()
        observation = run.record["commands"][0]["process_observation"]
        self.assertEqual(observation["resource_scan_at_failure"]["last"], {"category": "derived_data", "state": "failed",
                         "start_elapsed": 0, "end_elapsed": 26, "duration_seconds": 26})
        self.assertEqual(observation["first_observed_exit"]["source"], "cleanup_return")
        self.assertEqual(run.flush.call_count, 2)

    def test_nonempty_pipe_read_is_not_eof_and_diagnostic_clock_cannot_replace_primary(self):
        run = self.command_run()
        original = C.DeadlineFailure("after pipe read")
        run.resource_size = Mock(side_effect=original)
        with self.fake_child(active=True) as child:
            self.preserve_exit(child)
            child.selector.select.return_value = [(SimpleNamespace(fileobj=child.process.stdout, data=0), 1)]
            with patch.object(C.os, "read", return_value=b"payload") as read, \
                    patch.object(run, "diagnostic_elapsed", side_effect=KeyboardInterrupt("secondary")):
                with self.assertRaises(C.DeadlineFailure) as caught:
                    run.command(["injected-child"], "fake", cap=30)
            self.assertIs(caught.exception, original)
            read.assert_called_once_with(111, 65536)
            child.selector.unregister.assert_not_called()
            child.stop.assert_called_once()
        command = run.record["commands"][0]
        self.assertNotIn("stdout_eof", command["process_observation"])
        self.assertEqual(command["process_observation"]["first_observed_exit"], {"source": "cleanup_return", "returncode": 0, "elapsed": None})
        self.assertEqual(command["stdout_sha256"], C.sha(b"payload"))
        self.assertTrue(command["cleanup"]["success"])
        self.assertEqual(run.record["cleanup_errors"], [])

    def test_empty_selector_does_not_invent_pipe_eof(self):
        run = self.command_run()
        with self.fake_child() as child, patch.object(C.os, "read", side_effect=AssertionError("no read expected")):
            self.preserve_exit(child)
            self.assertEqual(run.command(["injected-child"], "fake", cap=30), b"")
            child.process.poll.assert_called_once()
            child.process.wait.assert_called_once()
            child.stop.assert_called_once()
        observation = run.record["commands"][0]["process_observation"]
        self.assertEqual(observation["selector_state"], "empty")
        self.assertNotIn("stdout_eof", observation)
        self.assertNotIn("stderr_eof", observation)

    def test_exit_pass_through_and_sticky_first_observation_with_missing_clock(self):
        run = self.run_fixture()
        target = {}
        with patch.object(run, "clock", side_effect=RuntimeError("no clock")):
            self.assertIsNone(run.observe_runtime("poll", target, None))
            self.assertEqual(target, {})
            self.assertEqual(run.observe_runtime("poll", target, 0), 0)
        self.clock.now += 10
        self.assertEqual(run.observe_runtime("wait", target, -15), -15)
        self.assertEqual(run.observe_runtime("cleanup_return", target, -15), -15)
        self.assertEqual(target["process_observation"]["first_observed_exit"], {"source": "poll", "returncode": 0, "elapsed": None})

    def test_final_group_cleanup_result_is_an_observation_without_new_process_queries(self):
        run = self.run_fixture()
        process = Mock()
        record = {"name": "fake", "cleanup": {"success": False}}
        run.groups = [{"process": process, "record": record, "state": {}}]
        run.record["primary_error"] = {"type": "RunFailure", "message": "original"}
        report = {"returncode": 0, "success": True}
        with patch.object(C, "kill_owned", return_value=report) as stop:
            run.cleanup()
        stop.assert_called_once()
        process.poll.assert_not_called()
        process.wait.assert_not_called()
        self.assertEqual(record["process_observation"]["first_observed_exit"],
                         {"source": "final_cleanup_return", "returncode": 0, "elapsed": 0})
        self.assertFalse(record["cleanup"]["success"])
        self.assertEqual(run.record["cleanup_errors"], [{"command": "fake", "final_observation": report}])

    def test_owned_cleanup_failure_is_recorded_before_interrupted_exit_metadata(self):
        run = self.command_run()
        class DropEarlyExitMetadata(dict):
            attempts = 0
            def __setitem__(self, key, value):
                if key == "first_observed_exit":
                    self.attempts += 1
                    if self.attempts <= 2:
                        raise MemoryError("optional poll/wait metadata unavailable")
                return super().__setitem__(key, value)
        with self.fake_child() as child:
            child.cleanup["success"] = False
            self.preserve_exit(child)
            def spawn(*args, **kwargs):
                run.record["commands"][-1]["process_observation"] = DropEarlyExitMetadata()
                return child.process
            child.start.side_effect = spawn
            elapsed = run.diagnostic_elapsed
            def cleanup_elapsed(**kwargs):
                if child.stop.called:
                    raise C.DeadlineFailure("metadata deadline")
                return elapsed(**kwargs)
            # Fault only cleanup-return metadata, not the newly distinct
            # ordinary child-completion checkpoint before cleanup.
            with patch.object(run, "diagnostic_elapsed", side_effect=cleanup_elapsed):
                with self.assertRaisesRegex(C.RunFailure, "Owned process cleanup uncertain"):
                    run.command(["injected-child"], "fake", cap=30)
            child.stop.assert_called_once()
            child.process.poll.assert_called_once()
            child.process.wait.assert_called_once_with(timeout=0)
        command = run.record["commands"][0]
        self.assertIsNone(command["primary_error"])
        self.assertFalse(command["cleanup"]["success"])
        self.assertEqual([item["operation"] for item in run.record["cleanup_errors"]], ["owned_group"])
        self.assertNotIn("metadata deadline", run.record["cleanup_errors"][0]["error"])
        self.assertTrue(command["process_observation"]["capture_incomplete"])
        self.assertEqual(command["process_observation"]["first_observed_exit"], {"source": "cleanup_return", "returncode": 0, "elapsed": None})

    def test_final_cleanup_observation_already_records_failure_before_metadata_interrupt(self):
        run = self.run_fixture()
        record = {"name": "fake", "cleanup": {"success": False}}
        run.groups = [{"process": Mock(), "record": record, "state": {}}]
        report = {"returncode": 0, "success": False}
        with patch.object(C, "kill_owned", return_value=report), \
                patch.object(run, "diagnostic_elapsed", side_effect=KeyboardInterrupt("metadata interruption")):
            run.cleanup()
        self.assertIsNone(run.record["primary_error"])
        self.assertEqual(run.record["cleanup_errors"], [{"command": "fake", "final_observation": report}])
        self.assertEqual(record["process_observation"]["first_observed_exit"]["elapsed"], None)

    def test_mapping_truth_is_consumed_once_and_poll_short_circuit_is_preserved(self):
        run = self.command_run()
        class Mapping:
            calls = 0
            def __bool__(self):
                self.calls += 1
                return True
        mapping = Mapping()
        original = C.DeadlineFailure("after map")
        run.guard.side_effect = lambda: (_ for _ in ()).throw(original) if run.groups else None
        with self.fake_child() as child:
            self.preserve_exit(child)
            child.selector.get_map.return_value = mapping
            with self.assertRaises(C.DeadlineFailure):
                run.command(["injected-child"], "fake", cap=30)
            child.process.poll.assert_not_called()
            child.stop.assert_called_once()
        self.assertEqual(mapping.calls, 1)

    def test_interrupt_during_observation_reaches_existing_handler_and_owned_cleanup(self):
        run = self.command_run()
        original = KeyboardInterrupt("observer interrupted")
        class InterruptedDict(dict):
            def __setitem__(self, key, value):
                raise original
        with self.fake_child() as child:
            self.preserve_exit(child)
            def spawn(*args, **kwargs):
                run.record["commands"][-1]["process_observation"] = InterruptedDict()
                return child.process
            child.start.side_effect = spawn
            with self.assertRaises(KeyboardInterrupt) as caught:
                run.command(["injected-child"], "fake", cap=30)
            self.assertIs(caught.exception, original)
            child.stop.assert_called_once()
            child.process.poll.assert_not_called()
        self.assertEqual(run.record["commands"][0]["primary_error"], {"type": "KeyboardInterrupt", "message": str(original)})
        self.assertTrue(run.record["commands"][0]["cleanup"]["success"])
        self.assertEqual(run.record["cleanup_errors"], [])

    def test_closed_categories_and_constructive_combined_receipt_bound(self):
        run = self.run_fixture()
        with patch.object(C, "tree_size", return_value={}):
            run.resource_size("/secret/path" * 500, run.output, 1024)
        self.assertEqual(run.record["resource_scan"]["last"]["category"], "unknown")
        self.assertNotIn("secret", json.dumps(run.record["resource_scan"]))
        span = {"category": max(C.SCAN_CATEGORIES, key=len), "state": "returned", "start_elapsed": 86399.999999,
                "end_elapsed": 86399.999999, "duration_seconds": 86399.999999}
        pair = {"current": span, "last": span}
        observation = {"selector_state": "nonempty", "stdout_eof": {"observed": True, "elapsed": 86399.999999},
                       "stderr_eof": {"observed": True, "elapsed": 86399.999999},
                       "first_observed_exit": {"source": "final_cleanup_return", "returncode": -255, "elapsed": 86399.999999},
                       "resource_scan_at_failure": pair, "capture_incomplete": True}
        before = {"commands": [{}]}
        after = {"commands": [{"process_observation": observation}], "resource_scan": pair, "failure_resource_scan": pair}
        contribution = len(json.dumps(after, indent=2, allow_nan=False)) - len(json.dumps(before, indent=2))
        self.assertLessEqual(contribution, 2048)
        self.assertEqual(set(pair), {"current", "last"})

    @staticmethod
    def failing_marker(secondary):
        class MarkerFailure(dict):
            def __setitem__(self, key, value):
                if key == "capture_incomplete":
                    raise secondary
                return super().__setitem__(key, value)
        return {"process_observation": MarkerFailure()}

    def assert_dual_failure(self, original, secondary, expected):
        run = C.RecoveryRun(self.grant(), clock=self.clock)
        target = self.failing_marker(secondary)
        with patch.object(run, "diagnostic_elapsed", side_effect=original):
            with self.assertRaises(BaseException) as caught:
                run.observe_runtime("poll", target, 0)
        self.assertIs(caught.exception, expected)
        self.assertEqual(target["process_observation"]["first_observed_exit"],
                         {"source": "poll", "returncode": 0, "elapsed": None})
        # Exercise the real outer classification as well as exception identity.
        run.owns_output = True
        for name in ("prepare", "prepare_device", "test_and_collect", "cleanup", "flush"):
            setattr(run, name, Mock())
        run.build = Mock(side_effect=lambda: run.observe_runtime("poll", self.failing_marker(secondary), 0))
        with patch.object(run, "diagnostic_elapsed", side_effect=original):
            code = run.execute()
        self.assertEqual(code, 124 if isinstance(expected, C.DeadlineFailure) else 1)
        self.assertEqual(run.record["primary_error"], {"type": type(expected).__name__, "message": str(expected)})
        run.cleanup.assert_called_once()
        run.prepare_device.assert_not_called()
        run.test_and_collect.assert_not_called()
        self.popen.assert_not_called()

    def test_original_control_wins_over_secondary_marker_control_identity_and_exit(self):
        for original, secondary in [(C.DeadlineFailure("first"), KeyboardInterrupt("second")),
                                    (C.DeadlineFailure("first"), SystemExit(9)),
                                    (KeyboardInterrupt("first"), C.DeadlineFailure("second")),
                                    (SystemExit(9), C.DeadlineFailure("second"))]:
            with self.subTest(first=type(original).__name__, second=type(secondary).__name__):
                self.assert_dual_failure(original, secondary, original)

    def test_preserve_primary_suppresses_both_observer_controls(self):
        run = self.run_fixture()
        primary = {"type": "RunFailure", "message": "already recorded"}
        run.record["primary_error"] = primary
        for original, secondary in [(C.DeadlineFailure("first"), KeyboardInterrupt("second")),
                                    (C.DeadlineFailure("first"), SystemExit(9)),
                                    (KeyboardInterrupt("first"), C.DeadlineFailure("second")),
                                    (SystemExit(9), C.DeadlineFailure("second")),
                                    (MemoryError("first"), C.DeadlineFailure("second"))]:
            with self.subTest(first=type(original).__name__, second=type(secondary).__name__), \
                    patch.object(run, "diagnostic_elapsed", side_effect=original):
                target = self.failing_marker(secondary)
                self.assertEqual(run.observe_runtime("poll", target, 0, preserve_primary=True), 0)
                self.assertIs(run.record["primary_error"], primary)
                self.assertIsNone(target["process_observation"]["first_observed_exit"]["elapsed"])
        self.popen.assert_not_called()

    def test_secondary_control_still_propagates_after_generic_observer_error(self):
        for secondary in (C.DeadlineFailure("second"), KeyboardInterrupt("second"), SystemExit(9)):
            with self.subTest(second=type(secondary).__name__):
                self.assert_dual_failure(MemoryError("first"), secondary, secondary)


if __name__ == "__main__":
    unittest.main()
