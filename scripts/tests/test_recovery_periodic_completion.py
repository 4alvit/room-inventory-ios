"""Periodic completion cadence with injected clock, metadata and persistence."""
import contextlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_recovery_device_service as fixtures

C = fixtures.C


class PeriodicCompletionTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))

    @staticmethod
    def slow_entries(w):
        def inspect(info, active):
            w.clock.now += 5
            return info
        w.stat_action = inspect

    def test_long_complete_walk_waits_two_seconds_and_force_remains_uncached(self):
        with fixtures.World(count=1, actual_guard=True) as w:
            self.slow_entries(w)
            w.run.guard()
            self.assertEqual(w.run.last_resource_check, w.clock.now)
            completed = w.clock.now
            self.assertEqual(completed - w.run.start, 5)
            scans = C.os.scandir.call_count
            w.count = 2  # Later walks must observe changed injected metadata.
            w.run.guard()
            self.assertEqual(C.os.scandir.call_count, scans)
            w.clock.now = completed + 1.999
            w.run.guard()
            self.assertEqual(C.os.scandir.call_count, scans)
            self.assertEqual(len(w.run.last_samples), 1)
            w.clock.now = completed + 2
            w.run.guard()
            self.assertGreater(C.os.scandir.call_count, scans)
            self.assertEqual(w.run.last_samples[-1]['device']['entries'], 2)
            self.assertEqual(w.run.last_resource_check, w.clock.now)
            self.assertEqual(len(w.run.last_samples), 2)
            w.count = 3
            w.run.guard(force=True)
            self.assertEqual(w.run.last_samples[-1]['device']['entries'], 3)
            self.assertEqual(len(w.run.last_samples), 3)
            self.assertEqual(w.run.last_resource_check, w.clock.now)

    def test_failed_cap_walk_and_both_handoff_sentinels_do_not_advance_completion(self):
        for mode in ('io', 'cap', 'deadline', 'device_handoff', 'derived_handoff'):
            with self.subTest(mode=mode), fixtures.World(count=1, actual_guard=True) as w:
                self.slow_entries(w)
                w.run.guard()
                completed = w.run.last_resource_check
                w.clock.now = completed + 2
                def fail(info, active):
                    if mode == 'io':
                        raise OSError('injected metadata failure')
                    if mode == 'device_handoff':
                        raise C._DeviceScanDeferred()
                    if mode == 'derived_handoff':
                        raise C._DerivedScanDeferred()
                    if mode == 'cap':
                        info.st_blocks = C.DEVICE_CAP // 512 + 1
                    else:
                        w.clock.now = w.run.phase_end
                    return info
                w.stat_action = fail
                error = fixtures.failure(lambda: w.run.guard(force=True))
                self.assertIsInstance(error, (OSError, C.RunFailure, C._DeviceScanDeferred, C._DerivedScanDeferred))
                self.assertEqual(w.run.last_resource_check, completed)
                self.assertEqual(len(w.run.last_samples), 1)

    def test_failed_persistence_or_late_completion_does_not_advance_timestamp(self):
        for mode in ('write_error', 'late_write'):
            with self.subTest(mode=mode), fixtures.World(count=1, actual_guard=True) as w:
                self.slow_entries(w)
                w.run.guard()
                completed = w.run.last_resource_check
                def persist(*args):
                    if mode == 'write_error':
                        raise OSError('injected persistence failure')
                    w.clock.now = w.run.phase_end
                with patch.object(C, 'write_json', side_effect=persist):
                    error = fixtures.failure(lambda: w.run.guard(force=True))
                self.assertIsInstance(error, (OSError, C.DeadlineFailure))
                self.assertEqual(w.run.last_resource_check, completed)

    def test_periodic_suppression_still_checks_both_free_floors_and_deadline(self):
        with fixtures.World(count=1, actual_guard=True) as w:
            self.slow_entries(w)
            w.run.guard()
            completed = w.run.last_resource_check
            w.clock.now = completed + .5
            scans = C.os.scandir.call_count
            disks = sum(e[0] == 'disk' for e in w.events)
            w.run.guard()
            self.assertEqual(sum(e[0] == 'disk' for e in w.events), disks + 2)
            self.assertEqual(C.os.scandir.call_count, scans)
            for low_path in (w.run.output.parent, w.run.device_base):
                w.run.disk_usage = lambda path, low_path=low_path: SimpleNamespace(
                    free=C.ABORT_BYTES - 1 if path == low_path else 24 * C.GIB)
                with self.assertRaises(C.RunFailure):
                    w.run.guard()
                self.assertEqual(w.run.last_resource_check, completed)
                self.assertEqual(C.os.scandir.call_count, scans)
            w.run.disk_usage = w.disk
            w.clock.now = w.run.phase_end
            with self.assertRaises(C.DeadlineFailure):
                w.run.guard()
            self.assertEqual(w.run.last_resource_check, completed)
            self.assertEqual(C.os.scandir.call_count, scans)


if __name__ == '__main__':
    unittest.main()
