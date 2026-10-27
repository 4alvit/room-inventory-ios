"""Exception attribution only; all process, timer and signal APIs are fakes."""
from copy import deepcopy
import json
from pathlib import Path
import signal
import tarfile
import unittest
from unittest.mock import Mock, call, patch

import test_recovery_controller as fixtures
import test_recovery_retention as retention_fixtures

controller = fixtures.controller


def caught_failure(depth=0):
    def nested(remaining):
        if remaining:
            nested(remaining - 1)
        else:
            controller.require(False, "secret-argument /private/host/path", controller.DeadlineFailure)
    try:
        nested(depth)
    except controller.DeadlineFailure as error:
        return error


class ExceptionOriginTests(unittest.TestCase):
    def test_known_origin_is_source_line_without_values_locals_or_paths(self):
        error = caught_failure()
        with patch.object(Path, "open", side_effect=AssertionError("no source reads")), \
                patch.object(controller.subprocess, "Popen", side_effect=AssertionError("no processes")), \
                patch.object(controller.signal, "setitimer", side_effect=AssertionError("no timer")):
            observation = controller.exception_origin(error, "operation", "precommand")
        self.assertEqual(observation["frames"][-1], {
            "source": "run-recovery-journey.py", "line": controller.require.__code__.co_firstlineno + 2})
        self.assertTrue(observation["origin_known"])
        self.assertTrue(observation["unmapped_frames"])
        self.assertFalse(observation["frames_truncated"])
        self.assertEqual(observation["reason"], "deadline")
        serialized = json.dumps(observation)
        for value in ("secret-argument", "/private", str(Path(__file__).parent), "nested", "remaining"):
            self.assertNotIn(value, serialized)

    def test_frame_limit_marks_omitted_prefix_but_known_innermost_origin(self):
        observation = controller.exception_origin(caught_failure(12), "operation", "build")
        self.assertEqual(len(observation["frames"]), 8)
        self.assertTrue(observation["frames_truncated"])
        self.assertFalse(observation["tail_unvisited"])
        self.assertTrue(observation["origin_known"])

    def test_visit_limit_marks_unvisited_tail_and_never_invents_innermost_origin(self):
        observation = controller.exception_origin(caught_failure(50), "operation", "build")
        self.assertEqual(len(observation["frames"]), 8)
        self.assertTrue(observation["frames_truncated"])
        self.assertTrue(observation["tail_unvisited"])
        self.assertFalse(observation["origin_known"])
        self.assertTrue(all(frame == {"source": "external", "line": 0} for frame in observation["frames"]))

    def test_missing_traceback_and_untrusted_labels_are_explicit_unknown(self):
        observation = controller.exception_origin(ValueError("secret"), "/private/site", "secret" * 1000)
        self.assertEqual(observation["frames"], [])
        self.assertTrue(observation["traceback_unavailable"])
        self.assertFalse(observation["origin_known"])
        self.assertEqual(observation["capture_site"], "unknown")
        self.assertEqual(observation["last_stage"], "unknown")
        self.assertNotIn("secret", json.dumps(observation))

    def test_external_filename_and_function_name_are_never_exported(self):
        namespace = {}
        exec(compile("def private_secret_function():\n raise ValueError('secret')\n", "/private/" + "secret" * 100, "exec"), namespace)
        try:
            namespace["private_secret_function"]()
        except ValueError as error:
            observation = controller.exception_origin(error, "command", "command_wait")
        self.assertFalse(observation["origin_known"])
        self.assertTrue(observation["unmapped_frames"])
        self.assertNotIn("secret", json.dumps(observation))
        self.assertNotIn("/", json.dumps(observation))

    def test_exception_values_and_chains_are_not_inspected(self):
        class UnprintableError(Exception):
            def __str__(self):
                raise AssertionError("must not format exception")
        error = UnprintableError("secret")
        error.__cause__ = error
        observation = controller.exception_origin(error, "command", "command_wait")
        self.assertEqual(observation["reason"], "exception")
        self.assertNotIn("secret", json.dumps(observation))

    def test_constructive_worst_case_is_below_2kib_in_every_receipt_location(self):
        observation = controller.exception_origin(caught_failure(), "command_cleanup", "device_initial_state")
        # Bounds come from fixed source names, integer range and closed labels;
        # even eight maximal frames at the deepest actual JSON location fit.
        observation["frames"] = [{"source": max(controller.ORIGIN_SOURCES.values(), key=len), "line": 9999999}] * 8
        for stage in controller.ORIGIN_STAGES:
            observation["last_stage"] = stage
            for location in ("top", "command", "cleanup", "finalization"):
                before = {"commands": [{}], "cleanup_errors": [{}], "finalization_error": {}}
                after = deepcopy(before)
                target = {"top": after, "command": after["commands"][0], "cleanup": after["cleanup_errors"][0],
                          "finalization": after["finalization_error"]}[location]
                target["exception_origin"] = observation
                added = len(json.dumps(after, indent=2).encode("ascii")) - len(json.dumps(before, indent=2).encode("ascii"))
                self.assertLessEqual(added, 2048, (stage, location, added))


class ExceptionOriginIntegrationTests(fixtures.ControllerCase):
    fake_child = fixtures.CommandFailureTests.fake_child

    def staged_run(self):
        run = self.run_fixture()
        for name in ("prepare", "build", "prepare_device", "test_and_collect", "cleanup"):
            setattr(run, name, Mock())
        run.flush = Mock()
        run.guard = Mock()
        return run

    @staticmethod
    def preserve_exit(child):
        def stop(process, end, *, state, clock):
            state["returncode"] = child.cleanup["returncode"]
            return child.cleanup
        child.stop.side_effect = stop

    def test_precommand_guard_failure_has_origin_without_starting_a_child(self):
        run = self.staged_run()
        run.build.side_effect = lambda: run.command(["never-executed"], "fake", cap=90)
        run.guard.side_effect = lambda: controller.require(False, "deadline", controller.DeadlineFailure)
        self.assertEqual(run.execute(), 124)
        self.assertEqual(run.record["exception_origin"]["last_stage"], "precommand")
        self.assertEqual(run.record["exception_origin"]["frames"][-1]["source"], "run-recovery-journey.py")
        self.assertEqual(run.record["primary_error"], {"type": "DeadlineFailure", "message": "deadline"})
        self.assertEqual(run.record["commands"], [])
        self.popen.assert_not_called()
        run.prepare_device.assert_not_called()
        run.cleanup.assert_called_once()
        run.flush.assert_called_once()

    def test_receipt_deadline_after_exit_zero_stays_failure_with_separate_origin(self):
        run = self.staged_run()
        run.build.side_effect = lambda: run.command(["injected-child"], "fake-boot-status", cap=90)
        receipts = []
        def flush():
            receipts.append(deepcopy(run.record))
            if len(receipts) == 2:
                controller.require(False, "receipt deadline", controller.DeadlineFailure)
        run.flush.side_effect = flush
        with self.fake_child() as child:
            self.preserve_exit(child)
            self.assertEqual(run.execute(), 124)
            child.start.assert_called_once()
            child.stop.assert_called_once()
            child.process.wait.assert_called_once_with(timeout=0)
            child.selector.close.assert_called_once()
            for stream in child.log_streams + [child.process.stdout, child.process.stderr]:
                stream.close.assert_called_once()
        command = run.record["commands"][0]
        self.assertEqual(command["exit_code"], 0)
        self.assertIsNone(command["primary_error"])
        self.assertTrue(command["cleanup"]["success"])
        self.assertEqual(run.record["primary_error"], {"type": "DeadlineFailure", "message": "receipt deadline"})
        origin = run.record["cleanup_errors"][0]["exception_origin"]
        self.assertEqual(origin["capture_site"], "command_cleanup")
        self.assertEqual(origin["last_stage"], "command_receipt")
        self.assertTrue(origin["origin_known"])
        # The outer observation honestly records the later finally/return stage.
        self.assertEqual(run.record["exception_origin"]["last_stage"], "command_return")
        self.assertEqual(command["end_deadline_elapsed"], 90)
        self.assertEqual(run.flush.call_count, 3)
        self.assertEqual(len(run.record["commands"]), 1)
        run.prepare_device.assert_not_called()
        run.test_and_collect.assert_not_called()
        run.cleanup.assert_called_once()
        self.assertEqual(self.signal_mask.call_args_list, [call(signal.SIG_BLOCK, {signal.SIGALRM}), call(signal.SIG_SETMASK, set())])
        timer_values = [call.args[1] for call in self.timers.call_args_list]
        # Separate phase-bound accounting arm, then the existing receipt arm.
        self.assertEqual(timer_values, [116, 86, 86, 0, 90, 90, 90, 90, 90, 90, 0, 120, 120, 0, 1800, 0])
        self.assertEqual(self.handlers.call_args_list[-1].args, (signal.SIGALRM, self.previous_handler))

    def test_loop_failure_keeps_original_exception_and_owned_cleanup(self):
        run = self.run_fixture()
        original = caught_failure()
        run.flush = Mock()
        run.guard = Mock(side_effect=lambda: (_ for _ in ()).throw(original) if run.groups else None)
        with self.fake_child(active=True) as child:
            self.preserve_exit(child)
            with self.assertRaises(controller.DeadlineFailure) as raised:
                run.command(["injected-child"], "fake", cap=90)
            child.stop.assert_called_once()
            child.start.assert_called_once()
        self.assertIs(raised.exception, original)
        command = run.record["commands"][0]
        self.assertEqual(command["exception_origin"]["last_stage"], "command_loop")
        self.assertEqual(command["exit_code"], 0)
        self.assertTrue(command["cleanup"]["success"])
        self.assertEqual(command["primary_error"], {"type": "DeadlineFailure", "message": str(original)})
        self.assertEqual(run.flush.call_count, 2)

    def test_diagnostic_failure_or_interruption_cannot_replace_primary_or_skip_cleanup(self):
        for secondary in (TypeError("diagnostic"), controller.DeadlineFailure("secondary"), KeyboardInterrupt("secondary")):
            with self.subTest(secondary=type(secondary).__name__):
                run = controller.RecoveryRun(self.grant(), clock=self.clock)
                run.output.mkdir(exist_ok=True)
                run.flush = Mock()
                original = caught_failure()
                run.guard = Mock(side_effect=lambda: (_ for _ in ()).throw(original) if run.groups else None)
                with self.fake_child(active=True) as child, patch.object(controller, "exception_origin", side_effect=secondary) as diagnose:
                    self.preserve_exit(child)
                    with self.assertRaises(controller.DeadlineFailure) as raised:
                        run.command(["injected-child"], "fake", cap=90)
                    child.stop.assert_called_once()
                    child.start.assert_called_once()
                    diagnose.assert_called_once()
                self.assertIs(raised.exception, original)
                self.assertTrue(run.record["commands"][0]["cleanup"]["success"])
                self.assertNotIn("exception_origin", run.record["commands"][0])
                self.assertEqual(run.record["cleanup_errors"], [])
                self.assertEqual(run.flush.call_count, 2)

    def test_alarm_after_group_cleanup_has_top_origin_despite_null_command_primary(self):
        run = self.staged_run()
        run.build.side_effect = lambda: run.command(["injected-child"], "fake-boot-status", cap=90)
        original_disarm, disarms = run.disarm, 0
        def interrupted_disarm():
            nonlocal disarms
            original_disarm()
            disarms += 1
            if disarms == 2:
                # Inject at the existing unprotected boundary after owned-group
                # cleanup. This models attribution, not the historical cause.
                self.handlers.call_args_list[0].args[1](signal.SIGALRM, None)
        run.disarm = Mock(side_effect=interrupted_disarm)
        with self.fake_child() as child:
            self.preserve_exit(child)
            self.assertEqual(run.execute(), 124)
            child.start.assert_called_once()
            child.stop.assert_called_once()
            child.process.wait.assert_called_once_with(timeout=0)
        command = run.record["commands"][0]
        self.assertEqual(command["exit_code"], 0)
        self.assertIsNone(command["primary_error"])
        self.assertNotIn("exception_origin", command)
        self.assertTrue(command["cleanup"]["success"])
        self.assertEqual(run.record["cleanup_errors"], [])
        self.assertEqual(run.record["primary_error"], {"type": "DeadlineFailure", "message": "Absolute operation deadline reached"})
        self.assertEqual(run.record["exception_origin"]["last_stage"], "group_cleanup")
        self.assertTrue(run.record["exception_origin"]["origin_known"])
        self.assertEqual(run.record["exception_origin"]["frames"][-1]["source"], "run-recovery-journey.py")
        self.assertEqual(run.flush.call_count, 2)
        run.prepare_device.assert_not_called()
        run.test_and_collect.assert_not_called()
        run.cleanup.assert_called_once()
        self.assertEqual(self.handlers.call_args_list[-1].args, (signal.SIGALRM, self.previous_handler))

    def test_three_device_cleanup_failures_keep_unknown_state_and_original_commands(self):
        run = self.run_fixture()
        run.device_id = "12345678-1234-4234-8234-123456789ABC"
        run.command = Mock(side_effect=lambda *args, **kwargs: controller.require(False, "deadline", controller.DeadlineFailure))
        with patch.object(controller, "kill_owned", side_effect=AssertionError("no owned group")):
            run.cleanup()
        self.assertEqual([call.args[1] for call in run.command.call_args_list],
                         ["device-cleanup-before", "shutdown-owned-device", "device-final-state"])
        self.assertEqual([call.kwargs["cap"] for call in run.command.call_args_list], [10, 25, 15])
        self.assertNotIn("device_final_state", run.record)
        self.assertEqual([item["operation"] for item in run.record["cleanup_errors"]], ["initial_state", "shutdown", "final_state"])
        self.assertEqual([item["exception_origin"]["last_stage"] for item in run.record["cleanup_errors"]],
                         ["device_initial_state", "device_shutdown", "device_final_state"])
        self.assertTrue(all(item["exception_origin"]["origin_known"] for item in run.record["cleanup_errors"]))
        self.popen.assert_not_called()

    def test_installed_alarm_handler_is_unmodified_and_capture_runs_after_handler_returns(self):
        run = self.staged_run()
        real_diagnose = controller.exception_origin
        in_handler = False
        def during_prepare():
            nonlocal in_handler
            in_handler = True
            try:
                self.handlers.call_args_list[0].args[1](signal.SIGALRM, None)
            finally:
                in_handler = False
        def diagnose(*args):
            self.assertFalse(in_handler)
            return real_diagnose(*args)
        run.prepare.side_effect = during_prepare
        with patch.object(controller, "exception_origin", side_effect=diagnose) as capture:
            self.assertEqual(run.execute(), 124)
            capture.assert_called_once()
        self.assertEqual(run.record["primary_error"], {"type": "DeadlineFailure", "message": "Absolute operation deadline reached"})
        self.assertEqual(run.record["exception_origin"]["last_stage"], "prepare")
        self.assertTrue(run.record["exception_origin"]["origin_known"])
        run.build.assert_not_called()
        run.cleanup.assert_called_once()
        self.popen.assert_not_called()

    def test_final_receipt_error_does_not_overwrite_primary_or_claim_durable_observation(self):
        run = self.staged_run()
        original = controller.ConfigurationFailure("primary")
        run.prepare.side_effect = original
        run.flush.side_effect = lambda: controller.require(False, "final deadline", controller.DeadlineFailure)
        self.assertEqual(run.execute(), 124)
        self.assertEqual(run.record["primary_error"], {"type": "ConfigurationFailure", "message": "primary"})
        self.assertEqual(run.record["finalization_error"]["exception_origin"]["last_stage"], "final_receipt")
        self.assertEqual(run.record["status"], "FAIL")
        run.cleanup.assert_called_once()
        run.flush.assert_called_once()
        self.assertFalse((run.output / "result.json").exists())
        self.popen.assert_not_called()


class ExceptionOriginRetentionTests(unittest.TestCase):
    def fixture(self):
        fixture = retention_fixtures.RecoveryRetentionTests("test_complete_packet_preserves_raw_bytes_and_omits_live_state")
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def test_additive_observation_survives_retention_without_changing_validity(self):
        fixture = self.fixture()
        fixture.result["exception_origin"] = controller.exception_origin(caught_failure(), "operation", "command_return")
        raw = retention_fixtures.R.encoded(fixture.result)
        fixture.write("run/result.json", raw)
        with patch.object(controller.subprocess, "Popen", side_effect=AssertionError("no native tools")):
            report = fixture.package()
        # Diagnostics are metadata, never a replacement for existing gates.
        self.assertTrue(report["complete"], report["failures"])
        with tarfile.open(fixture.upload / "evidence.tar") as archive:
            self.assertEqual(archive.extractfile("run/result.json").read(), raw)

    def test_failed_exit_zero_child_receipt_remains_incomplete_and_is_retained(self):
        fixture = self.fixture()
        fixture.result.update(status="FAIL", exit_code=124, primary_error={"type": "DeadlineFailure", "message": "deadline"},
                              exception_origin=controller.exception_origin(caught_failure(), "operation", "command_return"))
        fixture.context.update(controller_exit_code=124, primary_error=fixture.result["primary_error"])
        raw = retention_fixtures.R.encoded(fixture.result)
        fixture.write("run/result.json", raw)
        with patch.object(controller.subprocess, "Popen", side_effect=AssertionError("no native tools")):
            report = fixture.package()
        self.assertFalse(report["complete"])
        with tarfile.open(fixture.upload / "evidence.tar") as archive:
            self.assertEqual(archive.extractfile("run/result.json").read(), raw)


if __name__ == "__main__":
    unittest.main()
