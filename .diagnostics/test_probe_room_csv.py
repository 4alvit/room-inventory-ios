import unittest
import ast
import inspect
import errno
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock
import probe_room_csv as probe


class ProbeContracts(unittest.TestCase):
    def test_single_pass_command_omits_repetition_options(self):
        tree = ast.parse(inspect.getsource(probe.main))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "command"]
        test_calls = [node for node in calls if any(isinstance(part, ast.Constant)
                      and part.value == "test-without-building" for part in ast.walk(node.args[0]))]
        self.assertEqual(len(test_calls), 1)
        flags = {part.value for part in ast.walk(test_calls[0].args[0])
                 if isinstance(part, ast.Constant) and isinstance(part.value, str)}
        self.assertIn("-only-testing:RoomInventoryUITests/LocalizationUITests", flags)
        self.assertFalse(flags & {"-test-iterations", "-retry-tests-on-failure", "-run-tests-until-failure"})

    def test_expired_global_budget_never_starts_another_process(self):
        with mock.patch.object(probe, "ACTIVE_DEADLINE", 0), mock.patch.object(probe.subprocess, "Popen") as popen:
            result, data = probe.command(["must-not-start"], ".")
            popen.assert_not_called()
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["primary_error"]["phase"], "budget")
        self.assertIsNone(result["pid"])
        self.assertFalse(probe.command_ok(result))

    def test_logger_header_is_not_a_recorded_system_event(self):
        self.assertEqual(probe.event_count(b'Filtering the log data\n{"eventMessage":"no timestamp"}'), 0)
        self.assertEqual(probe.event_count(b'header\n{"timestamp":"now","eventMessage":"hello"}\n'), 1)

    def test_exited_leader_still_requires_group_absence_without_signals(self):
        process = mock.Mock(pid=12345, returncode=0)
        evidence = {}
        with mock.patch.object(probe.os, "killpg", side_effect=ProcessLookupError(errno.ESRCH, "absent")) as kill:
            self.assertTrue(probe.stop(process, evidence))
        self.assertEqual(kill.call_args_list, [mock.call(12345, 0)])
        self.assertTrue(evidence["leader_reaped"])
        self.assertEqual(evidence["group_state"], "absent")
        self.assertEqual(evidence["leader_cached_returncode_before"], 0)
        process.wait.assert_not_called()

    def test_tail_is_bounded_and_accounts_for_all_omitted_bytes(self):
        tail = probe.Tail(5)
        tail.add(b"abc")
        tail.add(b"defghij")
        self.assertEqual(bytes(tail.data), b"fghij")
        self.assertEqual(tail.dropped, 5)

    def test_exact_runtime_and_model_ignore_booted_other_runtime(self):
        wanted = {"udid": "E952A9B0-CC78-435C-BF08-06AD47FE1076", "isAvailable": True, "name": "iPhone 17 Pro"}
        data = {"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-26-2": [wanted],
                            "com.apple.CoreSimulator.SimRuntime.iOS-18-5": [dict(wanted, state="Booted")]}}
        self.assertEqual(probe.select_device(data), wanted)

    def test_no_runtime_substitution(self):
        with self.assertRaises(RuntimeError):
            probe.select_device({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-5": []}})

    def test_ambiguous_and_unavailable_devices_fail_closed(self):
        wanted = {"udid": "E952A9B0-CC78-435C-BF08-06AD47FE1076", "isAvailable": True, "name": "iPhone 17 Pro"}
        for devices in ([wanted, wanted], [dict(wanted, isAvailable=False)]):
            with self.assertRaises(RuntimeError):
                probe.select_device({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-26-2": devices}})

    def test_summary_requires_two_executed_tests_and_matching_outcomes(self):
        summary = {"totalTestCount": 2, "skippedTests": 0, "passedTests": 1, "failedTests": 1,
                   "devicesAndConfigurations": [{"device": {"deviceId": "device", "osVersion": "26.2"}}]}
        outcomes = dict(zip(probe.CASES, ("passed", "failed")))
        self.assertTrue(probe.summary_valid(summary, "device", outcomes))
        for change in ({"skippedTests": 1}, {"totalTestCount": 3}, {"passedTests": 2}, {"expectedFailures": 1}):
            self.assertFalse(probe.summary_valid(dict(summary, **change), "device", outcomes))
        self.assertFalse(probe.summary_valid(summary, "different-device", outcomes))
        self.assertFalse(probe.summary_valid(summary, "device", {probe.CASES[0]: "passed"}))

    def test_failure_attachments_preferred_to_earlier_success_and_unrelated_video(self):
        names = ["ru-csv-share_0.png", "ru-csv-share-accessibility_0.txt", "ru-csv-share-failure_0.png",
                 "ru-csv-share-failure-accessibility_0.txt", "Screen Recording.mp4"]
        manifest = [{"attachments": [{"suggestedHumanReadableName": n, "exportedFileName": str(i)} for i, n in enumerate(names)]}]
        chosen = probe.choose_attachments(manifest)
        self.assertEqual([item[0]["exportedFileName"] for item in chosen], ["2", "3"])
        self.assertEqual([item[1] for item in chosen], ["share.png", "share-ax.txt"])

    def test_duplicate_attachment_is_not_guessed(self):
        item = {"suggestedHumanReadableName": "ru-csv-share-failure_0.png", "exportedFileName": "a"}
        self.assertEqual(probe.choose_attachments([item, item]), [])


class CleanupFailureContracts(unittest.TestCase):
    def setUp(self):
        self.process = mock.Mock(pid=12345, returncode=0)
        self.selector = mock.Mock()
        self.selector.get_map.return_value = {}
        self.enterContext(mock.patch.object(probe, "ACTIVE_DEADLINE", None))
        self.spawn = self.enterContext(mock.patch.object(probe.subprocess, "Popen", return_value=self.process))
        self.enterContext(mock.patch.object(probe.selectors, "DefaultSelector", return_value=self.selector))
        self.stop = self.enterContext(mock.patch.object(probe, "stop", side_effect=PermissionError(errno.EPERM, "signal denied")))

    def read_event(self, payload=None, error=None):
        self.selector.get_map.return_value = {7: True}
        self.selector.select.return_value = [(SimpleNamespace(fd=7, fileobj=self.process.stdout), 1)]
        return self.enterContext(mock.patch.object(probe.os, "read", return_value=payload, side_effect=error))

    def test_successful_exit_with_permission_denied_cleanup_is_failure(self):
        result, data = probe.command(["xcrun", "simctl", "list"], "/source", stage="precheck.simctl_devices")
        self.assertEqual(result["exit"], 0)
        self.assertIsNone(result["primary_error"])
        self.assertEqual(result["cleanup_errors"][0]["phase"], "stop")
        self.assertEqual(result["cleanup_errors"][0]["errno"], errno.EPERM)
        self.assertFalse(result["cleanup_ok"])
        self.assertFalse(probe.command_ok(result))
        self.assertEqual((result["pid"], result["pgid"]), (12345, 12345))
        self.assertEqual(result["stage"], "precheck.simctl_devices")
        self.assertEqual(result["command"], ["xcrun", "simctl", "list"])
        self.selector.close.assert_called_once_with()
        self.process.stdout.close.assert_called_once_with()

    def test_primary_read_error_and_each_cleanup_error_are_preserved_separately(self):
        self.read_event(error=OSError(errno.EIO, "read failed"))
        self.selector.close.side_effect = OSError(errno.EIO, "selector close failed")
        self.process.stdout.close.side_effect = OSError(errno.EBADF, "pipe close failed")
        result, data = probe.command(["fake"], ".")
        self.assertEqual(result["primary_error"]["phase"], "read")
        self.assertEqual(result["primary_error"]["errno"], errno.EIO)
        self.assertEqual([e["phase"] for e in result["cleanup_errors"]], ["stop", "selector_close", "stdout_close"])
        self.process.stdout.close.assert_called_once_with()
        self.assertFalse(probe.command_ok(result))

    def test_timeout_flag_survives_cleanup_permission_error(self):
        self.selector.get_map.return_value = {7: True}
        with mock.patch.object(probe.time, "monotonic", side_effect=[0, 0, 2]):
            result, data = probe.command(["fake"], ".", timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertIsNone(result["primary_error"])
        self.assertEqual(result["cleanup_errors"][0]["errno"], errno.EPERM)
        self.process.wait.assert_not_called()
        self.process.stdout.close.assert_called_once_with()

    def test_partial_output_stays_bounded_when_callback_and_cleanup_fail(self):
        self.read_event(payload=b"0123456789abcdef")
        callback = mock.Mock(side_effect=ValueError("observer failed"))
        result, data = probe.command(["fake"], ".", cap=4, on_chunk=callback)
        self.assertEqual(data, b"cdef")
        self.assertEqual(result["dropped_bytes"], 12)
        self.assertEqual(result["primary_error"]["phase"], "output_callback")
        self.assertEqual(len(result["cleanup_errors"]), 1)

    def test_spawn_denied_has_no_cleanup_attempt_or_invented_pid(self):
        self.spawn.side_effect = PermissionError(errno.EPERM, "spawn denied")
        result, data = probe.command(["fake"], ".")
        self.assertEqual(result["primary_error"]["phase"], "spawn")
        self.assertIsNone(result["pid"])
        self.assertIsNone(result["pgid"])
        self.stop.assert_not_called()
        self.selector.close.assert_not_called()
        self.assertFalse(probe.command_ok(result))

    def test_checked_carries_structured_failure_instead_of_hiding_cleanup(self):
        with self.assertRaises(probe.CommandFailure) as caught:
            probe.checked(["fake"], ".", stage="precheck.simctl_devices")
        result = caught.exception.result
        self.assertEqual(result["stage"], "precheck.simctl_devices")
        self.assertEqual(result["cleanup_errors"][0]["phase"], "stop")
        self.assertFalse(probe.command_ok(result))

    def test_main_retains_precheck_failure_when_final_verification_also_fails(self):
        def failure(stage, message):
            return probe.CommandFailure({"stage": stage, "exit": 0, "pid": 12345, "pgid": 12345,
                "command": ["fake"], "timed_out": True, "resource_limited": False,
                "cleanup_ok": False, "primary_error": None,
                "cleanup_errors": [probe.error_record("stop", PermissionError(errno.EPERM, message))],
                "dropped_bytes": 0}, b"retained output")
        def checked(args, cwd, timeout=30, stage=None):
            answers = {"precheck.source_head": probe.HEAD, "precheck.source_tree": probe.TREE,
                       "precheck.source_diff": "", "precheck.xcode": "Xcode 16.4\nBuild version 16F6", "precheck.sdk": "18.5"}
            if stage in answers:
                return answers[stage]
            if stage == "precheck.simctl_devices":
                raise failure(stage, "original cleanup error")
            if stage == "final.source_head":
                raise failure(stage, "later verification error")
            self.fail("Unexpected command stage: " + str(stage))
        with tempfile.TemporaryDirectory() as directory:
            env = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64",
                   "GITHUB_REPOSITORY": "4alvit/room-inventory-ios", "GITHUB_RUN_ATTEMPT": "1",
                   "GITHUB_RUN_ID": "mock-only", "GITHUB_SHA": "mock-only", "RUNNER_TEMP": directory,
                   "GITHUB_OUTPUT": str(Path(directory) / "outputs")}
            with mock.patch.dict(probe.os.environ, env), mock.patch.object(probe.sys, "argv", ["mock", directory]), mock.patch.object(probe, "checked", side_effect=checked), mock.patch("builtins.print"):
                self.assertEqual(probe.main(), 1)
            report = json.loads((Path(directory) / "room-csv-once-mock-only/evidence/result.json").read_text())
        self.spawn.assert_not_called()
        self.assertEqual(report["error"], "Command failed at precheck.simctl_devices")
        self.assertEqual(report["failed_command_stage"], "precheck.simctl_devices")
        self.assertIn("precheck.simctl_devices", report["commands"])
        self.assertIn("final.source_head", report["commands"])
        self.assertTrue(report["commands"]["precheck.simctl_devices"]["timed_out"])
        self.assertEqual(report["status"], "SOURCE_PIN_INVALID")
        self.assertFalse(report["software_acceptance"])

    def test_unstarted_logger_thread_does_not_mask_start_error_or_skip_pipe_close(self):
        device = {"udid": "E952A9B0-CC78-435C-BF08-06AD47FE1076", "name": "iPhone 17 Pro",
                  "isAvailable": True, "state": "Booted"}
        def checked(args, cwd, timeout=30, stage=None):
            if stage.endswith("source_head"):
                return probe.HEAD
            if stage.endswith("source_tree"):
                return probe.TREE
            return {"precheck.xcode": "Xcode 16.4\nBuild version 16F6", "precheck.sdk": "18.5",
                    "precheck.simctl_devices": json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-26-2": [device]}}),
                    "prepare.xcodegen_install": "/fake/xcodegen"}.get(stage, "")
        thread = mock.Mock()
        thread.start.side_effect = RuntimeError("cannot start new thread")
        thread.join.side_effect = RuntimeError("cannot join thread before it is started")
        thread.is_alive.return_value = False
        self.stop.side_effect = None
        self.stop.return_value = True
        good = {"exit": 0, "timed_out": False, "resource_limited": False, "cleanup_ok": True,
                "primary_error": None, "cleanup_errors": [], "dropped_bytes": 0}
        with tempfile.TemporaryDirectory() as directory:
            env = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64",
                   "GITHUB_REPOSITORY": "4alvit/room-inventory-ios", "GITHUB_RUN_ATTEMPT": "1",
                   "GITHUB_RUN_ID": "mock-logger", "GITHUB_SHA": "mock-only", "RUNNER_TEMP": directory,
                   "GITHUB_OUTPUT": str(Path(directory) / "outputs")}
            with mock.patch.dict(probe.os.environ, env), mock.patch.object(probe.sys, "argv", ["mock", directory]), mock.patch.object(probe, "checked", side_effect=checked), mock.patch.object(probe, "command", return_value=(good, b"")), mock.patch.object(probe.threading, "Thread", return_value=thread), mock.patch("builtins.print"):
                self.assertEqual(probe.main(), 1)
            report = json.loads((Path(directory) / "room-csv-once-mock-logger/evidence/result.json").read_text())
        self.assertEqual(report["error"], "cannot start new thread")
        self.assertEqual(report["system_log"]["cleanup_errors"][0]["phase"], "logger_join")
        self.assertFalse(report["system_log"]["cleanup_ok"])
        self.process.stdout.close.assert_called_once_with()
        self.assertFalse(report["software_acceptance"])


if __name__ == "__main__":
    unittest.main()
