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

    def test_only_verified_application_installs_once_with_original_allowance(self):
        for duration,start in [(100,0),(200,0),(295,0),(100,400)]:
            with self.subTest(duration=duration,start=start),self.fixture([duration],start=start) as (run,now,calls):
                R.install_application(run,'exact-rc.app')
                self.assertEqual(calls,[['xcrun','simctl','install',ID,'exact-rc.app']])
                self.assertEqual([c['timeout_seconds'] for c in run.commands],[296])
                self.assertEqual(run.commands[0]['cleanup_reserved_seconds'],4)
                self.assertEqual(now[0],start+duration)
                self.assertEqual(run.end,1800)
                self.assertIsNone(run.cleanup_end)

    def test_late_application_never_retries_or_installs_runner(self):
        from rc_acceptance_process import CaptureFailure
        for duration in [296,297,300]:
            with self.subTest(duration=duration),self.fixture([duration]) as (run,now,calls):
                with self.assertRaisesRegex(CaptureFailure,'completed after work deadline'):
                    R.install_application(run,'exact-rc.app')
                self.assertEqual(calls,[['xcrun','simctl','install',ID,'exact-rc.app']])
                self.assertEqual(run.commands[0]['timeout_seconds'],296)
                self.assertEqual(run.commands[0]['elapsed_seconds'],duration)

    def test_parent_deadline_clips_application_without_renewal(self):
        with self.fixture([20],start=1770) as (run,now,calls):
            R.install_application(run,'exact-rc.app')
            self.assertEqual([c['timeout_seconds'] for c in run.commands],[26])
            self.assertEqual(now[0],1790)
            self.assertEqual(run.end,1800)
            self.assertIsNone(run.cleanup_end)

    def test_parent_expiry_blocks_admission_or_late_success(self):
        from rc_acceptance_process import CaptureFailure
        with self.fixture([26],start=1770) as (run,now,calls):
            with self.assertRaises(CaptureFailure):R.install_application(run,'exact-rc.app')
            self.assertEqual(len(calls),1)
            self.assertEqual(run.commands[0]['timeout_seconds'],26)
        for start in [1796,1800,1801]:
            with self.subTest(start=start),self.fixture([],start=start) as (run,now,calls):
                with self.assertRaisesRegex(R.AcceptanceError,'Application installation deadline'):
                    R.install_application(run,'exact-rc.app')
                self.assertEqual(calls,[])
                self.assertEqual(run.commands,[])

    def test_cleanup_at_or_after_installation_phase_end_is_not_success(self):
        for delay in [5,6]:
            with self.subTest(delay=delay),self.fixture([295],cleanup_durations=[delay]) as (run,now,calls):
                with self.assertRaisesRegex(R.AcceptanceError,'Application installation returned late'):
                    R.install_application(run,'exact-rc.app')
                self.assertEqual(len(calls),1)
                self.assertEqual(run.commands[0]['returncode'],0)
                self.assertNotIn('error',run.commands[0])
                self.assertEqual(now[0],295+delay)

    def test_timely_cleanup_does_not_admit_a_redundant_runner_install(self):
        with self.fixture([290],cleanup_durations=[6]) as (run,now,calls):
            R.install_application(run,'exact-rc.app')
            self.assertEqual(calls,[['xcrun','simctl','install',ID,'exact-rc.app']])
            self.assertEqual(run.commands[0]['returncode'],0)
            self.assertEqual(now[0],296)

    def test_install_failure_is_preserved_without_retry(self):
        from rc_acceptance_process import CaptureFailure
        with self.fixture([1],returncodes=[7]) as (run,now,calls):
            with self.assertRaisesRegex(CaptureFailure,'Metadata command exited 7'):
                R.install_application(run,'exact-rc.app')
            self.assertEqual(calls,[['xcrun','simctl','install',ID,'exact-rc.app']])
            self.assertEqual(run.commands[0]['returncode'],7)
            self.assertEqual(run.commands[0]['error'],'CaptureFailure: Metadata command exited 7')

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
            'process_closed':True,'cleanup_failed':True})
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
