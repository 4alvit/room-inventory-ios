import unittest
from unittest import mock
import probe_room_csv as probe


class ProbeContracts(unittest.TestCase):
    def test_expired_global_budget_never_starts_another_process(self):
        with mock.patch.object(probe, "ACTIVE_DEADLINE", 0), mock.patch.object(probe.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                probe.command(["must-not-start"], ".")
            popen.assert_not_called()

    def test_logger_header_is_not_a_recorded_system_event(self):
        self.assertEqual(probe.event_count(b'Filtering the log data\n{"eventMessage":"no timestamp"}'), 0)
        self.assertEqual(probe.event_count(b'header\n{"timestamp":"now","eventMessage":"hello"}\n'), 1)

    def test_exited_leader_does_not_bypass_owned_group_cleanup(self):
        process = mock.Mock(pid=12345)
        process.poll.return_value = 0
        with mock.patch.object(probe.os, "killpg", side_effect=[None, ProcessLookupError]) as kill:
            probe.stop(process)
        self.assertEqual(kill.call_args_list, [mock.call(12345, probe.signal.SIGTERM), mock.call(12345, 0)])

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


if __name__ == "__main__":
    unittest.main()
