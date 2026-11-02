"""Malformed on-disk artifacts, not native UI execution or simulator tests."""
import base64
import copy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("recovery_verifier", ROOT / "scripts/verify-recovery-journey.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
PIN = "d49d2ec21e5faf1ce5916f102fef4596b7fa25bf"
JOURNEY = "11111111-1111-4111-8111-111111111111"
SOURCE = "22222222-2222-4222-8222-222222222222"
TARGET = "33333333-3333-4333-8333-333333333333"
HOME = "44444444-4444-4444-8444-444444444444"
ROOM = "55555555-5555-4555-8555-555555555555"
ITEM = "66666666-6666-4666-8666-666666666666"
ORIGINAL = "77777777-7777-4777-8777-777777777777"
HEADERS = "home_id,home,room_id,room,item_id,item,model,serial_number,purchase_price,purchase_date,notes,attachment_id,attachment_kind,attachment_path,original_name,media_type,sha256".split(",")
STEPS = "source_empty_free item_before_ocr photos_receipt_selected ocr_review_unselected ocr_selection_model_price source_item_after_ocr source_free source_zip_saved backup_saved target_empty_free restore_confirmation target_restored target_relaunched original_preview recovered_zip_saved target_free complete".split()
# Deliberately separate fixture construction from the verifier implementation.
# This lightweight PDF is only for the verifier's stated structural check.
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


class RecoveryJourneyVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = (ROOT / "UITests/Fixtures/SyntheticRecoveryReceipt.png").read_bytes()
        self.assertEqual(len(self.fixture), 74736)
        self.assertEqual(hashlib.sha256(self.fixture).hexdigest(), "3be0a311997c35182f58e2658f64afe06b437665dfb420f1dc595e23e24ea181")
        self.filename = ORIGINAL.lower() + ".png"
        self.item = {"id": ITEM, "name": "Recovery Item 11111111", "model": "VISTA-420", "serialNumber": "KEEP-SERIAL",
                     "purchasePrice": "USD149.50", "purchaseDate": "2025-01-01", "notes": "Recovery receipt QA",
                     "attachments": [{"id": ORIGINAL, "kind": "receipt", "fileName": self.filename, "originalName": "Photo-TEST.png",
                                      "mediaType": "image/png", "sha256": hashlib.sha256(self.fixture).hexdigest()}]}
        self.inventory = {"schemaVersion": 1, "homes": [{"id": HOME, "name": "Recovery Home 11111111", "rooms": [
            {"id": ROOM, "name": "Recovery Room 11111111", "items": [self.item]}]}]}
        self.paths = {"fixture": "fixture.png", "source_inventory": "source/inventory.json", "target_inventory": "target/inventory.json",
                      "source_original": "source/assets/" + self.filename, "target_original": "target/assets/" + self.filename,
                      "source_zip": "files/source.zip", "backup": "files/backup.roominventory", "target_zip": "files/recovered.zip",
                      "source_generated_zip": "generated/source/Inventory-package.zip", "generated_backup": "generated/backup/Inventory.roominventory",
                      "target_generated_zip": "generated/recovered/Inventory-package.zip"}
        expected = {"home_name": "Recovery Home 11111111", "room_name": "Recovery Room 11111111", "item_name": "Recovery Item 11111111", "notes": "Recovery receipt QA"}
        before = {"model": "BEFORE-MODEL", "serial": "KEEP-SERIAL", "price": "USD 1.00", "date": "2025-01-01", "notes": "Recovery receipt QA"}
        after = {**before, "model": "VISTA-420", "price": "USD149.50"}
        self.ui = {"schema_version": 1, "journey_run_id": JOURNEY, "source_run_id": SOURCE, "target_run_id": TARGET,
                   "outcome": "passed", "expected": expected, "events": [], "issues": []}
        self.ui_attachments = {}
        for index, name in enumerate(STEPS, 1):
            observations = {}
            if name == "item_before_ocr": observations = before.copy()
            if name in {"source_item_after_ocr", "target_restored", "target_relaunched"}: observations = after.copy()
            if name.startswith("ocr_"):
                observations = {"model": "VISTA-420", "serial": "QA-2026-0042", "price": "USD149.50", "date": "2026-10-20"}
                observations.update({"selected." + key: "1" if name == "ocr_selection_model_price" and key in {"model", "price"} else "0" for key in ["model", "serial", "price", "date"]})
            if name in {"source_empty_free", "target_empty_free"}: observations = {"empty_label": "Add your first home", "free_label": "Explore Pro"}
            if name in {"source_free", "target_free"}: observations = {"free_label": "Explore Pro"}
            if name == "restore_confirmation": observations = {"warning": "Replace the current inventory?"}
            if name == "original_preview": observations = {"original_name": "Photo-TEST.png", "image_label": "Receipt"}
            if name == "photos_receipt_selected": observations = {"purpose": "Receipt", "photo_label": "Photo, October 20"}
            for step, prefix in [("source_zip_saved", "source-"), ("backup_saved", "backup-"), ("recovered_zip_saved", "recovered-")]:
                if name == step: observations = {"save_name": prefix + JOURNEY, "folder": "Recovery-" + JOURNEY}
            refs = {"screenshot": f"{index}-screen", "accessibility": f"{index}-ax"}
            for kind, attachment in refs.items():
                path = f"ui/{attachment}.{'png' if kind == 'screenshot' else 'txt'}"
                self.ui_attachments[attachment] = path
                self.write(path, self.fixture if kind == "screenshot" else b"Synthetic unit-test accessibility evidence; no UI ran.")
            self.ui["events"].append({"sequence": index, "name": name, "run_id": SOURCE if index <= 9 else TARGET,
                                      "observations": observations, "assertions": [{"name": "reported checkpoint", "actual": "present", "expected": "present", "passed": True}], "attachments": refs})
        self.manifest = {"schema_version": 1, "source_commit": PIN, "source_run_id": SOURCE, "target_run_id": TARGET,
                         "ui_evidence": "ui-evidence.json", "ui_attachments": self.ui_attachments,
                         "artifacts": self.paths, "collection_receipt": "collection-receipt.json"}
        for role in ["fixture", "source_original", "target_original"]: self.write(self.paths[role], self.fixture)
        self.regenerate()
        self.save_json("collection.json", self.manifest)
        self.save_json("ui-evidence.json", self.ui)

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def save_json(self, path, data):
        self.write(path, json.dumps(data, ensure_ascii=False).encode())

    def csv_bytes(self, rows):
        output = io.StringIO(newline="")
        writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerows(rows)
        return output.getvalue().encode()

    def zip_files(self):
        home = self.inventory["homes"][0]
        room = home["rooms"][0]
        item = room["items"][0]
        original = item["attachments"][0]
        path = f"originals/{item['id']}/{original['fileName']}"
        row = [home["id"], home["name"], room["id"], room["name"], item["id"], item["name"], item["model"], item["serialNumber"],
               item["purchasePrice"], item["purchaseDate"], item["notes"], original["id"], original["kind"], path,
               original["originalName"], original["mediaType"], original["sha256"]]
        localized = row.copy()
        localized[12] = "Receipt"
        return {"Inventory.csv": self.csv_bytes([HEADERS, row]), "Inventory-localized.csv": self.csv_bytes([["Column " + str(i) for i in range(17)], localized]),
                "Inventory.pdf": PDF, "README.txt": b"Synthetic export description", path: self.fixture}

    def encode_zip(self, files):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in files.items(): archive.writestr(name, data)
        return output.getvalue()

    def regenerate(self):
        for role in ["source_inventory", "target_inventory"]: self.save_json(self.paths[role], self.inventory)
        self.backup = {"format": "com.alvit.roominventory.backup", "version": 1, "inventory": copy.deepcopy(self.inventory),
                       "files": {self.filename: base64.b64encode(self.fixture).decode()}}
        self.save_backup()
        blob = self.encode_zip(self.zip_files())
        for role in ["source_zip", "target_zip", "source_generated_zip", "target_generated_zip"]: self.write(self.paths[role], blob)
        self.refresh_receipt()

    def save_backup(self):
        for role in ["backup", "generated_backup"]: self.save_json(self.paths[role], self.backup)

    def refresh_receipt(self):
        entries = []
        for index, (role, generated, filename, prefix, ext) in enumerate([
            ("source_zip", "source_generated_zip", "Inventory-package.zip", "source-", "zip"),
            ("backup", "generated_backup", "Inventory.roominventory", "backup-", "roominventory"),
            ("target_zip", "target_generated_zip", "Inventory-package.zip", "recovered-", "zip")], 1):
            data = (self.root / self.paths[generated]).read_bytes()
            directory = f"9999999{index}-9999-4999-8999-999999999999"
            entries.append({"role": role, "directory_id": directory, "generated_path": f"tmp/InventoryExports/{directory}/{filename}",
                            "device_id": 42, "inode": 100 + index, "created_at_ns": 1000 + index, "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(), "saved_path": f"Recovery-{JOURNEY}/{prefix}{JOURNEY}.{ext}"})
        self.receipt = {"schema_version": 1, "journey_run_id": JOURNEY, "source_run_id": SOURCE, "target_run_id": TARGET,
                        "exports_before": [], "exports_after": entries}
        self.save_json("collection-receipt.json", self.receipt)

    def verify(self):
        return VERIFIER.verify_collection(self.root / "collection.json", PIN)

    def reject(self, phrase):
        with self.assertRaisesRegex(VERIFIER.EvidenceError, phrase): self.verify()

    def replace_target_zip(self, files):
        blob = self.encode_zip(files)
        for role in ["target_zip", "target_generated_zip"]: self.write(self.paths[role], blob)
        self.refresh_receipt()

    def test_valid_collected_artifacts_do_not_claim_ui_execution(self):
        result = self.verify()
        self.assertEqual(result["status"], "PASS_OFFLINE_ARTIFACT_CONSISTENCY")
        self.assertEqual(result["ui_execution"], "NOT_INDEPENDENTLY_VERIFIED")
        self.assertEqual(result["recorded_checkpoints"], 17)
        self.assertEqual((self.root / self.paths["source_zip"]).read_bytes(), (self.root / self.paths["target_zip"]).read_bytes(), "Distinct exports are allowed to have identical bytes")

    def test_pdf_metadata_difference_between_exports_is_allowed(self):
        files = self.zip_files()
        files["Inventory.pdf"] = PDF.replace(b"trailer", b"% Second export timestamp\ntrailer")
        self.replace_target_zip(files)
        self.assertEqual(self.verify()["status"], "PASS_OFFLINE_ARTIFACT_CONSISTENCY")

    def test_allowed_ocr_spacing_is_preserved_in_all_final_artifacts(self):
        self.item["purchasePrice"] = "USD 149.50"
        self.regenerate()
        for event in self.ui["events"]:
            if event["name"] in {"source_item_after_ocr", "target_restored", "target_relaunched", "ocr_review_unselected", "ocr_selection_model_price"}: event["observations"]["price"] = "USD 149.50"
        self.save_json("ui-evidence.json", self.ui)
        self.verify()

    def test_unselected_or_unintentionally_selected_ocr_field_is_rejected(self):
        event = next(event for event in self.ui["events"] if event["name"] == "ocr_selection_model_price")
        for field in ("model", "serial", "price", "date"):
            key = "selected." + field
            original = event["observations"][key]
            with self.subTest(field=field):
                event["observations"][key] = "0" if original == "1" else "1"
                self.save_json("ui-evidence.json", self.ui)
                self.reject("OCR selection differs")
            event["observations"][key] = original

    def test_normalizing_ocr_price_in_storage_is_rejected(self):
        self.item["purchasePrice"] = "USD 149.50"
        self.regenerate()
        self.reject("fixed selective-Apply")

    def test_internally_consistent_altered_metadata_is_rejected(self):
        self.item["serialNumber"] = "QA-2026-0042"
        self.regenerate()
        self.reject("fixed selective-Apply")

    def test_changing_reported_expected_fields_does_not_allow_altered_data(self):
        self.ui["expected"]["notes"] = "replacement"
        self.item["notes"] = "replacement"
        self.regenerate()
        self.save_json("ui-evidence.json", self.ui)
        self.reject("fixed scenario names")

    def test_target_schema_boolean_is_not_equal_to_integer_one(self):
        target = copy.deepcopy(self.inventory)
        target["schemaVersion"] = True
        self.save_json(self.paths["target_inventory"], target)
        self.reject("inventory schema")

    def test_embedded_backup_schema_boolean_is_rejected(self):
        self.backup["inventory"]["schemaVersion"] = True
        self.save_backup()
        self.refresh_receipt()
        self.reject("inventory schema")

    def test_changed_target_identity_is_rejected(self):
        target = copy.deepcopy(self.inventory)
        target["homes"][0]["id"] = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
        self.save_json(self.paths["target_inventory"], target)
        self.reject("metadata or identities")

    def test_missing_zip_original_is_rejected(self):
        files = self.zip_files()
        del files[f"originals/{ITEM}/{self.filename}"]
        self.replace_target_zip(files)
        self.reject("ZIP members")

    def test_substituted_zip_original_is_rejected(self):
        files = self.zip_files()
        files[f"originals/{ITEM}/{self.filename}"] = b"substituted original"
        self.replace_target_zip(files)
        self.reject("ZIP original differs")

    def test_substituted_stored_original_is_rejected(self):
        self.write(self.paths["target_original"], b"not the original PNG")
        self.reject("Stored original differs")

    def test_csv_wrong_item_association_is_rejected(self):
        files = self.zip_files()
        files["Inventory.csv"] = files["Inventory.csv"].replace(ITEM.encode(), HOME.encode())
        self.replace_target_zip(files)
        self.reject("Machine CSV metadata")

    def test_missing_regenerated_pdf_is_rejected(self):
        files = self.zip_files()
        del files["Inventory.pdf"]
        self.replace_target_zip(files)
        self.reject("ZIP members")

    def test_truncated_regenerated_pdf_is_rejected(self):
        files = self.zip_files()
        files["Inventory.pdf"] = PDF[:90]
        self.replace_target_zip(files)
        self.reject("truncated PDF")

    def test_zip_duplicate_member_is_rejected(self):
        output = io.BytesIO(self.encode_zip(self.zip_files()))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(output, "a") as archive: archive.writestr("Inventory.csv", b"duplicate")
        for role in ["target_zip", "target_generated_zip"]: self.write(self.paths[role], output.getvalue())
        self.refresh_receipt()
        self.reject("Duplicate ZIP")

    def test_zip_escaping_member_is_rejected(self):
        files = self.zip_files()
        files["../outside.png"] = self.fixture
        self.replace_target_zip(files)
        self.reject("ZIP members")

    def test_invalid_backup_base64_is_rejected(self):
        self.backup["files"][self.filename] = "%%%"
        self.save_backup()
        self.refresh_receipt()
        self.reject("base64")

    def test_backup_missing_original_is_rejected(self):
        self.backup["files"] = {}
        self.save_backup()
        self.refresh_receipt()
        self.reject("backup originals")

    def test_wrong_backup_version_is_rejected(self):
        self.backup["version"] = 2
        self.save_backup()
        self.refresh_receipt()
        self.reject("backup format/version")

    def test_duplicate_json_key_is_rejected(self):
        raw = (self.root / self.paths["source_inventory"]).read_bytes()
        self.write(self.paths["source_inventory"], raw.replace(b'"schemaVersion": 1', b'"schemaVersion": 2, "schemaVersion": 1'))
        self.reject("Duplicate JSON key")

    def test_missing_collection_receipt_is_rejected(self):
        (self.root / "collection-receipt.json").unlink()
        self.reject("Cannot read collection receipt")

    def test_reused_generated_export_directory_is_rejected(self):
        self.receipt["exports_after"][2]["directory_id"] = self.receipt["exports_after"][0]["directory_id"]
        self.save_json("collection-receipt.json", self.receipt)
        self.reject("directory reused")

    def test_reused_generated_file_identity_is_rejected(self):
        self.receipt["exports_after"][2]["inode"] = self.receipt["exports_after"][0]["inode"]
        self.save_json("collection-receipt.json", self.receipt)
        self.reject("file identity")

    def test_saved_files_copy_must_match_generated_payload(self):
        self.write(self.paths["source_zip"], b"different saved copy")
        self.reject("Saved Files copy differs")

    def test_wrong_namespace_and_out_of_order_ui_are_rejected(self):
        self.ui["events"][9]["run_id"] = SOURCE
        self.save_json("ui-evidence.json", self.ui)
        self.reject("wrong namespace")
        self.ui["events"][9]["run_id"] = TARGET
        self.ui["events"][0], self.ui["events"][1] = self.ui["events"][1], self.ui["events"][0]
        self.save_json("ui-evidence.json", self.ui)
        self.reject("out of order")

    def test_journey_identifier_cannot_reuse_a_namespace(self):
        self.ui["journey_run_id"] = SOURCE
        self.save_json("ui-evidence.json", self.ui)
        self.reject("identifiers must all differ")

    def test_missing_ui_attachment_is_rejected(self):
        (self.root / "ui/14-screen.png").unlink()
        self.reject("Cannot read UI screenshot")

    def test_missing_critical_ui_observations_do_not_pass_on_generic_assertions(self):
        steps = ["source_empty_free", "target_empty_free", "source_free", "target_free", "restore_confirmation",
                 "original_preview", "source_zip_saved", "backup_saved", "recovered_zip_saved", "photos_receipt_selected"]
        for name in steps:
            with self.subTest(step=name):
                ui = copy.deepcopy(self.ui)
                next(event for event in ui["events"] if event["name"] == name)["observations"] = {}
                self.save_json("ui-evidence.json", ui)
                self.reject("UI observations|receipt picker")

    def test_reported_issues_reject_otherwise_passed_ui_evidence(self):
        self.ui["issues"] = ["a recorded XCTest failure"]
        self.save_json("ui-evidence.json", self.ui)
        self.reject("UI evidence has issues")

    def test_nonimage_screenshot_and_reused_ui_path_are_rejected(self):
        self.write("ui/14-screen.png", b"not a screenshot")
        self.reject("not a PNG or JPEG")
        self.write("ui/14-screen.png", self.fixture)
        self.manifest["ui_attachments"]["14-screen"] = self.manifest["ui_attachments"]["1-screen"]
        self.save_json("collection.json", self.manifest)
        self.reject("distinct collected paths")

    def test_additional_backup_original_is_rejected(self):
        self.backup["files"]["extra.png"] = base64.b64encode(self.fixture).decode()
        self.save_backup()
        self.refresh_receipt()
        self.reject("backup originals")

    def test_internally_consistent_altered_model_price_and_date_are_rejected(self):
        for field, value in [("model", "ALTERED"), ("purchasePrice", "USD 149.51"), ("purchaseDate", "2026-10-20")]:
            with self.subTest(field=field):
                original = self.item[field]
                self.item[field] = value
                self.regenerate()
                self.reject("fixed selective-Apply")
                self.item[field] = original

    def test_more_than_one_inventory_original_is_rejected(self):
        self.item["attachments"].append(copy.deepcopy(self.item["attachments"][0]))
        self.regenerate()
        self.reject("exactly one original")

    def test_incorrect_localized_csv_values_are_rejected(self):
        files = self.zip_files()
        files["Inventory-localized.csv"] = files["Inventory-localized.csv"].replace(b"KEEP-SERIAL", b"CHANGED")
        self.replace_target_zip(files)
        self.reject("Localized CSV altered")

    def test_bool_versions_and_integer_assertion_are_rejected(self):
        for location in ["collection", "ui", "backup", "receipt"]:
            with self.subTest(location=location):
                manifest, ui, backup, receipt = map(copy.deepcopy, [self.manifest, self.ui, self.backup, self.receipt])
                doc = {"collection": manifest, "ui": ui, "backup": backup, "receipt": receipt}[location]
                doc["version" if location == "backup" else "schema_version"] = True
                self.save_json("collection.json", manifest)
                self.save_json("ui-evidence.json", ui)
                self.save_json(self.paths["backup"], backup)
                self.save_json("collection-receipt.json", receipt)
                self.reject("schema|format/version")
        self.save_json("collection-receipt.json", self.receipt)
        self.ui["events"][0]["assertions"][0]["passed"] = 1
        self.save_json("ui-evidence.json", self.ui)
        self.reject("UI assertion failed")

    def test_outside_path_is_rejected(self):
        self.manifest["artifacts"]["fixture"] = "../fixture.png"
        self.save_json("collection.json", self.manifest)
        self.reject("Unsafe path")

    def test_caller_pin_and_reported_result_fail_closed(self):
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "caller-pinned"):
            VERIFIER.verify_collection(self.root / "collection.json", "0" * 40)
        self.ui["outcome"] = "failed"
        self.save_json("ui-evidence.json", self.ui)
        self.reject("passed journey")

    def test_cli_returns_nonzero_json_for_malformed_evidence(self):
        self.write(self.paths["target_original"], b"bad")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/verify-recovery-journey.py"), str(self.root / "collection.json"), "--expected-commit", PIN], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
