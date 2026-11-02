"""Owned live DerivedData child disappearance; filesystem/native work is injected."""
import errno
from pathlib import Path
import stat
import unittest
from unittest.mock import patch

import test_recovery_vanished_device_child as support

C = support.C


class DerivedWorld(support.World):
    def __init__(self):
        super().__init__()
        self.run.device_root = None
        self.root = self.run.derived
        self.entries = {self.root: []}
        self.run.owns_output = True
        self.root_exists = False
        self.output_info = support.info(mode=stat.S_IFDIR, ino=10)
        self.output_lstats = 0
        self.mkdirs = 0

    def lstat(self, path):
        if path == self.run.output:
            self.output_lstats += 1
            return self.output_info
        return super().lstat(path)

    def mkdir(self, path, *, mode):
        assert path == self.root and mode == 0o700
        self.mkdirs += 1
        if self.root_exists:
            raise FileExistsError(errno.EEXIST, 'preexisting root')
        self.root_exists = True

    def bind(self):
        self.run.prepare_derived_resource_root()

    def service(self):
        self.service_calls += 1
        self.run.tick()

    def scan_derived(self, cap=C.DERIVED_CAP, **kwargs):
        return self.run.resource_size('derived_data', self.root, cap,
                                      cap_metric='allocated', **kwargs)

    def __enter__(self):
        super().__enter__()
        self.stack.enter_context(patch.object(Path, 'mkdir', lambda path, **kw: self.mkdir(path, **kw)))
        return self


class DerivedChildTests(unittest.TestCase):
    setUp = support.VanishedDeviceTests.setUp

    def test_build_binds_created_derived_root_before_native_command(self):
        with DerivedWorld() as w:
            stop = RuntimeError('injected command boundary')
            def command(args, name, **kwargs):
                self.assertEqual(name, 'build')
                self.assertIs(w.run._owned_derived_identity[1], w.root)
                self.assertEqual(args[args.index('-derivedDataPath') + 1], w.root)
                raise stop
            with patch.object(w.run, 'command', side_effect=command):
                self.assertIs(support.thrown(w.run.build), stop)
            self.assertEqual(w.mkdirs, 1)
            bound = w.run._owned_derived_identity
            self.assertIsInstance(support.thrown(w.bind), C.ConfigurationFailure)
            self.assertIs(w.run._owned_derived_identity, bound)
            self.assertEqual(w.mkdirs, 1)

    def test_vanished_pcm_child_preserves_allocation_attempt_and_service_limits(self):
        with DerivedWorld() as w:
            w.bind()
            w.run._derived_scan_service = w.service
            missing = FileNotFoundError(errno.ENOENT, 'renamed pcm.tmp')
            w.set_children(support.info(size=7, blocks=2), missing, support.info(size=5, blocks=3))
            result = w.scan_derived()
            self.assertEqual(result, dict(logical_bytes=12, allocated_bytes=3072, entries=2,
                cap_metric='allocated', attempted_entries=3, vanished_entries=1, vanished_directories=0))
            self.assertGreater(w.service_calls, 0)
            self.assertEqual(w.stats, ['0', '1', '2'])
            # The same observed blocks still reach the exact cap; disappearance
            # cannot reset charged bytes or authorize an extra entry attempt.
            error = support.thrown(lambda: w.scan_derived(cap=3072))
            self.assertIsInstance(error, C.RunFailure)
            self.assertEqual(w.run.record['resource_cap_crossing']['allocated_bytes'], 3072)
            w.set_children(missing, missing, missing)
            self.assertIn('entry-count cap', str(support.thrown(lambda: w.scan_derived(max_entries=2))))

    def test_identity_loss_strict_errors_and_late_returns_remain_failures(self):
        for mode in ('root_missing', 'root_replaced', 'output_replaced', 'root_symlink',
                     'owner_lost', 'eacces', 'eio', 'deadline'):
            with self.subTest(mode=mode), DerivedWorld() as w:
                w.bind()
                original = FileNotFoundError(errno.ENOENT, 'pcm.tmp')
                before = []
                def child():
                    before.append((w.lstats, w.output_lstats))
                    if mode == 'root_missing': w.root_error = FileNotFoundError(errno.ENOENT, 'root')
                    elif mode == 'root_replaced': w.root_info.st_ino += 1
                    elif mode == 'output_replaced': w.output_info.st_ino += 1
                    elif mode == 'root_symlink': w.root_info.st_mode = stat.S_IFLNK
                    elif mode == 'owner_lost': w.run.owns_output = False
                    elif mode == 'eacces': raise PermissionError(errno.EACCES, 'stat denied')
                    elif mode == 'eio': raise OSError(errno.EIO, 'stat I/O')
                    elif mode == 'deadline': w.clock.now = w.run.phase_end
                    raise original
                w.set_children(child)
                error = support.thrown(w.scan_derived)
                if mode == 'root_missing': self.assertIs(error, w.root_error)
                elif mode in ('eacces', 'eio'): self.assertEqual(error.errno, errno.EACCES if mode == 'eacces' else errno.EIO)
                elif mode == 'deadline':
                    self.assertIsInstance(error, C.DeadlineFailure)
                    self.assertEqual((w.lstats, w.output_lstats), before[0])
                else: self.assertIsInstance(error, C.RunFailure)
                self.assertEqual(w.run.record['resource_scan']['last']['state'], 'failed')
                self.assertEqual(w.run.last_samples, [])


if __name__ == '__main__':
    unittest.main()
