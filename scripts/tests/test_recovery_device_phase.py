"""Startup redistribution with fake clocks/processes; no native execution."""
import contextlib
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

    def test_measured_prefix_and_remaining_command_accounting_fit_startup_budget(self):
        with fixtures.World() as w:
            run = w.run
            original = run.work_end, run.outer_end
            w.clock.now = run.start + 72.408448
            run.phase('device')
            self.assertEqual(run.phase_end, run.start + 1020)
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
                              ('seed-sole-photo', 30), ('app-container', 60),
                              ('runner-container', 60)]:
                w.cleaned = False
                # Total child work includes any pre-spawn/live guard time and
                # stays one second inside the existing cap-minus-four limit.
                w.process.wait.side_effect = lambda timeout, cap=cap: (
                    setattr(w.clock, 'now', w.clock.now + cap - 5) or 0)
                self.assertEqual(run.command(['fake-child'], name, cap=cap), b'')
                record = run.record['commands'][-1]
                self.assertLess(record['child_completed_elapsed'], record['end_deadline_elapsed'] - 4)
                self.assertLess(record['cleanup_completed_elapsed'], record['end_deadline_elapsed'])
                self.assertEqual(record['post_command_accounting']['status'], 'COMPLETED')
                self.assertEqual(record['post_command_accounting']['deadline_elapsed'], 1020)
            self.assertEqual(len(prechecks), 5)
            self.assertEqual(len(barriers), 5)
            self.assertFalse(costs)
            self.assertAlmostEqual(w.clock.now - run.start, 895.363919)
            self.assertGreater(run.phase_end - w.clock.now, 124)
            self.assertEqual((run.work_end, run.outer_end), original)
            self.assertEqual(C.PHASE_SECONDS['device'], 180)

    def test_full_earlier_allowances_leave_original_device_budget_without_renewal(self):
        with fixtures.World() as w:
            run = w.run
            w.clock.now = run.start + 120 + 720
            run.phase('device')
            self.assertEqual(run.phase_end - w.clock.now, 180)
            deadline = run.phase_end
            w.clock.now += 10
            run.phase('device')
            self.assertEqual(run.phase_end, deadline)
            self.assertEqual(run.phase_end - w.clock.now, 170)

    def test_startup_boundary_blocks_device_dispatch_and_preserves_all_later_reserves(self):
        for extra in (0, .001):
            with self.subTest(extra=extra), fixtures.World() as w:
                run = w.run
                original = run.work_end, run.outer_end
                run.phase('device')
                run.guard = lambda force=False: run.tick()
                w.clock.now = run.start + 1020 + extra
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
            self.assertEqual(run.phase_end - w.clock.now, 480)
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


if __name__ == '__main__':
    unittest.main()
