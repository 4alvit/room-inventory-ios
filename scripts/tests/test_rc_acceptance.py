"""No network, Xcode or Simulator: adversarial acceptance-input fixtures only."""
import copy
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
