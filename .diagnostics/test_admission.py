import ast
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import probe_room_csv as probe


class Clock:
    def __init__(self, now=386):
        self.now = now
    def __call__(self):
        return self.now


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.process = mock.Mock(pid=12345, returncode=0)
        self.selector = mock.Mock()
        self.selector.get_map.return_value = {}
        self.enterContext(mock.patch.object(probe.time, "monotonic", self.clock))
        self.enterContext(mock.patch.object(probe, "ACTIVE_DEADLINE", 960))
        self.spawn = self.enterContext(mock.patch.object(probe.subprocess, "Popen", return_value=self.process))
        self.select = self.enterContext(mock.patch.object(probe.selectors, "DefaultSelector", return_value=self.selector))
        self.enterContext(mock.patch.object(probe, "stop", return_value=True))

    def run_command(self):
        return probe.command(["fake-test"], ".", timeout=480,
                             stage="test", full_window_reserve=94)[0]

    def test_exact_threshold_admits_full_window_and_reserve(self):
        result = self.run_command()
        self.spawn.assert_called_once()
        self.assertTrue(result["admission"]["admitted"])
        self.assertEqual(result["admission"]["remaining_seconds"], 574)
        self.assertEqual(result["admission"]["command_deadline_monotonic"], 866)
        self.assertEqual(probe.ACTIVE_DEADLINE, 960)
        self.process.wait.assert_called_once_with(timeout=480)

    def test_under_threshold_rejects_before_spawn_without_clamping(self):
        self.clock.now = 386.000001
        result = self.run_command()
        self.spawn.assert_not_called()
        self.select.assert_not_called()
        self.assertFalse(result["admission"]["admitted"])
        self.assertEqual(result["primary_error"]["phase"], "admission")
        self.assertIsNone(result["pid"])
        self.assertFalse(probe.command_ok(result))

    def test_elapsed_setup_cannot_renew_original_deadline(self):
        self.clock.now = 0
        self.assertEqual(probe.ACTIVE_DEADLINE, 960)
        self.clock.now += 400
        result = self.run_command()
        self.spawn.assert_not_called()
        self.assertEqual(result["admission"]["remaining_seconds"], 560)
        self.assertEqual(probe.ACTIVE_DEADLINE, 960)

    def test_missing_original_deadline_fails_closed(self):
        with mock.patch.object(probe, "ACTIVE_DEADLINE", None):
            result = self.run_command()
        self.spawn.assert_not_called()
        self.assertFalse(result["admission"]["admitted"])

    def test_selector_setup_consumes_admitted_window(self):
        def delayed_register(*args):
            self.clock.now += 37
        self.selector.register.side_effect = delayed_register
        result = self.run_command()
        self.assertEqual(result["admission"]["command_deadline_monotonic"], 866)
        self.process.wait.assert_called_once_with(timeout=443)
        self.assertEqual(probe.ACTIVE_DEADLINE, 960)

    def test_spawn_delay_cannot_restart_expired_command_window(self):
        def delayed_spawn(*args, **kwargs):
            self.clock.now += 481
            return self.process
        self.spawn.side_effect = delayed_spawn
        result = self.run_command()
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["admission"]["command_deadline_monotonic"], 866)
        self.process.wait.assert_not_called()
        self.assertEqual(probe.ACTIVE_DEADLINE, 960)

    def test_main_uses_full_window_for_original_two_case_filter(self):
        tree = ast.parse(inspect.getsource(probe.main))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "command"]
        calls = [node for node in calls if any(isinstance(part, ast.Constant)
                 and part.value == "test-without-building" for part in ast.walk(node.args[0]))]
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call.args[2].id, "TEST_WINDOW_SECONDS")
        self.assertEqual(next(k.value.id for k in call.keywords if k.arg == "full_window_reserve"), "POST_TEST_RESERVE_SECONDS")
        self.assertEqual((probe.TEST_WINDOW_SECONDS, probe.POST_TEST_RESERVE_SECONDS), (480, 94))
        self.assertEqual(probe.CASES, ("testPreferredLanguagesAtLaunch", "testRussianCreationEditingAndCSVExportWithUSRegion"))
        self.assertEqual((probe.WORK_SECONDS, probe.FINALIZE_SECONDS), (960, 40))


class AdmissionReportTests(unittest.TestCase):
    def test_main_records_preflight_failure_without_test_spawn_or_summary(self):
        clock = Clock(0)
        real_command = probe.command
        stages = []
        udid = "E952A9B0-CC78-435C-BF08-06AD47FE1076"
        def checked(args, cwd, timeout=30, stage=None):
            if stage.endswith("source_head"):
                return probe.HEAD
            if stage.endswith("source_tree"):
                return probe.TREE
            return {"precheck.xcode": "Xcode 16.4\nBuild version 16F6", "precheck.sdk": "18.5",
                    "precheck.simctl_devices": json.dumps({"devices": {
                        "com.apple.CoreSimulator.SimRuntime.iOS-26-2": [{"udid": udid,
                        "name": "iPhone 17 Pro", "isAvailable": True, "state": "Booted"}]}}),
                    "prepare.xcodegen_install": "/fake/xcodegen"}.get(stage, "")
        def command(*args, stage=None, **kwargs):
            stages.append(stage)
            if stage == "test":
                clock.now = 387
                return real_command(*args, stage=stage, **kwargs)
            self.assertEqual(stage, "build")
            return {"exit": 0, "timed_out": False, "resource_limited": False,
                    "cleanup_ok": True, "primary_error": None, "cleanup_errors": [], "dropped_bytes": 0}, b""
        logger = mock.Mock(pid=12345, returncode=0)
        thread = mock.Mock()
        thread.is_alive.return_value = False
        with tempfile.TemporaryDirectory() as directory:
            env = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64",
                   "GITHUB_REPOSITORY": "4alvit/room-inventory-ios", "GITHUB_RUN_ATTEMPT": "1",
                   "GITHUB_RUN_ID": "mock-admission", "GITHUB_SHA": "mock", "RUNNER_TEMP": directory,
                   "GITHUB_OUTPUT": str(Path(directory) / "outputs")}
            with mock.patch.dict(probe.os.environ, env), mock.patch.object(probe.sys, "argv", ["mock", directory]), mock.patch.object(probe.time, "monotonic", clock), mock.patch.object(probe, "checked", side_effect=checked), mock.patch.object(probe, "command", side_effect=command), mock.patch.object(probe, "stop", return_value=True), mock.patch.object(probe.threading, "Thread", return_value=thread), mock.patch.object(probe.subprocess, "Popen", return_value=logger) as spawn, mock.patch("builtins.print"):
                self.assertEqual(probe.main(), 1)
                spawn.assert_called_once()  # Logger only, never xcodebuild test.
            report = json.loads((Path(directory) / "room-csv-once-mock-admission/evidence/result.json").read_text())
        self.assertEqual(stages, ["build", "test"])
        self.assertEqual(report["status"], "PREFLIGHT_FAILED_INSUFFICIENT_TEST_BUDGET")
        self.assertIsNone(report["commands"]["test"]["pid"])
        self.assertFalse(report["commands"]["test"]["admission"]["admitted"])
        self.assertFalse(report["software_acceptance"])


if __name__ == "__main__":
    unittest.main()
