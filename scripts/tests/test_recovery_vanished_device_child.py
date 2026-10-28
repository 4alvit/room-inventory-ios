"""Device-only child-stat ENOENT policy. Runtime filesystem/process/time are fake."""
from contextlib import contextmanager, ExitStack
import errno
import importlib.util
import os
from pathlib import Path
import resource
import signal
import socket
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / 'run-recovery-journey.py'
TARGETS = [(subprocess, ('Popen','run','call','check_call','check_output')),
           (os, ('system','kill','killpg','fork','posix_spawn','posix_spawnp','scandir')),
           (signal, ('signal','alarm','setitimer','pthread_sigmask','raise_signal')),
           (time, ('sleep',)), (socket, ('socket','create_connection','getaddrinfo')),
           (resource, ('getrlimit','setrlimit'))]
@contextmanager
def runtime_guard():
    denied=[]
    def stop(name):
        def failure(*args,**kwargs):
            denied.append(name)
            raise AssertionError('real runtime operation forbidden: '+name)
        return failure
    with ExitStack() as stack:
        for module,names in TARGETS:
            for name in names:
                if hasattr(module,name): stack.enter_context(patch.object(module,name,stop(module.__name__+'.'+name)))
        yield denied

with runtime_guard() as IMPORT_DENIALS:
    spec=importlib.util.spec_from_file_location('recovery_vanished_device_under_test',SCRIPT)
    C=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(C)
assert not IMPORT_DENIALS

class Clock:
    def __init__(self): self.now=100.0
    def __call__(self): return self.now

def info(*,size=3,blocks=1,mode=stat.S_IFREG,ino=22,dev=1):
    return SimpleNamespace(st_size=size,st_blocks=blocks,st_mode=mode,st_dev=dev,st_ino=ino)

def thrown(call):
    try: call()
    except BaseException as error: return error
    raise AssertionError('expected failure')

class World:
    def __init__(self):
        self.clock=Clock()
        grant=dict(worktree='/owned/repo',output_root='/owned/out',developer_dir='/owned/developer',
                   journey_run_id='11111111-1111-4111-8111-111111111111')
        self.run=C.RecoveryRun(grant,clock=self.clock,disk_usage=lambda _:SimpleNamespace(free=24*C.GIB))
        self.run.device_base=Path('/owned/devices')
        self.run.device_id='22222222-2222-4222-8222-222222222222'
        self.root=self.run.device_root=self.run.device_base/self.run.device_id
        self.root_info=info(mode=stat.S_IFDIR,ino=11)
        self.root_error=None;self.root_exists=True;self.before_lstat=None
        self.lstats=0;self.stats=[];self.opens=[];self.events=[];self.saved=[]
        self.entries={self.root:[]};self.open_errors={};self.close_error=None;self.iter_error=None
        self.service_calls=0;self.service_error=None
    def child(self,name,value):
        def observe(*,follow_symlinks):
            assert follow_symlinks is False
            self.stats.append(name);self.events.append(('stat',name))
            if callable(value):return value()
            if isinstance(value,BaseException):raise value
            return value
        return SimpleNamespace(path=str(self.root/name),stat=observe)
    def set_children(self,*values):
        self.entries[self.root]=[self.child(str(index),value) for index,value in enumerate(values)]
    def lstat(self,path):
        assert path==self.root, 'unexpected runtime lstat'
        self.lstats+=1;self.events.append(('root_lstat',self.lstats))
        if self.before_lstat:self.before_lstat()
        if self.root_error:raise self.root_error
        return self.root_info
    @contextmanager
    def scan(self,path):
        self.opens.append(path);self.events.append(('open',str(path)))
        if path in self.open_errors:raise self.open_errors[path]
        try:
            def iterator():
                yield from self.entries.get(path,[])
                if self.iter_error:raise self.iter_error
            yield iterator()
        finally:
            if self.close_error:raise self.close_error
    def bind(self):self.run.bind_device_resource_root()
    def service(self):
        self.service_calls+=1
        assert self.run._device_scan_context is self.run._device_scan_service
        if self.service_error:raise self.service_error
        self.run.tick()
    def active(self):self.run._device_scan_service=(self.root,self.service)
    def scan_device(self,**kwargs):return self.run.resource_size('device',self.root,C.DEVICE_CAP,**kwargs)
    def __enter__(self):
        self.stack=ExitStack()
        self.stack.enter_context(patch.object(Path,'lstat',lambda path:self.lstat(path)))
        self.stack.enter_context(patch.object(Path,'exists',lambda path:self.root_exists if path==self.root else False))
        self.stack.enter_context(patch.object(Path,'is_dir',return_value=True))
        self.stack.enter_context(patch.object(Path,'is_symlink',return_value=False))
        self.stack.enter_context(patch.object(Path,'stat',side_effect=AssertionError('unexpected runtime path.stat')))
        self.stack.enter_context(patch.object(Path,'open',side_effect=AssertionError('unexpected runtime path.open')))
        self.stack.enter_context(patch.object(C.os,'scandir',side_effect=self.scan))
        self.stack.enter_context(patch.object(C,'write_json',side_effect=lambda path,value:self.saved.append((path,value))))
        return self
    def __exit__(self,*args):return self.stack.__exit__(*args)

class VanishedDeviceTests(unittest.TestCase):
    def setUp(self):
        stack=ExitStack();self.addCleanup(stack.close)
        self.denied=stack.enter_context(runtime_guard())
        self.addCleanup(lambda:self.assertEqual(self.denied,[]))
        self.addCleanup(lambda:self.assertEqual(IMPORT_DENIALS,[]))
    def test_one_vanished_stat_counts_attempt_and_preserves_other_bytes(self):
        with World() as w:
            w.bind();w.set_children(info(size=5),FileNotFoundError(errno.ENOENT,'mock child'),info(size=7,blocks=2))
            result=w.scan_device()
            self.assertEqual(result,dict(logical_bytes=12,allocated_bytes=1536,entries=2,
                                         cap_metric='max_logical_allocated',attempted_entries=3,vanished_entries=1))
            self.assertEqual(w.stats,['0','1','2'])
    def test_generic_tree_still_propagates_exact_missing_stat(self):
        with World() as w:
            original=FileNotFoundError(errno.ENOENT,'generic child')
            w.set_children(original)
            self.assertIs(thrown(lambda:C.tree_size(w.root,C.DEVICE_CAP,w.run.tick)),original)
    def test_other_resource_category_does_not_enable_policy(self):
        with World() as w:
            w.bind();original=FileNotFoundError(errno.ENOENT,'other resource');w.set_children(original)
            self.assertIs(thrown(lambda:w.run.resource_size('output',w.root,C.OUTPUT_CAP)),original)
    def test_generic_optional_absent_root_preserved(self):
        with World() as w:
            w.root_exists=False
            self.assertEqual(C.tree_size(w.root,10,w.run.tick),dict(logical_bytes=0,allocated_bytes=0,entries=0,cap_metric='max_logical_allocated'))
            self.assertEqual(w.lstats,0)
    def test_all_non_enoent_stat_errors_and_control_propagate_identity(self):
        for original in (OSError(errno.EIO,'io'),PermissionError(errno.EACCES,'denied'),NotADirectoryError(errno.ENOTDIR,'type'),FileNotFoundError(errno.EIO,'wrong errno'),KeyboardInterrupt('control'),C.DeadlineFailure('clock')):
            with self.subTest(error=type(original).__name__,errno=getattr(original,'errno',None)),World() as w:
                w.bind();w.set_children(original)
                self.assertIs(thrown(w.scan_device),original)
    def test_callback_enoent_is_not_a_child_stat(self):
        with World() as w:
            w.bind();w.active();w.service_error=FileNotFoundError(errno.ENOENT,'callback')
            self.assertIs(thrown(w.scan_device),w.service_error)
            self.assertEqual(w.stats,[])
    def test_stat_enoent_then_deadline_is_not_swallowed(self):
        with World() as w:
            w.bind()
            def vanished():
                w.clock.now=w.run.phase_end
                raise FileNotFoundError(errno.ENOENT,'child')
            w.set_children(vanished)
            self.assertIsInstance(thrown(w.scan_device),C.DeadlineFailure)
            self.assertEqual(w.stats,['0'])
    def test_queued_scandir_enoent_and_iteration_close_enoent_stay_strict(self):
        for site in ('open','iteration','close'):
            with self.subTest(site=site),World() as w:
                w.bind();original=FileNotFoundError(errno.ENOENT,'strict boundary')
                if site=='open':
                    w.set_children(info(mode=stat.S_IFDIR));w.open_errors[w.root/'0']=original
                elif site=='iteration':w.iter_error=original
                else:w.close_error=original
                self.assertIs(thrown(w.scan_device),original)
    def test_mandatory_root_missing_before_scan_not_zero(self):
        with World() as w:
            w.bind();original=FileNotFoundError(errno.ENOENT,'root');w.root_error=original;w.root_exists=False
            self.assertIs(thrown(w.scan_device),original)
            self.assertEqual(w.opens,[])
    def test_observed_missing_root_between_checks_is_failure(self):
        with World() as w:
            w.bind();w.root_exists=False
            self.assertIsInstance(thrown(w.scan_device),C.ResourceAccountingFailure)
            self.assertEqual(w.opens,[])
    def test_root_missing_or_replaced_during_child_enoent_fails(self):
        for mode in ('missing','replaced','symlink','ownership'):
            with self.subTest(mode=mode),World() as w:
                w.bind();bound=w.run._owned_device_identity
                def changed():
                    if mode=='missing':w.root_error=FileNotFoundError(errno.ENOENT,'root')
                    elif mode=='replaced':w.root_info.st_ino+=1
                    elif mode=='symlink':w.root_info.st_mode=stat.S_IFLNK
                    else:w.run.device_id='stale'
                    raise FileNotFoundError(errno.ENOENT,'child')
                w.set_children(changed);error=thrown(w.scan_device)
                self.assertIs(error,w.root_error) if mode=='missing' else self.assertIsInstance(error,C.RunFailure)
                self.assertIs(w.run._owned_device_identity,bound)
    def test_root_replacement_at_scan_finish_fails(self):
        with World() as w:
            w.bind();bound=w.run._owned_device_identity
            def replace_after_valid_stat():
                w.root_info.st_ino+=1
                return info()
            w.set_children(replace_after_valid_stat)
            self.assertIsInstance(thrown(w.scan_device),C.ResourceAccountingFailure)
            self.assertIs(w.run._owned_device_identity,bound)
    def test_root_eio_and_eacces_during_enoent_validation_propagate(self):
        for original in (OSError(errno.EIO,'root io'),PermissionError(errno.EACCES,'root denied')):
            with self.subTest(error=type(original).__name__),World() as w:
                w.bind()
                def vanished():
                    w.root_error=original
                    raise FileNotFoundError(errno.ENOENT,'child')
                w.set_children(vanished)
                self.assertIs(thrown(w.scan_device),original)
    def test_identity_binds_once_and_never_reinitializes_after_failure(self):
        with World() as w:
            w.bind();bound=w.run._owned_device_identity;lstats=w.lstats
            w.root_info.st_ino+=1
            self.assertIsInstance(thrown(w.bind),C.ConfigurationFailure)
            self.assertEqual(w.lstats,lstats)
            self.assertIs(w.run._owned_device_identity,bound)
            self.assertIsInstance(thrown(w.scan_device),C.ResourceAccountingFailure)
            self.assertIs(w.run._owned_device_identity,bound)
    def test_unbound_identity_and_binding_override_are_rejected(self):
        with World() as w:
            self.assertIsInstance(thrown(w.scan_device),C.ConfigurationFailure)
            w.bind()
            self.assertIsInstance(thrown(lambda:w.scan_device(vanished_child_check=lambda:None)),C.ConfigurationFailure)
    def test_invalid_creation_identity_and_root_kind_are_rejected(self):
        for field,value in (('st_ino',None),('st_dev',-1),('st_ino',True),('st_mode',stat.S_IFLNK),('st_mode',stat.S_IFREG)):
            with self.subTest(field=field,value=value),World() as w:
                setattr(w.root_info,field,value)
                self.assertIsInstance(thrown(w.bind),C.ResourceAccountingFailure)
                self.assertIsNone(w.run._owned_device_identity)
    def test_attempt_cap_enforced_even_if_every_child_vanishes(self):
        with World() as w:
            w.bind();w.set_children(*[FileNotFoundError(errno.ENOENT,'child') for _ in range(3)])
            error=thrown(lambda:w.scan_device(max_entries=2))
            self.assertIsInstance(error,C.RunFailure)
            self.assertIn('entry-count cap',str(error))
            self.assertEqual(w.stats,['0','1'])
    def test_observed_bytes_hardlinks_and_cap_are_not_subtracted(self):
        with World() as w:
            w.bind();shared=info(size=6,blocks=1,ino=9)
            w.set_children(shared,FileNotFoundError(errno.ENOENT,'gone'),shared)
            result=w.scan_device()
            self.assertEqual((result['logical_bytes'],result['allocated_bytes']),(12,1024))
            error=thrown(lambda:w.run.resource_size('device',w.root,1024))
            self.assertIsInstance(error,C.RunFailure)
            self.assertEqual(w.run.record['resource_cap_crossing']['entries'],2)
    def test_invalid_blocks_are_not_reclassified_as_disappearance(self):
        with World() as w:
            w.bind();child=info();del child.st_blocks;w.set_children(child)
            self.assertIsInstance(thrown(w.scan_device),C.ResourceAccountingFailure)
    def test_observed_symlink_is_counted_without_queued_target_traversal(self):
        with World() as w:
            w.bind();w.set_children(info(mode=stat.S_IFLNK,size=15))
            result=w.scan_device()
            self.assertEqual(result['logical_bytes'],15)
            self.assertEqual(w.opens,[w.root])
            # This does not simulate or claim protection from a later path race.
    def test_active_scan_and_fresh_hookless_guard_both_validate(self):
        with World() as w:
            w.bind();w.set_children(FileNotFoundError(errno.ENOENT,'live child'),info())
            w.active();active=w.scan_device();self.assertGreater(w.service_calls,0)
            self.assertEqual(active['vanished_entries'],1)
            w.run._device_scan_service=None;before=w.service_calls
            w.run.guard(force=True)
            self.assertEqual(w.service_calls,before)
            self.assertEqual(len(w.run.last_samples),1)
            self.assertEqual(w.run.last_samples[0]['device']['vanished_entries'],1)
            self.assertEqual(w.run.last_samples[0]['device']['attempted_entries'],2)
    def test_fresh_guard_failure_does_not_publish_partial_sample(self):
        with World() as w:
            w.bind();w.root_info.st_ino+=1
            self.assertIsInstance(thrown(lambda:w.run.guard(force=True)),C.ResourceAccountingFailure)
            self.assertEqual(w.run.last_samples,[])
            self.assertEqual(w.saved,[])
    def test_handoff_stays_incomplete_and_never_publishes_partial_sample(self):
        with World() as w:
            w.bind();w.set_children(info());w.active();sentinel=C._DeviceScanDeferred()
            w.service_error=sentinel
            self.assertIs(thrown(lambda:w.run.guard(force=True)),sentinel)
            self.assertEqual(w.run.last_samples,[])
            self.assertEqual(w.run.record['resource_scan']['last']['state'],'failed')
            self.assertIsNone(w.run._device_scan_context)
    def test_handoff_after_vanished_child_does_not_publish_counts_as_complete(self):
        with World() as w:
            w.bind();w.set_children(FileNotFoundError(errno.ENOENT,'child'),info())
            sentinel=C._DeviceScanDeferred();after_missing_ticks=[]
            def service():
                w.run.tick()
                if w.stats==['0']:
                    after_missing_ticks.append(1)
                    if len(after_missing_ticks)==3:raise sentinel
            w.run._device_scan_service=(w.root,service)
            self.assertIs(thrown(lambda:w.run.guard(force=True)),sentinel)
            self.assertEqual(w.stats,['0'])
            self.assertEqual(w.run.last_samples,[])
            self.assertEqual(w.saved,[])
            self.assertEqual(w.run.record['resource_scan']['last']['state'],'failed')
            self.assertIsNone(w.run._device_scan_context)
    def test_late_root_validation_cannot_finish_a_scan(self):
        with World() as w:
            w.bind()
            w.before_lstat=lambda:setattr(w.clock,'now',w.run.phase_end)
            self.assertIsInstance(thrown(w.scan_device),C.DeadlineFailure)
    def test_late_child_stat_does_not_query_root_again_or_publish_sample(self):
        with World() as w:
            w.bind();before=[]
            def late():
                before.append(w.lstats)
                w.clock.now=w.run.phase_end
                raise FileNotFoundError(errno.ENOENT,'late child')
            w.set_children(late)
            self.assertIsInstance(thrown(lambda:w.run.guard(force=True)),C.DeadlineFailure)
            self.assertEqual(w.lstats,before[0])
            self.assertEqual(w.run.last_samples,[])
            self.assertEqual(w.saved,[])
    def test_late_iterator_close_does_not_query_root_again_or_publish_sample(self):
        with World() as w:
            w.bind();w.set_children(info());before=[]
            original=w.scan
            @contextmanager
            def close_late(path):
                with original(path) as iterator:yield iterator
                if path==w.root:
                    before.append(w.lstats)
                    w.clock.now=w.run.phase_end
            w.stack.enter_context(patch.object(C.os,'scandir',side_effect=close_late))
            self.assertIsInstance(thrown(lambda:w.run.guard(force=True)),C.DeadlineFailure)
            self.assertEqual(w.lstats,before[0])
            self.assertEqual(w.run.last_samples,[])
            self.assertEqual(w.saved,[])
    def test_repeated_scans_do_not_rebind_current_root(self):
        with World() as w:
            w.bind();w.scan_device();bound=w.run._owned_device_identity
            w.root_info.st_dev+=1
            self.assertIsInstance(thrown(w.scan_device),C.ResourceAccountingFailure)
            self.assertIs(w.run._owned_device_identity,bound)

if __name__=='__main__':unittest.main(verbosity=2)
