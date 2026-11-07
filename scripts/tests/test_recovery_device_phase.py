"""Startup redistribution with fake clocks/processes; no native execution."""
import contextlib
from pathlib import Path
import unittest
from unittest.mock import Mock

import test_recovery_device_service as fixtures

C = fixtures.C


class DevicePhaseTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))

    def test_old_startup_workload_cannot_borrow_expanded_test_reserve(self):
        with fixtures.World() as w:
            run = w.run
            original = run.work_end, run.outer_end
            w.clock.now = run.start + 72.408448
            run.phase('device')
            self.assertEqual(run.phase_end, run.start + 660)
            # Retained bootstatus accounting ended here, before the failed
            # install-app precommand guard. Subsequent costs are injected,
            # not a prediction about future filesystem or simulator latency.
            w.clock.now = run.start + 235.891974
            costs = [14.471945, 20, 20, 20, 20]
            barriers = []
            prechecks = []
            def guard(force=False):
                if force:
                    self.assertTrue(w.cleaned)
                    self.assertIsNone(run._derived_scan_service)
                    self.assertIsNone(run._device_scan_service)
                    barriers.append(w.clock.now)
                    w.clock.now += 75  # Round up the retained 70.004 s barrier.
                elif run.command_deadline is None:
                    prechecks.append(w.clock.now)
                    w.clock.now += costs.pop(0)
                run.tick()
            run.guard = guard
            w.cleanup_action = lambda: setattr(w.clock, 'now', w.clock.now + 1)
            for name, cap in [('install-app', 30), ('install-runner', 30),
                              ('seed-sole-photo', 30), ('app-container', 60)]:
                w.cleaned = False
                # Total child work includes any pre-spawn/live guard time and
                # stays one second inside the existing cap-minus-four limit.
                w.process.wait.side_effect = lambda timeout, cap=cap: (
                    setattr(w.clock, 'now', w.clock.now + cap - 5) or 0)
                if name == 'app-container':
                    with self.assertRaises(C.DeadlineFailure):
                        run.command(['fake-child'], name, cap=cap)
                    record = run.record['commands'][-1]
                    self.assertEqual(record['end_deadline_elapsed'], 660)
                    self.assertIsNone(record['post_command_accounting'])
                    self.assertTrue(w.cleaned)
                    break
                self.assertEqual(run.command(['fake-child'], name, cap=cap), b'')
                record = run.record['commands'][-1]
                self.assertLess(record['child_completed_elapsed'], record['end_deadline_elapsed'] - 4)
                self.assertLess(record['cleanup_completed_elapsed'], record['end_deadline_elapsed'])
                self.assertEqual(record['post_command_accounting']['status'], 'COMPLETED')
                self.assertEqual(record['post_command_accounting']['deadline_elapsed'], 660)
            self.assertEqual(len(prechecks), 4)
            self.assertEqual(len(barriers), 3)
            self.assertEqual(costs, [20])
            self.assertEqual(len(run.record['commands']), 4)
            self.assertGreater(w.clock.now, run.phase_end)
            self.assertEqual((run.work_end, run.outer_end), original)
            self.assertEqual(C.PHASE_SECONDS['device'], 180)

    def test_device_budget_cannot_renew_or_admit_a_late_build(self):
        with fixtures.World() as w:
            run = w.run
            w.clock.now = run.start + 480
            run.phase('device')
            self.assertEqual(run.phase_end - w.clock.now, 180)
            deadline = run.phase_end
            w.clock.now += 10
            run.phase('device')
            self.assertEqual(run.phase_end, deadline)
            self.assertEqual(run.phase_end - w.clock.now, 170)
        with fixtures.World() as w:
            run = w.run
            w.clock.now = run.start + 120 + 720
            with self.assertRaises(C.DeadlineFailure):
                run.phase('device')
            self.assertEqual(run.phase_end, run.start + 660)
            self.assertFalse(any(e[0] == 'spawn' for e in w.events))

    def test_startup_boundary_blocks_device_dispatch_and_preserves_all_later_reserves(self):
        for extra in (0, .001):
            with self.subTest(extra=extra), fixtures.World() as w:
                run = w.run
                original = run.work_end, run.outer_end
                run.phase('device')
                run.guard = lambda force=False: run.tick()
                w.clock.now = run.start + 660 + extra
                with self.assertRaises(C.DeadlineFailure):
                    run.command(['never-spawn'], 'install-app', cap=30)
                self.assertFalse(any(e[0] == 'spawn' for e in w.events))
                self.assertEqual(run.record['commands'], [])
                with self.assertRaises(C.DeadlineFailure):
                    run.phase('device')
                self.assertEqual((run.work_end, run.outer_end), original)
        with fixtures.World() as w:
            run = w.run
            run.phase('device')
            w.clock.now = run.phase_end
            run.phase('test')
            self.assertEqual(run.phase_end - w.clock.now, 1020)
            w.clock.now = run.phase_end
            run.phase('collect')
            self.assertEqual(run.phase_end - w.clock.now, 240)
            self.assertEqual(run.phase_end, run.work_end)
            self.assertEqual(run.outer_end - run.work_end, 60)
            w.clock.now = run.work_end
            with self.assertRaises(C.DeadlineFailure):
                run.tick()
            with self.assertRaises(C.DeadlineFailure):
                run.phase('collect')
            self.assertEqual(run.outer_end - run.work_end, 60)

    def test_expanded_test_work_still_requires_fresh_complete_terminal_accounting(self):
        with fixtures.World(actual_guard=True, count=17) as w:
            run = w.run
            w.clock.now = run.start + 660
            run.phase('test')
            original = run.phase_end, run.work_end, run.outer_end
            start = w.clock.now
            w.process.wait.side_effect = lambda timeout: (
                setattr(w.clock, 'now', start + 900) or 0)
            w.cleanup_action = lambda: setattr(w.clock, 'now', w.clock.now + .25)
            def inspect(info, active):
                if w.cleaned:
                    w.clock.now += 2
                return info
            w.stat_action = inspect
            self.assertEqual(run.command(['fake-child'], 'ui-test', cap=1020), b'')
            record = run.record['commands'][0]
            self.assertEqual(record['end_deadline_elapsed'], 1680)
            self.assertEqual(record['child_completed_elapsed'], 1560)
            self.assertEqual(record['post_command_accounting']['status'], 'COMPLETED')
            self.assertEqual(record['post_command_accounting']['deadline_elapsed'], 1680)
            self.assertEqual(w.barrier_walked, 17)
            self.assertEqual(run.last_samples[-1]['device']['entries'], 17)
            self.assertTrue(record['cleanup']['leader_reaped'])
            self.assertEqual(record['cleanup']['group_state'], 'absent')
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)
            self.assertEqual(run.work_end - run.phase_end, 240)
            self.assertEqual(run.outer_end - run.work_end, 60)

    def test_expanded_test_rejects_late_child_or_incomplete_terminal_accounting(self):
        for work, accounting in ((1016, False), (1010, True)):
            with self.subTest(work=work), fixtures.World(actual_guard=True, count=17) as w:
                run = w.run
                w.clock.now = run.start + 660
                run.phase('test')
                original = run.phase_end, run.work_end, run.outer_end
                start = w.clock.now
                w.process.wait.side_effect = lambda timeout: (
                    setattr(w.clock, 'now', start + work) or 0)
                w.cleanup_action = lambda: setattr(w.clock, 'now', w.clock.now + .25)
                def inspect(info, active):
                    if w.cleaned:
                        w.clock.now += 2
                    return info
                w.stat_action = inspect
                with self.assertRaises(C.DeadlineFailure):
                    run.command(['fake-child'], 'ui-test', cap=1020)
                record = run.record['commands'][0]
                if accounting:
                    self.assertEqual(record['post_command_accounting']['status'], 'FAILED')
                    self.assertEqual(record['device_service']['terminal_barrier'],
                                     {'reached': True, 'completed': False})
                else:
                    self.assertIsNone(record['post_command_accounting'])
                self.assertTrue(w.cleaned)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)
                self.assertEqual(run.work_end - run.phase_end, 240)
                self.assertEqual(run.outer_end - run.work_end, 60)

    def test_expanded_test_does_not_admit_command_without_cleanup_time(self):
        for remaining in (7, 4, 0):
            with self.subTest(remaining=remaining), fixtures.World() as w:
                run = w.run
                w.clock.now = run.start + 660
                run.phase('test')
                deadline = run.phase_end
                w.clock.now = deadline - remaining
                with self.assertRaises(C.DeadlineFailure):
                    run.command(['never-spawn'], 'ui-test', cap=1020)
                self.assertFalse(any(e[0] == 'spawn' for e in w.events))
                self.assertEqual(run.record['commands'], [])
                self.assertEqual(run.phase_end, deadline)

    def test_expanded_phase_never_extends_individual_child_work_cap(self):
        with fixtures.World() as w:
            run = w.run
            w.clock.now = run.start + 72.408448
            run.phase('device')
            run.guard = Mock(side_effect=lambda force=False: run.tick())
            started = w.clock.now
            w.process.wait.side_effect = lambda timeout: (
                setattr(w.clock, 'now', started + 26) or 0)
            with self.assertRaises(C.DeadlineFailure):
                run.command(['fake-child'], 'install-app', cap=30)
            self.assertEqual(run.record['commands'][0]['end_deadline_elapsed'], started - run.start + 30)
            self.assertIsNone(run.record['commands'][0]['post_command_accounting'])
            self.assertTrue(w.cleaned)
            self.assertIsNone(run.command_deadline)


class SharedInstallationTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))

    def configure(self, world, *, elapsed=280, work=(120, 10), preparation=(5, 5), accounting=(8, 8)):
        run = world.run
        world.clock.now = run.start + elapsed
        run.phase('device')
        run.app, run.runner = Path('/owned/app'), Path('/owned/runner')
        work, preparation, accounting = list(work), list(preparation), list(accounting)
        def guard(force=False):
            if force:
                self.assertTrue(world.cleaned)
                world.clock.now += accounting.pop(0)
            elif run.command_deadline is None:
                world.cleaned = False
                world.clock.now += preparation.pop(0)
            run.tick()
        run.guard = guard
        world.process.wait.side_effect = lambda timeout: (
            setattr(world.clock, 'now', world.clock.now + work.pop(0)) or 0)
        world.cleanup_action = lambda: setattr(world.clock, 'now', world.clock.now + 1)
        return run, (run.phase_end, run.work_end, run.outer_end)

    def test_long_first_install_and_fast_second_share_one_window_with_all_costs(self):
        with fixtures.World() as w:
            run, original = self.configure(w)
            run.install_products()
            window = run.record['installation_window']
            self.assertEqual(window, dict(start_elapsed=280, end_deadline_elapsed=460,
                device_phase_end_elapsed=660, maximum_seconds=180, cleanup_per_child_seconds=4,
                status='COMPLETED', completed_elapsed=438))
            self.assertEqual([c['name'] for c in run.record['commands']], ['install-app', 'install-runner'])
            self.assertEqual([c['args'] for c in run.record['commands']], [
                ['xcrun', 'simctl', 'install', run.device_id, '/owned/app'],
                ['xcrun', 'simctl', 'install', run.device_id, '/owned/runner']])
            self.assertEqual([c['start_elapsed'] for c in run.record['commands']], [285, 419])
            for c in run.record['commands']:
                self.assertEqual(c['end_deadline_elapsed'], 460)
                self.assertEqual(c['preparation']['deadline_elapsed'], 456)
                self.assertEqual(c['post_command_accounting']['deadline_elapsed'], 460)
                self.assertEqual(c['post_command_accounting']['status'], 'COMPLETED')
                self.assertTrue(c['cleanup']['success'])
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)
            with self.assertRaises(C.ConfigurationFailure):
                run.install_products()
            self.assertEqual(sum(e[0] == 'spawn' for e in w.events), 2)

    def test_window_is_clipped_to_original_parent_and_preserves_later_reserves(self):
        with fixtures.World() as w:
            run, original = self.configure(w, elapsed=620, work=(10, 5), preparation=(1, 1), accounting=(1, 1))
            run.install_products()
            self.assertEqual(run.record['installation_window']['end_deadline_elapsed'], 660)
            self.assertEqual(run.record['installation_window']['completed_elapsed'], 641)
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)
            self.assertEqual(run.work_end - run.phase_end, 1020 + 240)
            self.assertEqual(run.outer_end - run.work_end, 60)

    def test_first_preparation_expiry_starts_no_child_and_does_not_renew(self):
        for cost in (176, 180, 181):
            with self.subTest(cost=cost), fixtures.World() as w:
                run, original = self.configure(w, preparation=(cost,))
                with self.assertRaises(C.DeadlineFailure):
                    run.install_products()
                self.assertFalse(any(e[0] == 'spawn' for e in w.events))
                self.assertEqual(run.record['installation_window']['status'], 'FAILED')
                self.assertEqual(run.record['installation_window']['end_deadline_elapsed'], 460)
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)
                with self.assertRaises(C.ConfigurationFailure):
                    run.install_products()

    def test_late_first_or_second_child_preserves_single_absolute_deadline(self):
        for work, count in (((176,), 1), ((120, 55), 2)):
            with self.subTest(work=work), fixtures.World() as w:
                run, original = self.configure(w, work=work, preparation=(0, 0), accounting=(0, 0))
                with self.assertRaises(C.DeadlineFailure):
                    run.install_products()
                self.assertEqual(sum(e[0] == 'spawn' for e in w.events), count)
                self.assertEqual(run.record['installation_window']['status'], 'FAILED')
                self.assertIsNone(run.record['installation_window']['completed_elapsed'])
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_late_full_first_accounting_blocks_second_install(self):
        for cost in (59, 60):
            with self.subTest(cost=cost), fixtures.World() as w:
                run, original = self.configure(w, work=(120,), preparation=(0,), accounting=(cost,))
                with self.assertRaises(C.DeadlineFailure):
                    run.install_products()
                self.assertEqual(sum(e[0] == 'spawn' for e in w.events), 1)
                self.assertEqual(run.record['commands'][0]['post_command_accounting']['status'], 'FAILED')
                self.assertEqual(run.record['installation_window']['status'], 'FAILED')
                self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_second_preparation_cannot_spend_a_fresh_install_allowance(self):
        with fixtures.World() as w:
            run, original = self.configure(w, work=(120,), preparation=(0, 58), accounting=(1,))
            with self.assertRaises(C.DeadlineFailure):
                run.install_products()
            self.assertEqual(sum(e[0] == 'spawn' for e in w.events), 1)
            self.assertEqual(run.record['installation_window']['end_deadline_elapsed'], 460)
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_failed_child_and_cleanup_error_keep_primary_error_and_block_second(self):
        with fixtures.World() as w:
            run, original = self.configure(w)
            w.poll_action = lambda: 3
            w.process.wait.side_effect = lambda timeout: 3
            w.cleanup.update(success=False, errors=[{'operation': 'group_probe', 'errno': 1}])
            with self.assertRaisesRegex(C.RunFailure, 'Command failed.*install-app'):
                run.install_products()
            self.assertEqual(sum(e[0] == 'spawn' for e in w.events), 1)
            self.assertTrue(run.record['cleanup_errors'])
            self.assertEqual(run.record['installation_window']['status'], 'FAILED')
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_both_installs_retain_actual_uncached_complete_resource_barriers(self):
        with fixtures.World(actual_guard=True, count=17) as w:
            run, original = self.configure(w, work=(100, 5))
            run.guard = lambda force=False: C.RecoveryRun.guard(run, force=force)
            run.install_products()
            self.assertEqual(len(run.record['commands']), 2)
            for command in run.record['commands']:
                self.assertEqual(command['post_command_accounting']['status'], 'COMPLETED')
                self.assertEqual(command['post_command_accounting']['deadline_elapsed'], 460)
                self.assertEqual(command['device_service']['terminal_barrier'],
                                 {'reached': True, 'completed': True})
                self.assertEqual(command['derived_service']['terminal_barrier'],
                                 {'reached': True, 'completed': True})
            self.assertGreaterEqual(len(run.last_samples), 4)
            self.assertTrue(all(sample['device']['entries'] == 17 for sample in run.last_samples))
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)

    def test_cancellation_restores_parent_and_original_alarm_without_second_command(self):
        with fixtures.World() as w:
            run, original = self.configure(w)
            error = KeyboardInterrupt('injected cancellation')
            run.command = Mock(side_effect=error)
            run.arm, run.disarm = Mock(), Mock()
            run.timer_enabled = True
            with self.assertRaises(KeyboardInterrupt) as caught:
                run.install_products()
            self.assertIs(caught.exception, error)
            self.assertEqual(run.command.call_count, 1)
            self.assertEqual([call.args[0] for call in run.arm.call_args_list],
                             [run.start + 456, original[0]])
            run.disarm.assert_called_once_with()
            self.assertEqual((run.phase_end, run.work_end, run.outer_end), original)


if __name__ == '__main__':
    unittest.main()
