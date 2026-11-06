#!/usr/bin/env python3
"""Read-only published-RC provenance and isolated hosted Simulator acceptance.

This workflow produces evidence for review, never a publication or promotion.
The sole native entry point requires a trusted main workflow_dispatch context.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import signal
import stat
import sys
import time
import uuid
import zipfile
from urllib.parse import unquote
from rc_acceptance_process import bounded_capture

MIB = 1024 * 1024
INSTALLATION_SECONDS = 300
REPO = '4alvit/room-inventory-ios'
BUNDLE = 'com.alvit.roominventory'
RUNNER = 'com.alvit.roominventory.rcacceptance.xctrunner'
TARGET = 'RoomInventoryRCAcceptanceTests'
METHOD = 'RCArtifactAcceptanceTests/testPublishedRC'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-27-0'
DEVICES = {'iphone': 'com.apple.CoreSimulator.SimDeviceType.iPhone-17',
           'ipad': 'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4-16GB'}
STEPS = ['fresh-launch', 'created-records', 'edited-record', 'cold-relaunch',
         'saved-csv', 'saved-pdf', 'saved-package', 'saved-backup',
         'restore-cancelled', 'mutated-record', 'restore-confirmed', 'restored-relaunch']
SOURCE_INPUTS = ['Acceptance/RC/project.yml', 'Acceptance/RC/RCArtifactAcceptanceTests.swift',
    'scripts/rc_acceptance.py', 'scripts/rc_acceptance_process.py',
    'scripts/release_control.py', 'scripts/release_validation.py', 'scripts/install-xcodegen.py', 'scripts/install_release_gh.py',
    'scripts/download_release_gh.go',
    '.github/gh/release.json', '.github/workflows/rc-acceptance.yml'] + [
    'UITests/Support/' + name + '.swift' for name in ['AutofocusedNameEntry',
    'NameEntryKeyboardReadiness', 'RecoveryOCRReadinessWindow', 'FilesNavigationReadiness',
    'ExportReturnReadiness']]

class AcceptanceError(RuntimeError): pass

def require(condition, message):
    if not condition: raise AcceptanceError(message)

def digest(data): return hashlib.sha256(data).hexdigest()

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result

def loads(data):
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(AcceptanceError('Nonfinite JSON')))

def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False); stream.write('\n')

def regular(path, limit=256*MIB):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit, 'Nonregular or oversized file')
        with os.fdopen(fd, 'rb', closefd=False) as stream: data = stream.read(limit+1)
        after = os.fstat(fd)
        key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(key(before) == key(after) and len(data) == before.st_size, 'File changed or truncated while reading')
        return data
    finally: os.close(fd)

def inventory(root, *, count_limit=4096, byte_limit=512*MIB):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'Expected plain inventory root')
    result, total, pending, entries = {}, 0, [root], 0
    while pending:
        parent = pending.pop()
        for path in sorted(parent.iterdir()):
            entries += 1; require(entries <= count_limit, 'Inventory entry cap')
            s = path.lstat(); require(not stat.S_ISLNK(s.st_mode), 'Inventory symlink')
            if stat.S_ISDIR(s.st_mode): pending.append(path); continue
            data = regular(path, byte_limit-total); total += len(data)
            result[path.relative_to(root).as_posix()] = {'size': len(data), 'sha256': digest(data),
                                                        'executable': bool(s.st_mode & 0o111)}
    return result

def verify_payload(expected, data):
    require(len(data)==expected['size'] and digest(data)==expected['sha256'], 'Incomplete or changed payload')

def same_installed(expected, installed):
    require(expected == installed, 'Installed AUT differs from exact downloaded RC')

def zip_members(data, *, max_files=4096, max_bytes=512*MIB):
    files, names, total = {}, set(), 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist(); require(len(infos) <= max_files, 'ZIP entry cap')
        for info in infos:
            name = info.filename.rstrip('/')
            p = PurePosixPath(name); mode = info.external_attr >> 16
            require(name and not p.is_absolute() and '\\' not in name and '\x00' not in name
                    and all(x not in ('', '.', '..') for x in name.split('/'))
                    and p.as_posix() == name, 'Unsafe ZIP path')
            require(name.casefold() not in names, 'Duplicate/case-folded ZIP member')
            names.add(name.casefold())
            require(not info.flag_bits & 1 and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR),
                    'Unsupported ZIP member')
            if info.is_dir(): continue
            total += info.file_size; require(0 <= info.file_size <= max_bytes and total <= max_bytes, 'ZIP byte cap')
            for ancestor in p.parents:
                require(ancestor.as_posix() not in files, 'ZIP file/directory collision')
            require(not any(x.startswith(name + '/') for x in files), 'ZIP file/directory collision')
            with z.open(info) as f: raw = f.read(info.file_size+1)
            require(len(raw) == info.file_size, 'ZIP incomplete member')
            files[name] = (raw, bool(mode & 0o111))
    return files

def extract_preview(data, destination, version):
    files = zip_members(data)
    require('PREVIEW-README.txt' in files and 'RoomInventory.app/Info.plist' in files, 'Not an unsigned Simulator preview')
    require(all(n == 'PREVIEW-README.txt' or n.startswith('RoomInventory.app/') for n in files), 'Unexpected preview member')
    info = plistlib.loads(files['RoomInventory.app/Info.plist'][0])
    require(info.get('CFBundleIdentifier') == BUNDLE and info.get('CFBundleExecutable') == 'RoomInventory'
            and info.get('CFBundleShortVersionString') == version
            and info.get('CFBundleSupportedPlatforms') == ['iPhoneSimulator'], 'AUT identity/platform/version mismatch')
    require('RoomInventory.app/RoomInventory' in files, 'AUT executable missing')
    destination = Path(destination); destination.mkdir(exist_ok=False)
    for name, (raw, executable) in files.items():
        p = destination/name; p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('xb') as f: f.write(raw)
        p.chmod(0o755 if executable else 0o644)
    return inventory(destination/'RoomInventory.app')

def validate_expected(config):
    require(set(config) == {'tag','source_sha','source_tree','run_id','run_attempt','release_id','manifest_sha256'}, 'Expected identity fields')
    require(re.fullmatch(r'v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-rc\.[1-9]\d*', config['tag'] or ''), 'Strict RC tag required')
    for key, length in [('source_sha',40),('source_tree',40),('manifest_sha256',64)]:
        require(isinstance(config[key],str) and re.fullmatch('[0-9a-f]{%d}'%length,config[key]), 'Invalid '+key)
    for key in ['run_id','run_attempt','release_id']:
        require(type(config[key]) is int and config[key] > 0, 'Invalid '+key)

def validate_manifest_binding(config, manifest, raw, release, assets):
    validate_expected(config)
    require(digest(raw) == config['manifest_sha256'], 'Manifest SHA mismatch')
    require(release.get('id') == config['release_id'], 'Release ID mismatch')
    require(all(manifest.get(k)==config[k] for k in ('source_sha','run_id','run_attempt','tag')), 'Manifest execution identity mismatch')
    expected = manifest['assets']; require(len({x['name'].casefold() for x in expected})==len(expected), 'Manifest duplicate assets')
    by_name = {x['name']:x for x in assets}
    require(len(by_name)==len(assets) and set(by_name)=={x['name'] for x in expected}|{'release-manifest.json'}, 'Asset inventory mismatch')
    for x in expected:
        require(by_name[x['name']]['size']==x['size'], 'Advertised asset size mismatch')
    return {x['name']:x for x in expected}

def destination_xctestrun(raw, runner_info, run_id):
    obj = plistlib.loads(raw)
    version = obj.get('__xctestrun_metadata__',{}).get('FormatVersion')
    require(version in (1,2), 'Unsupported xctestrun format')
    if version == 1:
        require(set(obj)=={'__xctestrun_metadata__',TARGET}, 'Expected only the dedicated target')
        target=obj[TARGET]
    else:
        configs = obj.get('TestConfigurations',[])
        require(len(configs)==1 and configs[0].get('IsEnabled',True) is True, 'Expected one test configuration')
        targets = configs[0].get('TestTargets',[])
        require(len(targets)==1, 'Expected one dedicated test target')
        target = targets[0]
    require(target.get('BlueprintName')==TARGET and target.get('IsUITestBundle') is True, 'Unexpected test target')
    require(runner_info.get('CFBundleIdentifier')==RUNNER, 'Unexpected test host')
    require(target.get('TestBundlePath','').endswith('/PlugIns/'+TARGET+'.xctest'), 'Unexpected test bundle path')
    require(target.get('TestHostPath','').endswith('/'+TARGET+'-Runner.app'), 'Unexpected runner path')
    require(not target.get('UITargetAppPath') and not target.get('UITargetAppBundleIdentifier'), 'Harness contains an AUT dependency')
    for k in ('TestBundlePath','TestHostPath','UITargetAppPath','DependentProductPaths','SkipTestIdentifiers'):
        target.pop(k,None)
    target.update(UseDestinationArtifacts=True,TestHostBundleIdentifier=RUNNER,
        TestBundleDestinationRelativePath='__TESTHOST__/PlugIns/'+TARGET+'.xctest',
        UITargetAppBundleIdentifier=BUNDLE,OnlyTestIdentifiers=[METHOD],
        EnvironmentVariables={'RC_ACCEPTANCE_ID':run_id},
        UITargetAppEnvironmentVariables={},UITargetAppCommandLineArguments=[])
    return plistlib.dumps(obj)

def validate_journey(value, run_id, evidence_files):
    require(value.get('schema_version')==1 and value.get('run_id')==run_id and value.get('status')=='complete', 'Incomplete/wrong journey')
    require(value.get('bundle_id')==BUNDLE and value.get('aut_launch_arguments')==['-AppleLanguages','(en)','-AppleLocale','en_US']
            and value.get('aut_launch_environment')=={}, 'Unexpected AUT injection')
    require(value.get('steps')==STEPS, 'Missing, duplicate or out-of-order acceptance steps')
    for step in STEPS:
        require(step+'.png' in evidence_files and step+'.txt' in evidence_files, 'Missing checkpoint screenshot/AX')
        require(evidence_files[step+'.png']['size']>32 and evidence_files[step+'.txt']['size']>32, 'Empty checkpoint evidence')
    require(value.get('restore_confirm_count')==1 and value.get('restore_cancel_count')==1, 'Restore action counts')
    expected_names={k:'RC '+label+' '+run_id[:8] for k,label in [('home','Home'),('room','Room'),('item','Item')]}
    require(value.get('names')==expected_names, 'Unexpected synthetic record names')
    return value['names']

def assert_inventory(value, names, notes):
    require(value.get('schemaVersion')==1 and len(value.get('homes',[]))==1, 'Expected one home')
    home=value['homes'][0]; require(home.get('name')==names['home'] and len(home.get('rooms',[]))==1, 'Home mismatch')
    room=home['rooms'][0]; require(room.get('name')==names['room'] and len(room.get('items',[]))==1, 'Room mismatch')
    item=room['items'][0]
    expected={'name':names['item'],'model':'RC Model','serialNumber':'RC-SERIAL-001',
              'purchasePrice':'USD 123.45','purchaseDate':'2026-01-02','notes':notes,'attachments':[]}
    require(all(item.get(k)==v for k,v in expected.items()), 'Restored item content mismatch')
    for node in [home,room,item]: uuid.UUID(node['id'])
    return item

def validate_exports(files, inv, names, run_id):
    expected={f'csv-{run_id}.csv',f'pdf-{run_id}.pdf',f'package-{run_id}.zip',f'backup-{run_id}.roominventory',f'cancel-backup-{run_id}.roominventory'}
    require(set(files)==expected, 'Missing/unexpected saved exports')
    backup=loads(files[f'backup-{run_id}.roominventory'])
    require(backup.get('format')=='com.alvit.roominventory.backup' and backup.get('version')==1 and backup.get('files')=={}, 'Backup format/original inventory mismatch')
    assert_inventory(backup.get('inventory',{}),names,'RC saved notes')
    cancelled=loads(files[f'cancel-backup-{run_id}.roominventory'])
    require(cancelled==backup,'Cancelling restore changed the exported inventory/originals')
    require(backup['inventory']==inv, 'Restored inventory does not equal exported backup')
    package=zip_members(files[f'package-{run_id}.zip'],max_files=8,max_bytes=24*MIB)
    require(set(package)=={'Inventory.csv','Inventory-localized.csv','Inventory.pdf','README.txt'},'Unexpected package contents')
    require(package['Inventory-localized.csv'][0]==files[f'csv-{run_id}.csv'],'Standalone and packaged CSV differ')
    require(files[f'pdf-{run_id}.pdf'].startswith(b'%PDF-') and b'%%EOF' in files[f'pdf-{run_id}.pdf'][-2048:], 'Invalid PDF framing')
    rows=list(csv.DictReader(io.StringIO(package['Inventory.csv'][0].decode('utf-8'))))
    require(len(rows)==1,'Expected exactly one CSV item')
    row=rows[0]; require(all(row.get(k)==v for k,v in {'home':names['home'],'room':names['room'],'item':names['item'],
        'model':'RC Model','serial_number':'RC-SERIAL-001','purchase_price':'USD 123.45',
        'purchase_date':'2026-01-02','notes':'RC saved notes','attachment_id':''}.items()),'CSV content mismatch')
    return {'backup_inventory_equal':True,'cancelled_backup_equal':True,'standalone_package_csv_equal':True,'pdf_review_required':True,'csv_items':1,
            'limitations':['No original attachment was added in this text-record acceptance scenario.','PDF framing/content bytes preserved; human page review remains required.']}

def validate_created_device(before, after, device_id, name, device_type):
    previous={d['udid'] for group in before['devices'].values() for d in group}
    require(device_id not in previous, 'Created device UUID already existed')
    current=[d for d in after['devices'].get(RUNTIME,[]) if d['udid']==device_id]
    require(len(current)==1 and current[0].get('name')==name
            and current[0].get('deviceTypeIdentifier')==device_type
            and current[0].get('state')=='Shutdown', 'Created device identity mismatch')
    return current[0]

def install_artifacts(run, aut, runner):
    phase_end=min(time.monotonic()+INSTALLATION_SECONDS,run.end)
    for artifact in (aut,runner):
        remaining=phase_end-time.monotonic()
        require(remaining>4,'Shared installation deadline')
        run.sim('install',run.device,artifact,cap=remaining-4)
        require(time.monotonic()<phase_end,'Artifact installation returned late')

class Run:
    def __init__(self, root, out):
        self.root,self.out=Path(root),Path(out)
        self.out.mkdir(parents=True,exist_ok=False)
        (self.out/'operations').mkdir()
        self.end=time.monotonic()+1800; self.commands=[]; self.device=None; self.cleanup_end=None
        self.owned_device=None; self.device_cleanup=None
    def command(self,argv,name,cap=30,limit=16*MIB,cleanup=False):
        if cleanup and self.cleanup_end is None:self.cleanup_end=time.monotonic()+90
        parent_end=self.cleanup_end if cleanup else self.end
        remaining=parent_end-time.monotonic()
        require(remaining>4 and cap>0,'Overall acceptance deadline')
        record={}; stem=self.out/'operations'/f'{len(self.commands)+1:03d}-{name}'
        try:
            return bounded_capture([str(x) for x in argv],cwd=self.root,env=os.environ.copy(),
                timeout=min(cap,remaining-4),limit=limit,receipt=record,
                stdout_path=stem.with_suffix('.stdout'),stderr_path=stem.with_suffix('.stderr'),
                cleanup_parent_deadline=parent_end)
        finally:
            self.commands.append(record); save(stem.with_suffix('.json'),record)
    def sim(self,*args,cap=30,cleanup=False):
        return self.command(['xcrun','simctl',*args],str(args[0]),cap=cap,cleanup=cleanup)
    def container(self,bundle,kind,cleanup=False):
        p=Path(self.sim('get_app_container',self.device,bundle,kind,cleanup=cleanup).decode().strip())
        expected=Path.home()/'Library/Developer/CoreSimulator/Devices'/self.device/'data/Containers'
        require(p.is_absolute() and p.resolve()==p and p.is_relative_to(expected),'Container outside exact device')
        return p
    def claim_created_device(self, before, after, device_id, name, device_type):
        created=validate_created_device(before,after,device_id,name,device_type)
        require(self.device==device_id and str(uuid.UUID(device_id)).upper()==device_id,
                'Created device differs from owned UUID')
        ownership={'udid':device_id,'name':name,'runtime':RUNTIME,'device_type':device_type,
                   'absent_before':True}
        # Preserve validated identity before any boot or installation side effect.
        save(self.out/'owned-device.json',ownership)
        self.owned_device=ownership
        return created
    def close_device(self):
        if not self.device:return
        report={'device_uuid':self.device,'state':'unproved','shutdown_requested':False,'errors':[]}
        self.device_cleanup=report
        def failed(stage,error):
            report['errors'].append(stage+': '+type(error).__name__+': '+str(error))
        try:
            owned=self.owned_device
            require(owned is not None and owned['udid']==self.device and owned['absent_before'] is True,
                    'Validated device ownership missing or changed')
            require(loads(regular(self.out/'owned-device.json',MIB))==owned,
                    'Persisted device ownership changed')
        except Exception as error:
            failed('ownership',error)
            raise AcceptanceError('; '.join(report['errors'])) from None
        def state(devices):
            matches=[(runtime,d) for runtime,group in devices['devices'].items()
                     for d in group if d['udid']==owned['udid']]
            require(len(matches)==1,'Owned device missing or duplicated')
            runtime,device=matches[0]
            require(runtime==owned['runtime'] and device.get('name')==owned['name']
                    and device.get('deviceTypeIdentifier')==owned['device_type'],
                    'Owned device identity changed')
            return device.get('state')
        may_shutdown=True; already_shutdown=False
        try:
            before=loads(self.sim('list','devices','--json',cleanup=True))
        except Exception as error:
            failed('initial census',error)
        else:
            try:already_shutdown=state(before)=='Shutdown'
            except Exception as error:
                failed('initial identity',error);may_shutdown=False
        if may_shutdown and not already_shutdown:
            # A request may be rejected by Run.command before any child is admitted.
            report['shutdown_requested']=True
            try:self.sim('shutdown',owned['udid'],cap=30,cleanup=True)
            except Exception as error:failed('shutdown',error)
        # Verification is independent of the initial census and shutdown outcome.
        # Run.command retains the one cleanup deadline; no stage renews it.
        try:
            devices=loads(self.sim('list','devices','--json',cleanup=True))
            require(state(devices)=='Shutdown','Owned device shutdown unproved')
            report['state']='Shutdown'
        except Exception as error:failed('final verification',error)
        if report['errors']:raise AcceptanceError('; '.join(report['errors']))

# The publication engine is reused only through this bodyless-GET transport.
def readonly_client(rc, run, gh_path):
    class ReadOnly(rc.GitHub):
        def __init__(self):
            self.repo=REPO; self.base='repos/'+REPO; self.workflow_scope_verified=False
            self.downloaded=set(); self.asset_sizes={}; self.total_bytes=0
        def upload(self,*a,**kw): raise AcceptanceError('Publication unavailable')
        def request(self,path,method='GET',body=None,mode='json'):
            require(method=='GET' and body is None and mode in ('json','pages','asset'),'Bodyless GET only')
            require(any(re.fullmatch(pattern,path,re.ASCII) for pattern in rc.API_PATHS['GET'])
                    or re.fullmatch(r'git/commits/[0-9a-f]{40}',path),'Unsupported read endpoint')
            require(all(p not in ('.','..') for p in unquote(path).split('/')),'Unsafe endpoint')
            binary=mode=='asset' or bool(re.fullmatch(r'actions/artifacts/[1-9]\d*/zip',path))
            argv=[gh_path,'api','--allow-escape-sequences','--hostname','github.com','--method','GET']
            endpoint=self.base+('/'+path if path else '')
            if binary:
                require(path not in self.downloaded,'Binary read cannot be replayed');self.downloaded.add(path)
                limit=self.asset_sizes.get(path) if mode=='asset' else 8*MIB
                require(type(limit) is int and 0<limit<=256*MIB,'Binary byte cap')
                self.total_bytes+=limit;require(self.total_bytes<=768*MIB,'Total binary byte cap')
                if mode=='asset':argv+=['-H','Accept: application/octet-stream']
            else:
                argv+=['--include'];limit=16*MIB
                if mode=='pages':
                    argv+=['--paginate','--jq','tojson'];endpoint+=('&' if '?' in endpoint else '?')+'per_page=100'
            raw=run.command(argv+['--',endpoint],'github-read',cap=180 if binary else 30,limit=limit)
            if not binary:
                status,raw=rc.github_http_response(raw,paginated=mode=='pages')
                require(status==200,'Metadata read must return HTTP 200')
            return raw
        def download_asset(self,path,stream):stream.write(self.request(path,mode='asset'))
    return ReadOnly()

def download_rc(run,expected,gh_path):
    import release_control as rc
    gh=readonly_client(rc,run,gh_path); info=rc.repository_info(gh)
    require(info.get('id')==1432741511 and info.get('default_branch')=='main','Wrong repository/default branch')
    initial=rc.release_snapshot(gh,expected['tag']);ref,release,assets=initial
    require(ref['object'].get('sha')==expected['source_sha'],'Tag source mismatch')
    commit=gh.api('git/commits/'+expected['source_sha'])
    require(commit.get('sha')==expected['source_sha'] and commit.get('tree',{}).get('sha')==expected['source_tree'],'Source tree mismatch')
    for asset in assets:gh.asset_sizes['releases/assets/'+str(rc.positive(asset['id'],'asset ID'))]=rc.positive(asset['size'],'asset size')
    manifests=[x for x in assets if x['name']==rc.MANIFEST];require(len(manifests)==1,'Expected one manifest')
    payload=run.out/'payload';payload.mkdir()
    rc.download_asset(gh,manifests[0]['id'],payload/rc.MANIFEST)
    raw=regular(payload/rc.MANIFEST,2*MIB);manifest=rc.validate_manifest(raw,REPO,expected['tag'])
    by_name=validate_manifest_binding(expected,manifest,raw,release,assets)
    policy=rc.source_policy_snapshot(gh,expected['source_sha']);rc.require_release_policy(policy['data'],REPO,qualified=True)
    require(policy==manifest['source_policy'],'Source policy mismatch')
    require(policy['data'].get('sign_releases',False) is False,'Signed RC requires separate qualified signature verifier')
    source_run=gh.api('actions/runs/'+str(expected['run_id']))
    require(source_run.get('id')==expected['run_id'] and source_run.get('event')=='workflow_dispatch','Wrong RC event')
    rc.validate_validation_run(gh,source_run,policy['data'],'rc')
    rc.validate_run(gh,source_run,info,expected['source_sha'],expected['run_attempt'],completed=True)
    rc.check_ancestry(gh,expected['source_sha'],info['default_branch']);rc.verify_evidence(gh,manifest,raw)
    for asset in assets:
        if asset['name']==rc.MANIFEST:continue
        got=rc.download_asset(gh,asset['id'],payload/asset['name'])
        require(got=={k:by_name[asset['name']][k] for k in ('size','sha256')},'Incomplete/wrong asset bytes')
        verify_payload(by_name[asset['name']],regular(payload/asset['name']))
    require(rc.snapshot_identity(rc.release_snapshot(gh,expected['tag']))==rc.snapshot_identity(initial),'Release changed during download')
    save(run.out/'rc-provenance.json',{'expected':expected,'manifest':manifest,'release_snapshot':initial,'source_run':source_run,'commit':commit})
    return rc,gh,initial,manifest

def saved_folder(device,folder):
    groups=Path.home()/'Library/Developer/CoreSimulator/Devices'/device/'data/Containers/Shared/AppGroup'
    require(groups.is_dir() and not groups.is_symlink(),'Missing device AppGroup root')
    matches=[];budget=10000
    for group in groups.iterdir():
        budget-=1;require(budget>=0 and not group.is_symlink(),'AppGroup entry cap/symlink')
        if not group.is_dir():continue
        provider=group/'File Provider Storage'
        if not provider.exists():continue
        require(not provider.is_symlink(),'Provider symlink')
        pending=[(provider,0)]
        while pending:
            p,depth=pending.pop();require(depth<=12,'Provider depth cap')
            for x in p.iterdir():
                budget-=1;require(budget>=0 and not x.is_symlink(),'Provider entry cap/symlink')
                if x.is_dir():
                    if x.name==folder:matches.append(x)
                    else:pending.append((x,depth+1))
    require(len(matches)==1,'Exact saved folder missing/ambiguous')
    return matches[0]

def build_harness(run,run_id):
    require(run.command(['xcodebuild','-version'],'xcode-version',cap=8).decode().strip()=='Xcode 27.1\nBuild version 27A9275','Unqualified Xcode')
    require(run.command(['uname','-m'],'architecture',cap=8).strip()==b'arm64','Unexpected host architecture')
    tool=run.command([sys.executable,'scripts/install-xcodegen.py'],'xcodegen-install',cap=120).decode().strip()
    (run.out/'project').mkdir()
    run.command([tool,'generate','--spec',run.root/'Acceptance/RC/project.yml',
        '--project-root',run.root,'--project',run.out/'project'],'generate',cap=30)
    run.command(['xcodebuild','-project',run.out/'project/RoomInventoryRCAcceptance.xcodeproj','-scheme','RCAcceptance',
        '-configuration','Release','-destination','generic/platform=iOS Simulator','-derivedDataPath',run.out/'DerivedData',
        'CODE_SIGNING_ALLOWED=NO','ARCHS=arm64','build-for-testing'],'build-runner',cap=600,limit=64*MIB)
    products=run.out/'DerivedData/Build/Products';runs=list(products.glob('*.xctestrun'))
    require(len(runs)==1,'Expected one generated xctestrun')
    runners=list(products.glob('Release-iphonesimulator/'+TARGET+'-Runner.app'))
    require(len(runners)==1,'Missing dedicated runner');runner=runners[0]
    apps=list(products.rglob('*.app'));require(len(apps)==1 and apps[0]==runner,'Unexpected application build product')
    configured=destination_xctestrun(regular(runs[0],2*MIB),plistlib.loads(regular(runner/'Info.plist',MIB)),run_id)
    plan=products/'RC-Installed.xctestrun';plan.write_bytes(configured)
    (run.out/'generated.xctestrun').write_bytes(regular(runs[0],2*MIB))
    (run.out/'configured.xctestrun').write_bytes(configured)
    proof={'runner_bundle_id':RUNNER,'only_app_product':str(runner.relative_to(run.out)),
           'configured_xctestrun_sha256':digest(configured),'mode':'UseDestinationArtifacts',
           'application_built':False,'test_executed':False}
    return products,runner,plan,proof

def build_only(args):
    require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_EVENT_NAME')=='pull_request'
            and os.environ.get('GITHUB_REPOSITORY')==REPO and os.environ.get('RUNNER_ARCH')=='ARM64',
            'Harness-only builds require this repository hosted PR context')
    root=Path(__file__).resolve().parents[1];run=Run(root,args.output)
    result={'status':'FAILED','application_installed':False,'tests_executed':False}
    error=None
    try:
        head=run.command(['git','rev-parse','HEAD'],'source-head',cap=8).decode().strip()
        require(head==args.harness_sha==os.environ.get('GITHUB_SHA') and re.fullmatch('[0-9a-f]{40}',head),'Harness SHA mismatch')
        require(not run.command(['git','status','--porcelain'],'source-clean',cap=8).strip(),'Harness checkout dirty')
        source={p:digest(regular(root/p,2*MIB)) for p in SOURCE_INPUTS}
        _,_,_,proof=build_harness(run,str(uuid.uuid4()).upper())
        for p,sha in source.items():require(digest(regular(root/p,2*MIB))==sha,'Harness source changed')
        result.update(status='PASS_RC_HARNESS_BUILD_NOT_EXERCISED',harness_sha=head,source=source,build=proof)
    except BaseException as caught:
        error=caught;result['error']=type(caught).__name__+': '+str(caught)
    finally:
        result['operations']=run.commands;save(run.out/'result.json',result)
    if error:raise error


def execute(args):
    validate_expected(args.expected)
    require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch'
        and os.environ.get('GITHUB_REPOSITORY')==REPO and os.environ.get('GITHUB_REF')=='refs/heads/main'
        and os.environ.get('GITHUB_WORKFLOW_REF')==REPO+'/.github/workflows/rc-acceptance.yml@refs/heads/main',
        'Only the trusted main hosted dispatch may execute')
    require(os.environ.get('RUNNER_ARCH')=='ARM64','This acceptance scope is ARM64 only')
    root=Path(__file__).resolve().parents[1];run=Run(root,args.output)
    result={'status':'FAILED','expected_rc':args.expected,'scope':{'runtime':RUNTIME,'device_type':DEVICES[args.device],'architecture':'arm64'},
            'limitations':['Hosted Simulator only; no physical device, TestFlight or production StoreKit acceptance.',
                           'Text-only record scenario; no original attachment added.','Human screenshot/AX/PDF review required before acceptance.']}
    primary=None; cleanup_errors=[]; run_id=None
    try:
        head=run.command(['git','rev-parse','HEAD'],'source-head',cap=8).decode().strip()
        require(head==args.harness_sha==os.environ.get('GITHUB_SHA') and re.fullmatch('[0-9a-f]{40}',head),'Harness SHA mismatch')
        require(not run.command(['git','status','--porcelain'],'source-clean',cap=8).strip(),'Harness checkout dirty')
        source={}
        for p in SOURCE_INPUTS:
            raw=regular(root/p,2*MIB); source[p]={'size':len(raw),'sha256':digest(raw)}
        result['harness']={'sha':head,'run_id':os.environ['GITHUB_RUN_ID'],'run_attempt':os.environ['GITHUB_RUN_ATTEMPT'],'files':source}
        gh=run.out/'tools/gh'; gh.parent.mkdir()
        run.command([sys.executable,'scripts/install_release_gh.py','--output',gh],'install-qualified-gh',cap=240,limit=4*MIB)
        gh_manifest=loads(regular(root/'.github/gh/release.json',MIB))
        require(digest(regular(gh,64*MIB))==gh_manifest['artifacts']['macOS_arm64']['binary_sha256'],'Unqualified gh binary')
        rc,client,initial,manifest=download_rc(run,args.expected,str(gh))
        previews=[x for x in manifest['assets'] if x['name'].endswith('-unsigned-simulator.zip')]
        require(len(previews)==1,'Expected one unsigned Simulator ZIP')
        asset=previews[0];preview=regular(run.out/'payload'/asset['name']);require(digest(preview)==asset['sha256'],'Preview changed')
        aut_inventory=extract_preview(preview,run.out/'extracted',manifest['version'])
        save(run.out/'downloaded-app-inventory.json',aut_inventory)
        aut=run.out/'extracted/RoomInventory.app'
        archs=run.command(['lipo','-archs',aut/'RoomInventory'],'rc-architectures',cap=8).decode().split()
        require(set(archs)=={'arm64','x86_64'} and len(archs)==2,'Expected universal Simulator payload')
        build_metadata=loads(regular(run.out/'payload/preview-build.json',MIB))
        require(build_metadata.get('source_commit')==args.expected['source_sha'] and build_metadata.get('base_version')==manifest['version']
            and build_metadata.get('artifact_kind')=='unsigned-ios-simulator-preview'
            and build_metadata.get('architectures')==' '.join(archs), 'Packaged build metadata mismatch')
        result['packaged_build']=build_metadata
        run_id=str(uuid.uuid4()).upper();result['journey_id']=run_id
        products,runner,plan,build_proof=build_harness(run,run_id)
        result['harness_build']=build_proof
        runtime_info=loads(run.sim('list','runtimes','--json'))
        matching=[x for x in runtime_info['runtimes'] if x.get('identifier')==RUNTIME and x.get('isAvailable') is True]
        require(len(matching)==1,'Required iOS 27.0 runtime unavailable');result['runtime']=matching[0]
        name='RC-'+run_id
        previous_devices=loads(run.sim('list','devices','--json'))
        created=run.sim('create',name,DEVICES[args.device],RUNTIME).decode().strip()
        require(str(uuid.UUID(created)).upper()==created,'Invalid created UUID')
        require(created not in {d['udid'] for group in previous_devices['devices'].values() for d in group}, 'Refusing ownership of a pre-existing device')
        run.device=created;result['device_uuid']=run.device
        result['created_device']=run.claim_created_device(previous_devices,loads(run.sim('list','devices','--json')),created,name,DEVICES[args.device])
        boot_end=time.monotonic()+180
        run.sim('boot',run.device,cap=boot_end-time.monotonic())
        require(time.monotonic()<boot_end,'Boot budget expired')
        run.sim('bootstatus',run.device,'-b',cap=boot_end-time.monotonic())
        require(time.monotonic()<boot_end,'Boot status returned late')
        install_artifacts(run,aut,runner)
        installed=run.container(BUNDLE,'app');same_installed(aut_inventory,inventory(installed))
        save(run.out/'installed-before.json',inventory(installed))
        run.command(['xcodebuild','test-without-building','-xctestrun',plan,'-destination','platform=iOS Simulator,id='+run.device,
            '-only-testing:'+TARGET+'/'+METHOD,'-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1',
            '-collect-test-diagnostics','never','-resultBundlePath',run.out/'Acceptance.xcresult'],
            'test-installed-rc',cap=720,limit=64*MIB)
        same_installed(aut_inventory,inventory(run.container(BUNDLE,'app')))
        save(run.out/'installed-after.json',inventory(installed))
        summary=loads(run.command(['xcrun','xcresulttool','get','test-results','summary','--path',run.out/'Acceptance.xcresult'],'test-summary',cap=45))
        require(summary.get('result')=='Passed' and all(summary.get(k)==v for k,v in {'totalTestCount':1,'passedTests':1,'failedTests':0,'skippedTests':0,'expectedFailures':0}.items()),'Expected one successful native acceptance test')
        configurations=summary.get('devicesAndConfigurations',[])
        require(len(configurations)==1 and configurations[0].get('device',{}).get('deviceId')==run.device,'Result device mismatch')
        save(run.out/'test-summary.json',summary)
        runner_data=run.container(RUNNER,'data');evidence=runner_data/'Documents'/('RC-'+run_id)
        ei=inventory(evidence,count_limit=128,byte_limit=64*MIB)
        journey=loads(regular(evidence/'journey.json',MIB));names=validate_journey(journey,run_id,ei)
        shutil.copytree(evidence,run.out/'ui-evidence');same_installed(ei,inventory(run.out/'ui-evidence',count_limit=128,byte_limit=64*MIB))
        data=run.container(BUNDLE,'data');inv=loads(regular(data/'Library/Application Support/RoomInventory/inventory.json',4*MIB))
        assert_inventory(inv,names,'RC saved notes');save(run.out/'restored-inventory.json',inv)
        folder=saved_folder(run.device,'RC-'+run_id);saved=inventory(folder,count_limit=8,byte_limit=32*MIB)
        files={p:regular(folder/p,24*MIB) for p in saved};checks=validate_exports(files,inv,names,run_id)
        generated_root=data/'tmp/InventoryExports'
        generated=inventory(generated_root,count_limit=16,byte_limit=32*MIB)
        generated_names={'csv':('Inventory-localized.csv','csv'),'pdf':('Inventory.pdf','pdf'),
            'package':('Inventory-package.zip','zip'),'backup':('Inventory.roominventory','roominventory'),
            'cancel-backup':('Inventory.roominventory','roominventory')}
        wanted=Counter((filename,digest(files[f'{kind}-{run_id}.{ext}'])) for kind,(filename,ext) in generated_names.items())
        observed=Counter()
        for p,meta in generated.items():
            parts=PurePosixPath(p).parts;require(len(parts)==2,'Unexpected generated export nesting');uuid.UUID(parts[0])
            observed[(parts[1],meta['sha256'])]+=1
        require(observed==wanted,'Generated/saved export byte multiset mismatch')
        result['generated_exports']=generated
        export_dir=run.out/'exports';export_dir.mkdir()
        for p,raw in files.items():(export_dir/p).write_bytes(raw)
        unpacked=export_dir/'package-contents';unpacked.mkdir()
        for p,(raw,_) in zip_members(files[f'package-{run_id}.zip'],max_files=8,max_bytes=24*MIB).items():(unpacked/p).write_bytes(raw)
        result['export_checks']=checks;result['saved_exports']=saved
        result['ui_evidence']=ei;result['steps']=journey['steps'];result['installed_app_inventory']=aut_inventory
        require(rc.snapshot_identity(rc.release_snapshot(client,args.expected['tag']))==rc.snapshot_identity(initial),'RC changed during exercise')
        for p,v in source.items():require(digest(regular(root/p,2*MIB))==v['sha256'],'Harness source changed')
        require(digest(regular(run.out/'payload'/asset['name']))==asset['sha256'],'RC archive changed')
        result['status']='PASS_HOSTED_RC_EXERCISE_REVIEW_PENDING'
    except BaseException as e:
        primary=e;result['error']=type(e).__name__+': '+str(e)
    finally:
        try:run.close_device()
        except BaseException as e:cleanup_errors.append(type(e).__name__+': '+str(e))
        # Preserve best-effort failure captures without changing the primary verdict.
        if run_id and run.device and not cleanup_errors and not (run.out/'ui-evidence').exists():
            try:
                origin=run.container(RUNNER,'data',cleanup=True)/'Documents'/('RC-'+run_id)
                before=inventory(origin,count_limit=128,byte_limit=64*MIB)
                shutil.copytree(origin,run.out/'ui-evidence')
                same_installed(before,inventory(run.out/'ui-evidence',count_limit=128,byte_limit=64*MIB))
            except Exception as e:result['failure_evidence_error']=type(e).__name__+': '+str(e)
        result['cleanup_errors']=cleanup_errors;result['device_cleanup']=run.device_cleanup;result['operations']=run.commands
        if cleanup_errors:result['status']='FAILED'
        save(run.out/'result.json',result)
    if primary:raise primary
    require(not cleanup_errors,'Device cleanup failed')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--device',choices=DEVICES)
    parser.add_argument('--build-only',action='store_true')
    parser.add_argument('--harness-sha',required=True)
    args=parser.parse_args()
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(AcceptanceError('Cancellation requested')))
    if args.build_only:
        require(args.expected is None and args.device is None,'Build-only does not accept RC/runtime inputs')
        build_only(args)
    else:
        require(args.expected is not None and args.device is not None,'RC inputs and device are required')
        args.expected=loads(regular(args.expected,MIB));execute(args)

if __name__=='__main__':main()
