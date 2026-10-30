#!/usr/bin/env python3
"""Install the digest-pinned XcodeGen distribution into ignored local build space."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.46.0"
DIGEST = "4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806"
URL = f"https://github.com/yonaskolb/XcodeGen/releases/download/{VERSION}/xcodegen.zip"
DESTINATION = ROOT / ".build" / "tools" / f"xcodegen-{VERSION}"


def main() -> None:
    executable = DESTINATION / "xcodegen" / "bin" / "xcodegen"
    receipt = DESTINATION / "receipt.sha256"
    if executable.is_file() and receipt.is_file():
        expected = receipt.read_text().strip()
        if expected == hashlib.sha256(executable.read_bytes()).hexdigest():
            print(executable)
            return
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=60) as response:
        payload = response.read(32 * 1024 * 1024 + 1)
    if hashlib.sha256(payload).hexdigest() != DIGEST:
        raise SystemExit("XcodeGen archive digest mismatch; refusing installation")
    temporary = Path(tempfile.mkdtemp(prefix="xcodegen-", dir=DESTINATION.parent))
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for member in archive.infolist():
                path = PurePosixPath(member.filename)
                mode = member.external_attr >> 16
                if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
                    raise SystemExit("Unsafe member in XcodeGen archive")
            archive.extractall(temporary)
        binary = temporary / "xcodegen" / "bin" / "xcodegen"
        binary.chmod(0o755)
        version = subprocess.check_output([str(binary), "--version"], text=True).strip()
        if version != f"Version: {VERSION}":
            raise SystemExit("Unexpected XcodeGen version")
        (temporary / "receipt.sha256").write_text(hashlib.sha256(binary.read_bytes()).hexdigest() + "\n")
        if DESTINATION.is_symlink():
            raise SystemExit("Refusing to replace a symlink tool directory")
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        os.replace(temporary, DESTINATION)
        print(executable)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    main()
