"""No network, Xcode or Simulator: adversarial acceptance-input fixtures only."""
import copy
import ast
from contextlib import contextmanager
import importlib.util
import inspect
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
    # Exact standalone descriptor emitted by Xcode 27.1 (27A9275). It contains
    # runner-only relative paths and no machine paths, credentials or RC data.
    return plistlib.loads((SCRIPTS/'tests/fixtures/rc-generated-simulator.xctestrun').read_bytes())

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
    def test_captured_simulator_descriptor_preserves_runner_paths_and_testing_environment(self):
        generated=plan()[R.TARGET]
        p=R.simulator_xctestrun(plistlib.dumps(plan()),{'CFBundleIdentifier':R.RUNNER},ID)
        target=plistlib.loads(p)[R.TARGET]
        for key in ('TestHostPath','TestBundlePath','DependentProductPaths','TestingEnvironmentVariables',
                    'TestHostBundleIdentifier','UseUITargetAppProvidedByTests'):
            self.assertEqual(target[key],generated[key])
        self.assertFalse({'UseDestinationArtifacts','TestBundleDestinationRelativePath',
                          'UITargetAppPath','UITargetAppBundleIdentifier'}&set(target))
        self.assertEqual(target['OnlyTestIdentifiers'],[R.METHOD])
        self.assertEqual(target['EnvironmentVariables'],{'RC_ACCEPTANCE_ID':ID})
        self.assertEqual(target['UITargetAppEnvironmentVariables'],{})
        self.assertEqual(target['UITargetAppCommandLineArguments'],[])
    def test_device_only_mode_or_missing_test_provided_aut_rejected(self):
        for key,value in [('UseDestinationArtifacts',True),
                          ('TestBundleDestinationRelativePath','__TESTHOST__/PlugIns/'+R.TARGET+'.xctest'),
                          ('UseUITargetAppProvidedByTests',False),('UseUITargetAppProvidedByTests',None)]:
            with self.subTest(key=key,value=value):
                p=plan()
                if value is None:p[R.TARGET].pop(key)
                else:p[R.TARGET][key]=value
                with self.assertRaises(R.AcceptanceError):
                    R.simulator_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)
    def test_foreign_missing_or_duplicate_build_dependency_rejected(self):
        expected=plan()[R.TARGET]['DependentProductPaths']
        for dependencies in [None,[],expected[:1],expected+[expected[0]],expected+[{'path':'bad'}],
                             [expected[0],'__TESTROOT__/RoomInventory.app']]:
            with self.subTest(dependencies=dependencies):
                p=plan()
                if dependencies is None:p[R.TARGET].pop('DependentProductPaths')
                else:p[R.TARGET]['DependentProductPaths']=dependencies
                with self.assertRaises(R.AcceptanceError):
                    R.simulator_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)
    def test_foreign_runner_roots_or_bundle_identity_rejected(self):
        for key,value in [('TestHostPath','/other/'+R.TARGET+'-Runner.app'),
                          ('TestBundlePath','/other/PlugIns/'+R.TARGET+'.xctest'),
                          ('TestHostBundleIdentifier','other'),('UITargetAppBundleIdentifier',R.BUNDLE)]:
            with self.subTest(key=key):
                p=plan();p[R.TARGET][key]=value
                with self.assertRaises(R.AcceptanceError):
                    R.simulator_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)
    def test_app_dependency_is_rejected(self):
        p=plan();p[R.TARGET]['UITargetAppPath']='__TESTROOT__/rebuilt/RoomInventory.app'
        with self.assertRaises(R.AcceptanceError):R.simulator_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)
    def test_wrong_runner_and_added_target_rejected(self):
        with self.assertRaises(R.AcceptanceError):R.simulator_xctestrun(plistlib.dumps(plan()),{'CFBundleIdentifier':'other'},ID)
        p=plan();p['OtherTarget']={}
        with self.assertRaises(R.AcceptanceError):R.simulator_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)
    def test_format_two_also_requires_one_target(self):
        p={'__xctestrun_metadata__':{'FormatVersion':2},'TestConfigurations':[{'TestTargets':[plan()[R.TARGET]],'IsEnabled':True}]}
        configured=plistlib.loads(R.simulator_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID))
        target=configured['TestConfigurations'][0]['TestTargets'][0]
        self.assertEqual(target['TestHostPath'],plan()[R.TARGET]['TestHostPath'])
        self.assertIs(target['UseUITargetAppProvidedByTests'],True)
        self.assertNotIn('UseDestinationArtifacts',target)
        p['TestConfigurations'][0]['TestTargets'].append(copy.deepcopy(plan()[R.TARGET]))
        with self.assertRaises(R.AcceptanceError):R.simulator_xctestrun(plistlib.dumps(p),{'CFBundleIdentifier':R.RUNNER},ID)

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
    def test_executable_descriptor_keeps_original_products_root_not_evidence_copy(self):
        with tempfile.TemporaryDirectory(prefix='rc build output ') as d:
            run=self.fixture(Path(d));products,runner,configured,proof=R.build_harness(run,ID)
            original=products/'generated.xctestrun'
            self.assertEqual(configured.parent,original.parent)
            self.assertNotEqual(configured,run.out/'configured.xctestrun')
            self.assertEqual(configured.read_bytes(),(run.out/'configured.xctestrun').read_bytes())
            target=plistlib.loads(configured.read_bytes())[R.TARGET]
            host=Path(target['TestHostPath'].replace('__TESTROOT__',str(configured.parent)))
            bundle=Path(target['TestBundlePath'].replace('__TESTHOST__',str(host)))
            self.assertEqual(host,runner)
            self.assertEqual(bundle,runner/'PlugIns'/f'{R.TARGET}.xctest')
            self.assertEqual({Path(p.replace('__TESTROOT__',str(configured.parent)))
                              for p in target['DependentProductPaths']},{host,bundle})
            self.assertEqual(proof['test_root'],str(products.relative_to(run.out)))
            self.assertEqual(proof['configured_xctestrun'],str(configured.relative_to(run.out)))
            self.assertEqual(proof['mode'],'SimulatorRunnerWithPreinstalledAUT')
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
        for record_failure,output_error in [(False,None),(True,None),(True,OSError('closed output')),(True,ValueError('unavailable output'))]:
            def command(run,*args,**kwargs):
                if record_failure:run.commands.append({'command':['private-gh','api','private-endpoint'],'returncode':7,'error':'private primary error'})
                raise primary
            def cleanup_command(run):
                if record_failure:run.commands.append({'command':['xcrun','simctl','list','devices'],'error':'private cleanup error'})
                raise cleanup
            with self.subTest(record_failure=record_failure,output_error=output_error),tempfile.TemporaryDirectory() as d:
                args=R.argparse.Namespace(expected=expected,harness_sha='a'*40,device='iphone',output=Path(d)/'out')
                with patch.dict(os.environ,env),patch.object(R.Run,'command',new=command), \
                        patch.object(R.Run,'close_device',autospec=True,side_effect=cleanup_command) as close, \
                        patch('builtins.print',side_effect=output_error) as output:
                    with self.assertRaises(R.AcceptanceError) as caught:R.execute(args)
                self.assertIs(caught.exception,primary);close.assert_called_once()
                result=json.loads((args.output/'result.json').read_bytes())
                self.assertEqual(result['status'],'FAILED')
                self.assertEqual(result['error'],'AcceptanceError: original install failure')
                self.assertEqual(result['cleanup_errors'],['AcceptanceError: initial census failure; final state unproved'])
                output.assert_called_once()
                marker,summary=output.call_args.args[0].split(' ',1)
                self.assertEqual(marker,'ROOM_RC_FAILURE_V1')
                self.assertTrue(json.loads(summary)['cleanup_failed'])
                self.assertNotIn('original install failure',summary)
                self.assertEqual(json.loads(summary)['operation_index'],1 if record_failure else None)
                self.assertEqual(json.loads(summary)['phase'],'github-read' if record_failure else 'controller')
                self.assertNotIn('private',summary)


class InstallationWindow(unittest.TestCase):
    @contextmanager
    def fixture(self, durations, start=0, cleanup_durations=None, returncodes=None):
        # Exercise the real command admission and capture deadlines without
        # starting simctl; process/pipe cleanup behavior has separate fixtures.
        import rc_acceptance_process as P
        now=[0.0];calls=[]
        def spawn(argv, **kwargs):
            index=len(calls);duration=durations[index]
            process=Mock(pid=1000+index,returncode=None)
            def poll():
                now[0]+=duration
                process.returncode=0 if returncodes is None else returncodes[index]
                return process.returncode
            process.poll.side_effect=poll
            calls.append(list(argv))
            return process
        def cleanup(process, deadline, *, state):
            # A controlled cleanup delay also exercises the phase postcheck,
            # which must reject a timely child whose capture returns late.
            if cleanup_durations is not None:now[0]+=cleanup_durations[process.pid-1000]
            return {'success':True}
        selector=Mock();selector.get_map.return_value={}
        with tempfile.TemporaryDirectory() as d, \
                patch.object(P.time,'monotonic',side_effect=lambda:now[0]), \
                patch.object(P.subprocess,'Popen',side_effect=spawn), \
                patch.object(P.selectors,'DefaultSelector',return_value=selector), \
                patch.object(P.os,'set_blocking'), \
                patch.object(P,'kill_owned',side_effect=cleanup):
            run=R.Run(d,Path(d)/'out');run.device=ID;now[0]=start
            yield run,now,calls

    def test_slow_boot_or_install_shares_original_total_with_one_aut_install(self):
        for durations,start in [([2,200,100],0),([2,50,295],0),([2,200,100],400)]:
            with self.subTest(durations=durations,start=start),self.fixture(durations,start=start) as (run,now,calls):
                R.setup_application(run,'exact-rc.app')
                self.assertEqual(calls,[['xcrun','simctl','boot',ID],
                    ['xcrun','simctl','bootstatus',ID,'-b'],['xcrun','simctl','install',ID,'exact-rc.app']])
                self.assertEqual([c['timeout_seconds'] for c in run.commands],
                    [476,476-durations[0],476-sum(durations[:2])])
                self.assertTrue(all(c['cleanup_reserved_seconds']==4 for c in run.commands))
                self.assertTrue(all(c['work_deadline_monotonic']==start+476 for c in run.commands))
                self.assertTrue(all(c['cleanup_deadline_monotonic']==start+480 for c in run.commands))
                self.assertEqual(run.setup_window,dict(start_monotonic=start,end_monotonic=start+480,
                    parent_end_monotonic=1800,maximum_seconds=480,cleanup_per_child_seconds=4,
                    status='COMPLETED',finished_monotonic=start+sum(durations),admissions=[
                        dict(operation=operation,operation_index=index+1,admission_monotonic=start+sum(durations[:index]),
                            granted_seconds=476-sum(durations[:index]),deadline_monotonic=start+480,
                            returned_monotonic=start+sum(durations[:index+1]),status='COMPLETED')
                        for index,operation in enumerate(['boot','bootstatus','install'])]))
                self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)
                with self.assertRaisesRegex(R.AcceptanceError,'not fresh'):
                    R.setup_application(run,'exact-rc.app')
                self.assertEqual(len(calls),3)

    def test_late_child_at_each_stage_never_renews_or_starts_next_action(self):
        from rc_acceptance_process import CaptureFailure
        for durations in [[476],[2,474],[2,200,274]]:
            with self.subTest(durations=durations),self.fixture(durations) as (run,now,calls):
                with self.assertRaisesRegex(CaptureFailure,'completed after work deadline'):
                    R.setup_application(run,'exact-rc.app')
                self.assertEqual(len(calls),len(durations))
                self.assertEqual(run.setup_window['end_monotonic'],480)
                self.assertEqual(run.setup_window['status'],'FAILED')
                self.assertIsNone(run.setup_window['finished_monotonic'])
                self.assertEqual(len(run.setup_window['admissions']),len(durations))
                self.assertIsNone(run.setup_window['admissions'][-1]['returned_monotonic'])
                self.assertEqual(run.setup_window['admissions'][-1]['status'],'STARTED')

    def test_parent_deadline_clips_all_setup_without_renewal(self):
        with self.fixture([2,3,10],start=1770) as (run,now,calls):
            R.setup_application(run,'exact-rc.app')
            self.assertEqual([c['timeout_seconds'] for c in run.commands],[26,24,21])
            self.assertEqual(now[0],1785)
            self.assertEqual(run.setup_window['end_monotonic'],1800)
            self.assertEqual([a['granted_seconds'] for a in run.setup_window['admissions']],[26,24,21])
            self.assertTrue(all(a['deadline_monotonic']==1800 for a in run.setup_window['admissions']))
            self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)

    def test_parent_expiry_blocks_first_admission_or_late_success(self):
        from rc_acceptance_process import CaptureFailure
        with self.fixture([26],start=1770) as (run,now,calls):
            with self.assertRaises(CaptureFailure):R.setup_application(run,'exact-rc.app')
            self.assertEqual(len(calls),1)
            self.assertEqual(run.commands[0]['timeout_seconds'],26)
        for start in [1796,1800,1801]:
            with self.subTest(start=start),self.fixture([],start=start) as (run,now,calls):
                with self.assertRaisesRegex(R.AcceptanceError,'Simulator setup deadline'):
                    R.setup_application(run,'exact-rc.app')
                self.assertEqual(calls,[]);self.assertEqual(run.commands,[])
                self.assertEqual(run.setup_window['status'],'FAILED')
                self.assertEqual(run.setup_window['admissions'],[])

    def test_cleanup_at_or_after_shared_end_blocks_next_action(self):
        for durations,delays in [([475],[5]),([475],[6]),([2,470],[0,8])]:
            with self.subTest(durations=durations,delays=delays),self.fixture(durations,cleanup_durations=delays) as (run,now,calls):
                with self.assertRaisesRegex(R.AcceptanceError,'Simulator setup command returned late'):
                    R.setup_application(run,'exact-rc.app')
                self.assertEqual(len(calls),len(durations))
                self.assertEqual(run.commands[-1]['returncode'],0)
                self.assertNotIn('error',run.commands[-1])
                self.assertEqual(run.setup_window['status'],'FAILED')
                self.assertEqual(run.setup_window['admissions'][-1]['returned_monotonic'],now[0])
                self.assertEqual(run.setup_window['admissions'][-1]['status'],'RETURNED_LATE')
                self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)

    def test_timely_cleanup_consumes_shared_time_without_runner_install(self):
        with self.fixture([2,200,260],cleanup_durations=[1,1,1]) as (run,now,calls):
            R.setup_application(run,'exact-rc.app')
            self.assertEqual([c['timeout_seconds'] for c in run.commands],[476,473,272])
            self.assertEqual(calls[-1],['xcrun','simctl','install',ID,'exact-rc.app'])
            self.assertEqual(sum(c[2]=='install' for c in calls),1)
            self.assertEqual(now[0],465)
            self.assertEqual([a['admission_monotonic'] for a in run.setup_window['admissions']],[0,3,204])
            self.assertEqual([a['returned_monotonic'] for a in run.setup_window['admissions']],[3,204,465])

    def test_native_failure_at_each_stage_is_preserved_without_retry(self):
        from rc_acceptance_process import CaptureFailure
        for index in range(3):
            with self.subTest(index=index),self.fixture([1]*(index+1),returncodes=[0]*index+[7]) as (run,now,calls):
                with self.assertRaisesRegex(CaptureFailure,'Metadata command exited 7'):
                    R.setup_application(run,'exact-rc.app')
                self.assertEqual(len(calls),index+1)
                self.assertEqual(run.commands[-1]['error'],'CaptureFailure: Metadata command exited 7')
                self.assertEqual(run.setup_window['status'],'FAILED')
                self.assertIsNone(run.setup_window['admissions'][-1]['returned_monotonic'])

    def test_cancellation_does_not_advance_setup_or_replace_error(self):
        with self.fixture([]) as (run,now,calls):
            error=R.CancellationRequested('injected cancellation')
            with patch.object(run,'sim',side_effect=error) as sim:
                with self.assertRaises(R.CancellationRequested) as caught:R.setup_application(run,'exact-rc.app')
            self.assertIs(caught.exception,error)
            self.assertEqual(sim.call_count,1)
            self.assertEqual(calls,[])
            self.assertEqual(run.setup_window['status'],'FAILED')
            self.assertEqual(len(run.setup_window['admissions']),1)
            self.assertIsNone(run.setup_window['admissions'][0]['returned_monotonic'])
            self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)

    def test_production_setup_still_precedes_authoritative_inventory_and_ui(self):
        source=inspect.getsource(R.execute)
        self.assertLess(source.index('run.claim_created_device('),source.index('setup_application(run,aut)'))
        self.assertLess(source.index('setup_application(run,aut)'),source.index("installed=run.container(BUNDLE,'app')"))
        self.assertLess(source.index("save(run.out/'installed-before.json'"),source.index("'test-installed-rc',cap=720"))
        self.assertIn("result['setup_window']=run.setup_window",source)

    def test_preparation_is_debited_before_scoped_capture_admission(self):
        original=R.os.environ.copy
        with self.fixture([2,3,4]) as (run,now,calls):
            def prepare():
                now[0]+=7
                return original()
            with patch.object(R.os.environ,'copy',side_effect=prepare):
                R.setup_application(run,'exact-rc.app')
            self.assertEqual([c['timeout_seconds'] for c in run.commands],[469,460,450])
            self.assertTrue(all(c['work_deadline_monotonic']==476 for c in run.commands))
            self.assertTrue(all(c['cleanup_deadline_monotonic']==480 for c in run.commands))
            self.assertEqual(run.setup_window['finished_monotonic'],30)
            self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)
        with self.fixture([]) as (run,now,calls):
            def expired_preparation():
                now[0]=476
                return original()
            with patch.object(R.os.environ,'copy',side_effect=expired_preparation):
                with self.assertRaisesRegex(R.AcceptanceError,'Overall acceptance deadline'):
                    R.setup_application(run,'exact-rc.app')
            self.assertEqual(calls,[]);self.assertEqual(run.commands,[])

    def test_delayed_capture_entry_clips_work_and_rejects_expiry_before_spawn(self):
        from rc_acceptance_process import CaptureFailure
        original=R.bounded_capture
        with self.fixture([2,3,4]) as (run,now,calls):
            def delayed(*args,**kwargs):
                now[0]+=7
                self.assertEqual(kwargs['work_deadline'],476)
                self.assertEqual(kwargs['cleanup_parent_deadline'],480)
                return original(*args,**kwargs)
            with patch.object(R,'bounded_capture',side_effect=delayed):
                R.setup_application(run,'exact-rc.app')
            self.assertEqual([c['timeout_seconds'] for c in run.commands],[469,460,450])
            self.assertEqual(run.setup_window['finished_monotonic'],30)
        for entered in [476,481]:
            with self.subTest(entered=entered),self.fixture([]) as (run,now,calls):
                def expired(*args,**kwargs):
                    now[0]=entered
                    return original(*args,**kwargs)
                with patch.object(R,'bounded_capture',side_effect=expired):
                    with self.assertRaisesRegex(CaptureFailure,'before spawn'):
                        R.setup_application(run,'exact-rc.app')
                self.assertEqual(calls,[])
                self.assertEqual(run.commands[0]['timeout_seconds'],0)
                self.assertEqual(run.commands[0]['work_deadline_monotonic'],476)
                self.assertEqual(run.commands[0]['cleanup_deadline_monotonic'],480)
                self.assertNotIn('pid',run.commands[0])
                self.assertEqual(run.setup_window['status'],'FAILED')

    def test_absolute_work_deadline_rejects_nonfinite_or_nonnumeric_without_spawn(self):
        import rc_acceptance_process as P
        for value in [float('nan'),float('inf'),float('-inf'),'476',True]:
            with self.subTest(value=value),self.fixture([]) as (run,now,calls):
                record={}
                with self.assertRaisesRegex(P.CaptureFailure,'Invalid absolute work deadline'):
                    P.bounded_capture(['inert'],timeout=30,receipt=record,
                        work_deadline=value,cleanup_parent_deadline=480)
                self.assertEqual(calls,[]);self.assertNotIn('pid',record)


class FailureSummary(unittest.TestCase):
    def test_allowlist_does_not_emit_sensitive_operation_content(self):
        secret='PRIVATE_FAILURE_SENTINEL'
        op={'command':['/private/'+secret+'/gh','api','--header',secret],
            'timeout_seconds':30,'elapsed_seconds':1.5,'returncode':1,'error':secret,
            'stdout':secret,'stderr':secret,
            'cleanup':{'success':True,'group_state':'absent','leader_reaped':True,'errors':[]}}
        summary=R.failure_summary([op],1,[secret])
        self.assertEqual(summary,{'schema_version':1,'controller_failed':True,'phase':'github-read','operation_index':1,
            'grant_seconds':30,'elapsed_seconds':1.5,'exit_code':1,'exit_code_source':'work','timed_out':False,
            'process_closed':True,'cleanup_failed':True,'diagnostics_status':None})
        self.assertNotIn(secret,json.dumps(summary))

    def test_timeout_and_unproved_closure_remain_distinct(self):
        op={'command':['xcrun','simctl','get_app_container',ID,R.BUNDLE,'app'],
            'timeout_seconds':30,'elapsed_seconds':34.5,
            'error':'CaptureFailure: Metadata command work deadline exceeded',
            'cleanup':{'success':False,'group_state':'present','leader_reaped':False,'errors':['private'],'returncode':-15}}
        summary=R.failure_summary([op],1,[])
        self.assertEqual(summary['phase'],'simulator-get_app_container')
        self.assertTrue(summary['timed_out']);self.assertFalse(summary['process_closed'])
        self.assertEqual(summary['exit_code'],-15)
        self.assertEqual(summary['exit_code_source'],'cleanup')
        # Some capture records retain the unset work result explicitly. The
        # known cleanup exit is still reported without claiming work success.
        op['returncode']=None
        summary=R.failure_summary([op],1,[])
        self.assertEqual(summary['exit_code'],-15)
        self.assertEqual(summary['exit_code_source'],'cleanup')
        self.assertTrue(summary['timed_out'])

    def test_missing_or_invalid_numbers_never_create_success_or_nonfinite_json(self):
        op={'command':['private-command'],'timeout_seconds':float('inf'),'elapsed_seconds':float('nan'),
            'returncode':True,'cleanup':{}}
        summary=R.failure_summary([op],1,[])
        self.assertIsNone(summary['grant_seconds']);self.assertIsNone(summary['elapsed_seconds'])
        self.assertIsNone(summary['exit_code']);self.assertFalse(summary['process_closed'])
        self.assertIsNone(summary['exit_code_source'])
        json.dumps(summary,allow_nan=False)
        for index in [None,0,2,True]:
            empty=R.failure_summary([op],index,[])
            self.assertIsNone(empty['operation_index']);self.assertEqual(empty['phase'],'controller')


class FailureDiagnostics(unittest.TestCase):
    @contextmanager
    def fixture(self, *, end=100, duration=1, failure=None, closed=True):
        with tempfile.TemporaryDirectory() as d:
            run=R.Run(d,Path(d)/'out');run.end=end;run.device=ID;run.owned_device={'udid':ID}
            run.commands=[{'pid':123,'error':'original failure'}]
            now=[0.0];calls=[]
            def capture(argv,**kw):
                calls.append((argv,kw['timeout'],kw['cleanup_parent_deadline'],kw['limit']))
                now[0]+=duration
                raw=b'123 1 123 S 00:30 0.0 0.1 simctl\n999 1 999 S 00:01 0.0 0.1 private-token\n'
                kw['receipt'].update(command=argv,timeout_seconds=kw['timeout'],returncode=0,
                    cleanup={'success':closed,'group_state':'absent' if closed else 'unverified',
                             'leader_reaped':closed,'errors':[]},stdout_bytes=len(raw),stderr_bytes=0)
                for key in ('stdout_path','stderr_path'):
                    if kw.get(key):Path(kw[key]).write_bytes(raw if key=='stdout_path' else b'')
                if failure:raise failure
                return raw
            with patch.object(R.time,'monotonic',side_effect=lambda:now[0]),patch.object(R,'bounded_capture',side_effect=capture):
                yield run,now,calls
    def test_fixed_commands_and_filtered_processes_share_one_parent_window(self):
        with self.fixture() as (run,now,calls):
            result=R.collect_failure_diagnostics(run,1)
            self.assertEqual(result['status'],'collected')
            self.assertEqual([x[0][0] for x in calls],['/bin/ps','/usr/bin/vm_stat','/usr/bin/log'])
            self.assertEqual([x[1] for x in calls],[2,2,8])
            self.assertEqual([x[2] for x in calls],[20,20,20])
            self.assertEqual([x[3] for x in calls],[R.MIB,128*1024,4*R.MIB])
            self.assertIn('ucomm=',calls[0][0][-1]);self.assertNotIn('args',calls[0][0][-1])
            self.assertEqual(calls[2][0][2:4],['--last','10m'])
            self.assertIn('process == "com.apple.CoreSimulator.CoreSimulatorService"',calls[2][0][-1])
            self.assertNotIn('simctl',[x[0][0] for x in calls])
            selected=(run.out/'failure-diagnostics/processes-selected.json').read_text()
            self.assertNotIn('private-token',selected)
            self.assertEqual(len(json.loads(selected)['processes']),1)
            self.assertEqual(run.commands,[{'pid':123,'error':'original failure'}])
            self.assertIsNone(run.cleanup_end)
    def test_expired_parent_or_missing_device_admits_no_diagnostic_child(self):
        for end in (0,4):
            with self.subTest(end=end),self.fixture(end=end) as (run,now,calls):
                self.assertEqual(R.collect_failure_diagnostics(run,1),{'status':'skipped_no_parent_time'})
                self.assertEqual(calls,[]);self.assertFalse((run.out/'failure-diagnostics').exists())
        with self.fixture() as (run,now,calls):
            run.owned_device=None
            self.assertEqual(R.collect_failure_diagnostics(run,1),{'status':'skipped_no_owned_device'})
            self.assertEqual(calls,[])

    def test_workflow_upload_includes_actual_generated_diagnostic_files(self):
        with self.fixture() as (run,now,calls):
            R.collect_failure_diagnostics(run,1)
            generated=[p.relative_to(run.out) for p in run.out.rglob('*') if p.is_file()]
            self.assertTrue(generated)
            workflow=(SCRIPTS.parent/'.github/workflows/rc-acceptance.yml').read_text()
            prefix='${{ runner.temp }}/rc-acceptance/'
            uploaded=[Path(line.strip()[len(prefix):]) for line in workflow.split('          path: |\n',1)[1].splitlines()
                      if line.strip().startswith(prefix)]
            for path in generated:
                self.assertTrue(any(path==root or path.is_relative_to(root) for root in uploaded),str(path))
    def test_parent_clips_phase_and_prevents_another_child_after_late_return(self):
        with self.fixture(end=7,duration=3) as (run,now,calls):
            result=R.collect_failure_diagnostics(run,1)
            self.assertEqual(result['status'],'partial');self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][1:3],(2,7))
        with self.fixture(end=100,duration=25) as (run,now,calls):
            self.assertEqual(R.collect_failure_diagnostics(run,1)['status'],'partial')
            self.assertEqual(len(calls),1)
    def test_collector_failure_is_retained_without_retry_or_primary_mutation(self):
        with self.fixture(failure=OSError('private diagnostic failure')) as (run,now,calls):
            result=R.collect_failure_diagnostics(run,1)
            self.assertEqual(result['status'],'partial');self.assertEqual(len(calls),3)
            self.assertEqual([x['status'] for x in result['operations']],['failed']*3)
            self.assertEqual(run.commands[0]['error'],'original failure')
            self.assertNotIn('private diagnostic failure',json.dumps(result))
    def test_unproved_diagnostic_process_stops_collection(self):
        with self.fixture(closed=False) as (run,now,calls):
            result=R.collect_failure_diagnostics(run,1)
            self.assertEqual(result['status'],'partial');self.assertEqual(len(calls),1)
            self.assertEqual(result['operations'][0]['receipt']['cleanup']['group_state'],'unverified')
    def test_process_fields_and_stdout_summary_cannot_copy_names_or_streams(self):
        raw=b'123 1 123 S 00:30 0 0 PRIVATE_SECRET\n7 1 7 S 00:02 nan 0 simctl\n8 1 8 S 00:02 0 0 simctl-secret\n'
        selected=R.diagnostic_processes(raw,123)
        self.assertEqual([x['pid'] for x in selected['processes']],[123,8])
        self.assertNotIn('SECRET',json.dumps(selected));self.assertNotIn('simctl-secret',json.dumps(selected))
        self.assertIsNone(R.failure_summary([],None,[],{'status':'PRIVATE_SECRET'})['diagnostics_status'])
        summary=R.failure_summary([],None,[],{'status':'partial','stdout':'PRIVATE_SECRET','error':'PRIVATE_SECRET'})
        self.assertEqual(summary['diagnostics_status'],'partial');self.assertNotIn('PRIVATE_SECRET',json.dumps(summary))
    def test_observed_truncated_accounting_names_keep_only_fixed_service_counters(self):
        names=['com.apple.CoreSi','com.apple.CoreSimulator.CoreSimulatorService','CoreSimulatorService',
               'SimulatorTrampol','SimulatorTrampoline','com.apple.otherService']
        raw=''.join(f'{i+1} 1 {i+1} S 00:02 0 0 {name}\n' for i,name in enumerate(names)).encode()
        selected=R.diagnostic_processes(raw,None)
        self.assertEqual([x['pid'] for x in selected['processes']],[1,2,3,4,5])
        self.assertEqual([x['role'] for x in selected['processes']],['core-simulator']*3+['simulator-launcher']*2)
        self.assertTrue(all(not x['matches_recorded_pid'] for x in selected['processes']))
        self.assertNotIn('com.apple',json.dumps(selected));self.assertNotIn('SimulatorTrampol',json.dumps(selected))
    def test_actual_finalizer_skips_success_and_preserves_failure_if_collector_raises(self):
        tree=ast.parse((SCRIPTS/'rc_acceptance.py').read_text())
        execute=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='execute')
        final=next(x for x in execute.body if isinstance(x,ast.Try)).finalbody
        code=compile(ast.fix_missing_locations(ast.Module(body=final,type_ignores=[])),'actual-finalizer','exec')
        for primary in (None,R.AcceptanceError('original failure')):
            with self.subTest(failed=primary is not None),tempfile.TemporaryDirectory() as d:
                run=R.Run(d,Path(d)/'out');run.device=ID;run.close_device=Mock()
                run.container=Mock(side_effect=AssertionError('No post-shutdown container query'))
                result={'status':'PASS' if primary is None else 'FAILED','error':'original failure'}
                collector=Mock(side_effect=OSError('private collector failure'))
                namespace=dict(R.__dict__,run=run,result=result,primary=primary,cleanup_errors=[],run_id=ID,
                               failed_index=None,failure_sample=None,collect_failure_diagnostics=collector)
                with patch('builtins.print') as output:exec(code,namespace)
                run.close_device.assert_called_once()
                run.container.assert_not_called()
                if primary is None:
                    collector.assert_not_called();output.assert_not_called()
                    self.assertNotIn('failure_diagnostics',result);self.assertEqual(result['status'],'PASS')
                else:
                    collector.assert_called_once_with(run,None)
                    self.assertEqual(result['failure_diagnostics'],{'status':'unavailable'})
                    self.assertIs(namespace['primary'],primary);self.assertEqual(result['error'],'original failure')
                    self.assertNotIn('private collector failure',output.call_args.args[0])

class CleanupAdmission(unittest.TestCase):
    @contextmanager
    def fixture(self, durations, mode='exit_on_term'):
        # Keep Run, bounded_capture and kill_owned real. Only the clock and
        # operating-system seams are inert; no process or signal is created.
        import rc_acceptance_process as P
        now=[0.0]
        seen={'parents':[],'processes':[],'probes':[],'signals':[],'waits':[],'sleeps':[]}
        real_cleanup=P.kill_owned
        def spawn(argv, **kwargs):
            duration=durations[len(seen['processes'])]
            process=Mock(pid=43000+len(seen['processes']),returncode=None)
            process.terminated=False
            def poll():
                now[0]+=duration
                if mode=='already_reaped':process.returncode=0;return 0
                return None
            def wait(timeout):
                seen['waits'].append((process.pid,timeout))
                if mode=='stalled_reap':now[0]+=148
                if process.terminated:process.returncode=-15;return -15
                raise P.subprocess.TimeoutExpired(argv,timeout)
            process.poll.side_effect=poll
            process.wait.side_effect=wait
            seen['processes'].append(process)
            return process
        def killpg(pid, sig):
            process=next(p for p in seen['processes'] if p.pid==pid)
            if sig==0:
                seen['probes'].append(pid)
                if mode=='permission':raise PermissionError(P.errno.EPERM,'fixture')
                if process.returncode is not None:raise ProcessLookupError(P.errno.ESRCH,'fixture')
            else:
                seen['signals'].append((pid,sig,now[0]))
                if mode=='exit_on_term':process.terminated=True
        def sleep(seconds):
            seen['sleeps'].append(seconds);now[0]+=seconds
        def cleanup(process, deadline, *, state):
            seen['parents'].append(deadline)
            return real_cleanup(process,deadline,state=state,clock=lambda:now[0],sleep=sleep,killpg=killpg)
        selector=Mock();selector.get_map.return_value={}
        with tempfile.TemporaryDirectory() as d, \
                patch.object(P.time,'monotonic',side_effect=lambda:now[0]), \
                patch.object(P.subprocess,'Popen',side_effect=spawn), \
                patch.object(P.selectors,'DefaultSelector',return_value=selector), \
                patch.object(P.os,'set_blocking'), \
                patch.object(P,'kill_owned',side_effect=cleanup):
            run=R.Run(d,Path(d)/'out')
            yield P,run,now,seen

    def test_late_work_gets_one_cleanup_window_inside_original_parent(self):
        with self.fixture([95]) as (P,run,now,seen):
            with self.assertRaisesRegex(P.CaptureFailure,'work deadline exceeded'):
                run.command(['inert'],'late',cap=90)
            record=run.commands[0]
            self.assertEqual(record['timeout_seconds'],90)
            self.assertEqual(seen['parents'],[1800])
            self.assertEqual(record['cleanup_state']['cleanup_deadline_monotonic'],99)
            self.assertEqual([s[1] for s in seen['signals']],[P.signal.SIGTERM])
            self.assertTrue(record['cleanup']['success'])
            self.assertTrue(record['cleanup']['leader_reaped'])
            self.assertEqual(record['cleanup']['group_state'],'absent')
            self.assertEqual(run.end,1800)
            self.assertIn('work deadline exceeded',record['error'])

    def test_default_capture_keeps_historical_work_relative_cleanup_deadline(self):
        with self.fixture([95]) as (P,run,now,seen):
            record={}
            with self.assertRaisesRegex(P.CaptureFailure,'work deadline exceeded'):
                P.bounded_capture(['inert'],timeout=90,receipt=record)
            self.assertEqual(seen['parents'],[94])
            self.assertEqual(seen['signals'],[])
            self.assertEqual(seen['probes'],[])
            self.assertEqual(record['cleanup_state']['cleanup_deadline_monotonic'],94)
            self.assertEqual(record['cleanup']['group_state'],'unverified')
            self.assertFalse(record['cleanup']['leader_reaped'])

    def test_scoped_capture_work_and_actual_cleanup_share_absolute_parent(self):
        with self.fixture([477]) as (P,run,now,seen):
            with self.assertRaisesRegex(P.CaptureFailure,'work deadline exceeded'):
                run.command(['inert'],'scoped-late',cap=476,deadline=480)
            record=run.commands[0]
            self.assertEqual(record['work_deadline_monotonic'],476)
            self.assertEqual(record['cleanup_deadline_monotonic'],480)
            self.assertEqual(seen['parents'],[480])
            self.assertEqual(record['cleanup_state']['cleanup_deadline_monotonic'],480)
            self.assertEqual([s[1] for s in seen['signals']],[P.signal.SIGTERM])
            self.assertTrue(record['cleanup']['success'])
            self.assertTrue(record['cleanup']['leader_reaped'])
            self.assertEqual(record['cleanup']['group_state'],'absent')
            self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)

    def test_term_kill_and_repeated_probes_do_not_renew_four_seconds(self):
        with self.fixture([95],mode='stubborn') as (P,run,now,seen):
            with self.assertRaises(P.CaptureFailure):run.command(['inert'],'late',cap=90)
            record=run.commands[0]
            self.assertEqual([s[1] for s in seen['signals']],[P.signal.SIGTERM,P.signal.SIGKILL])
            self.assertGreater(len(seen['probes']),2)
            self.assertEqual(seen['parents'],[1800])
            self.assertEqual(record['cleanup_state']['cleanup_deadline_monotonic'],99)
            self.assertAlmostEqual(now[0],99)
            self.assertFalse(record['cleanup']['success'])
            self.assertTrue(record['cleanup']['budget_exhausted'])

    def test_nearer_parent_clips_cleanup_without_extending_it(self):
        with self.fixture([95],mode='stubborn') as (P,run,now,seen):
            run.end=97
            with self.assertRaises(P.CaptureFailure):run.command(['inert'],'late',cap=90)
            record=run.commands[0]
            self.assertEqual(record['timeout_seconds'],90)
            self.assertEqual(seen['parents'],[97])
            self.assertEqual(record['cleanup_state']['cleanup_deadline_monotonic'],97)
            self.assertAlmostEqual(now[0],97)
            self.assertEqual(run.end,97)
            self.assertTrue(all(s[2]<97 for s in seen['signals']))

    def test_expired_parent_cannot_admit_a_signal_or_a_new_cleanup_window(self):
        with self.fixture([95]) as (P,run,now,seen):
            run.end=95
            with self.assertRaises(P.CaptureFailure):run.command(['inert'],'late',cap=90)
            record=run.commands[0]
            self.assertEqual(seen['parents'],[95])
            self.assertEqual(record['cleanup_state']['cleanup_deadline_monotonic'],95)
            self.assertEqual(seen['waits'],[])
            self.assertEqual(seen['probes'],[])
            self.assertEqual(seen['signals'],[])
            self.assertFalse(record['cleanup']['success'])
            self.assertTrue(record['cleanup']['budget_exhausted'])

    def test_device_cleanup_commands_share_the_first_ninety_second_parent(self):
        with self.fixture([15,15]) as (P,run,now,seen):
            for name in ['first','second']:
                with self.assertRaises(P.CaptureFailure):
                    run.command(['inert'],name,cap=10,cleanup=True)
            self.assertEqual(seen['parents'],[90,90])
            self.assertEqual(run.cleanup_end,90)
            self.assertEqual(run.end,1800)
            self.assertEqual([r['timeout_seconds'] for r in run.commands],[10,10])
            self.assertEqual([r['cleanup_state']['cleanup_deadline_monotonic'] for r in run.commands],[19,34])
            self.assertTrue(all(r['cleanup']['success'] for r in run.commands))

    def test_late_reaped_leader_is_never_signaled(self):
        with self.fixture([95],mode='already_reaped') as (P,run,now,seen):
            with self.assertRaisesRegex(P.CaptureFailure,'completed after work deadline'):
                run.command(['inert'],'late',cap=90)
            cleanup=run.commands[0]['cleanup']
            self.assertEqual(seen['signals'],[])
            self.assertEqual(seen['waits'],[])
            self.assertEqual(cleanup['returncode'],0)
            self.assertTrue(cleanup['leader_reaped'])
            self.assertEqual(cleanup['group_state'],'absent')
            self.assertTrue(cleanup['success'])

    def test_permission_error_remains_sticky_and_blocks_signaling(self):
        with self.fixture([95],mode='permission') as (P,run,now,seen):
            with self.assertRaisesRegex(P.CaptureFailure,'work deadline exceeded'):
                run.command(['inert'],'late',cap=90)
            cleanup=run.commands[0]['cleanup']
            self.assertEqual(seen['signals'],[])
            self.assertEqual(cleanup['group_state'],'unknown')
            self.assertFalse(cleanup['success'])
            self.assertTrue(cleanup['errors'])
            self.assertTrue(all(e['operation']=='group_probe' and e['errno']==P.errno.EPERM for e in cleanup['errors']))
            self.assertAlmostEqual(now[0],99)

    def test_synchronous_reap_stall_is_not_reported_as_hard_bounded_or_closed(self):
        with self.fixture([95],mode='stalled_reap') as (P,run,now,seen):
            with self.assertRaisesRegex(P.CaptureFailure,'work deadline exceeded'):
                run.command(['inert'],'late',cap=90)
            record=run.commands[0];cleanup=record['cleanup']
            self.assertEqual(record['cleanup_state']['cleanup_deadline_monotonic'],99)
            self.assertEqual(cleanup['elapsed_seconds'],148)
            self.assertEqual(record['elapsed_seconds'],243)
            self.assertEqual(seen['signals'],[])
            self.assertEqual(seen['probes'],[])
            self.assertEqual(cleanup['group_state'],'unverified')
            self.assertFalse(cleanup['leader_reaped'])
            self.assertIsNone(cleanup['returncode'])
            self.assertFalse(cleanup['success'])
            self.assertTrue(cleanup['budget_exhausted'])

class LiveFailureSample(unittest.TestCase):
    @contextmanager
    def fixture(self, *, rows=None, changed=False, failed=None, unclosed=None, advance=None):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d).resolve();run=R.Run(home,home/'out');run.device=ID
            run.owned_device={'udid':ID,'absent_before':True}
            R.save(run.out/'owned-device.json',run.owned_device)
            installed=home/'Library/Developer/CoreSimulator/Devices'/ID/'data/Containers/Bundle/Application'/ID/'RoomInventory.app'
            installed.mkdir(parents=True);(installed/'RoomInventory').write_bytes(b'exact installed executable')
            R.save(run.out/'installed-before.json',R.inventory(installed))
            now=[0.0];calls=[];run.end=1800
            def capture(argv,**kwargs):
                name=['identity-before','sample','identity-after'][len(calls)]
                calls.append((argv,kwargs));now[0]+=(advance or {}).get(name,1 if name=='sample' else .1)
                receipt=kwargs['receipt'];receipt.update(returncode=0,cleanup={'success':name!=unclosed,
                    'group_state':'unknown' if name==unclosed else 'absent','leader_reaped':True,'errors':[]})
                if name==failed:raise R.AcceptanceError('private diagnostic exception')
                if name=='sample':raw=b'bounded stack fixture'
                else:
                    pid=124 if changed and name=='identity-after' else 123
                    raw=(rows if rows is not None else f'{pid} Sat Nov 7 06:04:52 2026 {installed}/RoomInventory\n').encode()
                if kwargs.get('stdout_path'):kwargs['stdout_path'].write_bytes(raw)
                kwargs['stderr_path'].write_bytes(b'')
                return raw
            with patch.object(R.Path,'home',return_value=home),patch.object(R.time,'monotonic',side_effect=lambda:now[0]), \
                    patch.object(R,'bounded_capture',side_effect=capture):
                sampler=R.FailureSample(run,ID,installed)
                yield sampler,run,now,calls

    def test_static_preparation_is_not_repeated_inside_live_sample_window(self):
        with self.fixture() as (s,run,now,calls):
            regular=R.regular
            def slow_read(*args):
                now[0]+=2.5
                return regular(*args)
            with patch.object(R,'regular',side_effect=slow_read):
                prepared=R.FailureSample(run,ID,s.installed)
            self.assertEqual(prepared.preparation_seconds,5)
            self.assertEqual(calls,[])
            self.assertFalse((run.out/'failure-diagnostics').exists())
            with patch.object(R,'regular',side_effect=AssertionError('Repeated static read')), \
                    patch.object(R.Path,'resolve',side_effect=AssertionError('Repeated path resolution')):
                prepared.feed(prepared.marker+b'\n',720)
            self.assertEqual(prepared.report['status'],'collected')
            self.assertEqual(calls[0][1]['timeout'],2)
            self.assertTrue(all(kwargs['cleanup_parent_deadline']==15 for _,kwargs in calls))
            self.assertEqual(prepared.report['installed_before_sha256'],
                             R.digest(regular(run.out/'installed-before.json',16*R.MIB)))
            self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)

    def test_unavailable_static_context_never_runs_diagnostic_on_success_or_failure(self):
        with self.fixture() as (s,run,now,calls):
            (run.out/'installed-before.json').unlink()
            unavailable=R.FailureSample(run,ID,s.installed)
            unavailable.feed(b'ordinary successful test\n',720)
            self.assertFalse(unavailable.seen);self.assertIsNone(unavailable.report)
            self.assertFalse((run.out/'failure-diagnostics').exists())
            unavailable.feed(unavailable.marker+b'\n',720)
            self.assertEqual(unavailable.report['status'],'partial');self.assertEqual(calls,[])

    def test_static_preparation_cannot_renew_parent_or_swallow_cancellation(self):
        with self.fixture() as (s,run,now,calls):
            regular=R.regular;run.end=4
            def late_read(*args):
                now[0]+=3
                return regular(*args)
            with patch.object(R,'regular',side_effect=late_read):
                unavailable=R.FailureSample(run,ID,s.installed)
            self.assertIsNone(unavailable.prepared);self.assertEqual(run.end,4)
            unavailable.feed(unavailable.marker+b'\n',720)
            self.assertEqual(unavailable.report['status'],'skipped_no_parent_time')
            self.assertEqual(calls,[])
            run.end=1800
            with patch.object(R,'regular',side_effect=R.CancellationRequested('Cancellation requested')):
                with self.assertRaises(R.CancellationRequested):R.FailureSample(run,ID,s.installed)

    def test_replaced_executable_or_changed_owned_device_never_reuses_preparation(self):
        for mode in ['replacement','device','owner']:
            with self.subTest(mode=mode),self.fixture() as (s,run,now,calls):
                if mode=='replacement':
                    exe=s.installed/'RoomInventory';other=exe.with_name('replacement')
                    other.write_bytes(exe.read_bytes());other.replace(exe)
                elif mode=='device':run.device=str(uuid.uuid4()).upper()
                else:run.owned_device['absent_before']=False
                s.feed(s.marker+b'\n',720)
                self.assertEqual(s.report['status'],'partial');self.assertEqual(calls,[])

    def test_late_fresh_file_identity_does_not_admit_process_read(self):
        with self.fixture() as (s,run,now,calls):
            lstat=R.Path.lstat
            def slow_identity(path):
                now[0]+=11
                return lstat(path)
            with patch.object(R.Path,'lstat',autospec=True,side_effect=slow_identity):
                s.feed(s.marker+b'\n',720)
            self.assertEqual(s.report['status'],'partial');self.assertEqual(calls,[])
            self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)

    def test_chunked_exact_nonce_triggers_once_before_cleanup(self):
        with self.fixture() as (s,run,now,calls):
            s.feed(b'ordinary stdout\nROOM_RC_SAMPLE_V1 '+ID[:8].encode(),720)
            self.assertFalse(s.seen);self.assertEqual(calls,[])
            s.feed(ID[8:].encode()+b'\n',720)
            s.feed(s.marker+b'\n',720)
            self.assertEqual(s.report['status'],'collected');self.assertEqual(len(calls),3)
            self.assertEqual(calls[1][0],['/usr/bin/sample','123','1','10','-mayDie','-file','/dev/stdout'])
            self.assertEqual(calls[0][0],['/bin/ps','-axww','-o','pid=,lstart=,comm='])
            self.assertEqual(calls[1][1]['limit'],2*R.MIB)
            self.assertTrue(all(k['cleanup_parent_deadline']==10 for _,k in calls))
            self.assertEqual(run.end,1800);self.assertIsNone(run.cleanup_end)
            self.assertEqual((run.out/'failure-diagnostics/live-aut/sample.stdout').read_bytes(),b'bounded stack fixture')
            self.assertFalse((run.out/'failure-diagnostics/live-aut/identity-before.stdout').exists())

    def test_success_wrong_nonce_and_embedded_or_overlong_markers_do_nothing(self):
        with self.fixture() as (s,run,now,calls):
            for data in [b'normal successful test\n',b'ROOM_RC_SAMPLE_V1 '+str(uuid.uuid4()).upper().encode()+b'\n',
                         b'prefix '+s.marker+b'\n',b'x'*300,s.marker+b'\n']:
                s.feed(data,720)
            self.assertFalse(s.seen);self.assertEqual(calls,[])
            self.assertFalse((run.out/'failure-diagnostics').exists())

    def test_no_remaining_time_never_admits_diagnostic(self):
        with self.fixture() as (s,run,now,calls):
            s.feed(s.marker+b'\n',4)
            self.assertEqual(s.report['status'],'skipped_no_parent_time');self.assertEqual(calls,[])

    def test_missing_ambiguous_foreign_or_malformed_identity_never_samples(self):
        with self.fixture() as (s,run,now,calls):
            exe=s.installed/'RoomInventory'
            line=f'123 Sat Nov 7 06:04:52 2026 {exe}\n'
        for rows in ['',line+line,line.replace(str(exe),'/foreign/RoomInventory'),line.replace('06:04:52','invalid')]:
            with self.subTest(rows=rows),self.fixture(rows=rows) as (s,run,now,calls):
                # Each fixture has a different owned root; no matching foreign path can be sampled.
                s.feed(s.marker+b'\n',720)
                self.assertEqual(s.report['status'],'partial');self.assertEqual(len(calls),1)

    def test_identity_parser_rejects_duplicate_and_bad_start_for_current_path(self):
        path=Path('/owned/RoomInventory.app/RoomInventory')
        line=f'123 Sat Nov 7 06:04:52 2026 {path}\n'
        self.assertEqual(R.exact_aut_process(line.encode(),path)['pid'],123)
        for raw in [line+line,line.replace('06:04:52','invalid'),line.replace('123','true',1)]:
            with self.assertRaises(R.AcceptanceError):R.exact_aut_process(raw.encode(),path)

    def test_replaced_identity_unclosed_child_and_native_error_remain_partial(self):
        for mode in ['changed','failed','unclosed']:
            options={'changed':True} if mode=='changed' else {mode:'sample'}
            with self.subTest(mode=mode),self.fixture(**options) as (s,run,now,calls):
                s.feed(s.marker+b'\n',720);before=len(calls);s.feed(s.marker+b'\n',720)
                self.assertEqual(s.report['status'],'partial');self.assertEqual(len(calls),before)
                self.assertEqual(before,3 if mode=='changed' else 2)
                self.assertNotIn('private diagnostic exception',json.dumps(s.report))

    def test_late_sample_has_no_post_lookup_or_new_budget(self):
        with self.fixture(advance={'sample':10}) as (s,run,now,calls):
            s.feed(s.marker+b'\n',8)
            self.assertEqual(s.report['status'],'partial');self.assertEqual(len(calls),2)
            self.assertTrue(all(k['cleanup_parent_deadline']==8 for _,k in calls))

    def test_changed_ownership_or_symlink_prevents_process_lookup(self):
        for mode in ['owner','symlink']:
            with self.subTest(mode=mode),self.fixture() as (s,run,now,calls):
                if mode=='owner':run.owned_device['udid']=str(uuid.uuid4()).upper()
                else:
                    exe=s.installed/'RoomInventory';exe.unlink();exe.symlink_to('/foreign')
                s.feed(s.marker+b'\n',720)
                self.assertEqual(s.report['status'],'partial');self.assertEqual(calls,[])

    def test_cancellation_is_not_swallowed_as_a_best_effort_diagnostic_error(self):
        with self.fixture() as (s,run,now,calls):
            with patch.object(R,'bounded_capture',side_effect=R.CancellationRequested('Cancellation requested')):
                with self.assertRaises(R.CancellationRequested):s.feed(s.marker+b'\n',720)
            self.assertTrue(s.seen)
            self.assertEqual(s.report['status'],'partial')

    def test_cancellation_during_final_report_save_propagates_after_closed_children(self):
        with self.fixture() as (s,run,now,calls):
            save=R.save
            def persist(path,value):
                if path.name=='result.json':raise R.CancellationRequested('Cancellation requested')
                return save(path,value)
            with patch.object(R,'save',side_effect=persist):
                with self.assertRaises(R.CancellationRequested):s.feed(s.marker+b'\n',720)
            self.assertEqual(len(calls),3);self.assertTrue(s.seen)
            self.assertTrue(all(row['receipt']['cleanup']['success'] for row in s.report['operations']))

    def test_post_cleanup_collector_does_not_swallow_cancellation(self):
        with FailureDiagnostics().fixture(failure=R.CancellationRequested('Cancellation requested')) as (run,now,calls):
            with self.assertRaises(R.CancellationRequested):R.collect_failure_diagnostics(run,1)
            self.assertEqual(len(calls),1)

    def test_marker_precedes_failure_capture_and_never_authorizes_acceptance(self):
        swift=(SCRIPTS.parent/'Acceptance/RC/RCArtifactAcceptanceTests.swift').read_text()
        marker=swift.index('ROOM_RC_SAMPLE_V1 ')
        self.assertLess(marker,swift.index('try? capture("failure", app)'))
        self.assertGreater(marker,swift.index('} catch {'))
        source=(SCRIPTS/'rc_acceptance.py').read_text()
        self.assertIn('on_stdout=failure_sample.feed',source)
        self.assertLess(source.index("save(run.out/'installed-before.json'"),
                        source.index('failure_sample=FailureSample(run,run_id,installed)'))
        self.assertLess(source.index('failure_sample=FailureSample(run,run_id,installed)'),
                        source.index("run.command(['xcodebuild','test-without-building'"))
        self.assertLess(source.index("require(not failure_sample.seen,'Native failure marker received')"),
                        source.index("save(run.out/'installed-after.json'"))

    def test_actual_zero_exit_boundary_rejects_previously_marked_failure(self):
        # Execute the production admission/command/postcondition statements;
        # no download, native process or Simulator is involved.
        source=(SCRIPTS/'rc_acceptance.py').read_text();tree=ast.parse(source)
        execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute')
        body=next(n for n in execute.body if isinstance(n,ast.Try)).body
        index=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign)
                   and any(isinstance(t,ast.Name) and t.id=='failure_sample' for t in n.targets))
        module=ast.fix_missing_locations(ast.Module(body=body[index:index+3],type_ignores=[]))
        run=Mock(device=ID,out=Path('/inert'));run.command.return_value=b''
        sample=Mock(seen=True)
        scope={'FailureSample':lambda *a:sample,'run':run,'run_id':ID,'installed':Path('/inert/app'),
               'plan':Path('/inert/plan'),'TARGET':R.TARGET,'METHOD':R.METHOD,'MIB':R.MIB,'require':R.require}
        with self.assertRaisesRegex(R.AcceptanceError,'Native failure marker received'):
            exec(compile(module,'actual-execute-native-boundary','exec'),scope)
        run.command.assert_called_once()
        self.assertEqual(run.command.call_args.kwargs['cap'],720)

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

    def test_stdout_observer_is_optional_and_cannot_hide_native_nonzero_exit(self):
        from rc_acceptance_process import bounded_capture,CaptureFailure
        chunks=[];receipt={}
        with self.assertRaises(CaptureFailure):
            bounded_capture([sys.executable,'-c','import sys; print("marker",flush=True); print("not callback",file=sys.stderr); sys.exit(2)'],
                timeout=3,limit=1024,receipt=receipt,on_stdout=lambda chunk,end:chunks.append((chunk,end)))
        self.assertEqual(b''.join(chunk for chunk,_ in chunks),b'marker\n')
        self.assertEqual(receipt['returncode'],2);self.assertTrue(receipt['cleanup']['success'])

    def test_stdout_callback_cannot_renew_deadline_and_child_is_closed(self):
        # Use the existing real-helper/owned-cleanup fixture, not host scheduling
        # or destructive signals to an actual process, for the late callback.
        with CleanupAdmission().fixture([0]) as (P,run,now,seen):
            selector=P.selectors.DefaultSelector.return_value
            key=Mock(data='stdout',fd=111,fileobj=Mock())
            selector.get_map.return_value={'stdout':key};selector.select.return_value=[(key,None)]
            calls=[]
            def callback(chunk,deadline):calls.append((chunk,deadline));now[0]=95
            with self.assertRaisesRegex(P.CaptureFailure,'work deadline'):
                with patch.object(P.os,'read',return_value=b'marker\n'):
                    run.command(['inert'],'test-installed-rc',cap=90,on_stdout=callback)
            self.assertEqual(calls,[(b'marker\n',90)])
            receipt=run.commands[0]
            self.assertTrue(receipt['cleanup']['success']);self.assertTrue(receipt['cleanup']['leader_reaped'])
            self.assertEqual(receipt['cleanup']['group_state'],'absent')
            self.assertEqual(seen['parents'],[1800]);self.assertEqual(run.end,1800)

if __name__=='__main__':unittest.main(verbosity=2)
