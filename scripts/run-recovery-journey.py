#!/usr/bin/env python3
"""One explicitly granted Room Inventory recovery run. No retries or global cleanup.

This command performs native work only with --execute and a separately approved,
SHA-bound grant. Source preparation/tests must not create an executable grant.
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

GIB, MIB = 2**30, 2**20
OUTER_SECONDS, CLEANUP_SECONDS = 1800, 60
PHASE_SECONDS = {"preflight": 120, "build": 720, "device": 180, "test": 480, "collect": 240}
ADMISSION_BYTES, ABORT_BYTES = 24 * GIB, 8 * GIB
DEVICE_CAP, DERIVED_CAP, OUTPUT_CAP = 8 * GIB, 4 * GIB, GIB
XCRESULT_CAP, ATTACHMENT_CAP, LOG_CAP = 192 * MIB, 128 * MIB, 64 * MIB
CASE = "RoomInventoryUITests/InventoryRecoveryJourneyTests/testPhotosOCRExportRestoreIntoFreshNamespace"
BUNDLE, RUNNER_BUNDLE = "com.alvit.roominventory", "com.alvit.roominventory.uitests.xctrunner"
FIXTURE_SHA = "3be0a311997c35182f58e2658f64afe06b437665dfb420f1dc595e23e24ea181"


class RunFailure(Exception):
    exit_code = 1


class ConfigurationFailure(RunFailure):
    exit_code = 2


class DeadlineFailure(RunFailure):
    exit_code = 124


class _DeviceScanDeferred(BaseException):
    """Private per-command handoff, never evidence of a completed resource scan."""


class ResourceAccountingFailure(RunFailure):
    """An allocated disk budget cannot be established from this filesystem stat."""


# Diagnostic labels are closed; never derive them from commands or exception text.
ORIGIN_SOURCES = {str(Path(__file__).with_name(name)): name for name in (
    "run-recovery-journey.py", "recovery_hosted.py", "recovery_collector.py", "recovery_retention.py")}
ORIGIN_FILENAME_LIMIT = max(map(len, ORIGIN_SOURCES))
ORIGIN_STAGES = frozenset((
    "unstarted", "prepare", "build", "prepare_device", "test_collect", "phase",
    "precommand", "command_setup", "command_spawn", "command_loop", "command_wait",
    "command_cleanup", "selector_cleanup", "stream_cleanup", "group_cleanup",
    "command_receipt", "command_return", "command_accounting", "cleanup", "device_initial_state",
    "device_shutdown", "device_final_state", "final_group_cleanup", "final_receipt"))
ORIGIN_SITES = frozenset(("command", "command_cleanup", "operation", "device_cleanup", "cleanup", "finalization"))
SCAN_CATEGORIES = frozenset(("output", "derived_data", "device", "original_xcresult",
                             "verified_xcresult", "attachments", "logs"))


def exception_origin(error, site, stage):
    """Bounded metadata only: no traceback formatting, source reads or values.

    Visit at most 32 nodes and retain at most eight frames. If the innermost
    frame was not reached or mapped, do not claim a known origin. Stage is the
    last reached checkpoint; a finally block may have advanced it after a throw.
    """
    reason = ("deadline" if isinstance(error, DeadlineFailure) else
              "configuration" if isinstance(error, ConfigurationFailure) else
              "run_failure" if isinstance(error, RunFailure) else
              "os_error" if isinstance(error, OSError) else
              "interruption" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "exception")
    frames, visited, unmapped = [], 0, False
    node = BaseException.__traceback__.__get__(error)
    while node is not None and visited < 32:
        # A fixed filename allowlist excludes absolute paths and external names.
        filename = node.tb_frame.f_code.co_filename
        source = ORIGIN_SOURCES.get(filename, "external") if len(filename) <= ORIGIN_FILENAME_LIMIT else "external"
        line = node.tb_lineno if source != "external" and 0 < node.tb_lineno <= 9999999 else 0
        unmapped = unmapped or source == "external" or line == 0
        frames.append({"source": source, "line": line})
        if len(frames) > 8:
            del frames[0]
        visited += 1
        node = node.tb_next
    return {
        "reason": reason,
        "capture_site": site if type(site) is str and len(site) <= 32 and site in ORIGIN_SITES else "unknown",
        "last_stage": stage if type(stage) is str and len(stage) <= 32 and stage in ORIGIN_STAGES else "unknown",
        "frames": frames, "frames_truncated": visited > 8 or node is not None,
        "tail_unvisited": node is not None, "traceback_unavailable": visited == 0,
        "unmapped_frames": unmapped,
        "origin_known": bool(frames and node is None and frames[-1]["line"] > 0),
    }


def require(condition, message, kind=RunFailure):
    if not condition:
        raise kind(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def write_json(path, value):
    """Atomic replace is only used in a newly created, attempt-owned directory."""
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def canonical_uuid(value):
    require(isinstance(value, str), "Expected UUID string", ConfigurationFailure)
    try:
        parsed = str(uuid.UUID(value)).upper()
    except ValueError as error:
        raise ConfigurationFailure("Invalid UUID") from error
    require(value == parsed, "UUID must use canonical uppercase spelling", ConfigurationFailure)
    return value


def validate_grant(grant, *, now, script_root):
    required = {"schema_version", "native_execution_authorized", "not_before", "expires_at", "source_commit",
                "source_tree", "controller_sha256", "collector_sha256", "worktree", "output_root",
                "device_type", "runtime", "xcodegen_path", "xcodegen_sha256", "developer_dir", "journey_run_id"}
    require(type(grant) is dict and set(grant) == required, "Unexpected grant fields", ConfigurationFailure)
    require(type(grant["schema_version"]) is int and grant["schema_version"] == 1
            and grant["native_execution_authorized"] is True, "No native slot grant", ConfigurationFailure)
    for key in ("source_commit", "source_tree"):
        require(isinstance(grant[key], str) and re.fullmatch(r"[0-9a-f]{40}", grant[key]), "Invalid source pin", ConfigurationFailure)
    for key in ("controller_sha256", "collector_sha256", "xcodegen_sha256"):
        require(isinstance(grant[key], str) and re.fullmatch(r"[0-9a-f]{64}", grant[key]), "Invalid tool pin", ConfigurationFailure)
    for key in ("worktree", "output_root", "xcodegen_path", "developer_dir"):
        require(isinstance(grant[key], str) and Path(grant[key]).is_absolute(), "Grant paths must be absolute", ConfigurationFailure)
    require(Path(grant["worktree"]).resolve() == script_root.resolve(), "Controller must run from granted checkout", ConfigurationFailure)
    require(re.fullmatch(r"com\.apple\.CoreSimulator\.SimDeviceType\.iPhone-[A-Za-z0-9-]+", grant["device_type"] or ""), "Only an explicit iPhone device type is supported", ConfigurationFailure)
    require(re.fullmatch(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-[0-9-]+", grant["runtime"] or ""), "Explicit installed iOS runtime required", ConfigurationFailure)
    canonical_uuid(grant["journey_run_id"])
    try:
        start, end = [dt.datetime.fromisoformat(grant[key].replace("Z", "+00:00")) for key in ("not_before", "expires_at")]
        require(start.tzinfo is not None and end.tzinfo is not None, "Grant times must have timezones", ConfigurationFailure)
        require(start <= now and (end - now).total_seconds() >= OUTER_SECONDS, "Grant inactive or less than 1800 seconds remain", ConfigurationFailure)
    except (ValueError, TypeError, AttributeError) as error:
        raise ConfigurationFailure("Invalid grant times") from error
    return grant


def owned_directory_identity(root):
    """Sample a required owned directory identity without following its final link.

    Path ancestry and concurrent changes between checks are not made atomic.
    This is a checkpoint identity guard, not a descriptor-anchored traversal.
    """
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode), "Owned resource root is not an ordinary directory",
            ResourceAccountingFailure)
    require(type(info.st_dev) is int and type(info.st_ino) is int
            and info.st_dev >= 0 and info.st_ino >= 0,
            "Owned resource root identity unavailable", ResourceAccountingFailure)
    return info.st_dev, info.st_ino


def tree_size(root, cap, tick, *, max_entries=100000, excluded=(), on_cap=None,
              cap_metric="max_logical_allocated", vanished_child_check=None):
    """Bounded lstat traversal. Do not follow symlinks or require native size probes."""
    require(cap_metric in ("max_logical_allocated", "allocated"), "Unknown resource cap metric")
    if vanished_child_check is not None:
        tick()
        vanished_child_check()
        tick()
    if not root.exists() and not root.is_symlink():
        require(vanished_child_check is None, "Required resource root disappeared", ResourceAccountingFailure)
        return {"logical_bytes": 0, "allocated_bytes": 0, "entries": 0, "cap_metric": cap_metric}
    require(root.is_dir() and not root.is_symlink(), "Resource root is not an ordinary directory")
    pending, logical, allocated, entries = [root], 0, 0, 0
    attempted_entries, vanished_entries, vanished_directories = 0, 0, 0
    excluded = set(excluded)

    def allocation_bytes(info):
        blocks = getattr(info, "st_blocks", None)
        require(type(blocks) is int and blocks >= 0,
                "Allocated resource accounting unavailable: " + str(root), ResourceAccountingFailure)
        # A valid zero is meaningful for sparse files. st_size is not
        # an upper bound on allocation, so unknown blocks fail closed.
        return blocks * 512

    def check_cap(path, info):
        budget_bytes = allocated if cap_metric == "allocated" else max(logical, allocated)
        if budget_bytes >= cap:
            primary = RunFailure("Owned resource byte cap reached: " + str(root))
            try:
                if on_cap is not None:
                    on_cap(root, cap, logical, allocated, entries, path, info)
            except BaseException:
                # Diagnostics, including interruption while formatting,
                # must not replace this failure or prevent group cleanup.
                pass
            raise primary

    if cap_metric == "allocated":
        tick()
        root_info = root.lstat()
        require(stat.S_ISDIR(root_info.st_mode), "Resource root is not an ordinary directory")
        allocated = allocation_bytes(root_info)
        # The root can consume blocks even with no children. Keep entries as
        # the count of visited children; a root-only crossing has path '.'.
        check_cap(root, root_info)
    while pending:
        tick()
        directory = pending.pop()
        try:
            iterator = os.scandir(directory)
        except FileNotFoundError as error:
            if (vanished_child_check is None or error.errno != errno.ENOENT
                    or directory == root or not directory.is_relative_to(root)):
                raise
            # A previously charged owned directory can disappear while queued.
            # Only the scandir open is eligible; iteration/context errors stay strict.
            tick()  # Do not query identity after a late open return.
            vanished_child_check()
            tick()
            vanished_directories += 1
            continue  # Retain the directory's already observed allocated bytes.
        with iterator as children:
            for entry in children:
                tick()
                path = Path(entry.path)
                if path in excluded:
                    continue
                if vanished_child_check is not None:
                    # Bound encountered work even if every observed child vanishes.
                    attempted_entries += 1
                    require(attempted_entries <= max_entries, "Resource entry-count cap exceeded")
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError as error:
                    if vanished_child_check is None or error.errno != errno.ENOENT:
                        raise
                    # Only this child-stat syscall is eligible here. Root, callback,
                    # iterator/context, metadata and cap failures stay strict.
                    tick()  # A late stat return cannot start another filesystem query.
                    vanished_child_check()
                    tick()
                    vanished_entries += 1
                    continue
                entries += 1
                require(entries <= max_entries, "Resource entry-count cap exceeded")
                # Native products/device roots may contain links; account for the
                # link itself, never traverse its target or any external tree.
                # Count each hardlink observation conservatively; do not cache
                # inode sizes or discard growth at a later entry or sample.
                allocated += allocation_bytes(info)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                else:
                    logical += info.st_size
                check_cap(path, info)
    result = {"logical_bytes": logical, "allocated_bytes": allocated, "entries": entries,
              "cap_metric": cap_metric}
    if vanished_child_check is not None:
        tick()  # Iterator closure is a returning boundary under the same deadline.
        vanished_child_check()
        tick()
        result.update(attempted_entries=attempted_entries, vanished_entries=vanished_entries,
                      vanished_directories=vanished_directories)
    return result


# This is the bounded owned-group cleanup used by the reviewed Room smoke runner.
# Keep terminal absence and observation errors sticky across subsequent attempts.
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

    def observe():
        if clock() >= end:
            report["budget_exhausted"] = True
            return False
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
        if clock() >= end or state["group_state"] == "absent":
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


def configure_xctestrun(value, ids):
    """Retain generated paths/environment, select one UI target and one case."""
    def reject_storekit(node):
        if isinstance(node, dict):
            for key, child in node.items():
                require("storekit" not in key.lower(), "Unexpected StoreKit configuration", ConfigurationFailure)
                reject_storekit(child)
        elif isinstance(node, list):
            for child in node:
                reject_storekit(child)
        elif isinstance(node, str):
            require(".storekit" not in node.lower(), "Unexpected StoreKit configuration path", ConfigurationFailure)
    reject_storekit(value)
    require(type(value) is dict and value.get("__xctestrun_metadata__", {}).get("FormatVersion") == 2,
            "Only generated xctestrun format 2 is supported", ConfigurationFailure)
    configs = value.get("TestConfigurations")
    require(isinstance(configs, list) and len(configs) == 1, "Exactly one generated test configuration required", ConfigurationFailure)
    targets = configs[0].get("TestTargets", [])
    selected = [item for item in targets if item.get("BlueprintName") == "RoomInventoryUITests"]
    require(len(selected) == 1, "Generated UI target missing or ambiguous", ConfigurationFailure)
    target = selected[0]
    require(target.get("IsUITestBundle") is True
            and target.get("TestHostBundleIdentifier") == RUNNER_BUNDLE
            and target.get("TestHostPath") == "__TESTROOT__/Debug-iphonesimulator/RoomInventoryUITests-Runner.app"
            and target.get("UITargetAppPath") == "__TESTROOT__/Debug-iphonesimulator/RoomInventory.app"
            and target.get("TestBundlePath") == "__TESTHOST__/PlugIns/RoomInventoryUITests.xctest",
            "Unexpected UI application or runner target", ConfigurationFailure)
    # xcodebuild.xctestrun(5): preinstalled destination artifacts prevent an
    # implicit reinstall from invalidating the pinned container identities.
    target["UseDestinationArtifacts"] = True
    target["TestBundleDestinationRelativePath"] = target.pop("TestBundlePath")
    target.pop("TestHostPath")
    target.pop("UITargetAppPath")
    target["UITargetAppBundleIdentifier"] = BUNDLE
    env = target.setdefault("EnvironmentVariables", {})
    require(isinstance(env, dict), "Malformed test environment", ConfigurationFailure)
    for key in list(env):
        require(not key.startswith(("RECOVERY_", "UITEST_", "RUN_INVENTORY_")), "Unexpected preexisting test override", ConfigurationFailure)
    app_env = target.get("UITargetAppEnvironmentVariables", {})
    require(isinstance(app_env, dict) and not any(key.startswith(("RECOVERY_", "UITEST_", "RUN_INVENTORY_")) for key in app_env), "Unexpected app test override", ConfigurationFailure)
    env.update({"RUN_INVENTORY_RECOVERY_JOURNEY": "1", "RECOVERY_JOURNEY_RUN_ID": ids["journey_run_id"],
                "RECOVERY_SOURCE_RUN_ID": ids["source_run_id"], "RECOVERY_TARGET_RUN_ID": ids["target_run_id"]})
    target["OnlyTestIdentifiers"] = [CASE.split("/", 1)[1]]
    target["SkipTestIdentifiers"] = []
    target["ParallelizationEnabled"] = False
    target["TestLanguage"] = "en"
    target["TestRegion"] = "US"
    target["SystemAttachmentLifetime"] = "keepAlways"
    target["UserAttachmentLifetime"] = "keepAlways"
    configs[0]["TestTargets"] = selected
    return value


class RecoveryRun:
    def __init__(self, grant, *, clock=time.monotonic, disk_usage=shutil.disk_usage):
        self.grant = grant
        self.clock, self.disk_usage = clock, disk_usage
        self.start = clock()
        self.outer_end = self.start + OUTER_SECONDS
        self.work_end = self.outer_end - CLEANUP_SECONDS
        self.phase_end = min(self.start + PHASE_SECONDS["preflight"], self.work_end)
        self.command_deadline = None
        self.timer_enabled = False
        self.repo = Path(grant["worktree"])
        self.output = Path(grant["output_root"])
        self.derived = self.output / "DerivedData"
        self.device_root = None
        self._owned_device_identity = None
        self._owned_derived_identity = None
        self.device_base = Path.home() / "Library/Developer/CoreSimulator/Devices"
        self.owns_output = False
        self.device_id = None
        self.collector = None
        self.groups = []
        self.last_resource_check = float("-inf")
        self.last_samples = []
        self.resource_cap_observed = False
        self.cleanup_mode = False
        self._derived_scan_service = None
        self._device_scan_service = None
        self._device_scan_context = None
        self.diagnostic_stage = "unstarted"
        self.ids = {"journey_run_id": grant["journey_run_id"], "source_run_id": str(uuid.uuid4()).upper(), "target_run_id": str(uuid.uuid4()).upper()}
        require(len(set(self.ids.values())) == 3, "UUID collision", ConfigurationFailure)
        self.record = {"started_at": utc_now().isoformat(), "ids": self.ids, "commands": [], "primary_error": None,
                       "cleanup_errors": [], "native_started": False, "build_count": 0, "test_count": 0}
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith(("DYLD_", "SIMCTL_", "TEST_RUNNER_", "RECOVERY_", "UITEST_", "RUN_INVENTORY_"))}
        self.environment["DEVELOPER_DIR"] = grant["developer_dir"]
        self.environment["NSUnbufferedIO"] = "YES"

    def record_exception_origin(self, target, error, site):
        # Best effort only after an error is already recorded. A secondary
        # diagnostic failure must not replace that error or skip owned cleanup.
        try:
            target["exception_origin"] = exception_origin(error, site, self.diagnostic_stage)
            if site in ("command", "operation"):
                self.observe_runtime("scan_snapshot", target, preserve_primary=True)
        except BaseException:
            pass

    def diagnostic_elapsed(self, *, sampled=None):
        """Optional monotonic observation, not a deadline or actual child exit."""
        try:
            now = self.clock() if sampled is None else sampled
            if type(now) not in (int, float) or type(self.start) not in (int, float):
                return None
            value = now - self.start
            if 0 <= value <= 86400 and math.isfinite(value):
                return round(value, 6)
        except DeadlineFailure:
            raise
        except Exception:
            pass
        return None

    def observe_runtime(self, event, target=None, value=None, *, failed=False, preserve_primary=False):
        """Fixed-size optional state; pass through existing poll/selector values.

        No filesystem/process query or write occurs here. On the ordinary path
        control interruptions still reach the existing command/error handlers.
        Once a primary error exists, optional diagnostics cannot replace it.
        """
        try:
            if event == "scan_start":
                category = value if type(value) is str and len(value) <= 32 and value in SCAN_CATEGORIES else "unknown"
                previous = self.record.get("resource_scan", {}).get("last")
                value = {"category": category, "state": "started", "start_elapsed": None,
                         "end_elapsed": None, "duration_seconds": None}
                self.record["resource_scan"] = {"current": value, "last": previous}
                value["start_elapsed"] = self.diagnostic_elapsed()
            elif event == "scan_end" and type(value) is dict:
                # A known tree_size return/failure is distinct from a measured
                # finish: the optional end clock can still be unavailable.
                value["state"] = "failed" if failed else "returned"
                value["end_elapsed"] = self.diagnostic_elapsed()
                start, end = value["start_elapsed"], value["end_elapsed"]
                if start is not None and end is not None and end >= start:
                    value["duration_seconds"] = round(end - start, 6)
                self.record["resource_scan"] = {"current": None, "last": value}
            elif event == "scan_snapshot":
                scans = self.record.get("resource_scan")
                if scans is not None:
                    snapshot = {key: None if scans[key] is None else dict(scans[key]) for key in ("current", "last")}
                    if target is self.record:
                        target["failure_resource_scan"] = snapshot
                    else:
                        target.setdefault("process_observation", {})["resource_scan_at_failure"] = snapshot
            elif event == "selector":
                target.setdefault("process_observation", {})["selector_state"] = "nonempty" if value else "empty"
            elif event in ("stdout_eof", "stderr_eof"):
                pipe = {"observed": True, "elapsed": None}
                target.setdefault("process_observation", {})[event] = pipe
                pipe["elapsed"] = self.diagnostic_elapsed()
            elif event in ("poll", "wait", "cleanup_return", "final_cleanup_return") and type(value) is int and -255 <= value <= 255:
                observation = target.setdefault("process_observation", {})
                if "first_observed_exit" not in observation:
                    first = {"source": event, "returncode": value, "elapsed": None}
                    observation["first_observed_exit"] = first
                    first["elapsed"] = self.diagnostic_elapsed()
        except BaseException as error:
            try:
                if target is not None and event in ("selector", "stdout_eof", "stderr_eof", "poll", "wait", "cleanup_return", "final_cleanup_return"):
                    target.setdefault("process_observation", {})["capture_incomplete"] = True
            except BaseException as secondary:
                if (not preserve_primary and not isinstance(error, (DeadlineFailure, KeyboardInterrupt, SystemExit))
                        and isinstance(secondary, (DeadlineFailure, KeyboardInterrupt, SystemExit))):
                    raise
            if not preserve_primary and isinstance(error, (DeadlineFailure, KeyboardInterrupt, SystemExit)):
                raise
        return value

    def observe_derived_service(self, target, event, *, index=None, value=None, preserve_primary=False):
        """Fixed aggregates of returned service work; no clock or I/O queries.

        Missing/incomplete observations are not proof of no work. Only supplied
        completion clock values are sampled; counters never drive supervision.
        """
        try:
            observation = target.get("derived_service")
            if observation is None:
                observation = {
                    "quanta_started": 0, "quanta_completed": 0, "polls_returned": 0,
                    "stdout": {"read_returns": 0, "read_bytes": 0, "eof_returns": 0, "would_block": 0},
                    "stderr": {"read_returns": 0, "read_bytes": 0, "eof_returns": 0, "would_block": 0},
                    "first_completed_checkpoint_elapsed": None, "last_completed_checkpoint_elapsed": None,
                    "terminal_barrier": {"reached": False, "completed": False},
                    "capture_incomplete": False, "saturated": False,
                }
                target["derived_service"] = observation

            def increment(fields, key, amount=1):
                limit = 2**31 - 1
                current = fields[key]
                require(type(current) is int and 0 <= current <= limit
                        and type(amount) is int and amount >= 0, "Invalid service counter")
                if amount > limit - current:
                    fields[key] = limit
                    observation["saturated"] = observation["capture_incomplete"] = True
                else:
                    fields[key] = current + amount

            if event == "quantum_started":
                increment(observation, "quanta_started")
            elif event == "quantum_completed":
                elapsed = None
                if type(value) in (int, float) and type(self.start) in (int, float):
                    try:
                        delta = value - self.start
                        if math.isfinite(delta) and 0 <= delta <= 86400:
                            elapsed = round(delta, 6)
                    except (OverflowError, ValueError):
                        pass
                previous = observation["last_completed_checkpoint_elapsed"]
                first = observation["first_completed_checkpoint_elapsed"]
                if elapsed is not None and any(point is not None and elapsed < point for point in (first, previous)):
                    elapsed = None
                if elapsed is None:
                    observation["capture_incomplete"] = True
                if observation["quanta_completed"] == 0:
                    observation["first_completed_checkpoint_elapsed"] = elapsed
                observation["last_completed_checkpoint_elapsed"] = elapsed
                increment(observation, "quanta_completed")
            elif event in ("read_return", "would_block"):
                require(type(index) is int and index in (0, 1), "Invalid service pipe")
                pipe = observation["stdout" if index == 0 else "stderr"]
                if event == "would_block":
                    increment(pipe, "would_block")
                else:
                    increment(pipe, "read_returns")
                    increment(pipe, "read_bytes", value)
                    if value == 0:
                        increment(pipe, "eof_returns")
            elif event == "poll_return":
                increment(observation, "polls_returned")
            elif event in ("barrier_reached", "barrier_completed"):
                observation["terminal_barrier"]["reached" if event == "barrier_reached" else "completed"] = True
            elif event == "incomplete":
                observation["capture_incomplete"] = True
            else:
                require(event == "init", "Invalid service observation")
        except BaseException as error:
            try:
                target["derived_service"]["capture_incomplete"] = True
            except BaseException as secondary:
                if (not preserve_primary and not isinstance(error, (DeadlineFailure, KeyboardInterrupt, SystemExit))
                        and isinstance(secondary, (DeadlineFailure, KeyboardInterrupt, SystemExit))):
                    raise
            if not preserve_primary and isinstance(error, (DeadlineFailure, KeyboardInterrupt, SystemExit)):
                raise

    def arm(self, deadline):
        if self.timer_enabled:
            require(deadline > self.clock(), "Deadline expired before timer arm", DeadlineFailure)
            signal.setitimer(signal.ITIMER_REAL, max(.001, deadline - self.clock()))

    def disarm(self):
        if self.timer_enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)

    def tick(self):
        require(self.clock() < min(self.phase_end, self.outer_end, self.command_deadline or self.outer_end), "Absolute phase/outer deadline exceeded", DeadlineFailure)

    def record_resource_cap(self, category, root, cap, logical, allocated, entries, path, info,
                            *, cap_metric="max_logical_allocated"):
        if self.resource_cap_observed:
            return
        # Claim the first crossing even if its optional formatting fails. Use
        # only this traversal's data, never a retry or a second filesystem probe.
        self.resource_cap_observed = True
        numbers = (cap, logical, allocated, entries, info.st_size, info.st_blocks)
        require(all(type(value) is int and value.bit_length() <= 128 for value in numbers),
                "Resource observation integer out of bounds")
        require(type(category) is str and len(category) <= 64 and category.isascii(),
                "Resource observation category out of bounds")
        relative = path.relative_to(root)
        require(not relative.is_absolute() and ".." not in relative.parts,
                "Resource observation path is not relative")
        text = str(relative)
        escaped = text[:256].encode("unicode_escape").decode("ascii")
        entry_type = {stat.S_IFREG: "regular_file", stat.S_IFDIR: "directory",
                      stat.S_IFLNK: "symlink", stat.S_IFIFO: "fifo", stat.S_IFSOCK: "socket",
                      stat.S_IFCHR: "character_device", stat.S_IFBLK: "block_device"}.get(
                          stat.S_IFMT(info.st_mode), "unknown")
        observation = {
            "traversal": "partial", "category": category, "cap_bytes": cap,
            "cap_metric": cap_metric,
            "logical_bytes": logical, "allocated_bytes": allocated, "entries": entries,
            "current_entry": {"relative_path": escaped[:1024], "path_encoding": "unicode_escape",
                              "path_truncated": len(text) > 256 or len(escaped) > 1024,
                              "type": entry_type, "size_bytes": info.st_size,
                              "blocks_512": info.st_blocks},
        }
        # Bound the complete JSON contribution before adding it to the existing
        # receipt. This is memory-only; command cleanup still precedes its write.
        encoded = json.dumps({"resource_cap_crossing": observation}, indent=2,
                             ensure_ascii=True, allow_nan=False)
        require(len(encoded) <= 4096, "Resource observation JSON out of bounds")
        self.record["resource_cap_crossing"] = observation

    def bind_device_resource_root(self):
        # Bind once, immediately after create-device supplied the canonical UUID
        # and the new root passed the existing ordinary-directory checks.
        require(self._owned_device_identity is None, "Owned device identity already bound", ConfigurationFailure)
        require(self.device_id is not None and self.device_root == self.device_base / self.device_id,
                "Invalid owned device root binding", ConfigurationFailure)
        identity = owned_directory_identity(self.device_root)
        self._owned_device_identity = (self.device_root, self.device_id, identity)

    def validate_device_resource_root(self, root, binding):
        require(binding is not None and self._owned_device_identity is binding
                and root is binding[0] and root is self.device_root
                and self.device_id == binding[1] and root == self.device_base / self.device_id,
                "Stale owned device resource binding", ConfigurationFailure)
        require(owned_directory_identity(root) == binding[2], "Owned device root replaced",
                ResourceAccountingFailure)

    def prepare_derived_resource_root(self):
        # Create and bind this attempt's DerivedData before its only build. Never
        # adopt an existing root or rebind after an observed identity change.
        require(self._owned_derived_identity is None and self.owns_output
                and self.output == Path(self.grant["output_root"])
                and self.derived == self.output / "DerivedData",
                "Invalid owned DerivedData binding", ConfigurationFailure)
        self.tick()
        output_identity = owned_directory_identity(self.output)
        self.tick()
        self.derived.mkdir(mode=0o700)
        self.tick()
        derived_identity = owned_directory_identity(self.derived)
        self.tick()
        require(owned_directory_identity(self.output) == output_identity,
                "Owned output root replaced", ResourceAccountingFailure)
        self.tick()
        self._owned_derived_identity = (self.output, self.derived, output_identity, derived_identity)

    def validate_derived_resource_root(self, root, binding):
        require(binding is not None and self._owned_derived_identity is binding
                and self.owns_output and self.output is binding[0]
                and root is binding[1] and root is self.derived
                and self.output == Path(self.grant["output_root"])
                and root == self.output / "DerivedData",
                "Stale owned DerivedData binding", ConfigurationFailure)
        require(owned_directory_identity(self.output) == binding[2],
                "Owned output root replaced", ResourceAccountingFailure)
        self.tick()
        require(owned_directory_identity(root) == binding[3],
                "Owned DerivedData root replaced", ResourceAccountingFailure)

    def resource_size(self, category, root, cap, *, cap_metric="max_logical_allocated", **kwargs):
        span = self.observe_runtime("scan_start", value=category)
        try:
            if category == "device":
                require("vanished_child_check" not in kwargs, "Device validation cannot be overridden", ConfigurationFailure)
                owned_binding = self._owned_device_identity
                kwargs["vanished_child_check"] = lambda: self.validate_device_resource_root(root, owned_binding)
            elif category == "derived_data" and self._owned_derived_identity is not None:
                require("vanished_child_check" not in kwargs, "DerivedData validation cannot be overridden", ConfigurationFailure)
                owned_binding = self._owned_derived_identity
                kwargs["vanished_child_check"] = lambda: self.validate_derived_resource_root(root, owned_binding)
            checkpoint = (self._derived_scan_service if category == "derived_data" and root == self.derived
                          and not self.cleanup_mode and self._derived_scan_service is not None else self.tick)
            binding = self._device_scan_service if category == "device" and not self.cleanup_mode else None
            if binding is not None:
                require(root is binding[0] and root is self.device_root and self._device_scan_context is None,
                        "Invalid active device scan binding", ConfigurationFailure)
                checkpoint = binding[1]
                self._device_scan_context = binding
            try:
                result = tree_size(root, cap, checkpoint, cap_metric=cap_metric, **kwargs,
                                   on_cap=lambda *data: self.record_resource_cap(category, *data, cap_metric=cap_metric))
            finally:
                if binding is not None:
                    self._device_scan_context = None
        except _DeviceScanDeferred:
            # This is not an error primary: a control interruption during optional
            # metadata must still fail the command rather than authorize handoff.
            self.observe_runtime("scan_end", value=span, failed=True)
            raise
        except BaseException:
            try:
                self.observe_runtime("scan_end", value=span, failed=True, preserve_primary=True)
            except BaseException:
                pass
            raise
        self.observe_runtime("scan_end", value=span)
        return result

    def guard(self, force=False):
        self.tick()
        # Cleanup still enforces time but must remain possible after disk abort.
        if self.cleanup_mode:
            return
        free = min(self.disk_usage(self.output.parent).free, self.disk_usage(self.device_base).free)
        require(free >= ABORT_BYTES, "Free disk fell below 8 GiB")
        if force or self.clock() - self.last_resource_check >= 2:
            self.last_resource_check = self.clock()
            sample = {"elapsed": self.clock() - self.start, "free_bytes": free,
                      "output": self.resource_size("output", self.output, OUTPUT_CAP, excluded=(self.derived,)),
                      # DerivedData is a live disk budget, not a logical copy/input bound.
                      # Keep logical sizes visible without charging sparse reservations.
                      "derived_data": self.resource_size("derived_data", self.derived, DERIVED_CAP,
                                                         cap_metric="allocated")}
            if self.device_root:
                sample["device"] = self.resource_size("device", self.device_root, DEVICE_CAP)
            for name, root, limit in [
                ("original_xcresult", self.output / "original.xcresult", XCRESULT_CAP),
                ("verified_xcresult", self.output / "evidence/collection/xcresult/verified.xcresult", XCRESULT_CAP),
                ("attachments", self.output / "evidence/collection/xcresult/attachments", ATTACHMENT_CAP),
                ("logs", self.output / "logs", LOG_CAP),
            ]:
                sample[name] = self.resource_size(name, root, limit)
            self.last_samples.append(sample)
            require(len(self.last_samples) <= 2000, "Resource observation cap exceeded")
            write_json(self.output / "resource-samples.json", self.last_samples)

    def phase(self, name):
        self.diagnostic_stage = "phase"
        self.phase_end = min(self.clock() + PHASE_SECONDS[name], self.work_end)
        self.arm(self.phase_end - 4)
        self.tick()
        self.record["phase"] = name
        self.flush()

    def flush(self):
        write_json(self.output / "result.json", self.record)

    def command(self, args, name, *, cap=60, on_poll=None, allowed_codes=(0,)):
        """One owned process group, bounded pipe draining, sticky cleanup result."""
        self.diagnostic_stage = "precommand"
        require(self.command_deadline is None, "Nested commands are unsupported", ConfigurationFailure)
        require(self._derived_scan_service is None and self._device_scan_service is None
                and self._device_scan_context is None, "Stale scan service", ConfigurationFailure)
        self.guard()
        end = min(self.phase_end, self.clock() + cap)
        require(end - self.clock() >= 8, "Insufficient command and cleanup budget", DeadlineFailure)
        # Include log creation and the pre-spawn receipt in this command's cap.
        self.diagnostic_stage = "command_setup"
        self.arm(end - 4)
        logs = self.output / "logs"
        logs.mkdir(exist_ok=True)
        record = {"name": name, "args": [str(a) for a in args], "start_elapsed": self.clock() - self.start,
                  "end_deadline_elapsed": end - self.start, "primary_error": None, "exit_code": None,
                  "child_completed_elapsed": None, "cleanup_completed_elapsed": None,
                  "post_command_accounting": None}
        self.record["commands"].append(record)
        self.flush()
        buffers, streams = [bytearray(), bytearray()], []
        process, entry, primary = None, None, None
        selector = selectors.DefaultSelector()
        previous_deadline = self.command_deadline
        self.command_deadline = end - 4
        service_checkpoints, service_last, service_busy = 0, None, False
        device_checkpoints, device_last = 0, None
        device_root, device_id = self.device_root, self.device_id
        device_binding = (device_root, lambda: service_scan(device_scan=True))
        device_deferred = _DeviceScanDeferred()
        pipe_eof = [False, False]

        def require_device_owner(*, active_scan=True):
            # Python object/ledger identity only; never infer kernel group absence.
            require(self._device_scan_service is device_binding
                    and self._device_scan_context is (device_binding if active_scan else None)
                    and self.device_root is device_root and self.device_id == device_id
                    and device_id is not None and device_root == self.device_base / device_id
                    and bool(self.groups) and self.groups[-1] is entry
                    and entry["process"] is process and entry["record"] is record
                    and record["pid"] == record["pgid"] == process.pid
                    and not entry["state"].get("leader_reaped")
                    and not entry["state"].get("observation_errors")
                    and entry["state"].get("group_state") != "absent",
                    "Stale device scan owner", ConfigurationFailure)

        def service_derived_scan():
            service_scan()

        def service_scan(*, device_scan=False):
            """Cooperative work between returning walker checkpoints, never a worker.

            No callback/guard/flush here. A single blocked syscall still blocks
            supervision; every returning boundary checks the original deadline.
            """
            nonlocal service_checkpoints, service_last, service_busy, device_checkpoints, device_last
            self.tick()
            require(self._derived_scan_service is service_derived_scan and not service_busy,
                    "Invalid or reentrant scan service", ConfigurationFailure)
            if device_scan:
                require_device_owner()
                device_checkpoints += 1
                checkpoints, last = device_checkpoints, device_last
            else:
                service_checkpoints += 1
                checkpoints, last = service_checkpoints, service_last
            if checkpoints < 64 and self.clock() - last < .05:
                self.tick()
                return
            service_busy = True
            try:
                if not device_scan:
                    self.observe_derived_service(record, "quantum_started")
                # The outer loop checked this floor before each read batch.
                # Repeat it here without recursively entering the resource guard.
                free = self.disk_usage(self.output.parent).free
                self.tick()
                free = min(free, self.disk_usage(self.device_base).free)
                self.tick()
                require(free >= ABORT_BYTES, "Free disk fell below 8 GiB")
                ready = selector.select(0)
                self.tick()
                require(len(ready) <= 2, "Unexpected scan service readiness count")
                seen, drained = set(), False
                for key, _ in ready:
                    self.tick()
                    index = key.data
                    require(type(index) is int and index in (0, 1) and index not in seen
                            and key.fileobj is (process.stdout, process.stderr)[index],
                            "Unexpected scan service pipe identity", ConfigurationFailure)
                    seen.add(index)
                    try:
                        data = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        if not device_scan:
                            self.observe_derived_service(record, "would_block", index=index)
                        self.tick()
                        continue
                    if not device_scan:
                        self.observe_derived_service(record, "read_return", index=index, value=len(data))
                    self.tick()
                    if not data:
                        selector.unregister(key.fileobj)
                        pipe_eof[index] = True  # Only an actual empty read establishes EOF.
                        self.observe_runtime("stdout_eof" if index == 0 else "stderr_eof", record)
                        continue
                    require(len(buffers[index]) + len(data) <= 16 * MIB, "Command stream cap exceeded: " + name)
                    written = streams[index].write(data)
                    self.tick()
                    require(written == len(data), "Incomplete command log write: " + name)
                    buffers[index].extend(data)
                    drained = True
                self.tick()
                polled = process.poll()
                if not device_scan:
                    self.observe_derived_service(record, "poll_return")
                self.observe_runtime("poll", record, polled)
                self.tick()
                if drained:
                    # Validate newly persisted logs with the plain deadline tick.
                    # Preserve the active DerivedData span and cap accounting.
                    tree_size(logs, LOG_CAP, self.tick, max_entries=256,
                              on_cap=lambda *data: self.record_resource_cap("logs", *data))
                    self.tick()
                if device_scan:
                    device_checkpoints, device_last = 0, self.clock()
                else:
                    service_checkpoints, service_last = 0, self.clock()
                self.tick()
                if not device_scan:
                    self.observe_derived_service(record, "quantum_completed", value=service_last)
                elif all(pipe_eof) and polled is not None:
                    require(type(polled) is int and polled in allowed_codes, "Command failed: " + name)
                    require_device_owner()
                    self.tick()  # The allowed exit AND EOF must be observed in time.
                    raise device_deferred
            finally:
                service_busy = False

        def cleanup_error(operation, error):
            observation = {"command": name, "operation": operation,
                           "error": type(error).__name__ + ": " + str(error)}
            self.record["cleanup_errors"].append(observation)
            try:
                self.record_exception_origin(observation, error, "command_cleanup")
            except BaseException:
                pass

        try:
            if not self.cleanup_mode:
                self.observe_derived_service(record, "init")
            self.arm(end - 4)
            for suffix in ("stdout", "stderr"):
                streams.append((logs / (name + "." + suffix)).open("xb", buffering=0))
            self.guard()
            self.diagnostic_stage = "command_spawn"
            # Block only alarm delivery while registering ownership. A pending
            # deadline is delivered after the PID/group has entered our ledger.
            blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM}) if self.timer_enabled else None
            try:
                self.tick()
                process = subprocess.Popen(record["args"], cwd=self.repo, env=self.environment, start_new_session=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
                entry = {"process": process, "state": {}, "record": record}
                self.groups.append(entry)
                record["pid"] = record["pgid"] = process.pid
            finally:
                if blocked is not None:
                    signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
            for index, pipe in enumerate((process.stdout, process.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, index)
            service_last = self.clock()
            device_last = service_last
            if not self.cleanup_mode:
                self._derived_scan_service = service_derived_scan
                if device_root is not None:
                    self._device_scan_service = device_binding
            self.diagnostic_stage = "command_loop"
            # Preserve the original short circuit and consume map truth once.
            # This outer condition alone adds no poll for a nonempty selector.
            while (self.observe_runtime("selector", record, bool(selector.get_map())) or
                   self.observe_runtime("poll", record, process.poll()) is None):
                device_handoff = False
                try:
                    self.guard()
                except _DeviceScanDeferred as deferred:
                    # Only this command's sentinel may cross the walker boundary.
                    # A scandir close/stat/cap exception replaces it and fails normally.
                    require(deferred is device_deferred and self._device_scan_service is device_binding
                            and self._device_scan_context is None,
                            "Invalid device scan handoff", ConfigurationFailure)
                    self.tick()  # Context-manager unwinding consumed the same budget.
                    record["device_scan_handoff"] = {
                        "state": "incomplete", "reason": "allowed_exit_and_both_pipe_eof"}
                    device_handoff = True
                self.tick()
                if on_poll:
                    on_poll()
                self.tick()
                if device_handoff:
                    # Preserve the normal callback boundary outside the walker.
                    require_device_owner(active_scan=False)
                    self.tick()
                    break
                for key, _ in selector.select(timeout=min(.1, max(0, end - 4 - self.clock()))):
                    self.tick()
                    try:
                        data = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not data:
                        require(type(key.data) is int and key.data in (0, 1)
                                and key.fileobj is (process.stdout, process.stderr)[key.data],
                                "Unexpected command pipe identity", ConfigurationFailure)
                        selector.unregister(key.fileobj)
                        pipe_eof[key.data] = True
                        self.observe_runtime("stdout_eof" if key.data == 0 else "stderr_eof", record)
                        continue
                    index = key.data
                    require(len(buffers[index]) + len(data) <= 16 * MIB, "Command stream cap exceeded: " + name)
                    require(streams[index].write(data) == len(data), "Incomplete command log write: " + name)
                    buffers[index].extend(data)
                self.resource_size("logs", logs, LOG_CAP, max_entries=256)
            self.diagnostic_stage = "command_wait"
            record["exit_code"] = self.observe_runtime("wait", record, process.wait(timeout=0))
            require(record["exit_code"] in allowed_codes, "Command failed: " + name)
            # Preserve the child-work deadline check before any cleanup or
            # transition to phase-bounded post-command accounting.
            self._derived_scan_service = None
            self._device_scan_service = None
            self._device_scan_context = None
            if self.cleanup_mode:
                self.guard(force=True)  # Existing time-only cleanup-mode guard.
            self.tick()
            if not self.cleanup_mode:
                record["child_completed_elapsed"] = self.diagnostic_elapsed()
                self.tick()
        except BaseException as error:
            primary = error
            record["primary_error"] = {"type": type(error).__name__, "message": str(error)}
            try:
                if not self.cleanup_mode:
                    self.observe_derived_service(record, "incomplete", preserve_primary=True)
            except BaseException:
                pass
            try:
                self.record_exception_origin(record, error, "command")
            except BaseException:
                pass
        finally:
            self._derived_scan_service = None
            self._device_scan_service = None
            self._device_scan_context = None
            self.diagnostic_stage = "command_cleanup"
            self.disarm()
            self.command_deadline = previous_deadline
            try:
                self.diagnostic_stage = "selector_cleanup"
                require(self.clock() < end, "Selector cleanup deadline expired", DeadlineFailure)
                self.arm(end)
                selector.close()
            except BaseException as error:
                cleanup_error("selector_close", error)
            for stream in streams + ([process.stdout, process.stderr] if process else []):
                try:
                    self.diagnostic_stage = "stream_cleanup"
                    require(self.clock() < end, "Stream cleanup deadline expired", DeadlineFailure)
                    self.arm(end)
                    stream.close()
                except BaseException as error:
                    cleanup_error("stream_close", error)
            if process:
                try:
                    self.diagnostic_stage = "group_cleanup"
                    if self.clock() < end:
                        self.arm(end)
                    cleanup = kill_owned(process, end, state=entry["state"], clock=self.clock)
                    record["cleanup"] = cleanup
                    record["exit_code"] = entry["state"].get("returncode")
                    if not cleanup["success"]:
                        cleanup_error("owned_group", RunFailure(str(cleanup)))
                    try:
                        self.observe_runtime("cleanup_return", record, record["exit_code"],
                                             preserve_primary=primary is not None or not cleanup["success"])
                    except BaseException:
                        if primary is None and cleanup["success"]:
                            raise
                except BaseException as error:
                    cleanup_error("owned_group_exception", error)
            self.disarm()
            cleanup_completed = self.clock()
            record["elapsed_seconds"] = cleanup_completed - self.start - record["start_elapsed"]
            record["stdout_sha256"], record["stderr_sha256"] = [sha(bytes(value)) for value in buffers]
            if (not self.cleanup_mode and primary is None and process is not None
                    and record.get("cleanup", {}).get("success")
                    and not any(e.get("command") == name for e in self.record["cleanup_errors"])):
                try:
                    # Even a successful report cannot authorize late cleanup,
                    # unknown descendants or failed selector/stream closure.
                    require(cleanup_completed < end, "Owned cleanup returned after command deadline", DeadlineFailure)
                    require(record["cleanup"].get("group_state") == "absent"
                            and record["cleanup"].get("leader_reaped") is True
                            and not record["cleanup"].get("errors")
                            and not record["cleanup"].get("budget_exhausted")
                            and not entry["state"].get("observation_errors"), "Owned cleanup not confirmed")
                    record["cleanup_completed_elapsed"] = self.diagnostic_elapsed(sampled=cleanup_completed)
                    self.diagnostic_stage = "command_accounting"
                    accounting_end = min(self.phase_end, self.work_end, self.outer_end)
                    self.command_deadline = accounting_end
                    self.arm(accounting_end)
                    accounting_started = self.clock()
                    record["post_command_accounting"] = {
                        "start_elapsed": self.diagnostic_elapsed(sampled=accounting_started),
                        "deadline_elapsed": self.diagnostic_elapsed(sampled=accounting_end),
                        "end_elapsed": None, "status": "STARTED"}
                    self.observe_derived_service(record, "barrier_reached")
                    # Group absence does not make simulator/DerivedData roots
                    # quiescent. Always complete a fresh, uncached full guard.
                    self.guard(force=True)
                    self.tick()
                    self.observe_derived_service(record, "barrier_completed")
                    record["post_command_accounting"]["end_elapsed"] = self.diagnostic_elapsed()
                    self.tick()
                    record["post_command_accounting"]["status"] = "COMPLETED"
                except BaseException as error:
                    primary = error
                    record["primary_error"] = {"type": type(error).__name__, "message": str(error)}
                    try:
                        if record["post_command_accounting"] is not None:
                            record["post_command_accounting"]["status"] = "FAILED"
                            record["post_command_accounting"]["end_elapsed"] = self.diagnostic_elapsed()
                    except BaseException:
                        pass
                    try:
                        self.observe_derived_service(record, "incomplete", preserve_primary=True)
                    except BaseException:
                        pass
                    try:
                        self.record_exception_origin(record, error, "command")
                    except BaseException:
                        pass
                finally:
                    self.command_deadline = previous_deadline
            try:
                self.diagnostic_stage = "command_receipt"
                receipt_end = min(self.phase_end, self.outer_end)
                receipt_started = self.clock()
                record["elapsed_seconds"] = receipt_started - self.start - record["start_elapsed"]
                require(receipt_started < receipt_end, "Command receipt deadline expired", DeadlineFailure)
                self.arm(receipt_end)
                self.flush()
                self.tick()
            except BaseException as error:
                cleanup_error("command_receipt", error)
                if primary is None:
                    primary = error
        self.diagnostic_stage = "command_return"
        if primary:
            raise primary
        require(record.get("cleanup", {}).get("success"), "Owned process cleanup uncertain: " + name)
        require(not any(e.get("command") == name for e in self.record["cleanup_errors"]),
                "Command cleanup or receipt failed: " + name)
        return bytes(buffers[0])

    def pin_sources(self, suffix=""):
        head = self.command(["git", "rev-parse", "HEAD", "HEAD^{tree}"], "source-head" + suffix).decode().splitlines()
        require(head == [self.grant["source_commit"], self.grant["source_tree"]], "Source commit/tree changed", ConfigurationFailure)
        require(self.command(["git", "status", "--porcelain=v1"], "source-status" + suffix) == b"", "Source checkout must be clean", ConfigurationFailure)
        tree = self.command(["git", "ls-tree", "-r", "HEAD"], "source-tree" + suffix)
        self.tree_sha = sha(tree)
        for name, pin in [("run-recovery-journey.py", "controller_sha256"), ("recovery_collector.py", "collector_sha256")]:
            require(sha((self.repo / "scripts" / name).read_bytes()) == self.grant[pin], "Executable source pin changed", ConfigurationFailure)
        require(sha(Path(self.grant["xcodegen_path"]).read_bytes()) == self.grant["xcodegen_sha256"], "XcodeGen pin changed", ConfigurationFailure)
        require(sha((self.repo / "UITests/Fixtures/SyntheticRecoveryReceipt.png").read_bytes()) == FIXTURE_SHA, "Fixture pin changed", ConfigurationFailure)
        write_json(self.output / "source-pin.json", {"commit": head[0], "tree": head[1], "tree_listing_sha256": self.tree_sha, "grant": self.grant})

    def app_container(self, bundle, name):
        raw = self.command(["xcrun", "simctl", "get_app_container", self.device_id, bundle, "data"], name).decode().strip()
        path = Path(raw)
        require(path.is_absolute() and path.resolve().is_relative_to(self.device_root.resolve()) and path.is_dir(), "Container outside owned device")
        return path

    def prepare(self):
        require(not self.output.exists() and not self.output.is_symlink(), "Output path must not exist", ConfigurationFailure)
        require(self.output.parent.is_dir() and not self.output.parent.is_symlink(), "Output parent must exist and be ordinary", ConfigurationFailure)
        require(not self.output.resolve().is_relative_to(self.repo.resolve()), "Output must be outside source checkout", ConfigurationFailure)
        require(self.device_base.is_dir(), "Simulator devices base missing", ConfigurationFailure)
        require(min(self.disk_usage(self.output.parent).free, self.disk_usage(self.device_base).free) >= ADMISSION_BYTES, "Admission requires 24 GiB free; no native work started", ConfigurationFailure)
        self.output.mkdir(mode=0o700)
        self.owns_output = True
        self.flush()
        self.pin_sources()
        self.record["native_started"] = True
        self.command([self.grant["xcodegen_path"], "generate", "--spec", "project.yml"], "generate-project", cap=60)
        self.flush()
        devices = json.loads(self.command(["xcrun", "simctl", "list", "devices", "--json"], "devices-before"))
        self.device_name = "Room Recovery " + self.ids["journey_run_id"]
        require(not any(d.get("name") == self.device_name for values in devices["devices"].values() for d in values), "Owned simulator name already exists", ConfigurationFailure)
        self.record["device_creation_attempted"] = True
        self.flush()
        raw = self.command(["xcrun", "simctl", "create", self.device_name, self.grant["device_type"], self.grant["runtime"]], "create-device", cap=60).decode().strip()
        self.device_id = canonical_uuid(raw)
        self.device_root = self.device_base / self.device_id
        require(self.device_root.is_dir() and not self.device_root.is_symlink(), "New device root missing")
        self.bind_device_resource_root()
        self.record["device_id"] = self.device_id
        self.record["device_path"] = str(self.device_root)
        self.flush()

    def build(self):
        self.phase("build")
        self.prepare_derived_resource_root()
        self.record["build_count"] += 1
        self.command(["xcodebuild", "build-for-testing", "-project", "RoomInventory.xcodeproj", "-scheme", "RoomInventory",
                      "-configuration", "Debug", "-destination", "platform=iOS Simulator,id=" + self.device_id,
                      "-derivedDataPath", self.derived, "-only-testing:" + CASE,
                      "CODE_SIGNING_ALLOWED=NO"], "build", cap=PHASE_SECONDS["build"])
        products = self.derived / "Build/Products"
        candidates = list(products.glob("*.xctestrun"))
        require(len(candidates) == 1, "Generated xctestrun missing or ambiguous")
        original = candidates[0]
        raw = original.read_bytes()
        require(len(raw) <= MIB, "xctestrun too large")
        value = configure_xctestrun(plistlib.loads(raw), self.ids)
        self.xctestrun = original.with_name("Recovery-" + self.ids["journey_run_id"] + ".xctestrun")
        require(not self.xctestrun.exists(), "Owned test configuration already exists")
        self.xctestrun.write_bytes(plistlib.dumps(value))
        self.xctestrun_sha = sha(self.xctestrun.read_bytes())
        (self.output / "generated.xctestrun.plist").write_bytes(raw)
        (self.output / "selected.xctestrun.plist").write_bytes(self.xctestrun.read_bytes())
        self.app = products / "Debug-iphonesimulator/RoomInventory.app"
        self.runner = products / "Debug-iphonesimulator/RoomInventoryUITests-Runner.app"
        require(self.app.is_dir() and self.runner.is_dir(), "Built app or UI runner missing")
        for product, bundle in [(self.app, BUNDLE), (self.runner, RUNNER_BUNDLE)]:
            info_path = product / "Info.plist"
            require(info_path.stat().st_size < MIB, "Unexpected product plist size")
            require(plistlib.loads(info_path.read_bytes()).get("CFBundleIdentifier") == bundle,
                    "Built product bundle identifier differs", ConfigurationFailure)

    def prepare_device(self):
        from recovery_collector import Collector
        self.phase("device")
        self.command(["xcrun", "simctl", "boot", self.device_id], "boot-device", cap=30)
        self.command(["xcrun", "simctl", "bootstatus", self.device_id, "-b"], "boot-status", cap=90)
        for app, label in [(self.app, "app"), (self.runner, "runner")]:
            self.command(["xcrun", "simctl", "install", self.device_id, app], "install-" + label, cap=30)
        self.command(["xcrun", "simctl", "addmedia", self.device_id, self.repo / "UITests/Fixtures/SyntheticRecoveryReceipt.png"], "seed-sole-photo", cap=30)
        app_container = self.app_container(BUNDLE, "app-container")
        runner_container = self.app_container(RUNNER_BUNDLE, "runner-container")
        config = {**self.ids, "app_container": app_container, "runner_container": runner_container,
                  "simulator_root": self.device_root, "evidence_root": self.output / "evidence",
                  "fixture_path": self.repo / "UITests/Fixtures/SyntheticRecoveryReceipt.png",
                  "source_commit": self.grant["source_commit"], "source_tree_sha256": self.tree_sha,
                  "config_sha256": sha(json.dumps(self.grant, sort_keys=True).encode()), "xctestrun_sha256": self.xctestrun_sha,
                  "simulator_udid": self.device_id, "app_bundle_id": BUNDLE, "runner_bundle_id": RUNNER_BUNDLE}
        (self.output / "evidence").mkdir()
        self.collector = Collector(config, guard=self.guard,
                                   run=lambda args: self.command(["xcrun", "xcresulttool", *args], "xcresult-" + str(len(self.record["commands"])), cap=40))
        self.collector.capture_initial_exports()

    def test_and_collect(self):
        self.phase("test")
        self.pin_sources("-pretest")
        require(self.xctestrun.stat().st_size <= MIB and sha(self.xctestrun.read_bytes()) == self.xctestrun_sha,
                "Selected xctestrun changed before execution", ConfigurationFailure)
        self.record["test_count"] += 1
        self.xcresult = self.output / "original.xcresult"
        test_error = None
        try:
            self.command(["xcodebuild", "test-without-building", "-xctestrun", self.xctestrun,
                          "-destination", "platform=iOS Simulator,id=" + self.device_id,
                          "-resultBundlePath", self.xcresult, "-only-testing:" + CASE,
                          "-parallel-testing-enabled", "NO", "-maximum-concurrent-test-simulator-destinations", "1",
                          "-test-iterations", "1", "-test-timeouts-enabled", "YES",
                          "-maximum-test-execution-time-allowance", "420"], "ui-test", cap=480, on_poll=self.collector.poll_bridge)
        except BaseException as error:
            test_error = error
        # Preserve and inventory the original even for a failed test. No reader
        # may see it; native readers operate only on a verified independent copy.
        try:
            self.phase("collect")
            copied = self.collector.capture_xcresult(self.xcresult)
            if test_error is None:
                collected = self.collector.collect(copied)
                self.record["collection"] = str(collected)
                self.command([sys.executable, self.repo / "scripts/verify-recovery-journey.py", collected,
                              "--expected-commit", self.grant["source_commit"]], "verify-artifacts", cap=30)
        except BaseException as error:
            if test_error is None:
                raise
            self.record["preservation_error"] = {"type": type(error).__name__, "message": str(error)}
        if test_error:
            raise test_error
        self.guard(force=True)

    def cleanup(self):
        self.diagnostic_stage = "cleanup"
        self.disarm()
        self.cleanup_mode = True
        self.phase_end = self.outer_end
        self.command_deadline = None
        self.record["retained_resources"] = {"output": str(self.output), "derived_data": str(self.derived), "device": str(self.device_root) if self.device_root else None}
        if self.clock() < self.outer_end:
            self.arm(self.outer_end)
        if self.record.get("device_creation_attempted") and self.device_id is None:
            self.record["cleanup_errors"].append({"device": "Creation outcome uncertain; no unverified device is signalled"})
        if self.device_id:
            already_shutdown = False
            try:
                self.diagnostic_stage = "device_initial_state"
                before = json.loads(self.command(["xcrun", "simctl", "list", "devices", "--json"], "device-cleanup-before", cap=10))
                states = [d for values in before["devices"].values() for d in values if d.get("udid") == self.device_id]
                require(len(states) == 1, "Owned device missing or ambiguous during cleanup")
                already_shutdown = states[0].get("state") == "Shutdown"
            except BaseException as error:
                observation = {"device": self.device_id, "operation": "initial_state", "error": str(error)}
                self.record["cleanup_errors"].append(observation)
                try:
                    self.record_exception_origin(observation, error, "device_cleanup")
                except BaseException:
                    pass
            # Failure to read state must not skip shutdown of our known UUID.
            if not already_shutdown:
                try:
                    self.diagnostic_stage = "device_shutdown"
                    self.command(["xcrun", "simctl", "shutdown", self.device_id], "shutdown-owned-device", cap=25)
                except BaseException as error:
                    observation = {"device": self.device_id, "operation": "shutdown", "error": str(error)}
                    self.record["cleanup_errors"].append(observation)
                    try:
                        self.record_exception_origin(observation, error, "device_cleanup")
                    except BaseException:
                        pass
            try:
                self.diagnostic_stage = "device_final_state"
                listing = json.loads(self.command(["xcrun", "simctl", "list", "devices", "--json"], "device-final-state", cap=15))
                observed = [d for values in listing["devices"].values() for d in values if d.get("udid") == self.device_id]
                require(len(observed) == 1 and observed[0].get("state") == "Shutdown", "Owned simulator shutdown not established")
                self.record["device_final_state"] = "Shutdown"
            except BaseException as error:
                observation = {"device": self.device_id, "operation": "final_state", "error": str(error)}
                self.record["cleanup_errors"].append(observation)
                try:
                    self.record_exception_origin(observation, error, "device_cleanup")
                except BaseException:
                    pass
        # Each group retains its first cleanup deadline and sticky EPERM state.
        # Never restart a timed-out group's cleanup allowance.
        for entry in self.groups:
            if not entry["record"].get("cleanup", {}).get("success"):
                try:
                    self.diagnostic_stage = "final_group_cleanup"
                    report = kill_owned(entry["process"], self.outer_end, state=entry["state"], clock=self.clock)
                    self.record["cleanup_errors"].append({"command": entry["record"]["name"], "final_observation": report})
                    try:
                        self.observe_runtime("final_cleanup_return", entry["record"], report.get("returncode"),
                                             preserve_primary=True)
                    except BaseException:
                        pass
                except BaseException as error:
                    observation = {"command": entry["record"]["name"], "operation": "final_group_cleanup", "error": str(error)}
                    self.record["cleanup_errors"].append(observation)
                    try:
                        self.record_exception_origin(observation, error, "cleanup")
                    except BaseException:
                        pass
        self.record["finished_at"] = utc_now().isoformat()
        self.record["elapsed_seconds"] = self.clock() - self.start

    def execute(self):
        code = 0
        previous_handler = signal.getsignal(signal.SIGALRM)

        def deadline_alarm(signum, frame):
            raise DeadlineFailure("Absolute operation deadline reached")

        # This executable owns the process timer; embedding in an already timed
        # process is deliberately unsupported, rather than replacing its timer.
        require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0),
                "An existing process deadline timer is active", ConfigurationFailure)
        signal.signal(signal.SIGALRM, deadline_alarm)
        self.timer_enabled = True
        try:
            try:
                self.diagnostic_stage = "prepare"
                self.arm(self.phase_end - 4)
                self.prepare()
                self.diagnostic_stage = "build"
                self.build()
                self.diagnostic_stage = "prepare_device"
                self.prepare_device()
                self.diagnostic_stage = "test_collect"
                self.test_and_collect()
            except BaseException as error:
                code = error.exit_code if isinstance(error, RunFailure) else 1
                self.record["primary_error"] = {"type": type(error).__name__, "message": str(error)}
                try:
                    self.record_exception_origin(self.record, error, "operation")
                except BaseException:
                    pass
            self.disarm()
            if self.owns_output:
                try:
                    self.cleanup()
                except BaseException as error:
                    observation = {"operation": "cleanup", "error": str(error)}
                    self.record["cleanup_errors"].append(observation)
                    try:
                        self.record_exception_origin(observation, error, "cleanup")
                    except BaseException:
                        pass
                    code = code or (error.exit_code if isinstance(error, RunFailure) else 1)
                code = code or (1 if self.record["cleanup_errors"] else 0)
                if self.clock() >= self.outer_end:
                    code = 124
                self.record["exit_code"] = code
                self.record["status"] = "PASS_UI_AND_ARTIFACTS_PIXEL_REVIEW_PENDING" if code == 0 else "FAIL"
                # A persisted status is provisional until the process exits.
                # Keep the absolute timer armed through the final fsync.
                self.record["requires_process_exit_code_zero"] = True
                try:
                    self.diagnostic_stage = "final_receipt"
                    self.arm(self.outer_end)
                    self.flush()
                    require(self.clock() < self.outer_end, "Final receipt exceeded outer deadline", DeadlineFailure)
                except BaseException as error:
                    code = 124 if isinstance(error, DeadlineFailure) or self.clock() >= self.outer_end else (code or 1)
                    self.record["finalization_error"] = {"type": type(error).__name__, "message": str(error)}
                    try:
                        self.record_exception_origin(self.record["finalization_error"], error, "finalization")
                    except BaseException:
                        pass
                    self.record["exit_code"], self.record["status"] = code, "FAIL"
        finally:
            self.disarm()
            self.timer_enabled = False
            signal.signal(signal.SIGALRM, previous_handler)
        return code


def emit_summary(value):
    """A stopped pipe reader must not make final reporting unbounded."""
    raw = (json.dumps(value) + "\n").encode()
    descriptor = sys.stdout.fileno()
    os.set_blocking(descriptor, False)
    require(os.write(descriptor, raw) == len(raw), "Incomplete final summary")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--grant", required=True, type=Path)
    parser.add_argument("--grant-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        require(args.execute, "--execute requires a separately approved native slot", ConfigurationFailure)
        raw = args.grant.read_bytes()
        require(len(raw) <= 65536 and sha(raw) == args.grant_sha256, "Grant digest/size differs", ConfigurationFailure)
        grant = validate_grant(json.loads(raw), now=utc_now(), script_root=Path(__file__).resolve().parents[1])
        runner = RecoveryRun(grant)
        code = runner.execute()
        emit_summary({"exit_code": code, "status": runner.record.get("status", "FAIL_BEFORE_NATIVE"), "primary_error": runner.record["primary_error"], "finalization_error": runner.record.get("finalization_error"), "output": str(runner.output) if runner.owns_output else None})
        if runner.clock() >= runner.outer_end:
            return 124
        return code
    except (OSError, ValueError, RunFailure) as error:
        try:
            emit_summary({"status": "FAIL", "error": str(error)})
        except (OSError, ValueError, RunFailure):
            pass
        return error.exit_code if isinstance(error, RunFailure) else 2


if __name__ == "__main__":
    sys.exit(main())
