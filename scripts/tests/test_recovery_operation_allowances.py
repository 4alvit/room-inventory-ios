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
        collector.begin_installation.assert_called_once_with()
        collector.capture_initial_exports.assert_not_called()
        calls = run.command.call_args_list
        self.assertEqual([c.args[1] for c in calls],
                         ["boot-device", "boot-status", "install-app", "install-runner", "authorize-runner-photos"])
        self.assertEqual([c.kwargs["cap"] for c in calls], [30, 300, 90, 90, 90])
        self.assertEqual(calls[1].args[0], ["xcrun", "simctl", "bootstatus", run.device_id, "-b"])
        self.boot_request = calls[1]
        self.assertEqual(calls[4].args[0], ["xcrun", "simctl", "privacy", run.device_id,
                                             "grant", "photos", C.RUNNER_BUNDLE])
        self.assertFalse(any("addmedia" in call.args[0] for call in calls))
        self.install_request = calls[2]
        self.permission_request = calls[4]
        installs = [c for c in calls if c.args[1].startswith("install-")]
        for call, app in zip(installs, (run.app, run.runner)):
            self.assertEqual(call.args[0], ["xcrun", "simctl", "install", run.device_id, app])
        self.popen.assert_not_called()
        return installs

    def test_actual_boot_request_allows_cold_start_and_requires_fresh_full_accounting(self):
        self.install_requests()
        request = self.boot_request
        for elapsed, work, scan_step in ((200, 282, 2), (540, 110, .25)):
            with self.subTest(elapsed=elapsed), devices.World(module=C, actual_guard=True, count=17) as w:
                run = w.run
                w.clock.now = run.start + elapsed
                run.phase("device")
                start = w.clock.now
                original = run.work_end, run.outer_end
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                w.cleanup_action = lambda: setattr(w.clock, "now", w.clock.now + .25)
                def inspect(info, active):
                    if w.cleaned:
                        w.clock.now += scan_step
                    return info
                w.stat_action = inspect
                run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertEqual(record["end_deadline_elapsed"], min(elapsed + 300, 660))
                self.assertGreater(record["child_completed_elapsed"] - elapsed, 86)
                self.assertLess(record["child_completed_elapsed"], record["end_deadline_elapsed"] - 4)
                self.assertEqual(record["cleanup"]["group_state"], "absent")
                self.assertTrue(record["cleanup"]["leader_reaped"])
                self.assertEqual(w.barrier_walked, 17)
                self.assertEqual(run.last_samples[-1]["device"]["entries"], 17)
                self.assertEqual(record["post_command_accounting"]["status"], "COMPLETED")
                self.assertEqual(record["post_command_accounting"]["deadline_elapsed"], 660)
                if elapsed == 200:
                    # The complete post-command walk uses the unchanged phase
                    # deadline even after the child has used most of its cap.
                    self.assertGreater(record["post_command_accounting"]["end_elapsed"],
                                       record["end_deadline_elapsed"])
                self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
                self.assertEqual((run.work_end, run.outer_end), original)
                self.assertEqual(run.outer_end - run.work_end, 60)

    def test_actual_boot_request_rejects_work_at_cap_and_clipped_startup_boundary(self):
        self.install_requests()
        request = self.boot_request
        for elapsed, work in ((200, 296), (540, 116)):
            with self.subTest(elapsed=elapsed), devices.World(module=C) as w:
                run = w.run
                w.clock.now = run.start + elapsed
                run.phase("device")
                start = w.clock.now
                run.guard = lambda force=False: run.tick()
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                with self.assertRaises(C.DeadlineFailure):
                    run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertEqual(record["end_deadline_elapsed"], min(elapsed + 300, 660))
                self.assertIsNone(record["child_completed_elapsed"])
                self.assertIsNone(record["post_command_accounting"])
                self.assertTrue(w.cleaned)
                self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
                self.assertEqual(run.outer_end - run.work_end, 60)

    def test_actual_boot_request_cannot_renew_startup_or_spawn_without_cleanup_time(self):
        self.install_requests()
        request = self.boot_request
        for elapsed in (653, 656, 660):
            with self.subTest(elapsed=elapsed), devices.World(module=C) as w:
                run = w.run
                run.phase("device")
                original = run.phase_end, run.work_end, run.outer_end
                w.clock.now = run.start + elapsed
                run.guard = lambda force=False: run.tick()
                with self.assertRaises(C.DeadlineFailure):
                    run.phase("device")
                    run.command(*request.args, **request.kwargs)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)
                self.assertEqual(run.phase_end, run.start + 660)
                self.assertFalse(any(e[0] == "spawn" for e in w.events))

    def test_single_install_allows_slow_install_and_requires_fresh_full_accounting(self):
        self.install_requests()
        request = self.install_request
        for elapsed, work, scan_step in ((270, 80, 2), (620, 30, .25)):
            with self.subTest(elapsed=elapsed), devices.World(module=C, actual_guard=True, count=17) as w:
                run = w.run
                w.clock.now = run.start + elapsed
                run.phase("device")
                original = run.phase_end, run.work_end, run.outer_end
                start = w.clock.now
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                w.cleanup_action = lambda: setattr(w.clock, "now", w.clock.now + .25)
                def inspect(info, active):
                    if w.cleaned:
                        w.clock.now += scan_step
                    return info
                w.stat_action = inspect
                run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertEqual(record["end_deadline_elapsed"], min(elapsed + 90, 660))
                self.assertGreater(record["child_completed_elapsed"] - elapsed, 26)
                self.assertLess(record["child_completed_elapsed"], record["end_deadline_elapsed"] - 4)
                self.assertEqual(record["cleanup"]["group_state"], "absent")
                self.assertTrue(record["cleanup"]["leader_reaped"])
                self.assertEqual(w.barrier_walked, 17)
                self.assertEqual(run.last_samples[-1]["device"]["entries"], 17)
                self.assertEqual(record["post_command_accounting"]["status"], "COMPLETED")
                self.assertEqual(record["post_command_accounting"]["deadline_elapsed"], 660)
                if elapsed == 270:
                    self.assertGreater(record["post_command_accounting"]["end_elapsed"],
                                       record["end_deadline_elapsed"])
                self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_single_install_rejects_late_completion_at_own_or_startup_limit(self):
        self.install_requests()
        request = self.install_request
        for elapsed, work in ((270, 86), (620, 36)):
            with self.subTest(elapsed=elapsed), devices.World(module=C) as w:
                run = w.run
                w.clock.now = run.start + elapsed
                run.phase("device")
                run.guard = lambda force=False: run.tick()
                start = w.clock.now
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                with self.assertRaises(C.DeadlineFailure):
                    run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertEqual(record["end_deadline_elapsed"], min(elapsed + 90, 660))
                self.assertIsNone(record["child_completed_elapsed"])
                self.assertIsNone(record["post_command_accounting"])
                self.assertTrue(w.cleaned)
                self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)

    def test_timely_install_cannot_succeed_with_incomplete_terminal_accounting(self):
        self.install_requests()
        with devices.World(module=C, actual_guard=True, count=17) as w:
            run = w.run
            w.clock.now = run.start + 620
            run.phase("device")
            original = run.phase_end, run.work_end, run.outer_end
            start = w.clock.now
            w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + 30) or 0)
            w.cleanup_action = lambda: setattr(w.clock, "now", w.clock.now + .25)
            def inspect(info, active):
                if w.cleaned:
                    w.clock.now += 1
                return info
            w.stat_action = inspect
            with self.assertRaises(C.DeadlineFailure):
                run.command(*self.install_request.args, **self.install_request.kwargs)
            record = run.record["commands"][0]
            self.assertLess(record["child_completed_elapsed"], record["end_deadline_elapsed"] - 4)
            self.assertEqual(record["post_command_accounting"]["status"], "FAILED")
            self.assertEqual(record["device_service"]["terminal_barrier"],
                             {"reached": True, "completed": False})
            self.assertTrue(w.cleaned)
            self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_single_install_cannot_renew_startup_or_spawn_without_cleanup_time(self):
        self.install_requests()
        for elapsed in (653, 656, 660):
            with self.subTest(elapsed=elapsed), devices.World(module=C) as w:
                run = w.run
                run.phase("device")
                original = run.phase_end, run.work_end, run.outer_end
                w.clock.now = run.start + elapsed
                run.guard = lambda force=False: run.tick()
                with self.assertRaises(C.DeadlineFailure):
                    run.phase("device")
                    run.command(*self.install_request.args, **self.install_request.kwargs)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)
                self.assertFalse(any(e[0] == "spawn" for e in w.events))
                self.assertEqual(run.record["commands"], [])

    def test_photos_permission_targets_only_owned_runner_before_photokit_setup(self):
        self.install_requests()
        # install_requests already exercises the real prepare_device builder.
        for value in ({}, {"NSPhotoLibraryUsageDescription": ""},
                      {"NSPhotoLibraryUsageDescription": "  "},
                      {"NSPhotoLibraryUsageDescription": True},
                      {"NSPhotoLibraryUsageDescription": "a" * 4097}):
            with self.subTest(value=value), self.assertRaises(C.ConfigurationFailure):
                C.validate_runner_photos_metadata(value)
        C.validate_runner_photos_metadata({"NSPhotoLibraryUsageDescription": "Automated testing"})
        self.popen.assert_not_called()

    def test_photos_grant_allows_cold_service_and_requires_fresh_full_accounting(self):
        self.install_requests()
        request = self.permission_request
        for elapsed, work, scan_step in ((344.180151, 80, 2), (620, 30, .25)):
            with self.subTest(elapsed=elapsed), devices.World(module=C, actual_guard=True, count=17) as w:
                run = w.run
                w.clock.now = run.start + elapsed
                run.phase("device")
                original = run.phase_end, run.work_end, run.outer_end
                start = w.clock.now
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                w.cleanup_action = lambda: setattr(w.clock, "now", w.clock.now + .25)
                def inspect(info, active):
                    if w.cleaned:
                        w.clock.now += scan_step
                    return info
                w.stat_action = inspect
                run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertAlmostEqual(record["end_deadline_elapsed"], min(elapsed + 90, 660))
                self.assertGreater(record["child_completed_elapsed"] - elapsed, 26)
                self.assertLess(record["child_completed_elapsed"], record["end_deadline_elapsed"] - 4)
                self.assertEqual(record["cleanup"]["group_state"], "absent")
                self.assertTrue(record["cleanup"]["leader_reaped"])
                self.assertEqual(w.barrier_walked, 17)
                self.assertEqual(run.last_samples[-1]["device"]["entries"], 17)
                self.assertEqual(record["post_command_accounting"]["status"], "COMPLETED")
                self.assertEqual(record["post_command_accounting"]["deadline_elapsed"], 660)
                if elapsed < 620:
                    self.assertGreater(record["post_command_accounting"]["end_elapsed"],
                                       record["end_deadline_elapsed"])
                self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_photos_grant_rejects_own_and_clipped_work_boundaries(self):
        self.install_requests()
        request = self.permission_request
        for elapsed, work in ((344.180151, 86), (344.180151, 86.5), (620, 36)):
            with self.subTest(elapsed=elapsed, work=work), devices.World(module=C) as w:
                run = w.run
                w.clock.now = run.start + elapsed
                run.phase("device")
                original = run.phase_end, run.work_end, run.outer_end
                run.guard = lambda force=False: run.tick()
                start = w.clock.now
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                with self.assertRaises(C.DeadlineFailure):
                    run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertAlmostEqual(record["end_deadline_elapsed"], min(elapsed + 90, 660))
                self.assertIsNone(record["child_completed_elapsed"])
                self.assertIsNone(record["post_command_accounting"])
                self.assertTrue(w.cleaned)
                self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_photos_grant_cannot_succeed_with_incomplete_terminal_accounting(self):
        self.install_requests()
        with devices.World(module=C, actual_guard=True, count=17) as w:
            run = w.run
            w.clock.now = run.start + 620
            run.phase("device")
            original = run.phase_end, run.work_end, run.outer_end
            start = w.clock.now
            w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + 30) or 0)
            w.cleanup_action = lambda: setattr(w.clock, "now", w.clock.now + .25)
            def inspect(info, active):
                if w.cleaned:
                    w.clock.now += 1
                return info
            w.stat_action = inspect
            with self.assertRaises(C.DeadlineFailure):
                run.command(*self.permission_request.args, **self.permission_request.kwargs)
            record = run.record["commands"][0]
            self.assertLess(record["child_completed_elapsed"], record["end_deadline_elapsed"] - 4)
            self.assertEqual(record["post_command_accounting"]["status"], "FAILED")
            self.assertEqual(record["device_service"]["terminal_barrier"],
                             {"reached": True, "completed": False})
            self.assertTrue(w.cleaned)
            self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_photos_grant_cannot_renew_startup_or_spawn_without_cleanup_time(self):
        self.install_requests()
        request = self.permission_request
        for elapsed in (653, 656, 660):
            with self.subTest(elapsed=elapsed), devices.World(module=C) as w:
                run = w.run
                run.phase("device")
                original = run.phase_end, run.work_end, run.outer_end
                w.clock.now = run.start + elapsed
                run.guard = lambda force=False: run.tick()
                with self.assertRaises(C.DeadlineFailure):
                    run.phase("device")
                    run.command(*request.args, **request.kwargs)
                self.assertFalse(any(e[0] == "spawn" for e in w.events))
                self.assertEqual(run.record["commands"], [])
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def collection_shutdown_request(self):
        # Exercise the actual collection-entry builder and its admission gates.
        run = self.run_fixture()
        run.bind_output_resource_root()
        run.prepare_derived_resource_root()
        run.device_id = "44444444-4444-4444-8444-444444444444"
        run.device_root = self.devices / run.device_id
        run.device_root.mkdir()
        run.bind_device_resource_root()
        root = run.output / "evidence/collection"
        copied, original = root / "xcresult/verified.xcresult", run.output / "original.xcresult"
        copied.mkdir(parents=True)
        original.mkdir()
        run.collector = Mock(root=root, xc_copy=copied, xc_original=original,
                             live_seal={"test": True}, seal_sha256="a" * 64)
        run.record["phase"] = "collect"
        run.record["commands"].append({"name": "ui-test", "exit_code": 0, "primary_error": None,
            "cleanup": {"success": True, "group_state": "absent", "leader_reaped": True}})
        run.groups = [{"state": {"group_state": "absent", "leader_reaped": True}}]
        state = json.dumps({"devices": {"runtime": [{"udid": run.device_id, "state": "Shutdown"}]}}).encode()
        run.command = Mock(side_effect=[b"", state])
        run.begin_offline_collection(copied)
        calls = run.command.call_args_list
        self.assertEqual([c.args[1] for c in calls], ["collection-shutdown", "collection-device-state"])
        self.assertEqual(calls[1].kwargs["cap"], 24)
        self.assertEqual(calls[0].args[0], ["xcrun", "simctl", "shutdown", run.device_id])
        self.assertEqual(run.record["offline_collection"]["shutdown_state"], "Shutdown")
        self.assertIn("device", run.last_samples[-1])
        self.assertIn("derived_data", run.last_samples[-1])
        self.popen.assert_not_called()
        return calls[0]

    def test_collection_shutdown_allows_slow_exit_with_fresh_full_accounting(self):
        request = self.collection_shutdown_request()
        for phase_start, elapsed, work, scan_step in ((700, 700, 80, 2),
                                                     (700, 900, 30, .25),
                                                     (1780, 1880, 30, .25)):
            with self.subTest(elapsed=elapsed), devices.World(module=C, actual_guard=True, count=17) as w:
                run = w.run
                w.clock.now = run.start + phase_start
                run.phase("collect")
                original = run.phase_end, run.work_end, run.outer_end
                w.clock.now = start = run.start + elapsed
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                w.cleanup_action = lambda: setattr(w.clock, "now", w.clock.now + .25)
                def inspect(info, active):
                    if w.cleaned:
                        w.clock.now += scan_step
                    return info
                w.stat_action = inspect
                run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertEqual(record["end_deadline_elapsed"], min(elapsed + 90, phase_start + 240, 1920))
                self.assertGreater(record["child_completed_elapsed"] - elapsed, 21)
                self.assertLess(record["child_completed_elapsed"], record["end_deadline_elapsed"] - 4)
                self.assertTrue(record["cleanup"]["success"])
                self.assertEqual(record["cleanup"]["group_state"], "absent")
                self.assertTrue(record["cleanup"]["leader_reaped"])
                self.assertEqual(w.barrier_walked, 17)
                self.assertEqual(run.last_samples[-1]["device"]["entries"], 17)
                self.assertEqual(record["post_command_accounting"]["status"], "COMPLETED")
                self.assertEqual(record["post_command_accounting"]["deadline_elapsed"], original[0] - run.start)
                if elapsed == 700:
                    self.assertGreater(record["post_command_accounting"]["end_elapsed"], record["end_deadline_elapsed"])
                self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_collection_shutdown_rejects_own_collection_and_outer_work_boundaries(self):
        request = self.collection_shutdown_request()
        for phase_start, elapsed, work in ((700, 700, 86), (700, 700, 86.5),
                                           (700, 900, 36), (1780, 1880, 36)):
            with self.subTest(elapsed=elapsed, work=work), devices.World(module=C) as w:
                run = w.run
                w.clock.now = run.start + phase_start
                run.phase("collect")
                original = run.phase_end, run.work_end, run.outer_end
                w.clock.now = start = run.start + elapsed
                run.guard = lambda force=False: run.tick()
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + work) or 0)
                with self.assertRaises(C.DeadlineFailure):
                    run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertIsNone(record["child_completed_elapsed"])
                self.assertIsNone(record["post_command_accounting"])
                self.assertTrue(w.cleaned)
                self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_collection_shutdown_cannot_spawn_with_exhausted_existing_budget(self):
        request = self.collection_shutdown_request()
        for phase_start in (700, 1780):
            for remaining in (7, 4, 0):
                with self.subTest(phase_start=phase_start, remaining=remaining), devices.World(module=C) as w:
                    run = w.run
                    w.clock.now = run.start + phase_start
                    run.phase("collect")
                    original = run.phase_end, run.work_end, run.outer_end
                    w.clock.now = run.phase_end - remaining
                    run.guard = lambda force=False: run.tick()
                    with self.assertRaises(C.DeadlineFailure):
                        run.command(*request.args, **request.kwargs)
                    self.assertFalse(any(e[0] == "spawn" for e in w.events))
                    self.assertEqual(run.record["commands"], [])
                    self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_collection_shutdown_cannot_skip_late_full_accounting(self):
        request = self.collection_shutdown_request()
        with devices.World(module=C, actual_guard=True, count=17) as w:
            run = w.run
            w.clock.now = run.start + 700
            run.phase("collect")
            original = run.phase_end, run.work_end, run.outer_end
            w.clock.now = start = run.start + 900
            w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", start + 30) or 0)
            w.cleanup_action = lambda: setattr(w.clock, "now", w.clock.now + .25)
            def inspect(info, active):
                if w.cleaned:
                    w.clock.now += 1
                return info
            w.stat_action = inspect
            with self.assertRaises(C.DeadlineFailure):
                run.command(*request.args, **request.kwargs)
            record = run.record["commands"][0]
            self.assertLess(record["child_completed_elapsed"], record["end_deadline_elapsed"] - 4)
            self.assertEqual(record["post_command_accounting"]["status"], "FAILED")
            self.assertEqual(record["device_service"]["terminal_barrier"], {"reached": True, "completed": False})
            self.assertTrue(w.cleaned)
            self.assertEqual(sum(e[0] == "spawn" for e in w.events), 1)
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

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
        self.assertEqual([c.kwargs["cap"] for c in calls], [24, 25, 30])
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
                self.assertEqual(record["post_command_accounting"]["deadline_elapsed"], 660)
                self.assertTrue(any(c.kwargs == {"force": True} for c in run.guard.call_args_list))
                self.assertEqual((run.work_end, run.outer_end), original)

    def test_actual_install_admission_rejects_child_boundary_and_startup_exhaustion(self):
        request = self.install_requests()[0]
        for elapsed, work in ((217.613819, 86), (652, 4), (660, None)):
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
                self.assertEqual(run.phase_end, run.start + 660)

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

    def cleanup_with_final_observation(self, work, *, states=("Shutdown",), final_udid=None):
        with devices.World(module=C) as world:
            run = world.run
            world.clock.now = run.start + 880
            run.guard = lambda force=False: run.tick()
            emitted = set()

            def read(fd):
                name = run.record["commands"][-1]["name"]
                if fd != 111 or name in emitted:
                    return b""
                emitted.add(name)
                if name == "shutdown-owned-device":
                    return b""
                observations = ([{"udid": run.device_id, "state": "Booted"}]
                                if name == "device-cleanup-before" else
                                [{"udid": final_udid or run.device_id, "state": state}
                                 for state in states])
                return json.dumps({"devices": {"runtime": observations}}).encode()

            def wait(timeout):
                record = run.record["commands"][-1]
                if record["name"] == "device-final-state":
                    world.clock.now = run.start + record["start_elapsed"] + work
                return 0

            world.read_action = read
            world.process.wait.side_effect = wait
            run.cleanup()
            return world

    def test_single_final_inventory_accepts_slow_timely_shutdown_proof(self):
        for work in (13, 20, 25.5):
            with self.subTest(work=work):
                world = self.cleanup_with_final_observation(work)
                run = world.run
                self.assertEqual([c["name"] for c in run.record["commands"]],
                                 ["device-cleanup-before", "shutdown-owned-device", "device-final-state"])
                final = run.record["commands"][-1]
                self.assertEqual(final["args"], ["xcrun", "simctl", "list", "devices", "--json"])
                self.assertEqual(final["end_deadline_elapsed"] - final["start_elapsed"], 30)
                self.assertEqual(final["exit_code"], 0)
                self.assertTrue(final["cleanup"]["success"])
                self.assertTrue(final["cleanup"]["leader_reaped"])
                self.assertEqual(final["cleanup"]["group_state"], "absent")
                self.assertEqual(run.record["device_final_state"], "Shutdown")
                self.assertEqual(run.record["cleanup_errors"], [])
                self.assertEqual(sum(e[0] == "spawn" for e in world.events), 3)
                self.assertEqual(run.phase_end, run.outer_end)
                self.assertEqual(run.outer_end - run.work_end, 60)

    def test_final_inventory_rejects_exact_and_late_work_boundary_without_retry(self):
        for work in (26, 26.5):
            with self.subTest(work=work):
                world = self.cleanup_with_final_observation(work)
                run = world.run
                final = run.record["commands"][-1]
                self.assertEqual(final["primary_error"]["type"], "DeadlineFailure")
                self.assertNotIn("device_final_state", run.record)
                self.assertEqual([e["operation"] for e in run.record["cleanup_errors"]], ["final_state"])
                self.assertEqual(sum(c["name"] == "device-final-state" for c in run.record["commands"]), 1)
                self.assertTrue(final["cleanup"]["success"])
                self.assertEqual(sum(e[0] == "spawn" for e in world.events), 3)

    def test_final_inventory_still_requires_one_exact_owned_shutdown_state(self):
        for states, udid in (((), None), (("Booted",), None),
                             (("Shutdown", "Shutdown"), None),
                             (("Shutdown",), "44444444-4444-4444-8444-444444444444")):
            with self.subTest(states=states, udid=udid):
                world = self.cleanup_with_final_observation(13, states=states, final_udid=udid)
                run = world.run
                self.assertEqual(run.record["commands"][-1]["exit_code"], 0)
                self.assertNotIn("device_final_state", run.record)
                self.assertEqual([e["operation"] for e in run.record["cleanup_errors"]], ["final_state"])
                self.assertIn("shutdown not established", run.record["cleanup_errors"][0]["error"])
                self.assertEqual(sum(e[0] == "spawn" for e in world.events), 3)

    def test_final_inventory_insufficient_outer_admission_starts_no_child(self):
        request = self.cleanup_requests()[2]
        for remaining in (7.99, 4, 0):
            with self.subTest(remaining=remaining), devices.World(module=C) as world:
                run = world.run
                run.cleanup_mode = True
                run.phase_end = run.outer_end
                world.clock.now = run.outer_end - remaining
                run.guard = lambda force=False: run.tick()
                with self.assertRaises(C.DeadlineFailure):
                    run.command(*request.args, **request.kwargs)
                self.assertEqual(run.record["commands"], [])
                self.assertFalse(any(e[0] == "spawn" for e in world.events))
                self.assertEqual(world.logs, [])

    def test_observed_shutdown_does_not_clear_prior_group_permission_failure(self):
        run = self.run_fixture(output=False)
        run.device_id = "44444444-4444-4444-8444-444444444444"
        observation = {"operation": "group_probe", "errno": 1, "error": "PermissionError"}
        state = {"group_state": "absent", "leader_reaped": True, "returncode": 0,
                 "observation_errors": [observation], "cleanup_deadline_monotonic": self.clock() + 4}
        deadline = state["cleanup_deadline_monotonic"]
        run.groups.append({"process": Mock(pid=43210, returncode=0), "state": state,
                           "record": {"name": "prior-command", "cleanup": {"success": False}}})
        prior_error = {"command": "prior-command", "operation": "owned_group", "error": "group_probe EPERM"}
        run.record["cleanup_errors"].append(prior_error)
        listing = json.dumps({"devices": {"runtime": [{"udid": run.device_id, "state": "Shutdown"}]}}).encode()
        run.command = Mock(side_effect=[listing, listing])
        with patch.object(C.os, "killpg", side_effect=AssertionError("No group signalling expected")) as signals:
            run.cleanup()
        self.assertEqual(run.record["device_final_state"], "Shutdown")
        self.assertEqual([c.args[1] for c in run.command.call_args_list],
                         ["device-cleanup-before", "device-final-state"])
        self.assertIs(run.record["cleanup_errors"][0], prior_error)
        self.assertFalse(run.record["cleanup_errors"][-1]["final_observation"]["success"])
        self.assertEqual(state["observation_errors"], [observation])
        self.assertEqual(state["cleanup_deadline_monotonic"], deadline)
        signals.assert_not_called()

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
            self.assertEqual(run.record["commands"][0]["end_deadline_elapsed"], 1980)
            self.assertTrue(w.cleaned)
            self.assertEqual(run.outer_end - run.work_end, 60)
