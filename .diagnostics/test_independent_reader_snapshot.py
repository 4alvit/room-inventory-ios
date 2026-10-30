"""Independent regression: late reader exit cannot validate an older snapshot."""

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import probe_room_csv as probe


class ReaderSnapshotContracts(unittest.TestCase):
    def test_reader_alive_at_join_deadline_stays_incomplete_after_late_exit(self):
        udid = "E952A9B0-CC78-435C-BF08-06AD47FE1076"
        log = probe.EventLog(5 * probe.MIB)
        complete = b'{"timestamp":"earlier","eventMessage":"kept","subsystem":"com.apple.ShareSheet"}\n'
        partial = b'{"timestamp":"last","eventMessage":"partial'
        log.add(complete)
        log.add(partial)

        # A timed-out join can be followed by a late exit. Repeated liveness
        # queries used to skip finish(), then validate the stale snapshot.
        thread = mock.Mock()
        thread.is_alive.side_effect = [True, True, False]
        eof = threading.Event()
        eof.set()
        logger = mock.Mock(pid=12345, returncode=0)
        logger.poll.return_value = None

        def checked(args, cwd, timeout=30, stage=None):
            if stage.endswith("source_head"):
                return probe.HEAD
            if stage.endswith("source_tree"):
                return probe.TREE
            answers = {
                "precheck.xcode": "Xcode 16.4\nBuild version 16F6",
                "precheck.sdk": "18.5",
                "precheck.simctl_devices": json.dumps({"devices": {
                    "com.apple.CoreSimulator.SimRuntime.iOS-26-2": [{
                        "udid": udid, "name": "iPhone 17 Pro",
                        "isAvailable": True, "state": "Booted",
                    }],
                }}),
                "prepare.xcodegen_install": "/mock/xcodegen",
            }
            return answers.get(stage, "")

        def command(*args, stage=None, **kwargs):
            result = {
                "exit": 0, "timed_out": False, "resource_limited": False,
                "cleanup_ok": True, "primary_error": None,
                "cleanup_errors": [], "dropped_bytes": 0,
            }
            if stage == "test":
                result["admission"] = {"admitted": True}
                for case in probe.CASES:
                    marker = "Test Case '-[RoomInventoryUITests.LocalizationUITests " + case + "]' "
                    args[4]((marker + "started.\n" + marker + "passed (1 seconds).\n").encode())
            if stage == "summary":
                summary = {
                    "totalTestCount": 2, "passedTests": 2,
                    "failedTests": 0, "skippedTests": 0,
                    "devicesAndConfigurations": [{"device": {
                        "deviceId": udid, "osVersion": "26.2",
                    }}],
                }
                return result, json.dumps(summary).encode()
            return result, b""

        with tempfile.TemporaryDirectory() as directory:
            env = {
                "GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS",
                "RUNNER_ARCH": "ARM64", "GITHUB_REPOSITORY": "4alvit/room-inventory-ios",
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_ID": "mock-reader-race",
                "GITHUB_SHA": "mock", "RUNNER_TEMP": directory,
                "GITHUB_OUTPUT": str(Path(directory) / "outputs"),
            }
            with (
                mock.patch.dict(probe.os.environ, env),
                mock.patch.object(probe.sys, "argv", ["mock", directory]),
                mock.patch.object(probe, "ACTIVE_DEADLINE", None),
                mock.patch.object(probe, "checked", side_effect=checked),
                mock.patch.object(probe, "command", side_effect=command),
                mock.patch.object(probe, "stop", return_value=True),
                mock.patch.object(probe, "EventLog", return_value=log),
                mock.patch.object(probe.subprocess, "Popen", return_value=logger),
                mock.patch.object(probe.threading, "Thread", return_value=thread),
                mock.patch.object(probe.threading, "Event", return_value=eof),
                mock.patch.object(probe.os, "killpg", side_effect=AssertionError("No real signals")),
                mock.patch("builtins.print"),
            ):
                self.assertEqual(probe.main(), 1)
            evidence = Path(directory) / "room-csv-once-mock-reader-race/evidence"
            report = json.loads((evidence / "result.json").read_text())
            self.assertEqual((evidence / "share-system-tail.ndjson").read_bytes(), complete)

        self.assertFalse(report["system_log"]["reader_stopped"])
        self.assertFalse(report["system_log"]["reader_reached_eof"])
        self.assertFalse(report["evidence_complete"]["system_log"])
        self.assertFalse(report["evidence_complete"]["overall"])
        self.assertEqual(bytes(log.pending), partial)
        logger.stdout.close.assert_not_called()
        thread.join.assert_called_once_with(timeout=3)


if __name__ == "__main__":
    unittest.main()
