"""Ephemeral-host retention tested with injected files, never native tools."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import struct
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
import uuid
import zlib
from unittest.mock import patch

import test_recovery_collector as collector_fixtures
import test_recovery_journey as journey_fixtures

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("recovery_retention", ROOT / "scripts/recovery_retention.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def macho(platform=7):
    commands = struct.pack("<II", 0x1B, 24) + uuid.UUID("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA").bytes
    commands += struct.pack("<6I", 0x32, 24, platform, 0x120000, 0x1B0000, 0)
    return struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 2, len(commands), 0, 0) + commands


class RecoveryRetentionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = collector_fixtures.RecoveryCollectorTests("test_equal_zip_bytes_have_distinct_live_origins_and_verify_end_to_end_offline")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.journey()
        verified = self.fixture.collector.capture_xcresult(self.fixture.original)
        self.fixture.collector.collect(verified)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.work = self.base / "room-recovery-work"
        self.upload = self.base / "room-recovery-upload"
        (self.work / "run/evidence").mkdir(parents=True)
        shutil.copytree(self.fixture.collector.root, self.work / "run/evidence/collection")
        shutil.copytree(self.fixture.original, self.work / "run/original.xcresult")
        self.guard_hook = lambda: None
        self.guard_calls = 0
        self.source = {"commit": journey_fixtures.PIN, "tree": "d" * 40, "tree_listing_sha256": "e" * 64}
        self.profile, self.workflow = b'{"runner":"macos-15"}\n', b"name: fixture workflow\n"
        self.context = {"source_commit": self.source["commit"], "source_tree": self.source["tree"],
                        "profile_sha256": R.digest(self.profile), "workflow_sha256": R.digest(self.workflow),
                        "hosted_identity": {"runner_environment": "github-hosted", "run_id": "123"},
                        "controller_exit_code": 0, "primary_error": None, "cleanup_errors": [],
                        "tool_hashes": {"controller": "1" * 64, "collector": "2" * 64, "retention": "3" * 64}}
        self.write("preflight/recovery-hosted-profile.json", self.profile)
        self.write("preflight/ci.yml", self.workflow)
        self.grant = {"source_commit": self.source["commit"], "source_tree": self.source["tree"]}
        self.envelope = {key: self.context[key] for key in ("source_commit", "source_tree", "profile_sha256", "workflow_sha256", "hosted_identity", "tool_hashes")}
        self.envelope["controller_grant"] = self.grant
        self.write("hosted-grant-envelope.json", R.encoded(self.envelope))
        self.source["grant"] = self.grant
        self.write("run/source-pin.json", R.encoded(self.source))
        self.write("run/resource-samples.json", b'[{"free_bytes":123456789}]')
        self.write("run/generated.xctestrun.plist", plistlib.dumps({"fixture": "generated"}))
        self.write("run/selected.xctestrun.plist", plistlib.dumps({"fixture": "selected"}))
        derived = self.work / "run/DerivedData"
        products = derived / "Build/Products/Debug-iphonesimulator"
        app, runner = products / "RoomInventory.app", products / "RoomInventoryUITests-Runner.app"
        tests = runner / "PlugIns/RoomInventoryUITests.xctest"
        for path, bundle, executable in [(app, "com.alvit.roominventory", "RoomInventory"),
                                         (runner, "com.alvit.roominventory.uitests.xctrunner", "RoomInventoryUITests-Runner"),
                                         (tests, "com.alvit.roominventory.uitests", "RoomInventoryUITests")]:
            path.mkdir(parents=True, exist_ok=True)
            (path / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": bundle, "CFBundleExecutable": executable,
                "CFBundleSupportedPlatforms": ["iPhoneSimulator"], "DTPlatformName": "iphonesimulator", "DTSDKName": "iphonesimulator27.0"}))
            (path / executable).write_bytes(macho())
        actual = derived / "Build/Products/Recovery.xctestrun"
        shutil.copyfile(self.work / "run/selected.xctestrun.plist", actual)
        self.controller = SimpleNamespace(output=self.work / "run", derived=derived, app=app, runner=runner,
            xctestrun=actual, xctestrun_sha=R.digest(actual.read_bytes()), tree_sha=self.source["tree_listing_sha256"],
            grant={"source_commit": self.source["commit"], "source_tree": self.source["tree"]},
            ids=self.fixture.collector.ids, device_id=self.fixture.config["simulator_udid"])
        R.capture_build_identity(self.controller, self.work / "build-identity", self.guard)
        binding_path = self.work / "run/evidence/collection/source-binding.json"
        binding = json.loads(binding_path.read_bytes())
        binding.update(source_tree_sha256=self.source["tree_listing_sha256"],
                       config_sha256=R.digest(json.dumps(self.grant, sort_keys=True).encode()),
                       xctestrun_sha256=self.controller.xctestrun_sha)
        binding_path.write_bytes(R.encoded(binding))
        verification = journey_fixtures.VERIFIER.verify_collection(self.work / "run/evidence/collection/collection.json", self.source["commit"])
        commands = []
        for name in ["build", "ui-test", "verify-artifacts", "device-final-state"]:
            stdout = R.encoded(verification) if name == "verify-artifacts" else b"injected command output"
            self.write("run/logs/" + name + ".stdout", stdout)
            self.write("run/logs/" + name + ".stderr", b"")
            commands.append({"name": name, "exit_code": 0, "primary_error": None, "cleanup": {"success": True},
                             "stdout_sha256": R.digest(stdout), "stderr_sha256": R.digest(b"")})
        self.result = {"status": "PASS_UI_AND_ARTIFACTS_PIXEL_REVIEW_PENDING", "exit_code": 0, "primary_error": None,
                       "cleanup_errors": [], "device_final_state": "Shutdown", "build_count": 1, "test_count": 1, "commands": commands}
        self.write("run/result.json", R.encoded(self.result))

    def guard(self):
        self.guard_calls += 1
        self.guard_hook()

    def write(self, relative, data):
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def package(self, collector=None):
        return R.package_evidence(self.work, self.upload, self.context, self.guard, collector=collector)

    def files_capture_fixture(self):
        """Only synthetic, pinned runner state; no native process or screenshot."""
        collector = self.fixture.collector
        collector.root = self.work / "run/evidence/collection"
        collector.photos_isolated = True
        collector.config.update(source_tree_sha256=self.source["tree_listing_sha256"],
                                config_sha256=R.digest(json.dumps(self.grant, sort_keys=True).encode()),
                                xctestrun_sha256=self.controller.xctestrun_sha)
        root = collector.runner / "Documents" / ("RecoveryFilesFirstTap-" + collector.ids["journey_run_id"])
        root.mkdir(parents=True)
        identity = {**collector.ids, "simulator_udid": collector.config["simulator_udid"]}
        png = (ROOT / "UITests/Fixtures/SyntheticRecoveryReceipt.png").read_bytes()
        for stage in ("before", "after"):
            document = {"schema_version": 1, **identity, "stage": stage}
            ax = {**document, "local_title": "On My iPhone", "selected_target": {"exists": True},
                  "matches": [], "navigation_bars": [], "hierarchy": "Application\n  StaticText On My iPhone"}
            (root / (stage + ".png")).write_bytes(png)
            (root / (stage + "-ax.json")).write_bytes(R.encoded(ax))
            self.files_stage_receipt(root, document)
        return collector, root

    def files_stage_receipt(self, root, document):
        stage = document["stage"]
        entries = []
        for suffix in (".png", "-ax.json"):
            name = stage + suffix
            raw = (root / name).read_bytes()
            entries.append({"name": name, "bytes": len(raw), "sha256": R.digest(raw)})
        (root / (stage + ".json")).write_bytes(R.encoded({**{k: v for k, v in document.items() if k != "files"}, "files": entries}))

    def test_files_capture_survives_oversized_original_without_acceptance(self):
        collector, root = self.files_capture_fixture()
        original = {p.name: p.read_bytes() for p in root.iterdir()}
        self.context.update(controller_exit_code=1, primary_error="injected UI failure")
        snapshot = R.Files.snapshot
        def reject_original(files, path, limit, count):
            if path == self.work / "run/original.xcresult":
                raise R.RetentionError("file size/type limit")
            return snapshot(files, path, limit, count)
        with patch.object(R.Files, "snapshot", reject_original):
            report = self.package(collector)
        self.assertFalse(report["complete"])
        self.assertEqual(report["status"], "PARTIAL")
        capture = report["files_first_tap"]
        self.assertTrue(capture["complete"], capture)
        self.assertFalse(capture["acceptance_evidence"])
        with tarfile.open(self.upload / "evidence.tar") as archive:
            for name, raw in original.items():
                self.assertEqual(archive.extractfile("run/evidence/collection/files-first-tap/" + name).read(), raw)
            receipt = json.loads(archive.extractfile(capture["receipt"]).read())
            self.assertEqual(receipt["source_commit"], self.source["commit"])
            self.assertEqual(receipt["source_tree"], self.source["tree"])
            self.assertFalse(any(n.startswith("run/original.xcresult") for n in archive.getnames()))
        self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, original)

    def test_files_capture_rejects_incomplete_corrupt_foreign_and_extra_payloads(self):
        collector, root = self.files_capture_fixture()
        baseline = {p.name: p.read_bytes() for p in root.iterdir()}
        for damage in ("missing", "truncated", "digest", "run", "stage", "duplicate", "extra", "symlink", "png_over", "ax_over"):
            with self.subTest(damage=damage):
                for p in root.iterdir(): p.unlink()
                for name, raw in baseline.items(): (root / name).write_bytes(raw)
                receipt = json.loads((root / "after.json").read_bytes())
                if damage == "missing": (root / "after.png").unlink()
                elif damage == "truncated": (root / "after.png").write_bytes(baseline["after.png"][:-1])
                elif damage == "digest":
                    receipt["files"][0]["sha256"] = "0" * 64
                    (root / "after.json").write_bytes(R.encoded(receipt))
                elif damage in ("run", "stage"):
                    receipt["source_run_id" if damage == "run" else "stage"] = "FOREIGN"
                    (root / "after.json").write_bytes(R.encoded(receipt))
                elif damage == "duplicate": (root / "after.json").write_bytes(b'{"stage":"after",' + baseline["after.json"][1:])
                elif damage == "extra": (root / "extra.txt").write_text("unexpected")
                elif damage == "symlink":
                    (root / "after.png").unlink()
                    (root / "after.png").symlink_to(root / "before.png")
                else:
                    name, limit = ("after.png", 2 * R.MIB) if damage == "png_over" else ("after-ax.json", 256 * 1024)
                    (root / name).write_bytes(b"x" * (limit + 1))
                    self.files_stage_receipt(root, receipt)
                report = R.capture_first_files_tap(self.work, self.context, collector, R.Files(self.guard))
                self.assertFalse(report["complete"], report)
                self.assertEqual(report["status"], "MISSING_OR_INVALID")
                self.assertFalse((collector.root / "files-first-tap").exists())

    def test_files_capture_accepts_exact_payload_bounds(self):
        collector, root = self.files_capture_fixture()
        for stage in ("before", "after"):
            path = root / (stage + ".png")
            png = path.read_bytes()
            padding = b"k\x00" + b"a" * (2 * R.MIB - len(png) - 14)
            chunk = struct.pack(">I", len(padding)) + b"tEXt" + padding
            chunk += struct.pack(">I", zlib.crc32(b"tEXt" + padding))
            path.write_bytes(png[:-12] + chunk + png[-12:])
            self.assertEqual(path.stat().st_size, 2 * R.MIB)
            path = root / (stage + "-ax.json")
            raw = path.read_bytes()
            path.write_bytes(raw + b" " * (256 * 1024 - len(raw)))
            self.files_stage_receipt(root, json.loads((root / (stage + ".json")).read_bytes()))
        report = R.capture_first_files_tap(self.work, self.context, collector, R.Files(self.guard))
        self.assertTrue(report["complete"], report)

    def test_files_capture_rejects_foreign_source_and_collection_budget(self):
        collector, root = self.files_capture_fixture()
        for mode in ("source", "budget"):
            with self.subTest(mode=mode):
                context = {**self.context, "source_commit": "0" * 40} if mode == "source" else self.context
                snapshot = R.Files.snapshot
                def constrained(files, path, limit, count):
                    value = snapshot(files, path, limit, count)
                    if mode == "budget" and path == collector.root:
                        value["reserved"] = {"kind": "file", "bytes": 512 * R.MIB}
                    return value
                with patch.object(R.Files, "snapshot", constrained):
                    report = R.capture_first_files_tap(self.work, context, collector, R.Files(self.guard))
                self.assertFalse(report["complete"], report)
                self.assertFalse((collector.root / "files-first-tap").exists())

    def test_files_capture_missing_does_not_change_existing_acceptance(self):
        report = self.package()
        self.assertTrue(report["complete"], report["failures"])
        self.assertFalse(report["files_first_tap"]["complete"])
        self.assertFalse(report["files_first_tap"]["acceptance_evidence"])

    def test_files_capture_changed_before_archive_is_not_reported_complete(self):
        collector, _ = self.files_capture_fixture()
        copied = collector.root / "files-first-tap"
        changed = []
        def mutate():
            if not changed and (copied / "capture.json").exists():
                changed.append(True)
                with (copied / "before.png").open("ab") as stream:
                    stream.write(b"injected change")
        self.guard_hook = mutate
        report = self.package(collector)
        self.assertTrue(changed)
        self.assertFalse(report["files_first_tap"]["complete"], report)
        self.assertEqual(report["files_first_tap"]["status"], "MISSING_OR_INVALID")

    def test_files_capture_rechecks_runner_metadata_after_reads_before_publish(self):
        collector, root = self.files_capture_fixture()
        files = R.Files(self.guard)
        read = files.read
        reads, changed = [], []
        metadata = collector.runner / collector_fixtures.C.MCM
        def mutate(path, limit, *, keep=True):
            result = read(path, limit, keep=keep)
            if path == root / "after-ax.json":
                reads.append(path)
                # First read is the initial subtree snapshot; second is the
                # payload read, after the initial container pin validation.
                if len(reads) == 2:
                    value = plistlib.loads(metadata.read_bytes())
                    value["InjectedMetadataChange"] = True
                    metadata.write_bytes(plistlib.dumps(value))
                    changed.append(True)
            return result
        with patch.object(files, "read", side_effect=mutate), \
                patch.object(collector, "_write", wraps=collector._write) as publish:
            report = R.capture_first_files_tap(self.work, self.context, collector, files)
        self.assertTrue(changed)
        self.assertFalse(report["complete"], report)
        self.assertIn("container relocated or metadata changed", report["reason"])
        publish.assert_not_called()
        self.assertFalse((collector.root / "files-first-tap").exists())

    def test_complete_packet_preserves_raw_bytes_and_omits_live_state(self):
        original = self.work / "run/original.xcresult/Data/payload"
        before = original.read_bytes()
        report = self.package()
        self.assertTrue(report["complete"], report["failures"])
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse(report["full_simulator_retained"])
        self.assertFalse(report["derived_data_retained"])
        with tarfile.open(self.upload / "evidence.tar") as archive:
            names = archive.getnames()
            self.assertEqual(archive.extractfile("run/original.xcresult/Data/payload").read(), before)
            self.assertIn("run/evidence/collection/artifacts/target_generated_zip.zip", names)
            self.assertIn("build-identity/identity.json", names)
            self.assertFalse(any("DerivedData" in name or "simulator/" in name for name in names))
            self.assertIn(b"NOT retained", archive.extractfile("RETENTION-NOTICE.txt").read())
        self.assertEqual(sum(path.stat().st_size for path in self.upload.iterdir()), sum(path.stat().st_size for path in self.upload.iterdir() if path.is_file()))

    def test_build_capture_records_actual_hashes_and_macho_platform(self):
        identity = json.loads((self.work / "build-identity/identity.json").read_bytes())
        self.assertEqual(set(identity["products"]), {"app", "runner", "tests"})
        executable = self.controller.app / "RoomInventory"
        self.assertEqual(identity["products"]["app"]["executable_file"]["sha256"], R.digest(executable.read_bytes()))
        self.assertEqual(identity["products"]["tests"]["macho"][0]["platform"], 7)
        self.assertFalse(any(path.name == "RoomInventory" for path in (self.work / "build-identity").rglob("*")))

    def test_missing_required_file_produces_partial_packet(self):
        (self.work / "run/evidence/collection/artifacts/target_generated_zip.zip").unlink()
        report = self.package()
        self.assertFalse(report["complete"])
        self.assertEqual(report["status"], "PARTIAL")
        self.assertTrue((self.upload / "evidence.tar").is_file())
        self.assertTrue(json.loads((self.upload / "retention.json").read_bytes())["failures"])

    def test_changed_source_binding_cannot_be_complete(self):
        self.context["source_commit"] = "f" * 40
        report = self.package()
        self.assertFalse(report["complete"])
        self.assertTrue(any("source pin differs" in failure for failure in report["failures"]))

    def test_changed_profile_bytes_are_not_accepted(self):
        self.write("preflight/recovery-hosted-profile.json", b"altered")
        self.assertFalse(self.package()["complete"])

    def test_changed_envelope_link_is_not_accepted(self):
        self.envelope["tool_hashes"] = {"controller": "4" * 64}
        self.write("hosted-grant-envelope.json", R.encoded(self.envelope))
        report = self.package()
        self.assertFalse(report["complete"])
        self.assertTrue(any("envelope/context" in item for item in report["failures"]))

    def test_changed_collection_configuration_binding_is_not_accepted(self):
        path = self.work / "run/evidence/collection/source-binding.json"
        binding = json.loads(path.read_bytes())
        binding["xctestrun_sha256"] = "5" * 64
        path.write_bytes(R.encoded(binding))
        report = self.package()
        self.assertFalse(report["complete"])
        self.assertTrue(any("collected source/configuration" in item for item in report["failures"]))

    def test_symlink_selected_root_is_rejected_and_not_followed(self):
        outside = self.base / "private-sentinel"
        outside.write_bytes(b"must not be retained")
        (self.work / "run/original.xcresult/link").symlink_to(outside)
        report = self.package()
        self.assertFalse(report["complete"])
        with tarfile.open(self.upload / "evidence.tar") as archive:
            self.assertFalse(any(member.issym() or member.islnk() for member in archive))
            self.assertNotIn("run/original.xcresult/link", archive.getnames())

    def test_collection_path_escape_is_rejected_without_reading_external_file(self):
        manifest = self.work / "run/evidence/collection/collection.json"
        value = json.loads(manifest.read_bytes())
        value["artifacts"]["fixture"] = "../../../../private-sentinel"
        manifest.write_bytes(R.encoded(value))
        report = self.package()
        self.assertFalse(report["complete"])
        self.assertTrue(any("Unsafe path" in failure for failure in report["failures"]))

    def test_oversized_archive_budget_is_partial(self):
        with patch.object(R, "PACKET_CAP", 1024 * 1024):
            report = self.package()
        self.assertFalse(report["complete"])
        self.assertTrue(any("budget" in failure or "cap" in failure for failure in report["failures"]))

    def test_original_change_during_archive_is_rejected(self):
        original = self.work / "run/original.xcresult/Data/payload"
        fired = []
        def change():
            if not fired and (self.upload / "evidence.tar").exists():
                fired.append(True)
                original.write_bytes(b"external concurrent change")
        self.guard_hook = change
        report = self.package()
        self.assertFalse(report["complete"])
        self.assertTrue(any("changed" in failure for failure in report["failures"]))

    def test_failed_controller_retains_incomplete_available_owned_state(self):
        self.context["controller_exit_code"] = 1
        self.context["primary_error"] = "injected UI failure"
        collector = self.fixture.collector
        collector.root = self.work / "run/evidence/collection"
        report = self.package(collector)
        self.assertFalse(report["complete"])
        with tarfile.open(self.upload / "evidence.tar") as archive:
            names = archive.getnames()
            self.assertIn("partial-capture/source-namespace/inventory.json", names)
            self.assertIn("partial-capture/target-namespace/inventory.json", names)
            observation = json.loads(archive.extractfile("partial-capture/partial-observations.json").read())
            self.assertEqual(observation["status"], "INCOMPLETE_OBSERVATIONS")
            self.assertFalse(observation["roles_inferred_from_hash_or_time"])
            self.assertEqual(len(observation["sources"]), 4)

    def test_missing_pins_record_absence_without_guessing_owned_state(self):
        self.context["controller_exit_code"] = 1
        self.package()
        report = json.loads((self.work / "partial-capture/partial-observations.json").read_bytes())
        self.assertEqual(report["sources"], [])
        self.assertTrue(report["failures"])

    def test_partial_capture_retains_empty_directories(self):
        collector = self.fixture.collector
        collector.root = self.work / "run/evidence/collection"
        (collector.app / "tmp/RoomInventoryUITests" / collector.ids["source_run_id"] / "empty/child").mkdir(parents=True)
        self.context["controller_exit_code"] = 1
        self.package(collector)
        with tarfile.open(self.upload / "evidence.tar") as archive:
            member = archive.getmember("partial-capture/source-namespace/empty/child")
            self.assertTrue(member.isdir())

    def test_scaled_shared_partial_byte_budget_preserves_admissible_subset(self):
        collector = self.fixture.collector
        collector.root = self.work / "run/evidence/collection"
        # The four roots fit their individual 8+8+24+24 KiB limits. Together
        # their payloads exhaust 64 KiB before any diagnostic receipt is added.
        for key in ("source_run_id", "target_run_id"):
            namespace = collector.app / "tmp/RoomInventoryUITests" / collector.ids[key]
            manifest_size = (namespace / "inventory.json").stat().st_size
            next((namespace / "assets").iterdir()).write_bytes(b"p" * (8 * 1024 - manifest_size))
        for path in (collector.app / "tmp/InventoryExports").rglob("*"):
            if path.is_file():
                path.write_bytes(b"g" * (8 * 1024))
        saved_folder = collector.simulator / collector._files()["folder"]
        for path in saved_folder.iterdir():
            path.write_bytes(b"s" * (8 * 1024))
        self.context["controller_exit_code"] = 1
        capture = R.capture_partial
        def scaled_capture(*args):
            # Scale this capture's limits without also shrinking unrelated
            # final packet metadata/receipt limits below their normal sizes.
            with patch.object(R, "MIB", 1024):
                return capture(*args)
        with patch.object(R, "capture_partial", side_effect=scaled_capture):
            report = self.package(collector)
        self.assertFalse(report["complete"])
        self.assertIn("partial-capture", report["selected_source_roots"])
        partial = self.work / "partial-capture"
        self.assertLessEqual(sum(path.stat().st_size for path in partial.rglob("*") if path.is_file()), 64 * 1024)
        observation = json.loads((partial / "partial-observations.json").read_bytes())
        self.assertTrue(observation["failures"])
        self.assertLessEqual(observation["budget"]["payload_bytes_reserved"], 60 * 1024)
        self.assertLessEqual((partial / "partial-observations.json").stat().st_size, 4 * 1024)
        with tarfile.open(self.upload / "evidence.tar") as archive:
            self.assertIn("partial-capture/source-namespace/inventory.json", archive.getnames())
            self.assertIn("partial-capture/partial-observations.json", archive.getnames())

    def test_shared_partial_entry_budget_keeps_copied_files_and_receipt(self):
        collector = self.fixture.collector
        collector.root = self.work / "run/evidence/collection"
        self.context["controller_exit_code"] = 1
        with patch.object(R, "PARTIAL_ENTRY_CAP", 6):
            report = self.package(collector)
        self.assertFalse(report["complete"])
        self.assertIn("partial-capture", report["selected_source_roots"])
        partial = self.work / "partial-capture"
        self.assertLessEqual(1 + len(list(partial.rglob("*"))), 6)
        observation = json.loads((partial / "partial-observations.json").read_bytes())
        self.assertTrue(observation["failures"])
        self.assertLessEqual(observation["budget"]["entries_reserved_including_receipt"], 6)
        with tarfile.open(self.upload / "evidence.tar") as archive:
            self.assertIn("partial-capture/source-namespace/inventory.json", archive.getnames())
            self.assertIn("partial-capture/partial-observations.json", archive.getnames())

    def test_complete_packet_preserves_raw_xcresult_root_mode_and_identity(self):
        original = self.work / "run/original.xcresult"
        original.chmod(0o700)
        report = self.package()
        self.assertTrue(report["complete"], report["failures"])
        with tarfile.open(self.upload / "evidence.tar") as archive:
            member = archive.getmember("run/original.xcresult")
            self.assertTrue(member.isdir())
            self.assertEqual(member.mode, 0o700)
            before = json.loads(archive.extractfile("RETENTION-SOURCE-BEFORE.json").read())
            after = json.loads(archive.extractfile("RETENTION-SOURCE-AFTER.json").read())
            self.assertEqual(before["run/original.xcresult"][""]["mode"], 0o700)
            self.assertEqual(before["run/original.xcresult"][""]["inode"], original.stat().st_ino)
            self.assertEqual(before["run/original.xcresult"][""], after["run/original.xcresult"][""])
        manifest = json.loads((self.upload / "archive-manifest.json").read_bytes())
        self.assertEqual(manifest["run/original.xcresult"], {"kind": "directory", "mode": 0o700})

    def test_build_identity_budget_is_checked_before_output_write(self):
        shutil.rmtree(self.work / "build-identity")
        with patch.object(R, "BUILD_IDENTITY_CAP", 10):
            with self.assertRaisesRegex(R.RetentionError, "build identity output"):
                R.capture_build_identity(self.controller, self.work / "build-identity", self.guard)
        self.assertEqual(list((self.work / "build-identity").iterdir()), [])

    def test_guard_cutoff_keeps_initial_partial_receipt(self):
        def cutoff():
            if (self.upload / "retention.json").exists():
                raise TimeoutError("injected packaging deadline")
        self.guard_hook = cutoff
        with self.assertRaises(TimeoutError):
            self.package()
        self.assertFalse(json.loads((self.upload / "retention.json").read_bytes())["complete"])

    def test_product_with_wrong_platform_is_rejected_without_native_tools(self):
        shutil.rmtree(self.work / "build-identity")
        (self.controller.app / "RoomInventory").write_bytes(macho(platform=2))
        with self.assertRaisesRegex(R.RetentionError, "not an iOS simulator"):
            R.capture_build_identity(self.controller, self.work / "build-identity", self.guard)

    def test_foreign_output_path_is_rejected(self):
        with self.assertRaisesRegex(R.RetentionError, "retention roots"):
            R.package_evidence(self.work, self.base / "other", self.context, self.guard)


if __name__ == "__main__":
    unittest.main()
