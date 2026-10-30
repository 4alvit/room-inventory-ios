"""DerivedData terminal handoff: fake time, processes, traversal and signals only."""
import contextlib
from pathlib import Path
import unittest

import test_recovery_device_service as fixtures

C = fixtures.C


class DerivedWorld(fixtures.World):
    def __init__(self):
        super().__init__(module=C, count=200, actual_guard=True)
        self.root = self.run.derived
        self.stat_action = self.cost
        self.read_action = self.ready_read
        self.poll_action = lambda: 0 if self.clock.now >= self.run.start + 8 else None

    def __enter__(self):
        super().__enter__()
        self.run.prepare_derived_resource_root()
        return self

    def cost(self, info, active):
        if active or self.cleaned:
            self.clock.now += .3  # A complete walk exceeds the 26 s child-work cap.
        return info

    def ready_read(self, fd):
        if self.clock.now < self.run.start + 8:
            raise BlockingIOError()
        return b''

    def invoke(self):
        return self.run.command(['fake-child'], 'fake-boot', cap=30, on_poll=self.callback)


class DerivedHandoffTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))

    def assert_closed(self, w):
        self.assertTrue(w.cleaned)
        self.assertEqual(sum(e[0] == 'cleanup' for e in w.events), 1)
        self.assertIsNone(w.run._derived_scan_service)
        self.assertIsNone(w.run._derived_scan_context)
        self.assertIsNone(w.run.command_deadline)

    def test_timely_terminal_walk_handoff_requires_fresh_complete_accounting(self):
        with DerivedWorld() as w:
            budgets = w.run.phase_end, w.run.work_end, w.run.outer_end
            self.assertEqual(w.invoke(), b'')
            self.assertLess(w.walked, w.count)
            self.assertEqual(w.barrier_walked, w.count)
            self.assertEqual(len(w.run.last_samples), 2)  # Initial and fresh terminal only.
            self.assertTrue(all(s['derived_data']['entries'] == w.count for s in w.run.last_samples))
            self.assertEqual(w.record['derived_scan_handoff'], {
                'state': 'incomplete', 'reason': 'allowed_exit_and_both_pipe_eof'})
            self.assertLess(w.record['child_completed_elapsed'], 26)
            self.assertLess(w.record['cleanup_completed_elapsed'], 30)
            accounting = w.record['post_command_accounting']
            self.assertEqual(accounting['status'], 'COMPLETED')
            self.assertGreater(accounting['end_elapsed'], 30)
            self.assertEqual(accounting['deadline_elapsed'], budgets[0] - w.run.start)
            self.assertEqual((w.run.phase_end, w.run.work_end, w.run.outer_end), budgets)
            events = [e[0] for e in w.events]
            callback = events.index('callback')
            self.assertEqual(events[callback - 1], 'scan_close')
            self.assertLess(callback, events.index('cleanup'))
            self.assertEqual(w.record['derived_service']['terminal_barrier'], {'reached': True, 'completed': True})
            self.assert_closed(w)

    def test_missing_or_disallowed_terminal_evidence_cannot_handoff(self):
        for mode in ('one_eof', 'no_exit', 'disallowed', 'late_poll'):
            with self.subTest(mode=mode), DerivedWorld() as w:
                if mode == 'one_eof':
                    w.read_action = lambda fd: b'' if fd == 111 else b'held'
                elif mode == 'no_exit':
                    w.poll_action = lambda: None
                elif mode == 'disallowed':
                    w.poll_action = lambda: 1
                else:
                    def late():
                        w.clock.now = w.run.start + 26
                        return 0
                    w.poll_action = late
                error = fixtures.failure(w.invoke)
                self.assertIsInstance(error, C.RunFailure)
                self.assertNotIn('derived_scan_handoff', w.record)
                self.assertIsNone(w.record['post_command_accounting'])
                self.assert_closed(w)

    def test_stale_owner_root_context_and_unwind_errors_never_authorize_handoff(self):
        for mode in ('root', 'ledger', 'context', 'sentinel', 'unwind', 'late_unwind', 'callback'):
            with self.subTest(mode=mode), DerivedWorld() as w:
                if mode in ('root', 'ledger', 'context'):
                    def stale():
                        if mode == 'root':
                            w.run._owned_derived_identity = tuple(list(w.run._owned_derived_identity))
                        elif mode == 'ledger':
                            w.run.groups[-1]['record'] = {}
                        else:
                            w.run._derived_scan_context = object()
                        return 0
                    w.poll_action = stale
                elif mode == 'sentinel':
                    w.poll_action = lambda: (_ for _ in ()).throw(C._DerivedScanDeferred())
                elif mode in ('unwind', 'late_unwind'):
                    def close():
                        if w.run.groups and not w.cleaned:
                            if mode == 'unwind':
                                raise OSError('injected scan close error')
                            w.clock.now = w.run.start + 26
                    w.close_action = close
                else:
                    w.callback_action = lambda: setattr(w.run, 'derived', Path('/wrong/root'))
                error = fixtures.failure(w.invoke)
                self.assertIsInstance(error, (C.RunFailure, OSError))
                self.assertIsNone(w.record['post_command_accounting'])
                if mode == 'unwind':
                    self.assertEqual(str(error), 'injected scan close error')
                self.assert_closed(w)

    def test_failed_cleanup_or_fresh_accounting_remains_failure(self):
        for mode in ('cleanup', 'cap', 'phase_deadline', 'root_replaced'):
            with self.subTest(mode=mode), DerivedWorld() as w:
                if mode == 'cleanup':
                    w.cleanup['success'] = False
                elif mode == 'root_replaced':
                    w.cleanup_action = lambda: setattr(w.run, '_owned_derived_identity',
                        (w.run.output, w.run.derived, (1, 999), (1, 1)))
                else:
                    def reject(info, active):
                        w.cost(info, active)
                        if w.cleaned:
                            if mode == 'cap':
                                info.st_blocks = C.DERIVED_CAP // 512 + 1
                            else:
                                w.clock.now = w.run.phase_end
                        return info
                    w.stat_action = reject
                self.assertIsInstance(fixtures.failure(w.invoke), C.RunFailure)
                self.assertEqual(w.record['derived_scan_handoff']['state'], 'incomplete')
                accounting = w.record['post_command_accounting']
                if mode == 'cleanup':
                    self.assertIsNone(accounting)
                else:
                    self.assertEqual(accounting['status'], 'FAILED')
                self.assertFalse(w.record['derived_service']['terminal_barrier']['completed'])
                self.assertEqual(len(w.run.last_samples), 1)
                self.assert_closed(w)


if __name__ == '__main__':
    unittest.main()
