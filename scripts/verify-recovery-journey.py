#!/usr/bin/env python3
"""Validate explicitly collected recovery artifacts; never infer that UI ran.

Usage: verify-recovery-journey.py collection.json --expected-commit <40-hex-sha>
The collection and all referenced files must live inside one evidence directory.
No latest-file discovery, simulator access, service calls, or native tools occur.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import uuid
import zipfile

FIXTURE_SHA256 = "3be0a311997c35182f58e2658f64afe06b437665dfb420f1dc595e23e24ea181"
FIXTURE_BYTES = 74736
MAX_BYTES = 8 * 1024 * 1024
STEPS = (
    "source_empty_free", "item_before_ocr", "photos_receipt_selected",
    "ocr_review_unselected", "ocr_selection_model_price", "source_item_after_ocr",
    "source_free", "source_zip_saved", "backup_saved", "target_empty_free",
    "restore_confirmation", "target_restored", "target_relaunched",
    "original_preview", "recovered_zip_saved", "target_free", "complete",
)
INITIAL = {"model": "BEFORE-MODEL", "serial": "KEEP-SERIAL", "price": "USD 1.00",
           "date": "2025-01-01", "notes": "Recovery receipt QA"}
FINAL = {**INITIAL, "model": "VISTA-420", "price": "USD 149.50"}
OCR = {"model": "VISTA-420", "serial": "QA-2026-0042", "price": "USD 149.50", "date": "2026-10-20"}
HEADERS = ["home_id", "home", "room_id", "room", "item_id", "item", "model", "serial_number",
           "purchase_price", "purchase_date", "notes", "attachment_id", "attachment_kind",
           "attachment_path", "original_name", "media_type", "sha256"]
ARTIFACTS = {"fixture", "source_inventory", "target_inventory", "source_original",
             "target_original", "source_zip", "backup", "target_zip",
             "source_generated_zip", "generated_backup", "target_generated_zip"}


class EvidenceError(ValueError):
    """An artifact does not satisfy the bounded, fixed recovery scenario."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(data: bytes, label: str):
    try:
        return json.loads(data, object_pairs_hook=unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(EvidenceError(f"Invalid JSON number: {value}")))
    except (UnicodeDecodeError, ValueError) as error:
        raise EvidenceError(f"Invalid JSON in {label}: {error}") from error


def identifier(value, label: str) -> str:
    require(isinstance(value, str), f"{label} must be a UUID string")
    try:
        normalized = str(uuid.UUID(value)).upper()
    except ValueError as error:
        raise EvidenceError(f"Invalid UUID for {label}") from error
    require(value.upper() == normalized, f"Noncanonical UUID for {label}")
    return normalized


def keys(value, expected, label: str) -> None:
    require(isinstance(value, dict) and set(value) == set(expected), f"Wrong fields in {label}")


class Collection:
    def __init__(self, manifest: Path):
        self.root = manifest.resolve().parent
        self.hashes = {}

    def read(self, relative, label: str) -> bytes:
        require(isinstance(relative, str) and bool(relative), f"Missing path for {label}")
        path = PurePosixPath(relative)
        require(not path.is_absolute() and ".." not in path.parts and "\\" not in relative
                and path.as_posix() == relative,
                f"Unsafe path for {label}")
        target = self.root.joinpath(*path.parts)
        require(target.resolve().is_relative_to(self.root), f"Path escapes collection: {label}")
        current = target
        while current != self.root:
            require(not current.is_symlink(), f"Symlink in {label}")
            current = current.parent
        try:
            metadata = target.stat()
            require(stat.S_ISREG(metadata.st_mode), f"Not a regular file: {label}")
            require(0 < metadata.st_size <= MAX_BYTES, f"Empty or oversized file: {label}")
            with target.open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
        except OSError as error:
            raise EvidenceError(f"Cannot read {label}: {error}") from error
        require(0 < len(data) <= MAX_BYTES, f"Empty or oversized file: {label}")
        self.hashes[relative] = {"sha256": digest(data), "bytes": len(data)}
        return data


def verify_ui(ui, collection, mappings, source_id, target_id):
    require(isinstance(ui, dict) and type(ui.get("schema_version")) is int and ui.get("schema_version") == 1, "Unsupported UI evidence schema")
    require(ui.get("outcome") == "passed", "UI evidence does not report a passed journey")
    require(ui.get("issues") == [], "UI evidence has issues or omits its issue list")
    journey = identifier(ui.get("journey_run_id"), "journey_run_id")
    require(len({journey, source_id, target_id}) == 3, "Journey and namespace identifiers must all differ")
    require(identifier(ui.get("source_run_id"), "UI source_run_id") == source_id, "UI source run ID mismatch")
    require(identifier(ui.get("target_run_id"), "UI target_run_id") == target_id, "UI target run ID mismatch")
    short = journey[:8]
    expected = {"home_name": "Recovery Home " + short, "room_name": "Recovery Room " + short,
                "item_name": "Recovery Item " + short, "notes": "Recovery receipt QA"}
    require(ui.get("expected") == expected, "UI names are not the fixed scenario names")
    events = ui.get("events")
    require(isinstance(events, list) and len(events) == len(STEPS) and all(isinstance(e, dict) for e in events)
            and [e.get("name") for e in events] == list(STEPS),
            "UI checkpoints missing or out of order")
    require(isinstance(mappings, dict), "Missing explicit UI attachment mapping")
    require(all(isinstance(path, str) for path in mappings.values())
            and len(set(mappings.values())) == len(mappings), "UI attachments need distinct collected paths")
    used = set()
    observations = {}
    for index, event in enumerate(events, 1):
        require(type(event.get("sequence")) is int and event["sequence"] == index, "Invalid UI sequence")
        expected_run = source_id if index <= 9 else target_id
        require(identifier(event.get("run_id"), "event run_id") == expected_run, "Checkpoint assigned to wrong namespace")
        assertions = event.get("assertions")
        require(isinstance(assertions, list) and assertions, "Checkpoint has no recorded assertions")
        for assertion in assertions:
            require(isinstance(assertion, dict) and isinstance(assertion.get("name"), str)
                    and bool(assertion["name"]), "Malformed UI assertion")
            require(assertion.get("passed") is True and isinstance(assertion.get("actual"), str)
                    and assertion.get("actual") == assertion.get("expected"), "UI assertion failed or inconsistent")
        observed = event.get("observations")
        require(isinstance(observed, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in observed.items()),
                "Malformed UI observations")
        observations[event["name"]] = observed
        refs = event.get("attachments")
        keys(refs, {"screenshot", "accessibility"}, "checkpoint attachments")
        for kind, name in refs.items():
            require(isinstance(name, str) and name in mappings, f"Unmapped {kind} attachment")
            require(name not in used, "UI attachment name reused across checkpoints")
            used.add(name)
            data = collection.read(mappings[name], "UI " + kind)
            if kind == "screenshot":
                require(data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff"), "UI screenshot is not a PNG or JPEG")
            else:
                try:
                    require(bool(data.decode("utf-8").strip()) and b"\x00" not in data, "Empty or nontext accessibility capture")
                except UnicodeDecodeError as error:
                    raise EvidenceError("Accessibility capture is not UTF-8 text") from error
    require(set(mappings) == used, "UI attachment mapping contains unused entries")
    fixed_observations = {
        "source_empty_free": {"empty_label": "Add your first home", "free_label": "Explore Pro"},
        "target_empty_free": {"empty_label": "Add your first home", "free_label": "Explore Pro"},
        "source_free": {"free_label": "Explore Pro"},
        "target_free": {"free_label": "Explore Pro"},
        "restore_confirmation": {"warning": "Replace the current inventory?"},
        "original_preview": {"image_label": "Receipt"},
    }
    for step, prefix in [("source_zip_saved", "source-"), ("backup_saved", "backup-"),
                         ("recovered_zip_saved", "recovered-")]:
        fixed_observations[step] = {"save_name": prefix + journey, "folder": "Recovery-" + journey}
    for step, values in fixed_observations.items():
        require(all(observations[step].get(k) == v for k, v in values.items()), f"Required UI observations differ at {step}")
    photo = observations["photos_receipt_selected"]
    require("Receipt" in photo.get("purpose", "") and photo.get("photo_label", "").lower().startswith("photo,"),
            "Photo selection does not record the real receipt picker")
    actual_price = observations["ocr_selection_model_price"].get("price")
    require(actual_price in {"USD149.50", "USD 149.50"}, "OCR price differs from fixed receipt")
    final = {**FINAL, "price": actual_price}
    for step, values in [("item_before_ocr", INITIAL), ("source_item_after_ocr", final),
                         ("target_restored", final), ("target_relaunched", final)]:
        require(all(observations[step].get(k) == v for k, v in values.items()), f"Observed fields differ at {step}")
    for step, selected in [("ocr_review_unselected", {k: "0" for k in OCR}),
                           ("ocr_selection_model_price", {"model": "1", "serial": "0", "price": "1", "date": "0"})]:
        require(all(observations[step].get(k) == v for k, v in {**OCR, "price": actual_price}.items()), f"OCR observations differ at {step}")
        require(all(observations[step].get("selected." + k) == v for k, v in selected.items()), f"OCR selection differs at {step}")
    original_name = observations["original_preview"].get("original_name")
    require(isinstance(original_name, str) and 0 < len(original_name) <= 256
            and original_name.lower().endswith(".png"), "Missing observed original PNG name")
    return journey, expected, original_name, final


def validate_inventory(inventory, expected, observed_original, final):
    keys(inventory, {"schemaVersion", "homes"}, "inventory")
    require(type(inventory["schemaVersion"]) is int and inventory["schemaVersion"] == 1, "Unsupported inventory schema")
    require(isinstance(inventory["homes"], list) and len(inventory["homes"]) == 1, "Expected exactly one home")
    home = inventory["homes"][0]
    keys(home, {"id", "name", "rooms"}, "home")
    require(isinstance(home["rooms"], list) and len(home["rooms"]) == 1, "Expected exactly one room")
    room = home["rooms"][0]
    keys(room, {"id", "name", "items"}, "room")
    require(isinstance(room["items"], list) and len(room["items"]) == 1, "Expected exactly one item")
    item = room["items"][0]
    keys(item, {"id", "name", "model", "serialNumber", "purchasePrice", "purchaseDate", "notes", "attachments"}, "item")
    require(isinstance(item["attachments"], list) and len(item["attachments"]) == 1, "Expected exactly one original")
    original = item["attachments"][0]
    keys(original, {"id", "kind", "fileName", "originalName", "mediaType", "sha256"}, "original")
    ids = [identifier(obj["id"], label) for obj, label in [(home, "home"), (room, "room"), (item, "item"), (original, "original")]]
    require(len(set(ids)) == 4, "Duplicate inventory identities")
    require([home["name"], room["name"], item["name"]] == [expected["home_name"], expected["room_name"], expected["item_name"]], "Inventory names differ from UI scenario")
    require({"model": item["model"], "serial": item["serialNumber"], "price": item["purchasePrice"],
             "date": item["purchaseDate"], "notes": item["notes"]} == final, "Inventory fields differ from fixed selective-Apply expectations")
    require(original["kind"] == "receipt" and original["mediaType"] == "image/png", "Original is not a PNG receipt")
    require(original["fileName"] == ids[3].lower() + ".png", "Original filename does not match identity")
    require(original["originalName"] == observed_original, "Original name differs from preview observation")
    require(original["sha256"] == FIXTURE_SHA256, "Original digest is not the fixed synthetic receipt")
    path = f"originals/{ids[2]}/{original['fileName']}"
    row = [ids[0], home["name"], ids[1], room["name"], ids[2], item["name"], item["model"], item["serialNumber"],
           item["purchasePrice"], item["purchaseDate"], item["notes"], ids[3], original["kind"], path,
           original["originalName"], original["mediaType"], original["sha256"]]
    return original, path, row


def verify_zip(data, fixture, original_path, row, label):
    expected_names = {"Inventory.csv", "Inventory-localized.csv", "Inventory.pdf", "README.txt", original_path}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [entry.filename for entry in infos]
            require(len(names) == len(set(names)), f"Duplicate ZIP members in {label}")
            require(set(names) == expected_names, f"Missing or unexpected ZIP members in {label}")
            require(sum(entry.file_size for entry in infos) <= MAX_BYTES, f"Oversized expanded ZIP in {label}")
            for entry in infos:
                require(entry.compress_type == zipfile.ZIP_STORED and not (entry.flag_bits & 1), f"Unexpected ZIP encoding in {label}")
                require(not entry.is_dir(), f"Directory ZIP member in {label}")
            files = {entry.filename: archive.read(entry) for entry in infos}
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as error:
        raise EvidenceError(f"Invalid ZIP {label}: {error}") from error
    require(files[original_path] == fixture, f"ZIP original differs from fixed receipt in {label}")
    try:
        rows = list(csv.reader(io.StringIO(files["Inventory.csv"].decode("utf-8"), newline=""), strict=True))
        localized = list(csv.reader(io.StringIO(files["Inventory-localized.csv"].decode("utf-8"), newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as error:
        raise EvidenceError(f"Invalid CSV in {label}: {error}") from error
    require(rows == [HEADERS, row], f"Machine CSV metadata or original association differs in {label}")
    require(len(localized) == 2 and len(localized[0]) == 17 and all(localized[0])
            and len(set(localized[0])) == 17 and len(localized[1]) == 17, f"Malformed localized CSV in {label}")
    local_row = localized[1][:]
    require(local_row[12] in {"Receipt", "Чек"}, f"Wrong localized original kind in {label}")
    local_row[12] = "receipt"
    require(local_row == row, f"Localized CSV altered inventory values in {label}")
    pdf = files["Inventory.pdf"]
    require(pdf.startswith(b"%PDF-") and b"%%EOF" in pdf[-1024:]
            and re.search(rb"/Type\s*/Page\b", pdf) is not None, f"Missing or structurally truncated PDF in {label}")
    require(bool(files["README.txt"].strip()), f"Empty export README in {label}")
    return {name: {"sha256": digest(payload), "bytes": len(payload)} for name, payload in files.items()}


def verify_receipt(receipt, journey, source_id, target_id, payloads):
    keys(receipt, {"schema_version", "journey_run_id", "source_run_id", "target_run_id", "exports_before", "exports_after"}, "collection receipt")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1, "Unsupported receipt schema")
    for name, expected in [("journey_run_id", journey), ("source_run_id", source_id), ("target_run_id", target_id)]:
        require(identifier(receipt[name], name) == expected, "Collection receipt run ID differs")
    require(receipt["exports_before"] == [], "Export directory was not recorded empty before the journey")
    entries = receipt["exports_after"]
    require(isinstance(entries, list) and len(entries) == 3 and all(isinstance(e, dict) for e in entries), "Need exactly three recorded app export directories")
    roles = ["source_zip", "backup", "target_zip"]
    require([e.get("role") for e in entries] == roles, "Generated export order differs")
    directories, identities, timestamps = set(), set(), []
    for entry, role, generated, filename, saved_prefix, extension in zip(
        entries, roles, ["source_generated_zip", "generated_backup", "target_generated_zip"],
        ["Inventory-package.zip", "Inventory.roominventory", "Inventory-package.zip"],
        ["source-", "backup-", "recovered-"], ["zip", "roominventory", "zip"]
    ):
        keys(entry, {"role", "directory_id", "generated_path", "device_id", "inode", "created_at_ns", "bytes", "sha256", "saved_path"}, "export receipt entry")
        directory = identifier(entry["directory_id"], "export directory")
        require(directory not in directories, "Generated export directory reused")
        directories.add(directory)
        require(entry["generated_path"] == f"tmp/InventoryExports/{directory}/{filename}", "Generated export path is not the recorded unique directory")
        for key in ["device_id", "inode", "created_at_ns", "bytes"]:
            require(type(entry[key]) is int and entry[key] > 0, "Invalid recorded file identity, size or time")
        identity = (entry["device_id"], entry["inode"])
        require(identity not in identities, "Generated exports reuse one file identity")
        identities.add(identity)
        timestamps.append(entry["created_at_ns"])
        require(entry["saved_path"] == f"Recovery-{journey}/{saved_prefix}{journey}.{extension}", "Saved Files path differs from journey")
        require(payloads[generated] == payloads[role], "Saved Files copy differs from actual generated export")
        require(entry["sha256"] == digest(payloads[generated]) and entry["bytes"] == len(payloads[generated]), "Recorded generated export digest/size differs")
    require(timestamps == sorted(timestamps), "Recorded generated export times are not ordered")


def verify_collection(manifest: Path, expected_commit: str):
    require(re.fullmatch(r"[0-9a-f]{40}", expected_commit) is not None, "Expected commit must be a full lowercase SHA")
    collection = Collection(manifest)
    raw = collection.read(manifest.name, "collection manifest")
    document = parse_json(raw, "collection manifest")
    keys(document, {"schema_version", "source_commit", "source_run_id", "target_run_id", "ui_evidence", "ui_attachments", "artifacts", "collection_receipt"}, "collection manifest")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1, "Unsupported collection schema")
    require(document["source_commit"] == expected_commit, "Collection commit does not match caller-pinned source")
    source_id = identifier(document["source_run_id"], "source_run_id")
    target_id = identifier(document["target_run_id"], "target_run_id")
    require(source_id != target_id, "Source and fresh target namespaces must differ")
    ui = parse_json(collection.read(document["ui_evidence"], "UI evidence"), "UI evidence")
    journey, expected, original_name, final = verify_ui(ui, collection, document["ui_attachments"], source_id, target_id)
    keys(document["artifacts"], ARTIFACTS, "artifact mapping")
    paths = document["artifacts"]
    require(all(isinstance(path, str) for path in paths.values()) and len(set(paths.values())) == len(paths), "Every artifact needs a distinct collected path")
    payloads = {name: collection.read(path, name) for name, path in paths.items()}
    fixture = payloads["fixture"]
    require(len(fixture) == FIXTURE_BYTES and digest(fixture) == FIXTURE_SHA256
            and fixture.startswith(b"\x89PNG\r\n\x1a\n"), "Fixture is not the pinned real synthetic PNG")
    source = parse_json(payloads["source_inventory"], "source inventory")
    target = parse_json(payloads["target_inventory"], "target inventory")
    original, path, row = validate_inventory(source, expected, original_name, final)
    validate_inventory(target, expected, original_name, final)
    require(source == target, "Fresh target inventory differs from source metadata or identities")
    require(payloads["source_original"] == fixture and payloads["target_original"] == fixture, "Stored original differs from fixed receipt")
    backup = parse_json(payloads["backup"], "saved backup")
    keys(backup, {"format", "version", "inventory", "files"}, "saved backup")
    require(backup["format"] == "com.alvit.roominventory.backup" and type(backup["version"]) is int and backup["version"] == 1, "Unsupported backup format/version")
    validate_inventory(backup["inventory"], expected, original_name, final)
    require(backup["inventory"] == source, "Backup inventory differs from observed source")
    keys(backup["files"], {original["fileName"]}, "backup originals")
    try:
        encoded = backup["files"][original["fileName"]]
        require(isinstance(encoded, str), "Backup original is not base64 text")
        original_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise EvidenceError(f"Invalid backup original base64: {error}") from error
    require(original_bytes == fixture, "Backup original differs from fixed receipt")
    receipt = parse_json(collection.read(document["collection_receipt"], "collection receipt"), "collection receipt")
    verify_receipt(receipt, journey, source_id, target_id, payloads)
    zips = {name: verify_zip(payloads[name], fixture, path, row, name) for name in ["source_zip", "target_zip"]}
    return {"status": "PASS_OFFLINE_ARTIFACT_CONSISTENCY", "source_commit": expected_commit,
            "journey_run_id": journey, "source_run_id": source_id, "target_run_id": target_id,
            "ui_execution": "NOT_INDEPENDENTLY_VERIFIED", "reported_ui_outcome": ui["outcome"],
            "recorded_checkpoints": len(STEPS), "files": collection.hashes, "zip_members": zips,
            "limitations": ["A matching JSON event log and screenshots do not independently prove UI actions or a passed XCTest run. Bind this result to the actual xcresult and its source SHA separately.",
                            "The collector asserts that the explicitly mapped files came from the stated source and target namespaces and two UI exports; this verifier does not access a simulator or establish capture chronology.",
                            "PDF checks establish bounded structural presence, not rendering or semantic text correctness. Separate visual/PDF text evidence is required.",
                            "A fresh UITEST_RUN_ID namespace is not proof of uninstall/reinstall, a physical device, or App Store acceptance."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_collection(args.collection, args.expected_commit)
    except (EvidenceError, RecursionError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
