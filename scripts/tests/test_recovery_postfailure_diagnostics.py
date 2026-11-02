"""Post-controller diagnostics: fake clocks/process ledgers, no native work."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_recovery_hosted import HostedCase, hosted as H


def fixture():
    primary = {"type": "DeadlineFailure", "message": "Absolute phase/outer deadline exceeded"}
    proof = {"pgid": 123, "group_state": "absent", "leader_reaped": True,
             "returncode": -15, "success": False,
             "errors": [{"operation": "group_probe", "errno": 1}]}
    command = {"name": "authorize-runner-photos", "pid": 123, "pgid": 123,
               "args": ["xcrun", "simctl", "privacy", "owned-device", "grant", "photos", H.controller.RUNNER_BUNDLE],
               "start_elapsed": 237.882, "end_deadline_elapsed": 267.882,
               "elapsed_seconds": 27.893, "primary_error": primary,
               "post_command_accounting": None, "cleanup": proof}
    record = {"phase": "device", "test_count": 0, "primary_error": primary,
              "elapsed_seconds": 337.812, "commands": [command],
              "cleanup_errors": [{"command": command["name"], "final_observation": deepcopy(proof)}]}
    return SimpleNamespace(record=record, start=100.0, device_id="owned-device", cleanup_mode=True,
                           timer_enabled=False, groups=[{"record": command,
                           "process": SimpleNamespace(pid=123, returncode=-15), "state": deepcopy(proof)}])


class PostfailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 438.0
        self.runner = fixture()
        self.anchor = {"before": 100.0, "wall": 1000.0, "after": 100.0}
        self.old_alarm = H.Alarm(220.0, lambda: self.now)
        self.discovery = H.Discovery(Path(self.temp.name), Path(self.temp.name), {}, self.old_alarm,
                                     disk_usage=lambda _: SimpleNamespace(free=30 * H.controller.GIB))
        self.discovery.records = [{"cleanup": {"group_state": "absent", "leader_reaped": True,
                                               "returncode": 0, "pgid": 122}}]
        self.discovery.command = Mock(return_value=b"[]")
        self.context = {"primary_error": self.runner.record["primary_error"],
                        "cleanup_errors": self.runner.record["cleanup_errors"]}
        self.original = deepcopy(self.runner.record)
        self.armed = []
        for owner, name in ((H.subprocess, "Popen"), (H.os, "killpg")):
            p = patch.object(owner, name, side_effect=AssertionError("native work forbidden"))
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("getitimer", (0.0, 0.0)), ("getsignal", object()), ("signal", None)):
            p = patch.object(H.signal, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(H.signal, "setitimer", side_effect=lambda _, seconds: self.armed.append(self.now + seconds) if seconds else None)
        p.start()
        self.addCleanup(p.stop)

    def diagnose(self, *, outer_end=2200.0, returned=True, wall=None):
        H.diagnose_controller_failure(self.discovery, self.runner, self.context, self.anchor, outer_end,
                                      execute_returned=returned, wall_clock=wall or (lambda: self.now + 900))
        return self.context.get("controller_native_log")

    def test_exact_query_once_after_sticky_eperm_without_clearing_failure(self):
        event = {"processImagePath": "/private/CoreSimulator/simctl", "subsystem": "com.apple.CoreSimulator",
                 "timestamp": "1970-01-01T00:20:40+00:00",
                 "eventMessage": "permission denied NSPOSIXErrorDomain errno=1 secret@example.test /Users/private"}
        self.discovery.command.return_value = json.dumps([event]).encode()
        row = self.diagnose()
        self.diagnose()
        self.discovery.command.assert_called_once()
        args, name, cap = self.discovery.command.call_args.args
        self.assertEqual((name, cap), ("controller-native-log", 10))
        self.assertEqual(args[:3], ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin:/usr/sbin:/sbin"])
        self.assertEqual(args[4:7], ["LANG=C", "LC_ALL=C", "/usr/bin/log"])
        self.assertEqual(args[7:], ["show", "--style", "json", "--timezone", "UTC", "--no-pager", "--info", "--debug",
                                   "--start", "1970-01-01 00:20:37+0000", "--end", "1970-01-01 00:21:06+0000",
                                   "--predicate", H.NATIVE_LOG_PREDICATE])
        self.assertEqual(self.discovery.command.call_args.kwargs, {"retain_output": False})
        self.assertEqual(list((Path(self.temp.name) / "controller-native-log-home").iterdir()), [])
        self.assertEqual(row["status"], "OBSERVED")
        self.assertEqual(row["signals"][0]["numeric_codes"], [1])
        self.assertEqual(row["native_cause"], "UNKNOWN")
        self.assertEqual(self.runner.record, self.original)
        self.assertIs(self.context["primary_error"], self.runner.record["primary_error"])
        self.assertIs(self.discovery.alarm, self.old_alarm)
        self.assertTrue(all(end <= 452 for end in self.armed))
        for secret in ("secret@", "/private", "/Users", "eventMessage", "processImagePath"):
            self.assertNotIn(secret, json.dumps(row))

    def test_every_owned_group_requires_terminal_identity_proof(self):
        changes = [lambda r: r.groups[0]["state"].update(group_state="unknown"),
                   lambda r: r.groups[0]["state"].update(leader_reaped=False),
                   lambda r: setattr(r.groups[0]["process"], "returncode", None),
                   lambda r: r.record["cleanup_errors"][0]["final_observation"].update(pgid=999),
                   lambda r: r.groups[0]["record"].update(pgid=999),
                   lambda r: r.groups.clear(),
                   lambda r: r.record["commands"].append({"pid": 999}),
                   lambda r: r.groups[0].update(record=deepcopy(r.groups[0]["record"]))]
        for change in changes:
            with self.subTest(change=change):
                self.runner = fixture()
                self.context.pop("controller_native_log", None)
                change(self.runner)
                self.assertEqual(self.diagnose()["reason"], "owned_groups_unconfirmed")
        self.discovery.command.assert_not_called()

    def test_uncertain_discovery_group_or_unfinished_controller_never_queries(self):
        for returned, cleanup, timer in ((False, True, False), (True, False, False), (True, True, True)):
            self.context.pop("controller_native_log", None)
            self.runner.cleanup_mode, self.runner.timer_enabled = cleanup, timer
            self.assertEqual(self.diagnose(returned=returned)["reason"], "controller_cleanup_unfinished")
        self.runner = fixture()
        self.context.pop("controller_native_log", None)
        self.discovery.records[0]["cleanup"]["group_state"] = "unknown"
        self.assertEqual(self.diagnose()["reason"], "discovery_groups_unconfirmed")
        self.discovery.command.assert_not_called()

    def test_success_other_phases_and_ui_failure_are_not_eligible(self):
        for change in ({"primary_error": None}, {"phase": "build"}, {"phase": "test"}, {"test_count": 1}):
            self.runner = fixture()
            self.runner.record.update(change)
            self.assertIsNone(self.diagnose())
        self.discovery.command.assert_not_called()

    def test_wrong_command_identity_or_completed_native_work_never_queries(self):
        for change in ({"args": ["other"]}, {"args": ["xcrun", "simctl", "privacy", "foreign"]},
                       {"name": "ui-test"}, {"post_command_accounting": {"status": "FAILED"}},
                       {"primary_error": {"type": "Other"}}):
            self.runner = fixture()
            self.context.pop("controller_native_log", None)
            self.runner.record["commands"][0].update(change)
            self.assertEqual(self.diagnose()["reason"], "failed_device_command_unconfirmed")
        self.discovery.command.assert_not_called()

    def test_full_14_plus_180_seconds_required_and_old_alarm_not_rearmed(self):
        self.assertEqual(self.diagnose(outer_end=self.now + 193.999)["reason"], "insufficient_remaining_budget")
        self.discovery.command.assert_not_called()
        self.context.pop("controller_native_log")
        self.assertTrue(self.diagnose(outer_end=self.now + 194)["complete"])
        self.assertEqual(self.armed, [452.0, 452.0])
        self.assertEqual(self.old_alarm.end, 220)

    def test_untrusted_wall_monotonic_or_command_window_never_queries(self):
        variants = [({"before": 100, "after": 102, "wall": 1000}, 1338),
                    (None, 1338), (self.anchor, 1340.001), (self.anchor, float("nan"))]
        for anchor, wall in variants:
            self.context.pop("controller_native_log", None)
            self.anchor = anchor
            self.assertEqual(self.diagnose(wall=lambda: wall)["reason"], "clock_window_unconfirmed")
        self.anchor = {"before": 100.0, "after": 100.0, "wall": 1000.0}
        for change in ({"elapsed_seconds": float("inf")}, {"elapsed_seconds": -1},
                       {"start_elapsed": True}, {"end_deadline_elapsed": 600}):
            self.context.pop("controller_native_log", None)
            self.runner = fixture()
            self.runner.record["commands"][0].update(change)
            self.assertEqual(self.diagnose()["reason"], "clock_window_unconfirmed")
        self.discovery.command.assert_not_called()

    def test_failed_boot_longer_than_old_inventory_window_is_bounded_by_its_own_cap(self):
        self.runner.record["commands"][0].update(name="boot-status", start_elapsed=10,
                                               end_deadline_elapsed=310, elapsed_seconds=290,
                                               args=["xcrun", "simctl", "bootstatus", "owned-device", "-b"])
        self.assertTrue(self.diagnose()["complete"])
        self.assertEqual(self.context["controller_native_log"]["command"], "boot-status")

    def test_early_native_failure_does_not_require_waiting_until_unused_command_cap(self):
        self.runner.record["commands"][0].update(name="boot-status", start_elapsed=10,
                                               end_deadline_elapsed=310, elapsed_seconds=2)
        self.runner.record["elapsed_seconds"] = 50
        self.assertTrue(self.diagnose()["complete"])

    def test_preparation_cannot_consume_query_reserve(self):
        mkdir = Path.mkdir
        def slow(path, *args, **kwargs):
            result = mkdir(path, *args, **kwargs)
            self.now += 5
            return result
        with patch.object(Path, "mkdir", slow):
            self.assertEqual(self.diagnose()["reason"], "insufficient_observation_budget")
        self.discovery.command.assert_not_called()

    def test_query_and_parser_share_nonrenewing_deadline(self):
        def command(*args, **kwargs):
            self.assertEqual(self.discovery.alarm.end, 452)
            self.now = 448
            return b"[]"
        def parser(*args):
            self.now = 452
            args[-1]()
            self.fail("Late parser must fail")
        self.discovery.command.side_effect = command
        with patch.object(H, "sanitize_native_log", side_effect=parser):
            row = self.diagnose()
        self.assertFalse(row["complete"])
        self.assertEqual(self.armed, [452, 452])
        self.assertEqual(self.runner.record, self.original)

    def test_private_query_errors_and_interrupts_do_not_replace_primary(self):
        for error in (RuntimeError("secret@example.test"), H.Deadline("private path"), KeyboardInterrupt("private")):
            self.context.pop("controller_native_log", None)
            home = Path(self.temp.name) / "controller-native-log-home"
            if home.exists():
                home.rmdir()
            self.discovery.command.side_effect = error
            row = self.diagnose()
            self.assertFalse(row["complete"])
            self.assertNotIn("private", json.dumps(row))
            self.assertNotIn("secret@", json.dumps(row))
            self.assertEqual(self.runner.record, self.original)

    def test_existing_home_is_not_reused_and_empty_logs_are_not_a_cause(self):
        home = Path(self.temp.name) / "controller-native-log-home"
        home.symlink_to(Path(self.temp.name), target_is_directory=True)
        self.assertFalse(self.diagnose()["query_attempted"])
        self.discovery.command.assert_not_called()
        home.unlink()
        self.context.pop("controller_native_log")
        row = self.diagnose()
        self.assertEqual(row["status"], "NO_MATCHING_SIGNALS")
        self.assertEqual(row["native_cause"], "UNKNOWN")


class AdapterIntegrationTests(HostedCase):
    def test_diagnostic_runs_after_execute_and_before_retention_without_changing_failure(self):
        self.fake_execution(code=124, primary={"type": "DeadlineFailure", "message": "original"},
                            cleanup=[{"operation": "group_probe", "errno": 1}], complete=False)
        sequence = []
        self.runner.execute.side_effect = lambda: sequence.append("execute") or 124
        def diagnose(discovery, runner, context, anchor, outer_end, *, execute_returned):
            self.assertTrue(execute_returned)
            self.assertEqual(outer_end, 2200)
            self.assertEqual(context["primary_error"]["message"], "original")
            sequence.append("diagnose")
            context["controller_native_log"] = {"status": "UNAVAILABLE"}
        self.package.side_effect = lambda *args, **kwargs: sequence.append("retain") or {"status": "PARTIAL", "complete": False}
        with patch.object(H, "diagnose_controller_failure", side_effect=diagnose):
            result = self.run_adapter()
        self.assertEqual(sequence, ["execute", "diagnose", "retain"])
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual(result["primary_error"]["message"], "original")
        self.assertEqual(self.package.call_args.args[2]["cleanup_errors"], [{"operation": "group_probe", "errno": 1}])

    def test_failed_execute_never_claims_returned_and_diagnostic_interrupt_preserves_primary(self):
        self.fake_execution(code=124, primary={"type": "DeadlineFailure", "message": "original"}, complete=False)
        self.runner.execute.side_effect = H.Deadline("interrupted")
        def interrupted(*args, **kwargs):
            self.assertFalse(kwargs["execute_returned"])
            raise KeyboardInterrupt("private")
        with patch.object(H, "diagnose_controller_failure", side_effect=interrupted):
            result = self.run_adapter()
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual(result["primary_error"]["message"], "original")
        row = self.package.call_args.args[2]["controller_native_log"]
        self.assertEqual(row["reason"], "diagnostic_interrupted")
        self.assertNotIn("private", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
