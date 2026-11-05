"""Pre-spawn accounting uses phase time, with no native process in these tests."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_recovery_controller as base
import test_recovery_device_service as devices
import test_recovery_operation_allowances as allowances

C = base.controller


class CommandPreparationTests(base.ControllerCase):
    fake_child = base.CommandFailureTests.fake_child
    install_requests = allowances.OperationAllowanceTests.install_requests

    def test_real_install_builders_finish_full_pre_spawn_walk_before_child_budget(self):
        requests = self.install_requests()
        requests.append(self.boot_request)
        for request in requests:
            with self.subTest(command=request.args[1]), devices.World(module=C, actual_guard=True, count=17) as w:
                run = w.run
                w.clock.now = run.start + 242
                run.phase("device")
                original = run.phase_end, run.work_end, run.outer_end
                run.last_resource_check = w.clock.now
                writes = 0

                def flush():
                    nonlocal writes
                    writes += 1
                    if writes == 1:
                        w.clock.now += 2.1  # Receipt work makes the next census due.

                run.flush = Mock(side_effect=flush)

                def inspect(info, active):
                    if not run.groups:
                        w.clock.now += 4  # 68 seconds before any child exists.
                    return info

                w.stat_action = inspect
                w.process.wait.side_effect = lambda timeout: (setattr(w.clock, "now", w.clock.now + 30) or 0)
                run.command(*request.args, **request.kwargs)
                record = run.record["commands"][0]
                self.assertEqual(sum(event[0] == "spawn" for event in w.events), 1)
                self.assertEqual(run.last_samples[0]["device"]["entries"], 17)
                self.assertEqual(w.barrier_walked, 17)
                self.assertEqual(record["post_command_accounting"]["status"], "COMPLETED")
                self.assertEqual(record["preparation"]["status"], "COMPLETED")
                self.assertAlmostEqual(record["command_cap_started_elapsed"], 312.1)
                self.assertAlmostEqual(record["start_elapsed"], 312.1)
                self.assertAlmostEqual(record["preparation"]["start_elapsed"], 242)
                self.assertAlmostEqual(record["end_deadline_elapsed"], 312.1 + request.kwargs["cap"])
                # The native diagnostic consumer retains its <=300s window;
                # preparation cost is not silently folded into that interval.
                self.assertLessEqual(record["end_deadline_elapsed"] - record["start_elapsed"], 300)
                self.assertLess(record["elapsed_seconds"], 68)
                self.assertLess(record["child_completed_elapsed"], 398.1)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def command_with_preparation(self, *, preparation=70, child_work=30, elapsed=242,
                                 cleanup=False, setup_error=None):
        run = self.run_fixture(output=False)
        run.output.mkdir(exist_ok=True)
        run.owns_output = True
        self.clock.now = run.start + elapsed
        run.phase("device")
        run.cleanup_mode = cleanup
        calls = 0

        def guard(force=False):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.clock.now += preparation
                if setup_error is not None:
                    raise setup_error
            run.tick()

        run.guard = Mock(side_effect=guard)
        run.flush = Mock()
        return run, lambda timeout: (setattr(self.clock, "now", self.clock.now + child_work) or 0)

    def test_preparation_can_exceed_child_cap_without_renewing_phase(self):
        run, wait = self.command_with_preparation(preparation=100, child_work=1)
        original = run.phase_end, run.work_end, run.outer_end
        with self.fake_child() as child:
            child.process.wait.side_effect = wait
            run.command(["injected-child"], "slow-admission", cap=90)
            child.start.assert_called_once()
            child.stop.assert_called_once()
        self.assertEqual(run.record["commands"][0]["end_deadline_elapsed"], 432)
        self.assertEqual(run.record["commands"][0]["start_elapsed"], 342)
        self.assertEqual(run.record["commands"][0]["elapsed_seconds"], 1)
        self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_preparation_exhaustion_or_insufficient_remaining_budget_never_spawns(self):
        for elapsed, preparation in ((600, 53), (600, 56), (600, 61)):
            with self.subTest(elapsed=elapsed, preparation=preparation):
                run, _ = self.command_with_preparation(elapsed=elapsed, preparation=preparation)
                with self.fake_child() as child, self.assertRaises(C.DeadlineFailure):
                    run.command(["injected-child"], "expired-admission", cap=90)
                child.start.assert_not_called()
                child.stop.assert_not_called()
                self.assertIsNone(run.record["commands"][0]["command_cap_started_elapsed"])
                self.assertEqual(run.phase_end, run.start + 660)
                self.assertIsNone(run.command_deadline)

    def test_failed_admission_preserves_error_and_never_spawns(self):
        for error in (C.ResourceAccountingFailure("unknown allocated blocks"),
                      C.RunFailure("resource cap"), OSError("stat failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                run, _ = self.command_with_preparation(setup_error=error)
                with self.fake_child() as child, self.assertRaises(type(error)) as caught:
                    run.command(["injected-child"], "failed-admission", cap=90)
                self.assertIs(caught.exception, error)
                child.start.assert_not_called()
                child.stop.assert_not_called()
                self.assertEqual(run.record["commands"][0]["preparation"]["status"], "FAILED")
                self.assertIsNone(run.command_deadline)

    def test_real_pre_spawn_census_rejects_caps_missing_allocation_and_disk_floor(self):
        for fault in ("cap", "unknown", "disk"):
            with self.subTest(fault=fault), devices.World(module=C, actual_guard=True, count=1) as w:
                run = w.run
                run.last_resource_check = w.clock.now
                ready = False

                def flush():
                    nonlocal ready
                    ready = True
                    w.clock.now += 2.1

                run.flush = Mock(side_effect=flush)
                disk = run.disk_usage
                run.disk_usage = lambda path: SimpleNamespace(free=C.ABORT_BYTES - 1) if ready and fault == "disk" else disk(path)

                def inspect(info, active):
                    info.st_blocks = None if fault == "unknown" else C.DEVICE_CAP // 512
                    return info

                w.stat_action = inspect
                with self.assertRaises(C.RunFailure):
                    run.command(["injected-child"], "bad-resource", cap=90)
                self.assertFalse(any(event[0] == "spawn" for event in w.events))
                self.assertIsNone(run.record["commands"][0]["command_cap_started_elapsed"])

    def test_new_timing_interruptions_do_not_escape_ownership_or_authorize_progress(self):
        for after_spawn in (False, True):
            with self.subTest(after_spawn=after_spawn):
                run, _ = self.command_with_preparation(preparation=0)
                elapsed = run.diagnostic_elapsed
                error = KeyboardInterrupt("timing interrupted")

                def observe(*args, **kwargs):
                    if bool(run.groups) == after_spawn:
                        raise error
                    return elapsed(*args, **kwargs)

                run.diagnostic_elapsed = observe
                with self.fake_child() as child, self.assertRaises(KeyboardInterrupt) as caught:
                    run.command(["injected-child"], "timing-interruption", cap=90)
                self.assertIs(caught.exception, error)
                self.assertEqual(child.start.call_count, int(after_spawn))
                self.assertEqual(child.stop.call_count, int(after_spawn))
                self.assertIsNone(run.command_deadline)

    def test_native_completion_at_cap_or_clipped_phase_boundary_still_fails(self):
        for elapsed, preparation, work in ((242, 70, 86), (580, 30, 46)):
            with self.subTest(elapsed=elapsed):
                run, wait = self.command_with_preparation(elapsed=elapsed, preparation=preparation, child_work=work)
                with self.fake_child() as child, self.assertRaises(C.DeadlineFailure):
                    child.process.wait.side_effect = wait
                    run.command(["injected-child"], "late-child", cap=90)
                child.start.assert_called_once()
                child.stop.assert_called_once()
                record = run.record["commands"][0]
                self.assertEqual(record["end_deadline_elapsed"], min(elapsed + preparation + 90, 660))
                self.assertIsNone(record["child_completed_elapsed"])
                self.assertIsNone(record["post_command_accounting"])

    def test_cleanup_mode_keeps_its_original_cap_including_preparation(self):
        run, wait = self.command_with_preparation(cleanup=True)
        with self.fake_child() as child, self.assertRaises(C.DeadlineFailure):
            child.process.wait.side_effect = wait
            run.command(["injected-child"], "cleanup-window", cap=90)
        child.start.assert_called_once()
        self.assertEqual(child.stop.call_args.args[1] - run.start, 332)
        self.assertEqual(run.record["commands"][0]["end_deadline_elapsed"], 332)

    def test_log_setup_uses_preparation_budget_and_failure_closes_opened_resources(self):
        for point in ("mkdir", "receipt", "selector", "second-log"):
            with self.subTest(point=point):
                run, _ = self.command_with_preparation(preparation=0)
                error = OSError("injected " + point)
                with self.fake_child() as child:
                    if point == "mkdir":
                        target = patch.object(C.Path, "mkdir", side_effect=error)
                    elif point == "receipt":
                        target = patch.object(run, "flush", side_effect=error)
                    elif point == "selector":
                        target = patch.object(C.selectors, "DefaultSelector", side_effect=error)
                    else:
                        open_log = C.Path.open

                        def open_second(path, *args, **kwargs):
                            if path.name.endswith(".stderr"):
                                raise error
                            return open_log(path, *args, **kwargs)

                        target = patch.object(C.Path, "open", open_second)
                    with target, self.assertRaises(OSError) as caught:
                        run.command(["injected-child"], "failed-log-setup", cap=90)
                    self.assertIs(caught.exception, error)
                    child.start.assert_not_called()
                    child.stop.assert_not_called()
                    for stream in child.log_streams:
                        stream.close.assert_called_once()
                self.assertEqual(run.record["commands"][0]["preparation"]["status"], "FAILED")
                self.assertIsNone(run.command_deadline)

    def test_slow_receipt_is_not_charged_to_child_but_cannot_overrun_phase(self):
        for elapsed, cost, succeeds in ((242, 70, True), (600, 56, False)):
            with self.subTest(elapsed=elapsed):
                run, wait = self.command_with_preparation(elapsed=elapsed, preparation=0)
                calls = 0

                def flush():
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        self.clock.now += cost

                run.flush = Mock(side_effect=flush)
                with self.fake_child() as child:
                    child.process.wait.side_effect = wait
                    if succeeds:
                        run.command(["injected-child"], "slow-receipt", cap=90)
                        child.start.assert_called_once()
                        self.assertEqual(run.record["commands"][0]["end_deadline_elapsed"], 402)
                    else:
                        with self.assertRaises(C.DeadlineFailure):
                            run.command(["injected-child"], "slow-receipt", cap=90)
                        child.start.assert_not_called()
