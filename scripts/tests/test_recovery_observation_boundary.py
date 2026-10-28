"""Primary-error preservation at diagnostic callable entry and inside its body."""
from unittest.mock import Mock, patch
import unittest

import test_recovery_controller as fixtures

C = fixtures.controller


class ObservationBoundaryTests(fixtures.ControllerCase):
    fake_child = fixtures.CommandFailureTests.fake_child

    def exercise(self, location, secondary):
        run = C.RecoveryRun(self.grant(), clock=self.clock)
        run.output.mkdir(exist_ok=True)
        run.owns_output = True
        for name in ("prepare", "prepare_device", "test_and_collect", "cleanup", "flush"):
            setattr(run, name, Mock())
        primary = C.DeadlineFailure("original cooperative tick deadline")
        def guard():
            if run.groups:
                raise primary
        run.guard = Mock(side_effect=guard)
        raised_from_command = []
        def build():
            try:
                run.command(["injected-child"], "fake-boot-status", cap=90)
            except BaseException as error:
                raised_from_command.append(error)
                raise
        run.build = Mock(side_effect=build)
        real_observe = run.observe_runtime
        injected = []
        def entry_fault(event, *args, **kwargs):
            if event == ("cleanup_return" if location == "cleanup_return" else "scan_snapshot"):
                injected.append(event)
                # The underlying callable has not entered its own protected body.
                raise secondary
            return real_observe(event, *args, **kwargs)
        class BodyFault(dict):
            def __getitem__(self, key):
                injected.append(key)
                raise secondary
        if location == "body":
            run.record["resource_scan"] = BodyFault()
            fault = patch.object(run, "observe_runtime", wraps=real_observe)
        elif location in ("entry", "cleanup_return"):
            fault = patch.object(run, "observe_runtime", side_effect=entry_fault)
        elif location in ("origin_entry", "cleanup_origin_entry"):
            def origin_entry(*args):
                injected.append(args[-1])
                raise secondary
            fault = patch.object(run, "record_exception_origin", side_effect=origin_entry)
        else:
            def formatter_fault(*args):
                injected.append("formatter")
                raise secondary
            fault = patch.object(C, "exception_origin", side_effect=formatter_fault)
        with self.fake_child(active=True) as child, fault:
            if location == "cleanup_origin_entry":
                child.selector.close.side_effect = OSError("original selector cleanup error")
            def stop(process, end, *, state, clock):
                state["returncode"] = 0
                return child.cleanup
            child.stop.side_effect = stop
            code, escaped = None, None
            try:
                code = run.execute()
            except BaseException as error:
                # Catch control failures too: a negative control must fail an
                # assertion, not abort the offline test harness itself.
                escaped = error
            self.assertIsNone(escaped, type(escaped).__name__)
            self.assertEqual(code, 124)
            self.assertEqual(len(raised_from_command), 1)
            self.assertIs(raised_from_command[0], primary)
            self.assertEqual(len(injected), 1 if location == "cleanup_return" else 3 if location == "cleanup_origin_entry" else 2)
            child.start.assert_called_once()
            child.stop.assert_called_once()
            child.selector.close.assert_called_once()
            for stream in child.log_streams + [child.process.stdout, child.process.stderr]:
                stream.close.assert_called_once()
            child.process.poll.assert_not_called()
            child.process.wait.assert_not_called()
        expected = {"type": "DeadlineFailure", "message": str(primary)}
        self.assertEqual(run.record["primary_error"], expected)
        command = run.record["commands"][0]
        self.assertEqual(command["primary_error"], expected)
        self.assertEqual(command["exit_code"], 0)
        self.assertTrue(command["cleanup"]["success"])
        if location == "cleanup_origin_entry":
            self.assertEqual(len(run.record["cleanup_errors"]), 1)
            self.assertEqual(run.record["cleanup_errors"][0]["operation"], "selector_close")
            self.assertEqual(run.record["cleanup_errors"][0]["error"], "OSError: original selector cleanup error")
        else:
            self.assertEqual(run.record["cleanup_errors"], [])
        self.assertEqual(run.record["status"], "FAIL")
        run.cleanup.assert_called_once()
        run.prepare_device.assert_not_called()
        run.test_and_collect.assert_not_called()
        self.assertEqual(run.flush.call_count, 3)
        self.assertEqual(self.handlers.call_args_list[-1].args, (C.signal.SIGALRM, self.previous_handler))

    def test_callable_entry_controls_preserve_primary_and_all_owned_cleanup(self):
        for secondary in self.controls():
            with self.subTest(secondary=type(secondary).__name__):
                self.exercise("entry", secondary)

    def test_inside_snapshot_body_controls_preserve_primary_and_cleanup(self):
        for secondary in self.controls():
            with self.subTest(secondary=type(secondary).__name__):
                self.exercise("body", secondary)

    def test_formatter_controls_still_preserve_primary_and_cleanup(self):
        for secondary in self.controls():
            with self.subTest(secondary=type(secondary).__name__):
                self.exercise("formatter", secondary)

    def test_command_and_operation_origin_callable_entry_preserve_primary_and_cleanup(self):
        for secondary in self.controls():
            with self.subTest(secondary=type(secondary).__name__):
                self.exercise("origin_entry", secondary)

    def test_command_cleanup_origin_entry_cannot_skip_stream_and_group_cleanup(self):
        for secondary in self.controls():
            with self.subTest(secondary=type(secondary).__name__):
                self.exercise("cleanup_origin_entry", secondary)

    def test_cleanup_return_entry_cannot_add_failure_to_existing_primary(self):
        for secondary in self.controls():
            with self.subTest(secondary=type(secondary).__name__):
                self.exercise("cleanup_return", secondary)

    @staticmethod
    def controls():
        return (C.DeadlineFailure("secondary alarm"), KeyboardInterrupt("secondary"), SystemExit(9))

    @staticmethod
    def captured(call):
        try:
            return call(), None
        except BaseException as error:
            return None, error

    def new_run(self):
        run = C.RecoveryRun(self.grant(), clock=self.clock)
        run.output.mkdir(exist_ok=True)
        run.owns_output = True
        return run

    def test_scan_end_entry_preserves_active_traversal_failure(self):
        for secondary in self.controls():
            run = self.new_run()
            original = C.DeadlineFailure("original traversal deadline")
            real_observe = run.observe_runtime
            def observe(event, *args, **kwargs):
                if event == "scan_end":
                    self.assertTrue(kwargs["failed"])
                    self.assertTrue(kwargs["preserve_primary"])
                    raise secondary
                return real_observe(event, *args, **kwargs)
            with self.subTest(secondary=type(secondary).__name__), patch.object(C, "tree_size", side_effect=original) as tree, \
                    patch.object(run, "observe_runtime", side_effect=observe):
                _, error = self.captured(lambda: run.resource_size("logs", run.output, 1024))
                self.assertIs(error, original)
                tree.assert_called_once()
                self.popen.assert_not_called()

    def test_successful_scan_end_entry_still_propagates_control(self):
        for secondary in self.controls():
            run = self.new_run()
            real_observe = run.observe_runtime
            def observe(event, *args, **kwargs):
                if event == "scan_end":
                    self.assertNotIn("preserve_primary", kwargs)
                    raise secondary
                return real_observe(event, *args, **kwargs)
            with self.subTest(secondary=type(secondary).__name__), patch.object(C, "tree_size", return_value={}) as tree, \
                    patch.object(run, "observe_runtime", side_effect=observe):
                _, error = self.captured(lambda: run.resource_size("logs", run.output, 1024))
                self.assertIs(error, secondary)
                tree.assert_called_once()

    def test_all_device_cleanup_origin_entries_preserve_errors_and_remaining_commands(self):
        for secondary in self.controls():
            run = self.new_run()
            run.device_id = "12345678-1234-4234-8234-123456789ABC"
            run.command = Mock(side_effect=C.DeadlineFailure("original device cleanup deadline"))
            with self.subTest(secondary=type(secondary).__name__), \
                    patch.object(run, "record_exception_origin", side_effect=secondary) as capture:
                _, error = self.captured(run.cleanup)
                self.assertIsNone(error)
                self.assertEqual(capture.call_count, 3)
            self.assertEqual([c.args[1] for c in run.command.call_args_list],
                             ["device-cleanup-before", "shutdown-owned-device", "device-final-state"])
            self.assertEqual([c.kwargs["cap"] for c in run.command.call_args_list], [24, 25, 15])
            self.assertEqual([e["operation"] for e in run.record["cleanup_errors"]], ["initial_state", "shutdown", "final_state"])
            self.assertTrue(all(e["error"] == "original device cleanup deadline" for e in run.record["cleanup_errors"]))
            self.assertNotIn("device_final_state", run.record)

    def test_final_group_origin_entry_does_not_skip_remaining_group_observation(self):
        for secondary in self.controls():
            run = self.new_run()
            run.groups = [{"process": Mock(), "record": {"name": name, "cleanup": {"success": False}}, "state": {}}
                          for name in ("first", "second")]
            report = {"success": False, "returncode": 0}
            with self.subTest(secondary=type(secondary).__name__), \
                    patch.object(C, "kill_owned", side_effect=[OSError("original group cleanup"), report]) as stop, \
                    patch.object(run, "record_exception_origin", side_effect=secondary) as capture:
                _, error = self.captured(run.cleanup)
                self.assertIsNone(error)
                self.assertEqual(stop.call_count, 2)
                capture.assert_called_once()
            self.assertEqual(run.record["cleanup_errors"], [
                {"command": "first", "operation": "final_group_cleanup", "error": "original group cleanup"},
                {"command": "second", "final_observation": report}])

    def test_outer_cleanup_and_finalization_origin_entry_keep_original_exit(self):
        for site in ("cleanup", "finalization"):
            for secondary in self.controls():
                run = self.new_run()
                original = C.DeadlineFailure("original operation deadline")
                for name in ("prepare", "build", "prepare_device", "test_and_collect", "cleanup", "flush"):
                    setattr(run, name, Mock())
                run.prepare.side_effect = original
                if site == "cleanup":
                    run.cleanup.side_effect = OSError("original outer cleanup")
                else:
                    run.flush.side_effect = OSError("original final receipt")
                real_origin = run.record_exception_origin
                def origin(target, error, capture_site):
                    if capture_site == site:
                        raise secondary
                    return real_origin(target, error, capture_site)
                with self.subTest(site=site, secondary=type(secondary).__name__), \
                        patch.object(run, "record_exception_origin", side_effect=origin):
                    code, error = self.captured(run.execute)
                    self.assertIsNone(error)
                    self.assertEqual(code, 124)
                self.assertEqual(run.record["primary_error"], {"type": "DeadlineFailure", "message": str(original)})
                run.cleanup.assert_called_once()
                run.build.assert_not_called()
                if site == "cleanup":
                    self.assertEqual(run.record["cleanup_errors"], [{"operation": "cleanup", "error": "original outer cleanup"}])
                else:
                    self.assertEqual(run.record["finalization_error"], {"type": "OSError", "message": "original final receipt"})

    def test_cleanup_return_entry_respects_failure_vs_ordinary_path(self):
        for success in (False, True):
            for secondary in self.controls():
                run = self.new_run()
                run.guard, run.flush = Mock(), Mock()
                real_observe = run.observe_runtime
                def observe(event, *args, **kwargs):
                    if event == "cleanup_return":
                        raise secondary
                    return real_observe(event, *args, **kwargs)
                with self.subTest(success=success, secondary=type(secondary).__name__), self.fake_child() as child, \
                        patch.object(run, "observe_runtime", side_effect=observe):
                    report = {**child.cleanup, "success": success}
                    def stop(process, end, *, state, clock):
                        state["returncode"] = 0
                        return report
                    child.stop.side_effect = stop
                    _, error = self.captured(lambda: run.command(["injected-child"], "fake", cap=90))
                    self.assertIsInstance(error, C.RunFailure)
                    child.stop.assert_called_once()
                operations = [e["operation"] for e in run.record["cleanup_errors"]]
                self.assertEqual(operations, ["owned_group_exception" if success else "owned_group"])
                if not success:
                    self.assertEqual(run.record["cleanup_errors"][0]["error"], "RunFailure: " + str(report))

    def test_final_cleanup_return_entry_preserves_recorded_cleanup_failure(self):
        for secondary in self.controls():
            run = self.new_run()
            run.groups = [{"process": Mock(), "record": {"name": "fake", "cleanup": {"success": False}}, "state": {}}]
            report = {"success": False, "returncode": 0}
            real_observe = run.observe_runtime
            def observe(event, *args, **kwargs):
                if event == "final_cleanup_return":
                    raise secondary
                return real_observe(event, *args, **kwargs)
            with self.subTest(secondary=type(secondary).__name__), patch.object(C, "kill_owned", return_value=report) as stop, \
                    patch.object(run, "observe_runtime", side_effect=observe):
                _, error = self.captured(run.cleanup)
                self.assertIsNone(error)
                stop.assert_called_once()
            self.assertEqual(run.record["cleanup_errors"], [{"command": "fake", "final_observation": report}])


if __name__ == "__main__":
    unittest.main()
