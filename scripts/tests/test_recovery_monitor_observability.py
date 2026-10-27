"""Aggregate receipts use fake children and supplied timestamps only."""
from copy import deepcopy
import json
from unittest.mock import Mock
import unittest

import test_recovery_controller as fixtures
import test_recovery_monitor_supervision as monitor

C = fixtures.controller


class MonitorObservabilityTests(fixtures.ControllerCase):
    world = monitor.MonitorSupervisionTests.world
    captured = staticmethod(monitor.MonitorSupervisionTests.captured)
    fake_child = fixtures.CommandFailureTests.fake_child
    assert_cleaned = monitor.MonitorSupervisionTests.assert_cleaned

    def observation(self, w):
        self.assertIn("derived_service", w.run.record["commands"][0])
        return w.run.record["commands"][0]["derived_service"]

    def test_success_aggregates_are_saved_by_existing_receipt_after_cleanup(self):
        with self.world() as w:
            saved = []
            w.run.flush.side_effect = lambda: saved.append(deepcopy(w.run.record))
            self.assertEqual(w.invoke(), b"e" * 9)
            observation = self.observation(w)
            self.assertEqual(observation, {
                "quanta_started": 3, "quanta_completed": 3, "polls_returned": 3,
                "stdout": {"read_returns": 3, "read_bytes": 9, "eof_returns": 0, "would_block": 0},
                "stderr": {"read_returns": 3, "read_bytes": 9, "eof_returns": 0, "would_block": 0},
                "first_completed_checkpoint_elapsed": 0.0, "last_completed_checkpoint_elapsed": 0.0,
                "terminal_barrier": {"reached": True, "completed": True},
                "capture_incomplete": False, "saturated": False,
            })
            self.assertEqual(len(saved), 2)
            self.assertEqual(saved[-1]["commands"][0]["derived_service"], observation)
            self.assertTrue(saved[-1]["commands"][0]["cleanup"]["success"])
            self.assert_cleaned(w)

    def test_quantum_before_io_can_fail_with_zero_work_and_unknown_completion(self):
        with self.world() as w:
            primary = C.DeadlineFailure("select interrupted")
            def fail():
                raise primary
            w.select_fault = fail
            _, error = self.captured(w.invoke)
            self.assertIs(error, primary)
            observation = self.observation(w)
            self.assertEqual(observation["quanta_started"], 1)
            self.assertEqual(observation["quanta_completed"], 0)
            self.assertEqual(observation["polls_returned"], 0)
            self.assertEqual(observation["stdout"]["read_returns"], 0)
            self.assertEqual(observation["stderr"]["read_returns"], 0)
            self.assertIsNone(observation["first_completed_checkpoint_elapsed"])
            self.assertIsNone(observation["last_completed_checkpoint_elapsed"])
            self.assertTrue(observation["capture_incomplete"])
            self.assert_cleaned(w)

    def test_returned_bytes_are_recorded_even_when_late_read_is_not_persisted(self):
        with self.world() as w:
            def read(fd, amount):
                self.clock.now = w.run.command_deadline
                return b"returned-but-not-persisted"
            w.read_fault = read
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.DeadlineFailure)
            observation = self.observation(w)
            self.assertEqual(observation["stderr"]["read_returns"], 1)
            self.assertEqual(observation["stderr"]["read_bytes"], len(b"returned-but-not-persisted"))
            self.assertEqual(observation["quanta_completed"], 0)
            self.assertEqual(observation["polls_returned"], 0)
            self.assertFalse(any(event[0] == "write" for event in w.events))
            self.assertEqual(w.run.record["commands"][0]["stderr_sha256"], C.sha(b""))
            self.assertTrue(observation["capture_incomplete"])
            self.assert_cleaned(w)

    def test_partial_write_does_not_rename_returned_bytes_as_retained(self):
        with self.world() as w:
            w.write_fault = lambda index, data: 1
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            observation = self.observation(w)
            self.assertEqual(observation["stderr"]["read_bytes"], 3)
            self.assertEqual(w.run.record["commands"][0]["stderr_sha256"], C.sha(b""))
            self.assertNotIn("retained_bytes", observation["stderr"])
            self.assertNotIn("persisted_bytes", observation["stderr"])
            self.assertTrue(observation["capture_incomplete"])
            self.assert_cleaned(w)

    def test_eof_and_would_block_have_distinct_return_semantics(self):
        with self.world() as w:
            def read(fd, amount):
                if w.scanning and fd == 112:
                    raise BlockingIOError()
                return b""
            w.read_fault = read
            w.invoke()
            observation = self.observation(w)
            self.assertEqual(observation["stdout"], {"read_returns": 1, "read_bytes": 0, "eof_returns": 1, "would_block": 0})
            self.assertEqual(observation["stderr"], {"read_returns": 0, "read_bytes": 0, "eof_returns": 0, "would_block": 3})
            self.assertEqual(observation["polls_returned"], 3)
            self.assert_cleaned(w)

    def test_read_and_poll_exceptions_are_not_counted_as_returns(self):
        for point in ("read", "poll"):
            with self.subTest(point=point), self.world() as w:
                primary = OSError("injected syscall error")
                def fail(*args):
                    raise primary
                setattr(w, point + "_fault", fail)
                _, error = self.captured(w.invoke)
                self.assertIs(error, primary)
                observation = self.observation(w)
                self.assertEqual(observation["polls_returned"], 0)
                self.assertEqual(observation["stderr"]["read_returns"], 0 if point == "read" else 1)
                self.assertTrue(observation["capture_incomplete"])
                self.assert_cleaned(w)

    def test_failed_terminal_barrier_keeps_counts_but_never_marks_completed(self):
        with self.world() as w:
            saved = []
            w.run.flush.side_effect = lambda: saved.append(deepcopy(w.run.record))
            def expire():
                self.clock.now = w.run.command_deadline
            w.barrier_fault = expire
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.DeadlineFailure)
            observation = self.observation(w)
            self.assertEqual(observation["quanta_completed"], 3)
            self.assertEqual(observation["terminal_barrier"], {"reached": True, "completed": False})
            self.assertTrue(observation["capture_incomplete"])
            self.assertEqual(saved[-1]["commands"][0]["derived_service"], observation)
            self.assert_cleaned(w)

    def test_failed_owned_cleanup_does_not_erase_completed_barrier_or_counters(self):
        with self.world() as w:
            saved = []
            w.run.flush.side_effect = lambda: saved.append(deepcopy(w.run.record))
            w.child.cleanup["success"] = False
            w.child.cleanup["errors"] = ["sticky group uncertainty"]
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            observation = self.observation(w)
            self.assertEqual(observation["quanta_completed"], 3)
            self.assertEqual(observation["terminal_barrier"], {"reached": True, "completed": True})
            self.assertFalse(w.run.record["commands"][0]["cleanup"]["success"])
            self.assertEqual(saved[-1]["commands"][0]["derived_service"], observation)
            self.assert_cleaned(w)

    def test_non_derived_scans_have_no_service_work_and_cleanup_is_not_applicable(self):
        for category in ("output", "logs"):
            with self.subTest(category=category), self.world(category=category) as w:
                w.invoke()
                observation = self.observation(w)
                self.assertEqual(observation["quanta_started"], 0)
                self.assertEqual(observation["polls_returned"], 0)
                self.assertEqual(observation["stdout"]["read_returns"], 0)
                self.assertEqual(observation["stderr"]["read_returns"], 0)
                self.assertIsNone(observation["first_completed_checkpoint_elapsed"])
                self.assertEqual(observation["terminal_barrier"], {"reached": True, "completed": True})
        with self.world() as w:
            w.run.cleanup_mode = True
            w.invoke()
            self.assertNotIn("derived_service", w.run.record["commands"][0])

    def test_supplied_completion_clock_values_only_no_clock_or_io_query(self):
        run = self.run_fixture()
        run.clock = Mock(side_effect=AssertionError("observer queried clock"))
        run.disk_usage = Mock(side_effect=AssertionError("observer queried disk"))
        target = {}
        run.observe_derived_service(target, "quantum_started")
        run.observe_derived_service(target, "quantum_completed", value=run.start + .25)
        run.observe_derived_service(target, "quantum_completed", value=run.start + .75)
        self.assertEqual(target["derived_service"]["first_completed_checkpoint_elapsed"], .25)
        self.assertEqual(target["derived_service"]["last_completed_checkpoint_elapsed"], .75)
        run.clock.assert_not_called()
        run.disk_usage.assert_not_called()

    def test_invalid_or_reversed_checkpoint_is_null_and_incomplete(self):
        run = self.run_fixture()
        for value in (None, float("nan"), float("inf"), run.start - 1, run.start + 86401, 1 << 10000):
            with self.subTest(value_type=type(value).__name__):
                target = {}
                run.observe_derived_service(target, "quantum_completed", value=run.start + 2)
                run.observe_derived_service(target, "quantum_completed", value=value)
                observation = target["derived_service"]
                self.assertEqual(observation["first_completed_checkpoint_elapsed"], 2)
                self.assertIsNone(observation["last_completed_checkpoint_elapsed"])
                self.assertTrue(observation["capture_incomplete"])
        target = {}
        run.observe_derived_service(target, "quantum_completed", value=run.start + 2)
        run.observe_derived_service(target, "quantum_completed", value=run.start + 1)
        self.assertIsNone(target["derived_service"]["last_completed_checkpoint_elapsed"])
        run.observe_derived_service(target, "quantum_completed", value=run.start + 3)
        self.assertEqual(target["derived_service"]["last_completed_checkpoint_elapsed"], 3)
        self.assertTrue(target["derived_service"]["capture_incomplete"])

    def test_saturation_bounds_fixed_schema_and_marks_lower_bounds(self):
        run = self.run_fixture()
        target = {}
        run.observe_derived_service(target, "init")
        observation = target["derived_service"]
        limit = 2**31 - 1
        for key in ("quanta_started", "quanta_completed", "polls_returned"):
            observation[key] = limit
        for pipe in ("stdout", "stderr"):
            for key in observation[pipe]:
                observation[pipe][key] = limit
        for event in ("quantum_started", "quantum_completed", "poll_return", "barrier_reached", "barrier_completed"):
            run.observe_derived_service(target, event, value=run.start + 86400)
        for index in (0, 1):
            for event, value in (("read_return", 1 << 10000), ("read_return", 0), ("would_block", None)):
                run.observe_derived_service(target, event, index=index, value=value)
        self.assertTrue(observation["saturated"])
        self.assertTrue(observation["capture_incomplete"])
        for pipe in ("stdout", "stderr"):
            self.assertTrue(all(value == limit for value in observation[pipe].values()))
        encoded = json.dumps({"commands": [target]}, indent=2, allow_nan=False)
        self.assertLessEqual(len(encoded), 2048)
        self.assertEqual(set(observation), {"quanta_started", "quanta_completed", "polls_returned", "stdout", "stderr",
                         "first_completed_checkpoint_elapsed", "last_completed_checkpoint_elapsed", "terminal_barrier",
                         "capture_incomplete", "saturated"})

    @staticmethod
    def controls():
        return (C.DeadlineFailure("alarm"), KeyboardInterrupt("interrupt"), SystemExit(9))

    def test_ordinary_caller_entry_controls_abort_and_cleanup_without_swallowing(self):
        for event in ("quantum_started", "barrier_completed"):
            for primary in self.controls():
                with self.subTest(event=event, primary=type(primary).__name__), self.world() as w:
                    original = w.run.observe_derived_service
                    def at_entry(target, actual, **kwargs):
                        if actual == event:
                            raise primary
                        return original(target, actual, **kwargs)
                    w.run.observe_derived_service = at_entry
                    _, error = self.captured(w.invoke)
                    self.assertIs(error, primary)
                    self.assertTrue(self.observation(w)["capture_incomplete"])
                    if event == "quantum_started":
                        self.assertFalse(any(e[0] == "read" for e in w.events))
                    self.assert_cleaned(w)

    def test_post_primary_caller_entry_controls_cannot_replace_primary_or_skip_cleanup(self):
        for secondary in self.controls():
            with self.subTest(secondary=type(secondary).__name__), self.world() as w:
                primary = C.DeadlineFailure("original select interruption")
                def fail():
                    raise primary
                w.select_fault = fail
                original = w.run.observe_derived_service
                attempted = []
                def at_entry(target, event, **kwargs):
                    if event == "incomplete":
                        attempted.append(event)
                        raise secondary
                    return original(target, event, **kwargs)
                w.run.observe_derived_service = at_entry
                _, error = self.captured(w.invoke)
                self.assertIs(error, primary)
                self.assertEqual(attempted, ["incomplete"])
                self.assertEqual(w.run.record["commands"][0]["primary_error"]["message"], str(primary))
                self.assert_cleaned(w)

    def test_observer_body_and_marker_dual_controls_preserve_priority(self):
        run = self.run_fixture()
        for primary in (*self.controls(), ValueError("generic observer failure")):
            for secondary in self.controls():
                for preserve in (False, True):
                    with self.subTest(primary=type(primary).__name__, secondary=type(secondary).__name__, preserve=preserve):
                        class Broken(dict):
                            def __getitem__(self, key):
                                raise primary
                            def __setitem__(self, key, value):
                                raise secondary
                        target = {"derived_service": Broken()}
                        _, error = self.captured(lambda: run.observe_derived_service(target, "quantum_started", preserve_primary=preserve))
                        expected = None if preserve else primary if isinstance(primary, (C.DeadlineFailure, KeyboardInterrupt, SystemExit)) else secondary
                        self.assertIs(error, expected)

    def test_generic_body_failure_marks_incomplete_but_keeps_work_and_cleanup(self):
        with self.world() as w:
            original = w.run.observe_derived_service
            class BrokenCounter(dict):
                def __getitem__(self, key):
                    if key == "quanta_started":
                        raise ValueError("counter unavailable")
                    return super().__getitem__(key)
            def inject(target, event, **kwargs):
                if event == "quantum_started" and type(target["derived_service"]) is dict:
                    target["derived_service"] = BrokenCounter(target["derived_service"])
                return original(target, event, **kwargs)
            w.run.observe_derived_service = inject
            self.assertEqual(w.invoke(), b"e" * 9)
            self.assertTrue(self.observation(w)["capture_incomplete"])
            self.assertEqual(self.observation(w)["quanta_completed"], 3)
            self.assertEqual(self.observation(w)["terminal_barrier"], {"reached": True, "completed": True})
            self.assert_cleaned(w)


if __name__ == "__main__":
    unittest.main()
