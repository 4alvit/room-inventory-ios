#!/usr/bin/env python3
"""Bind hosted preview bytes to an immutable checkout; never publish or sign."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "4alvit/room-inventory-ios"


def commit(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Expected an immutable Git identity")
    return value


def positive_number(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("Expected a positive hosted run identifier")
    return int(value)


def context(checkout: str, tree: str, env: dict[str, str], event: dict) -> dict:
    """Validate only allowlisted event fields; do not retain arbitrary event data."""
    if env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("Preview provenance requires this repository's hosted run")
    if event.get("repository", {}).get("full_name") != REPOSITORY:
        raise ValueError("Event repository does not match preview repository")
    checkout, tree = commit(checkout), commit(tree)
    event_sha = commit(env.get("GITHUB_SHA", ""))
    kind = env.get("GITHUB_EVENT_NAME")
    result = {
        "schema": 1,
        "repository": REPOSITORY,
        "checkout_commit": checkout,
        "checkout_tree": tree,
        "event": kind,
        "event_commit": event_sha,
        "run_id": positive_number(env.get("GITHUB_RUN_ID", "")),
        "run_attempt": positive_number(env.get("GITHUB_RUN_ATTEMPT", "")),
        "signed_attestation": False,
        "app_store_release": False,
    }
    if kind == "pull_request":
        pr = event.get("pull_request", {})
        head = pr.get("head", {})
        if head.get("repo", {}).get("full_name") != REPOSITORY:
            raise ValueError("PR preview requires a same-repository head")
        head_sha = commit(head.get("sha", ""))
        tested_commit = commit(env.get("PREVIEW_TESTED_COMMIT", ""))
        tested_tree = commit(env.get("PREVIEW_TESTED_TREE", ""))
        if commit(env.get("PREVIEW_SOURCE_REF", "")) != head_sha or checkout != head_sha:
            raise ValueError("Checkout must be the immutable PR head")
        if tested_commit != event_sha or tested_tree != tree:
            raise ValueError("Tested PR merge and candidate must have the same source tree")
        number = pr.get("number")
        if type(number) is not int or number <= 0:
            raise ValueError("Expected a positive PR number")
        result.update(pr_number=number, pr_head_commit=head_sha,
                      tested_commit=tested_commit, tested_tree=tested_tree)
    elif kind in {"push", "schedule", "workflow_dispatch"}:
        if checkout != event_sha or any(env.get(name) for name in (
            "PREVIEW_SOURCE_REF", "PREVIEW_TESTED_COMMIT", "PREVIEW_TESTED_TREE"
        )):
            raise ValueError("Release caller must retain its event checkout")
    else:
        raise ValueError("Unsupported preview event")
    result["run_url"] = f"https://github.com/{REPOSITORY}/actions/runs/{result['run_id']}"
    return result


def record(output: Path, identity: dict) -> None:
    """Verify existing hashes before adding a receipt; leave all payloads intact."""
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Expected a regular preview output directory")
    entries = list(output.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("Preview output must contain only regular files")
    metadata_bytes = (output / "preview-build.json").read_bytes()
    metadata = json.loads(metadata_bytes)
    version, channel = metadata.get("base_version"), metadata.get("channel")
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
        raise ValueError("Invalid preview version")
    if channel not in {"nightly", "beta", "rc"}:
        raise ValueError("Invalid preview channel")
    prefix = f"room-inventory-ios-{version}-{channel}"
    names = {"PREVIEW-README.txt", "preview-build.json", f"{prefix}-source.tar.gz", f"{prefix}-unsigned-simulator.zip"}
    if {path.name for path in entries} != names | {"SHA256SUMS"}:
        raise ValueError("Unexpected or already recorded preview output")
    if (metadata.get("source_commit") != identity["checkout_commit"] or
            metadata.get("repository") != REPOSITORY or
            metadata.get("artifact_kind") != "unsigned-ios-simulator-preview" or
            metadata.get("app_store_release") is not False or
            metadata.get("real_purchases_configured") is not False):
        raise ValueError("Packaged preview identity differs from checked checkout")
    hashes = {}
    for line in (output / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match or match[2] not in names or match[2] in hashes:
            raise ValueError("Invalid preview checksum inventory")
        hashes[match[2]] = match[1]
    if set(hashes) != names:
        raise ValueError("Incomplete preview checksum inventory")
    payloads = {}
    for name in sorted(names):
        data = (output / name).read_bytes()
        if name == "preview-build.json" and data != metadata_bytes:
            raise ValueError("Preview metadata changed during validation")
        digest = hashlib.sha256(data).hexdigest()
        if digest != hashes[name]:
            raise ValueError("Preview payload checksum mismatch")
        payloads[name] = {"sha256": digest, "bytes": len(data)}
    receipt = dict(identity, payloads=payloads,
                   acceptance="Build provenance only; full CI and runtime acceptance remain separate")
    receipt_path = output / "preview-provenance.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    hashes[receipt_path.name] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text("".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "record"))
    action = parser.parse_args().action
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        if not isinstance(event, dict):
            raise ValueError("Expected an event object")
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.PIPE).strip()
        if git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError("Preview provenance requires a clean checkout")
        identity = context(git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}"), dict(os.environ), event)
        if action == "record":
            record(ROOT / "release-dist", identity)
    except (OSError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError, ValueError):
        # Event text, credentials and filesystem paths must not leak through errors.
        raise SystemExit("Preview provenance validation failed") from None
    print("Preview checkout provenance verified" if action == "check" else "Preview payload provenance recorded")


if __name__ == "__main__":
    main()
