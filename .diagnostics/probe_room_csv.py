#!/usr/bin/env python3
"""One hosted observation of immutable Room source; never software acceptance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import threading
import time

HEAD = "060c24a995239c7ea2a82bb03969227da4997c59"
TREE = "c6edd9909e79e71bab079926546d6ed8727c8700"
CASES = ("testPreferredLanguagesAtLaunch", "testRussianCreationEditingAndCSVExportWithUSRegion")
MIB = 1024 * 1024
FINAL_CAP = 8 * MIB - 64 * 1024
WORK_SECONDS = 16 * 60
FINALIZE_SECONDS = 40
ACTIVE_DEADLINE = None


class Tail:
    def __init__(self, limit):
        self.limit, self.data, self.dropped = limit, bytearray(), 0

    def add(self, data):
        self.data.extend(data)
        excess = max(0, len(self.data) - self.limit)
        if excess:
            del self.data[:excess]
            self.dropped += excess


def stop(process):
    # The session leader may have exited while descendants still own its pipe.
    # start_new_session=True makes this group exclusive to our command.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.poll()
        return True
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return False
    return True


def tree_size(path):
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except FileNotFoundError:
            # xcresult writers can replace their own temporary files.
            continue
    return total


def event_count(data):
    count = 0
    for line in data.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if isinstance(event, dict) and "eventMessage" in event and "timestamp" in event:
            count += 1
    return count


def command(args, cwd, timeout=30, cap=256 * 1024, on_chunk=None, directory_limit=None):
    if ACTIVE_DEADLINE is not None:
        timeout = min(timeout, ACTIVE_DEADLINE - time.monotonic())
    if timeout <= 0:
        raise RuntimeError("Overall observation time budget exhausted")
    tail = Tail(cap)
    process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    timed_out = False
    resource_limited = False
    next_size_check = time.monotonic()
    try:
        while selector.get_map():
            if directory_limit and time.monotonic() >= next_size_check:
                path, limit = directory_limit
                size = tree_size(path)
                if size > limit:
                    resource_limited = True
                    break
                next_size_check = time.monotonic() + 1
            if time.monotonic() >= deadline:
                timed_out = True
                break
            for key, _ in selector.select(timeout=min(0.2, max(0, deadline - time.monotonic()))):
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                tail.add(data)
                if on_chunk:
                    on_chunk(data)
        if not timed_out and not resource_limited:
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
        if directory_limit:
            path, limit = directory_limit
            size = tree_size(path)
            resource_limited = resource_limited or size > limit
    finally:
        cleanup_ok = stop(process)
        selector.close()
        process.stdout.close()
    return {"exit": process.returncode, "timed_out": timed_out,
            "cleanup_ok": cleanup_ok, "resource_limited": resource_limited,
            "dropped_bytes": tail.dropped}, bytes(tail.data)


def checked(args, cwd, timeout=30):
    result, data = command(args, cwd, timeout)
    if result["exit"] or result["timed_out"] or result["dropped_bytes"] or not result["cleanup_ok"]:
        raise RuntimeError("Command failed: " + args[0] + " " + args[1] + ": " + data[-1000:].decode(errors="replace"))
    return data.decode().strip()


def select_device(inventory):
    devices = inventory.get("devices", {}).get("com.apple.CoreSimulator.SimRuntime.iOS-26-2", [])
    matches = [d for d in devices if d.get("isAvailable") is True and d.get("name") == "iPhone 17 Pro"]
    if len(matches) != 1 or not re.fullmatch(r"[0-9A-Fa-f-]{36}", matches[0].get("udid", "")):
        raise RuntimeError("Need exactly one available iPhone 17 Pro on iOS 26.2; no substitute runtime")
    return matches[0]


def walk_records(value):
    if isinstance(value, dict):
        if "exportedFileName" in value:
            yield value
        for item in value.values():
            yield from walk_records(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_records(item)


def choose_attachments(manifest):
    records = list(walk_records(manifest))
    failure = any(str(r.get("suggestedHumanReadableName", "")).startswith("ru-csv-share-failure_") for r in records)
    stem = "ru-csv-share-failure" if failure else "ru-csv-share"
    selected = []
    for suffix, target, limit in [("_", "share.png", MIB), ("-accessibility_", "share-ax.txt", 256 * 1024)]:
        found = [r for r in records if str(r.get("suggestedHumanReadableName", "")).startswith(stem + suffix)]
        if len(found) == 1:
            selected.append((found[0], target, limit))
    return selected


def summary_valid(summary, udid, outcomes):
    devices = summary.get("devicesAndConfigurations", [])
    return (summary.get("totalTestCount") == 2 and summary.get("skippedTests") == 0
            and summary.get("expectedFailures", 0) == 0
            and summary.get("passedTests", 0) + summary.get("failedTests", 0) == 2
            and len(devices) == 1 and devices[0].get("device", {}).get("deviceId") == udid
            and devices[0].get("device", {}).get("osVersion") == "26.2"
            and set(outcomes) == set(CASES)
            and list(outcomes.values()).count("passed") == summary.get("passedTests", 0)
            and list(outcomes.values()).count("failed") == summary.get("failedTests", 0))


def main():
    global ACTIVE_DEADLINE
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "macOS"
            or os.environ.get("GITHUB_REPOSITORY") != "4alvit/room-inventory-ios"
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
        raise SystemExit("Hosted first attempt only; refusing local or repeat execution")
    source = Path(sys.argv[1]).resolve()
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    root = runner_temp / ("room-csv-once-" + os.environ["GITHUB_RUN_ID"])
    root.mkdir(mode=0o700)
    started = time.monotonic()
    ACTIVE_DEADLINE = started + WORK_SECONDS
    output = root / "evidence"
    output.mkdir(mode=0o700)
    report = {"source_head": HEAD, "source_tree": TREE, "status": "PRECHECK_FAILED",
              "software_acceptance": False, "recovery_executed": False,
              "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": 1,
              "orchestration_sha": os.environ["GITHUB_SHA"], "commands": {}, "outcomes": {},
              "work_budget_seconds": WORK_SECONDS, "finalize_budget_seconds": FINALIZE_SECONDS}
    logger = None
    log_thread = None
    log_tail = Tail(5 * MIB)
    log_stop = threading.Event()
    log_errors = []
    logger_closed = False
    def archive_log():
        nonlocal logger_closed
        if logger is None or logger_closed:
            return
        alive = logger.poll() is None
        cleanup_ok = stop(logger)
        log_stop.set()
        if log_thread:
            log_thread.join(timeout=3)
        payload = bytes(log_tail.data)
        (output / "share-system-tail.ndjson").write_bytes(payload)
        report["system_log"] = {"exit": logger.returncode, "dropped_bytes": log_tail.dropped,
                                "bytes": len(payload), "parsed_events": event_count(payload),
                                "reader_stopped": log_thread is not None and not log_thread.is_alive(),
                                "collector_errors": log_errors, "cleanup_ok": cleanup_ok,
                                "alive_until_test_end": alive,
                                "scope": "test pass, filtered processes/messages; tail on cap"}
        logger_closed = True
    try:
        if checked(["git", "rev-parse", "HEAD"], source) != HEAD or checked(["git", "rev-parse", "HEAD^{tree}"], source) != TREE:
            raise RuntimeError("Immutable application source mismatch")
        checked(["git", "diff", "--exit-code", "HEAD"], source)
        version = checked(["xcodebuild", "-version"], source)
        sdk = checked(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"], source)
        report.update(xcode=version, sdk=sdk)
        if version != "Xcode 16.4\nBuild version 16F6" or sdk != "18.5":
            raise RuntimeError("Original toolchain unavailable; no substitution")
        if os.environ.get("RUNNER_ARCH") != "ARM64":
            raise RuntimeError("Original ARM runner required")
        device = select_device(json.loads(checked(["xcrun", "simctl", "list", "devices", "available", "--json"], source)))
        report["device"] = device
        udid = device["udid"]
        checked(["xcrun", "xcresulttool", "export", "attachments", "--help"], source)
        generator = checked([sys.executable, "scripts/install-xcodegen.py"], source, 120)
        checked([generator, "generate", "--spec", "project.yml"], source, 60)
        derived, xcresult = root / "DerivedData", root / "Probe.xcresult"
        common = ["xcodebuild", "-project", "RoomInventory.xcodeproj", "-scheme", "RoomInventory",
                  "-configuration", "Debug", "-destination", "platform=iOS Simulator,id=" + udid,
                  "-derivedDataPath", str(derived), "-parallel-testing-enabled", "NO", "CODE_SIGNING_ALLOWED=NO"]
        build, data = command(common + ["build-for-testing"], source, 600)
        report["commands"]["build"] = build
        (output / "build-tail.log").write_bytes(data)
        if build["exit"] or build["timed_out"] or not build["cleanup_ok"]:
            report["status"] = "BUILD_FAILED"
            raise RuntimeError("Build failed before the single test pass")
        if device.get("state") != "Booted":
            checked(["xcrun", "simctl", "boot", udid], source, 30)
        checked(["xcrun", "simctl", "bootstatus", udid, "-b"], source, 120)
        predicate = ('process == "RoomInventory" OR process CONTAINS[c] "sharing" OR '
                     'process CONTAINS[c] "share" OR eventMessage CONTAINS "UIActivity" OR '
                     'eventMessage CONTAINS "com.alvit.roominventory"')
        logger = subprocess.Popen(["xcrun", "simctl", "spawn", udid, "log", "stream", "--style", "ndjson",
                                   "--level", "debug", "--predicate", predicate], stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, start_new_session=True)
        def collect():
            try:
                while not log_stop.is_set():
                    data = logger.stdout.read1(65536)
                    if not data:
                        break
                    log_tail.add(data)
            except Exception as exc:
                log_errors.append(str(exc)[:500])
        log_thread = threading.Thread(target=collect, daemon=True)
        log_thread.start()
        pending = bytearray()
        starts = []
        def observe(data):
            pending.extend(data)
            while b"\n" in pending:
                line, _, rest = pending.partition(b"\n")
                pending[:] = rest
                text = line.decode(errors="replace")
                for case in CASES:
                    marker = "LocalizationUITests " + case + "]' "
                    if marker in text:
                        if " started." in text:
                            starts.append(case)
                        for outcome in ("passed", "failed", "skipped"):
                            if marker + outcome in text:
                                report["outcomes"][case] = outcome
            if len(pending) > 65536:
                pending.clear()
        report["test_started_epoch"] = time.time()
        report["status"] = "INCOMPLETE_OBSERVATION"
        test, data = command(common + ["-resultBundlePath", str(xcresult), "-only-testing:RoomInventoryUITests/LocalizationUITests",
                                      "-test-iterations", "1", "test-without-building"], source, 360, 768 * 1024, observe,
                             directory_limit=(xcresult, 192 * MIB))
        report["test_finished_epoch"] = time.time()
        report["commands"]["test"] = test
        report["case_start_sequence"] = starts
        (output / "test-tail.log").write_bytes(data)
        archive_log()
        summary_result, summary_data = command(["xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(xcresult), "--compact"], source, 30, 128 * 1024)
        report["commands"]["summary"] = summary_result
        if summary_result["exit"] or summary_result["timed_out"] or summary_result["dropped_bytes"] or not summary_result["cleanup_ok"]:
            raise RuntimeError("Complete bounded test summary unavailable")
        summary = json.loads(summary_data)
        (output / "summary.json").write_bytes(summary_data)
        if not summary_valid(summary, udid, report["outcomes"]) or starts != list(CASES):
            raise RuntimeError("Exact two-test sequence/count/device not proven")
        if test["timed_out"] or test["resource_limited"] or not test["cleanup_ok"]:
            raise RuntimeError("Observation reached its time/storage limit")
        report["status"] = "NO_REPRO" if test["exit"] == 0 and summary.get("failedTests") == 0 else "OBSERVED_TEST_FAILURE"
        attachments = root / "attachments"
        attachment_result, _ = command(["xcrun", "xcresulttool", "export", "attachments", "--path", str(xcresult),
                                       "--output-path", str(attachments), "--test-id",
                                       "LocalizationUITests/testRussianCreationEditingAndCSVExportWithUSRegion()"], source, 45, 32 * 1024,
                                      directory_limit=(attachments, 96 * MIB))
        report["commands"]["attachments"] = attachment_result
        report["retained_attachments"] = []
        if (attachment_result["exit"] == 0 and attachment_result["cleanup_ok"]
                and not attachment_result["timed_out"] and not attachment_result["resource_limited"]):
            manifest = attachments / "manifest.json"
            if manifest.is_file() and manifest.stat().st_size <= 256 * 1024:
                for record, target, limit in choose_attachments(json.loads(manifest.read_text())):
                    filename = record.get("exportedFileName", "")
                    path = attachments / filename
                    if Path(filename).name != filename or path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
                        continue
                    payload = path.read_bytes()
                    if target.endswith(".png") and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                        continue
                    (output / target).write_bytes(payload)
                    report["retained_attachments"].append({"name": target, "original": record, "bytes": len(payload),
                                                           "sha256": hashlib.sha256(payload).hexdigest()})
    except Exception as exc:
        report["error"] = str(exc)[:3000]
    finally:
        archive_log()
        ACTIVE_DEADLINE = time.monotonic() + FINALIZE_SECONDS
        try:
            report["source_unchanged_after"] = (checked(["git", "rev-parse", "HEAD"], source) == HEAD
                and checked(["git", "rev-parse", "HEAD^{tree}"], source) == TREE
                and checked(["git", "diff", "--exit-code", "HEAD"], source) == "")
        except Exception:
            report["source_unchanged_after"] = False
        if not report["source_unchanged_after"]:
            report["status"] = "SOURCE_PIN_INVALID"
            report["error"] = "Source head/tree/content did not remain at the requested revision"
        log = report.get("system_log", {})
        completeness = {"summary": (output / "summary.json").is_file(),
                        "png": (output / "share.png").is_file(),
                        "accessibility": (output / "share-ax.txt").is_file(),
                        "system_log": bool(log.get("parsed_events") and log.get("reader_stopped")
                                           and log.get("alive_until_test_end") and log.get("dropped_bytes") == 0
                                           and not log.get("collector_errors") and log.get("cleanup_ok")),
                        "source_unchanged": report["source_unchanged_after"]}
        completeness["overall"] = all(completeness.values())
        report["evidence_complete"] = completeness
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        entries = [{"path": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in sorted(output.iterdir()) if p.is_file()]
        (output / "manifest.json").write_text(json.dumps({"source_head": HEAD, "entries": entries}, indent=2) + "\n")
        total = sum(p.stat().st_size for p in output.iterdir() if p.is_file())
        if total > FINAL_CAP:
            raise SystemExit("Evidence exceeds hard upload cap; no upload path emitted")
        with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
            handle.write("evidence=" + str(output) + "\n")
            handle.write("evidence_ready=true\n")
        print(json.dumps({"status": report["status"], "outcomes": report["outcomes"], "bytes": total,
                          "error": report.get("error"), "software_acceptance": False}))
    return 0 if report["status"] == "NO_REPRO" and report["evidence_complete"]["overall"] and "error" not in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
