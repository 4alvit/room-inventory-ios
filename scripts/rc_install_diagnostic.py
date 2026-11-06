#!/usr/bin/env python3
"""One branch-only install diagnostic; never an installed-RC acceptance result."""
from __future__ import annotations
import argparse
from collections import Counter
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import threading
import time
import uuid

import rc_acceptance as R
from rc_acceptance_process import bounded_capture

BRANCH = 'diagnostic/rc-install-responsiveness'
SOURCE = '2c7dfdf5c776e3b0f0809dcf93d74160e19396f8'
TREE = '37cded0739a2c12199c224affb479e88df8f54dd'
EXPECTED = dict(tag='v0.1.0-rc.1', source_sha=SOURCE, source_tree=TREE,
                run_id=42229983753, run_attempt=1, release_id=436610044,
                manifest_sha256='440d4f0b52a85dfade7659918d51bfc1e156fedb421f0866764e27f25d14cae8')
GIB = 1024**3
FREE_FLOOR = 16 * GIB
OWNED_CEILING = 12 * GIB
TELEMETRY_CAP = 8 * R.MIB
OBSERVER_SECONDS = 480
SAFE_ENV_NAMES = ('SIMULATOR_RUNTIME_VERSION', 'SIMULATOR_UDID', 'SIMULATOR_ROOT',
                  'SIMCTL_CHILD_DYLD_INSERT_LIBRARIES', 'DYLD_INSERT_LIBRARIES',
                  'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH')
PROCESS_NAMES = ('simctl', 'com.apple.CoreSimulator.CoreSimulatorService',
                 'simdiskimaged', 'SimLaunchHost', 'SimLaunchHost.arm64', 'installd')
TERMS = ('connection invalid', 'connection interrupted', 'timeout', 'timed out',
         'unavailable', 'failed', 'error', 'permission', 'denied', 'registration',
         'register', 'unregister', 'mount', 'unmount', 'cleanup', 'migration',
         'duplicate', 'MobileAsset', 'cryptex')
DOMAINS = ('NSPOSIXErrorDomain', 'NSCocoaErrorDomain', 'NSMachErrorDomain',
           'NSOSStatusErrorDomain', 'com.apple.CoreSimulator.SimError')
UUID_RE = re.compile(r'\b[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\b')
DISK_RE = re.compile(r'(?<![A-Za-z0-9])(?:/dev/)?disk\d+(?:s\d+)*(?![A-Za-z0-9])')
BUILD_RE = re.compile(r'\b\d{2}[A-Z]\d{2,6}[a-z]?\b')
LOG_PREDICATE = ('(' + ' OR '.join('process == '+json.dumps(x) for x in PROCESS_NAMES)
                 + ' OR subsystem BEGINSWITH "com.apple.CoreSimulator") AND ('
                 + ' OR '.join('eventMessage CONTAINS[c] '+json.dumps(x)
                               for x in (*TERMS,*DOMAINS,'code','errno')) + ')')


def stamp():
    return dict(monotonic_ns=time.monotonic_ns(), utc_ns=time.time_ns(), cpu_ns=time.process_time_ns())


def validate_host(env):
    expected = dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='workflow_dispatch',
                    GITHUB_REPOSITORY=R.REPO, GITHUB_REF='refs/heads/'+BRANCH,
                    GITHUB_WORKFLOW_REF=R.REPO+'/.github/workflows/rc-acceptance.yml@refs/heads/'+BRANCH,
                    RUNNER_ARCH='ARM64', DEVELOPER_DIR='/Applications/Xcode_27.1.app/Contents/Developer')
    R.require(all(env.get(k) == v for k, v in expected.items()), 'Diagnostic hosted context mismatch')
    R.require(re.fullmatch('[0-9a-f]{40}', env.get('GITHUB_SHA', '')), 'Diagnostic source SHA missing')


class Trace:
    """Bounded scalar events plus separate last/terminal records after saturation."""
    def __init__(self):
        self.events, self.counts, self.last, self.terminal = [], Counter(), None, {}
        self.max_gap_ns, self.dropped, self.incomplete = 0, 0, False
        self.max_gap_pair = None
    def __call__(self, phase, **fields):
        try:
            row = dict(phase=phase, **stamp())
            row.update({k:v for k,v in fields.items() if type(v) in (int, float) and math.isfinite(v)})
            if self.last:
                gap = row['monotonic_ns'] - self.last['monotonic_ns']
                if gap < 0:self.incomplete = True
                if gap > self.max_gap_ns:
                    self.max_gap_ns = gap
                    self.max_gap_pair = dict(previous=self.last,next=row)
            self.counts[phase] += 1; self.last = row
            if phase in ('work_expired','cleanup_begin','cleanup_end','pipe_close_end','persist_end'):
                self.terminal[phase] = row
            if len(self.events) < 2048:self.events.append(row)
            else:self.dropped += 1
        except Exception:self.incomplete = True
    def result(self):
        return dict(events=self.events, counts=dict(self.counts), last=self.last,
                    terminal=self.terminal, max_gap_ns=self.max_gap_ns,
                    max_gap_pair=self.max_gap_pair,
                    dropped=self.dropped, incomplete=self.incomplete or bool(self.dropped))


def correlations(text):
    return dict(uuids=sorted(set(x.upper() for x in UUID_RE.findall(text)))[:16],
                mount_devices=sorted(set(x.removeprefix('/dev/') for x in DISK_RE.findall(text)))[:16],
                builds=sorted(set(BUILD_RE.findall(text)))[:16])


def checked_json(raw):
    R.require(len(raw) <= 4*R.MIB, 'Diagnostic JSON byte cap')
    depth, quoted, escaped = 0, False, False
    for c in raw:
        if quoted:
            if escaped:escaped=False
            elif c==92:escaped=True
            elif c==34:quoted=False
        elif c==34:quoted=True
        elif c in (91,123):
            depth+=1;R.require(depth<=16,'Diagnostic JSON depth cap')
        elif c in (93,125):depth-=1
    return R.loads(raw)


def registry(raw):
    obj=checked_json(raw); rows=[]; visited=0; omitted=0
    def visit(value, key=''):
        nonlocal visited, omitted
        visited+=1;R.require(visited<=4096,'Registry node cap')
        if isinstance(value,dict):
            safe={}; corr=correlations(key)
            for k,v in value.items():
                if isinstance(v,(str,int,bool)) and not isinstance(v,float):
                    if k.lower() in ('uuid','identifier','runtimeidentifier','build','buildversion','version','state','status','kind','isavailable'):
                        if isinstance(v,str):
                            if (UUID_RE.fullmatch(v) or BUILD_RE.fullmatch(v) or re.fullmatch(r'\d+(?:[.-]\d+){0,4}',v)
                                or re.fullmatch(r'com\.apple\.CoreSimulator\.SimRuntime\.[A-Za-z0-9.-]{1,80}',v)
                                or v.lower() in ('ready','available','unavailable','mounted','unmounted','mounting','unmounting','disk image','bundled','runtime','error','unusable','unusable - cryptex mount preferred')):
                                safe[k.lower()]=v
                            for field, items in correlations(v).items():corr[field]=sorted(set(corr[field]+items))[:16]
                        else:safe[k.lower()]=v
                    elif isinstance(v,str):
                        for field,items in correlations(v).items():corr[field]=sorted(set(corr[field]+items))[:16]
            if safe or any(corr.values()):
                if len(rows)<128:rows.append(dict(fields=safe, **corr))
                else:omitted+=1
            for k,v in value.items():
                if isinstance(v,(dict,list)):visit(v,k)
        elif isinstance(value,list):
            for v in value:visit(v,key)
    visit(obj)
    return dict(rows=rows, visited=visited, omitted=omitted, incomplete=bool(omitted))


def mounts(raw):
    R.require(len(raw)<=R.MIB,'Mount byte cap');rows=[];omitted=0
    for line in raw.decode('utf-8','strict').splitlines():
        if not any(x in line for x in ('CoreSimulator','SimulatorRuntime','cryptex','Cryptex','MobileAsset')):continue
        row=correlations(line)
        row['categories']=[x for x in ('CoreSimulator','SimulatorRuntime','cryptex','Cryptex','MobileAsset') if x in line]
        if len(rows)<128:rows.append(row)
        else:omitted+=1
    return dict(rows=rows, omitted=omitted, incomplete=bool(omitted))


def processes(raw, owned):
    R.require(len(raw)<=R.MIB,'Process byte cap');rows=[];omitted=0
    for line in raw.decode('utf-8','strict').splitlines():
        bits=line.strip().split(None,7)
        if len(bits)!=8:continue
        pid,ppid,pgid,state,cpu,rss,elapsed,command=bits;name=command.rsplit('/',1)[-1]
        if not pid.isdigit() or (int(pid) not in owned and name not in PROCESS_NAMES):continue
        R.require(ppid.isdigit() and pgid.isdigit() and rss.isdigit(),'Invalid process scalars')
        R.require(re.fullmatch(r'[A-Za-z+<>NWsX?]{1,12}',state) and re.fullmatch(r'[0-9:-]{1,32}',elapsed),'Invalid process state')
        percent=float(cpu);R.require(math.isfinite(percent) and 0<=percent<=100000,'Invalid process CPU')
        row=dict(pid=int(pid),ppid=int(ppid),pgid=int(pgid),state=state,cpu_percent=percent,rss_kib=int(rss),elapsed=elapsed,source=name if name in PROCESS_NAMES else 'owned')
        if len(rows)<64:rows.append(row)
        else:omitted+=1
    return dict(rows=rows, omitted=omitted, incomplete=bool(omitted))


def native_logs(raw, begin, finish):
    events=checked_json(raw);R.require(isinstance(events,list) and len(events)<=4096,'Log event cap')
    rows=[];omitted=0;outside=0
    for event in events:
        R.require(isinstance(event,dict),'Invalid log event')
        process=event.get('processImagePath','').rsplit('/',1)[-1];subsystem=event.get('subsystem','')
        if process not in PROCESS_NAMES and not subsystem.startswith('com.apple.CoreSimulator'):continue
        text=event.get('eventMessage','');timestamp=event.get('timestamp','')
        R.require(isinstance(text,str) and len(text)<=256*1024 and isinstance(timestamp,str) and len(timestamp)<=64,'Invalid log fields')
        t=dt.datetime.fromisoformat(timestamp.replace('Z','+00:00'));R.require(t.tzinfo is not None,'Log timezone missing')
        if not begin<=t.timestamp()<=finish:outside+=1;continue
        row=dict(source=process if process in PROCESS_NAMES else 'coresimulator_subsystem',timestamp=t.astimezone(dt.timezone.utc).isoformat(),
                 terms=[x for x in TERMS if re.search(r'\b'+re.escape(x)+r'\b',text,re.I)],
                 domains=[x for x in DOMAINS if x in text],codes=[int(x) for x in re.findall(r'\b(?:Code|code|errno)\s*[=:]\s*(-?\d{1,6})(?!\d)',text)[:8]],**correlations(text))
        if len(rows)<128:rows.append(row)
        else:omitted+=1
    result=dict(returned=len(events),outside_window=outside,rows=rows,omitted=omitted,incomplete=bool(omitted),native_cause='UNKNOWN')
    while len(json.dumps(result).encode())>65536 and rows:
        rows.pop();result['omitted']+=1;result['incomplete']=True
    return result


def partial_stream(raw):
    """Correlations in a captured prefix are not structured/query-complete evidence."""
    text=raw.decode('utf-8','replace')
    return dict(bytes=len(raw),sha256=R.digest(raw),prefix_only=True,
                structured_state_proven=False,**correlations(text),
                terms={x:min(4096,len(re.findall(r'\b'+re.escape(x)+r'\b',text,re.I))) for x in TERMS
                       if re.search(r'\b'+re.escape(x)+r'\b',text,re.I)})


def heartbeat(output, token, end):
    validate_host(os.environ)
    output=Path(output);R.require(output.is_dir() and not output.is_symlink(),'Observer output absent')
    R.require(output==Path(os.environ['RUNNER_TEMP'])/'rc-install-diagnostic/diagnostic','Observer output mismatch')
    R.require(str(uuid.UUID(token)).upper()==token,'Invalid observer token')
    R.require(math.isfinite(end) and end<=time.monotonic()+OBSERVER_SECONDS,'Invalid observer deadline')
    count=0;reason='fixed_deadline';first=stamp()
    with (output/'heartbeat.jsonl').open('x') as stream:
        while time.monotonic()<end and count<480:
            if (output/'observer-stop.json').exists():
                R.require(R.loads(R.regular(output/'observer-stop.json',128))==dict(token=token),'Observer stop mismatch')
                reason='requested';break
            row=stamp();row.update(load=list(os.getloadavg()),free_bytes=shutil.disk_usage(output).free)
            encoded=json.dumps(row,allow_nan=False)+'\n';R.require(len(encoded)<=1024,'Heartbeat row cap')
            stream.write(encoded);stream.flush();count+=1
            time.sleep(min(1,max(0,end-time.monotonic())))  # Measurement cadence, never a readiness delay.
    R.save(output/'heartbeat-result.json',dict(first=first,last=stamp(),samples=count,stop_reason=reason,
           scope='Observer CPU and heartbeat, not target-process CPU; missing intervals are not cause proof.'))


class DiagnosticRun(R.Run):
    def __init__(self, root, out):
        super().__init__(root,out)
        self.diagnostics=[];self.diagnostic_bytes=0;self.traces=[];self.owned_pids={os.getpid()}
        self.omissions=[];self.trace_terminals=[]
        self.observer=None;self.observer_record={};self.observer_error=None;self.native_begin=None
        self.diagnostic_dir=self.out/'diagnostic';self.diagnostic_dir.mkdir()
    def keep(self,name,value,final=False):
        raw=(json.dumps(value,allow_nan=False,indent=2)+'\n').encode()
        # Reserve512KiB for the480 bounded heartbeat rows and their final record.
        limit=TELEMETRY_CAP-512*1024 if final else TELEMETRY_CAP-512*1024-R.MIB
        if len(raw)>R.MIB or self.diagnostic_bytes+len(raw)>limit:
            if len(self.omissions)<128:self.omissions.append(dict(name=name,reason='retention_cap'))
            return False
        with (self.diagnostic_dir/name).open('xb') as f:f.write(raw)
        self.diagnostic_bytes+=len(raw)
        return True
    def guard(self):
        R.require(shutil.disk_usage(self.out).free>=FREE_FLOOR,'Diagnostic free-space floor')
        end=min(self.end,time.monotonic()+10);pending=[self.out];total=entries=0
        while pending:
            R.require(time.monotonic()<end,'Owned output census deadline')
            with os.scandir(pending.pop()) as scan:
                for entry in scan:
                    entries+=1;R.require(entries<=100000 and time.monotonic()<end,'Owned output census cap')
                    s=entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(s.st_mode):pending.append(entry.path)
                    else:total+=max(s.st_size,getattr(s,'st_blocks',0)*512)
                    R.require(total<=OWNED_CEILING,'Diagnostic owned output ceiling')
        return dict(free_bytes=shutil.disk_usage(self.out).free,owned_bytes=total,entries=entries)
    def command(self,argv,name,cap=30,limit=16*R.MIB,cleanup=False):
        if cleanup and self.cleanup_end is None:self.cleanup_end=time.monotonic()+90
        remaining=(self.cleanup_end if cleanup else self.end)-time.monotonic()
        R.require(remaining>4 and cap>0,'Overall acceptance deadline')
        record={};stem=self.out/'operations'/f'{len(self.commands)+1:03d}-{name}';trace=Trace()
        try:
            return bounded_capture([str(x) for x in argv],cwd=self.root,env=os.environ.copy(),
                timeout=min(cap,remaining-4),limit=limit,receipt=record,
                stdout_path=stem.with_suffix('.stdout'),stderr_path=stem.with_suffix('.stderr'),
                phase_sink=trace if self.native_begin is not None else None)
        finally:
            self.commands.append(record);R.save(stem.with_suffix('.json'),record)
            if record.get('pid') and not record.get('cleanup',{}).get('leader_reaped'):
                self.owned_pids.add(record['pid'])
            if self.native_begin is not None:
                summary=trace.result()
                self.trace_terminals.append(dict(command=stem.name,last=summary['last'],terminal=summary['terminal'],
                                                max_gap_pair=summary['max_gap_pair'],dropped=summary['dropped'],incomplete=summary['incomplete']))
                try:self.keep(stem.name+'-phases.json',summary)
                except Exception:self.omissions.append(dict(name=stem.name,reason='trace_write_failed'))
    def observe(self,name,argv,cap,limit,sanitizer,empty_home=False):
        row=dict(name=name,start=stamp(),status='UNAVAILABLE');record={};captured={}
        def receive(stdout,stderr):captured.update(stdout=stdout,stderr=stderr)
        try:
            # Unlike Run.command, neither raw stream is persisted.
            R.require(time.monotonic()+cap+4<self.end,'Observation budget unavailable')
            R.require(shutil.disk_usage(self.out).free>=FREE_FLOOR,'Observation disk floor')
            env=os.environ.copy()
            if empty_home:
                env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C','LC_ALL':'C',
                     'HOME':str(self.diagnostic_dir/'empty-home'),'DEVELOPER_DIR':os.environ['DEVELOPER_DIR']}
            raw=bounded_capture(argv,cwd=self.root,env=env,timeout=cap,limit=limit,
                                receipt=record,stream_sink=receive)
            row['data']=sanitizer(raw);row['status']='OBSERVED'
        except Exception as e:
            row['reason']=type(e).__name__
            if captured:
                row['status']='PARTIAL'
                row['partial_streams']={k:partial_stream(v) for k,v in captured.items()}
                row['omission']='command_or_parse_incomplete; captured prefixes only, not complete native state'
            else:row['omission']='no_stream_handoff_before_failure'
        finally:
            row['finish']=stamp();row['operation']=record
            self.diagnostics.append(row);self.keep(name+'.json',row)
        return row
    def observations_safe(self):
        return all(not x['operation'].get('pid') or (x['operation'].get('cleanup',{}).get('group_state')=='absent'
                   and x['operation'].get('cleanup',{}).get('leader_reaped')) for x in self.diagnostics)
    def snapshot(self,phase,registry_too=False):
        if not self.observations_safe():
            self.keep(phase+'-omitted.json',dict(reason='earlier_observation_group_unproved'));return
        owned=set(self.owned_pids)
        if self.observer_record.get('pid') and not self.observer_record.get('cleanup',{}).get('leader_reaped'):
            owned.add(self.observer_record['pid'])
        self.observe(phase+'-processes',['/bin/ps','-axo','pid=,ppid=,pgid=,state=,%cpu=,rss=,etime=,comm='],2,R.MIB,lambda x:processes(x,owned))
        if registry_too and self.observations_safe():
            self.observe(phase+'-registry',['xcrun','simctl','runtime','list','-j'],5,4*R.MIB,registry)
        if registry_too and self.observations_safe():
            self.observe(phase+'-mounts',['/sbin/mount'],2,R.MIB,mounts)
    def start_observer(self):
        self.native_begin=stamp();self.observer_token=str(uuid.uuid4()).upper()
        self.observer_end=min(time.monotonic()+OBSERVER_SECONDS+4,self.end)
        def run():
            try:
                remaining=self.observer_end-time.monotonic()-4
                R.require(remaining>0,'Observer parent budget exhausted')
                bounded_capture([sys.executable,str(Path(__file__).resolve()),'observe','--output',str(self.diagnostic_dir),'--token',self.observer_token,'--end',str(self.observer_end-4)],
                    cwd=self.root,env=os.environ.copy(),timeout=remaining,limit=65536,receipt=self.observer_record)
            except BaseException as e:self.observer_error=type(e).__name__
        self.observer=threading.Thread(target=run,name='diagnostic-heartbeat-owner',daemon=True);self.observer.start()
    def stop_observer(self):
        if self.observer is None:return
        R.save(self.diagnostic_dir/'observer-stop.json',dict(token=self.observer_token))
        end=min(self.observer_end,self.cleanup_end if self.cleanup_end is not None else self.end)
        self.observer.join(max(0,end-time.monotonic()))
        self.keep('observer-owner.json',dict(operation=dict(self.observer_record),error=self.observer_error,
                  owner_thread_finished=not self.observer.is_alive(),coverage='best_effort_fixed480s_no_renewal'))
        R.require(not self.observer.is_alive() and self.observer_record.get('cleanup',{}).get('success') is True,
                  'Heartbeat owner cleanup unproved')


def native_sequence(run,aut,result):
    run.start_observer();run.snapshot('before-boot',True)
    R.require(run.observations_safe(),'Observation child unproved before device work')
    runtime=R.loads(run.sim('list','runtimes','--json'))
    matches=[x for x in runtime['runtimes'] if x.get('identifier')==R.RUNTIME and x.get('isAvailable') is True]
    R.require(len(matches)==1,'Required runtime unavailable');result['runtime']=matches[0]
    name='RC-DIAGNOSTIC-'+str(uuid.uuid4()).upper()
    before=R.loads(run.sim('list','devices','--json'))
    created=run.sim('create',name,R.DEVICES['iphone'],R.RUNTIME).decode().strip()
    R.require(str(uuid.UUID(created)).upper()==created,'Invalid created UUID')
    R.require(created not in {x['udid'] for group in before['devices'].values() for x in group},'Preexisting device')
    run.device=created;result['device_uuid']=created
    result['created_device']=R.validate_created_device(before,R.loads(run.sim('list','devices','--json')),created,name,R.DEVICES['iphone'])
    boot_end=time.monotonic()+180
    run.sim('boot',created,cap=boot_end-time.monotonic());R.require(time.monotonic()<boot_end,'Boot budget expired')
    run.sim('bootstatus',created,'-b',cap=boot_end-time.monotonic());R.require(time.monotonic()<boot_end,'Boot status returned late')
    run.snapshot('after-boot')
    R.require(run.observations_safe(),'Observation child unproved before install')
    run.sim('install',created,aut,cap=60)
    result['install_completed']=True


def execute(args):
    validate_host(os.environ);R.validate_expected(args.expected);R.require(args.expected==EXPECTED,'Diagnostic RC changed')
    R.require(args.output==Path(os.environ['RUNNER_TEMP'])/'rc-install-diagnostic','Diagnostic output mismatch')
    root=Path(__file__).resolve().parents[1];run=DiagnosticRun(root,args.output)
    result=dict(status='DIAGNOSTIC_FAILED',expected_rc=args.expected,tests_executed=False,install_completed=False,
                observations='not installed-artifact acceptance',safe_environment_presence={x:x in os.environ for x in SAFE_ENV_NAMES})
    primary=None;cleanup_errors=[]
    try:
        head=run.command(['git','rev-parse','HEAD'],'source-head',cap=8).decode().strip()
        R.require(head==args.harness_sha==os.environ['GITHUB_SHA'],'Diagnostic SHA mismatch')
        R.require(not run.command(['git','status','--porcelain'],'source-clean',cap=8).strip(),'Dirty diagnostic checkout')
        result['harness_sha']=head
        result['sources']={p:R.digest(R.regular(root/p,2*R.MIB)) for p in R.SOURCE_INPUTS+['scripts/rc_install_diagnostic.py']}
        result['admission']=run.guard()
        (run.diagnostic_dir/'empty-home').mkdir()
        gh=run.out/'tools/gh';gh.parent.mkdir()
        run.command([sys.executable,'scripts/install_release_gh.py','--output',gh],'install-qualified-gh',cap=240,limit=4*R.MIB)
        gh_manifest=R.loads(R.regular(root/'.github/gh/release.json',R.MIB))
        R.require(R.digest(R.regular(gh,64*R.MIB))==gh_manifest['artifacts']['macOS_arm64']['binary_sha256'],'Unqualified gh')
        _,_,_,manifest=R.download_rc(run,args.expected,str(gh))
        candidates=[x for x in manifest['assets'] if x['name'].endswith('-unsigned-simulator.zip')]
        R.require(len(candidates)==1,'Expected one Simulator preview');asset=candidates[0]
        raw=R.regular(run.out/'payload'/asset['name']);R.verify_payload(asset,raw)
        inventory=R.extract_preview(raw,run.out/'extracted',manifest['version']);R.save(run.out/'downloaded-app-inventory.json',inventory)
        aut=run.out/'extracted/RoomInventory.app'
        archs=run.command(['lipo','-archs',aut/'RoomInventory'],'rc-architectures',cap=8).decode().split()
        R.require(set(archs)=={'arm64','x86_64'} and len(archs)==2,'Unexpected RC architectures')
        metadata=R.loads(R.regular(run.out/'payload/preview-build.json',R.MIB))
        R.require(metadata.get('source_commit')==SOURCE and metadata.get('base_version')==manifest['version']
                  and metadata.get('artifact_kind')=='unsigned-ios-simulator-preview' and metadata.get('architectures')==' '.join(archs),'Packaged metadata mismatch')
        result['packaged_build']=metadata
        _,_,_,result['harness_build']=R.build_harness(run,str(uuid.uuid4()).upper())
        result['after_build']=run.guard()
        native_sequence(run,aut,result)
        result['status']='DIAGNOSTIC_INSTALL_RETURNED_NOT_ACCEPTANCE'
    except BaseException as e:
        primary=e;result['error']=type(e).__name__
    finally:
        # No issue33 behavior change: preserve the observed list-first cleanup.
        try:
            if run.observations_safe():run.close_device()
            else:cleanup_errors.append('ObservationGroupUnproved_cleanup_not_admitted')
        except BaseException as e:cleanup_errors.append(type(e).__name__)
        try:
            if run.native_begin and run.observations_safe():
                begin=run.native_begin['utc_ns']/1e9;finish=time.time()
                R.require(0<=finish-begin<=1800,'Invalid log window')
                fmt=lambda x:dt.datetime.fromtimestamp(x,dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S%z')
                run.observe('native-log',['/usr/bin/log','show','--style','json','--timezone','UTC','--no-pager','--info','--debug',
                    '--start',fmt(begin),'--end',fmt(finish),'--predicate',LOG_PREDICATE],6,4*R.MIB,lambda x:native_logs(x,begin,finish),empty_home=True)
            if run.native_begin:run.snapshot('after-cleanup',True)
        except BaseException as e:cleanup_errors.append('diagnostic_'+type(e).__name__)
        try:run.stop_observer()
        except BaseException as e:cleanup_errors.append('observer_'+type(e).__name__)
        try:result['final_resources']=run.guard()
        except BaseException as e:cleanup_errors.append('resources_'+type(e).__name__)
        try:
            result['source_unchanged']=all(R.digest(R.regular(root/p,2*R.MIB))==sha for p,sha in result.get('sources',{}).items())
            R.require(result.get('sources') and result['source_unchanged'],'Diagnostic source changed')
        except BaseException as e:cleanup_errors.append('source_'+type(e).__name__)
        try:
            run.keep('terminal-summary.json',dict(commands=run.trace_terminals,omissions=run.omissions),final=True)
        except BaseException as e:cleanup_errors.append('terminal_'+type(e).__name__)
        result['cleanup_errors']=cleanup_errors;result['operations']=run.commands
        result['observation_operations']=[dict(name=x['name'],status=x['status'],operation=x['operation']) for x in run.diagnostics]
        result['observer_operation']=dict(run.observer_record)
        result['limitations']=['No UI tests or matrix acceptance.','Cooperative deadlines can overshoot on a stalled host.',
                              'Heartbeat coverage is fixed480s and may expire before cleanup.','No source, runtime registration or signing repair is performed.']
        if cleanup_errors:result['status']='DIAGNOSTIC_FAILED'
        R.save(run.out/'result.json',result)
    if primary:raise primary
    R.require(not cleanup_errors,'Diagnostic cleanup incomplete')


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    one=sub.add_parser('run');one.add_argument('--expected',type=Path,required=True);one.add_argument('--harness-sha',required=True);one.add_argument('--output',type=Path,required=True)
    observe=sub.add_parser('observe');observe.add_argument('--output',type=Path,required=True);observe.add_argument('--token',required=True);observe.add_argument('--end',type=float,required=True)
    args=parser.parse_args()
    if args.mode=='observe':heartbeat(args.output,args.token,args.end)
    else:
        args.expected=R.loads(R.regular(args.expected,R.MIB));execute(args)

if __name__=='__main__':main()
