"""Bounded diagnostic contracts; no Simulator, Xcode or network execution."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rc_install_diagnostic as D
import rc_acceptance_process as P

ID='D7CFD74C-28E6-44F0-BAED-4A4E0776E79F'

def environment(tmp='/tmp'):
    return dict(GITHUB_ACTIONS='true',GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REPOSITORY=D.R.REPO,
        GITHUB_REF='refs/heads/'+D.BRANCH,GITHUB_WORKFLOW_REF=D.R.REPO+'/.github/workflows/rc-acceptance.yml@refs/heads/'+D.BRANCH,
        GITHUB_SHA='a'*40,RUNNER_ARCH='ARM64',RUNNER_TEMP=tmp,DEVELOPER_DIR='/Applications/Xcode_27.1.app/Contents/Developer')


class Admission(unittest.TestCase):
    def test_changed_rc_rejected_before_output_or_process(self):
        from types import SimpleNamespace
        wrong=copy.deepcopy(D.EXPECTED);wrong['source_sha']='b'*40
        with patch.dict(os.environ,environment(),clear=True),patch.object(D,'DiagnosticRun',side_effect=AssertionError('must reject first')):
            with self.assertRaisesRegex(D.R.AcceptanceError,'RC changed'):
                D.execute(SimpleNamespace(expected=wrong))
    def test_exact_branch_only_and_main_not_diagnostic(self):
        D.validate_host(environment())
        for key,bad in [('GITHUB_REF','refs/heads/main'),('GITHUB_EVENT_NAME','push'),
                        ('GITHUB_REPOSITORY','foreign/repo'),('GITHUB_WORKFLOW_REF','foreign'),
                        ('GITHUB_SHA','not-a-sha'),('RUNNER_ARCH','X64'),('DEVELOPER_DIR','/other')]:
            with self.subTest(key=key):
                env=environment();env[key]=bad
                with self.assertRaises(D.R.AcceptanceError):D.validate_host(env)
    def test_production_execute_has_not_been_replaced(self):
        from types import SimpleNamespace
        with patch.dict(os.environ,environment(),clear=True), patch.object(D.R,'Run',side_effect=AssertionError('must reject first')):
            with self.assertRaisesRegex(D.R.AcceptanceError,'trusted main'):
                D.R.execute(SimpleNamespace(expected=D.EXPECTED))
    def test_workflow_has_one_diagnostic_and_original_main_matrix(self):
        text=(Path(__file__).resolve().parents[2]/'.github/workflows/rc-acceptance.yml').read_text()
        before,after=text.split('  install-diagnostic:',1)
        self.assertIn("github.ref == 'refs/heads/main'",before)
        self.assertIn('device: [iphone, ipad]',before)
        self.assertIn("github.ref == 'refs/heads/"+D.BRANCH+"'",after)
        self.assertNotIn('matrix:',after);self.assertNotIn('test-without-building',after)
        self.assertEqual(after.count('scripts/rc_install_diagnostic.py run'),1)


class Telemetry(unittest.TestCase):
    def test_saturated_trace_keeps_exact_largest_gap_pair(self):
        t=D.Trace()
        for _ in range(2050):t('loop')
        previous=t.last['monotonic_ns']
        with patch.object(D,'stamp',return_value=dict(monotonic_ns=previous+77_000_000_000,cpu_ns=1,utc_ns=1)):
            t('cleanup_begin')
        self.assertEqual(t.max_gap_ns,77_000_000_000)
        self.assertEqual(t.max_gap_pair['previous']['phase'],'loop')
        self.assertEqual(t.max_gap_pair['next']['phase'],'cleanup_begin')
    def test_capped_stream_sink_retains_prefix_without_persisting_raw(self):
        streams={};record={}
        def receive(out,err):streams.update(out=out,err=err)
        with self.assertRaisesRegex(P.CaptureFailure,'stream cap'):
            P.bounded_capture([sys.executable,'-c','print("x"*1000)'],timeout=3,limit=16,receipt=record,stream_sink=receive)
        self.assertEqual(streams['out'],b'x'*16);self.assertEqual(record['stdout_bytes'],16)
        self.assertTrue(record['cleanup']['leader_reaped'])
    def test_regressing_diagnostic_clock_is_incomplete_not_success(self):
        t=D.Trace()
        with patch.object(D,'stamp',side_effect=[dict(monotonic_ns=100),dict(monotonic_ns=90)]):
            t('loop');t('cleanup_end')
        self.assertTrue(t.result()['incomplete'])
    def test_terminal_retained_after_saturation(self):
        t=D.Trace()
        for _ in range(2200):t('loop')
        t('cleanup_end');t('persist_end')
        r=t.result();self.assertEqual(len(r['events']),2048)
        self.assertTrue(r['incomplete']);self.assertIn('cleanup_end',r['terminal'])
        self.assertEqual(r['last']['phase'],'persist_end')
    def test_no_diagnostic_clock_when_disabled_and_error_still_preserved(self):
        receipt={}
        with patch.object(P.time,'monotonic_ns',side_effect=AssertionError('diagnostic clock forbidden')):
            with self.assertRaises(P.CaptureFailure):
                P.bounded_capture([sys.executable,'-c','raise SystemExit(2)'],timeout=3,limit=1024,receipt=receipt)
        self.assertTrue(receipt['cleanup']['success']);self.assertEqual(receipt['returncode'],2)
    def test_enabled_hooks_keep_primary_and_terminal(self):
        receipt={};t=D.Trace()
        with self.assertRaises(P.CaptureFailure):
            P.bounded_capture([sys.executable,'-c','raise SystemExit(3)'],timeout=3,limit=1024,receipt=receipt,phase_sink=t)
        self.assertEqual(receipt['returncode'],3);self.assertTrue(receipt['cleanup']['success'])
        self.assertIn('cleanup_end',t.terminal);self.assertIn('persist_end',t.terminal)
    def test_callback_exception_cannot_replace_original_failure(self):
        def fail(*a,**k):raise ValueError('callback')
        with self.assertRaisesRegex(P.CaptureFailure,'exited 4'):
            P.bounded_capture([sys.executable,'-c','raise SystemExit(4)'],timeout=3,limit=1024,phase_sink=fail)
    def test_global_reserve_keeps_terminal_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=D.DiagnosticRun(tmp,Path(tmp)/'out');r.diagnostic_bytes=D.TELEMETRY_CAP-512*1024-D.R.MIB
            self.assertFalse(r.keep('overflow.json',{'x':'x'}))
            self.assertTrue(r.keep('terminal-summary.json',{'terminal':True},final=True))
            self.assertEqual(r.omissions[0]['reason'],'retention_cap')


class Sanitizers(unittest.TestCase):
    def test_registry_cryptex_state_and_simlaunchhost_arch_variant(self):
        row=D.registry(json.dumps({ID:{'state':'Unusable - Cryptex Mount Preferred','build':'24A434'}}).encode())['rows'][0]
        self.assertEqual(row['fields']['state'],'Unusable - Cryptex Mount Preferred')
        raw=b'11 1 11 S 2.0 100 00:02 /usr/bin/SimLaunchHost.arm64\n'
        self.assertEqual(D.processes(raw,set())['rows'][0]['source'],'SimLaunchHost.arm64')
        self.assertIn('SimLaunchHost.arm64',D.LOG_PREDICATE)
    def test_registry_retains_correlated_identity_without_paths_or_unknown_values(self):
        raw=json.dumps({ID:{'build':'24A434','state':'Ready','mountPath':'/private/secret/'+ID,
                           'untrusted':'secret@example.test','identifier':'secret@example.test'}}).encode()
        r=D.registry(raw);text=json.dumps(r)
        self.assertIn(ID,text);self.assertIn('24A434',text)
        self.assertNotIn('/private',text);self.assertNotIn('secret',text)
    def test_mount_filter_keeps_device_but_not_mount_path(self):
        r=D.mounts(b'/dev/disk7s1 on /private/secret/CoreSimulator/cryptex (apfs, read-only)\n/dev/disk1 on /Users/private (apfs)\n')
        self.assertEqual(len(r['rows']),1);self.assertEqual(r['rows'][0]['mount_devices'],['disk7s1'])
        self.assertNotIn('/private',json.dumps(r))
    def test_ps_omits_foreign_process_and_arguments(self):
        raw=b'11 1 11 S 2.0 100 00:02 /usr/bin/simdiskimaged\n12 1 12 S 0.0 10 00:03 /private/secret\n13 1 13 S 0.0 10 00:03 /private/owned\n'
        rows=D.processes(raw,{13})['rows'];self.assertEqual([x['pid'] for x in rows],[11,13])
        self.assertEqual(rows[1]['source'],'owned');self.assertNotIn('/private',json.dumps(rows))
    def test_logs_fixed_categories_uuids_build_mount_and_error_only(self):
        raw=json.dumps([dict(processImagePath='/private/simdiskimaged',timestamp='2026-11-06T15:00:00+00:00',
            eventMessage=f'unmount failed {ID} 24A434 /dev/disk7s1 NSPOSIXErrorDomain errno=1 secret@example.test /Users/private')]).encode()
        rows=D.native_logs(raw,1793977200,1793977210)['rows'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['codes'],[1]);self.assertIn(ID,rows[0]['uuids'])
        self.assertNotIn('secret',json.dumps(rows));self.assertNotIn('/Users',json.dumps(rows))
    def test_log_caps_partial_and_invalid_json_fail_closed(self):
        event=dict(processImagePath='/usr/bin/installd',timestamp='2026-11-06T15:00:00+00:00',eventMessage='error')
        r=D.native_logs(json.dumps([event]*129).encode(),1793977200,1793977210)
        self.assertEqual(len(r['rows']),128);self.assertEqual(r['omitted'],1);self.assertTrue(r['incomplete'])
        for raw in [b'[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]',b'{"x":NaN}',b'{"x":1,"x":2}']:
            with self.assertRaises(Exception):D.checked_json(raw)
    def test_runtime_and_mount_reads_are_memory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=D.DiagnosticRun(tmp,Path(tmp)/'out')
            def capture(argv,**kw):
                self.assertNotIn('stdout_path',kw);self.assertNotIn('stderr_path',kw)
                self.assertEqual(kw['env']['HOME'],'/actual/runner')
                kw['receipt'].update(pid=1,cleanup=dict(group_state='absent',leader_reaped=True))
                return b'{}'
            with patch.object(D,'bounded_capture',side_effect=capture),patch.object(D.shutil,'disk_usage',return_value=type('Disk',(),{'free':30*D.GIB})()),patch.dict(os.environ,{**environment(),'HOME':'/actual/runner'}):
                row=r.observe('registry',['fixed'],5,4*D.R.MIB,D.registry)
            self.assertEqual(row['status'],'OBSERVED')
            self.assertFalse(list(r.diagnostic_dir.glob('*.stdout')));self.assertFalse(list(r.diagnostic_dir.glob('*.stderr')))
    def test_failed_query_preserves_sanitized_prefix_and_marks_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=D.DiagnosticRun(tmp,Path(tmp)/'out')
            def capture(argv,**kw):
                kw['stream_sink'](('{"error":"unmount '+ID+' /private/secret').encode(),b'error secret@example.test')
                raise P.CaptureFailure('Metadata command work deadline exceeded')
            with patch.object(D,'bounded_capture',side_effect=capture),patch.object(D.shutil,'disk_usage',return_value=type('Disk',(),{'free':30*D.GIB})()):
                row=r.observe('query',['fixed'],5,4096,D.registry)
            self.assertEqual(row['status'],'PARTIAL');self.assertNotIn('data',row)
            self.assertIn(ID,row['partial_streams']['stdout']['uuids'])
            self.assertNotIn('secret',json.dumps(row));self.assertIn('incomplete',row['omission'])
    def test_log_query_alone_uses_empty_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=D.DiagnosticRun(tmp,Path(tmp)/'out')
            def capture(argv,**kw):
                self.assertEqual(kw['env']['HOME'],str(r.diagnostic_dir/'empty-home'));return b'[]'
            with patch.object(D,'bounded_capture',side_effect=capture),patch.object(D.shutil,'disk_usage',return_value=type('Disk',(),{'free':30*D.GIB})()),patch.dict(os.environ,environment()):
                self.assertEqual(r.observe('log',['fixed'],6,4096,lambda x:[],empty_home=True)['status'],'OBSERVED')
    def test_unproved_observational_group_blocks_new_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=D.DiagnosticRun(tmp,Path(tmp)/'out');r.diagnostics=[dict(operation=dict(pid=1,cleanup=dict(group_state='unverified',leader_reaped=False)))]
            with patch.object(r,'observe',side_effect=AssertionError('must omit')):r.snapshot('after',True)
            self.assertFalse(r.observations_safe())
            self.assertIn('unproved',(r.diagnostic_dir/'after-omitted.json').read_text())
    def test_closed_failed_observation_does_not_block_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=D.DiagnosticRun(tmp,Path(tmp)/'out')
            r.diagnostics=[dict(status='UNAVAILABLE',operation=dict(pid=1,cleanup=dict(group_state='absent',leader_reaped=True,success=False)))]
            self.assertTrue(r.observations_safe())


class NativeSequence(unittest.TestCase):
    def test_late_observer_start_and_join_use_existing_absolute_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=D.DiagnosticRun(tmp,Path(tmp)/'out');r.end=110
            with patch.object(D.time,'monotonic',return_value=100),patch.object(D.threading,'Thread'):
                r.start_observer()
            self.assertEqual(r.observer_end,110)
            r.cleanup_end=108;r.observer_record={'cleanup':{'success':True}};r.observer.is_alive.return_value=False
            with patch.object(D.time,'monotonic',return_value=105):r.stop_observer()
            r.observer.join.assert_called_once_with(3)
    class Fake:
        def __init__(self,fail=False):self.calls=[];self.fail=fail;self.device=None
        def start_observer(self):self.calls.append(('observer',))
        def snapshot(self,*args):self.calls.append(('snapshot',*args))
        def observations_safe(self):return True
        def sim(self,*args,**kw):
            self.calls.append((args,kw))
            if args[:2]==('list','runtimes'):return json.dumps({'runtimes':[dict(identifier=D.R.RUNTIME,isAvailable=True)]}).encode()
            if args[:2]==('list','devices'):
                items=[] if not self.device else [dict(udid=ID,name=self.name,deviceTypeIdentifier=D.R.DEVICES['iphone'],state='Shutdown')]
                return json.dumps({'devices':{D.R.RUNTIME:items}}).encode()
            if args[0]=='create':self.name=args[1];return ID.encode()
            if args[0]=='install' and self.fail:raise P.CaptureFailure('deadline')
            return b''
    def test_single_install_no_runner_or_ui_and_caps_unchanged(self):
        f=self.Fake();result={};D.native_sequence(f,Path('/app'),result)
        commands=[x for x in f.calls if isinstance(x[0],tuple)]
        self.assertEqual([x[0][0] for x in commands],['list','list','create','list','boot','bootstatus','install'])
        self.assertEqual(commands[-1][1],{'cap':60});self.assertTrue(result['install_completed'])
        self.assertLessEqual(commands[-2][1]['cap'],180)
    def test_install_error_not_retried_and_no_success(self):
        f=self.Fake(True);result={}
        with self.assertRaises(P.CaptureFailure):D.native_sequence(f,Path('/app'),result)
        self.assertEqual(sum(isinstance(x[0],tuple) and x[0][0]=='install' for x in f.calls),1)
        self.assertNotIn('install_completed',result)
    def test_boot_deadline_never_renews_or_reaches_install(self):
        f=self.Fake()
        with patch.object(D.time,'monotonic',side_effect=[0,0,181]):
            with self.assertRaisesRegex(D.R.AcceptanceError,'Boot budget expired'):
                D.native_sequence(f,Path('/app'),{})
        self.assertFalse(any(isinstance(x[0],tuple) and x[0][0]=='install' for x in f.calls))
    def test_preexisting_device_never_owned_or_booted(self):
        f=self.Fake();original=f.sim
        def sim(*a,**kw):
            if a[:2]==('list','devices'):return json.dumps({'devices':{D.R.RUNTIME:[dict(udid=ID)]}}).encode()
            return original(*a,**kw)
        f.sim=sim
        with self.assertRaisesRegex(D.R.AcceptanceError,'Preexisting'):D.native_sequence(f,Path('/app'),{})
        self.assertIsNone(f.device)
    def test_low_free_space_stops_owned_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=D.DiagnosticRun(tmp,Path(tmp)/'out')
            with patch.object(D.shutil,'disk_usage',return_value=type('Disk',(),{'free':D.FREE_FLOOR-1})()):
                with self.assertRaisesRegex(D.R.AcceptanceError,'free-space'):r.guard()
    def test_heartbeat_stop_is_owned_and_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'rc-install-diagnostic/diagnostic';out.mkdir(parents=True)
            D.R.save(out/'observer-stop.json',{'token':ID})
            with patch.dict(os.environ,environment(tmp),clear=True),patch.object(D,'bounded_capture',side_effect=AssertionError('heartbeat must not spawn')):
                D.heartbeat(out,ID,time.monotonic()+1)
            r=json.loads((out/'heartbeat-result.json').read_text());self.assertEqual(r['samples'],0);self.assertEqual(r['stop_reason'],'requested')

if __name__=='__main__':unittest.main(verbosity=2)
