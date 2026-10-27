"""Post-child accounting boundaries with fake time, processes and traversal."""
from contextlib import contextmanager
from copy import deepcopy
import errno
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import test_recovery_controller as fixtures

C = fixtures.controller


class CommandAccountingTests(fixtures.ControllerCase):
    fake_child = fixtures.CommandFailureTests.fake_child

    @staticmethod
    def captured(call):
        try:
            return call(), None
        except BaseException as error:
            return None, error

    @contextmanager
    def boundary(self, *, child_at=25, cleanup_cost=1, accounting_cost=20, active=False):
        run = self.run_fixture(output=False)
        run.output.mkdir(exist_ok=True)
        run.owns_output = True
        run.timer_enabled = True
        events, saved = [], []
        run.flush = Mock(side_effect=lambda: saved.append(deepcopy(run.record)))
        with self.fake_child(active=active) as child:
            registered = {}
            def register(pipe, events, index):
                registered[pipe.fileno()] = SimpleNamespace(fileobj=pipe, data=index)
            child.selector.register.side_effect = register
            child.selector.unregister.side_effect = lambda pipe: registered.pop(pipe.fileno())
            child.selector.get_map.side_effect = lambda: registered
            child.selector.select.side_effect = lambda **kwargs: [(key, 1) for key in registered.values()]
            child.process.poll.return_value = 0
            def guard(force=False):
                events.append(("guard", force, self.clock.now, run.command_deadline))
                if force:
                    self.clock.now += accounting_cost
                run.tick()
            run.guard = Mock(side_effect=guard)
            def wait(timeout):
                self.clock.now = run.start + child_at
                events.append(("wait", self.clock.now))
                return 0
            child.process.wait.side_effect = wait
            def stop(process, end, *, state, clock):
                events.append(("cleanup", self.clock.now, end))
                self.clock.now += cleanup_cost
                state["returncode"] = 0
                return child.cleanup
            child.stop.side_effect = stop
            with patch.object(C.os, "read", return_value=b""):
                yield SimpleNamespace(run=run, child=child, events=events, saved=saved,
                                      invoke=lambda: run.command(["fake-child"], "accounting", cap=30))

    def assert_closed(self, b):
        b.child.stop.assert_called_once()
        b.child.selector.close.assert_called_once()
        for stream in b.child.log_streams + [b.child.process.stdout, b.child.process.stderr]:
            stream.close.assert_called_once()
        self.assertIsNone(b.run._derived_scan_service)
        self.assertIsNone(b.run.command_deadline)

    def test_long_accounting_after_timely_cleanup_uses_original_phase(self):
        with self.boundary() as b:
            before = (b.run.phase_end, b.run.work_end, b.run.outer_end)
            output, error = self.captured(b.invoke)
            self.assertIsNone(error, type(error).__name__)
            self.assertEqual(output, b"")
            record = b.run.record["commands"][0]
            self.assertEqual(record["end_deadline_elapsed"], 30)
            self.assertEqual(record["child_completed_elapsed"], 25)
            self.assertEqual(record["cleanup_completed_elapsed"], 26)
            self.assertTrue(record["process_observation"]["stdout_eof"]["observed"])
            self.assertTrue(record["process_observation"]["stderr_eof"]["observed"])
            self.assertEqual(record["elapsed_seconds"], 46)
            self.assertEqual(record["post_command_accounting"], {
                "start_elapsed": 26, "deadline_elapsed": 120,
                "end_elapsed": 46, "status": "COMPLETED"})
            self.assertEqual((b.run.phase_end, b.run.work_end, b.run.outer_end), before)
            self.assertEqual(b.events[-2:], [("cleanup", 125, 130), ("guard", True, 126, 220)])
            b.child.start.assert_called_once()
            self.assertEqual(len(b.saved), 2)
            self.assertEqual(b.saved[-1]["commands"][0]["post_command_accounting"]["status"], "COMPLETED")
            self.assert_closed(b)

    def test_original_child_work_deadline_still_rejects_late_wait_and_poll(self):
        for point in ("wait", "poll"):
            for extra in (0, .001):
                with self.subTest(point=point, extra=extra), self.boundary(child_at=26 + extra, accounting_cost=0) as b:
                    if point == "poll":
                        def late_poll():
                            self.clock.now = b.run.start + 26 + extra
                            return 0
                        b.child.process.poll.side_effect = late_poll
                    _, error = self.captured(b.invoke)
                    self.assertIsInstance(error, C.DeadlineFailure)
                    self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
                    self.assertEqual(b.child.stop.call_args.args[1], b.run.start + 30)
                    self.assertIsNone(b.run.record["commands"][0]["post_command_accounting"])
                    self.assert_closed(b)

    def test_late_successful_cleanup_at_end_or_later_never_reaches_accounting(self):
        for extra in (0, .001):
            with self.subTest(extra=extra), self.boundary(cleanup_cost=5 + extra, accounting_cost=0) as b:
                _, error = self.captured(b.invoke)
                self.assertIsInstance(error, C.DeadlineFailure)
                self.assertIn("cleanup returned", str(error))
                self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
                self.assertTrue(b.run.record["commands"][0]["cleanup"]["success"])
                self.assertIsNone(b.run.record["commands"][0]["post_command_accounting"])
                self.assert_closed(b)

    def test_unknown_unreaped_sticky_or_failed_cleanup_cannot_pass(self):
        for changes in ({"success": False}, {"group_state": "unknown"}, {"leader_reaped": False}, {"errors": ["sticky"]}, {"budget_exhausted": True}):
            with self.subTest(changes=changes), self.boundary(accounting_cost=0) as b:
                b.child.cleanup.update(changes)
                _, error = self.captured(b.invoke)
                self.assertIsInstance(error, C.RunFailure)
                self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
                self.assertEqual(b.run.record["commands"][0]["derived_service"]["terminal_barrier"], {"reached": False, "completed": False})
                self.assert_closed(b)

    def test_real_owned_cleanup_late_esrch_success_is_rejected_at_return_boundary(self):
        real_cleanup = C.kill_owned
        with self.boundary(cleanup_cost=0, accounting_cost=0) as b:
            reports = []
            def stop(process, end, *, state, clock):
                def probe(pgid, sig):
                    self.assertEqual(pgid, process.pid)
                    self.assertEqual(sig, 0)
                    self.clock.now = end
                    raise OSError(errno.ESRCH, "fake absent group")
                report = real_cleanup(process, end, state=state, clock=clock,
                                      sleep=Mock(side_effect=AssertionError("no sleeping")), killpg=probe)
                reports.append(report)
                return report
            b.child.stop.side_effect = stop
            _, error = self.captured(b.invoke)
            self.assertIsInstance(error, C.DeadlineFailure)
            self.assertTrue(reports[0]["success"])
            self.assertEqual(reports[0]["group_state"], "absent")
            self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
            self.assert_closed(b)

    def test_late_close_never_authorizes_a_barrier_or_further_late_close(self):
        for point in ("selector", "stream"):
            with self.subTest(point=point), self.boundary(cleanup_cost=0, accounting_cost=0) as b:
                target = b.child.selector if point == "selector" else b.child.process.stdout
                def close():
                    self.clock.now = b.run.start + 30
                target.close.side_effect = close
                _, error = self.captured(b.invoke)
                self.assertIsInstance(error, C.RunFailure)
                self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
                b.child.stop.assert_called_once()
                b.child.process.stderr.close.assert_not_called()

    def test_cleanup_observer_entry_control_blocks_accounting(self):
        with self.boundary(accounting_cost=0) as b:
            primary = C.DeadlineFailure("cleanup observer entry")
            observer = b.run.observe_runtime
            def observe(event, *args, **kwargs):
                if event == "cleanup_return":
                    raise primary
                return observer(event, *args, **kwargs)
            b.run.observe_runtime = observe
            _, error = self.captured(b.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
            self.assertTrue(any(item["operation"] == "owned_group_exception" for item in b.run.record["cleanup_errors"]))
            self.assert_closed(b)

    def test_selector_or_stream_close_error_prevents_accounting_after_group_success(self):
        for point in ("selector", "stream"):
            with self.subTest(point=point), self.boundary(accounting_cost=0) as b:
                target = b.child.selector if point == "selector" else b.child.process.stdout
                target.close.side_effect = OSError("close failed")
                _, error = self.captured(b.invoke)
                self.assertIsInstance(error, C.RunFailure)
                self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
                self.assertTrue(b.run.record["commands"][0]["cleanup"]["success"])
                self.assert_closed(b)

    def test_phase_work_and_outer_boundaries_each_remain_absolute(self):
        for bound in ("phase_end", "work_end", "outer_end"):
            with self.subTest(bound=bound), self.boundary(accounting_cost=14) as b:
                setattr(b.run, bound, b.run.start + 40)
                before = (b.run.phase_end, b.run.work_end, b.run.outer_end)
                _, error = self.captured(b.invoke)
                self.assertIsInstance(error, C.DeadlineFailure)
                self.assertEqual((b.run.phase_end, b.run.work_end, b.run.outer_end), before)
                record = b.run.record["commands"][0]
                self.assertEqual(record["post_command_accounting"]["deadline_elapsed"], 40)
                self.assertEqual(record["post_command_accounting"]["status"], "FAILED")
                self.assertEqual(record["exception_origin"]["last_stage"], "command_accounting")
                self.assertEqual(record["derived_service"]["terminal_barrier"], {"reached": True, "completed": False})
                if bound in ("phase_end", "outer_end"):
                    self.assertEqual(len(b.saved), 1)  # Initial provisional write only.
                    self.assertIsNone(b.saved[0]["commands"][0]["post_command_accounting"])
                    self.assertTrue(any(item["operation"] == "command_receipt" for item in b.run.record["cleanup_errors"]))
                self.assert_closed(b)

    def test_phase_expired_at_accounting_entry_fails_before_scan(self):
        with self.boundary(accounting_cost=0) as b:
            b.run.work_end = b.run.start + 26
            _, error = self.captured(b.invoke)
            self.assertIsInstance(error, C.DeadlineFailure)
            self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
            self.assertIsNone(b.run.record["commands"][0]["post_command_accounting"])
            self.assert_closed(b)

    def test_timer_rearm_follows_confirmed_cleanup_without_reserve_borrowing(self):
        with self.boundary() as b:
            timer_events = []
            self.timers.side_effect = lambda which, duration: timer_events.append((self.clock.now, duration, b.child.stop.call_count))
            b.invoke()
            self.assertTrue(any(now + duration == 126 for now, duration, _ in timer_events if duration))
            self.assertTrue(any(now + duration == 130 for now, duration, _ in timer_events if duration))
            extended = [(now, duration, stops) for now, duration, stops in timer_events if duration and now + duration > 130]
            self.assertTrue(extended)
            self.assertTrue(all(stops == 1 and now + duration == 220 for now, duration, stops in extended))
            first = next(i for i, event in enumerate(timer_events) if event in extended)
            self.assertEqual(timer_events[first - 1][1], 0)
            self.assert_closed(b)


    def test_terminal_fresh_guard_still_enforces_caps_floor_and_unknown_blocks(self):
        for category in ("derived", "device", "logs", "output", "free", "unknown"):
            with self.subTest(category=category), self.boundary(accounting_cost=0) as b:
                run = b.run
                run.device_root = self.devices / "owned"
                root, cap = {
                    "derived": (run.derived, C.DERIVED_CAP), "unknown": (run.derived, C.DERIVED_CAP),
                    "device": (run.device_root, C.DEVICE_CAP), "logs": (run.output / "logs", C.LOG_CAP),
                    "output": (run.output, C.OUTPUT_CAP), "free": (run.output, C.OUTPUT_CAP)}[category]
                info = fixtures.resource_info(1, cap // 512)
                if category == "unknown":
                    info.st_blocks = None
                old_guard = run.guard.side_effect
                def guard(force=False):
                    if not force:
                        return old_guard(force=force)
                    b.child.stop.assert_called_once()
                    if category == "free":
                        run.disk_usage = lambda _: SimpleNamespace(free=C.ABORT_BYTES - 1)
                    return C.RecoveryRun.guard(run, force=True)
                run.guard.side_effect = guard
                with fixtures.injected_resource_tree({root: [("crossing", info)]}) as tree, patch.object(C, "write_json") as writes:
                    # The log allocation grows only after owned cleanup; the
                    # unchanged live log scan must still pass beforehand.
                    if category == "logs":
                        tree.entries[root / "crossing"].stat.side_effect = lambda follow_symlinks: info if b.child.stop.called else fixtures.resource_info()
                    _, error = self.captured(b.invoke)
                self.assertIsInstance(error, C.ResourceAccountingFailure if category == "unknown" else C.RunFailure)
                self.assertEqual(run.last_samples, [])
                writes.assert_not_called()
                self.assertEqual(run.record["commands"][0]["post_command_accounting"]["status"], "FAILED")
                self.assertEqual(run.record["commands"][0]["exception_origin"]["last_stage"], "command_accounting")
                self.assert_closed(b)

    def test_accounting_primary_survives_receipt_and_observer_entry_faults(self):
        with self.boundary(accounting_cost=0) as b:
            primary = C.RunFailure("original accounting cap")
            old_guard = b.run.guard.side_effect
            def guard(force=False):
                if force:
                    raise primary
                return old_guard(force=force)
            b.run.guard.side_effect = guard
            old_observe = b.run.observe_derived_service
            def observe(target, event, **kwargs):
                if event == "incomplete":
                    raise KeyboardInterrupt("secondary observer entry")
                return old_observe(target, event, **kwargs)
            b.run.observe_derived_service = observe
            b.run.record_exception_origin = Mock(side_effect=SystemExit(9))
            b.run.flush.side_effect = [None, OSError("receipt failed")]
            _, error = self.captured(b.invoke)
            self.assertIs(error, primary)
            self.assertEqual(b.run.record["commands"][0]["primary_error"]["message"], str(primary))
            self.assertEqual(b.run.record["commands"][0]["post_command_accounting"]["status"], "FAILED")
            self.assert_closed(b)

    def test_child_timing_control_interrupt_is_primary_and_still_cleans(self):
        for primary in (C.DeadlineFailure("child timing deadline"), KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(kind=type(primary).__name__), self.boundary(accounting_cost=0) as b:
                elapsed = b.run.diagnostic_elapsed
                def timing(**kwargs):
                    if b.run.diagnostic_stage == "command_wait":
                        raise primary
                    return elapsed(**kwargs)
                b.run.diagnostic_elapsed = timing
                _, error = self.captured(b.invoke)
                self.assertIs(error, primary)
                self.assertEqual(b.run.record["commands"][0]["primary_error"]["type"], type(primary).__name__)
                self.assertIsNone(b.run.record["commands"][0]["post_command_accounting"])
                self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
                self.assert_closed(b)

    def test_pending_alarm_at_accounting_observer_entry_remains_failure(self):
        with self.boundary(accounting_cost=0) as b:
            primary = C.DeadlineFailure("pending original alarm")
            observe = b.run.observe_derived_service
            def entry(target, event, **kwargs):
                if event == "barrier_reached":
                    raise primary
                return observe(target, event, **kwargs)
            b.run.observe_derived_service = entry
            _, error = self.captured(b.invoke)
            self.assertIs(error, primary)
            self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
            self.assert_closed(b)

    def test_on_poll_primary_skips_accounting_and_remains_primary(self):
        with self.boundary(active=True, accounting_cost=0) as b:
            primary = OSError("on_poll failed")
            def callback():
                raise primary
            _, error = self.captured(lambda: b.run.command(["fake-child"], "callback", cap=30, on_poll=callback))
            self.assertIs(error, primary)
            self.assertFalse(any(event[:2] == ("guard", True) for event in b.events))
            self.assert_closed(b)

    def test_cleanup_mode_retains_old_time_only_guard_before_owned_cleanup(self):
        with self.boundary(accounting_cost=0) as b:
            b.run.cleanup_mode = True
            b.invoke()
            self.assertEqual(b.events[-2][0:2], ("guard", True))
            self.assertEqual(b.events[-1][0], "cleanup")
            self.assertIsNone(b.run.record["commands"][0]["post_command_accounting"])
            self.assertNotIn("derived_service", b.run.record["commands"][0])
            self.assert_closed(b)


if __name__ == "__main__":
    unittest.main()
