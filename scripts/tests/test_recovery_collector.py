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
                       "evidence_root": self.evidence, "fixture_path": ROOT / "UITests/Fixtures/SyntheticRecoveryReceipt.data",
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
        self.copy_startup_fixture_for_offline_verification()

    def copy_startup_fixture_for_offline_verification(self):
        # These artifact tests use capture_initial_exports instead of a live
        # installation handshake. Supply their separately constructed receipts.
        for relative in self.artifact_case.manifest["startup_evidence"].values():
            self.collector._write(relative, (self.artifact_case.root / relative).read_bytes())

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

    def test_saved_files_ctime_drift_keeps_all_barriers_and_offline_verification(self):
        self.collector.capture_initial_exports()
        for index in range(2):
            self.request(index * 2 + 1)
            self.collector.poll_bridge()
            _, saved = self.export(index)
            self.request(index * 2 + 2)
            self.collector.poll_bridge()
        original_ctime = self.collector.origins[1]["saved_metadata"]["ctime_ns"]
        original_read = self.collector._read
        drift = 1

        def read(path, limit):
            data, record = original_read(path, limit)
            if Path(path) == saved:
                record["ctime_ns"] += drift
            return data, record

        with patch.object(self.collector, "_read", side_effect=read):
            self.request(5)
            self.assertEqual(self.collector.poll_bridge(), 5)
            self.assertEqual(self.collector.barriers[-1]["snapshot"]["saved"]["entries"]
                             [saved.name]["ctime_ns"], original_ctime + 1)
            self.export(2)
            drift = 2
            self.request(6)
            self.assertEqual(self.collector.poll_bridge(), 6)
            self.assertEqual(self.collector.barriers[-1]["snapshot"]["saved"]["entries"]
                             [saved.name]["ctime_ns"], original_ctime + 2)
            for label, run in [("source", fixtures.SOURCE), ("target", fixtures.TARGET)]:
                shutil.copytree(self.artifact_case.root / label, self.app / "tmp/RoomInventoryUITests" / run)
            drift = 3
            copy = self.collector.capture_xcresult(self.original)
            manifest = self.collector.collect(copy)
        self.copy_startup_fixture_for_offline_verification()
        self.assertEqual(fixtures.VERIFIER.verify_collection(manifest, fixtures.PIN)["status"],
                         "PASS_OFFLINE_ARTIFACT_CONSISTENCY")
        self.assertEqual(self.collector.origins[1]["saved_metadata"]["ctime_ns"], original_ctime)

    def test_saved_files_other_cross_observation_changes_reject_before_ack(self):
        self.collector.capture_initial_exports()
        self.request(1)
        self.collector.poll_bridge()
        self.export(0)
        self.request(2)
        self.collector.poll_bridge()
        self.request(3)
        before = self.collector._files()

        def reject(after):
            with patch.object(self.collector, "_files", return_value=after):
                with self.assertRaisesRegex(C.CollectorError, "outside their live barrier"):
                    self.collector.poll_bridge()
            self.assertFalse((self.collector.bridge / "ack-03.json").exists())

        for field, replacement in [("inode", -1), ("device_id", -1), ("bytes", -1),
                                   ("mtime_ns", -1), ("created_at_ns", -1),
                                   ("sha256", "0" * 64), ("kind", "directory")]:
            with self.subTest(field=field):
                after = copy.deepcopy(before)
                name = next(iter(after["entries"]))
                after["entries"][name][field] = replacement
                reject(after)
        for alteration in ("remove", "add", "folder", "folder_identity"):
            with self.subTest(alteration=alteration):
                after = copy.deepcopy(before)
                entries = after["entries"]
                if alteration == "remove":
                    entries.pop(next(iter(entries)))
                elif alteration == "add":
                    entries["foreign.zip"] = copy.deepcopy(next(iter(entries.values())))
                elif alteration == "folder":
                    after["folder"] += "-other"
                else:
                    after["identity"]["inode"] = -1
                reject(after)

    def test_saved_file_change_after_before_barrier_rejects_after_ack(self):
        self.collector.capture_initial_exports()
        self.request(1)
        self.collector.poll_bridge()
        _, saved = self.export(0)
        self.request(2)
        self.collector.poll_bridge()
        self.request(3)
        self.collector.poll_bridge()
        self.export(1)
        saved.write_bytes(b"changed after before barrier")
        self.request(4)
        with self.assertRaisesRegex(C.CollectorError, "prior saved Files copy changed"):
            self.collector.poll_bridge()
        self.assertFalse((self.collector.bridge / "ack-04.json").exists())

    def test_saved_file_identity_change_at_final_read_rejects_collection(self):
        self.journey()
        copy = self.collector.capture_xcresult(self.original)
        saved = self.sim / self.collector.origins[0]["saved"]
        original_read = self.collector._read
        reads = 0

        def read(path, limit):
            nonlocal reads
            data, record = original_read(path, limit)
            if Path(path) == saved:
                reads += 1
                if reads == 2:  # The final snapshot passed; now copy the saved artifact.
                    record["inode"] += 1
            return data, record

        with patch.object(self.collector, "_read", side_effect=read):
            with self.assertRaisesRegex(C.CollectorError, "export changed during final collection"):
                self.collector.collect(copy)
        self.assertFalse((self.collector.root / "collection.json").exists())

    def test_generated_export_ctime_drift_still_rejects_before_ack(self):
        self.collector.capture_initial_exports()
        self.request(1)
        self.collector.poll_bridge()
        generated, _ = self.export(0)
        self.request(2)
        self.collector.poll_bridge()
        self.request(3)
        original_read = self.collector._read

        def read(path, limit):
            data, record = original_read(path, limit)
            if Path(path) == generated:
                record["ctime_ns"] += 1
            return data, record

        with patch.object(self.collector, "_read", side_effect=read):
            with self.assertRaisesRegex(C.CollectorError, "outside their live barrier"):
                self.collector.poll_bridge()
        self.assertFalse((self.collector.bridge / "ack-03.json").exists())

    def test_saved_file_ctime_change_during_read_still_fails(self):
        _, saved = self.export(0)
        original_fstat = C.os.fstat

        def fstat(fd):
            info = original_fstat(fd)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
                                   st_size=info.st_size, st_mtime_ns=info.st_mtime_ns,
                                   st_ctime_ns=info.st_ctime_ns + 1)

        with patch.object(C.os, "fstat", side_effect=fstat):
            with self.assertRaisesRegex(C.CollectorError, "file changed while reading"):
                self.collector._read(saved, C.MIB)

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

    def test_missing_user_accessibility_capture_still_fails_collection(self):
        self.omit_capture = "14-ax"
        copy = self.collector.capture_xcresult(self.original)
        with self.assertRaisesRegex(C.CollectorError, "missing or ambiguous UI attachment"):
            self.collector.collect(copy)
        self.assertFalse((self.collector.root / "collection.json").exists())

    def test_missing_user_ledger_still_fails_collection(self):
        self.omit_capture = "recovery-journey-evidence.json"
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
        fixture.write_bytes((ROOT / "UITests/Fixtures/SyntheticRecoveryReceipt.data").read_bytes())
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

    def install(self, state, *, warmup=True):
        state.app = state.app.parent / "INSTALLEDAPP"
        state.runner = state.app.parent / "INSTALLEDRUNNER"
        for path, key in ((state.app, "app_bundle_id"), (state.runner, "runner_bundle_id")):
            path.mkdir()
            (path / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": state.config[key]}))
        state.bridge = state.runner / "Documents/RecoveryJourneyBridge" / state.config["journey_run_id"]
        state.bridge.mkdir(parents=True)
        if warmup:
            self.warmup(state)
        return state

    def warmup(self, state):
        path = state.app / "tmp/RoomInventoryUITests" / state.config["journey_run_id"]
        (path / "assets").mkdir(parents=True)
        (path / ".repository.lock").write_bytes(b"")
        return path

    def request(self, state, **changes):
        request = {"schema_version": 1, **state.collector.ids, "phase": "installation",
                   **{k: state.config[k] for k in ("simulator_udid", "app_bundle_id", "runner_bundle_id")},
                   "nonce": "44444444-4444-4444-8444-444444444444"}
        request.update(changes)
        raw = C.canonical(request)
        (state.bridge / "installation-request.json").write_bytes(raw)
        return raw

    def seed_receipt(self, state, initial_ids=None, **changes):
        fixture = state.fixture.read_bytes()
        initial_ids = sorted(initial_ids if initial_ids is not None else [f"default-{i}" for i in range(6)])
        created = "synthetic-owned-asset/L0/001"
        final_ids = sorted(initial_ids + [created])
        value = {"schema_version": 1, "phase": "photos_seed", "status": "passed", **state.collector.ids,
                 "simulator_udid": state.config["simulator_udid"], "runner_bundle_id": state.config["runner_bundle_id"],
                 "installation_request_sha256": state.collector.installation_files["installation-request.json"],
                 "fixture_filename": "SyntheticRecoveryReceipt.png", "bundle_resource_filename": "SyntheticRecoveryReceipt.data",
                 "fixture_bytes": len(fixture), "fixture_sha256": C.sha(fixture), "deadline_seconds": 86,
                 "authorization": {"before_raw": 3, "after_raw": 3, "requested": False, "callback_raw": None,
                                   "prompt_seen": False, "prompt_accepted": False,
                                   "prompt_runner": "", "prompt_text": "", "prompt_button": ""},
                 "read_write_authorized": True, "initial_asset_count": len(initial_ids), "initial_asset_ids": initial_ids,
                 "initial_asset_ids_sha256": C.sha("\n".join(initial_ids).encode()),
                 "final_asset_count": len(final_ids), "final_asset_ids": final_ids,
                 "final_asset_ids_sha256": C.sha("\n".join(final_ids).encode()), "created_asset_id": created,
                 "existing_fixture_count": 0, "mutation_attempts": 1, "change_requested": True, "change_completed": True,
                 "before_bytes": len(fixture), "before_sha256": C.sha(fixture),
                 "after_bytes": len(fixture), "after_sha256": C.sha(fixture),
                 "finished_within_deadline": True, "elapsed_seconds": 1.5}
        value.update(changes)
        raw = C.canonical(value)
        (state.bridge / "photos-seed.json").write_bytes(raw)
        return raw

    def photos_receipt(self, state, **changes):
        collector = state.collector
        fixture = state.fixture.read_bytes()
        seed_path = state.bridge / "photos-seed.json"
        if not seed_path.exists(): self.seed_receipt(state)
        seed_raw = seed_path.read_bytes()
        seed = C.parse(seed_raw)
        value = {"schema_version": 1, "phase": "photos_isolation", "status": "passed", **collector.ids,
                 "simulator_udid": state.config["simulator_udid"], "runner_bundle_id": state.config["runner_bundle_id"],
                 "installation_request_sha256": collector.installation_files["installation-request.json"],
                 "fixture_filename": "SyntheticRecoveryReceipt.png", "fixture_bytes": len(fixture),
                 "fixture_sha256": C.sha(fixture), "deadline_seconds": 20,
                 "authorization": {"before_raw": 3, "after_raw": 3, "requested": False, "callback_raw": None,
                                   "prompt_seen": False, "prompt_accepted": False,
                                   "prompt_runner": "", "prompt_text": "", "prompt_button": ""},
                 "read_write_authorized": True, "initial_asset_count": seed["final_asset_count"],
                 "seed_receipt_sha256": C.sha(seed_raw), "initial_asset_ids_sha256": seed["final_asset_ids_sha256"],
                 "fixture_asset_id": "synthetic-owned-asset/L0/001", "before_bytes": len(fixture),
                 "before_sha256": C.sha(fixture), "removed_asset_count": seed["initial_asset_count"],
                 "removed_asset_ids_sha256": seed["initial_asset_ids_sha256"],
                 "change_requested": True, "change_completed": True, "confirmation_seen": True,
                 "confirmation_accepted": True, "confirmation_text": "Runner would like to delete 6 photos",
                 "final_asset_count": 1,
                 "after_bytes": len(fixture), "after_sha256": C.sha(fixture),
                 "finished_within_deadline": True, "elapsed_seconds": 1.5}
        value.update(changes)
        raw = C.canonical(value)
        (state.bridge / "photos-isolation.json").write_bytes(raw)
        return raw

    def photos_state(self):
        state = self.fixture(); self.install(state); self.request(state)
        self.assertEqual(state.collector.poll_bridge(), 0)
        return state

    def test_explicit_installation_transition_pins_once_before_ack_with_durable_evidence(self):
        state = self.fixture(); collector = state.collector
        self.assertEqual(collector.poll_bridge(), 0)  # Old data roots are already gone.
        self.assertEqual(collector.pins, {})
        self.assertIsNone(collector.baseline)
        self.install(state); raw = self.request(state)
        original_link = C.os.link
        def durable(source, destination, **options):
            for name in ("preinstallation.json", "initial.json", "installation-request.json",
                         "installation-discovery.json", "installation-receipt.json", "installation-ack.json"):
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
        receipt = C.parse((collector.root / "bridge/installation-receipt.json").read_bytes())
        warmup = receipt["baseline"]["warmup"]
        self.assertEqual(warmup["namespace"], "tmp/RoomInventoryUITests/" + state.config["journey_run_id"])
        self.assertEqual(set(warmup["entries"]), {"assets", ".repository.lock"})
        self.assertEqual(warmup["entries"][".repository.lock"]["bytes"], 0)
        for action in (collector.begin_installation, collector.capture_initial_exports):
            with self.assertRaises(C.CollectorError): action()
        # The normal six-barrier path is still used after both startup gates.
        self.photos_receipt(state)
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

    def test_request_published_after_initial_census_binds_relocated_aut(self):
        state = self.install(self.fixture()); collector = state.collector
        old_app = state.app
        application_root = old_app.parent
        original_entries = collector._entries
        censuses, request_bytes = [], []

        def entries(path, budget):
            result = original_entries(path, budget)
            if path == application_root:
                censuses.append(result)
            return result

        def first_launch_during_request_discovery():
            if len(censuses) == 1 and not request_bytes:
                state.app = application_root / "AFTERFIRSTLAUNCH"
                old_app.rename(state.app)
                request_bytes.append(self.request(state))

        # The real first list is complete before _plain(request) calls guard.
        # No fake root list: the AUT actually moves and the runner publishes.
        state.guard_hook = first_launch_during_request_discovery
        with patch.object(collector, "_entries", side_effect=entries):
            self.assertEqual(collector.poll_bridge(), 0)
        self.assertEqual(len(censuses), 2)
        self.assertIn(old_app, censuses[0]); self.assertNotIn(state.app, censuses[0])
        self.assertNotIn(old_app, censuses[1]); self.assertIn(state.app, censuses[1])
        self.assertEqual(collector.app, state.app)
        self.assertEqual(collector.installation_state, "accepted")
        discovery = C.parse((collector.root / "bridge/installation-discovery.json").read_bytes())
        self.assertEqual(discovery["request"], C.parse(request_bytes[0]))
        self.assertEqual(discovery["request_sha256"], C.sha(request_bytes[0]))
        self.assertEqual([discovery[key] for key in ("initial_root_count", "post_request_root_count",
                                                    "added_root_count", "removed_root_count")], [2, 2, 1, 1])
        self.assertEqual(discovery["matches"]["app"], {
            "count": 1, "classification": "unique", "paths_truncated": False,
            "relative_paths": [state.app.relative_to(state.sim).as_posix()]})
        self.assertTrue((state.bridge / "installation-ack.json").is_file())

    def test_missing_or_duplicate_bundle_identity_cannot_select_an_aut(self):
        for mode in ("missing", "duplicate", "wrong-runner", "duplicate-runner"):
            with self.subTest(mode=mode):
                state = self.install(self.fixture()); self.request(state)
                if mode == "missing": (state.app / C.MCM).unlink()
                elif mode == "wrong-runner":
                    (state.runner / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": "foreign.runner"}))
                else:
                    duplicate = state.app.parent / "DUPLICATE"; duplicate.mkdir()
                    source = state.runner if mode == "duplicate-runner" else state.app
                    (duplicate / C.MCM).write_bytes((source / C.MCM).read_bytes())
                with self.assertRaisesRegex(C.CollectorError, "missing or ambiguous"):
                    state.collector.poll_bridge()
                self.assertFalse((state.bridge / "installation-ack.json").exists())
                discovery = C.parse((state.collector.root / "bridge/installation-discovery.json").read_bytes())
                role = "runner" if "runner" in mode else "app"
                count = 2 if "duplicate" in mode else 0
                self.assertEqual(discovery["matches"][role]["count"], count)
                self.assertEqual(discovery["matches"][role]["classification"], "duplicate" if count else "missing")

    def test_unique_runner_must_still_own_the_validated_request(self):
        state = self.install(self.fixture()); raw = self.request(state)
        foreign = state.app.parent / "FOREIGN"
        bridge = foreign / "Documents/RecoveryJourneyBridge" / state.config["journey_run_id"]
        bridge.mkdir(parents=True)
        (foreign / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": "unrelated.bundle"}))
        (state.bridge / "installation-request.json").rename(bridge / "installation-request.json")
        with self.assertRaisesRegex(C.CollectorError, "outside expected runner"):
            state.collector.poll_bridge()
        self.assertFalse((bridge / "installation-ack.json").exists())
        self.assertFalse((state.bridge / "installation-ack.json").exists())
        discovery = C.parse((state.collector.root / "bridge/installation-discovery.json").read_bytes())
        self.assertEqual(discovery["request_sha256"], C.sha(raw))
        self.assertEqual(discovery["request_runner"], foreign.relative_to(state.sim).as_posix())
        self.assertEqual(discovery["matches"]["runner"]["count"], 1)

    def test_post_request_census_keeps_entry_limit_and_guard(self):
        from contextlib import contextmanager
        from itertools import repeat
        for mode in ("entries", "deadline"):
            with self.subTest(mode=mode):
                state = self.install(self.fixture()); self.request(state)
                root = state.app.parent; original = C.os.scandir; calls = []
                entry = SimpleNamespace(path=str(root / "entry"), is_symlink=lambda: False)
                @contextmanager
                def scandir(path):
                    if path == root:
                        calls.append(path)
                        if len(calls) == 2:
                            if mode == "deadline":
                                state.guard_hook = lambda: (_ for _ in ()).throw(TimeoutError("original deadline"))
                            yield repeat(entry, 2001)
                            return
                    with original(path) as values: yield values
                error, message = (C.CollectorError, "entry count limit") if mode == "entries" else (TimeoutError, "original deadline")
                with patch.object(C.os, "scandir", side_effect=scandir):
                    with self.assertRaisesRegex(error, message): state.collector.poll_bridge()
                self.assertEqual(len(calls), 2)
                self.assertEqual(state.collector.pins, {})
                self.assertFalse((state.bridge / "installation-ack.json").exists())

    def test_changed_request_during_fresh_census_cannot_ack(self):
        state = self.install(self.fixture()); raw = self.request(state)
        original = state.collector._entries; censuses = []
        def entries(path, budget):
            result = original(path, budget)
            if path == state.app.parent:
                censuses.append(path)
                if len(censuses) == 2:
                    (state.bridge / "installation-request.json").write_bytes(raw + b" ")
            return result
        with patch.object(state.collector, "_entries", side_effect=entries):
            with self.assertRaisesRegex(C.CollectorError, "request changed during capture"):
                state.collector.poll_bridge()
        self.assertFalse((state.bridge / "installation-ack.json").exists())
        with self.assertRaisesRegex(C.CollectorError, "consumed or failed"): state.collector.poll_bridge()

    def test_reused_nonce_never_starts_post_request_census(self):
        state = self.install(self.fixture()); raw = self.request(state)
        state.collector.nonces.add(C.parse(raw)["nonce"])
        with patch.object(state.collector, "_entries", wraps=state.collector._entries) as entries:
            with self.assertRaisesRegex(C.CollectorError, "reused installation nonce"):
                state.collector.poll_bridge()
        self.assertEqual(sum(call.args[0] == state.app.parent for call in entries.call_args_list), 1)
        self.assertFalse((state.collector.root / "bridge/installation-discovery.json").exists())
        self.assertFalse((state.bridge / "installation-ack.json").exists())

    def test_discovery_caps_paths_but_preserves_full_duplicate_count(self):
        state = self.install(self.fixture()); self.request(state)
        for index in range(18):
            path = state.app.parent / ("DUPLICATE-" + str(index))
            path.mkdir(); (path / C.MCM).write_bytes((state.app / C.MCM).read_bytes())
        with self.assertRaisesRegex(C.CollectorError, "missing or ambiguous"):
            state.collector.poll_bridge()
        raw = (state.collector.root / "bridge/installation-discovery.json").read_bytes()
        discovery = C.parse(raw); matches = discovery["matches"]["app"]
        self.assertEqual(matches["count"], 19)
        self.assertEqual(len(matches["relative_paths"]), 16)
        self.assertTrue(matches["paths_truncated"])
        self.assertLessEqual(len(raw), 65536)
        self.assertNotIn(str(state.root).encode(), raw)
        self.assertFalse((state.bridge / "installation-ack.json").exists())

    def test_discovery_write_failure_preserves_exception_and_no_ack(self):
        state = self.install(self.fixture()); self.request(state)
        (state.app / C.MCM).unlink()
        original = state.collector._write; failure = TimeoutError("original controller deadline")
        def write(relative, data):
            if relative == "bridge/installation-discovery.json": raise failure
            return original(relative, data)
        with patch.object(state.collector, "_write", side_effect=write):
            with self.assertRaises(TimeoutError) as caught: state.collector.poll_bridge()
        self.assertIs(caught.exception, failure)
        self.assertIn("installation discovery counts: app=0, runner=1", failure.__notes__)
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


    def test_request_before_first_aut_launch_is_rejected_without_ack(self):
        state = self.install(self.fixture(), warmup=False)
        self.request(state)
        with self.assertRaisesRegex(C.CollectorError, "missing snapshot root"):
            state.collector.poll_bridge()
        self.assertEqual(state.collector.pins, {})
        self.assertEqual(state.collector.installation_state, "binding")
        self.assertFalse((state.bridge / "installation-ack.json").exists())
        with self.assertRaisesRegex(C.CollectorError, "consumed or failed"):
            state.collector.poll_bridge()

    def test_first_aut_launch_replacement_precedes_final_request_and_never_repins_after_ack(self):
        state = self.install(self.fixture(), warmup=False)
        old_app = state.app
        # Runner entry alone is insufficient: the first AUT launch removes this
        # still-preinstalled AUT, before it initializes its warmup namespace.
        old_app.rename(state.root / "aut-before-first-launch")
        self.assertEqual(state.collector.poll_bridge(), 0)
        self.assertEqual(state.collector.pins, {})
        self.assertIsNone(state.collector.baseline)
        state.app = old_app.parent / "AFTERFIRSTLAUNCH"
        state.app.mkdir()
        (state.app / C.MCM).write_bytes(plistlib.dumps({"MCMMetadataIdentifier": state.config["app_bundle_id"]}))
        self.warmup(state)
        self.request(state)
        self.assertEqual(state.collector.poll_bridge(), 0)
        self.assertEqual(state.collector.app, state.app)
        self.assertNotEqual(state.collector.app, old_app)
        for key in ("source_run_id", "target_run_id"):
            self.assertFalse((state.app / "tmp/RoomInventoryUITests" / state.config[key]).exists())
        pins = copy.deepcopy(state.collector.pins)
        state.app.rename(state.root / "lost-final-aut")
        with patch.object(state.collector, "_poll_installation", side_effect=AssertionError("rediscovery forbidden")):
            with self.assertRaises(FileNotFoundError): state.collector.poll_bridge()
        self.assertEqual(state.collector.pins, pins)
        self.assertEqual(state.collector.installation_state, "accepted")

    def test_warmup_must_have_only_empty_assets_and_regular_zero_byte_lock(self):
        for mode in ("missing-assets", "missing-lock", "nonempty-lock", "manifest", "original",
                     "extra-directory", "asset-symlink", "lock-symlink", "wrong-namespace"):
            with self.subTest(mode=mode):
                state = self.install(self.fixture())
                path = state.app / "tmp/RoomInventoryUITests" / state.config["journey_run_id"]
                if mode == "missing-assets": (path / "assets").rmdir()
                elif mode == "missing-lock": (path / ".repository.lock").unlink()
                elif mode == "nonempty-lock": (path / ".repository.lock").write_bytes(b"prior data")
                elif mode == "manifest": (path / "inventory.json").write_bytes(b'{"homes":[]}')
                elif mode == "original": (path / "assets/original.png").write_bytes(b"prior photo")
                elif mode == "extra-directory": (path / "unexpected").mkdir()
                elif mode == "asset-symlink":
                    (path / "assets").rmdir(); (path / "assets").symlink_to(state.root, target_is_directory=True)
                elif mode == "lock-symlink":
                    (path / ".repository.lock").unlink(); (path / ".repository.lock").symlink_to(state.fixture)
                else: path.rename(path.with_name("55555555-5555-4555-8555-555555555555"))
                self.request(state)
                with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
                self.assertFalse((state.bridge / "installation-ack.json").exists())
                self.assertEqual(state.collector.installation_state, "binding")

    def test_warmup_change_during_receipt_write_cannot_publish_final_ack(self):
        state = self.install(self.fixture()); self.request(state)
        changed = []
        def mutate():
            if not changed and (state.collector.root / "bridge/installation-receipt.json").exists():
                changed.append(True)
                path = state.app / "tmp/RoomInventoryUITests" / state.config["journey_run_id"]
                (path / "assets/unexpected").write_bytes(b"late data")
        state.guard_hook = mutate
        with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
        self.assertTrue(changed)
        self.assertFalse((state.bridge / "installation-ack.json").exists())
        self.assertEqual(state.collector.installation_state, "binding")

    def test_photos_receipt_is_retained_before_export_and_immutable(self):
        state = self.photos_state()
        raw = self.photos_receipt(state)
        self.assertEqual(state.collector.poll_bridge(), 0)
        self.assertTrue(state.collector.photos_isolated)
        self.assertEqual((state.collector.root / "bridge/photos-isolation.json").read_bytes(), raw)
        (state.bridge / "photos-isolation.json").write_bytes(raw + b" ")
        with self.assertRaisesRegex(C.CollectorError, "receipt changed"):
            state.collector.poll_bridge()

    def test_photos_missing_receipt_never_acknowledges_an_export(self):
        state = self.photos_state()
        request = {"schema_version": 1, **state.collector.ids, "sequence": 1,
                   "role": "source_zip", "phase": "before", "nonce": "55555555-5555-4555-8555-555555555555"}
        (state.bridge / "request-01.json").write_bytes(C.canonical(request))
        with self.assertRaisesRegex(C.CollectorError, "Photos isolation missing"):
            state.collector.poll_bridge()
        self.assertFalse((state.bridge / "ack-01.json").exists())

    def test_photos_postinstallation_full_authorization_requires_exact_callback_and_prompt(self):
        valid = {"before_raw": 0, "after_raw": 3, "requested": True, "callback_raw": 3,
                 "prompt_seen": True, "prompt_accepted": True, "prompt_runner": "RoomInventoryUITests-Runner",
                 "prompt_text": "“RoomInventoryUITests-Runner” Would Like Full Access to Your Photo Library\nAccess is necessary for automated testing.",
                 "prompt_button": "Allow Full Access"}
        state = self.photos_state(); self.photos_receipt(state, authorization=valid)
        self.assertEqual(state.collector.poll_bridge(), 0)
        self.assertTrue(state.collector.photos_isolated)
        for change in ({"before_raw": 2}, {"before_raw": 4}, {"before_raw": False}, {"after_raw": 4},
                       {"after_raw": True}, {"callback_raw": None}, {"callback_raw": 4}, {"requested": False},
                       {"prompt_seen": False}, {"prompt_accepted": False}, {"prompt_runner": "Other App"},
                       {"prompt_text": "unrelated prompt"}, {"prompt_button": "Select Photos…"}):
            with self.subTest(change=change):
                state = self.photos_state(); self.photos_receipt(state, authorization={**valid, **change})
                with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
                self.assertFalse(state.collector.photos_isolated)
                self.assertFalse((state.bridge / "ack-01.json").exists())

    def test_photos_authorized_callback_without_prompt_does_not_claim_interaction(self):
        automatic = {"before_raw": 0, "after_raw": 3, "requested": True, "callback_raw": 3,
                     "prompt_seen": False, "prompt_accepted": False,
                     "prompt_runner": "", "prompt_text": "", "prompt_button": ""}
        state = self.photos_state(); raw = self.photos_receipt(state, authorization=automatic)
        self.assertEqual(state.collector.poll_bridge(), 0)
        self.assertTrue(state.collector.photos_isolated)
        self.assertEqual((state.collector.root / "bridge/photos-isolation.json").read_bytes(), raw)
        for change in ({"callback_raw": None}, {"callback_raw": 2}, {"after_raw": 4},
                       {"prompt_seen": True}, {"prompt_accepted": True},
                       {"prompt_runner": "RoomInventoryUITests-Runner"}, {"prompt_text": "unobserved"},
                       {"prompt_button": "Allow Full Access"}):
            with self.subTest(change=change):
                state = self.photos_state(); self.photos_receipt(state, authorization={**automatic, **change})
                with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
                self.assertFalse(state.collector.photos_isolated)
                self.assertFalse((state.bridge / "ack-01.json").exists())

    def test_photos_foreign_incomplete_overdue_and_changed_original_receipts_fail(self):
        variants = [{"simulator_udid": "foreign"}, {"installation_request_sha256": "0" * 64},
                    {"runner_bundle_id": "com.alvit.roominventory"}, {"schema_version": True},
                    {"final_asset_count": 7}, {"initial_asset_count": 65, "removed_asset_count": 64},
                    {"initial_asset_count": True}, {"removed_asset_count": 5}, {"after_bytes": 0},
                    {"before_sha256": "0" * 64}, {"after_sha256": "0" * 64},
                    {"read_write_authorized": False}, {"change_completed": False}, {"confirmation_accepted": False},
                    {"change_requested": False}, {"finished_within_deadline": False},
                    {"elapsed_seconds": 20}, {"elapsed_seconds": True}, {"unknown": "field"}]
        for changes in variants:
            with self.subTest(changes=changes):
                state = self.photos_state(); self.photos_receipt(state, **changes)
                with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
                self.assertFalse(state.collector.photos_isolated)
                self.assertFalse((state.bridge / "ack-01.json").exists())

    def test_photos_failed_callback_receipt_is_saved_but_never_accepted(self):
        state = self.photos_state()
        raw = self.photos_receipt(state, status="failed", error="change callback deadline", change_completed=False)
        with self.assertRaisesRegex(C.CollectorError, "change callback deadline"):
            state.collector.poll_bridge()
        self.assertEqual((state.collector.root / "bridge/photos-isolation.json").read_bytes(), raw)
        self.assertFalse(state.collector.photos_isolated)
        with self.assertRaisesRegex(C.CollectorError, "previously failed"):
            state.collector.poll_bridge()

    def test_photos_receipt_symlink_and_source_fixture_change_are_rejected(self):
        state = self.photos_state(); raw = self.photos_receipt(state)
        path = state.bridge / "photos-isolation.json"; path.unlink()
        target = state.root / "foreign.json"; target.write_bytes(raw); path.symlink_to(target)
        with self.assertRaisesRegex(C.CollectorError, "symlink"):
            state.collector.poll_bridge()
        state = self.photos_state(); self.photos_receipt(state)
        state.fixture.write_bytes(b"changed fixture")
        with self.assertRaisesRegex(C.CollectorError, "fixture source changed"):
            state.collector.poll_bridge()

    def test_photos_already_isolated_single_fixture_does_not_require_a_change(self):
        state = self.photos_state()
        self.seed_receipt(state, initial_ids=[])
        self.photos_receipt(state, initial_asset_count=1, removed_asset_count=0, change_requested=False,
                            confirmation_seen=False, confirmation_accepted=False, confirmation_text="")
        self.assertEqual(state.collector.poll_bridge(), 0)
        self.assertTrue(state.collector.photos_isolated)


    def test_seed_receipt_is_persisted_before_isolation_and_never_reaccepted_after_failure(self):
        state = self.photos_state()
        raw = self.seed_receipt(state, status="failed", error="PhotoKit callback late", change_completed=False)
        with self.assertRaisesRegex(C.CollectorError, "Photos seed failed: PhotoKit callback late"):
            state.collector.poll_bridge()
        self.assertEqual((state.collector.root / "bridge/photos-seed.json").read_bytes(), raw)
        self.assertIsNone(state.collector.photos_seed)
        self.assertFalse(state.collector.photos_isolated)
        with self.assertRaisesRegex(C.CollectorError, "previously failed"): state.collector.poll_bridge()

    def test_partial_seed_failure_before_first_checkpoint_is_retained(self):
        state = self.photos_state()
        value = state.collector._photos_identity("photos_seed")
        value.update(status="failed", error="authorization deadline")
        raw = C.canonical(value)
        (state.bridge / "photos-seed.json").write_bytes(raw)
        with self.assertRaisesRegex(C.CollectorError, "Photos seed failed: authorization deadline"):
            state.collector.poll_bridge()
        self.assertEqual((state.collector.root / "bridge/photos-seed.json").read_bytes(), raw)
        self.assertEqual(state.collector.barriers, [])

    def test_seed_requires_ack_and_isolation_requires_seed(self):
        state = self.fixture(); self.install(state)
        with self.assertRaisesRegex(C.CollectorError, "installation acknowledgement"): state.collector._poll_photos_seed()
        state = self.photos_state(); self.photos_receipt(state)
        (state.bridge / "photos-seed.json").unlink()
        with self.assertRaisesRegex(C.CollectorError, "seed missing before isolation"): state.collector.poll_bridge()

    def test_seed_identity_and_mutation_proofs_fail_closed(self):
        variants = [{"simulator_udid": "foreign"}, {"installation_request_sha256": "0" * 64},
                    {"runner_bundle_id": "com.alvit.roominventory"}, {"schema_version": True},
                    {"bundle_resource_filename": "SyntheticRecoveryReceipt.png"}, {"fixture_bytes": 0},
                    {"before_sha256": "0" * 64}, {"after_sha256": "0" * 64}, {"after_bytes": 0},
                    {"existing_fixture_count": 1}, {"existing_fixture_count": False},
                    {"mutation_attempts": 0}, {"mutation_attempts": 2}, {"mutation_attempts": True},
                    {"change_requested": False}, {"change_completed": False}, {"read_write_authorized": False},
                    {"finished_within_deadline": False}, {"elapsed_seconds": 86}, {"elapsed_seconds": -1},
                    {"elapsed_seconds": True}, {"elapsed_seconds": float("inf")}, {"elapsed_seconds": float("nan")},
                    {"created_asset_id": "default-0"}, {"created_asset_id": "foreign"},
                    {"initial_asset_count": True}, {"final_asset_count": 0}, {"initial_asset_ids_sha256": "0" * 64},
                    {"final_asset_ids_sha256": "0" * 64}, {"unknown": 1}, {"deadline_seconds": 87}]
        for change in variants:
            with self.subTest(change=change):
                state = self.photos_state(); self.seed_receipt(state, **change)
                with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
                self.assertIsNone(state.collector.photos_seed)
                self.assertFalse(state.collector.photos_isolated)

    def test_seed_arrays_require_exact_new_asset_even_with_updated_digests(self):
        for initial, final in [(["a", "a"], ["a", "a", "synthetic-owned-asset/L0/001"]),
                               (["b", "a"], ["a", "b", "synthetic-owned-asset/L0/001"]),
                               (["a"], ["replacement", "synthetic-owned-asset/L0/001"]),
                               (["a"], ["a", "new", "synthetic-owned-asset/L0/001"]),
                               (["bad\nID"], ["bad\nID", "synthetic-owned-asset/L0/001"]),
                               ([str(i) for i in range(64)], [str(i) for i in range(64)] + ["synthetic-owned-asset/L0/001"])]:
            with self.subTest(initial=initial):
                state = self.photos_state()
                self.seed_receipt(state, initial_asset_ids=initial, initial_asset_count=len(initial),
                                  initial_asset_ids_sha256=C.sha("\n".join(initial).encode()),
                                  final_asset_ids=final, final_asset_count=len(final),
                                  final_asset_ids_sha256=C.sha("\n".join(final).encode()))
                with self.assertRaises(C.CollectorError): state.collector.poll_bridge()

    def test_seed_authorization_failure_does_not_admit_isolation(self):
        state = self.photos_state(); raw = self.seed_receipt(state)
        value = C.parse(raw); value["authorization"]["after_raw"] = 4
        (state.bridge / "photos-seed.json").write_bytes(C.canonical(value))
        with self.assertRaisesRegex(C.CollectorError, "full authorization"): state.collector.poll_bridge()

    def test_seed_is_immutable_and_cannot_disappear(self):
        for remove in (False, True):
            state = self.photos_state(); raw = self.seed_receipt(state)
            self.assertEqual(state.collector.poll_bridge(), 0)
            self.assertIsNotNone(state.collector.photos_seed)
            self.assertFalse(state.collector.photos_isolated)
            path = state.bridge / "photos-seed.json"
            if remove: path.unlink()
            else: path.write_bytes(raw + b" ")
            with self.assertRaisesRegex(C.CollectorError, "seed receipt (disappeared|changed)"): state.collector.poll_bridge()

    def test_isolation_must_keep_same_seed_asset_and_inventory(self):
        for change in ({"seed_receipt_sha256": "0" * 64}, {"fixture_asset_id": "another-asset"},
                       {"initial_asset_ids_sha256": "0" * 64}, {"removed_asset_ids_sha256": "0" * 64},
                       {"initial_asset_count": 6, "removed_asset_count": 5}):
            state = self.photos_state(); self.photos_receipt(state, **change)
            with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
            self.assertFalse(state.collector.photos_isolated)

    def test_seed_upper_inventory_bound_uses_own_bounded_receipt(self):
        state = self.photos_state()
        ids = [f"{i:03}-" + "a" * 250 for i in range(63)]
        raw = self.seed_receipt(state, initial_ids=ids)
        self.assertGreater(len(raw), 16384)
        self.assertLess(len(raw), 65536)
        self.assertEqual(state.collector.poll_bridge(), 0)
        self.assertIsNotNone(state.collector.photos_seed)

    def test_seed_symlink_and_oversized_receipt_rejected(self):
        for mode in ("symlink", "oversize"):
            state = self.photos_state(); raw = self.seed_receipt(state)
            path = state.bridge / "photos-seed.json"
            if mode == "symlink":
                path.unlink(); other = state.root / "outside.json"; other.write_bytes(raw); path.symlink_to(other)
            else: path.write_bytes(raw + b" " * 65536)
            with self.assertRaises(C.CollectorError): state.collector.poll_bridge()
