"""Publication boundaries are checked without compiling or publishing an app."""
from contextlib import ExitStack, contextmanager, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = spec_from_file_location("package_preview", Path(__file__).parents[1] / "package-preview.py")
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PreviewPolicyTests(unittest.TestCase):
    def test_cli_validation_failure_omits_traceback_and_absolute_paths(self):
        result = subprocess.run([sys.executable, MODULE.__file__, "package", "invalid-version", "rc"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), "Expected numeric X.Y.Z base version")

    def test_rejects_non_candidate_channel_and_unsafe_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "VERSION").write_text("0.1.0\n")
            for channel in ("stable", "app-store", "../rc", ""):
                with self.assertRaises(ValueError):
                    MODULE.validate_request("0.1.0", channel, root=root)
            for version in ("../0.1.0", "0.1.1", "v0.1.0", "0.1.0;touch x", "0.1.0-rc.1"):
                with self.assertRaises(ValueError):
                    MODULE.validate_request(version, "rc", root=root)

    def test_accepts_only_committed_base_with_candidate_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "VERSION").write_text("0.1.0\n")
            for channel in ("nightly", "beta", "rc"):
                MODULE.validate_request("0.1.0", channel, root=root)


class AppPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "RoomInventory.app"
        self.app.mkdir()
        self.executable = self.app / "RoomInventory"
        self.executable_bytes = b"synthetic executable\0arm64\0x86_64"
        self.executable.write_bytes(self.executable_bytes)
        self.executable.chmod(0o755)
        self.info = {
            "CFBundleExecutable": "RoomInventory",
            "CFBundleIdentifier": "com.alvit.roominventory",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleSupportedPlatforms": ["iPhoneSimulator"],
            "MinimumOSVersion": "17.0",
        }
        self.write_info()
        self.output = self.root / "release-dist"
        self.request = self.root / "preview-request.json"
        self.request.write_text(json.dumps({"source_commit": "a" * 40, "base_version": "0.1.0", "channel": "rc"}))
        (self.root / "VERSION").write_text("0.1.0\n")

    def write_info(self):
        (self.app / "Info.plist").write_bytes(plistlib.dumps(self.info))

    def resource(self, contents=b"ordinary localized resource"):
        path = self.app / "Resources" / "en.lproj" / "Localizable.strings"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def validate(self):
        return MODULE.validate_app_payload(self.app, root=self.root)

    @contextmanager
    def package_context(self):
        validate_request = MODULE.validate_request
        with ExitStack() as stack:
            stack.enter_context(patch.multiple(MODULE, ROOT=self.root, APP=self.app, OUTPUT=self.output, REQUEST=self.request))
            stack.enter_context(patch.object(MODULE, "validate_request", side_effect=lambda version, channel: validate_request(version, channel, root=self.root)))
            stack.enter_context(patch.object(MODULE, "ensure_clean_source", return_value="a" * 40))
            stack.enter_context(patch.object(MODULE, "checked_output", return_value="synthetic tool version"))
            archive = stack.enter_context(patch.object(MODULE.subprocess, "check_output", return_value=b"synthetic source tar"))
            architectures = stack.enter_context(patch.object(MODULE, "snapshot_architectures", return_value="arm64 x86_64"))
            stack.enter_context(patch("sys.argv", ["package-preview.py", "package", "0.1.0", "rc"]))
            stack.enter_context(redirect_stdout(io.StringIO()))
            yield archive, architectures

    def test_accepts_and_retains_complete_nested_payload(self):
        resource = self.resource(b"Russian and English strings\0binary resource")
        (self.app / "EmptyDirectory").mkdir()
        files = self.validate()
        self.assertEqual(set(files), {Path("Info.plist"), Path("RoomInventory"), resource.relative_to(self.app)})
        self.assertEqual(files[Path("RoomInventory")][0], self.executable_bytes)
        self.assertEqual(stat.S_IMODE(files[Path("RoomInventory")][1].st_mode), 0o755)
        self.assertEqual(files[resource.relative_to(self.app)][0], resource.read_bytes())

    def test_rejects_every_path_marker_in_binary_and_nested_resource(self):
        markers = {
            "developer-home": b"/Users/private-developer/project",
            "runner-home": b"/home/runner/private-project",
            "developer-temporary-directory": b"/private/var/folders/private-build",
            "build-root": os.fsencode(self.root) + b"/private-build",
        }
        resource = self.resource()
        for target in (self.executable, resource):
            clean = target.read_bytes()
            for label, marker in markers.items():
                with self.subTest(file=target.name, label=label):
                    target.write_bytes(b"prefix\0" + marker + b"\0suffix")
                    with self.assertRaises(ValueError) as error:
                        self.validate()
                    self.assertEqual(str(error.exception), f"Unsafe Simulator app payload: {target.relative_to(self.app).as_posix()} [{label}]")
                    self.assertNotIn(os.fsdecode(marker), str(error.exception))
                    self.assertNotIn(str(self.root), str(error.exception))
                    target.write_bytes(clean)

    def test_rejects_every_coverage_marker_in_binary_and_resource(self):
        markers = {
            "llvm-profile-data": b"__llvm_prf",
            "llvm-coverage": b"__llvm_cov",
            "llvm-profile-counter": b"___profc_",
            "llvm-profile-runtime": b"__llvm_profile",
        }
        resource = self.resource()
        for target in (self.executable, resource):
            clean = target.read_bytes()
            for label, marker in markers.items():
                with self.subTest(file=target.name, label=label):
                    target.write_bytes(b"prefix\0" + marker + b"_suffix\0")
                    with self.assertRaisesRegex(ValueError, label):
                        self.validate()
                    target.write_bytes(clean)

    def test_rejects_missing_empty_and_nonexecutable_binary(self):
        self.executable.unlink()
        with self.assertRaisesRegex(ValueError, "RoomInventory .*missing-executable"):
            self.validate()
        self.executable.write_bytes(b"")
        self.executable.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "empty-executable"):
            self.validate()
        self.executable.write_bytes(self.executable_bytes)
        self.executable.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "not-executable"):
            self.validate()

    def test_rejects_directory_instead_of_executable(self):
        self.executable.unlink()
        self.executable.mkdir()
        with self.assertRaisesRegex(ValueError, "missing-executable"):
            self.validate()

    def test_rejects_file_directory_and_dangling_symlinks(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "file").write_bytes(b"outside resource")
        for target in (outside, outside / "file", outside / "missing"):
            with self.subTest(target=target.name):
                link = self.app / "linked-entry"
                link.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "linked-entry .*symlink"):
                    self.validate()
                link.unlink()

    def test_rejects_symlink_as_app_root(self):
        link = self.root / "linked.app"
        link.symlink_to(self.app)
        with self.assertRaisesRegex(ValueError, r"\. \[symlink\]"):
            MODULE.validate_app_payload(link, root=self.root)

    def test_rejects_missing_or_non_directory_app_root(self):
        with self.assertRaisesRegex(ValueError, "stat-error"):
            MODULE.validate_app_payload(self.root / "missing.app", root=self.root)
        with self.assertRaisesRegex(ValueError, "not-directory"):
            MODULE.validate_app_payload(self.executable, root=self.root)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs require POSIX")
    def test_rejects_nonregular_entry_without_opening_it(self):
        os.mkfifo(self.app / "pipe")
        with self.assertRaisesRegex(ValueError, "pipe .*nonregular-file"):
            self.validate()

    def test_stat_error_is_fatal_and_redacts_os_exception(self):
        resource = self.resource()
        original = Path.lstat

        def fail_stat(path):
            if path == resource:
                raise PermissionError("private path: /Users/private-developer/project")
            return original(path)

        with patch.object(Path, "lstat", new=fail_stat):
            with self.assertRaisesRegex(ValueError, "stat-error") as error:
                self.validate()
        self.assertNotIn("private-developer", str(error.exception))
        self.assertNotIn(str(self.root), str(error.exception))

    def test_directory_read_error_is_fatal_and_redacted(self):
        resource = self.resource()
        original = os.scandir

        def fail_scandir(path):
            if Path(path) == resource.parent:
                raise PermissionError("private path: /Users/private-developer/project")
            return original(path)

        with patch.object(MODULE.os, "scandir", side_effect=fail_scandir):
            with self.assertRaisesRegex(ValueError, "directory-read-error") as error:
                self.validate()
        self.assertNotIn("private-developer", str(error.exception))

    def test_file_read_error_is_fatal_and_redacted(self):
        resource = self.resource()
        original = os.open

        def fail_open(path, *args, **kwargs):
            if Path(path) == resource:
                raise PermissionError("private path: /Users/private-developer/project")
            return original(path, *args, **kwargs)

        with patch.object(MODULE.os, "open", side_effect=fail_open):
            with self.assertRaisesRegex(ValueError, "file-read-error") as error:
                self.validate()
        self.assertNotIn("private-developer", str(error.exception))

    def test_mid_read_error_is_fatal_and_redacted(self):
        original = os.fdopen

        @contextmanager
        def failing_reader(descriptor, *args, **kwargs):
            with original(descriptor, *args, **kwargs) as stream:
                with patch.object(stream, "read", side_effect=OSError("read failed: /Users/private-developer/project")):
                    yield stream

        with patch.object(MODULE.os, "fdopen", side_effect=failing_reader):
            with self.assertRaisesRegex(ValueError, "file-read-error") as error:
                self.validate()
        self.assertNotIn("private-developer", str(error.exception))

    def test_directory_iteration_error_does_not_silently_skip_entries(self):
        @contextmanager
        def failing_scandir(path):
            def entries():
                raise OSError("directory iteration failed: /Users/private-developer/project")
                yield  # Make this an iterator whose first next() fails.
            yield entries()

        with patch.object(MODULE.os, "scandir", side_effect=failing_scandir):
            with self.assertRaisesRegex(ValueError, "directory-read-error") as error:
                self.validate()
        self.assertNotIn("private-developer", str(error.exception))

    def test_changed_file_is_fatal(self):
        self.resource()
        original = os.open

        def change_before_open(path, *args, **kwargs):
            if Path(path) == self.executable:
                self.executable.write_bytes(b"different file size")
            return original(path, *args, **kwargs)

        with patch.object(MODULE.os, "open", side_effect=change_before_open):
            with self.assertRaisesRegex(ValueError, "file-changed-during-read"):
                self.validate()

    def test_bad_payload_creates_no_release_directory_or_source_archive(self):
        resource = self.resource()
        for target, contents, label in (
            (resource, b"resource with /Users/private-developer/project", "developer-home"),
            (self.executable, b"executable with __llvm_prf_data", "llvm-profile-data"),
            (self.executable, b"", "empty-executable"),
        ):
            original = target.read_bytes()
            target.write_bytes(contents)
            with self.subTest(label=label), self.package_context() as (archive, architectures):
                with self.assertRaisesRegex(ValueError, label):
                    MODULE.main()
                archive.assert_not_called()
                architectures.assert_not_called()
            self.assertFalse(self.output.exists())
            target.write_bytes(original)

    def test_preserves_metadata_and_signing_guards_before_packaging(self):
        variants = (
            ("CFBundleExecutable", "../unexpected", "executable"),
            ("CFBundleIdentifier", "com.example.other", "identity/version"),
            ("CFBundleShortVersionString", "9.9.9", "identity/version"),
            ("CFBundleSupportedPlatforms", ["iPhoneOS"], "Simulator build"),
            ("CFBundleSupportedPlatforms", "iPhoneSimulator", "Simulator build"),
        )
        for key, value, error in variants:
            original = self.info[key]
            self.info[key] = value
            self.write_info()
            with self.subTest(key=key), self.package_context() as (archive, architectures):
                with self.assertRaisesRegex(ValueError, error):
                    MODULE.main()
                archive.assert_not_called()
                architectures.assert_not_called()
                self.assertFalse(self.output.exists())
            self.info[key] = original
        self.write_info()
        for name in ("embedded.mobileprovision", "_CodeSignature"):
            path = self.app / name
            path.mkdir() if name == "_CodeSignature" else path.write_bytes(b"signing material")
            with self.subTest(name=name), self.package_context() as (archive, architectures):
                with self.assertRaisesRegex(ValueError, "signing-material"):
                    MODULE.main()
                archive.assert_not_called()
                architectures.assert_not_called()
                self.assertFalse(self.output.exists())
            path.rmdir() if path.is_dir() else path.unlink()

    def test_signing_material_cannot_be_removed_after_snapshot_to_bypass_guard(self):
        validate_payload = MODULE.validate_app_payload
        for name in ("embedded.mobileprovision", "_CodeSignature"):
            path = self.app / name
            path.mkdir() if name == "_CodeSignature" else path.write_bytes(b"signing material")
            removed_after_scan = []

            def remove_after_scan(*args, **kwargs):
                files = validate_payload(*args, **kwargs)
                path.rmdir() if path.is_dir() else path.unlink()
                removed_after_scan.append(True)
                return files

            with self.subTest(name=name), self.package_context() as (archive, architectures):
                with patch.object(MODULE, "validate_app_payload", side_effect=remove_after_scan):
                    with self.assertRaisesRegex(ValueError, f"{name} .*signing-material"):
                        MODULE.main()
                archive.assert_not_called()
                architectures.assert_not_called()
                self.assertEqual(removed_after_scan, [])
                self.assertFalse(self.output.exists())
            path.rmdir() if path.is_dir() else path.unlink()

    def test_signing_material_added_after_unsigned_snapshot_is_not_archived(self):
        validate_payload = MODULE.validate_app_payload

        def add_after_scan(*args, **kwargs):
            files = validate_payload(*args, **kwargs)
            (self.app / "embedded.mobileprovision").write_bytes(b"late signing material")
            signature = self.app / "_CodeSignature"
            signature.mkdir()
            (signature / "CodeResources").write_bytes(b"late resource seal")
            return files

        with self.package_context() as (archive, architectures):
            with patch.object(MODULE, "validate_app_payload", side_effect=add_after_scan):
                MODULE.main()
            archive.assert_called_once()
            architectures.assert_called_once_with(self.executable_bytes)
        with zipfile.ZipFile(self.output / "room-inventory-ios-0.1.0-rc-unsigned-simulator.zip") as archive_zip:
            self.assertEqual(set(archive_zip.namelist()), {
                "RoomInventory.app/Info.plist", "RoomInventory.app/RoomInventory", "PREVIEW-README.txt",
            })

    def test_missing_or_malformed_info_plist_fails_before_output(self):
        info_path = self.app / "Info.plist"
        for contents in (b"not a plist", b"<?xml version='1.0'?><plist><broken>", None):
            info_path.write_bytes(contents) if contents is not None else info_path.unlink()
            with self.subTest(contents=contents), self.package_context() as (archive, architectures):
                with self.assertRaisesRegex(ValueError, "Invalid Simulator app metadata: Info.plist"):
                    MODULE.main()
                archive.assert_not_called()
                architectures.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_packages_verified_snapshot_with_executable_permissions(self):
        resource = self.resource()
        resource.chmod(0o644)
        with self.package_context() as (archive, architectures):
            def mutate_after_validation(executable):
                self.assertEqual(executable, self.executable_bytes)
                self.executable.write_bytes(b"/Users/private-developer/replaced-after-validation")
                (self.app / "late-resource").write_bytes(b"__llvm_profile_late")
                return "arm64 x86_64"

            architectures.side_effect = mutate_after_validation
            MODULE.main()
            archive.assert_called_once_with(["git", "archive", "--format=tar", "--prefix=room-inventory-ios/", "a" * 40], cwd=self.root)
        with zipfile.ZipFile(self.output / "room-inventory-ios-0.1.0-rc-unsigned-simulator.zip") as archive_zip:
            binary = archive_zip.getinfo("RoomInventory.app/RoomInventory")
            self.assertEqual(archive_zip.read(binary), self.executable_bytes)
            self.assertEqual(stat.S_IMODE(binary.external_attr >> 16), 0o755)
            self.assertEqual(binary.create_system, 3)
            self.assertEqual(stat.S_IMODE(archive_zip.getinfo("RoomInventory.app/Resources/en.lproj/Localizable.strings").external_attr >> 16), 0o644)
            self.assertNotIn("RoomInventory.app/late-resource", archive_zip.namelist())
        metadata = json.loads((self.output / "preview-build.json").read_text())
        self.assertEqual(metadata["architectures"], "arm64 x86_64")
        self.assertEqual(metadata["source_commit"], "a" * 40)
        self.assertFalse(metadata["app_store_release"])

    def test_lipo_reads_exact_snapshot_and_temporary_copy_is_removed(self):
        inspected = []

        def inspect(arguments, **kwargs):
            self.assertEqual(arguments[:2], ["lipo", "-archs"])
            path = Path(arguments[2])
            inspected.append(path)
            self.assertEqual(path.read_bytes(), self.executable_bytes)
            self.assertEqual(kwargs["stderr"], subprocess.PIPE)
            return "arm64 x86_64\n"

        with patch.object(MODULE.subprocess, "check_output", side_effect=inspect):
            self.assertEqual(MODULE.snapshot_architectures(self.executable_bytes), "arm64 x86_64")
        self.assertEqual(len(inspected), 1)
        self.assertFalse(inspected[0].exists())

    def test_lipo_failure_is_redacted(self):
        failure = subprocess.CalledProcessError(1, ["lipo", "/Users/private-developer/path"], stderr=b"/Users/private-developer/path")
        with patch.object(MODULE.subprocess, "check_output", side_effect=failure):
            with self.assertRaisesRegex(ValueError, "architecture-read-error") as error:
                MODULE.snapshot_architectures(self.executable_bytes)
        self.assertNotIn("private-developer", str(error.exception))


if __name__ == "__main__":
    unittest.main()
