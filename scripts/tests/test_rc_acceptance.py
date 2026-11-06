"""No network, Xcode or Simulator: adversarial acceptance-input fixtures only."""
import copy
from contextlib import contextmanager
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SCRIPTS))
import rc_acceptance as R

ID='D7CFD74C-28E6-44F0-BAED-4A4E0776E79F'
NAMES={'home':'RC Home D7CFD74C','room':'RC Room D7CFD74C','item':'RC Item D7CFD74C'}

def zipped(entries):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        for name,data,mode in entries:
            i=zipfile.ZipInfo(name);i.external_attr=mode<<16;z.writestr(i,data)
    return buf.getvalue()

def preview(**info_changes):
    info={'CFBundleIdentifier':R.BUNDLE,'CFBundleExecutable':'RoomInventory',
          'CFBundleShortVersionString':'0.1.0','CFBundleSupportedPlatforms':['iPhoneSimulator']}
    info.update(info_changes)
    return zipped([('PREVIEW-README.txt',b'unsigned',stat.S_IFREG|0o644),
        ('RoomInventory.app/Info.plist',plistlib.dumps(info),stat.S_IFREG|0o644),
        ('RoomInventory.app/RoomInventory',b'exact downloaded app bytes',stat.S_IFREG|0o755)])

def plan():
    return {'__xctestrun_metadata__':{'FormatVersion':1},R.TARGET:{
        'BlueprintName':R.TARGET,'IsUITestBundle':True,
        'TestHostPath':'__TESTROOT__/Release-iphonesimulator/'+R.TARGET+'-Runner.app',
        'TestBundlePath':'__TESTHOST__/PlugIns/'+R.TARGET+'.xctest',
        'TestingEnvironmentVariables':{'DYLD_INSERT_LIBRARIES':'__TESTBUNDLE__/Frameworks/libXCTestBundleInject.dylib'}}}

def inventory_fixture():
    item={'id':str(uuid.uuid4()),'name':NAMES['item'],'model':'RC Model','serialNumber':'RC-SERIAL-001',
          'purchasePrice':'USD 123.45','purchaseDate':'2026-01-02','notes':'RC saved notes','attachments':[]}
    return {'schemaVersion':1,'homes':[{'id':str(uuid.uuid4()),'name':NAMES['home'],
        'rooms':[{'id':str(uuid.uuid4()),'name':NAMES['room'],'items':[item]}]}]}

def exports():
    inv=inventory_fixture()
    csv=b'home,room,item,model,serial_number,purchase_price,purchase_date,notes,attachment_id\r\nRC Home D7CFD74C,RC Room D7CFD74C,RC Item D7CFD74C,RC Model,RC-SERIAL-001,USD 123.45,2026-01-02,RC saved notes,\r\n'
    pdf=b'%PDF-1.7\nfixture\n%%EOF\n'
    package=zipped([(n,b,stat.S_IFREG|0o644) for n,b in [('Inventory.csv',csv),('Inventory-localized.csv',csv),('Inventory.pdf',pdf),('README.txt',b'notice')]])
    backup=json.dumps({'format':'com.alvit.roominventory.backup','version':1,'files':{},'inventory':inv}).encode()
    return inv,{f'csv-{ID}.csv':csv,f'pdf-{ID}.pdf':pdf,f'package-{ID}.zip':package,f'backup-{ID}.roominventory':backup,f'cancel-backup-{ID}.roominventory':backup}

class Provenance(unittest.TestCase):
    def setUp(self):
        self.manifest={'source_sha':'a'*40,'run_id':12,'run_attempt':1,'tag':'v0.1.0-rc.1',
                       'assets':[{'name':'preview.zip','size':4,'sha256':R.digest(b'data')}]}
        self.raw=json.dumps(self.manifest).encode()
        self.expected={'tag':'v0.1.0-rc.1','source_sha':'a'*40,'source_tree':'b'*40,'run_id':12,
                       'run_attempt':1,'release_id':8,'manifest_sha256':R.digest(self.raw)}
        self.assets=[{'id':9,'name':'release-manifest.json','size':len(self.raw)}, {'id':10,'name':'preview.zip','size':4}]
    def validate(self):return R.validate_manifest_binding(self.expected,self.manifest,self.raw,{'id':8},self.assets)
    def test_exact_manifest_identity(self):self.assertEqual(set(self.validate()),{'preview.zip'})
    def test_wrong_attempt_and_source_rejected(self):
        for key,bad in [('run_attempt',2),('source_sha','c'*40)]:
            with self.subTest(key=key):
                before=self.expected[key];self.expected[key]=bad
                with self.assertRaises(R.AcceptanceError):self.validate()
                self.expected[key]=before
    def test_missing_or_boolean_id_rejected(self):
        for bad in [None,True,0,'12']:
            self.expected['run_id']=bad
            with self.assertRaises(R.AcceptanceError):self.validate()
    def test_manifest_checksum_and_release_id(self):
        self.expected['manifest_sha256']='0'*64
        with self.assertRaises(R.AcceptanceError):self.validate()
        self.expected['manifest_sha256']=R.digest(self.raw);self.expected['release_id']=99
        with self.assertRaises(R.AcceptanceError):self.validate()
    def test_unexpected_or_missing_asset_inventory(self):
        self.assets.append({'id':11,'name':'surprise','size':1})
        with self.assertRaises(R.AcceptanceError):self.validate()
        self.assets=self.assets[:1]
        with self.assertRaises(R.AcceptanceError):self.validate()
    def test_truncated_advertised_asset(self):
        self.assets[1]['size']=3
        with self.assertRaises(R.AcceptanceError):self.validate()
    def test_incomplete_binary_with_correct_metadata_is_rejected(self):
        expected={'size':4,'sha256':R.digest(b'data')}
        R.verify_payload(expected,b'data')
        for raw in [b'dat',b'datax',b'DATA']:
            with self.assertRaises(R.AcceptanceError):R.verify_payload(expected,raw)
    def test_duplicate_json_and_nonfinite_denied(self):
        for raw in ['{"id":1,"id":1}','{"id":NaN}']:
            with self.assertRaises(R.AcceptanceError):R.loads(raw)
    def test_readonly_denies_write_and_does_not_retry_error(self):
        class Base:pass
        class RC:GitHub=Base;API_PATHS={'GET':[r'actions/runs/\d+']}
        class Run:
            calls=0
            def command(self,*a,**k):
                self.calls+=1;raise R.AcceptanceError('HTTP 403 from fixture')
        run=Run();client=R.readonly_client(RC,run,'gh')
        with self.assertRaises(R.AcceptanceError):client.request('actions/runs/12',method='POST')
        self.assertEqual(run.calls,0)
        with self.assertRaises(R.AcceptanceError):client.request('actions/runs/12')
        self.assertEqual(run.calls,1)

class ArchiveAndInstalledAUT(unittest.TestCase):
    def test_exact_preview_then_installed_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'extract';before=R.extract_preview(preview(),root,'0.1.0')
            R.same_installed(before,R.inventory(root/'RoomInventory.app'))
            (root/'RoomInventory.app/RoomInventory').write_bytes(b'rebuilt app')
            with self.assertRaises(R.AcceptanceError):R.same_installed(before,R.inventory(root/'RoomInventory.app'))
    def test_unsafe_absolute_parent_and_symlink_paths(self):
        for name,mode in [('../escape',stat.S_IFREG),('/escape',stat.S_IFREG),('link',stat.S_IFLNK),('a//b',stat.S_IFREG)]:
            with self.subTest(name=name):
                with self.assertRaises(R.AcceptanceError):R.zip_members(zipped([(name,b'x',mode|0o644)]))
    def test_casefold_duplicate_and_file_parent_collision(self):
        for names in [('A','a'),('a','a/b'),('a/b','a')]:
            with self.assertRaises(R.AcceptanceError):R.zip_members(zipped([(n,b'x',stat.S_IFREG|0o644) for n in names]))
    def test_truncated_zip_never_extracts_successfully(self):
        with self.assertRaises(zipfile.BadZipFile):R.zip_members(preview()[:-10])
    def test_size_cap_and_wrong_platform(self):
        with self.assertRaises(R.AcceptanceError):R.zip_members(preview(),max_bytes=3)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(R.AcceptanceError):R.extract_preview(preview(CFBundleSupportedPlatforms=['iPhoneOS']),Path(d)/'out','0.1.0')
    def test_existing_destination_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            sentinel=Path(d)/'sentinel';sentinel.write_bytes(b'preserve')
            with self.assertRaises(FileExistsError):R.extract_preview(preview(),Path(d),'0.1.0')
            self.assertEqual(sentinel.read_bytes(),b'preserve')
    def test_inventory_rejects_symlink_and_extra_installed_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'original').write_bytes(b'a');base=R.inventory(root)
            (root/'extra').write_bytes(b'x')
            with self.assertRaises(R.AcceptanceError):R.same_installed(base,R.inventory(root))
            (root/'extra').unlink();(root/'link').symlink_to(root/'original')
            with self.assertRaises(R.AcceptanceError):R.inventory(root)

class ExternalAUT(unittest.TestCase):
    def test_preinstalled_mode_removes_all_install_paths(self):
        p=R.destination_xctestrun(plistlib.dumps(plan()),{'CFBundleIdentifier':R.RUNNER},ID)
        target=plistlib.loads(p)[R.TARGET]
        self.assertIs(target['UseDestinationArtifacts'],True)
        self.assertFalse({'TestHostPath','TestBundlePath','UITargetAppPath'}&set(target))
        self.assertEqual(target['UITargetAppBundleIdentifier'],R.BUNDLE)
        self.assertEqual(target['OnlyTestIdentifiers'],[R.METHOD])
        self.assertEqual(target['EnvironmentVariables'],{'RC_ACCEPTANCE_ID':ID})
    def test_app_dependency_is_rejected(self):
        p=plan();p[R.TARGET]['UITargetAppPath']='__TESTROOT__/rebuilt/RoomInventory.app'
        with self.assertRaises(R.AcceptanceError):R.destination_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)
    def test_wrong_runner_and_added_target_rejected(self):
        with self.assertRaises(R.AcceptanceError):R.destination_xctestrun(plistlib.dumps(plan()),{'CFBundleIdentifier':'other'},ID)
        p=plan();p['OtherTarget']={}
        with self.assertRaises(R.AcceptanceError):R.destination_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)
    def test_format_two_also_requires_one_target(self):
        p={'__xctestrun_metadata__':{'FormatVersion':2},'TestConfigurations':[{'TestTargets':[plan()[R.TARGET]],'IsEnabled':True}]}
        R.destination_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)
        p['TestConfigurations'][0]['TestTargets'].append(copy.deepcopy(plan()[R.TARGET]))
        with self.assertRaises(R.AcceptanceError):R.destination_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)

class Evidence(unittest.TestCase):
    def setUp(self):
        self.j={'schema_version':1,'run_id':ID,'status':'complete','bundle_id':R.BUNDLE,
                'aut_launch_arguments':['-AppleLanguages','(en)','-AppleLocale','en_US'],'aut_launch_environment':{},
                'steps':R.STEPS.copy(),'restore_confirm_count':1,'restore_cancel_count':1,'names':NAMES}
        self.e={n+ext:{'size':100} for n in R.STEPS for ext in ['.png','.txt']}
    def test_complete_journey_requires_every_checkpoint(self):
        self.assertEqual(R.validate_journey(self.j,ID,self.e),NAMES)
        self.e.pop('restored-relaunch.png')
        with self.assertRaises(R.AcceptanceError):R.validate_journey(self.j,ID,self.e)
    def test_wrong_id_missing_step_and_repeated_restore_rejected(self):
        for key,value in [('run_id',str(uuid.uuid4())),('steps',R.STEPS[:-1]),('restore_confirm_count',2)]:
            before=self.j[key];self.j[key]=value
            with self.assertRaises(R.AcceptanceError):R.validate_journey(self.j,ID,self.e)
            self.j[key]=before
    def test_debug_reset_or_pro_injection_rejected(self):
        self.j['aut_launch_environment']={'UITEST_RUN_ID':ID}
        with self.assertRaises(R.AcceptanceError):R.validate_journey(self.j,ID,self.e)
    def test_exported_backup_really_matches_restored_state(self):
        inv,files=exports();self.assertTrue(R.validate_exports(files,inv,NAMES,ID)['backup_inventory_equal'])
        inv['homes'][0]['rooms'][0]['items'][0]['notes']='RC MUTATED'
        with self.assertRaises(R.AcceptanceError):R.validate_exports(files,inv,NAMES,ID)
    def test_cancelled_restore_must_preserve_complete_backup(self):
        inv,files=exports();changed=json.loads(files[f'cancel-backup-{ID}.roominventory'])
        changed['inventory']['homes'][0]['id']=str(uuid.uuid4())
        files[f'cancel-backup-{ID}.roominventory']=json.dumps(changed).encode()
        with self.assertRaises(R.AcceptanceError):R.validate_exports(files,inv,NAMES,ID)
    def test_missing_backup_or_incorrect_csv_rejected(self):
        inv,files=exports();files.pop(f'backup-{ID}.roominventory')
        with self.assertRaises(R.AcceptanceError):R.validate_exports(files,inv,NAMES,ID)
        inv,files=exports();files[f'csv-{ID}.csv']+=b'tamper'
        with self.assertRaises(R.AcceptanceError):R.validate_exports(files,inv,NAMES,ID)

class BuildHarnessOnly(unittest.TestCase):
    def fixture(self, root, extra=False):
        class Run:
            def __init__(self):self.root=SCRIPTS.parent;self.out=root;self.commands=[]
            def command(self,argv,name,**kwargs):
                self.commands.append([str(x) for x in argv])
                return {'xcode-version':b'Xcode 27.1\nBuild version 27A9275\n',
                        'architecture':b'arm64\n','xcodegen-install':b'/fixture/xcodegen\n'}.get(name,b'')
        run=Run();products=root/'DerivedData/Build/Products'
        runner=products/('Release-iphonesimulator/'+R.TARGET+'-Runner.app');runner.mkdir(parents=True)
        (runner/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':R.RUNNER}))
        (products/'generated.xctestrun').write_bytes(plistlib.dumps(plan()))
        if extra:(products/'Release-iphonesimulator/RoomInventory.app').mkdir()
        return run
    def test_build_shape_validation_never_installs_or_runs(self):
        with tempfile.TemporaryDirectory() as d:
            run=self.fixture(Path(d));_,_,_,proof=R.build_harness(run,ID)
            self.assertIs(proof['test_executed'],False);self.assertIs(proof['application_built'],False)
            self.assertTrue(any('build-for-testing' in c for c in run.commands))
            self.assertFalse(any('simctl' in c or 'test-without-building' in c for c in run.commands))
    def test_project_destination_exists_before_generator_is_invoked(self):
        with tempfile.TemporaryDirectory() as d:
            run=self.fixture(Path(d));command=run.command;observed=[]
            self.assertFalse((run.out/'project').exists())
            def checked_command(argv,name,**kwargs):
                if name=='generate':
                    destination=Path(argv[argv.index('--project')+1])
                    self.assertEqual(destination,run.out/'project')
                    self.assertTrue(destination.is_dir())
                    self.assertFalse(destination.is_symlink())
                    observed.append(destination)
                return command(argv,name,**kwargs)
            run.command=checked_command
            R.build_harness(run,ID)
            self.assertEqual(observed,[run.out/'project'])
    def test_external_project_resolves_all_six_checkout_sources(self):
        with tempfile.TemporaryDirectory(prefix='rc build output ') as d:
            run=self.fixture(Path(d).resolve());command=run.command;observed=[]
            expected={p for p in R.SOURCE_INPUTS if p.endswith('.swift')}
            self.assertEqual(len(expected),6)
            def checked_command(argv,name,**kwargs):
                if name=='generate':
                    spec=Path(argv[argv.index('--spec')+1])
                    base=Path(argv[argv.index('--project-root')+1])
                    destination=Path(argv[argv.index('--project')+1])
                    self.assertEqual(spec,run.root/'Acceptance/RC/project.yml')
                    self.assertTrue(spec.is_absolute());self.assertEqual(base,run.root)
                    entries={line.removeprefix('      - ') for line in spec.read_text().splitlines()
                             if line.startswith('      - ')}
                    self.assertEqual(entries,expected)
                    for entry in entries:
                        source=base/entry
                        self.assertTrue(source.is_file())
                        self.assertNotEqual(source.parent,base)
                        # XcodeGen 2.46 emits a parent group relative to --project
                        # for these non-root sources, followed by the file basename.
                        group=os.path.relpath(source.parent,destination)
                        resolved=(destination/group/source.name).resolve()
                        self.assertEqual(resolved,source.resolve())
                        self.assertEqual(resolved.read_bytes(),(run.root/entry).read_bytes())
                    observed.append(entries)
                return command(argv,name,**kwargs)
            run.command=checked_command
            R.build_harness(run,ID)
            self.assertEqual(observed,[expected])
    def test_rebuilt_aut_product_fails_before_exercise(self):
        with tempfile.TemporaryDirectory() as d:
            run=self.fixture(Path(d),extra=True)
            with self.assertRaises(R.AcceptanceError):R.build_harness(run,ID)
            self.assertFalse(any('simctl' in c for c in run.commands))

class DeviceOwnership(unittest.TestCase):
    def test_exact_fresh_device_only(self):
        before={'devices':{R.RUNTIME:[]}}
        device={'udid':ID,'name':'RC-'+ID,'deviceTypeIdentifier':R.DEVICES['iphone'],'state':'Shutdown'}
        after={'devices':{R.RUNTIME:[device]}}
        self.assertEqual(R.validate_created_device(before,after,ID,'RC-'+ID,R.DEVICES['iphone']),device)
        with self.assertRaises(R.AcceptanceError):R.validate_created_device(after,after,ID,'RC-'+ID,R.DEVICES['iphone'])
    def test_wrong_runtime_or_type_cannot_be_claimed(self):
        before={'devices':{}}
        device={'udid':ID,'name':'RC-'+ID,'deviceTypeIdentifier':R.DEVICES['ipad'],'state':'Shutdown'}
        for after in [{'devices':{'other':[device]}},{'devices':{R.RUNTIME:[device]}}]:
            with self.assertRaises(R.AcceptanceError):R.validate_created_device(before,after,ID,'RC-'+ID,R.DEVICES['iphone'])

class OwnedDeviceCleanup(unittest.TestCase):
    def fixture(self, root):
        run=R.Run(root,root/'out');run.device=ID
        device={'udid':ID,'name':'RC-'+ID,'deviceTypeIdentifier':R.DEVICES['iphone'],'state':'Shutdown'}
        run.claim_created_device({'devices':{R.RUNTIME:[]}},
            {'devices':{R.RUNTIME:[device]}},ID,'RC-'+ID,R.DEVICES['iphone'])
        return run,device
    def commands(self, run, responses):
        calls=[]
        def sim(*args,**kwargs):
            calls.append((args,kwargs));response=responses.pop(0)
            if isinstance(response,Exception):raise response
            return json.dumps(response).encode() if isinstance(response,dict) else response
        run.sim=sim
        return calls
    def test_initial_census_error_still_shuts_down_only_owned_uuid(self):
        with tempfile.TemporaryDirectory() as d:
            run,device=self.fixture(Path(d))
            calls=self.commands(run,[R.AcceptanceError('census stalled'),b'',{'devices':{R.RUNTIME:[device]}}])
            with self.assertRaisesRegex(R.AcceptanceError,'initial census.*census stalled'):run.close_device()
            self.assertEqual([c[0] for c in calls],[('list','devices','--json'),('shutdown',ID),('list','devices','--json')])
            self.assertEqual(run.device_cleanup['state'],'Shutdown')
            self.assertEqual(len(run.device_cleanup['errors']),1)
            self.assertTrue(all(c[1]['cleanup'] for c in calls))
    def test_missing_or_changed_ownership_never_calls_simctl(self):
        for change in ['unclaimed','uuid','receipt']:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                run,device=self.fixture(Path(d));calls=self.commands(run,[])
                if change=='unclaimed':run.owned_device=None
                elif change=='uuid':run.device=str(uuid.uuid4()).upper()
                else:(run.out/'owned-device.json').write_text('{}')
                with self.assertRaisesRegex(R.AcceptanceError,'ownership'):run.close_device()
                self.assertEqual(calls,[])
                self.assertEqual(run.device_cleanup['state'],'unproved')
    def test_identity_conflict_blocks_shutdown_even_if_final_read_recovers(self):
        for field,value in [('name','foreign'),('deviceTypeIdentifier',R.DEVICES['ipad'])]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
                run,device=self.fixture(Path(d));changed=dict(device);changed[field]=value
                calls=self.commands(run,[{'devices':{R.RUNTIME:[changed]}},{'devices':{R.RUNTIME:[device]}}])
                with self.assertRaisesRegex(R.AcceptanceError,'initial identity'):run.close_device()
                self.assertEqual([c[0][0] for c in calls],['list','list'])
                self.assertFalse(run.device_cleanup['shutdown_requested'])
    def test_already_shutdown_is_independently_verified_without_shutdown(self):
        with tempfile.TemporaryDirectory() as d:
            run,device=self.fixture(Path(d));snapshot={'devices':{R.RUNTIME:[device]}}
            calls=self.commands(run,[snapshot,snapshot]);run.close_device()
            self.assertEqual([c[0][0] for c in calls],['list','list'])
            self.assertEqual(run.device_cleanup['state'],'Shutdown')
            self.assertEqual(run.device_cleanup['errors'],[])
    def test_shutdown_failure_does_not_skip_final_verification(self):
        with tempfile.TemporaryDirectory() as d:
            run,device=self.fixture(Path(d));booted=dict(device,state='Booted')
            calls=self.commands(run,[{'devices':{R.RUNTIME:[booted]}},R.AcceptanceError('shutdown stalled'),{'devices':{R.RUNTIME:[device]}}])
            with self.assertRaisesRegex(R.AcceptanceError,'shutdown.*shutdown stalled'):run.close_device()
            self.assertEqual([c[0][0] for c in calls],['list','shutdown','list'])
            self.assertEqual(run.device_cleanup['state'],'Shutdown')
            self.assertEqual(len(run.device_cleanup['errors']),1)
    def test_failed_final_state_is_never_called_shutdown(self):
        for final in [R.AcceptanceError('verification stalled'),{'devices':{}},
                      {'devices':{R.RUNTIME:[{'udid':ID,'name':'foreign'}]}}]:
            with self.subTest(final=final),tempfile.TemporaryDirectory() as d:
                run,device=self.fixture(Path(d));booted=dict(device,state='Booted')
                self.commands(run,[{'devices':{R.RUNTIME:[booted]}},b'',final])
                with self.assertRaisesRegex(R.AcceptanceError,'final verification'):run.close_device()
                self.assertEqual(run.device_cleanup['state'],'unproved')
    def test_cleanup_uses_one_deadline_and_stops_admitting_commands(self):
        for first_duration,expected_calls in [(31,3),(90,1)]:
            with self.subTest(first_duration=first_duration),tempfile.TemporaryDirectory() as d:
                run,device=self.fixture(Path(d));now=[0.0];calls=[]
                def capture(argv,**kwargs):
                    calls.append((argv,kwargs['timeout']))
                    if len(calls)==1:
                        now[0]+=first_duration
                        raise R.AcceptanceError('census stalled')
                    if argv[2]=='shutdown':now[0]+=31;return b''
                    return json.dumps({'devices':{R.RUNTIME:[device]}}).encode()
                with patch.object(R.time,'monotonic',side_effect=lambda:now[0]),patch.object(R,'bounded_capture',side_effect=capture):
                    with self.assertRaisesRegex(R.AcceptanceError,'initial census'):run.close_device()
                self.assertEqual(run.cleanup_end,90)
                self.assertEqual(len(calls),expected_calls)
                if expected_calls==3:
                    self.assertEqual([c[1] for c in calls],[30,30,24])
                    self.assertEqual(run.device_cleanup['state'],'Shutdown')
                else:
                    self.assertEqual(run.device_cleanup['state'],'unproved')
                    self.assertTrue(run.device_cleanup['shutdown_requested'])
                    self.assertEqual([c[0][2] for c in calls],['list'])
    def test_execute_keeps_primary_error_and_records_cleanup_error(self):
        primary=R.AcceptanceError('original install failure')
        cleanup=R.AcceptanceError('initial census failure; final state unproved')
        expected={'tag':'v0.1.0-rc.1','source_sha':'a'*40,'source_tree':'b'*40,
                  'run_id':12,'run_attempt':1,'release_id':8,'manifest_sha256':'c'*64}
        env={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
             'GITHUB_REPOSITORY':R.REPO,'GITHUB_REF':'refs/heads/main','RUNNER_ARCH':'ARM64',
             'GITHUB_WORKFLOW_REF':R.REPO+'/.github/workflows/rc-acceptance.yml@refs/heads/main'}
        with tempfile.TemporaryDirectory() as d:
            args=R.argparse.Namespace(expected=expected,harness_sha='a'*40,device='iphone',output=Path(d)/'out')
            with patch.dict(os.environ,env),patch.object(R.Run,'command',side_effect=primary),patch.object(R.Run,'close_device',side_effect=cleanup):
                with self.assertRaises(R.AcceptanceError) as caught:R.execute(args)
            self.assertIs(caught.exception,primary)
            result=json.loads((args.output/'result.json').read_bytes())
            self.assertEqual(result['status'],'FAILED')
            self.assertEqual(result['error'],'AcceptanceError: original install failure')
            self.assertEqual(result['cleanup_errors'],['AcceptanceError: initial census failure; final state unproved'])


class InstallationWindow(unittest.TestCase):
    @contextmanager
    def fixture(self, durations, start=0):
        # Exercise the real command admission and capture deadlines without
        # starting simctl; process/pipe cleanup behavior has separate fixtures.
        import rc_acceptance_process as P
        now=[0.0];calls=[]
        def spawn(argv, **kwargs):
            duration=durations[len(calls)]
            process=Mock(pid=1000+len(calls),returncode=None)
            def poll():
                now[0]+=duration;process.returncode=0;return 0
            process.poll.side_effect=poll
            calls.append(list(argv))
            return process
        selector=Mock();selector.get_map.return_value={}
        with tempfile.TemporaryDirectory() as d, \
                patch.object(P.time,'monotonic',side_effect=lambda:now[0]), \
                patch.object(P.subprocess,'Popen',side_effect=spawn), \
                patch.object(P.selectors,'DefaultSelector',return_value=selector), \
                patch.object(P.os,'set_blocking'), \
                patch.object(P,'kill_owned',return_value={'success':True}):
            run=R.Run(d,Path(d)/'out');run.device=ID;now[0]=start
            yield run,now,calls

    def test_aut_can_cross_sixty_seconds_then_runner_keeps_its_cap(self):
        for duration in [72,89.999]:
            with self.subTest(duration=duration),self.fixture([duration,1]) as (run,now,calls):
                R.install_artifacts(run,'exact-rc.app','standalone-runner.app')
                self.assertEqual(calls,[['xcrun','simctl','install',ID,'exact-rc.app'],
                                        ['xcrun','simctl','install',ID,'standalone-runner.app']])
                self.assertEqual([c['timeout_seconds'] for c in run.commands],[90,60])
                self.assertTrue(all(c['cleanup_reserved_seconds']==4 for c in run.commands))
                self.assertEqual(run.end,1800)
                self.assertIsNone(run.cleanup_end)

    def test_aut_at_or_after_ninety_never_installs_runner_or_retries(self):
        from rc_acceptance_process import CaptureFailure
        for duration in [90,91]:
            with self.subTest(duration=duration),self.fixture([duration]) as (run,now,calls):
                with self.assertRaisesRegex(CaptureFailure,'completed after work deadline'):
                    R.install_artifacts(run,'exact-rc.app','standalone-runner.app')
                self.assertEqual(len(calls),1)
                self.assertEqual(run.commands[0]['timeout_seconds'],90)
                self.assertEqual(run.commands[0]['elapsed_seconds'],duration)

    def test_runner_at_sixty_still_fails_without_retry(self):
        from rc_acceptance_process import CaptureFailure
        with self.fixture([72,60]) as (run,now,calls):
            with self.assertRaisesRegex(CaptureFailure,'completed after work deadline'):
                R.install_artifacts(run,'exact-rc.app','standalone-runner.app')
            self.assertEqual(len(calls),2)
            self.assertEqual([c['timeout_seconds'] for c in run.commands],[90,60])

    def test_parent_deadline_clips_both_installs_without_renewal(self):
        with self.fixture([20,5],start=1770) as (run,now,calls):
            R.install_artifacts(run,'exact-rc.app','standalone-runner.app')
            self.assertEqual([c['timeout_seconds'] for c in run.commands],[26,6])
            self.assertEqual(now[0],1795)
            self.assertEqual(run.end,1800)
            self.assertIsNone(run.cleanup_end)

    def test_parent_expiry_never_admits_another_install(self):
        from rc_acceptance_process import CaptureFailure
        with self.fixture([26],start=1770) as (run,now,calls):
            with self.assertRaises(CaptureFailure):
                R.install_artifacts(run,'exact-rc.app','standalone-runner.app')
            self.assertEqual(len(calls),1)
            self.assertEqual(run.commands[0]['timeout_seconds'],26)
        with self.fixture([],start=1796) as (run,now,calls):
            with self.assertRaisesRegex(R.AcceptanceError,'Overall acceptance deadline'):
                R.install_artifacts(run,'exact-rc.app','standalone-runner.app')
            self.assertEqual(calls,[])
            self.assertEqual(run.commands,[])

class ProcessEvidence(unittest.TestCase):
    def test_failed_child_retains_bounded_streams_and_is_reaped(self):
        from rc_acceptance_process import bounded_capture,CaptureFailure
        with tempfile.TemporaryDirectory() as d:
            o,e=Path(d)/'out',Path(d)/'err';receipt={}
            with self.assertRaises(CaptureFailure):
                bounded_capture([sys.executable,'-c','import sys; print("before failure"); print("cause",file=sys.stderr); sys.exit(2)'],
                    timeout=3,limit=1024,receipt=receipt,stdout_path=o,stderr_path=e)
            self.assertIn(b'before failure',o.read_bytes());self.assertIn(b'cause',e.read_bytes())
            self.assertTrue(receipt['cleanup']['success']);self.assertTrue(receipt['cleanup']['leader_reaped'])
            self.assertEqual(receipt['cleanup']['group_state'],'absent')

if __name__=='__main__':unittest.main(verbosity=2)
