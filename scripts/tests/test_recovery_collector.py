"""Injected filesystem/reader tests; these do not run Xcode or a simulator."""
import copy
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

# Reuse the independent artifact fixture, not the verifier's implementation.
import test_recovery_journey as fixtures

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("recovery_collector", ROOT / "scripts/recovery_collector.py")
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


class RecoveryCollectorTests(unittest.TestCase):
    def setUp(self):
        self.artifact_case = fixtures.RecoveryJourneyVerifierTests("test_valid_collected_artifacts_do_not_claim_ui_execution")
        self.artifact_case.setUp()
        self.addCleanup(self.artifact_case.doCleanups)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sim = self.root / "simulator"
        self.app = self.sim / "data/Containers/Data/Application/APP"
        self.runner = self.sim / "data/Containers/Data/Application/RUNNER"
        self.evidence = self.root / "evidence"
        for path in [self.app, self.runner, self.evidence]:
            path.mkdir(parents=True)
        self.app_id, self.runner_id = "com.alvit.roominventory", "com.alvit.roominventory.uitests.xctrunner"
        for path, bundle in [(self.app, self.app_id), (self.runner, self.runner_id)]:
            (path / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": bundle}))
        self.config = {"app_container": self.app, "runner_container": self.runner, "simulator_root": self.sim,
                       "evidence_root": self.evidence, "fixture_path": ROOT / "UITests/Fixtures/SyntheticRecoveryReceipt.png",
                       "journey_run_id": fixtures.JOURNEY, "source_run_id": fixtures.SOURCE, "target_run_id": fixtures.TARGET,
                       "source_commit": fixtures.PIN, "source_tree_sha256": "a" * 64, "config_sha256": "b" * 64,
                       "xctestrun_sha256": "c" * 64, "simulator_udid": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
                       "app_bundle_id": self.app_id, "runner_bundle_id": self.runner_id}
        self.calls, self.guard_count = [], 0
        self.guard_hook = lambda: None
        self.reader_hook = lambda args: None
        self.omit_capture = None
        self.duplicate_capture = False
        self.summary = {"result": "Passed", "totalTestCount": 1, "passedTests": 1, "failedTests": 0,
                        "skippedTests": 0, "expectedFailures": 0, "testFailures": [],
                        "devicesAndConfigurations": [{"device": {"deviceId": self.config["simulator_udid"]}}]}
        self.tests = {"testNodes": [{"nodeType": "Test Plan", "children": [{"nodeType": "UI test bundle", "name": "RoomInventoryUITests",
                       "children": [{"nodeType": "Test Case", "nodeIdentifier": C.CASE, "result": "Passed"}]}]}]}
        self.collector = C.Collector(self.config, guard=self.guard, run=self.fake_run)
        self.original = self.root / "actual.xcresult"
        (self.original / "Data").mkdir(parents=True)
        (self.original / "Info.plist").write_bytes(plistlib.dumps({"version": 1}))
        (self.original / "Data/payload").write_bytes(b"original immutable xcresult payload")

    def guard(self):
        self.guard_count += 1
        self.guard_hook()

    def fake_run(self, args):
        self.calls.append(args)
        self.assertEqual(args[args.index("--path") + 1], str(self.collector.xc_copy))
        self.assertNotIn(str(self.original), args)
        self.assertTrue((self.collector.root / "xcresult/original-before.json").exists())
        self.reader_hook(args)
        if args[:3] == ["get", "test-results", "summary"]:
            return json.dumps(self.summary).encode()
        if args[:3] == ["get", "test-results", "tests"]:
            return json.dumps(self.tests).encode()
        self.assertEqual(args[:2], ["export", "attachments"])
        destination = Path(args[args.index("--output-path") + 1])
        destination.mkdir()
        records = []
        entries = {"recovery-journey-evidence.json": self.artifact_case.root / "ui-evidence.json"}
        entries.update({name: self.artifact_case.root / path for name, path in self.artifact_case.ui_attachments.items()})
        for index, (name, source) in enumerate(entries.items()):
            if name == self.omit_capture:
                continue
            filename = f"exported-{index}.data"
            shutil.copyfile(source, destination / filename)
            record = {"deviceId": self.config["simulator_udid"], "isAssociatedWithFailure": False,
                      "suggestedHumanReadableName": name, "exportedFileName": filename}
            records.append(record)
            if self.duplicate_capture and name == "recovery-journey-evidence.json":
                records.append(record.copy())
        (destination / "manifest.json").write_text(json.dumps([{"testIdentifier": C.CASE, "attachments": records}]))
        return b""

    def request(self, number, **changes):
        bridge = self.collector.bridge
        bridge.mkdir(parents=True, exist_ok=True)
        request = {"schema_version": 1, **self.collector.ids, "sequence": number,
                   "role": ("source_zip", "backup", "target_zip")[(number - 1) // 2],
                   "phase": "before" if number % 2 else "after", "nonce": str(uuid.uuid4()).upper()}
        request.update(changes)
        raw = json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
        (bridge / f"request-{number:02d}.json").write_bytes(raw)
        return request, raw

    def export(self, index, directory=None):
        directory = directory or str(uuid.uuid4()).upper()
        generated = self.app / "tmp/InventoryExports" / directory
        generated.mkdir(parents=True)
        role = ("source_zip", "backup", "target_zip")[index]
        filename = ("Inventory-package.zip", "Inventory.roominventory", "Inventory-package.zip")[index]
        source = self.artifact_case.root / self.artifact_case.paths[role]
        shutil.copyfile(source, generated / filename)
        saved_folder = self.sim / "data/Containers/Shared/AppGroup/FILES/File Provider Storage" / self.collector.folder
        saved_folder.mkdir(parents=True, exist_ok=True)
        saved_name = ("source-", "backup-", "recovered-")[index] + fixtures.JOURNEY + (".roominventory" if index == 1 else ".zip")
        shutil.copyfile(source, saved_folder / saved_name)
        return generated / filename, saved_folder / saved_name

    def journey(self):
        self.collector.capture_initial_exports()
        for index in range(3):
            self.request(index * 2 + 1)
            self.assertEqual(self.collector.poll_bridge(), index * 2 + 1)
            self.export(index)
            self.request(index * 2 + 2)
            self.assertEqual(self.collector.poll_bridge(), index * 2 + 2)
        for label, run in [("source", fixtures.SOURCE), ("target", fixtures.TARGET)]:
            shutil.copytree(self.artifact_case.root / label, self.app / "tmp/RoomInventoryUITests" / run)

    def test_equal_zip_bytes_have_distinct_live_origins_and_verify_end_to_end_offline(self):
        self.journey()
        copy = self.collector.capture_xcresult(self.original)
        manifest = self.collector.collect(copy)
        result = fixtures.VERIFIER.verify_collection(manifest, fixtures.PIN)
        self.assertEqual(result["status"], "PASS_OFFLINE_ARTIFACT_CONSISTENCY")
        origins = self.collector.origins
        self.assertEqual(origins[0]["metadata"]["sha256"], origins[2]["metadata"]["sha256"])
        self.assertNotEqual(origins[0]["directory_id"], origins[2]["directory_id"])
        self.assertNotEqual(origins[0]["metadata"]["inode"], origins[2]["metadata"]["inode"])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual((self.original / "Data/payload").read_bytes(), b"original immutable xcresult payload")

    def test_ack_is_canonical_and_durable_receipt_precedes_publication(self):
        self.collector.capture_initial_exports()
        request, raw = self.request(1)
        self.collector.poll_bridge()
        ack = (self.collector.bridge / "ack-01.json").read_bytes()
        self.assertEqual(ack, C.canonical({**request, "request_sha256": C.sha(raw), "success": True}))
        self.assertTrue((self.collector.root / "bridge/receipt-01.json").is_file())
        self.assertEqual((self.collector.root / "bridge/request-01.json").read_bytes(), raw)

    def test_two_new_exports_make_origin_ambiguous(self):
        self.collector.capture_initial_exports()
        self.request(1)
        self.collector.poll_bridge()
        self.export(0)
        self.export(0)
        self.request(2)
        with self.assertRaisesRegex(C.CollectorError, "exactly one export"):
            self.collector.poll_bridge()
        self.assertFalse((self.collector.bridge / "ack-02.json").exists())

    def test_generated_saved_mismatch_rejects_ack(self):
        self.collector.capture_initial_exports()
        self.request(1)
        self.collector.poll_bridge()
        _, saved = self.export(0)
        saved.write_bytes(b"wrong saved content")
        self.request(2)
        with self.assertRaisesRegex(C.CollectorError, "payload differ"):
            self.collector.poll_bridge()
        self.assertFalse((self.collector.bridge / "ack-02.json").exists())

    def test_prior_export_change_and_duplicate_saved_folder_rejected(self):
        self.collector.capture_initial_exports()
        self.request(1)
        self.collector.poll_bridge()
        generated, saved = self.export(0)
        self.request(2)
        self.collector.poll_bridge()
        generated.write_bytes(b"changed prior export")
        self.request(3)
        with self.assertRaisesRegex(C.CollectorError, "outside their live barrier"):
            self.collector.poll_bridge()
        second = saved.parents[2].parent / "OTHER/File Provider Storage" / self.collector.folder
        second.mkdir(parents=True)
        with self.assertRaisesRegex(C.CollectorError, "ambiguous saved Files"):
            self.collector._files()

    def test_stale_and_duplicate_bridge_requests_fail_closed(self):
        self.collector.capture_initial_exports()
        self.request(1, schema_version=True)
        with self.assertRaisesRegex(C.CollectorError, "bridge schema"):
            self.collector.poll_bridge()
        self.request(1)
        self.collector.poll_bridge()
        (self.collector.bridge / "request-01.json").write_bytes(b"{}")
        with self.assertRaisesRegex(C.CollectorError, "prior bridge message changed"):
            self.collector.poll_bridge()

    def test_foreign_run_or_out_of_order_request_fails(self):
        self.collector.capture_initial_exports()
        self.request(2)
        with self.assertRaisesRegex(C.CollectorError, "out-of-order"):
            self.collector.poll_bridge()
        (self.collector.bridge / "request-02.json").unlink()
        self.request(1, target_run_id=fixtures.SOURCE)
        with self.assertRaisesRegex(C.CollectorError, "run IDs"):
            self.collector.poll_bridge()

    def test_container_identity_change_is_not_silently_relocated(self):
        self.collector.capture_initial_exports()
        (self.app / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": "other.app"}))
        with self.assertRaisesRegex(C.CollectorError, "bundle identity"):
            self.collector.poll_bridge()

    def test_original_xcresult_symlink_is_rejected_before_readers(self):
        (self.original / "Data/link").symlink_to(self.original / "Info.plist")
        with self.assertRaisesRegex(C.CollectorError, "symlink"):
            self.collector.capture_xcresult(self.original)
        self.assertEqual(self.calls, [])

    def test_xcresult_byte_and_entry_limits_are_enforced_before_readers(self):
        self.collector.xc_limit = 10
        with self.assertRaisesRegex(C.CollectorError, "byte limit"):
            self.collector.capture_xcresult(self.original)
        self.collector.xc_limit = 192 * C.MIB
        self.collector.xc_files = 1
        with self.assertRaisesRegex(C.CollectorError, "entry count"):
            self.collector.capture_xcresult(self.original)
        self.assertEqual(self.calls, [])

    def test_source_mutation_during_copy_is_detected(self):
        fired = []
        def change():
            if not fired and (self.collector.root / "xcresult/verified.xcresult/Data/payload").exists():
                fired.append(True)
                (self.original / "Data/payload").write_bytes(b"changed during copy")
        self.guard_hook = change
        with self.assertRaisesRegex(C.CollectorError, "changed during capture"):
            self.collector.capture_xcresult(self.original)
        self.assertEqual(self.calls, [])
        self.assertTrue((self.collector.root / "xcresult/original-before.json").exists())
        self.assertTrue((self.collector.root / "xcresult/original-after-copy.json").exists())
        self.assertTrue((self.collector.root / "xcresult/capture-errors.json").exists())

    def test_reader_mutation_is_confined_to_copy_and_post_manifests_record_it(self):
        self.journey()
        copy = self.collector.capture_xcresult(self.original)
        def mutate(args):
            (copy / "reader-cache").write_bytes(b"reader added cache")
        self.reader_hook = mutate
        self.collector.collect(copy)
        self.assertFalse((self.original / "reader-cache").exists())
        post = json.loads((self.collector.root / "xcresult/copy-after-readers.json").read_bytes())
        self.assertIn("reader-cache", post)

    def test_original_mutation_by_reader_is_detected_and_recorded(self):
        copy = self.collector.capture_xcresult(self.original)
        self.reader_hook = lambda args: (self.original / "Data/payload").write_bytes(b"unexpected original change")
        with self.assertRaisesRegex(C.CollectorError, "reader changed original"):
            self.collector.collect(copy)
        self.assertTrue((self.collector.root / "xcresult/original-after-readers.json").exists())

    def test_reader_failure_and_post_verification_failure_are_both_preserved(self):
        copy = self.collector.capture_xcresult(self.original)
        def fail(args):
            (self.original / "Data/payload").unlink()
            raise RuntimeError("primary reader failure sentinel")
        self.reader_hook = fail
        with self.assertRaisesRegex(C.CollectorError, "Primary reader failure: RuntimeError: primary reader failure sentinel.*reader changed original"):
            self.collector.collect(copy)
        report = json.loads((self.collector.root / "xcresult/reader-errors.json").read_bytes())
        self.assertIn("primary reader failure sentinel", report["primary_reader_error"])
        self.assertIn("reader changed original", report["post_reader_verification_errors"][0])

    def test_pre_copy_reservation_prevents_partial_xcresult_output(self):
        self.collector.output_limit = self.collector.written + 10
        with self.assertRaisesRegex(C.CollectorError, "before xcresult copy"):
            self.collector.capture_xcresult(self.original)
        self.assertFalse((self.collector.root / "xcresult/verified.xcresult").exists())
        self.assertEqual(self.calls, [])

    def test_original_is_rehashed_before_first_reader(self):
        copy = self.collector.capture_xcresult(self.original)
        (self.original / "Data/payload").write_bytes(b"changed before reading")
        with self.assertRaisesRegex(C.CollectorError, "original xcresult changed before readers"):
            self.collector.collect(copy)
        self.assertEqual(self.calls, [])

    def test_duplicate_final_ui_ledger_is_rejected(self):
        self.duplicate_capture = True
        copy = self.collector.capture_xcresult(self.original)
        with self.assertRaisesRegex(C.CollectorError, "ambiguous UI attachment"):
            self.collector.collect(copy)

    def test_no_reader_accepts_an_uncaptured_bundle(self):
        with self.assertRaisesRegex(C.CollectorError, "verified xcresult"):
            self.collector.collect(self.original)
        self.assertEqual(self.calls, [])

    def test_missing_ui_capture_fails_collection(self):
        self.omit_capture = "14-screen"
        copy = self.collector.capture_xcresult(self.original)
        with self.assertRaisesRegex(C.CollectorError, "missing or ambiguous UI attachment"):
            self.collector.collect(copy)
        self.assertFalse((self.collector.root / "collection.json").exists())

    def test_skipped_or_wrong_test_never_collects_attachments(self):
        self.summary["skippedTests"] = 1
        copy = self.collector.capture_xcresult(self.original)
        with self.assertRaisesRegex(C.CollectorError, "zero skips"):
            self.collector.collect(copy)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse((self.collector.root / "xcresult/attachments").exists())

    def test_guard_cutoff_prevents_ack_and_reader_execution(self):
        self.collector.capture_initial_exports()
        self.request(1)
        def cutoff():
            raise TimeoutError("injected absolute deadline")
        self.guard_hook = cutoff
        with self.assertRaises(TimeoutError):
            self.collector.poll_bridge()
        self.assertFalse((self.collector.bridge / "ack-01.json").exists())
        with self.assertRaises(TimeoutError):
            self.collector.capture_xcresult(self.original)
        self.assertEqual(self.calls, [])

    def test_output_budget_prevents_ack(self):
        self.collector.capture_initial_exports()
        self.request(1)
        self.collector.output_limit = self.collector.written + 1
        with self.assertRaisesRegex(C.CollectorError, "output byte limit"):
            self.collector.poll_bridge()
        self.assertFalse((self.collector.bridge / "ack-01.json").exists())

    def test_xcresulttool_export_name_matching_is_exact_or_known_suffix(self):
        self.assertTrue(C.attachment_name_matches("capture_0_AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA.png", "capture.png"))
        self.assertTrue(C.attachment_name_matches("capture.png_0_AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA.png", "capture.png"))
        self.assertFalse(C.attachment_name_matches("capture_1_AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA.png", "capture.png"))
        self.assertFalse(C.attachment_name_matches("other-capture.png", "capture.png"))


if __name__ == "__main__":
    unittest.main()


class InstallationHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="room-installation-control-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.number = 0

    def fixture(self):
        self.number += 1
        root = self.root / str(self.number)
        sim = root / "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
        app = sim / "data/Containers/Data/Application/PREAPP"
        runner = app.parent / "PRERUNNER"
        evidence = root / "evidence"
        fixture = root / "fixture.png"
        for path in (app, runner, evidence): path.mkdir(parents=True)
        fixture.write_bytes(b"inert exact synthetic fixture control")
        config = {"app_container": app, "runner_container": runner, "simulator_root": sim,
                  "evidence_root": evidence, "fixture_path": fixture, "fixture_sha256": C.sha(fixture.read_bytes()),
                  "journey_run_id": "11111111-1111-4111-8111-111111111111",
                  "source_run_id": "22222222-2222-4222-8222-222222222222",
                  "target_run_id": "33333333-3333-4333-8333-333333333333",
                  "source_commit": "a" * 40, "source_tree_sha256": "b" * 64,
                  "config_sha256": "c" * 64, "xctestrun_sha256": "d" * 64,
                  "simulator_udid": sim.name, "app_bundle_id": "com.alvit.roominventory",
                  "runner_bundle_id": "com.alvit.roominventory.uitests.xctrunner"}
        for path, key in ((app, "app_bundle_id"), (runner, "runner_bundle_id")):
            (path / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": config[key]}))
        state = SimpleNamespace(root=root, sim=sim, app=app, runner=runner, fixture=fixture,
                                guard_hook=lambda: None, config=config)
        def forbidden(args): raise AssertionError("native reader is forbidden")
        state.collector = C.Collector(config, guard=lambda: state.guard_hook(), run=forbidden)
        state.collector.begin_installation()
        app.rename(root / "preinstalled-app")
        runner.rename(root / "preinstalled-runner")
        return state

    def install(self, state):
        state.app = state.app.parent / "INSTALLEDAPP"
        state.runner = state.app.parent / "INSTALLEDRUNNER"
        for path, key in ((state.app, "app_bundle_id"), (state.runner, "runner_bundle_id")):
            path.mkdir()
            (path / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": state.config[key]}))
        state.bridge = state.runner / "Documents/RecoveryJourneyBridge" / state.config["journey_run_id"]
        state.bridge.mkdir(parents=True)
        return state

    def request(self, state, **changes):
        request = {"schema_version": 1, **state.collector.ids, "phase": "installation",
                   **{k: state.config[k] for k in ("simulator_udid", "app_bundle_id", "runner_bundle_id")},
                   "nonce": "44444444-4444-4444-8444-444444444444"}
        request.update(changes)
        raw = C.canonical(request)
        (state.bridge / "installation-request.json").write_bytes(raw)
        return raw

    def test_explicit_installation_transition_pins_once_before_ack_with_durable_evidence(self):
        state = self.fixture(); collector = state.collector
        self.assertEqual(collector.poll_bridge(), 0)  # Old data roots are already gone.
        self.assertEqual(collector.pins, {})
        self.assertIsNone(collector.baseline)
        self.install(state); raw = self.request(state)
        original_link = C.os.link
        def durable(source, destination, **options):
            for name in ("preinstallation.json", "initial.json", "installation-request.json",
                         "installation-receipt.json", "installation-ack.json"):
                self.assertTrue((collector.root / "bridge" / name).is_file())
            self.assertEqual(collector.app, state.app)
            self.assertEqual(collector.runner, state.runner)
            self.assertTrue(collector.pins)
            return original_link(source, destination, **options)
        with patch.object(C.os, "link", side_effect=durable):
            self.assertEqual(collector.poll_bridge(), 0)
        self.assertEqual(collector.installation_state, "accepted")
        ack = C.parse((state.bridge / "installation-ack.json").read_bytes())
        self.assertEqual(ack, {**C.parse(raw), "request_sha256": C.sha(raw), "success": True})
        self.assertEqual(collector.baseline, {"exports": {}, "saved": {"folder": None, "identity": None, "entries": {}}})
        for action in (collector.begin_installation, collector.capture_initial_exports):
            with self.assertRaises(C.CollectorError): action()
        # The normal six-barrier path is still used after the startup gate.
        request = {"schema_version": 1, **collector.ids, "sequence": 1,
                   "role": "source_zip", "phase": "before", "nonce": "55555555-5555-4555-8555-555555555555"}
        (state.bridge / "request-01.json").write_bytes(C.canonical(request))
        self.assertEqual(collector.poll_bridge(), 1)
        self.assertTrue((state.bridge / "ack-01.json").exists())

    def test_foreign_malformed_or_duplicate_requests_never_ack_or_restart_discovery(self):
        variants = [{"journey_run_id": "foreign"}, {"simulator_udid": "foreign"},
                    {"app_bundle_id": "other.app"}, {"runner_bundle_id": "other.runner"},
                    {"schema_version": True}, {"phase": "before"}, {"nonce": "invalid"}, {"unknown": 1}]
        for changes in variants:
            with self.subTest(changes=changes):
                state = self.install(self.fixture()); self.request(state, **changes)
                with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
                self.assertFalse((state.bridge / "installation-ack.json").exists())
                self.assertEqual(state.collector.installation_state, "binding")
                with self.assertRaisesRegex(C.CollectorError, "consumed or failed"):
                    state.collector.poll_bridge()
        state = self.install(self.fixture()); self.request(state)
        (state.bridge / "installation-request.json").write_bytes(b'{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(C.CollectorError, "duplicate JSON"):
            state.collector.poll_bridge()
        self.assertEqual(state.collector.installation_state, "binding")
        state = self.install(self.fixture()); raw = self.request(state)
        second = state.app / "Documents/RecoveryJourneyBridge" / state.config["journey_run_id"]
        second.mkdir(parents=True); (second / "installation-request.json").write_bytes(raw)
        with self.assertRaisesRegex(C.CollectorError, "duplicate installation"):
            state.collector.poll_bridge()
        self.assertFalse((state.bridge / "installation-ack.json").exists())

    def test_missing_or_duplicate_bundle_identity_cannot_select_an_aut(self):
        for mode in ("missing", "duplicate", "wrong-runner"):
            with self.subTest(mode=mode):
                state = self.install(self.fixture()); self.request(state)
                if mode == "missing": (state.app / C.MCM).unlink()
                elif mode == "wrong-runner":
                    (state.runner / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": "foreign.runner"}))
                else:
                    duplicate = state.app.parent / "DUPLICATE"; duplicate.mkdir()
                    (duplicate / C.MCM).write_bytes((state.app / C.MCM).read_bytes())
                with self.assertRaisesRegex(C.CollectorError, "missing or ambiguous"):
                    state.collector.poll_bridge()
                self.assertFalse((state.bridge / "installation-ack.json").exists())

    def test_prior_data_and_changed_fixture_are_not_blessed_as_installation(self):
        for mode in ("namespace", "exports", "fixture", "scenario-request"):
            with self.subTest(mode=mode):
                state = self.install(self.fixture()); self.request(state)
                if mode == "namespace":
                    path = state.app / "tmp/RoomInventoryUITests" / state.config["source_run_id"]
                    path.mkdir(parents=True)
                elif mode == "exports":
                    path = state.app / "tmp/InventoryExports" / state.config["source_run_id"]
                    path.mkdir(parents=True)
                elif mode == "fixture": state.fixture.write_bytes(b"changed synthetic seed source")
                else: (state.bridge / "request-01.json").write_bytes(b"{}")
                with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
                self.assertFalse((state.bridge / "installation-ack.json").exists())

    def test_no_follow_and_original_guard_deadline_prevent_startup_ack(self):
        state = self.install(self.fixture()); raw = self.request(state)
        request = state.bridge / "installation-request.json"
        request.rename(state.root / "outside-request.json")
        request.symlink_to(state.root / "outside-request.json")
        with patch.object(C.os, "open", side_effect=AssertionError("must reject before open")):
            with self.assertRaisesRegex(C.CollectorError, "symlink"):
                state.collector.poll_bridge()
        state = self.install(self.fixture()); self.request(state)
        def expired():
            if (state.collector.root / "bridge/installation-receipt.json").exists():
                raise TimeoutError("original controller deadline")
        state.guard_hook = expired
        with self.assertRaisesRegex(TimeoutError, "original controller deadline"):
            state.collector.poll_bridge()
        self.assertFalse((state.bridge / "installation-ack.json").exists())
        self.assertEqual(state.collector.installation_state, "binding")

    def test_deadline_after_temporary_ack_write_does_not_publish_success(self):
        state = self.install(self.fixture()); self.request(state)
        def expired_after_write():
            if any(path.name.startswith(".ack-") for path in state.bridge.iterdir()):
                raise TimeoutError("original deadline after ACK fsync")
        state.guard_hook = expired_after_write
        with self.assertRaisesRegex(TimeoutError, "original deadline after ACK fsync"):
            state.collector.poll_bridge()
        self.assertFalse((state.bridge / "installation-ack.json").exists())
        self.assertEqual(state.collector.installation_state, "binding")

    def test_post_ack_metadata_loss_or_handshake_mutation_never_rediscovers_or_repins(self):
        for mode in ("metadata", "request", "ack", "device"):
            with self.subTest(mode=mode):
                state = self.install(self.fixture()); self.request(state); state.collector.poll_bridge()
                pins = copy.deepcopy(state.collector.pins)
                if mode == "metadata": (state.app / C.MCM).unlink()
                elif mode in ("request", "ack"):
                    (state.bridge / ("installation-" + mode + ".json")).write_bytes(b"{}")
                else: state.collector.installation_device = {"device_id": -1, "inode": -1}
                with patch.object(state.collector, "_poll_installation", side_effect=AssertionError("rediscovery forbidden")):
                    with self.assertRaises((C.CollectorError, FileNotFoundError)):
                        state.collector.poll_bridge()
                self.assertEqual(state.collector.pins, pins)
                self.assertEqual(state.collector.installation_state, "accepted")

    def test_installation_search_keeps_the_actual_directory_entry_bound(self):
        from contextlib import contextmanager
        from itertools import repeat
        state = self.fixture()
        entry = SimpleNamespace(path=str(state.app.parent / "entry"), is_symlink=lambda: False)
        @contextmanager
        def entries(_):
            yield repeat(entry, 2001)
        with patch.object(C.os, "scandir", side_effect=entries):
            with self.assertRaisesRegex(C.CollectorError, "entry count limit"):
                state.collector.poll_bridge()
        self.assertEqual(state.collector.pins, {})
        self.assertIsNone(state.collector.baseline)
