"""Bounded filesystem collector for one opt-in recovery journey.

No process is launched here. ``run`` is the controller's bounded xcresulttool
adapter; ``guard`` enforces its absolute deadline and total resource envelope.
An offline receipt establishes consistency of observations, not screenshot truth.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import uuid

MIB = 1024 * 1024
CASE = "InventoryRecoveryJourneyTests/testPhotosOCRExportRestoreIntoFreshNamespace()"
ROLES = ("source_zip", "backup", "target_zip")
FILENAMES = ("Inventory-package.zip", "Inventory.roominventory", "Inventory-package.zip")
PREFIXES = ("source-", "backup-", "recovered-")
MCM = ".com.apple.mobile_container_manager.metadata.plist"


class CollectorError(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise CollectorError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def parse(data):
    def pairs(values):
        result = {}
        for key, value in values:
            check(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(CollectorError("invalid JSON number")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise CollectorError(f"invalid JSON: {error}") from error


def uuid_string(value):
    check(isinstance(value, str), "UUID must be text")
    try:
        normalized = str(uuid.UUID(value)).upper()
    except ValueError as error:
        raise CollectorError("invalid UUID") from error
    check(value == normalized, "UUID must be canonical uppercase")
    return value


def identity(info):
    return {"device_id": info.st_dev, "inode": info.st_ino}


def content_view(tree):
    return {name: {k: value[k] for k in ("kind", "bytes", "sha256") if k in value}
            for name, value in tree.items()}


class Collector:
    def __init__(self, config, *, guard, run):
        self.config = dict(config)
        self.guard, self.run = guard, run
        self.ids = {key: uuid_string(config[key]) for key in ("journey_run_id", "source_run_id", "target_run_id")}
        check(len(set(self.ids.values())) == 3, "three distinct run IDs required")
        uuid_string(config["simulator_udid"])
        for key, length in [("source_commit", 40), ("source_tree_sha256", 64), ("config_sha256", 64), ("xctestrun_sha256", 64)]:
            check(isinstance(config[key], str) and re.fullmatch(f"[0-9a-f]{{{length}}}", config[key]), f"invalid {key}")
        self.app = self._root(config["app_container"])
        self.runner = self._root(config["runner_container"])
        self.simulator = self._root(config["simulator_root"])
        check(self.app.is_relative_to(self.simulator) and self.runner.is_relative_to(self.simulator)
              and self.app != self.runner, "containers must be distinct within this simulator")
        self.root = self._root(config["evidence_root"]) / "collection"
        check(not self.root.exists(), "collector output already exists")
        self.root.mkdir()
        self.xc_limit = config.get("max_xcresult_bytes", 192 * MIB)
        self.xc_files = config.get("max_xcresult_files", 10000)
        self.attachment_limit = config.get("max_attachment_bytes", 128 * MIB)
        self.output_limit = config.get("max_output_bytes", 512 * MIB)
        for limit in (self.xc_limit, self.xc_files, self.attachment_limit, self.output_limit):
            check(type(limit) is int and limit > 0, "invalid collector bound")
        self.written = 0
        self.pins = {}
        self.baseline = None
        self.installation_state = "unstarted"
        self.installation_files = {}
        self.installation_device = None
        self.barriers, self.origins, self.nonces = [], [], set()
        self.xc_original = self.xc_copy = self.xc_before = None
        self.readers_started = False
        self.folder = "Recovery-" + self.ids["journey_run_id"]
        self.bridge = self.runner / "Documents/RecoveryJourneyBridge" / self.ids["journey_run_id"]
        self._write("source-binding.json", canonical({**self.ids, **{k: config[k] for k in (
            "source_commit", "source_tree_sha256", "config_sha256", "xctestrun_sha256", "simulator_udid")}}))

    def _root(self, value):
        path = Path(value).absolute()
        check(not path.is_symlink() and path.is_dir(), "configured root is missing or symlinked")
        # Resolve host aliases such as /var only at the trusted configuration boundary.
        return path.resolve()

    def _plain(self, path):
        self.guard()
        path = Path(path).absolute()
        current = path
        while current != current.parent:
            if current.exists() or current.is_symlink():
                check(not current.is_symlink(), f"symlink rejected: {current.name}")
            current = current.parent
        return path

    def _read(self, path, limit):
        path = self._plain(path)
        info = path.lstat()
        check(stat.S_ISREG(info.st_mode) and info.st_size <= limit, "file type or byte limit")
        fingerprint = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        chunks, count = [], 0
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            check(identity(os.fstat(stream.fileno())) == identity(info), "file replaced before read")
            while True:
                self.guard()
                chunk = stream.read(min(MIB, limit - count + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                count += len(chunk)
                check(count <= limit, "file grew past byte limit")
            after = os.fstat(stream.fileno())
        current = path.lstat()
        check(all((s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns) == fingerprint
                  for s in (after, current)), "file changed while reading")
        data = b"".join(chunks)
        return data, {"kind": "file", **identity(info), "bytes": count, "sha256": sha(data),
                      "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
                      "created_at_ns": int(getattr(info, "st_birthtime", info.st_ctime) * 1_000_000_000)}

    def _entries(self, path, budget):
        self._plain(path)
        with os.scandir(path) as entries:
            result = []
            for entry in entries:
                self.guard()
                budget[0] -= 1
                check(budget[0] >= 0, "directory entry count limit")
                check(not entry.is_symlink(), "symlink directory entry")
                result.append(Path(entry.path))
        return sorted(result)

    def _snapshot(self, path, max_bytes, max_files, *, missing=False):
        path = self._plain(path)
        if not path.exists():
            check(missing, "missing snapshot root")
            return {}
        check(path.is_dir(), "snapshot root is not a directory")
        tree, total, budget = {}, 0, [max_files]
        pending = [(path, 0)]
        while pending:
            folder, depth = pending.pop()
            check(depth <= 24, "directory depth limit")
            for child in self._entries(folder, budget):
                relative = child.relative_to(path).as_posix()
                info = child.lstat()
                if stat.S_ISDIR(info.st_mode):
                    tree[relative] = {"kind": "directory", **identity(info)}
                    pending.append((child, depth + 1))
                else:
                    _, value = self._read(child, max_bytes - total)
                    total += value["bytes"]
                    tree[relative] = value
        return dict(sorted(tree.items()))

    def _write(self, relative, data):
        self.guard()
        self.written += len(data)
        check(self.written <= self.output_limit, "collector output byte limit")
        path = self.root / relative
        self._plain(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            for start in range(0, len(data), MIB):
                self.guard()
                stream.write(data[start:start + MIB])
            stream.flush()
            os.fsync(stream.fileno())
        self._sync(path.parent)
        # Publish directory entries durably too (including a newly made bridge/).
        parent = path.parent
        while parent != self.root:
            parent = parent.parent
            self._sync(parent)
        self._sync(self.root.parent)
        return path

    def _sync(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _copy_tree(self, source, relative, before, limit, count):
        self.guard()
        copy_bytes = sum(record.get("bytes", 0) for record in before.values())
        check(self.written + copy_bytes <= self.output_limit, "insufficient collector byte budget before copy")
        destination = self.root / relative
        check(not destination.exists(), "copy destination already exists")
        destination.mkdir(parents=True)
        for name, record in before.items():
            self.guard()
            if record["kind"] == "directory":
                (destination / name).mkdir(parents=True, exist_ok=True)
            else:
                data, observed = self._read(source / name, limit)
                check(observed == record, "source changed during copy")
                self._write((destination / name).relative_to(self.root), data)
        after = self._snapshot(source, limit, count)
        copied = self._snapshot(destination, limit, count)
        check(after == before and content_view(copied) == content_view(before), "source or copy changed during capture")
        return destination, after, copied

    def _containers(self):
        result = {}
        for label, path, bundle_key in [("app", self.app, "app_bundle_id"), ("runner", self.runner, "runner_bundle_id")]:
            self._plain(path)
            data, meta = self._read(path / MCM, MIB)
            try:
                value = plistlib.loads(data)
            except Exception as error:
                raise CollectorError("invalid container metadata") from error
            check(isinstance(value, dict) and value.get("MCMMetadataIdentifier") == self.config[bundle_key], "container bundle identity changed")
            result[label] = {"root": identity(path.stat()), "metadata": meta}
        if self.pins:
            check(result == self.pins, "container relocated or metadata changed")
        return result

    def _exports(self):
        tree = self._snapshot(self.app / "tmp/InventoryExports", 24 * MIB, 12, missing=True)
        for name, info in tree.items():
            parts = PurePosixPath(name).parts
            check(len(parts) in (1, 2), "unexpected generated export nesting")
            uuid_string(parts[0])
            check((len(parts) == 1 and info["kind"] == "directory") or
                  (len(parts) == 2 and info["kind"] == "file" and parts[1] in set(FILENAMES)), "unexpected generated export member")
        return tree

    def _files(self):
        groups = self.simulator / "data/Containers/Shared/AppGroup"
        candidates, budget = [], [10000]
        if not groups.exists():
            return {"folder": None, "identity": None, "entries": {}}
        for group in self._entries(groups, budget):
            if not group.is_dir():
                continue
            provider = group / "File Provider Storage"
            self._plain(provider)
            if not provider.exists():
                continue
            pending = [(provider, 0)]
            while pending:
                parent, depth = pending.pop()
                check(depth <= 12, "Files provider depth limit")
                for entry in self._entries(parent, budget):
                    if entry.is_dir():
                        if entry.name == self.folder:
                            candidates.append(entry)
                        else:
                            pending.append((entry, depth + 1))
        check(len(candidates) <= 1, "ambiguous saved Files folder")
        if not candidates:
            return {"folder": None, "identity": None, "entries": {}}
        folder = candidates[0]
        tree = self._snapshot(folder, 24 * MIB, 6)
        check(all("/" not in name and info["kind"] == "file" for name, info in tree.items()), "unexpected saved Files nesting")
        return {"folder": folder.relative_to(self.simulator).as_posix(), "identity": identity(folder.stat()), "entries": tree}

    def _empty_installation_baseline(self, *, require_warmup=False):
        exports, saved = self._exports(), self._files()
        check(exports == {} and saved["folder"] is None, "installation exports or saved folder are not empty")
        for key in ("source_run_id", "target_run_id"):
            path = self._plain(self.app / "tmp/RoomInventoryUITests" / self.ids[key])
            check(not path.exists(), "scenario namespace exists before installation acknowledgement")
        fixture, _ = self._read(Path(self.config["fixture_path"]), 8 * MIB)
        check(sha(fixture) == self.config["fixture_sha256"], "installation fixture binding changed")
        result = {"exports": exports, "saved": saved, "fixture_sha256": sha(fixture)}
        warmup = self._plain(self.app / "tmp/RoomInventoryUITests" / self.ids["journey_run_id"])
        if require_warmup:
            # InventoryRepository initialization/load creates only this empty
            # assets directory and zero-byte storage lock; no inventory is seeded.
            tree = self._snapshot(warmup, 0, 2)
            check(set(tree) == {"assets", ".repository.lock"}
                  and tree["assets"]["kind"] == "directory"
                  and tree[".repository.lock"]["kind"] == "file"
                  and tree[".repository.lock"]["bytes"] == 0,
                  "installation namespace is not the exact empty warmup layout")
            result["warmup"] = {"namespace": warmup.relative_to(self.app).as_posix(),
                                "root": identity(warmup.stat()), "entries": tree}
        else:
            check(not warmup.exists(), "installation namespace exists before first launch")
        return result

    def begin_installation(self):
        check(self.installation_state == "unstarted" and self.baseline is None and not self.pins,
              "installation already started")
        self.guard()
        self.installation_state = "preparing"
        self.installation_device = identity(self.simulator.stat())
        initial = self._empty_installation_baseline()
        check(not self.bridge.exists(), "bridge directory already exists before installation")
        self._write("bridge/preinstallation.json", canonical({
            "containers": self._containers(), "baseline": initial,
            "app": self.app.relative_to(self.simulator).as_posix(),
            "runner": self.runner.relative_to(self.simulator).as_posix(),
            "simulator_udid": self.config["simulator_udid"], "simulator_identity": self.installation_device,
        }))
        # These are installation observations, not scenario pins. The only
        # transition to scenario pins requires a fresh runner request before
        # the test is allowed to construct/launch the AUT or manipulate data.
        self.installation_state = "waiting"

    def _poll_installation(self):
        check(self.installation_state == "waiting", "installation handshake already consumed or failed")
        self.guard()
        check(identity(self.simulator.stat()) == self.installation_device, "owned device changed during installation")
        roots = self._entries(self.simulator / "data/Containers/Data/Application", [2000])
        requests = []
        for root in roots:
            request = self._plain(root / "Documents/RecoveryJourneyBridge" /
                                  self.ids["journey_run_id"] / "installation-request.json")
            if request.exists():
                raw, _ = self._read(request, 16384)
                requests.append((root, request.parent, raw))
        if not requests:
            return 0
        # A consumed or malformed request can never trigger a new discovery.
        self.installation_state = "binding"
        check(len(requests) == 1, "duplicate installation requests")
        runner, bridge, raw = requests[0]
        request = parse(raw)
        expected = {"schema_version": 1, **self.ids, "phase": "installation",
                    **{k: self.config[k] for k in ("simulator_udid", "app_bundle_id", "runner_bundle_id")}}
        check(isinstance(request, dict) and set(request) == {*expected, "nonce"}
              and type(request["schema_version"]) is int
              and all(request[k] == v for k, v in expected.items()), "foreign or malformed installation request")
        nonce = uuid_string(request["nonce"])
        check(nonce not in self.nonces, "reused installation nonce")
        entries = self._entries(bridge, [24])
        check(all(path.name.startswith(".") or path.name == "installation-request.json" for path in entries),
              "scenario or acknowledgement file exists before installation handshake")
        matches = {self.config["app_bundle_id"]: [], self.config["runner_bundle_id"]: []}
        for root in roots:
            metadata = self._plain(root / MCM)
            if not metadata.exists():
                continue  # Installation has not established this unrelated container.
            data, _ = self._read(metadata, MIB)
            try:
                value = plistlib.loads(data)
            except Exception as error:
                raise CollectorError("invalid installation container metadata") from error
            check(isinstance(value, dict), "invalid installation container metadata")
            bundle = value.get("MCMMetadataIdentifier")
            if bundle in matches:
                matches[bundle].append(root)
        check(all(len(paths) == 1 for paths in matches.values()), "missing or ambiguous installed AUT or runner")
        check(matches[self.config["runner_bundle_id"]][0] == runner, "installation request is outside expected runner")
        check(not self.pins and self.baseline is None, "scenario pins already established")
        self.app = self._root(matches[self.config["app_bundle_id"]][0])
        self.runner = self._root(runner)
        check(self.app != self.runner, "installed AUT and runner containers must differ")
        self.bridge = bridge
        baseline = self._empty_installation_baseline(require_warmup=True)
        self.pins = self._containers()
        self.baseline = {k: baseline[k] for k in ("exports", "saved")}
        current, _ = self._read(self.bridge / "installation-request.json", 16384)
        check(current == raw, "installation request changed during capture")
        ack_raw = canonical({**request, "request_sha256": sha(raw), "success": True})
        self.installation_files = {"installation-request.json": sha(raw), "installation-ack.json": sha(ack_raw)}
        self._write("bridge/initial.json", canonical({"containers": self.pins, **self.baseline}))
        self._write("bridge/installation-request.json", raw)
        self._write("bridge/installation-receipt.json", canonical({
            "request": request, "request_sha256": sha(raw), "ack_sha256": sha(ack_raw),
            "app": self.app.relative_to(self.simulator).as_posix(),
            "runner": self.runner.relative_to(self.simulator).as_posix(),
            "containers": self.pins, "baseline": baseline,
            "simulator_identity": self.installation_device,
        }))
        self._write("bridge/installation-ack.json", ack_raw)
        # Revalidate after all evidence writes, before allowing data-bearing UI.
        self._containers()
        check(self._empty_installation_baseline(require_warmup=True) == baseline, "installation baseline changed before acknowledgement")
        current, _ = self._read(self.bridge / "installation-request.json", 16384)
        check(current == raw, "installation request changed before acknowledgement")
        check(identity(self.simulator.stat()) == self.installation_device, "owned device changed before installation acknowledgement")
        self.nonces.add(nonce)
        self._publish_ack("installation-ack.json", ack_raw)
        self.installation_state = "accepted"
        return 0

    def capture_initial_exports(self):
        check(self.installation_state == "unstarted", "installation requires its explicit startup handshake")
        check(self.baseline is None, "baseline already captured")
        self.pins = self._containers()
        exports, saved = self._exports(), self._files()
        check(exports == {} and saved["folder"] is None, "initial exports or saved folder are not empty")
        check(not self.bridge.exists(), "bridge directory already exists before test")
        self.baseline = {"exports": exports, "saved": saved}
        self._write("bridge/initial.json", canonical({"containers": self.pins, **self.baseline}))

    def _validate_request(self, request, number):
        fields = {"schema_version", *self.ids, "sequence", "role", "phase", "nonce"}
        check(isinstance(request, dict) and set(request) == fields, "invalid bridge request fields")
        check(type(request["schema_version"]) is int and request["schema_version"] == 1, "bridge schema")
        check(type(request["sequence"]) is int and request["sequence"] == number, "bridge sequence")
        check(all(request[key] == value for key, value in self.ids.items()), "bridge run IDs")
        check(request["role"] == ROLES[(number - 1) // 2] and request["phase"] == ("before" if number % 2 else "after"), "bridge role or phase")
        nonce = uuid_string(request["nonce"])
        check(nonce not in self.nonces, "reused bridge nonce")

    def poll_bridge(self):
        if self.installation_state in ("waiting", "binding"):
            return self._poll_installation()
        check(self.baseline is not None, "capture baseline first")
        self._containers()
        if self.installation_state == "accepted":
            check(identity(self.simulator.stat()) == self.installation_device, "owned device changed after installation")
            for name, digest in self.installation_files.items():
                raw, _ = self._read(self.bridge / name, 16384)
                check(sha(raw) == digest, "installation handshake changed after acknowledgement")
        if not self.bridge.exists():
            return len(self.barriers)
        entries = self._entries(self.bridge, [24])
        for previous in self.barriers:
            number = previous["request"]["sequence"]
            for prefix in ("request", "ack"):
                data, _ = self._read(self.bridge / f"{prefix}-{number:02d}.json", 16384)
                check(sha(data) == previous[prefix + "_sha256"], "prior bridge message changed")
        number = len(self.barriers) + 1
        for entry in entries:
            if entry.name.startswith("."):
                continue  # In-progress atomic publication, never consumed.
            if self.installation_state == "accepted" and entry.name in self.installation_files:
                continue  # Exact immutable bytes were checked above.
            match = re.fullmatch(r"(request|ack)-(0[1-6])\.json", entry.name)
            check(match is not None, "unexpected bridge file")
            seen = int(match[2])
            check(seen <= number and (match[1] != "ack" or seen < number), "stale or out-of-order bridge file")
        if number > 6:
            return 6
        request_path = self.bridge / f"request-{number:02d}.json"
        if not request_path.exists():
            return len(self.barriers)
        raw, _ = self._read(request_path, 16384)
        request = parse(raw)
        self._validate_request(request, number)
        current = {"exports": self._exports(), "saved": self._files()}
        prior = self.barriers[-1]["snapshot"] if self.barriers else self.baseline
        if number % 2:
            check(current == prior, "exports changed outside their live barrier")
        else:
            self._record_origin(request, prior, current)
        self.nonces.add(request["nonce"])
        ack = {**request, "request_sha256": sha(raw), "success": True}
        ack_raw = canonical(ack)
        receipt = {"request": request, "request_sha256": sha(raw), "ack_sha256": sha(ack_raw), "snapshot": current}
        self._write(f"bridge/request-{number:02d}.json", raw)
        self._write(f"bridge/receipt-{number:02d}.json", canonical(receipt))
        self._write(f"bridge/ack-{number:02d}.json", ack_raw)
        # All host evidence above is durable before allowing the UI to proceed.
        self._publish_ack(f"ack-{number:02d}.json", ack_raw)
        self.barriers.append(receipt)
        return number

    def _publish_ack(self, name, ack_raw):
        temporary = self.bridge / (".ack-" + str(uuid.uuid4()) + ".tmp")
        self._plain(temporary)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(ack_raw)
            stream.flush()
            os.fsync(stream.fileno())
        self.guard()  # A completed write/fsync cannot renew the original deadline.
        os.link(temporary, self.bridge / name, follow_symlinks=False)
        temporary.unlink()
        self._sync(self.bridge)

    def _record_origin(self, request, prior, current):
        before, after = prior["exports"], current["exports"]
        check(all(after.get(name) == value for name, value in before.items()), "prior generated export changed")
        additions = set(after) - set(before)
        directories = [name for name in additions if after[name]["kind"] == "directory"]
        check(len(directories) == 1 and len(additions) == 2, "barrier must create exactly one export directory and payload")
        index = ROLES.index(request["role"])
        generated = directories[0] + "/" + FILENAMES[index]
        check(generated in additions and after[generated]["kind"] == "file", "wrong generated payload for barrier")
        saved_before, saved_after = prior["saved"], current["saved"]
        if saved_before["folder"] is not None:
            check(saved_after["folder"] == saved_before["folder"] and saved_after["identity"] == saved_before["identity"], "saved Files folder changed identity")
        check(saved_after["folder"] is not None, "missing saved Files folder")
        check(all(saved_after["entries"].get(name) == value for name, value in saved_before["entries"].items()), "prior saved Files copy changed")
        extension = "roominventory" if index == 1 else "zip"
        saved_name = PREFIXES[index] + self.ids["journey_run_id"] + "." + extension
        check(set(saved_after["entries"]) - set(saved_before["entries"]) == {saved_name}, "barrier must save exactly its named Files copy")
        generated_meta, saved_meta = after[generated], saved_after["entries"][saved_name]
        check(content_view({"file": generated_meta}) == content_view({"file": saved_meta}), "saved and generated payload differ at barrier")
        check(all(identity_tuple(generated_meta) != identity_tuple(origin["metadata"]) for origin in self.origins), "reused generated file identity")
        self.origins.append({"role": request["role"], "directory_id": directories[0], "generated": generated,
                             "saved": saved_after["folder"] + "/" + saved_name, "metadata": generated_meta,
                             "saved_metadata": saved_meta, "barrier_sequence": request["sequence"]})

    def capture_xcresult(self, original):
        check(self.xc_original is None, "xcresult already captured")
        original = self._plain(Path(original).absolute())
        before = self._snapshot(original, self.xc_limit, self.xc_files)
        check(before and "Info.plist" in before, "missing xcresult bundle metadata")
        copy_bytes = sum(record.get("bytes", 0) for record in before.values())
        check(self.written + copy_bytes + 3 * len(canonical(before)) <= self.output_limit,
              "insufficient collector byte budget before xcresult copy")
        self._write("xcresult/original-before.json", canonical(before))
        try:
            copy, after, copied = self._copy_tree(original, "xcresult/verified.xcresult", before, self.xc_limit, self.xc_files)
        except Exception as primary:
            failures = []
            try:
                after = self._snapshot(original, self.xc_limit, self.xc_files)
                self._write("xcresult/original-after-copy.json", canonical(after))
            except Exception as error:
                failures.append(f"original post-copy capture: {type(error).__name__}: {error}")
            try:
                self._write("xcresult/capture-errors.json", canonical({
                    "primary_copy_error": f"{type(primary).__name__}: {primary}", "post_copy_errors": failures[:]}))
            except Exception as error:
                failures.append(f"error receipt: {type(error).__name__}: {error}")
            if failures:
                raise CollectorError(f"Primary copy failure: {primary}; " + "; ".join(failures)) from primary
            raise
        self._write("xcresult/original-after-copy.json", canonical(after))
        self._write("xcresult/copy-before-readers.json", canonical(copied))
        self.xc_original, self.xc_copy, self.xc_before = original, copy, before
        self.xc_copy_before = copied
        return copy

    def _tool_json(self, args, relative):
        self.guard()
        raw = self.run(args)
        check(isinstance(raw, bytes) and len(raw) <= 10 * MIB, "xcresult metadata byte limit")
        self._write(relative, raw)
        return parse(raw)

    def _validate_results(self, summary, tests):
        check(isinstance(summary, dict) and summary.get("result") == "Passed", "xcresult did not pass")
        for field, value in [("totalTestCount", 1), ("passedTests", 1), ("failedTests", 0), ("skippedTests", 0), ("expectedFailures", 0)]:
            check(type(summary.get(field)) is int and summary[field] == value, "xcresult must contain exactly one pass with zero skips/failures")
        check(summary.get("testFailures") == [], "xcresult contains test failures")
        devices = summary.get("devicesAndConfigurations")
        check(isinstance(devices, list) and len(devices) == 1 and isinstance(devices[0], dict)
              and isinstance(devices[0].get("device"), dict) and
              devices[0]["device"].get("deviceId") == self.config["simulator_udid"], "xcresult device does not match owned simulator")
        check(isinstance(tests, dict) and isinstance(tests.get("testNodes"), list), "missing test tree")
        pending, cases, count = list(tests["testNodes"]), [], 0
        while pending:
            self.guard()
            node = pending.pop()
            count += 1
            check(count <= 10000 and isinstance(node, dict), "invalid or oversized test tree")
            if node.get("nodeType") == "Test Case":
                cases.append(node)
            children = node.get("children", [])
            check(isinstance(children, list), "invalid test children")
            pending.extend(children)
        check(len(cases) == 1 and cases[0].get("nodeIdentifier") == CASE and cases[0].get("result") == "Passed", "wrong selected XCTest case")

    def _read_ui(self, copy):
        summary = self._tool_json(["get", "test-results", "summary", "--path", str(copy), "--compact"], "xcresult/summary.json")
        tests = self._tool_json(["get", "test-results", "tests", "--path", str(copy), "--compact"], "xcresult/tests.json")
        self._validate_results(summary, tests)
        exported = self.root / "xcresult/attachments"
        check(not exported.exists(), "attachment destination already exists")
        self.guard()
        output = self.run(["export", "attachments", "--path", str(copy), "--output-path", str(exported)])
        check(isinstance(output, bytes) and len(output) <= MIB, "attachment export output bound")
        self._write("xcresult/attachment-export.txt", output)
        tree = self._snapshot(exported, self.attachment_limit, 1000)
        self.written += sum(info.get("bytes", 0) for info in tree.values())
        check(self.written <= self.output_limit, "collector output byte limit")
        self._write("xcresult/attachments-manifest.json", canonical(tree))
        raw, _ = self._read(exported / "manifest.json", 10 * MIB)
        manifest = parse(raw)
        check(isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict)
              and manifest[0].get("testIdentifier") == CASE, "attachment manifest test identity")
        attachments = manifest[0].get("attachments")
        check(isinstance(attachments, list) and len(attachments) <= 999, "invalid attachment manifest")
        def resolve(name):
            hits = []
            for attachment in attachments:
                check(isinstance(attachment, dict), "invalid attachment record")
                suggested = attachment.get("suggestedHumanReadableName")
                if attachment_name_matches(suggested, name):
                    check(attachment.get("deviceId") == self.config["simulator_udid"] and
                          attachment.get("isAssociatedWithFailure") is False, "attachment device/failure mismatch")
                    filename = attachment.get("exportedFileName")
                    check(isinstance(filename, str) and PurePosixPath(filename).name == filename and
                          filename not in ("", ".", "..") and "\\" not in filename, "unsafe exported attachment filename")
                    check(filename in tree and tree[filename]["kind"] == "file", "missing exported attachment")
                    hits.append("xcresult/attachments/" + filename)
            check(len(hits) == 1, "missing or ambiguous UI attachment: " + name)
            return hits[0]
        ledger_path = resolve("recovery-journey-evidence.json")
        raw, _ = self._read(self.root / ledger_path, 8 * MIB)
        ledger = parse(raw)
        check(isinstance(ledger, dict) and ledger.get("outcome") == "passed" and ledger.get("issues") == [], "UI ledger did not complete")
        check(all(ledger.get(key) == value for key, value in self.ids.items()), "UI ledger run ID mismatch")
        events = ledger.get("events")
        check(isinstance(events, list) and len(events) == 17, "missing UI checkpoints")
        mapping = {}
        for event in events:
            check(isinstance(event, dict) and isinstance(event.get("attachments"), dict)
                  and set(event["attachments"]) == {"screenshot", "accessibility"}, "missing checkpoint captures")
            for name in event["attachments"].values():
                check(isinstance(name, str) and name not in mapping, "duplicate capture reference")
                mapping[name] = resolve(name)
        check(len(mapping) == 34 and len(set(mapping.values())) == 34, "UI captures are not distinct")
        return ledger_path, mapping

    def collect(self, verified_xcresult):
        check(self.xc_copy is not None and Path(verified_xcresult) == self.xc_copy, "readers require this collector's verified xcresult copy")
        check(not self.readers_started, "xcresult readers already attempted")
        check(self._snapshot(self.xc_original, self.xc_limit, self.xc_files) == self.xc_before,
              "original xcresult changed before readers")
        check(self._snapshot(self.xc_copy, self.xc_limit, self.xc_files) == self.xc_copy_before,
              "verified xcresult copy changed before readers")
        self.readers_started = True
        primary, post_errors = None, []
        try:
            ledger, attachments = self._read_ui(self.xc_copy)
        except Exception as error:
            primary = error
        # Verification failures must not replace the reader's original failure.
        for label, path in [("original", self.xc_original), ("copy", self.xc_copy)]:
            try:
                after = self._snapshot(path, self.xc_limit, self.xc_files)
                self._write(f"xcresult/{label}-after-readers.json", canonical(after))
                if label == "original":
                    check(after == self.xc_before, "reader changed original xcresult")
            except Exception as error:
                post_errors.append(f"{label}: {type(error).__name__}: {error}")
        if primary is not None or post_errors:
            report = {"primary_reader_error": None if primary is None else f"{type(primary).__name__}: {primary}",
                      "post_reader_verification_errors": post_errors[:]}
            try:
                self._write("xcresult/reader-errors.json", canonical(report))
            except Exception as error:
                post_errors.append(f"error receipt: {type(error).__name__}: {error}")
            if primary is not None and not post_errors:
                raise primary
            message = (f"Primary reader failure: {type(primary).__name__}: {primary}; " if primary is not None else "")
            raise CollectorError(message + "Post-reader verification: " + "; ".join(post_errors)) from primary
        check(self.poll_bridge() == 6 and len(self.origins) == 3, "incomplete live export barriers")
        check({"exports": self._exports(), "saved": self._files()} == self.barriers[-1]["snapshot"], "exports changed after final barrier")
        artifacts = {}
        for label, run_key in [("source", "source_run_id"), ("target", "target_run_id")]:
            source = self.app / "tmp/RoomInventoryUITests" / self.ids[run_key]
            before = self._snapshot(source, 8 * MIB, 100)
            _, _, _ = self._copy_tree(source, "namespaces/" + label, before, 8 * MIB, 100)
            self._write("namespaces/" + label + "-manifest.json", canonical(before))
            artifacts[label + "_inventory"] = "namespaces/" + label + "/inventory.json"
            raw, _ = self._read(self.root / artifacts[label + "_inventory"], 8 * MIB)
            try:
                filename = parse(raw)["homes"][0]["rooms"][0]["items"][0]["attachments"][0]["fileName"]
            except (KeyError, IndexError, TypeError) as error:
                raise CollectorError("missing namespace original reference") from error
            check(isinstance(filename, str) and re.fullmatch(r"[0-9a-f-]{36}\.png", filename), "unsafe namespace original filename")
            artifacts[label + "_original"] = "namespaces/" + label + "/assets/" + filename
            check("assets/" + filename in before, "namespace original file missing")
        receipt_entries = []
        for index, origin in enumerate(self.origins):
            generated_key = ("source_generated_zip", "generated_backup", "target_generated_zip")[index]
            for key, path, expected in [(generated_key, self.app / "tmp/InventoryExports" / origin["generated"], origin["metadata"]),
                                        (origin["role"], self.simulator / origin["saved"], origin["saved_metadata"])]:
                data, meta = self._read(path, 8 * MIB)
                check(meta == expected, "export changed during final collection")
                relative = "artifacts/" + key + (".roominventory" if index == 1 else ".zip")
                self._write(relative, data)
                artifacts[key] = relative
            meta = origin["metadata"]
            receipt_entries.append({"role": origin["role"], "directory_id": origin["directory_id"],
                                    "generated_path": "tmp/InventoryExports/" + origin["generated"],
                                    **{k: meta[k] for k in ("device_id", "inode", "created_at_ns", "bytes", "sha256")},
                                    "saved_path": self.folder + "/" + PurePosixPath(origin["saved"]).name})
        fixture, _ = self._read(Path(self.config["fixture_path"]), 8 * MIB)
        self._write("artifacts/fixture.png", fixture)
        artifacts["fixture"] = "artifacts/fixture.png"
        self._write("bridge/origins.json", canonical(self.origins))
        self._write("collection-receipt.json", canonical({"schema_version": 1, **self.ids, "exports_before": [], "exports_after": receipt_entries}))
        document = {"schema_version": 1, "source_commit": self.config["source_commit"],
                    "source_run_id": self.ids["source_run_id"], "target_run_id": self.ids["target_run_id"],
                    "ui_evidence": ledger, "ui_attachments": attachments, "artifacts": artifacts,
                    "collection_receipt": "collection-receipt.json"}
        return self._write("collection.json", canonical(document))


def identity_tuple(value):
    return value["device_id"], value["inode"]


def attachment_name_matches(candidate, expected):
    if not isinstance(candidate, str):
        return False
    if candidate == expected:
        return True
    path = PurePosixPath(expected)
    suffix = r"_0_[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}" + re.escape(path.suffix)
    return any(re.fullmatch(re.escape(prefix) + suffix, candidate) for prefix in (expected, path.stem))
