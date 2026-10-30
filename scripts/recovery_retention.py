"""Source-bound, bounded retention for the ephemeral hosted recovery attempt.

Only the named evidence subsets are archived. No native tools are invoked and
the simulator and DerivedData are never recursively retained.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import struct
import tarfile
import uuid

MIB, GIB = 2**20, 2**30
PACKET_CAP = GIB
BUILD_IDENTITY_CAP = 32 * MIB
PARTIAL_ENTRY_CAP = 1000
ENTRY_CAP = 30000
ROOTS = (
    ("preflight", 16 * MIB, 1000),
    ("hosted-grant-envelope.json", MIB, 1),
    ("build-identity", 32 * MIB, 10000),
    ("run/result.json", 10 * MIB, 1),
    ("run/source-pin.json", MIB, 1),
    ("run/resource-samples.json", 10 * MIB, 1),
    ("run/generated.xctestrun.plist", MIB, 1),
    ("run/selected.xctestrun.plist", MIB, 1),
    ("run/logs", 64 * MIB, 2000),
    ("run/original.xcresult", 192 * MIB, 10000),
    ("run/evidence/collection", 512 * MIB, 12000),
)
NOTICE = """Hosted recovery retained subset
This packet retains the named source/configuration/build identities, command and
cleanup records, raw xcresult, available verified reader copy and attachments,
and the collected inventory/original/export evidence. Consult retention.json for
missing or changed inputs. COMPLETE means retention and recorded checks passed;
independent pixel review and actual CI process exit remain separate evidence.
The full simulator, live app/Files/Photos state, DerivedData, and executable product
bundles are NOT retained. They are unavailable after ephemeral runner teardown.
Failure-state captures are incomplete observations, not successful recovery proof.
"""


class RetentionError(ValueError):
    pass


def require(value, message):
    if not value:
        raise RetentionError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def valid_hash(value, length):
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def relative(value):
    require(isinstance(value, str) and value and "\\" not in value, "invalid relative path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts and path.as_posix() == value and value != ".", "path escape")
    return value


def plain(path):
    path = Path(path).absolute()
    current = path
    while current != current.parent:
        require(not current.is_symlink(), "symlink rejected")
        current = current.parent
    return path


def metadata(info):
    return {"device": info.st_dev, "inode": info.st_ino, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns, "mode": stat.S_IMODE(info.st_mode) & 0o777}


def content(records):
    return {name: {key: value[key] for key in ("kind", "bytes", "sha256", "mode") if key in value}
            for name, value in records.items()}


class Files:
    def __init__(self, guard):
        self.guard = guard

    def read(self, path, limit, *, keep=True):
        self.guard()
        path = plain(path)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= limit, "file size/type limit")
        before, chunks, size, hasher = metadata(info), [], 0, hashlib.sha256()
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            require(metadata(os.fstat(stream.fileno())) == before, "file changed before read")
            while True:
                self.guard()
                part = stream.read(min(MIB, limit - size + 1))
                if not part:
                    break
                size += len(part)
                require(size <= limit, "file grew past limit")
                hasher.update(part)
                if keep:
                    chunks.append(part)
            require(metadata(os.fstat(stream.fileno())) == before, "file changed while reading")
        require(metadata(path.lstat()) == before and size == before["bytes"], "file replaced while reading")
        return b"".join(chunks), {"kind": "file", **before, "sha256": hasher.hexdigest()}

    def snapshot(self, root, limit, entries):
        root = plain(root)
        require(root.exists(), "missing selected evidence")
        if root.is_file():
            return {"": self.read(root, limit, keep=False)[1]}
        require(root.is_dir(), "unsupported evidence root")
        info = root.stat()
        require(entries >= 1, "entry count limit")
        pending, result, total, count = [(root, 0)], {
            "": {"kind": "directory", "mode": stat.S_IMODE(info.st_mode) & 0o777,
                 "device": info.st_dev, "inode": info.st_ino}}, 0, 1
        while pending:
            self.guard()
            folder, depth = pending.pop()
            require(depth <= 30, "directory depth limit")
            with os.scandir(folder) as iterator:
                for entry in iterator:
                    self.guard()
                    count += 1
                    require(count <= entries, "entry count limit")
                    require(not entry.is_symlink(), "symlink rejected")
                    path = Path(entry.path)
                    name = path.relative_to(root).as_posix()
                    relative(name)
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        result[name] = {"kind": "directory", "mode": stat.S_IMODE(info.st_mode) & 0o777,
                                        "device": info.st_dev, "inode": info.st_ino}
                        pending.append((path, depth + 1))
                    else:
                        record = self.read(path, limit - total, keep=False)[1]
                        total += record["bytes"]
                        result[name] = record
        return dict(sorted(result.items()))

    def json(self, path, limit=10 * MIB):
        raw, _ = self.read(path, limit)
        def unique(pairs):
            value = {}
            for key, item in pairs:
                require(key not in value, "duplicate JSON key")
                value[key] = item
            return value
        return json.loads(raw, object_pairs_hook=unique)

    def write(self, path, data):
        self.guard()
        path = plain(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name("." + path.name + ".tmp-" + uuid.uuid4().hex)
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
            for start in range(0, len(data), MIB):
                self.guard()
                stream.write(data[start:start + MIB])
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def copy(self, source, target, record, limit):
        raw, observed = self.read(source, limit)
        require(observed == record, "source changed before copy")
        self.write(target, raw)
        os.chmod(target, record["mode"])


def macho_identity(raw):
    """Read bounded Mach-O identities only; do not load or execute a product."""
    require(len(raw) >= 32, "truncated executable")
    if raw[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = raw[:4] == b"\xca\xfe\xba\xbf"
        count = struct.unpack_from(">I", raw, 4)[0]
        width = 32 if wide else 20
        require(0 < count <= 4 and 8 + width * count <= len(raw), "invalid universal header")
        slices, spans = [], []
        for i in range(count):
            row = struct.unpack_from(">IIQQII" if wide else ">IIIII", raw, 8 + width * i)
            offset, size = row[2:4]
            require(offset >= 8 + width * count and size > 0 and offset + size <= len(raw), "invalid universal slice")
            require(not any(offset < end and start < offset + size for start, end in spans), "overlapping universal slices")
            spans.append((offset, offset + size))
            value = macho_identity(raw[offset:offset + size])
            require(len(value) == 1 and value[0]["cpu_type"] == row[0], "universal CPU mismatch")
            slices.extend(value)
        return slices
    require(raw[:4] == b"\xcf\xfa\xed\xfe", "expected a 64-bit little-endian simulator Mach-O")
    _, cpu, subtype, filetype, count, size, _, _ = struct.unpack_from("<8I", raw)
    require(cpu in (0x01000007, 0x0100000C) and filetype in (2, 6, 8), "unsupported simulator executable type")
    require(count <= 1024 and 32 + size <= len(raw), "invalid Mach-O command extent")
    at, ids, builds = 32, [], []
    for _ in range(count):
        require(at + 8 <= 32 + size, "truncated Mach-O command")
        command, length = struct.unpack_from("<II", raw, at)
        require(length >= 8 and length % 4 == 0 and at + length <= 32 + size, "invalid Mach-O command size")
        if command == 0x1B:
            require(length == 24, "invalid LC_UUID")
            ids.append(str(uuid.UUID(bytes=raw[at + 8:at + 24])).upper())
        if command == 0x32:
            require(length >= 24, "invalid LC_BUILD_VERSION")
            platform, minimum, sdk, tools = struct.unpack_from("<4I", raw, at + 8)
            require(platform == 7 and 24 + tools * 8 == length, "executable is not an iOS simulator build")
            builds.append({"platform": platform, "minimum_os_encoded": minimum, "sdk_encoded": sdk})
        at += length
    require(at == 32 + size and len(ids) == 1 and len(builds) == 1, "missing or duplicate executable build identity")
    return [{"cpu_type": cpu, "cpu_subtype": subtype, "file_type": filetype, "uuid": ids[0], **builds[0]}]


def capture_build_identity(controller, destination, guard):
    files = Files(guard)
    destination = plain(destination)
    work = plain(controller.output).parent
    require(work.name == "room-recovery-work" and destination == work / "build-identity", "unexpected build identity destination")
    require(not destination.exists(), "build identity already exists")
    destination.mkdir()
    source = {"commit": controller.grant["source_commit"], "tree": controller.grant["source_tree"],
              "tree_listing_sha256": controller.tree_sha}
    require(valid_hash(source["commit"], 40) and valid_hash(source["tree"], 40)
            and valid_hash(source["tree_listing_sha256"], 64), "invalid build source binding")
    report = {"schema_version": 1, "status": "COMPLETE", "source": source, "ids": dict(controller.ids),
              "simulator_udid": controller.device_id, "products": {}, "configurations": {},
              "product_bundles_retained": False}
    written, entries = 0, 0
    def retain(name, raw):
        nonlocal written, entries
        written += len(raw)
        entries += 1
        require(written <= BUILD_IDENTITY_CAP and entries <= 16, "build identity output size/count limit")
        files.write(destination / name, raw)
    expected = [("app", Path(controller.app), "com.alvit.roominventory"),
                ("runner", Path(controller.runner), "com.alvit.roominventory.uitests.xctrunner"),
                ("tests", Path(controller.runner) / "PlugIns/RoomInventoryUITests.xctest", "com.alvit.roominventory.uitests")]
    derived = plain(controller.derived)
    require(derived == work / "run/DerivedData", "unexpected DerivedData identity root")
    for role, product, bundle in expected:
        product = plain(product)
        require(product.is_relative_to(derived / "Build/Products"), "product outside owned DerivedData")
        before = files.snapshot(product, 512 * MIB, 10000)
        raw, plist_record = files.read(product / "Info.plist", MIB)
        info = plistlib.loads(raw)
        require(isinstance(info, dict) and info.get("CFBundleIdentifier") == bundle, "build bundle identity differs")
        executable = info.get("CFBundleExecutable")
        require(isinstance(executable, str) and relative(executable) == PurePosixPath(executable).name, "unsafe executable name")
        require(info.get("CFBundleSupportedPlatforms") == ["iPhoneSimulator"], "build plist is not a simulator product")
        binary, binary_record = files.read(product / executable, 128 * MIB)
        slices = macho_identity(binary)
        retain(role + "-Info.plist", raw)
        retain(role + "-files.json", encoded(before))
        require(files.snapshot(product, 512 * MIB, 10000) == before, "product changed during build identity capture")
        report["products"][role] = {"product_relative_to_derived": product.relative_to(derived).as_posix(),
                                     "bundle_id": bundle, "info_plist": plist_record, "executable": executable,
                                     "executable_file": binary_record, "macho": slices,
                                     "files_manifest_sha256": digest(encoded(before)),
                                     "platform_metadata": {k: info[k] for k in ("DTPlatformName", "DTPlatformVersion", "DTSDKName", "DTXcode", "DTXcodeBuild", "MinimumOSVersion", "CFBundleVersion") if k in info}}
    for name in ("generated", "selected"):
        raw, record = files.read(Path(controller.output) / (name + ".xctestrun.plist"), MIB)
        require(isinstance(plistlib.loads(raw), dict), "invalid retained xctestrun")
        if name == "selected":
            actual, _ = files.read(Path(controller.xctestrun), MIB)
            require(actual == raw and digest(raw) == controller.xctestrun_sha, "selected xctestrun binding differs")
        retain(name + ".xctestrun.plist", raw)
        report["configurations"][name] = record
    retain("identity.json", encoded(report))
    files.snapshot(destination, BUILD_IDENTITY_CAP, 16)
    return report


def capture_first_files_tap(work, context, collector, files):
    """Preserve exactly two runner-owned observations, never an acceptance verdict."""
    report = {"status": "MISSING_OR_INVALID", "complete": False, "acceptance_evidence": False}
    original_guard = getattr(collector, "guard", None)
    try:
        require(collector is not None and collector.pins and collector.photos_isolated,
                "owned seeded runner unavailable")
        require(plain(collector.root) == work / "run/evidence/collection", "foreign collection root")
        collector.guard = files.guard  # Retention's existing deadline, independent of xcresult's cap.
        collector._containers()
        pin = files.json(work / "run/source-pin.json", MIB)
        binding = files.json(collector.root / "source-binding.json", MIB)
        selected, _ = files.read(work / "run/selected.xctestrun.plist", MIB)
        require(pin["commit"] == context["source_commit"] == collector.config["source_commit"]
                and pin["tree"] == context["source_tree"]
                and pin["tree_listing_sha256"] == collector.config["source_tree_sha256"]
                and digest(selected) == collector.config["xctestrun_sha256"], "Files capture source differs")
        expected = {**collector.ids, "simulator_udid": collector.config["simulator_udid"]}
        require(all(binding.get(k) == v for k, v in {**expected, **{k: collector.config[k] for k in
                ("source_commit", "source_tree_sha256", "config_sha256", "xctestrun_sha256")}}.items()),
                "Files capture binding differs")
        source = collector.runner / "Documents" / ("RecoveryFilesFirstTap-" + collector.ids["journey_run_id"])
        before = files.snapshot(source, 5 * MIB, 8)
        names = {stage + suffix for stage in ("before", "after") for suffix in (".png", "-ax.json", ".json")}
        require(set(before) == names | {""} and before[""]["kind"] == "directory"
                and all(before[n]["kind"] == "file" for n in names), "Files capture set incomplete or unexpected")

        def parse_capture(raw):
            def pairs(values):
                result = {}
                for key, value in values:
                    require(key not in result, "duplicate Files capture key")
                    result[key] = value
                return result
            return json.loads(raw, object_pairs_hook=pairs,
                              parse_constant=lambda _: require(False, "nonfinite Files capture number"))

        payloads, titles = {}, []
        for stage in ("before", "after"):
            name = stage + ".json"
            raw, observed = files.read(source / name, 16_384)
            require(observed == before[name], "Files receipt changed")
            payloads[name] = raw
            receipt = parse_capture(raw)
            identity = {"schema_version": 1, **expected, "stage": stage}
            require(type(receipt) is dict and set(receipt) == set(identity) | {"files"}
                    and all(type(receipt[k]) is type(v) and receipt[k] == v for k, v in identity.items()),
                    "Files capture run or stage differs")
            entries = receipt["files"]
            require(type(entries) is list and len(entries) == 2, "Files pair missing")
            for entry, suffix, cap in zip(entries, (".png", "-ax.json"), (2 * MIB, 256 * 1024)):
                name = stage + suffix
                require(type(entry) is dict and set(entry) == {"name", "bytes", "sha256"}
                        and entry["name"] == name and type(entry["bytes"]) is int
                        and 0 < entry["bytes"] <= cap, "Files payload name or length invalid")
                raw, observed = files.read(source / name, cap)
                require(observed == before[name] and len(raw) == entry["bytes"]
                        and digest(raw) == entry["sha256"], "Files payload changed or digest differs")
                payloads[name] = raw
                if suffix == ".png":
                    require(len(raw) >= 45 and raw[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                            and raw[-12:] == b"\x00\x00\x00\x00IEND\xaeB`\x82", "Files PNG framing invalid")
                else:
                    ax = parse_capture(raw)
                    require(type(ax) is dict and all(type(ax.get(k)) is type(v) and ax[k] == v for k, v in identity.items())
                            and ax.get("local_title") in ("On My iPhone", "On My iPad")
                            and type(ax.get("hierarchy")) is str and ax["hierarchy"].strip()
                            and type(ax.get("selected_target")) is dict
                            and type(ax.get("matches")) is list and len(ax["matches"]) <= 16
                            and type(ax.get("navigation_bars")) is list and len(ax["navigation_bars"]) <= 8,
                            "Files AX structure or identity invalid")
                    titles.append(ax["local_title"])
        require(titles[0] == titles[1], "Files location changed between stage labels")
        require(files.snapshot(source, 5 * MIB, 8) == before, "Files source changed during capture")
        receipt = {"schema_version": 1, "status": "CAPTURE_COMPLETE_NOT_ACCEPTANCE", "acceptance_evidence": False,
                   "source_commit": pin["commit"], "source_tree": pin["tree"], "source_binding": binding,
                   "source_relative_to_owned_runner": source.relative_to(collector.runner).as_posix(),
                   "files": {name: {"bytes": len(raw), "sha256": digest(raw)} for name, raw in payloads.items()}}
        raw_receipt = encoded(receipt)
        require(len(raw_receipt) <= 16_384, "Files capture receipt bound")
        payloads["capture.json"] = raw_receipt
        existing = files.snapshot(collector.root, 512 * MIB, 12000)
        require(len(existing) + len(payloads) + 1 <= 12000
                and sum(v.get("bytes", 0) for v in existing.values()) + sum(map(len, payloads.values())) <= 512 * MIB,
                "Files capture exceeds existing collection budget")
        # The capture subtree snapshot does not cover runner root/MCM identity.
        # Revalidate the original pins after reads and before publishing bytes.
        collector._containers()
        for name, raw in payloads.items():
            collector._write("files-first-tap/" + name, raw)
        retained = {"run/evidence/collection/files-first-tap/" + name:
                    {"bytes": len(raw), "sha256": digest(raw)} for name, raw in payloads.items()}
        report.update(status="CAPTURE_COMPLETE_NOT_ACCEPTANCE", complete=True,
                      receipt="run/evidence/collection/files-first-tap/capture.json",
                      receipt_sha256=digest(raw_receipt), retained_files=retained)
    except Exception as error:
        report["reason"] = type(error).__name__ + ": " + str(error)[:384]
    finally:
        if collector is not None and original_guard is not None:
            collector.guard = original_guard
    return report


def capture_partial(work, collector, files):
    """Capture only already-pinned attempt state; preserve labels as incomplete."""
    destination = work / "partial-capture"
    require(not destination.exists(), "partial capture already exists")
    destination.mkdir()
    cap_bytes, receipt_reserve = 64 * MIB, 4 * MIB
    require(PARTIAL_ENTRY_CAP >= 2, "partial capture needs root and receipt entries")
    payload_bytes, retained_entries = 0, 1  # The root itself is retained.
    report = {"status": "INCOMPLETE_OBSERVATIONS", "roles_inferred_from_hash_or_time": False,
              "sources": [], "failures": [], "completed_bridge_origins": [],
              "budget": {"byte_cap": cap_bytes, "entry_cap": PARTIAL_ENTRY_CAP,
                         "receipt_reserved_bytes": receipt_reserve, "receipt_reserved_entries": 1}}
    original_guard = getattr(collector, "guard", None)
    try:
        require(collector is not None and collector.pins, "owned container pins unavailable")
        require(plain(collector.root) == work / "run/evidence/collection", "foreign collector evidence root")
        collector.guard = files.guard
        collector._containers()
        require(collector.app.is_relative_to(collector.simulator) and collector.runner.is_relative_to(collector.simulator), "foreign collector containers")
        report["completed_bridge_origins"] = list(collector.origins)
        sources = [("source-namespace", collector.app / "tmp/RoomInventoryUITests" / collector.ids["source_run_id"], 8 * MIB, 100),
                   ("target-namespace", collector.app / "tmp/RoomInventoryUITests" / collector.ids["target_run_id"], 8 * MIB, 100),
                   ("generated-exports", collector.app / "tmp/InventoryExports", 24 * MIB, 100)]
        try:
            saved = collector._files()
            if saved["folder"] is not None:
                sources.append(("saved-files", collector.simulator / relative(saved["folder"]), 24 * MIB, 100))
            else:
                report["failures"].append("unique journey Files folder unavailable")
        except Exception as error:
            report["failures"].append("Files lookup: " + type(error).__name__)
        for label, source, cap, count in sources:
            try:
                before = files.snapshot(source, cap, count)
                observation = {"label": label, "source_relative_to_owned_device": source.relative_to(collector.simulator).as_posix(),
                               "before": before, "after": None, "retained_entries": [], "omitted_entries": [],
                               "retained_bytes": 0}
                report["sources"].append(observation)
                for name, record in before.items():
                    target = destination / label / name
                    size = record.get("bytes", 0)
                    reason = None
                    if retained_entries + 1 > PARTIAL_ENTRY_CAP - 1:
                        reason = "shared entry budget"
                    elif payload_bytes + size > cap_bytes - receipt_reserve:
                        reason = "shared byte budget"
                    elif not target.parent.is_dir():
                        reason = "parent directory omitted"
                    if reason:
                        observation["omitted_entries"].append({"path": name, "reason": reason})
                        continue
                    # Reserve before mkdir/copy; a failed write cannot release
                    # budget for another file while its partial bytes may remain.
                    retained_entries += 1
                    payload_bytes += size
                    if record["kind"] == "directory":
                        target.mkdir()
                        os.chmod(target, record["mode"])
                    else:
                        files.copy(source / name, target, record, cap)
                    observation["retained_entries"].append(name)
                    observation["retained_bytes"] += size
                after = files.snapshot(source, cap, count)
                observation["after"] = after
                if observation["omitted_entries"]:
                    report["failures"].append(label + ": entries omitted by shared capture budget")
                require(before == after, "partial source changed during capture")
            except Exception as error:
                report["failures"].append(label + ": " + type(error).__name__)
    except Exception as error:
        report["failures"].append("owned-state validation: " + type(error).__name__)
    finally:
        if collector is not None and original_guard is not None:
            collector.guard = original_guard
    report["budget"].update({"payload_bytes_reserved": payload_bytes, "entries_reserved_including_receipt": retained_entries + 1})
    if len(encoded(report)) > receipt_reserve:
        # Preserve bounded summaries rather than spending the payload reserve or
        # losing an already-copied subset because its diagnostic JSON grew.
        report["receipt_details_omitted"] = True
        for source in report["sources"]:
            for phase in ("before", "after"):
                value = source.pop(phase)
                source[phase + "_inventory"] = None if value is None else {
                    "entries": len(value), "sha256": digest(encoded(value))}
            for key in ("retained_entries", "omitted_entries"):
                source[key + "_count"] = len(source.pop(key))
        origins = report.pop("completed_bridge_origins")
        report["completed_bridge_origins_summary"] = {"count": len(origins), "sha256": digest(encoded(origins))}
    if len(encoded(report)) > receipt_reserve:
        report = {"status": "INCOMPLETE_OBSERVATIONS", "receipt_details_omitted": True,
                  "roles_inferred_from_hash_or_time": False, "budget": report["budget"],
                  "failures": ["Diagnostic details exceeded reserved receipt budget"],
                  "source_labels": [source["label"] for source in report["sources"]]}
    raw = encoded(report)
    require(len(raw) <= receipt_reserve, "partial receipt reserve too small")
    files.write(destination / "partial-observations.json", raw)
    files.snapshot(destination, cap_bytes, PARTIAL_ENTRY_CAP)
    return report


def validate_complete(work, context, files):
    for key, size in [("source_commit", 40), ("source_tree", 40), ("profile_sha256", 64), ("workflow_sha256", 64)]:
        require(valid_hash(context.get(key), size), "invalid hosted source/config context")
    require(isinstance(context.get("hosted_identity"), dict) and context["hosted_identity"], "missing hosted identity")
    for name, field in [("recovery-hosted-profile.json", "profile_sha256"), ("ci.yml", "workflow_sha256")]:
        raw, _ = files.read(work / "preflight" / name, MIB)
        require(digest(raw) == context[field], "retained profile/workflow hash differs")
    require(type(context.get("controller_exit_code")) is int and context["controller_exit_code"] == 0
            and context.get("primary_error") is None and context.get("cleanup_errors") == [], "hosted controller did not complete cleanly")
    result = files.json(work / "run/result.json")
    require(result.get("status") == "PASS_UI_AND_ARTIFACTS_PIXEL_REVIEW_PENDING" and
            type(result.get("exit_code")) is int and result["exit_code"] == 0 and result.get("cleanup_errors") == []
            and result.get("primary_error") is None and result.get("device_final_state") == "Shutdown"
            and type(result.get("build_count")) is int and result["build_count"] == 1
            and type(result.get("test_count")) is int and result["test_count"] == 1, "controller result is not complete")
    source = files.json(work / "run/source-pin.json")
    require(source.get("commit") == context["source_commit"] and source.get("tree") == context["source_tree"], "retained source pin differs")
    envelope = files.json(work / "hosted-grant-envelope.json")
    for key in ("source_commit", "source_tree", "profile_sha256", "workflow_sha256", "hosted_identity", "tool_hashes"):
        require(key in context and envelope.get(key) == context[key], "hosted envelope/context binding differs")
    require(isinstance(context["tool_hashes"], dict) and context["tool_hashes"] and
            all(valid_hash(value, 64) for value in context["tool_hashes"].values()), "invalid tool hash inventory")
    grant = envelope.get("controller_grant")
    require(isinstance(grant, dict) and source.get("grant") == grant and
            grant.get("source_commit") == context["source_commit"] and grant.get("source_tree") == context["source_tree"],
            "controller grant/source binding differs")
    build = files.json(work / "build-identity/identity.json")
    require(build.get("status") == "COMPLETE" and build.get("source") == {
        "commit": context["source_commit"], "tree": context["source_tree"], "tree_listing_sha256": source.get("tree_listing_sha256")}, "build/source binding differs")
    require(set(build.get("products", {})) == {"app", "runner", "tests"}, "missing executable identities")
    for role, product in build["products"].items():
        raw, _ = files.read(work / "build-identity" / (role + "-files.json"), 10 * MIB)
        require(digest(raw) == product.get("files_manifest_sha256"), "build manifest hash differs")
        inventory = json.loads(raw)
        require(inventory.get(product.get("executable")) == product.get("executable_file"), "executable hash absent from build inventory")
        plist, _ = files.read(work / "build-identity" / (role + "-Info.plist"), MIB)
        require(digest(plist) == product.get("info_plist", {}).get("sha256"), "retained build plist differs")
        require(macho_identity_metadata(product.get("macho")), "invalid executable identity receipt")
    for name in ("generated", "selected"):
        raw, _ = files.read(work / "run" / (name + ".xctestrun.plist"), MIB)
        copy, _ = files.read(work / "build-identity" / (name + ".xctestrun.plist"), MIB)
        require(raw == copy and digest(raw) == build["configurations"][name]["sha256"], "retained configuration changed")
    binding = files.json(work / "run/evidence/collection/source-binding.json")
    require(binding.get("source_commit") == context["source_commit"] and
            binding.get("source_tree_sha256") == source["tree_listing_sha256"] and
            binding.get("config_sha256") == digest(json.dumps(grant, sort_keys=True).encode()) and
            binding.get("xctestrun_sha256") == build["configurations"]["selected"]["sha256"], "collected source/configuration binding differs")
    require(isinstance(build.get("ids"), dict) and build["ids"] and
            all(binding.get(key) == value for key, value in build["ids"].items()) and
            binding.get("simulator_udid") == build.get("simulator_udid"), "build and collected namespace/device binding differs")
    samples = files.json(work / "run/resource-samples.json")
    require(isinstance(samples, list) and samples and all(isinstance(sample, dict) for sample in samples), "missing resource observations")
    commands = result.get("commands")
    require(isinstance(commands, list) and commands, "missing command receipts")
    names = set()
    for command in commands:
        require(isinstance(command, dict), "invalid command receipt")
        name = command.get("name")
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) and name not in names, "invalid/duplicate command name")
        names.add(name)
        require(type(command.get("exit_code")) is int and command["exit_code"] == 0 and
                command.get("primary_error") is None and command.get("cleanup", {}).get("success") is True, "command/cleanup failed")
        for suffix in ("stdout", "stderr"):
            raw, _ = files.read(work / "run/logs" / (name + "." + suffix), 16 * MIB)
            require(digest(raw) == command.get(suffix + "_sha256"), "command log digest differs")
    require({"build", "ui-test", "verify-artifacts", "device-final-state"}.issubset(names), "mandatory command receipt missing")
    verification = files.json(work / "run/logs/verify-artifacts.stdout")
    require(verification.get("status") == "PASS_OFFLINE_ARTIFACT_CONSISTENCY" and
            verification.get("source_commit") == context["source_commit"], "offline verifier result differs")
    collection = work / "run/evidence/collection"
    spec = importlib.util.spec_from_file_location("retention_journey_verifier", Path(__file__).with_name("verify-recovery-journey.py"))
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    verifier.verify_collection(collection / "collection.json", context["source_commit"])
    original = files.snapshot(work / "run/original.xcresult", 192 * MIB, 10000)
    def payload_view(records):
        # Q2 collector manifests describe children only. Retention snapshots
        # additionally preserve the root's mode/identity in the archive record.
        return {name: {key: value[key] for key in ("kind", "bytes", "sha256") if key in value}
                for name, value in records.items() if name != "" or value["kind"] != "directory"}
    for name in ("original-before", "original-after-copy", "original-after-readers"):
        require(payload_view(files.json(collection / "xcresult" / (name + ".json"))) == payload_view(original), "raw xcresult differs from its recorded inventory")
    verified = files.snapshot(collection / "xcresult/verified.xcresult", 192 * MIB, 10000)
    require(payload_view(files.json(collection / "xcresult/copy-after-readers.json")) == payload_view(verified), "verified reader copy differs from recorded inventory")


def macho_identity_metadata(value):
    return isinstance(value, list) and 0 < len(value) <= 4 and all(
        isinstance(item, dict) and item.get("platform") == 7 and isinstance(item.get("uuid"), str)
        for item in value)


class CappedWriter:
    def __init__(self, stream, guard, limit):
        self.stream, self.guard, self.limit, self.count = stream, guard, limit, 0

    def write(self, data):
        self.guard()
        require(self.count + len(data) <= self.limit, "archive byte cap exceeded")
        written = self.stream.write(data)
        self.count += written
        return written


class CheckedReader:
    def __init__(self, path, record, guard):
        self.path, self.record, self.guard = plain(path), record, guard
        self.stream = os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb")
        try:
            require(metadata(os.fstat(self.stream.fileno())) == {k: record[k] for k in metadata(os.fstat(self.stream.fileno()))}, "source changed before archive")
        except Exception:
            self.stream.close()
            raise
        self.hasher, self.size = hashlib.sha256(), 0

    def read(self, count):
        self.guard()
        data = self.stream.read(min(count, MIB))
        self.hasher.update(data)
        self.size += len(data)
        return data

    def close(self, *, validate=True):
        try:
            if not validate:
                return
            current = metadata(os.fstat(self.stream.fileno()))
            require(current == metadata(self.path.lstat()) and all(current[k] == self.record[k] for k in current), "source changed during archive")
            require(self.size == self.record["bytes"] and self.hasher.hexdigest() == self.record["sha256"], "archived source hash differs")
        finally:
            self.stream.close()


def package_evidence(work_root, upload_root, context, guard, *, collector=None):
    files = Files(guard)
    work, upload = plain(work_root), plain(upload_root)
    require(work.name == "room-recovery-work" and upload.name == "room-recovery-upload"
            and work.parent == upload.parent and not upload.exists(), "unexpected hosted retention roots")
    upload.mkdir()
    report = {"schema_version": 1, "status": "PARTIAL", "complete": False, "failures": ["retention not completed"],
              "retained_subset": NOTICE, "full_simulator_retained": False, "derived_data_retained": False,
              "live_state_available_after_runner_teardown": False}
    files.write(upload / "retention.json", encoded(report))
    failures, selected, snapshots, after = [], {}, {}, {}
    try:
        require(len(encoded(context)) <= 65536, "hosted context size limit")
        report["files_first_tap"] = capture_first_files_tap(work, context, collector, files)
        try:
            validate_complete(work, context, files)
        except Exception as error:
            failures.append("acceptance evidence: " + type(error).__name__ + ": " + str(error))
            capture_partial(work, collector, files)
        roots = ROOTS + (("partial-capture", 64 * MIB, PARTIAL_ENTRY_CAP),) if (work / "partial-capture").exists() else ROOTS
        for name, cap, count in roots:
            try:
                tree = files.snapshot(work / name, cap, count)
                require(tree, "empty selected evidence root")
                candidate = {name + ("/" + child if child else ""): record for child, record in tree.items()}
                require(len(selected) + len(candidate) <= ENTRY_CAP, "packet entry count limit")
                # Leave space for manifests, tar headers/padding and the receipt.
                require(sum(r.get("bytes", 0) for r in [*selected.values(), *candidate.values()]) < PACKET_CAP - 32 * MIB,
                        "selected evidence exceeds packet budget")
                selected.update(candidate)
                snapshots[name] = tree
            except Exception as error:
                failures.append(name + ": " + type(error).__name__ + ": " + str(error))
        archive = upload / "evidence.tar"
        archived = {}
        with archive.open("xb") as stream:
            writer = CappedWriter(stream, guard, PACKET_CAP - 8 * MIB)
            with tarfile.open(fileobj=writer, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                def add_bytes(name, raw):
                    info = tarfile.TarInfo(relative(name))
                    info.mode, info.size = 0o600, len(raw)
                    tar.addfile(info, io.BytesIO(raw))
                    archived[name] = {"kind": "file", "mode": info.mode, "bytes": len(raw), "sha256": digest(raw)}
                for name, record in sorted(selected.items()):
                    guard()
                    info = tarfile.TarInfo(relative(name))
                    info.mode = record["mode"]
                    if record["kind"] == "directory":
                        info.type = tarfile.DIRTYPE
                        tar.addfile(info)
                    else:
                        info.size = record["bytes"]
                        reader = CheckedReader(work / name, record, guard)
                        try:
                            tar.addfile(info, reader)
                        except Exception:
                            reader.close(validate=False)
                            raise
                        else:
                            reader.close()
                    archived[name] = content({name: record})[name]
                for name, cap, count in roots:
                    if name in snapshots:
                        try:
                            after[name] = files.snapshot(work / name, cap, count)
                            require(after[name] == snapshots[name], "source changed after packaging")
                        except Exception as error:
                            failures.append(name + " post-package: " + type(error).__name__ + ": " + str(error))
                add_bytes("RETENTION-CONTEXT.json", encoded(context))
                add_bytes("RETENTION-SOURCE-BEFORE.json", encoded(snapshots))
                add_bytes("RETENTION-SOURCE-AFTER.json", encoded(after))
                add_bytes("RETENTION-NOTICE.txt", NOTICE.encode())
            stream.flush()
            os.fsync(stream.fileno())
        # Re-read without extraction. Reject unexpected names/types and compare
        # the bytes actually in the archive, not only the input file hashes.
        seen = {}
        with tarfile.open(archive, "r:") as tar:
            for member in tar:
                guard()
                name = relative(member.name)
                require(name in archived and name not in seen, "unexpected/duplicate archive member")
                require(member.isfile() or member.isdir(), "unsupported archive member type")
                if member.isfile():
                    hasher, size = hashlib.sha256(), 0
                    with tar.extractfile(member) as reader:
                        while True:
                            guard()
                            part = reader.read(MIB)
                            if not part:
                                break
                            size += len(part)
                            require(size <= archived[name]["bytes"], "archive member grew")
                            hasher.update(part)
                    seen[name] = {"kind": "file", "mode": member.mode, "bytes": size, "sha256": hasher.hexdigest()}
                else:
                    seen[name] = {"kind": "directory", "mode": member.mode}
        require(seen == archived, "archive bytes or modes differ from inputs")
        _, archive_record = files.read(archive, PACKET_CAP, keep=False)
        archive_manifest = encoded(archived)
        require(len(archive_manifest) <= 4 * MIB, "archive inventory size limit")
        files.write(upload / "archive-manifest.json", archive_manifest)
        report.update({"archive": {"path": archive.name, **archive_record}, "archive_members_verified": True})
    except Exception as error:
        failures.append("retention: " + type(error).__name__ + ": " + str(error))
    capture = report.get("files_first_tap")
    if capture and capture["complete"]:
        retained = capture["retained_files"]
        if not report.get("archive_members_verified") or not all(
                all(selected.get(name, {}).get(key) == value for key, value in expected.items())
                for name, expected in retained.items()):
            capture.update(status="MISSING_OR_INVALID", complete=False, reason="Files capture not retained in verified archive")
    report.update({"complete": not failures, "status": "PARTIAL" if failures else "COMPLETE", "failures": failures,
                   "selected_source_roots": sorted(snapshots), "source_context": context})
    # The initial PARTIAL receipt remains honest if the bounded final write fails.
    temporary = upload / "retention-final.json"
    final = encoded(report)
    require(len(final) <= MIB, "retention receipt size limit")
    members = list(upload.iterdir())
    require(len(members) <= 16 and all(path.is_file() and not path.is_symlink() for path in members), "unexpected upload contents")
    require(sum(path.stat().st_size for path in members) + len(final) <= PACKET_CAP, "upload packet byte cap exceeded")
    files.write(temporary, final)
    os.replace(temporary, upload / "retention.json")
    return report
