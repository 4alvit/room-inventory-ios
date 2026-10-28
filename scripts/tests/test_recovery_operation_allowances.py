"""Finite hosted allowances through real builders and fake-clock admission."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_recovery_controller as base
import test_recovery_device_service as devices

C = base.controller


class OperationAllowanceTests(base.ControllerCase):
    def install_requests(self):
        run = self.run_fixture(output=False)
        run.output = self.root / "prepare-output"
        run.output.mkdir()
        run.device_id = "44444444-4444-4444-8444-444444444444"
        run.device_root = self.devices / run.device_id
        run.app, run.runner = self.root / "app", self.root / "runner"
        run.tree_sha, run.xctestrun_sha = "a" * 64, "b" * 64
        run.app_container = Mock(side_effect=[self.root / "app-data", self.root / "runner-data"])
        run.command = Mock(return_value=b"")
        collector = Mock()
        with patch.dict(sys.modules, {"recovery_collector": SimpleNamespace(Collector=Mock(return_value=collector))}):
            run.prepare_device()
        collector.capture_initial_exports.assert_called_once_with()
        calls = run.command.call_args_list
        self.assertEqual([c.args[1] for c in calls],
                         ["boot-device", "boot-status", "install-app", "install-runner", "seed-sole-photo"])
        self.assertEqual([c.kwargs["cap"] for c in calls], [30, 90, 90, 90, 30])
        installs = [c for c in calls if c.args[1].startswith("install-")]
        for call, app in zip(installs, (run.app, run.runner)):
            self.assertEqual(call.args[0], ["xcrun", "simctl", "install", run.device_id, app])
        self.popen.assert_not_called()
        return installs

    def cleanup_requests(self):
        run = self.run_fixture(output=False)
        run.device_id = "44444444-4444-4444-8444-444444444444"
        failure = C.DeadlineFailure("injected initial inventory timeout")
        final = json.dumps({"devices": {"runtime": [{"udid": run.device_id, "state": "Shutdown"}]}}).encode()
        run.command = Mock(side_effect=[failure, b"", final])
        run.cleanup()
        calls = run.command.call_args_list
        self.assertEqual([c.args[1] for c in calls],
                         ["device-cleanup-before", "shutdown-owned-device", "device-final-state"])
        self.assertEqual([c.kwargs["cap"] for c in calls], [24, 25, 15])
        self.assertEqual(calls[1].args[0], ["xcrun", "simctl", "shutdown", run.device_id])
        self.assertEqual(calls[0].args[0], calls[2].args[0])
        self.assertEqual(calls[0].args[0], ["xcrun", "simctl", "list", "devices", "--json"])
        self.assertEqual(run.record["device_final_state"], "Shutdown")
        self.assertEqual(len(run.record["cleanup_errors"]), 1)
        self.assertEqual(run.record["cleanup_errors"][0]["operation"], "initial_state")
        self.assertEqual(run.phase_end, run.outer_end)
        self.popen.assert_not_called()
        return calls

    def test_actual_install_requests_allow_cold_start_but_keep_original_phase_and_barrier(self):
        for request in self.install_requests():
            with self.subTest(command=request.args[1]), devices.World(module=C) as w:
                run = w.run
                w.clock.now = run.start + 217.613819
                run.phase("device")
                start = w.clock.now
                original = run.work_end, run.outer_end
                def guard(force=False):
                    if force:
                        self.assertTrue(w.cleaned)
                        w.clock.now += 10
                    run.tick()
                run.guard = Mock(side_effect=guard)
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + 85.5) or 0)
                w.cleanup_action = lambda: setattr(w.clock, "now", w.clock.now + .25)
                run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertAlmostEqual(record["end_deadline_elapsed"], start - run.start + 90)
                self.assertLess(record["child_completed_elapsed"], record["end_deadline_elapsed"] - 4)
                self.assertEqual(record["post_command_accounting"]["status"], "COMPLETED")
                self.assertEqual(record["post_command_accounting"]["deadline_elapsed"], 1020)
                self.assertTrue(any(c.kwargs == {"force": True} for c in run.guard.call_args_list))
                self.assertEqual((run.work_end, run.outer_end), original)

    def test_actual_install_admission_rejects_child_boundary_and_startup_exhaustion(self):
        request = self.install_requests()[0]
        for elapsed, work in ((217.613819, 86), (1012, 4), (1020, None)):
            with self.subTest(elapsed=elapsed), devices.World(module=C) as w:
                run = w.run
                run.phase("device")
                w.clock.now = run.start + elapsed
                run.guard = Mock(side_effect=lambda force=False: run.tick())
                if work is not None:
                    w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", run.start + elapsed + work) or 0)
                with self.assertRaises(C.DeadlineFailure):
                    run.command(*request.args, **request.kwargs)
                if work is None:
                    self.assertFalse(any(e[0] == "spawn" for e in w.events))
                else:
                    self.assertTrue(w.cleaned)
                    self.assertIsNone(run.record["commands"][0]["post_command_accounting"])
                self.assertEqual(run.outer_end - run.work_end, 60)
                self.assertEqual(run.phase_end, run.start + 1020)

    def test_initial_cleanup_has_twenty_work_seconds_only_when_absolute_time_allows(self):
        request = self.cleanup_requests()[0]
        for remaining, work, passes in ((60, 19.5, True), (60, 20, False), (12, 8, False), (7, None, False)):
            with self.subTest(remaining=remaining, work=work), devices.World(module=C) as w:
                run = w.run
                run.cleanup_mode = True
                run.phase_end = run.outer_end
                w.clock.now = run.outer_end - remaining
                start = w.clock.now
                run.guard = Mock(side_effect=lambda force=False: run.tick())
                if work is not None:
                    w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                if passes:
                    run.command(*request.args, **request.kwargs)
                else:
                    with self.assertRaises(C.DeadlineFailure):
                        run.command(*request.args, **request.kwargs)
                if work is None:
                    self.assertFalse(any(e[0] == "spawn" for e in w.events))
                else:
                    self.assertEqual(run.record["commands"][0]["end_deadline_elapsed"],
                                     min(start + 24, run.outer_end) - run.start)
                    self.assertTrue(w.cleaned)
                self.assertEqual(run.outer_end - run.work_end, 60)

    def test_late_final_inventory_is_clipped_without_renewing_cleanup(self):
        requests = self.cleanup_requests()
        with devices.World(module=C) as w:
            run = w.run
            run.cleanup_mode = True
            run.phase_end = run.outer_end
            # If initial inventory and shutdown use their entire 24+25 caps
            # from the reserved 60 seconds, only 11 remain for final proof.
            w.clock.now = run.work_end + requests[0].kwargs["cap"] + requests[1].kwargs["cap"]
            self.assertEqual(run.outer_end - w.clock.now, 11)
            start = w.clock.now
            run.guard = Mock(side_effect=lambda force=False: run.tick())
            w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + 7) or 0)
            with self.assertRaises(C.DeadlineFailure):
                run.command(*requests[2].args, **requests[2].kwargs)
            self.assertEqual(run.record["commands"][0]["end_deadline_elapsed"], 1800)
            self.assertTrue(w.cleaned)
            self.assertEqual(run.outer_end - run.work_end, 60)
