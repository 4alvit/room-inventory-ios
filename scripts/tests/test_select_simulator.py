"""Automatic test destinations must stay on the active SDK's runtime line."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("select_simulator", ROOT / "scripts/select-simulator.py")
SELECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECT)

FIRST = "11111111-1111-1111-1111-111111111111"
SECOND = "22222222-2222-2222-2222-222222222222"
THIRD = "33333333-3333-3333-3333-333333333333"


def device(udid=FIRST, *, name="iPhone 17", state="Shutdown", available=True):
    return {"name": name, "udid": udid, "state": state, "isAvailable": available}


def inventory(**runtimes):
    return {"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-" + version.replace("_", "-"): devices
                        for version, devices in runtimes.items()}}


class SimulatorSelectionTests(unittest.TestCase):
    def test_newer_installed_and_booted_older_runtime_do_not_override_sdk(self):
        source = inventory(**{"26_4": [device()], "26_5": [device(SECOND)],
                              "18_5": [device(THIRD, state="Booted")]})
        self.assertEqual(SELECT.select_simulator(source, "26.4"), FIRST)

    def test_highest_patch_wins_before_booted_preference(self):
        source = inventory(**{"26_4": [device(state="Booted")],
                              "26_4_1": [device(SECOND)], "26_4_2": [device(THIRD)]})
        self.assertEqual(SELECT.select_simulator(source, "26.4.0"), THIRD)

    def test_booted_device_wins_within_same_runtime(self):
        source = inventory(**{"26_4": [device(state="Booted"), device(SECOND)]})
        self.assertEqual(SELECT.select_simulator(source, "26.4"), FIRST)

    def test_ties_are_stable_across_inventory_order(self):
        for devices in ([device(), device(SECOND)], [device(SECOND), device()]):
            self.assertEqual(SELECT.select_simulator(inventory(**{"26_4": devices}), "26.4"), SECOND)

    def test_explicit_available_iphone_can_override_sdk_without_querying_it(self):
        source = inventory(**{"27_0": [device()], "26_4": [device(SECOND)]})
        self.assertEqual(SELECT.select_simulator(source, "26.4", FIRST), FIRST)
        self.assertEqual(SELECT.select_simulator(source, None, FIRST), FIRST)
        with patch.dict(os.environ, {"SIMULATOR_UDID": FIRST}), \
                patch.object(SELECT.subprocess, "check_output", return_value=json.dumps(source)) as command, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            SELECT.main()
        self.assertEqual(output.getvalue(), FIRST + "\n")
        command.assert_called_once_with(
            ["xcrun", "simctl", "list", "devices", "available", "--json"],
            text=True, stdin=subprocess.DEVNULL, timeout=60,
        )

    def test_unavailable_non_iphone_old_and_malformed_candidates_are_rejected(self):
        cases = [
            inventory(**{"26_4": [device(available=False)]}),
            inventory(**{"26_4": [device(name="iPad Pro")]}),
            inventory(**{"16_4": [device()]}),
            inventory(**{"26_4_beta": [device()]}),
            inventory(**{"26_4": [device("not-a-udid")]}),
            inventory(**{"26_4": [device(available="true")]}),
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "SIMULATOR_UDID"):
                SELECT.select_simulator(source, "26.4", FIRST)
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "No available"):
                SELECT.select_simulator(source, "26.4")

    def test_no_matching_runtime_fails_instead_of_silently_switching(self):
        source = inventory(**{"26_5": [device(state="Booted")]})
        with self.assertRaisesRegex(ValueError, "matches SDK 26.4"):
            SELECT.select_simulator(source, "26.4")

    def test_invalid_sdk_or_inventory_is_rejected(self):
        for sdk in (None, "", "26", "26.4beta", "not a version"):
            with self.subTest(sdk=sdk), self.assertRaisesRegex(ValueError, "SDK version"):
                SELECT.select_simulator(inventory(**{"26_4": [device()]}), sdk)
        for source in (None, [], {}, {"devices": []}):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "inventory"):
                SELECT.select_simulator(source, "26.4")

    def test_native_queries_have_timeouts_and_use_the_active_sdk(self):
        source = inventory(**{"26_4": [device()]})
        with patch.dict(os.environ, {"SIMULATOR_UDID": ""}), \
                patch.object(SELECT.subprocess, "check_output", side_effect=["26.4\n", json.dumps(source)]) as command, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            SELECT.main()
        self.assertEqual(output.getvalue(), FIRST + "\n")
        self.assertEqual(command.call_args_list, [
            call(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"],
                 text=True, stdin=subprocess.DEVNULL, timeout=30),
            call(["xcrun", "simctl", "list", "devices", "available", "--json"],
                 text=True, stdin=subprocess.DEVNULL, timeout=60),
        ])

    def test_native_failures_report_that_tests_did_not_run(self):
        for error in (subprocess.TimeoutExpired("xcrun", 30), subprocess.CalledProcessError(1, "xcrun"),
                      FileNotFoundError("xcrun")):
            with self.subTest(error=error), patch.dict(os.environ, {"SIMULATOR_UDID": ""}), \
                    patch.object(SELECT.subprocess, "check_output", side_effect=error), \
                    self.assertRaisesRegex(SystemExit, "App tests have NOT run"):
                SELECT.main()


if __name__ == "__main__":
    unittest.main()
