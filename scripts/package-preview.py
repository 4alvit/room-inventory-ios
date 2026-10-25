#!/usr/bin/env python3
"""Package committed source and a local unsigned Simulator build; never publish."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "release-dist"
APP = ROOT / ".build/ReleaseSimulator/Build/Products/Release-iphonesimulator/RoomInventory.app"
REQUEST = ROOT / ".build/preview-request.json"


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
    with (APP / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info["CFBundleShortVersionString"] != args.version or info["CFBundleIdentifier"] != "com.alvit.roominventory":
        raise ValueError("Built app identity/version differs from release inputs")
    if "iPhoneSimulator" not in info.get("CFBundleSupportedPlatforms", []):
        raise ValueError("Expected an iOS Simulator build, not a device archive")
    if (APP / "embedded.mobileprovision").exists() or (APP / "_CodeSignature").exists():
        raise ValueError("Expected an unsigned Simulator app without signing material")
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
        for path in sorted(APP.rglob("*")):
            if path.is_symlink():
                raise ValueError("Unexpected symlink in Simulator app")
            if path.is_file():
                archive_zip.write(path, Path("RoomInventory.app") / path.relative_to(APP))
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
        "architectures": checked_output("lipo", "-archs", str(APP / info["CFBundleExecutable"])),
        "minimum_ios": info.get("MinimumOSVersion"),
        "toolkit_revision": "755c2e66fb1e79fc67d9e4c85ecffcc046b967db",
    }
    (OUTPUT / "preview-build.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (OUTPUT / "PREVIEW-README.txt").write_text(preview_notice)
    sums = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in sorted(OUTPUT.iterdir()) if path.is_file()]
    (OUTPUT / "SHA256SUMS").write_text("".join(sums))
    print("Packaged source and unsigned Simulator preview in release-dist; no publication performed")


if __name__ == "__main__":
    main()
