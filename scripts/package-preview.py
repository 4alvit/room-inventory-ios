#!/usr/bin/env python3
"""Package committed source and a local unsigned Simulator build; never publish."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import tempfile
import time
from xml.parsers.expat import ExpatError
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "release-dist"
APP = ROOT / ".build/ReleaseSimulator/Build/Products/Release-iphonesimulator/RoomInventory.app"
REQUEST = ROOT / ".build/preview-request.json"
EXECUTABLE = "RoomInventory"


def checked_output(*arguments: str) -> str:
    return subprocess.check_output(arguments, cwd=ROOT, text=True).strip()


def validate_request(version: str, channel: str, *, root: Path = ROOT) -> None:
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
        raise ValueError("Expected numeric X.Y.Z base version")
    if channel not in {"nightly", "beta", "rc"}:
        raise ValueError("Only nightly, beta and rc preview builds are supported")
    if (root / "VERSION").read_text().strip() != version:
        raise ValueError("Requested version differs from committed VERSION")


def ensure_clean_source() -> str:
    source = checked_output("git", "rev-parse", "HEAD")
    if checked_output("git", "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Preview packaging requires a clean committed checkout; preserve and commit reviewed work first")
    return source


def validate_app_payload(app: Path, *, root: Path = ROOT) -> dict[Path, tuple[bytes, os.stat_result]]:
    """Read a complete, verified snapshot before creating any release artifacts."""
    markers = {
        "developer-home": b"/Users/",
        "runner-home": b"/home/runner/",
        "developer-temporary-directory": b"/private/var/folders/",
        "build-root": os.fsencode(root),
        "llvm-profile-data": b"__llvm_prf",
        "llvm-coverage": b"__llvm_cov",
        "llvm-profile-counter": b"___profc_",
        "llvm-profile-runtime": b"__llvm_profile",
    }
    files: dict[Path, tuple[bytes, os.stat_result]] = {}

    def reject(relative: Path, label: str) -> None:
        # Never interpolate the offending bytes or an OS exception with absolute paths.
        raise ValueError(f"Unsafe Simulator app payload: {relative.as_posix()} [{label}]") from None

    def inspect(path: Path, relative: Path) -> None:
        try:
            entry_stat = path.lstat()
        except OSError:
            reject(relative, "stat-error")
        if stat.S_ISLNK(entry_stat.st_mode):
            reject(relative, "symlink")
        if stat.S_ISDIR(entry_stat.st_mode):
            try:
                with os.scandir(path) as entries:
                    children = sorted(entries, key=lambda entry: entry.name)
            except OSError:
                reject(relative, "directory-read-error")
            for entry in children:
                child_relative = relative / entry.name
                if relative == Path(".") and entry.name in {"embedded.mobileprovision", "_CodeSignature"}:
                    reject(child_relative, "signing-material")
                inspect(path / entry.name, child_relative)
            return
        if not stat.S_ISREG(entry_stat.st_mode):
            reject(relative, "nonregular-file")
        try:
            # O_NOFOLLOW also rejects a file replaced by a symlink since lstat.
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as stream:
                opened_stat = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened_stat.st_mode):
                    reject(relative, "nonregular-file")
                contents = stream.read()
                finished_stat = os.fstat(stream.fileno())
        except OSError:
            reject(relative, "file-read-error")
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(entry_stat) != identity(opened_stat) or identity(opened_stat) != identity(finished_stat) or len(contents) != finished_stat.st_size:
            reject(relative, "file-changed-during-read")
        for label, marker in markers.items():
            if marker in contents:
                reject(relative, label)
        files[relative] = (contents, finished_stat)

    try:
        app_stat = app.lstat()
    except OSError:
        reject(Path("."), "stat-error")
    if stat.S_ISLNK(app_stat.st_mode):
        reject(Path("."), "symlink")
    if not stat.S_ISDIR(app_stat.st_mode):
        reject(Path("."), "not-directory")
    inspect(app, Path("."))
    executable = files.get(Path(EXECUTABLE))
    if executable is None:
        reject(Path(EXECUTABLE), "missing-executable")
    if not executable[0]:
        reject(Path(EXECUTABLE), "empty-executable")
    if not executable[1].st_mode & 0o111:
        reject(Path(EXECUTABLE), "not-executable")
    return files


def snapshot_architectures(executable: bytes) -> str:
    """Run lipo on the same executable bytes that will be included in the ZIP."""
    try:
        with tempfile.TemporaryDirectory(prefix="room-preview-") as temporary:
            path = Path(temporary) / EXECUTABLE
            path.write_bytes(executable)
            return subprocess.check_output(["lipo", "-archs", str(path)], cwd=ROOT, text=True, stderr=subprocess.PIPE).strip()
    except (OSError, subprocess.CalledProcessError):
        raise ValueError(f"Cannot inspect Simulator app executable: {EXECUTABLE} [architecture-read-error]") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "package"))
    parser.add_argument("version")
    parser.add_argument("channel")
    args = parser.parse_args()
    validate_request(args.version, args.channel)
    source = ensure_clean_source()
    identity = {"source_commit": source, "base_version": args.version, "channel": args.channel}
    if args.action == "prepare":
        if OUTPUT.is_symlink():
            raise ValueError("Release output must not be a symlink")
        if OUTPUT.exists() and any(OUTPUT.iterdir()):
            raise ValueError("release-dist must be empty; preserve or remove old artifacts before packaging")
        REQUEST.parent.mkdir(parents=True, exist_ok=True)
        REQUEST.write_text(json.dumps(identity, sort_keys=True) + "\n")
        print("Source is clean; unsigned Simulator preview build may begin")
        return
    if not REQUEST.is_file() or json.loads(REQUEST.read_text()) != identity:
        raise ValueError("Source or release inputs changed since preview preparation; run a fresh build")
    files = validate_app_payload(APP, root=ROOT)
    try:
        info = plistlib.loads(files[Path("Info.plist")][0])
    except (KeyError, ValueError, ExpatError, plistlib.InvalidFileException):
        raise ValueError("Invalid Simulator app metadata: Info.plist") from None
    if not isinstance(info, dict) or info.get("CFBundleExecutable") != EXECUTABLE:
        raise ValueError("Unexpected Simulator app executable in Info.plist")
    if info.get("CFBundleShortVersionString") != args.version or info.get("CFBundleIdentifier") != "com.alvit.roominventory":
        raise ValueError("Built app identity/version differs from release inputs")
    platforms = info.get("CFBundleSupportedPlatforms", [])
    if not isinstance(platforms, list) or "iPhoneSimulator" not in platforms:
        raise ValueError("Expected an iOS Simulator build, not a device archive")
    architectures = snapshot_architectures(files[Path(EXECUTABLE)][0])
    if OUTPUT.is_symlink():
        raise ValueError("Release output must not be a symlink")
    OUTPUT.mkdir(exist_ok=True)
    if any(OUTPUT.iterdir()):
        raise ValueError("Refusing to overwrite existing release artifacts")
    prefix = f"room-inventory-ios-{args.version}-{args.channel}"
    archive = subprocess.check_output(["git", "archive", "--format=tar", "--prefix=room-inventory-ios/", source], cwd=ROOT)
    with (OUTPUT / f"{prefix}-source.tar.gz").open("wb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
            compressed.write(archive)
    preview_notice = (
        "Room Inventory — UNSIGNED iOS Simulator preview\n"
        "This is not an IPA and cannot be installed on an iPhone or iPad.\n"
        "It is not an App Store release. StoreKit configuration/sandbox does not charge real money.\n"
        "Install using: xcrun simctl install booted RoomInventory.app\n"
        "Launch using: xcrun simctl launch booted com.alvit.roominventory\n"
        "Use only synthetic data for prerelease testing. Back up any existing app data first.\n"
        f"Base version: {args.version}\nChannel: {args.channel}\nSource commit: {source}\n"
    )
    with zipfile.ZipFile(OUTPUT / f"{prefix}-unsigned-simulator.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive_zip:
        for relative, (contents, file_stat) in sorted(files.items()):
            modified = max(time.localtime(file_stat.st_mtime)[:6], (1980, 1, 1, 0, 0, 0))
            entry = zipfile.ZipInfo((Path("RoomInventory.app") / relative).as_posix(), modified)
            entry.create_system = 3
            entry.external_attr = (file_stat.st_mode & 0xFFFF) << 16
            archive_zip.writestr(entry, contents, compress_type=zipfile.ZIP_DEFLATED)
        archive_zip.writestr("PREVIEW-README.txt", preview_notice)
    metadata = {
        "schema": 1,
        "repository": "4alvit/room-inventory-ios",
        "source_commit": source,
        "base_version": args.version,
        "channel": args.channel,
        "artifact_kind": "unsigned-ios-simulator-preview",
        "app_store_release": False,
        "real_purchases_configured": False,
        "xcode": checked_output("xcodebuild", "-version"),
        "swift": checked_output("swift", "--version"),
        "architectures": architectures,
        "minimum_ios": info.get("MinimumOSVersion"),
        "toolkit_revision": "755c2e66fb1e79fc67d9e4c85ecffcc046b967db",
    }
    (OUTPUT / "preview-build.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (OUTPUT / "PREVIEW-README.txt").write_text(preview_notice)
    sums = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in sorted(OUTPUT.iterdir()) if path.is_file()]
    (OUTPUT / "SHA256SUMS").write_text("".join(sums))
    print("Packaged source and unsigned Simulator preview in release-dist; no publication performed")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        # Expected validation failures must not expose local paths in a traceback.
        raise SystemExit(str(error)) from None
