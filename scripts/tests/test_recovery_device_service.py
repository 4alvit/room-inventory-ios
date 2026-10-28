"""Tiny deterministic device-service tests: all runtime I/O is injected.
No native grants, real children, signals, timers, sleep, sockets or rlimit calls.
"""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

# Every global replacement is scoped: import guard closes before discovery
# proceeds, and each test uses its own ExitStack restored by addCleanup.
_DENY_TARGETS = [(subprocess, ('Popen', 'run', 'call', 'check_call', 'check_output')),
                 (os, ('system', 'kill', 'killpg', 'fork', 'posix_spawn', 'posix_spawnp')),
                 (signal, ('signal', 'alarm', 'setitimer', 'pthread_sigmask', 'raise_signal')),
                 (time, ('sleep',)), (socket, ('socket', 'create_connection', 'getaddrinfo')),
                 (resource, ('setrlimit', 'getrlimit'))]

@contextlib.contextmanager
def runtime_guard():
    denials = []
    def denied(name):
        def forbidden(*args, **kwargs):
            denials.append(name)
            raise AssertionError('REAL OPERATION FORBIDDEN: ' + name)
        return forbidden
    with contextlib.ExitStack() as stack:
        for module, names in _DENY_TARGETS:
            for name in names:
                if hasattr(module, name):
                    stack.enter_context(patch.object(module, name, denied(module.__name__ + '.' + name)))
        yield denials

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Matches the repository scripts/tests relative-source convention.
with runtime_guard() as _IMPORT_DENIALS:
    C = load(Path(__file__).resolve().parents[1] / 'run-recovery-journey.py',
             'recovery_device_service_under_test')
assert not _IMPORT_DENIALS, 'controller import attempted a forbidden runtime operation'

class Clock:
    now = 100.0
    def __call__(self):
        return self.now

class World:
    def __init__(self, module=C, *, count=200, actual_guard=False):
        self.c, self.count, self.actual_guard = module, count, actual_guard
        self.clock = Clock()
        self.events, self.walked, self.barrier_walked = [], 0, 0
        self.scanning, self.cleaned, self.complete_samples = False, False, []
        self.read_action, self.poll_action, self.stat_action = None, None, None
        self.write_action, self.close_action, self.callback_action = None, None, None
        self.before_scan, self.barrier_action, self.cleanup_action = None, None, None
        self.max_entries, self.cap, self.samples = 100000, module.DEVICE_CAP, []
        self.current = None
        self.cleanup = dict(success=True, group_state='absent', leader_reaped=True,
                            returncode=0, errors=[], signals=[], budget_exhausted=False)
        grant = dict(worktree='/owned/repo', output_root='/owned/out', developer_dir='/owned/developer',
                     journey_run_id='11111111-1111-4111-8111-111111111111')
        self.run = module.RecoveryRun(grant, clock=self.clock, disk_usage=self.disk)
        self.run.device_base = Path('/owned/devices')
        self.run.device_id = '22222222-2222-4222-8222-222222222222'
        self.root = self.run.device_root = self.run.device_base / self.run.device_id
        self.run.owns_output = True
        self.run.flush = Mock()
        self.process = Mock(pid=43210)
        self.process.stdout.fileno.return_value = 111
        self.process.stderr.fileno.return_value = 112
        self.process.poll.side_effect = self.poll
        self.process.wait.return_value = 0
        self.selector, self.registered, self.logs = Mock(), {}, []
        self.selector.register.side_effect = self.register
        self.selector.unregister.side_effect = lambda pipe: self.registered.pop(pipe.fileno())
        self.selector.get_map.side_effect = lambda: self.registered
        self.selector.select.side_effect = self.select
        self.run.guard = self.guard if not actual_guard else lambda force=False: module.RecoveryRun.guard(self.run, force=force)
    def disk(self, path):
        self.events.append(('disk', self.walked, str(path)))
        return SimpleNamespace(free=24*self.c.GIB)
    def register(self, pipe, event, index):
        self.registered[pipe.fileno()] = SimpleNamespace(fileobj=pipe, data=index)
    def select(self, timeout):
        self.events.append(('select', self.walked, timeout))
        return [(v, 1) for v in reversed(list(self.registered.values()))]
    def poll(self):
        self.events.append(('poll', self.walked))
        return self.poll_action() if self.poll_action else 0
    def read(self, fd, amount):
        self.events.append(('read', self.walked, fd, amount))
        return self.read_action(fd) if self.read_action else b''
    def log(self, path, mode='r', *args, **kwargs):
        assert mode == 'xb', 'unexpected file open'
        index = len(self.logs)
        stream = Mock()
        stream.write.side_effect = lambda data: self.write(index, data)
        self.logs.append(stream)
        return stream
    def write(self, index, data):
        self.events.append(('write', self.walked, index, len(data)))
        return self.write_action(index, data) if self.write_action else len(data)
    def spawn(self, *args, **kwargs):
        self.events.append(('spawn',))
        if self.actual_guard:
            self.clock.now += 2.1  # Trigger the existing two-second scan cadence.
        return self.process
    def stop(self, process, end, *, state, clock):
        self.events.append(('cleanup', self.walked))
        assert getattr(self.run, '_derived_scan_service', None) is None
        assert getattr(self.run, '_device_scan_service', None) is None
        assert getattr(self.run, '_device_scan_context', None) is None
        self.cleaned = True
        if self.cleanup_action:
            self.cleanup_action()
        state.update(returncode=0, group_state=self.cleanup['group_state'], leader_reaped=True)
        if not self.cleanup['success']:
            state['observation_errors'] = [{'operation':'group_probe','errno':1}]
        return self.cleanup
    def guard(self, force=False):
        self.run.tick()
        if not self.run.groups or self.run.cleanup_mode:
            return
        if force:
            self.events.append(('barrier', self.walked))
            assert self.cleaned
            assert self.run._derived_scan_service is None
            assert getattr(self.run, '_device_scan_service', None) is None
            if self.barrier_action:
                self.barrier_action()
        elif self.before_scan:
            self.before_scan()
        result = self.run.resource_size('device', self.run.device_root, self.cap, max_entries=self.max_entries)
        self.complete_samples.append(result)
    def callback(self):
        self.events.append(('callback', self.walked))
        assert not self.scanning
        if self.callback_action:
            self.callback_action()
    @contextlib.contextmanager
    def scan(self, root):
        is_device = root == self.root
        was_scanning = self.scanning
        self.scanning = is_device
        if is_device:
            self.events.append(('scan_start', self.walked, self.cleaned))
        def entries():
            for i in range(self.count if is_device else 0):
                def inspect(*, follow_symlinks, number=i):
                    assert follow_symlinks is False
                    info = SimpleNamespace(st_size=1, st_blocks=1, st_mode=stat.S_IFREG)
                    active = bool(self.run.groups) and not self.cleaned
                    if active:
                        self.walked += 1
                    elif self.cleaned:
                        self.barrier_walked += 1
                    self.events.append(('stat', self.walked, self.cleaned))
                    if self.stat_action:
                        return self.stat_action(info, active)
                    return info
                yield SimpleNamespace(path=str(root / str(i)), stat=inspect)
        try:
            yield entries()
        finally:
            self.scanning = was_scanning
            if is_device:
                self.events.append(('scan_close', self.walked, self.cleaned))
                if self.close_action:
                    self.close_action()
    def __enter__(self):
        self.stack = contextlib.ExitStack()
        for target, name, replacement in [
            (self.c.subprocess, 'Popen', Mock(side_effect=self.spawn)),
            (self.c.selectors, 'DefaultSelector', Mock(return_value=self.selector)),
            (self.c.os, 'set_blocking', Mock()), (self.c.os, 'read', Mock(side_effect=self.read)),
            (self.c.os, 'scandir', Mock(side_effect=self.scan)),
            (self.c, 'kill_owned', Mock(side_effect=self.stop)),
            (self.c, 'write_json', Mock(side_effect=lambda p,v: self.samples.append((str(p), json.loads(json.dumps(v)))))),
            (Path, 'open', lambda path, *a, **k: self.log(path, *a, **k)), (Path, 'mkdir', Mock()), (Path, 'exists', Mock(return_value=True)),
            (Path, 'is_dir', Mock(return_value=True)), (Path, 'is_symlink', Mock(return_value=False)),
            (Path, 'lstat', Mock(return_value=SimpleNamespace(st_size=0,st_blocks=0,st_mode=stat.S_IFDIR)))]:
            self.stack.enter_context(patch.object(target, name, replacement))
        return self
    def __exit__(self, *args):
        return self.stack.__exit__(*args)
    def invoke(self):
        return self.run.command(['fake-child'], 'fake-install', cap=90, on_poll=self.callback)
    @property
    def record(self):
        return self.run.record['commands'][0]

def failure(call):
    try:
        call()
    except BaseException as error:
        return error
    raise AssertionError('expected failure')

class DeviceTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.denials = stack.enter_context(runtime_guard())
        # Cleanup assertions run before restoration; unittest still runs the
        # registered stack.close even if an assertion or test body fails.
        self.addCleanup(lambda: self.assertEqual(self.denials, []))
        self.addCleanup(lambda: self.assertEqual(_IMPORT_DENIALS, []))
    def assert_finished(self, w):
        self.assertTrue(w.cleaned)
        self.assertEqual(sum(e[0]=='cleanup' for e in w.events), 1)
        self.assertIsNone(w.run._derived_scan_service)
        self.assertIsNone(getattr(w.run, '_device_scan_service', None))
        self.assertIsNone(getattr(w.run, '_device_scan_context', None))
    def test_timely_handoff_and_fresh_complete_barrier(self):
        with World() as w:
            self.assertEqual(w.invoke(), b'')
            self.assertLess(w.walked, 200)
            self.assertEqual(w.barrier_walked, 200)
            self.assertEqual(len(w.complete_samples), 1)
            self.assertEqual(w.complete_samples[0]['entries'], 200)
            self.assertEqual(w.record['device_scan_handoff']['state'], 'incomplete')
            self.assertEqual(w.record['post_command_accounting']['status'], 'COMPLETED')
            self.assertEqual(w.record['derived_service']['quanta_started'], 0)
            order=[e[0] for e in w.events]
            self.assertLess(order.index('scan_close'), order.index('callback'))
            self.assertLess(order.index('callback'), order.index('cleanup'))
            self.assertLess(order.index('cleanup'), order.index('barrier'))
            self.assert_finished(w)
    def test_actual_guard_never_publishes_partial_device_sample(self):
        with World(actual_guard=True) as w:
            w.invoke()
            self.assertEqual(len(w.run.last_samples), 2)  # Initial + fresh terminal only.
            self.assertTrue(all(s['device']['entries']==200 for s in w.run.last_samples))
            self.assertLess(w.walked, 200)
            self.assertEqual(w.barrier_walked, 200)
    def test_fair_two_pipe_reads_bounded_and_dd_counters_unmodified(self):
        with World() as w:
            w.read_action=lambda fd: b'x' if w.walked < 180 else b''
            self.assertEqual(w.invoke(), b'xx')
            quanta=[e[1] for e in w.events if e[0]=='select' and e[2]==0]
            self.assertEqual(quanta, [62,126,190])
            self.assertTrue(all(e[3]==65536 for e in w.events if e[0]=='read'))
            for point in quanta:
                self.assertEqual({e[2] for e in w.events if e[0]=='read' and e[1]==point}, {111,112})
            self.assertEqual(w.record['stdout_sha256'], hashlib.sha256(b'xx').hexdigest())
            self.assertEqual(w.record['derived_service']['quanta_started'], 0)
            self.assert_finished(w)
    def test_one_eof_with_exit_does_not_handoff(self):
        with World(count=130) as w:
            w.read_action=lambda fd: b'' if fd==111 or w.walked>=130 else b'held'
            w.invoke()
            self.assertEqual(w.walked,130)
            self.assertNotIn('device_scan_handoff',w.record)
    def test_eof_without_exit_does_not_handoff(self):
        with World(count=130) as w:
            w.poll_action=lambda: None if w.scanning else 0
            w.invoke()
            self.assertEqual(w.walked,130)
            self.assertNotIn('device_scan_handoff',w.record)
    def test_disallowed_exit_with_eof_fails_and_cleans(self):
        with World() as w:
            w.poll_action=lambda: 3
            error=failure(w.invoke)
            self.assertIsInstance(error,C.RunFailure)
            self.assertIn('Command failed',str(error))
            self.assertNotIn('device_scan_handoff',w.record)
            self.assertIsNone(w.record['post_command_accounting'])
            self.assert_finished(w)
    def test_completion_exactly_deadline_fails(self):
        with World() as w:
            def late():
                w.clock.now=w.run.command_deadline
                return 0
            w.poll_action=late
            self.assertIsInstance(failure(w.invoke),C.DeadlineFailure)
            self.assertNotIn('device_scan_handoff',w.record)
            self.assert_finished(w)
    def test_context_close_error_preserved_not_handoff(self):
        with World() as w:
            original=OSError('fake-close-error')
            w.close_action=lambda: (_ for _ in ()).throw(original)
            self.assertIs(failure(w.invoke), original)
            self.assertNotIn('device_scan_handoff',w.record)
            self.assert_finished(w)
    def test_context_close_late_uses_original_deadline(self):
        with World() as w:
            w.close_action=lambda: setattr(w.clock,'now',w.run.command_deadline)
            self.assertIsInstance(failure(w.invoke),C.DeadlineFailure)
            self.assertNotIn('device_scan_handoff',w.record)
            self.assert_finished(w)
    def test_stale_owner_root_and_reentrant_context_rejected(self):
        for mode in ('root','record','process','context','state'):
            with self.subTest(mode=mode), World() as w:
                def stale():
                    if mode=='root': w.run.device_root=Path(str(w.root))
                    elif mode=='record': w.run.groups[-1]['record']={}
                    elif mode=='process': w.run.groups[-1]['process']=object()
                    elif mode=='context': w.run._device_scan_context=object()
                    else: w.run.groups[-1]['state']['observation_errors']=[{'errno':1}]
                w.before_scan=stale
                self.assertIsInstance(failure(w.invoke),C.ConfigurationFailure)
                self.assertNotIn('device_scan_handoff',w.record)
                self.assert_finished(w)
    def test_stat_cap_entry_and_missing_allocation_errors_preserved(self):
        for mode in ('stat','cap','entries','allocation'):
            with self.subTest(mode=mode), World() as w:
                original=OSError('fake-stat-error')
                if mode=='stat': w.stat_action=lambda info,active: (_ for _ in ()).throw(original)
                elif mode=='cap': w.cap=512
                elif mode=='entries': w.max_entries=1
                else:
                    def unsupported(info, active):
                        del info.st_blocks
                        return info
                    w.stat_action=unsupported
                error=failure(w.invoke)
                self.assertIs(error,original) if mode=='stat' else self.assertIsInstance(error,C.RunFailure)
                self.assertNotIn('device_scan_handoff',w.record)
                self.assertEqual(w.barrier_walked,0)
                self.assert_finished(w)
    def test_callback_runs_outside_walker_and_its_primary_survives(self):
        with World() as w:
            original=C.RunFailure('bridge-error')
            w.callback_action=lambda: (_ for _ in ()).throw(original)
            self.assertIs(failure(w.invoke),original)
            self.assertIsNone(w.record['post_command_accounting'])
            self.assert_finished(w)
    def test_callback_late_and_changed_owner_reject_handoff_success(self):
        for mode in ('late','owner'):
            with self.subTest(mode=mode), World() as w:
                w.callback_action=(lambda: setattr(w.clock,'now',w.run.command_deadline)) if mode=='late' else (lambda: setattr(w.run,'device_id','stale'))
                self.assertIsInstance(failure(w.invoke),C.DeadlineFailure if mode=='late' else C.ConfigurationFailure)
                self.assertIsNone(w.record['post_command_accounting'])
                self.assert_finished(w)
    def test_cleanup_unknown_or_late_blocks_terminal_success(self):
        for mode in ('unknown','late'):
            with self.subTest(mode=mode), World() as w:
                if mode=='unknown': w.cleanup.update(success=False,group_state='unknown',errors=[{'errno':1}])
                else: w.cleanup_action=lambda: setattr(w.clock,'now',w.record['command_end_monotonic'])
                self.assertIsInstance(failure(w.invoke),C.RunFailure)
                self.assertIsNone(w.record['post_command_accounting'])
                self.assert_finished(w)
    def test_full_barrier_cap_and_deadline_still_fail(self):
        for mode in ('cap','deadline'):
            with self.subTest(mode=mode), World() as w:
                original=C.RunFailure('terminal-cap')
                if mode=='cap':
                    def crossing(info, active):
                        if w.cleaned: info.st_size=C.DEVICE_CAP
                        return info
                    w.stat_action=crossing
                else:
                    w.barrier_action=lambda: setattr(w.clock,'now',w.run.phase_end)
                self.assertIsInstance(failure(w.invoke),C.RunFailure)
                self.assertEqual(w.record['post_command_accounting']['status'],'FAILED')
                self.assert_finished(w)
    def test_stale_hook_after_return_rejected(self):
        with World() as w:
            captured=[]
            w.before_scan=lambda: captured.append(w.run._device_scan_service[1])
            w.invoke()
            self.assertIsInstance(failure(captured[0]),C.ConfigurationFailure)
    def test_would_block_is_not_eof_and_partial_write_is_failure(self):
        for mode in ('block','write'):
            with self.subTest(mode=mode), World(count=130) as w:
                if mode=='block':
                    def data(fd):
                        if w.walked<130: raise BlockingIOError()
                        return b''
                    w.read_action=data
                    w.invoke()
                    self.assertEqual(w.walked,130)
                    self.assertNotIn('device_scan_handoff',w.record)
                else:
                    w.read_action=lambda fd:b'abc'
                    w.write_action=lambda index,data:len(data)-1
                    self.assertIsInstance(failure(w.invoke),C.RunFailure)
                    self.assertIsNone(w.record['post_command_accounting'])
                self.assert_finished(w)
    def test_handoff_metadata_interrupt_remains_primary(self):
        with World() as w:
            original=KeyboardInterrupt('mock-control')
            observe=w.run.observe_runtime
            def diagnostic(event, *args, **kwargs):
                if event=='scan_end' and kwargs.get('failed') and not w.cleaned:
                    raise original
                return observe(event,*args,**kwargs)
            w.run.observe_runtime=diagnostic
            self.assertIs(failure(w.invoke),original)
            self.assertNotIn('device_scan_handoff',w.record)
            self.assert_finished(w)
    def test_byte_and_log_caps_unchanged(self):
        for mode in ('stream','logs'):
            with self.subTest(mode=mode), World() as w:
                if mode=='stream':
                    w.read_action=lambda fd: type('OversizeReturnedChunk',(),{'__len__':lambda self:16*C.MIB+1})()
                else:
                    w.read_action=lambda fd:b'abc'
                    real_tree=C.tree_size
                    def capped(root,cap,tick,**kwargs):
                        if root==w.run.output/'logs':
                            self.assertEqual(cap,C.LOG_CAP)
                            self.assertEqual(kwargs['max_entries'],256)
                            self.assertEqual(tick,w.run.tick)
                            raise C.RunFailure('mock-log-cap')
                        return real_tree(root,cap,tick,**kwargs)
                    w.stack.enter_context(patch.object(C,'tree_size',side_effect=capped))
                self.assertIsInstance(failure(w.invoke),C.RunFailure)
                self.assertNotIn('device_scan_handoff',w.record)
                self.assertIsNone(w.record['post_command_accounting'])
                self.assert_finished(w)
    def test_cleanup_mode_has_no_service_or_full_barrier(self):
        with World() as w:
            w.run.cleanup_mode=True
            w.invoke()
            self.assertEqual(w.walked,0)
            self.assertEqual(w.barrier_walked,0)
            self.assertNotIn('device_scan_handoff',w.record)
            self.assertIsNone(w.record['post_command_accounting'])
            self.assert_finished(w)
    def test_wrong_sentinel_cannot_authorize_handoff(self):
        with World() as w:
            w.before_scan=lambda: (_ for _ in ()).throw(C._DeviceScanDeferred())
            self.assertIsInstance(failure(w.invoke),C.ConfigurationFailure)
            self.assertNotIn('device_scan_handoff',w.record)
            self.assert_finished(w)
    def test_no_denied_operations(self):
        self.assertEqual(self.denials,[])

if __name__=='__main__':
    unittest.main(verbosity=2)
