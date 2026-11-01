"""Test destinations must stay on the active SDK or explicitly pinned runtime line."""
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
IPHONE_16E = "com.apple.CoreSimulator.SimDeviceType.iPhone-16e"
IPHONE_17 = "com.apple.CoreSimulator.SimDeviceType.iPhone-17"


def device(udid=FIRST, *, name="iPhone 17", state="Shutdown", available=True, device_type=IPHONE_17):
    return {"name": name, "udid": udid, "state": state, "isAvailable": available,
            "deviceTypeIdentifier": device_type}


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
        with patch.dict(os.environ, {"SIMULATOR_UDID": FIRST}, clear=True), \
                patch.object(SELECT.subprocess, "check_output", return_value=json.dumps(source)) as command, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            SELECT.main()
        self.assertEqual(output.getvalue(), FIRST + "\n")
        command.assert_called_once_with(
            ["xcrun", "simctl", "list", "devices", "available", "--json"],
            text=True, stdin=subprocess.DEVNULL, timeout=60,
        )

    def test_explicit_older_runtime_uses_latest_patch_without_sdk_fallback(self):
        source = inventory(**{"26_2": [device(state="Booted")], "26_2_1": [device(SECOND)],
                              "26_4": [device(THIRD, state="Booted")]})
        self.assertEqual(SELECT.select_simulator(source, "26.4", runtime_version="26.2"), SECOND)

    def test_explicit_runtime_allows_matching_sdk_line(self):
        source = inventory(**{"26_4": [device()]})
        self.assertEqual(SELECT.select_simulator(source, "26.4.1", runtime_version="26.4"), FIRST)

    def test_explicit_runtime_and_udid_must_agree(self):
        source = inventory(**{"26_2": [device()], "26_2_1": [device(SECOND)], "26_4": [device(THIRD)]})
        self.assertEqual(SELECT.select_simulator(source, "26.4", FIRST, "26.2"), FIRST)
        for udid in (THIRD, "missing"):
            with self.subTest(udid=udid), self.assertRaisesRegex(ValueError, "matching SIMULATOR_RUNTIME_VERSION 26.2"):
                SELECT.select_simulator(source, "26.4", udid, "26.2")

    def test_missing_pinned_runtime_fails_without_fallback(self):
        source = inventory(**{"26_4": [device(state="Booted")], "26_1": [device(SECOND)]})
        with self.assertRaisesRegex(ValueError, "matches SIMULATOR_RUNTIME_VERSION 26.2"):
            SELECT.select_simulator(source, "26.4", runtime_version="26.2")

    def test_explicit_runtime_requires_supported_major_minor_format(self):
        source = inventory(**{"26_2": [device()]})
        for runtime in ("", "26", "26.2.1", "26.2beta", " 26.2", "026.2", "26.02", "16.4"):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, "major.minor"):
                SELECT.select_simulator(source, "26.4", runtime_version=runtime)

    def test_explicit_runtime_cannot_exceed_sdk_even_with_udid(self):
        source = inventory(**{"26_5": [device()]})
        for requested in (None, FIRST):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, "newer than active SDK 26.4"):
                SELECT.select_simulator(source, "26.4", requested, "26.5")

    def test_device_type_pin_uses_metadata_not_a_similar_name_or_booted_device(self):
        source = inventory(**{"26_4": [device(device_type=IPHONE_16E),
                                          device(SECOND, name="iPhone 16e", state="Booted")]})
        self.assertEqual(SELECT.select_simulator(source, "26.4", device_type=IPHONE_16E), FIRST)

    def test_device_type_pin_keeps_runtime_patch_and_booted_selection_rules(self):
        source = inventory(**{"26_2": [device(device_type=IPHONE_16E, state="Booted")],
                              "26_2_1": [device(SECOND, device_type=IPHONE_16E, state="Booted"),
                                         device(THIRD, device_type=IPHONE_16E)],
                              "26_4": [device(THIRD, device_type=IPHONE_16E, state="Booted")]})
        self.assertEqual(SELECT.select_simulator(source, "26.4", runtime_version="26.2",
                                                device_type=IPHONE_16E), SECOND)

    def test_missing_device_type_pin_fails_without_fallback(self):
        for candidate in (device(), device(device_type=None), device(device_type=IPHONE_16E, available=False)):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, "SIMULATOR_DEVICE_TYPE"):
                SELECT.select_simulator(inventory(**{"26_4": [candidate]}), "26.4", device_type=IPHONE_16E)

    def test_device_type_pin_rejects_malformed_and_non_iphone_identifiers(self):
        source = inventory(**{"26_4": [device()]})
        for identifier in ("", "iPhone-16e", "com.apple.CoreSimulator.SimDeviceType.iPad-Pro",
                           "com.apple.CoreSimulator.SimDeviceType.iPhone-", IPHONE_16E + "\n",
                           IPHONE_16E + "/other", IPHONE_16E.replace("16e", "16 e")):
            with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, "full iPhone device type"):
                SELECT.select_simulator(source, None, FIRST, device_type=identifier)

    def test_explicit_udid_must_also_match_device_type_pin(self):
        source = inventory(**{"27_0": [device()], "26_2": [device(SECOND, device_type=IPHONE_16E)]})
        self.assertEqual(SELECT.select_simulator(source, None, SECOND, device_type=IPHONE_16E), SECOND)
        for runtime in (None, "26.2"):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, "SIMULATOR_DEVICE_TYPE"):
                SELECT.select_simulator(source, "27.0", FIRST, runtime, IPHONE_16E)

    def test_native_device_type_pin_preserves_uuid_sdk_bypass(self):
        source = inventory(**{"27_0": [device(device_type=IPHONE_16E), device(SECOND)]})
        with patch.dict(os.environ, {"SIMULATOR_UDID": FIRST, "SIMULATOR_DEVICE_TYPE": IPHONE_16E}, clear=True), \
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
        with patch.dict(os.environ, {}, clear=True), \
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

    def test_native_runtime_pin_queries_sdk_and_applies_with_or_without_udid(self):
        source = inventory(**{"26_2": [device()], "26_4": [device(SECOND, state="Booted")]})
        for requested in ("", FIRST):
            with self.subTest(requested=requested), \
                    patch.dict(os.environ, {"SIMULATOR_RUNTIME_VERSION": "26.2", "SIMULATOR_UDID": requested}, clear=True), \
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
            with self.subTest(error=error), patch.dict(os.environ, {}, clear=True), \
                    patch.object(SELECT.subprocess, "check_output", side_effect=error), \
                    self.assertRaisesRegex(SystemExit, "App tests have NOT run"):
                SELECT.main()


if __name__ == "__main__":
    unittest.main()
