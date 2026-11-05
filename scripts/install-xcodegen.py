#!/usr/bin/env python3
"""Install the digest-pinned XcodeGen distribution into ignored local build space."""
from __future__ import annotations

from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import hashlib
import io
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.46.0"
DIGEST = "4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806"
URL = f"https://github.com/yonaskolb/XcodeGen/releases/download/{VERSION}/xcodegen.zip"
DESTINATION = ROOT / ".build" / "tools" / f"xcodegen-{VERSION}"
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@contextmanager
def acquisition_deadline(seconds: float):
    """Use a cooperative Unix timer; the hosted owner retains its 70s bound."""
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("XcodeGen download budget must be finite and positive")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise RuntimeError("Refusing to replace an active process timer")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise TimeoutError("XcodeGen download exceeded its acquisition deadline")

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def retry_delay(headers, attempt: int, now: float) -> float:
    """Respect a single Retry-After value without shortening the local backoff."""
    backoff = float(attempt)
    value = headers.get("Retry-After") if headers is not None else None
    if value is None:
        return backoff
    if hasattr(headers, "get_all") and len(headers.get_all("Retry-After")) != 1:
        raise ValueError("Ambiguous XcodeGen Retry-After header")
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        delay = float(value)
    else:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                raise ValueError("Missing Retry-After timezone")
            delay = max(0.0, when.timestamp() - now)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Invalid XcodeGen Retry-After header") from error
    if not math.isfinite(delay):
        raise ValueError("Invalid XcodeGen Retry-After delay")
    return max(backoff, delay)


def download_payload(*, opener=None, clock=None, sleep=None, wall_clock=None, timeout=60.0) -> bytes:
    """Retry only transient response errors within one acquisition budget."""
    opener = opener or urllib.request.urlopen
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    wall_clock = wall_clock or time.time
    deadline = clock() + timeout

    def remaining():
        value = deadline - clock()
        if value <= 0:
            raise TimeoutError("XcodeGen download exceeded its acquisition deadline")
        return value

    with acquisition_deadline(timeout):
        for attempt in range(1, 4):
            try:
                response = opener(URL, timeout=remaining())
            except urllib.error.HTTPError as error:
                try:
                    if error.code not in RETRYABLE_STATUS or attempt == 3:
                        raise
                    delay = retry_delay(error.headers, attempt, wall_clock())
                finally:
                    error.close()
                if delay >= remaining():
                    raise TimeoutError("XcodeGen Retry-After exceeds remaining acquisition budget")
                sleep(delay)
                continue
            # Body, transport, size and integrity failures are never retried.
            with response:
                remaining()
                payload = response.read(MAX_ARCHIVE_BYTES + 1)
            remaining()  # Reject late success even if a C call delayed the timer.
            if len(payload) > MAX_ARCHIVE_BYTES:
                raise ValueError("XcodeGen archive exceeds 32 MiB")
            if hashlib.sha256(payload).hexdigest() != DIGEST:
                raise SystemExit("XcodeGen archive digest mismatch; refusing installation")
            remaining()
            return payload
    raise RuntimeError("XcodeGen download did not produce an archive")


def main() -> None:
    executable = DESTINATION / "xcodegen" / "bin" / "xcodegen"
    receipt = DESTINATION / "receipt.sha256"
    if executable.is_file() and receipt.is_file():
        expected = receipt.read_text().strip()
        if expected == hashlib.sha256(executable.read_bytes()).hexdigest():
            print(executable)
            return
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    payload = download_payload()
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
