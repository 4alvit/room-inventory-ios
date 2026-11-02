"""Post-failure log contracts. No native child, signal, or service is used."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("room_native_log", Path(__file__).resolve().parents[1] / "recovery_hosted.py")
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)


def event(**updates):
    result = {"processImagePath": "/private/Frameworks/CoreSimulator/simctl",
              "subsystem": "com.apple.CoreSimulator", "timestamp": "1970-01-01 00:17:30+00:00",
              "eventMessage": "connection invalid: NSMachErrorDomain Code=5 private@example.test /Users/private/token-file secret-value"}
    result.update(updates)
    return result


def original():
    return {"name": "simulator-inventory", "args": ["xcrun", "simctl", "list", "--json"],
            "primary_error": {"type": "DeadlineFailure", "message": "Discovery command deadline reached"},
            "timing": {"start": 10.0, "finish": 96.0, "work_deadline": 96.0, "command_deadline": 100.0, "requested_cap": 90},
            "cleanup": {"success": True, "leader_reaped": True, "group_state": "absent", "errors": []}}


class NativeLogCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 100.0
        self.alarm = SimpleNamespace(end=130.0, clock=lambda: self.now, arm=Mock())
        self.discovery = SimpleNamespace(records=[original()], cleanup_errors=[], output=Path(self.temp.name),
                                         alarm=self.alarm, check=Mock(), command=Mock(return_value=b"[]"))
        self.context = {}
        self.armed_deadlines = []
        def arm(alarm, end=None):
            limit = min(alarm.end, alarm.end if end is None else end)
            self.armed_deadlines.append(limit)
            if alarm.clock() >= limit:
                raise H.Deadline("fake absolute deadline")
        p = patch.object(H.Alarm, "arm", autospec=True, side_effect=arm)
        p.start()
        self.addCleanup(p.stop)
        for owner, name in ((H.subprocess, "Popen"), (H.os, "killpg"), (H.signal, "setitimer")):
            p = patch.object(owner, name, side_effect=AssertionError("native call forbidden"))
            p.start()
            self.addCleanup(p.stop)

    def diagnose(self, begin=1000.0, finish=1086.0):
        H.diagnose_inventory_failure(self.discovery, self.context, 0, begin, lambda: finish)
        return self.context["inventory_native_log"]

    def test_exact_single_read_only_query_with_empty_home_and_no_raw_retention(self):
        self.discovery.command.return_value = json.dumps([event()]).encode()
        row = self.diagnose()
        H.diagnose_inventory_failure(self.discovery, self.context, 0, 1000, lambda: 1086)
        self.discovery.command.assert_called_once()
        args, name, cap = self.discovery.command.call_args.args
        self.assertEqual(name, "inventory-native-log")
        self.assertEqual(cap, 10)
        self.assertEqual(args[:7], ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
                                  "HOME=" + str(Path(self.temp.name) / "native-log-home"), "LANG=C", "LC_ALL=C", "/usr/bin/log"])
        self.assertEqual(args[7:], ["show", "--style", "json", "--timezone", "UTC", "--no-pager", "--info", "--debug",
                                   "--start", "1970-01-01 00:16:40+0000", "--end", "1970-01-01 00:18:06+0000",
                                   "--predicate", H.NATIVE_LOG_PREDICATE])
        self.assertEqual(self.discovery.command.call_args.kwargs, {"retain_output": False})
        self.assertEqual(list((Path(self.temp.name) / "native-log-home").iterdir()), [])
        self.assertEqual(row["status"], "OBSERVED")
        self.assertEqual(row["signals"][0]["numeric_codes"], [5])
        self.assertFalse(row["raw_text_retained"])
        self.assertEqual(row["native_cause"], "UNKNOWN")
        self.assertEqual(self.alarm.end, 130)
        self.assertIn(114, self.armed_deadlines)
        self.assertIs(self.discovery.alarm, self.alarm)
        self.alarm.arm.assert_called_with()

    def test_unconfirmed_sampler_or_target_cleanup_prevents_any_new_acquisition(self):
        # The rejected sampler could leave an unresolved helper when target cleanup
        # ran. Any existing uncertainty now forbids acquiring the diagnostic child.
        for mutation in (lambda d: d.cleanup_errors.append({"operation": "native_sample_cleanup"}),
                         lambda d: d.records[0]["cleanup"].update(success=False),
                         lambda d: d.records[0]["cleanup"].update(leader_reaped=False),
                         lambda d: d.records[0]["cleanup"].update(group_state="unknown"),
                         lambda d: d.records[0]["cleanup"].update(errors=["unconfirmed"]),
                         lambda d: d.records[0].pop("cleanup")):
            with self.subTest(mutation=mutation):
                self.discovery.records = [original()]
                self.discovery.cleanup_errors = []
                self.context = {}
                mutation(self.discovery)
                row = self.diagnose()
                self.assertFalse(row["query_attempted"])
                self.assertEqual(row["reason"], "inventory_cleanup_unconfirmed")
        self.discovery.command.assert_not_called()

    def test_wrong_or_missing_original_record_never_queries(self):
        for records in ([], [original(), original()], [{**original(), "name": "other"}],
                        [{**original(), "args": ["other"]}], [{**original(), "primary_error": None}]):
            self.discovery.records = records
            self.context = {}
            self.assertFalse(self.diagnose()["query_attempted"])
        self.discovery.command.assert_not_called()

    def test_exact_budget_floor_and_no_deadline_renewal(self):
        self.alarm.end = 113.999
        self.assertEqual(self.diagnose()["reason"], "insufficient_remaining_budget")
        self.discovery.command.assert_not_called()
        self.context = {}
        self.alarm.end = 114
        self.assertTrue(self.diagnose()["complete"])
        self.assertEqual(self.alarm.end, 114)

    def test_abort_floor_or_expired_alarm_prevents_query(self):
        self.discovery.check.side_effect = H.Deadline("expired or disk failure")
        row = self.diagnose()
        self.assertFalse(row["query_attempted"])
        self.discovery.command.assert_not_called()

    def test_clock_reversal_jump_nonfinite_or_wrong_type_prevents_query(self):
        for begin, finish in ((1087, 1086), (900, 1086), (1000, 1089),
                              (float("nan"), 1086), (1000, float("inf")), (None, 1086), (True, 1086)):
            self.context = {}
            self.assertEqual(self.diagnose(begin, finish)["reason"], "clock_window_unconfirmed")
        self.discovery.command.assert_not_called()

    def test_existing_output_directory_or_symlink_is_not_reused(self):
        home = Path(self.temp.name) / "native-log-home"
        home.symlink_to(Path(self.temp.name), target_is_directory=True)
        self.assertFalse(self.diagnose()["query_attempted"])
        self.discovery.command.assert_not_called()

    def test_query_failure_interrupt_and_private_errors_have_closed_reasons(self):
        for error in (RuntimeError("secret-value private@example.test"), KeyboardInterrupt("private"),
                      H.Deadline("native timeout")):
            self.context = {}
            home = Path(self.temp.name) / "native-log-home"
            if home.exists():
                home.rmdir()
            self.discovery.command.side_effect = error
            row = self.diagnose()
            self.assertFalse(row["complete"])
            self.assertNotIn("private", json.dumps(row))
            self.assertNotIn("secret-value", json.dumps(row))
        self.assertEqual(self.discovery.command.call_count, 3)

    def test_parser_cannot_use_more_than_remaining_four_seconds(self):
        def command(*args, **kwargs):
            self.now = 114
            return b"[]"
        self.discovery.command.side_effect = command
        self.assertEqual(self.diagnose()["reason"], "query_or_parse_unavailable")

    def test_slow_preparation_cannot_start_a_ten_second_query_outside_subdeadline(self):
        mkdir = Path.mkdir
        def slow(path, *args, **kwargs):
            result = mkdir(path, *args, **kwargs)
            self.now += 5
            return result
        with patch.object(Path, "mkdir", slow):
            row = self.diagnose()
        self.assertEqual(row["reason"], "insufficient_observation_budget")
        self.assertFalse(row["query_attempted"])
        self.discovery.command.assert_not_called()
        self.assertEqual(self.armed_deadlines, [114])
        self.assertIs(self.discovery.alarm, self.alarm)
        self.assertEqual(self.alarm.end, 130)

    def test_preparation_query_and_parser_all_share_the_same_absolute_subdeadline(self):
        mkdir = Path.mkdir
        def slow(path, *args, **kwargs):
            result = mkdir(path, *args, **kwargs)
            self.now += 2
            return result
        def command(*args, **kwargs):
            self.assertEqual(self.discovery.alarm.end, 114)
            self.assertEqual(args[2], 10)
            self.now = 112
            return b"[]"
        self.discovery.command.side_effect = command
        with patch.object(Path, "mkdir", slow):
            self.assertTrue(self.diagnose()["complete"])
        self.assertTrue(all(end == 114 for end in self.armed_deadlines))
        self.assertIs(self.discovery.alarm, self.alarm)

    def test_empty_response_is_not_evidence_of_no_native_error(self):
        row = self.diagnose()
        self.assertEqual(row["status"], "NO_MATCHING_SIGNALS")
        self.assertEqual(row["coverage"], "returned_query_events_only")
        self.assertEqual(row["native_cause"], "UNKNOWN")


class ParserTests(unittest.TestCase):
    def parse(self, events):
        return H.sanitize_native_log(json.dumps(events).encode(), 1000, 1086, lambda: None)

    def test_selected_fields_are_closed_and_private_content_is_never_retained(self):
        row = self.parse([event()])
        text = json.dumps(row)
        for secret in ("private@example", "/private", "/Users", "token-file", "secret-value", "processImagePath"):
            self.assertNotIn(secret, text)
        self.assertEqual(row["signals"], [{"source": "simctl", "timestamp": "1970-01-01T00:17:30+00:00",
                                          "terms": ["connection invalid"], "error_domains": ["NSMachErrorDomain"], "numeric_codes": [5]}])

    def test_only_three_fixed_source_categories(self):
        events = [event(processImagePath="/System/com.apple.CoreSimulator.CoreSimulatorService"),
                  event(processImagePath="/unknown", subsystem="com.apple.CoreSimulator.Service"),
                  event(processImagePath="/other", subsystem="other")]
        self.assertEqual([r["source"] for r in self.parse(events)["signals"]],
                         ["coresimulator_service", "coresimulator_subsystem"])

    def test_closed_time_window_filters_unrelated_old_events(self):
        row = self.parse([event(timestamp="1970-01-01 00:00:00Z"), event(timestamp="1970-01-01 00:20:00Z")])
        self.assertEqual(row["signals"], [])
        self.assertEqual(row["outside_window_count"], 2)

    def test_malformed_truncated_invalid_utf8_duplicate_and_nonfinite_json_rejected(self):
        for raw in (b"[", b"{}", b"[null]", b"[1]", b'[{"x":1,"x":2}]', b'[NaN]', b'[1e9999]', b'["\xff"]'):
            with self.subTest(raw=raw), self.assertRaises(H.NativeLogUnavailable):
                H.sanitize_native_log(raw, 1000, 1086, lambda: None)

    def test_size_depth_event_and_signal_limits(self):
        cases = (b" " * (H.NATIVE_LOG_LIMIT + 1), b"[" * 17 + b"]" * 17,
                 json.dumps([{}] * 4097).encode(), json.dumps([event()] * 129).encode())
        for raw in cases:
            with self.assertRaises(H.NativeLogUnavailable):
                H.sanitize_native_log(raw, 1000, 1086, lambda: None)

    def test_wrong_field_types_and_oversized_strings_rejected(self):
        for key, value in (("timestamp", "without-zone"), ("timestamp", True), ("eventMessage", {}),
                           ("eventMessage", "x" * (256 * 1024 + 1)), ("processImagePath", []), ("subsystem", 1)):
            with self.subTest(key=key), self.assertRaises(H.NativeLogUnavailable):
                self.parse([event(**{key: value})])

    def test_parsing_obeys_the_absolute_alarm(self):
        check = Mock(side_effect=H.Deadline("absolute budget"))
        with self.assertRaises(H.Deadline):
            H.sanitize_native_log(b"[]", 1000, 1086, check)


OBS_SPEC = importlib.util.spec_from_file_location("native_log_fake_world", Path(__file__).with_name("test_recovery_discovery_observation.py"))
OBS = importlib.util.module_from_spec(OBS_SPEC)
OBS_SPEC.loader.exec_module(OBS)


class OwnershipIntegrationTests(unittest.TestCase):
    def test_real_discovery_cleanup_precedes_query_and_keeps_90_4_120_budgets(self):
        with tempfile.TemporaryDirectory() as directory, OBS.World(True) as world:
            world.discovery.output = Path(directory)
            real_command = world.discovery.command
            calls = []
            def command(args, name, cap=20, **kwargs):
                calls.append(name)
                if name == "simulator-inventory":
                    return real_command(args, name, cap, **kwargs)
                self.assertEqual(world.stop_calls, 1)
                self.assertEqual(world.discovery.records[0]["cleanup"]["group_state"], "absent")
                self.assertEqual(cap, 10)
                self.assertFalse(kwargs["retain_output"])
                return b"[]"
            def select(_):
                world.now = 186.0
                return []
            world.selector.select = select
            context = {}
            with patch.object(world.discovery, "command", side_effect=command), self.assertRaises(OBS.H.Deadline):
                OBS.H.inventory_with_diagnostics(world.discovery, context, wall_clock=Mock(side_effect=[1000.0, 1086.0]))
            self.assertEqual(calls, ["simulator-inventory", "inventory-native-log"])
            self.assertEqual(world.discovery.records[0]["timing"]["work_deadline"], 186)
            self.assertEqual(world.discovery.records[0]["timing"]["command_deadline"], 190)
            self.assertEqual(world.alarm.end, 220)
            self.assertEqual(context["inventory_native_log"]["status"], "NO_MATCHING_SIGNALS")

    def test_real_uncertain_cleanup_never_acquires_log_child(self):
        with OBS.World(True) as world:
            world.cleanup_report.update(success=False, group_state="unknown", leader_reaped=False)
            def select(_):
                world.now = 186.0
                return []
            world.selector.select = select
            context = {}
            with self.assertRaises(OBS.H.Deadline):
                OBS.H.inventory_with_diagnostics(world.discovery, context, wall_clock=lambda: 1000.0)
            self.assertEqual([r["name"] for r in world.discovery.records], ["simulator-inventory"])
            self.assertEqual(context["inventory_native_log"]["reason"], "inventory_cleanup_unconfirmed")
            self.assertEqual(sum(e[0] == "Popen" for e in world.events), 1)

    def test_actual_discovery_raw_log_streams_are_not_written(self):
        with OBS.World(True) as world:
            raw = world.discovery.command(["/usr/bin/log", "show"], "inventory-native-log", 10, retain_output=False)
            self.assertEqual(raw, b"a")
            self.assertFalse(any(e[0] == "write" for e in world.events))
            row = world.discovery.records[0]
            self.assertEqual((row["stdout_bytes"], row["stderr_bytes"]), (1, 1))
            self.assertFalse(row["output_retained"])
            self.assertNotIn("stdout_sha256", row)
            self.assertNotIn("stderr_sha256", row)


class WrapperTests(unittest.TestCase):
    def test_success_has_no_diagnostic_query_or_context_change(self):
        discovery = SimpleNamespace(records=[], command=Mock(return_value=b'{"devices":{}}'))
        context = {}
        self.assertEqual(H.inventory_with_diagnostics(discovery, context, wall_clock=lambda: 1000), b'{"devices":{}}')
        discovery.command.assert_called_once_with(["xcrun", "simctl", "list", "--json"], "simulator-inventory", 90)
        self.assertEqual(context, {})

    def test_original_exception_identity_preserved_after_diagnostic_failure(self):
        error = H.Deadline("original inventory timeout")
        discovery = SimpleNamespace(records=[], command=Mock(side_effect=error))
        context = {}
        with self.assertRaises(H.Deadline) as caught:
            H.inventory_with_diagnostics(discovery, context, wall_clock=lambda: 1000)
        self.assertIs(caught.exception, error)
        discovery.command.assert_called_once()
        self.assertEqual(context["inventory_native_log"]["reason"], "inventory_record_missing")

    def test_cancel_never_enters_diagnostic_or_retries_inventory(self):
        error = KeyboardInterrupt()
        discovery = SimpleNamespace(records=[], command=Mock(side_effect=error))
        with patch.object(H, "diagnose_inventory_failure") as diagnose, self.assertRaises(KeyboardInterrupt):
            H.inventory_with_diagnostics(discovery, {}, wall_clock=lambda: 1000)
        diagnose.assert_not_called()
        discovery.command.assert_called_once()

    def test_unexpected_diagnostic_interruption_cannot_replace_original_failure(self):
        error = H.Deadline("original inventory timeout")
        discovery = SimpleNamespace(records=[], command=Mock(side_effect=error))
        context = {}
        with patch.object(H, "diagnose_inventory_failure", side_effect=KeyboardInterrupt()), self.assertRaises(H.Deadline) as caught:
            H.inventory_with_diagnostics(discovery, context, wall_clock=lambda: 1000)
        self.assertIs(caught.exception, error)
        self.assertEqual(context["inventory_native_log"]["reason"], "diagnostic_interrupted")

    def test_diagnostic_clock_failure_cannot_prevent_original_inventory(self):
        discovery = SimpleNamespace(records=[], command=Mock(return_value=b"original"))
        self.assertEqual(H.inventory_with_diagnostics(discovery, {}, wall_clock=Mock(side_effect=ValueError("clock"))), b"original")

    def test_no_rejected_native_sampler_or_opt_in_is_shipped(self):
        source = Path(H.__file__).read_text()
        self.assertNotIn("/usr/bin/sample", source)
        self.assertNotIn("NATIVE_SAMPLE", source)
        self.assertEqual(H.POLICY["discovery_seconds"], 120)
        self.assertEqual(H.POLICY["recovery_seconds"], 1800)


if __name__ == "__main__":
    unittest.main()
