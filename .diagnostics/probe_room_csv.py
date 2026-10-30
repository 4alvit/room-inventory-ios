#!/usr/bin/env python3
"""One hosted observation of immutable Room source; never software acceptance."""
from __future__ import annotations

import hashlib
import errno
from collections import deque
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
TEST_WINDOW_SECONDS = 480
POST_TEST_RESERVE_SECONDS = 94
ACTIVE_DEADLINE = None
LOG_PREDICATE = ('subsystem == "com.apple.ShareSheet" OR '
                 '(process == "RoomInventory" AND subsystem == "com.apple.foundation.NSItemProvider") OR '
                 '(process == "sharingd" AND subsystem == "com.apple.PeopleSuggester")')


class Tail:
    def __init__(self, limit):
        self.limit, self.data, self.dropped = limit, bytearray(), 0

    def add(self, data):
        self.data.extend(data)
        excess = max(0, len(self.data) - self.limit)
        if excess:
            del self.data[:excess]
            self.dropped += excess


def selected_log_event(event):
    """Mirror the narrow native predicate using fields present in saved ndjson."""
    path = event.get("processImagePath", "")
    process = Path(path).name if isinstance(path, str) else ""
    subsystem = event.get("subsystem")
    return (subsystem == "com.apple.ShareSheet"
            or (process == "RoomInventory" and subsystem == "com.apple.foundation.NSItemProvider")
            or (process == "sharingd" and subsystem == "com.apple.PeopleSuggester"))


class EventLog:
    """Whole selected records only; unrelated traffic cannot evict evidence."""
    def __init__(self, limit, record_limit=64 * 1024):
        self.limit, self.record_limit = limit, record_limit
        self.records, self.pending = deque(), bytearray()
        self.size = self.dropped = self.dropped_events = 0
        self.received_bytes = self.selected_events = self.filtered_events = 0
        self.malformed_lines = self.non_event_lines = 0
        self.oversized_lines = self.oversized_bytes = 0
        self.incomplete_lines = self.incomplete_bytes = 0
        self.skipping = False
        self.lock = threading.RLock()

    @property
    def data(self):
        with self.lock:
            return b"".join(record for record, _ in self.records)

    def add(self, data):
        with self.lock:
            self._add(data)

    def _add(self, data):
        self.received_bytes += len(data)
        fragments = data.split(b"\n")
        for index, fragment in enumerate(fragments):
            complete = index < len(fragments) - 1
            piece = fragment + (b"\n" if complete else b"")
            if self.skipping:
                self.oversized_bytes += len(piece)
            else:
                self.pending.extend(piece)
                if len(self.pending) > self.record_limit:
                    self.oversized_lines += 1
                    self.oversized_bytes += len(self.pending)
                    self.pending.clear()
                    self.skipping = True
            if complete:
                if not self.skipping:
                    self._record(bytes(self.pending))
                self.pending.clear()
                self.skipping = False

    def _record(self, line):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            if line.lstrip().startswith(b"{"):
                self.malformed_lines += 1
            else:
                self.non_event_lines += 1
            return
        if not isinstance(event, dict) or not isinstance(event.get("timestamp"), str) or not isinstance(event.get("eventMessage"), str):
            self.malformed_lines += 1
            return
        if not selected_log_event(event):
            self.filtered_events += 1
            return
        self.selected_events += 1
        self.records.append((line, event["timestamp"]))
        self.size += len(line)
        while self.size > self.limit:
            old, _ = self.records.popleft()
            self.size -= len(old)
            self.dropped += len(old)
            self.dropped_events += 1

    def finish(self):
        with self.lock:
            if self.pending or self.skipping:
                self.incomplete_lines += 1
                self.incomplete_bytes += len(self.pending)
                self.pending.clear()
                self.skipping = False

    def snapshot(self):
        with self.lock:
            return self.data, self.metadata()

    def metadata(self):
        return {"predicate": LOG_PREDICATE, "received_bytes": self.received_bytes,
                "retained_bytes": self.size, "dropped_bytes": self.dropped,
                "selected_events": self.selected_events, "filtered_events": self.filtered_events,
                "retained_events": len(self.records), "dropped_events": self.dropped_events,
                "malformed_lines": self.malformed_lines, "non_event_lines": self.non_event_lines,
                "oversized_lines": self.oversized_lines, "oversized_bytes": self.oversized_bytes,
                "incomplete_lines": self.incomplete_lines, "incomplete_bytes": self.incomplete_bytes,
                "first_retained_timestamp": self.records[0][1] if self.records else None,
                "last_retained_timestamp": self.records[-1][1] if self.records else None,
                "record_limit_bytes": self.record_limit}


def collect_log(stream, log, eof, errors):
    """Drain through EOF; the owning thread only waits its fixed join budget."""
    try:
        while True:
            data = stream.read1(65536)
            if not data:
                eof.set()
                return
            log.add(data)
    except Exception as exc:
        errors.append(str(exc)[:500])


# Reused verbatim from pinned application 060c24a, scripts/run-recovery-journey.py.
def kill_owned(process, deadline, *, state=None, clock=time.monotonic, sleep=time.sleep, killpg=os.killpg):
    state = {} if state is None else state
    state.setdefault("group_state", "unverified")
    state.setdefault("leader_reaped", False)
    state.setdefault("returncode", None)
    state.setdefault("observation_errors", [])
    start = clock()
    end = min(deadline, start + 4, state.get("cleanup_deadline_monotonic", float("inf")))
    state["cleanup_deadline_monotonic"] = end
    report = {"pgid": process.pid, "signals": [], "errors": [], "success": False, "budget_exhausted": False}

    def error(operation, exception):
        item = {"operation": operation, "errno": getattr(exception, "errno", None), "error": type(exception).__name__}
        report["errors"].append(item)
        state["observation_errors"].append(item)

    def note_known_reap():
        code = getattr(process, "returncode", None)
        if code is not None:
            state["returncode"] = code
            state["leader_reaped"] = True

    def observe():
        if clock() >= end:
            report["budget_exhausted"] = True
            return False
        note_known_reap()
        if not state["leader_reaped"]:
            try:
                state["returncode"] = process.wait(timeout=0)
                state["leader_reaped"] = True
            except subprocess.TimeoutExpired:
                pass
            except OSError as exception:
                error("leader_reap", exception)
        if clock() >= end:
            report["budget_exhausted"] = True
            return False
        if state["group_state"] == "absent":
            return state["leader_reaped"]
        try:
            killpg(process.pid, 0)
            state["group_state"] = "present"
        except OSError as exception:
            if exception.errno == errno.ESRCH:
                state["group_state"] = "absent"
            else:
                state["group_state"] = "unknown"
                error("group_probe", exception)
        return state["group_state"] == "absent" and state["leader_reaped"]

    def send(sig):
        # Reaping releases the leader PID; its numeric PGID is no longer a
        # destructive-signal capability. Unknown observations stay failures.
        note_known_reap()
        if (clock() >= end or state["leader_reaped"]
                or state["group_state"] != "present" or state["observation_errors"]):
            return
        try:
            killpg(process.pid, sig)
            report["signals"].append(sig.name)
        except OSError as exception:
            if exception.errno == errno.ESRCH:
                state["group_state"] = "absent"
            else:
                state["group_state"] = "unknown"
                error("group_signal_" + sig.name, exception)

    done = observe()
    for sig, phase_end in ((signal.SIGTERM, min(start + 2, max(start, end - 2))), (signal.SIGKILL, end)):
        if done or clock() >= end:
            break
        send(sig)
        done = observe()
        while not done and clock() < phase_end:
            sleep(min(.05, max(0, phase_end - clock())))
            done = observe()
    report.update({key: state[key] for key in ("group_state", "leader_reaped", "returncode")})
    report["success"] = done and not state["observation_errors"]
    report["budget_exhausted"] |= not done and clock() >= end
    report["elapsed_seconds"] = clock() - start
    return report


def stop(process, evidence=None):
    evidence = {} if evidence is None else evidence
    state = {}
    evidence.update(leader_cached_returncode_before=process.returncode,
                    leader_wait_attempts=0, leader_wait_observations=[],
                    leader_wait_observations_omitted=0)

    class ObservedLeader:
        pid = process.pid

        @property
        def returncode(self):
            return process.returncode

        def wait(self, timeout):
            item = {"operation": "Popen.wait", "timeout": timeout,
                    "at_monotonic": time.monotonic()}
            evidence["leader_wait_attempts"] += 1
            try:
                item["returncode"] = process.wait(timeout=timeout)
                return item["returncode"]
            except Exception as exc:
                item["error"] = error_record("leader_wait", exc)
                raise
            finally:
                if len(evidence["leader_wait_observations"]) < 16:
                    evidence["leader_wait_observations"].append(item)
                else:
                    evidence["leader_wait_observations_omitted"] += 1

    try:
        result = kill_owned(ObservedLeader(), time.monotonic() + 4, state=state,
                            clock=time.monotonic, sleep=time.sleep, killpg=os.killpg)
        evidence.update(result)
        return result["success"]
    finally:
        evidence.update(partial_state=state,
                        leader_cached_returncode_after=process.returncode)


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


def error_record(phase, error):
    return {"phase": phase, "type": type(error).__name__, "errno": getattr(error, "errno", None),
            "message": str(error)[:512]}


def command(args, cwd, timeout=30, cap=256 * 1024, on_chunk=None, directory_limit=None, stage=None,
            full_window_reserve=None):
    result = {"stage": stage or str(args[0])[:128], "command": [str(a)[:512] for a in args[:32]],
              "cwd": str(cwd)[:1024], "pid": None, "pgid": None,
              "pgid_basis": "start_new_session=True; group ID equals child PID",
              "exit": None, "timed_out": False, "resource_limited": False,
              "cleanup_ok": True, "primary_error": None, "cleanup_errors": [], "cleanup_report": {}, "dropped_bytes": 0}
    tail = Tail(cap)
    process = selector = None
    deadline = None
    phase = "budget"
    try:
        if full_window_reserve is not None:
            # This admission is immediately before spawn, after all caller setup.
            # Its command deadline includes process/selector startup and is never renewed.
            phase = "admission"
            now = time.monotonic()
            remaining = None if ACTIVE_DEADLINE is None else ACTIVE_DEADLINE - now
            admitted = (remaining is not None and timeout > 0 and full_window_reserve >= 0
                        and remaining >= timeout + full_window_reserve)
            result["admission"] = {"admitted": admitted, "checked_at_monotonic": now,
                                   "work_deadline_monotonic": ACTIVE_DEADLINE,
                                   "remaining_seconds": remaining, "command_seconds": timeout,
                                   "post_test_reserve_seconds": full_window_reserve,
                                   "required_seconds": timeout + full_window_reserve}
            if not admitted:
                raise RuntimeError("Insufficient original work budget for full test window and post-test reserve")
            deadline = now + timeout
            result["admission"]["command_deadline_monotonic"] = deadline
        elif ACTIVE_DEADLINE is not None:
            timeout = min(timeout, ACTIVE_DEADLINE - time.monotonic())
        if timeout <= 0:
            result["timed_out"] = True
            raise RuntimeError("Overall observation time budget exhausted")
        phase = "spawn"
        process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        result.update(pid=process.pid, pgid=process.pid)
        phase = "selector_setup"
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        if deadline is None:
            deadline = time.monotonic() + timeout
        next_size_check = time.monotonic()
        if full_window_reserve is not None and next_size_check >= deadline:
            result["timed_out"] = True
        while selector.get_map():
            phase = "storage_limit"
            if directory_limit and time.monotonic() >= next_size_check:
                path, limit = directory_limit
                if tree_size(path) > limit:
                    result["resource_limited"] = True
                    break
                next_size_check = time.monotonic() + 1
            if time.monotonic() >= deadline:
                result["timed_out"] = True
                break
            phase = "select"
            for key, _ in selector.select(timeout=min(0.2, max(0, deadline - time.monotonic()))):
                phase = "read"
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                tail.add(data)
                if on_chunk:
                    phase = "output_callback"
                    on_chunk(data)
            phase = "select"
        if not result["timed_out"] and not result["resource_limited"]:
            phase = "wait"
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
        if directory_limit:
            phase = "storage_limit"
            path, limit = directory_limit
            result["resource_limited"] = result["resource_limited"] or tree_size(path) > limit
    except Exception as exc:
        result["primary_error"] = error_record(phase, exc)
    finally:
        # Cleanup failures are evidence too, but must not replace the command's
        # primary exception, timeout flag or captured output.
        try:
            if process is not None:
                try:
                    if not stop(process, result["cleanup_report"]):
                        result["cleanup_errors"].append(error_record("stop", RuntimeError("Owned process cleanup was not verified; see cleanup_report")))
                except Exception as exc:
                    result["cleanup_errors"].append(error_record("stop", exc))
        finally:
            try:
                if selector is not None:
                    try:
                        selector.close()
                    except Exception as exc:
                        result["cleanup_errors"].append(error_record("selector_close", exc))
            finally:
                if process is not None and process.stdout is not None:
                    try:
                        process.stdout.close()
                    except Exception as exc:
                        result["cleanup_errors"].append(error_record("stdout_close", exc))
    result.update(exit=process.returncode if process is not None else None,
                  cleanup_ok=not result["cleanup_errors"], dropped_bytes=tail.dropped)
    return result, bytes(tail.data)


def command_ok(result):
    return (result["exit"] == 0 and not result["timed_out"] and not result["resource_limited"]
            and result["cleanup_ok"] and result["primary_error"] is None)


class CommandFailure(RuntimeError):
    def __init__(self, result, data):
        self.result = dict(result, output_tail=data[-4096:].decode(errors="replace"),
                           output_tail_bytes=min(len(data), 4096))
        super().__init__("Command failed at " + result["stage"])


def checked(args, cwd, timeout=30, stage=None):
    result, data = command(args, cwd, timeout, stage=stage)
    if not command_ok(result) or result["dropped_bytes"]:
        raise CommandFailure(result, data)
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
    log_tail = EventLog(5 * MIB)
    log_eof = threading.Event()
    log_errors = []
    logger_closed = False
    def archive_log():
        nonlocal logger_closed
        if logger is None or logger_closed:
            return
        logger_closed = True
        alive = logger.poll() is None
        cleanup_errors = []
        cleanup_ok = False
        cleanup_report = {}
        try:
            cleanup_ok = stop(logger, cleanup_report)
        except Exception as exc:
            cleanup_errors.append(error_record("logger_stop", exc))
        finally:
            if log_thread:
                try:
                    log_thread.join(timeout=3)
                except Exception as exc:
                    cleanup_errors.append(error_record("logger_join", exc))
            # Latch once before taking the snapshot. A reader that finishes
            # later must not make an earlier partial snapshot look complete.
            reader_stopped = log_thread is not None and not log_thread.is_alive()
            reader_reached_eof = reader_stopped and log_eof.is_set()
            # Closing a buffered pipe while its reader is still blocked can
            # itself block. Retain an explicit failure instead of waiting.
            if log_thread is None or reader_stopped:
                try:
                    logger.stdout.close()
                except Exception as exc:
                    cleanup_errors.append(error_record("logger_stdout_close", exc))
        if log_thread is None or reader_stopped:
            log_tail.finish()
        payload, filter_metadata = log_tail.snapshot()
        (output / "share-system-tail.ndjson").write_bytes(payload)
        report["system_log"] = {"exit": logger.returncode, "dropped_bytes": filter_metadata["dropped_bytes"],
                                "bytes": len(payload), "parsed_events": event_count(payload),
                                "reader_stopped": reader_stopped,
                                "reader_reached_eof": reader_reached_eof,
                                "collector_errors": list(log_errors), "cleanup_errors": cleanup_errors,
                                "cleanup_report": cleanup_report,
                                "pid": logger.pid, "pgid": logger.pid,
                                "cleanup_ok": cleanup_ok and not cleanup_errors,
                                "alive_until_test_end": alive,
                                "scope": "test pass; exact subsystem/process predicate; whole selected record tail",
                                "filter": filter_metadata}
    try:
        if (checked(["git", "rev-parse", "HEAD"], source, stage="precheck.source_head") != HEAD
                or checked(["git", "rev-parse", "HEAD^{tree}"], source, stage="precheck.source_tree") != TREE):
            raise RuntimeError("Immutable application source mismatch")
        checked(["git", "diff", "--exit-code", "HEAD"], source, stage="precheck.source_diff")
        version = checked(["xcodebuild", "-version"], source, stage="precheck.xcode")
        sdk = checked(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"], source, stage="precheck.sdk")
        report.update(xcode=version, sdk=sdk)
        if version != "Xcode 16.4\nBuild version 16F6" or sdk != "18.5":
            raise RuntimeError("Original toolchain unavailable; no substitution")
        if os.environ.get("RUNNER_ARCH") != "ARM64":
            raise RuntimeError("Original ARM runner required")
        device = select_device(json.loads(checked(["xcrun", "simctl", "list", "devices", "available", "--json"], source, stage="precheck.simctl_devices")))
        report["device"] = device
        udid = device["udid"]
        checked(["xcrun", "xcresulttool", "export", "attachments", "--help"], source, stage="precheck.xcresulttool")
        generator = checked([sys.executable, "scripts/install-xcodegen.py"], source, 120, stage="prepare.xcodegen_install")
        checked([generator, "generate", "--spec", "project.yml"], source, 60, stage="prepare.xcodegen_generate")
        derived, xcresult = root / "DerivedData", root / "Probe.xcresult"
        common = ["xcodebuild", "-project", "RoomInventory.xcodeproj", "-scheme", "RoomInventory",
                  "-configuration", "Debug", "-destination", "platform=iOS Simulator,id=" + udid,
                  "-derivedDataPath", str(derived), "-parallel-testing-enabled", "NO", "CODE_SIGNING_ALLOWED=NO"]
        build, data = command(common + ["build-for-testing"], source, 600, stage="build")
        report["commands"]["build"] = build
        (output / "build-tail.log").write_bytes(data)
        if not command_ok(build):
            report["status"] = "BUILD_FAILED"
            raise RuntimeError("Build failed before the single test pass")
        if device.get("state") != "Booted":
            checked(["xcrun", "simctl", "boot", udid], source, 30, stage="prepare.boot")
        checked(["xcrun", "simctl", "bootstatus", udid, "-b"], source, 120, stage="prepare.bootstatus")
        logger = subprocess.Popen(["xcrun", "simctl", "spawn", udid, "log", "stream", "--style", "ndjson",
                                   "--level", "debug", "--predicate", LOG_PREDICATE], stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, start_new_session=True)
        log_thread = threading.Thread(target=collect_log,
                                      args=(logger.stdout, log_tail, log_eof, log_errors), daemon=True)
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
        report["test_command_requested_epoch"] = time.time()
        report["status"] = "INCOMPLETE_OBSERVATION"
        test, data = command(common + ["-resultBundlePath", str(xcresult), "-only-testing:RoomInventoryUITests/LocalizationUITests",
                                      "test-without-building"], source, TEST_WINDOW_SECONDS, 768 * 1024, observe,
                             directory_limit=(xcresult, 192 * MIB), stage="test",
                             full_window_reserve=POST_TEST_RESERVE_SECONDS)
        report["test_finished_epoch"] = time.time()
        report["commands"]["test"] = test
        report["case_start_sequence"] = starts
        (output / "test-tail.log").write_bytes(data)
        archive_log()
        if not test.get("admission", {}).get("admitted", False):
            report["status"] = "PREFLIGHT_FAILED_INSUFFICIENT_TEST_BUDGET"
            raise RuntimeError("Tests not launched: full test window and reserve did not fit original work deadline")
        if test["primary_error"] is not None or not test["cleanup_ok"]:
            raise RuntimeError("Test command failed during execution or cleanup; see retained command details")
        summary_result, summary_data = command(["xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(xcresult), "--compact"], source, 30, 128 * 1024, stage="summary")
        report["commands"]["summary"] = summary_result
        if not command_ok(summary_result) or summary_result["dropped_bytes"]:
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
                                      directory_limit=(attachments, 96 * MIB), stage="attachments")
        report["commands"]["attachments"] = attachment_result
        report["retained_attachments"] = []
        if command_ok(attachment_result):
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
        if isinstance(exc, CommandFailure):
            report["failed_command_stage"] = exc.result["stage"]
            report["commands"][exc.result["stage"]] = exc.result
    finally:
        archive_log()
        ACTIVE_DEADLINE = time.monotonic() + FINALIZE_SECONDS
        try:
            report["source_unchanged_after"] = (checked(["git", "rev-parse", "HEAD"], source, stage="final.source_head") == HEAD
                and checked(["git", "rev-parse", "HEAD^{tree}"], source, stage="final.source_tree") == TREE
                and checked(["git", "diff", "--exit-code", "HEAD"], source, stage="final.source_diff") == "")
        except Exception as exc:
            report["source_unchanged_after"] = False
            report["source_verification_error"] = str(exc)[:3000]
            if isinstance(exc, CommandFailure):
                report["commands"][exc.result["stage"]] = exc.result
        if not report["source_unchanged_after"]:
            report["status"] = "SOURCE_PIN_INVALID"
            report.setdefault("error", "Source head/tree/content did not remain at the requested revision")
        log = report.get("system_log", {})
        completeness = {"summary": (output / "summary.json").is_file(),
                        "png": (output / "share.png").is_file(),
                        "accessibility": (output / "share-ax.txt").is_file(),
                        "system_log": bool(log.get("parsed_events") and log.get("reader_stopped")
                                           and log.get("reader_reached_eof")
                                           and log.get("alive_until_test_end") and log.get("dropped_bytes") == 0
                                           and not log.get("collector_errors") and log.get("cleanup_ok")
                                           and not any(log.get("filter", {}).get(key, 0) for key in
                                                       ("malformed_lines", "oversized_lines", "incomplete_lines"))),
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
