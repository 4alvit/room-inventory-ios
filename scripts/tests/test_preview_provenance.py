"""Exercise hosted preview receipts using synthetic bytes, never app builds."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROVENANCE = load_module("preview_provenance", ROOT / "scripts/preview-provenance.py")
CONTRACTS = load_module("preview_workflow_contracts", ROOT / "scripts/workflow_contracts.py")
REPOSITORY = "4alvit/room-inventory-ios"
HEAD, MERGE, TREE, OTHER = (letter * 40 for letter in "abcd")
PRIVATE = "synthetic-private-value-do-not-print"


def pr_inputs():
    return ({
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_EVENT_NAME": "pull_request", "GITHUB_SHA": MERGE,
        "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "2",
        "PREVIEW_SOURCE_REF": HEAD, "PREVIEW_TESTED_COMMIT": MERGE,
        "PREVIEW_TESTED_TREE": TREE,
    }, {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {"number": 17, "head": {"sha": HEAD, "repo": {"full_name": REPOSITORY}}},
    })


def identity():
    return PROVENANCE.context(HEAD, TREE, *pr_inputs())


class PreviewContextTests(unittest.TestCase):
    def test_same_tree_pr_accepts_different_head_and_tested_merge_commits(self):
        result = identity()
        self.assertNotEqual(HEAD, MERGE)
        self.assertEqual(result, {
            "schema": 1, "repository": REPOSITORY, "event": "pull_request",
            "checkout_commit": HEAD, "checkout_tree": TREE, "event_commit": MERGE,
            "run_id": 12345, "run_attempt": 2, "pr_number": 17,
            "pr_head_commit": HEAD, "tested_commit": MERGE, "tested_tree": TREE,
            "signed_attestation": False, "app_store_release": False,
            "run_url": f"https://github.com/{REPOSITORY}/actions/runs/12345",
        })

    def test_rejects_each_broken_pr_binding(self):
        cases = [
            (OTHER, TREE, {}, {}), (HEAD, OTHER, {}, {}),
            (HEAD, TREE, {"PREVIEW_SOURCE_REF": OTHER}, {}),
            (HEAD, TREE, {"PREVIEW_TESTED_COMMIT": OTHER}, {}),
            (HEAD, TREE, {"PREVIEW_TESTED_TREE": OTHER}, {}),
            (HEAD, TREE, {"GITHUB_SHA": OTHER}, {}),
            (HEAD, TREE, {}, {"sha": OTHER}),
        ]
        for checkout, tree, overrides, head_overrides in cases:
            with self.subTest(checkout=checkout, tree=tree, overrides=overrides, head=head_overrides):
                env, event = pr_inputs()
                env.update(overrides)
                event["pull_request"]["head"].update(head_overrides)
                with self.assertRaises(ValueError):
                    PROVENANCE.context(checkout, tree, env, event)

    def test_requires_hosted_expected_repository_in_env_and_event(self):
        for field, value in [("GITHUB_ACTIONS", "false"), ("GITHUB_ACTIONS", ""),
                             ("GITHUB_REPOSITORY", "someone/room-inventory-ios")]:
            with self.subTest(field=field, value=value):
                env, event = pr_inputs()
                env[field] = value
                with self.assertRaises(ValueError):
                    PROVENANCE.context(HEAD, TREE, env, event)
        for repository in [{}, {"full_name": "someone/room-inventory-ios"}]:
            env, event = pr_inputs()
            event["repository"] = repository
            with self.assertRaises(ValueError):
                PROVENANCE.context(HEAD, TREE, env, event)

    def test_rejects_fork_or_absent_head_repository(self):
        for repository in [{}, {"full_name": "fork/room-inventory-ios"}]:
            with self.subTest(repository=repository):
                env, event = pr_inputs()
                event["pull_request"]["head"]["repo"] = repository
                with self.assertRaises(ValueError):
                    PROVENANCE.context(HEAD, TREE, env, event)

    def test_rejects_unsupported_or_privileged_event_types(self):
        for kind in ["pull_request_target", "workflow_run", "merge_group", "release", "", None]:
            with self.subTest(kind=kind):
                env, event = pr_inputs()
                env["GITHUB_EVENT_NAME"] = kind
                with self.assertRaises(ValueError):
                    PROVENANCE.context(HEAD, TREE, env, event)

    def test_all_commit_and_tree_inputs_require_full_lowercase_git_ids(self):
        fields = ["checkout", "tree", "head", "GITHUB_SHA", "PREVIEW_SOURCE_REF", "PREVIEW_TESTED_COMMIT", "PREVIEW_TESTED_TREE"]
        for field in fields:
            for invalid in [None, True, "", "main", "a" * 39, "a" * 41, "A" * 40, "g" * 40, HEAD + "\n"]:
                with self.subTest(field=field, invalid=invalid):
                    env, event = pr_inputs()
                    checkout, tree = HEAD, TREE
                    if field == "checkout":
                        checkout = invalid
                    elif field == "tree":
                        tree = invalid
                    elif field == "head":
                        event["pull_request"]["head"]["sha"] = invalid
                    else:
                        env[field] = invalid
                    with self.assertRaises(ValueError):
                        PROVENANCE.context(checkout, tree, env, event)

    def test_run_ids_and_attempts_are_positive_decimal_strings(self):
        for field in ["GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"]:
            for invalid in [None, 1, True, "", "0", "01", "-1", "+1", "1.0", "1\n", "one"]:
                with self.subTest(field=field, invalid=invalid):
                    env, event = pr_inputs()
                    env[field] = invalid
                    with self.assertRaises(ValueError):
                        PROVENANCE.context(HEAD, TREE, env, event)

    def test_pr_number_is_a_positive_integer_not_a_boolean(self):
        for invalid in [None, True, False, 0, -1, "17", 1.5]:
            with self.subTest(number=invalid):
                env, event = pr_inputs()
                event["pull_request"]["number"] = invalid
                with self.assertRaises(ValueError):
                    PROVENANCE.context(HEAD, TREE, env, event)

    def test_non_pr_defaults_keep_event_checkout_without_pr_claims(self):
        for kind in ["push", "schedule", "workflow_dispatch"]:
            for empty_inputs in [False, True]:
                with self.subTest(kind=kind, empty_inputs=empty_inputs):
                    env, event = pr_inputs()
                    env.update(GITHUB_EVENT_NAME=kind, GITHUB_SHA=HEAD)
                    for field in ["PREVIEW_SOURCE_REF", "PREVIEW_TESTED_COMMIT", "PREVIEW_TESTED_TREE"]:
                        env.pop(field)
                        if empty_inputs:
                            env[field] = ""
                    result = PROVENANCE.context(HEAD, TREE, env, event)
                    self.assertEqual(result["checkout_commit"], result["event_commit"])
                    self.assertEqual(result["event"], kind)
                    self.assertFalse(set(result) & {"pr_number", "pr_head_commit", "tested_commit", "tested_tree"})

    def test_non_pr_rejects_checkout_override_and_each_pr_only_input(self):
        for kind in ["push", "schedule", "workflow_dispatch"]:
            for field in ["checkout", "PREVIEW_SOURCE_REF", "PREVIEW_TESTED_COMMIT", "PREVIEW_TESTED_TREE"]:
                with self.subTest(kind=kind, field=field):
                    env, event = pr_inputs()
                    env.update(GITHUB_EVENT_NAME=kind, GITHUB_SHA=HEAD,
                               PREVIEW_SOURCE_REF="", PREVIEW_TESTED_COMMIT="", PREVIEW_TESTED_TREE="")
                    checkout = OTHER if field == "checkout" else HEAD
                    if field != "checkout":
                        env[field] = HEAD
                    with self.assertRaises(ValueError):
                        PROVENANCE.context(checkout, TREE, env, event)

    def test_context_allowlist_does_not_leak_env_or_event_and_does_not_mutate_them(self):
        env, event = pr_inputs()
        env.update(GITHUB_TOKEN=PRIVATE, HOME="/Users/" + PRIVATE, UNRELATED_SECRET=PRIVATE)
        event.update(sender={"email": PRIVATE}, arbitrary=PRIVATE)
        event["pull_request"].update(title=PRIVATE, body=PRIVATE, user={"email": PRIVATE})
        event["pull_request"]["head"].update(ref=PRIVATE, label=PRIVATE)
        originals = deepcopy((env, event))
        self.assertEqual(PROVENANCE.context(HEAD, TREE, env, event), identity())
        self.assertEqual((env, event), originals)
        self.assertNotIn(PRIVATE, json.dumps(PROVENANCE.context(HEAD, TREE, env, event)))


class PreviewRecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "release-dist"
        self.output.mkdir()
        self.metadata = {
            "base_version": "0.1.0", "channel": "beta", "source_commit": HEAD,
            "repository": REPOSITORY, "artifact_kind": "unsigned-ios-simulator-preview",
            "app_store_release": False, "real_purchases_configured": False,
        }
        self.metadata_path = self.output / "preview-build.json"
        self.metadata_path.write_text(json.dumps(self.metadata))
        (self.output / "PREVIEW-README.txt").write_text("Synthetic preview fixture, not an app.\n")
        (self.output / "room-inventory-ios-0.1.0-beta-source.tar.gz").write_bytes(b"synthetic-source\x00")
        (self.output / "room-inventory-ios-0.1.0-beta-unsigned-simulator.zip").write_bytes(b"synthetic-simulator\x00")
        self.names = {p.name for p in self.output.iterdir()}
        self.checksums = self.output / "SHA256SUMS"
        self.write_checksums()

    def write_checksums(self):
        self.checksums.write_text("".join(
            f"{hashlib.sha256((self.output / name).read_bytes()).hexdigest()}  {name}\n"
            for name in sorted(self.names)))

    def snapshot(self):
        return {p.name: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
                for p in self.output.iterdir() if p.is_file() and not p.is_symlink()}

    def assert_rejected_without_writes(self):
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError)):
            PROVENANCE.record(self.output, identity())
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.output / "preview-provenance.json").exists())

    def test_records_receipt_and_hashes_without_changing_any_payload_bytes_or_modes(self):
        before = self.snapshot()
        PROVENANCE.record(self.output, identity())
        after = self.snapshot()
        self.assertEqual(set(after), set(before) | {"preview-provenance.json"})
        for name in self.names:
            self.assertEqual(after[name], before[name], name)
        receipt = json.loads((self.output / "preview-provenance.json").read_text())
        self.assertEqual(set(receipt), set(identity()) | {"payloads", "acceptance"})
        for key, value in identity().items():
            self.assertEqual(receipt[key], value)
        self.assertEqual(set(receipt["payloads"]), self.names)
        for name, payload in receipt["payloads"].items():
            self.assertEqual(payload, {"sha256": hashlib.sha256(before[name][0]).hexdigest(), "bytes": len(before[name][0])})
        self.assertIn("runtime acceptance remain separate", receipt["acceptance"])
        lines = self.checksums.read_text().splitlines()
        self.assertEqual(len(lines), 5)
        self.assertEqual([line[66:] for line in lines], sorted(self.names | {"preview-provenance.json"}))
        for line in lines:
            digest, name = line.split("  ")
            self.assertEqual(digest, hashlib.sha256((self.output / name).read_bytes()).hexdigest())

    def test_receipt_does_not_copy_unrelated_package_metadata(self):
        self.metadata["private_build_context"] = PRIVATE
        self.metadata_path.write_text(json.dumps(self.metadata))
        self.write_checksums()
        PROVENANCE.record(self.output, identity())
        self.assertNotIn(PRIVATE, (self.output / "preview-provenance.json").read_text())

    def test_rejects_tampering_in_each_payload_before_adding_receipt(self):
        for name in sorted(self.names):
            with self.subTest(name=name):
                path = self.output / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")  # Still valid JSON for the metadata case.
                self.assert_rejected_without_writes()
                path.write_bytes(original)

    def test_rejects_metadata_identity_and_release_claim_changes_even_with_new_hash(self):
        for field, invalid in [("source_commit", OTHER), ("repository", "fork/project"),
                               ("artifact_kind", "signed-ios-release"), ("app_store_release", True),
                               ("app_store_release", 0), ("real_purchases_configured", True),
                               ("real_purchases_configured", 0)]:
            with self.subTest(field=field, value=invalid):
                changed = dict(self.metadata, **{field: invalid})
                self.metadata_path.write_text(json.dumps(changed))
                self.write_checksums()
                self.assert_rejected_without_writes()

    def test_rejects_invalid_versions_and_non_candidate_channels(self):
        for field, values in [("base_version", [None, "v0.1.0", "01.0.0", "0.1.0-rc1", "../0.1.0"]),
                              ("channel", [None, "stable", "app-store", "../beta"])]:
            for value in values:
                with self.subTest(field=field, value=value):
                    self.metadata_path.write_text(json.dumps(dict(self.metadata, **{field: value})))
                    self.write_checksums()
                    self.assert_rejected_without_writes()

    def test_rejects_duplicate_incomplete_extra_and_malformed_checksum_entries(self):
        valid = self.checksums.read_text()
        lines = valid.splitlines(keepends=True)
        variants = {
            "duplicate": valid + lines[0], "missing": "".join(lines[1:]), "empty": "",
            "unknown": valid + "0" * 64 + "  unrelated.txt\n",
            "traversal": valid + "0" * 64 + "  ../outside\n",
            "bad-digest": "z" + valid[1:], "single-space": valid.replace("  ", " ", 1),
            "blank-line": valid + "\n",
        }
        for label, contents in variants.items():
            with self.subTest(label=label):
                self.checksums.write_text(contents)
                self.assert_rejected_without_writes()

    def test_rejects_missing_or_additional_payloads(self):
        for name in sorted(self.names | {"SHA256SUMS"}):
            with self.subTest(missing=name):
                path = self.output / name
                original = path.read_bytes()
                path.unlink()
                self.assert_rejected_without_writes()
                path.write_bytes(original)
        extra = self.output / "unrelated.txt"
        extra.write_text(PRIVATE)
        self.assert_rejected_without_writes()

    def test_never_overwrites_an_existing_receipt_or_rewrites_a_recorded_package(self):
        receipt = self.output / "preview-provenance.json"
        receipt.write_text(PRIVATE)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            PROVENANCE.record(self.output, identity())
        self.assertEqual(self.snapshot(), before)
        receipt.unlink()
        PROVENANCE.record(self.output, identity())
        before = self.snapshot()
        with self.assertRaises(ValueError):
            PROVENANCE.record(self.output, identity())
        self.assertEqual(self.snapshot(), before)

    def test_rejects_output_directory_symlink(self):
        link = self.root / "linked-output"
        link.symlink_to(self.output, target_is_directory=True)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            PROVENANCE.record(link, identity())
        self.assertEqual(self.snapshot(), before)

    def test_rejects_symlinks_in_every_payload_and_checksum_position(self):
        for name in sorted(self.names | {"SHA256SUMS"}):
            for dangling in [False, True]:
                with self.subTest(name=name, dangling=dangling):
                    path = self.output / name
                    data = path.read_bytes()
                    outside = self.root / "outside"
                    if not dangling:
                        outside.write_bytes(data)
                    path.unlink()
                    path.symlink_to(outside)
                    self.assert_rejected_without_writes()
                    path.unlink()
                    path.write_bytes(data)
                    if outside.exists():
                        outside.unlink()

    def test_rejects_non_regular_entries_and_missing_output(self):
        (self.output / "directory").mkdir()
        self.assert_rejected_without_writes()
        with self.assertRaises(ValueError):
            PROVENANCE.record(self.root / "missing-output", identity())


class PreviewCLITests(unittest.TestCase):
    def test_real_cli_redacts_missing_malformed_and_non_object_event_inputs(self):
        with tempfile.TemporaryDirectory(prefix=PRIVATE) as temporary:
            event_path = Path(temporary) / "event.json"
            env = dict(os.environ, GITHUB_EVENT_PATH=str(event_path), PRIVATE_TOKEN=PRIVATE)
            for contents in [None, '{"private":"' + PRIVATE, json.dumps([PRIVATE])]:
                with self.subTest(contents=contents):
                    if contents is not None:
                        event_path.write_text(contents)
                    result = subprocess.run([sys.executable, PROVENANCE.__file__, "check"],
                                            env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "Preview provenance validation failed\n")
                    self.assertNotIn(PRIVATE, result.stderr)

    def test_cli_redacts_git_failure_dirty_checkout_and_nested_event_errors(self):
        env, event = pr_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            event_path = Path(temporary) / "event.json"
            env["GITHUB_EVENT_PATH"] = str(event_path)
            variants = [
                (event, [PRIVATE]),
                (event, subprocess.CalledProcessError(1, ["git", PRIVATE], output=PRIVATE, stderr=PRIVATE)),
                (dict(event, pull_request=None), ["", HEAD, TREE]),
            ]
            for document, git_result in variants:
                with self.subTest(document=document, git_result=git_result):
                    event_path.write_text(json.dumps(document))
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["preview-provenance.py", "check"]), \
                         patch.object(PROVENANCE.subprocess, "check_output", side_effect=git_result), \
                         redirect_stdout(stdout), redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as error:
                            PROVENANCE.main()
                    self.assertEqual(str(error.exception), "Preview provenance validation failed")
                    self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")

    def test_cli_check_uses_clean_checkout_and_does_not_record(self):
        env, event = pr_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            event_path = Path(temporary) / "event.json"
            event_path.write_text(json.dumps(event))
            env["GITHUB_EVENT_PATH"] = str(event_path)
            stdout = io.StringIO()
            with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["preview-provenance.py", "check"]), \
                 patch.object(PROVENANCE.subprocess, "check_output", side_effect=["", HEAD, TREE]) as git, \
                 patch.object(PROVENANCE, "record") as record, redirect_stdout(stdout):
                PROVENANCE.main()
            record.assert_not_called()
            self.assertEqual([call.args[0] for call in git.call_args_list], [
                ["git", "status", "--porcelain", "--untracked-files=all"],
                ["git", "rev-parse", "HEAD"], ["git", "rev-parse", "HEAD^{tree}"],
            ])
            self.assertEqual(stdout.getvalue(), "Preview checkout provenance verified\n")

    def test_cli_record_passes_only_validated_context_and_redacts_filesystem_failure(self):
        env, event = pr_inputs()
        env["PRIVATE_TOKEN"] = PRIVATE
        event["private"] = PRIVATE
        with tempfile.TemporaryDirectory() as temporary:
            event_path = Path(temporary) / "event.json"
            event_path.write_text(json.dumps(event))
            env["GITHUB_EVENT_PATH"] = str(event_path)
            for failure in [None, OSError(PRIVATE)]:
                stdout = io.StringIO()
                with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["preview-provenance.py", "record"]), \
                     patch.object(PROVENANCE.subprocess, "check_output", side_effect=["", HEAD, TREE]), \
                     patch.object(PROVENANCE, "record", side_effect=failure) as record, redirect_stdout(stdout):
                    if failure:
                        with self.assertRaises(SystemExit) as error:
                            PROVENANCE.main()
                        self.assertEqual(str(error.exception), "Preview provenance validation failed")
                        self.assertEqual(stdout.getvalue(), "")
                    else:
                        PROVENANCE.main()
                        self.assertEqual(stdout.getvalue(), "Preview payload provenance recorded\n")
                record.assert_called_once_with(PROVENANCE.ROOT / "release-dist", identity())


class PreviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {
            path.name: yaml.load(path.read_text(), Loader=CONTRACTS.UniqueKeyLoader)  # nosec B506: BaseLoader only
            for path in (ROOT / ".github/workflows").glob("*.yml")
        }
        cls.ci = cls.workflows["ci.yml"]
        cls.release = cls.workflows["release-build.yml"]

    def test_preview_is_nested_under_ios_success_and_same_repository_pr_only(self):
        preview = self.ci["jobs"]["preview"]
        self.assertEqual(preview["needs"], "ios")
        self.assertEqual(preview["uses"], "./.github/workflows/release-build.yml")
        self.assertEqual(" ".join(preview["if"].split()),
                         "${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository }}")
        self.assertNotIn("continue-on-error", preview)
        self.assertEqual(preview["with"], {
            "version": "${{ needs.ios.outputs.version }}", "channel": "beta",
            "source-ref": "${{ github.event.pull_request.head.sha }}",
            "tested-commit": "${{ needs.ios.outputs.tested-commit }}",
            "tested-tree": "${{ needs.ios.outputs.tested-tree }}",
        })

    def test_reusable_workflows_add_no_independent_pr_or_privileged_trigger(self):
        for workflow in [self.ci, self.release]:
            self.assertEqual(set(workflow["on"]), {"workflow_call"})
        pr_entries = {name for name, workflow in self.workflows.items() if "pull_request" in workflow["on"]}
        self.assertEqual(pr_entries, {"quality-gate.yml"})
        for workflow in self.workflows.values():
            self.assertNotIn("pull_request_target", workflow["on"])

    def test_preview_permissions_are_read_only_and_no_secrets_are_forwarded(self):
        def inspect(node):
            if isinstance(node, dict):
                self.assertNotIn("secrets", node)
                for key, value in node.items():
                    if key == "permissions":
                        self.assertIsInstance(value, dict)
                        self.assertTrue(all(access == "read" for access in value.values()))
                    inspect(value)
            elif isinstance(node, list):
                for value in node:
                    inspect(value)
            elif isinstance(node, str):
                self.assertNotIn("secrets.", node)
                self.assertNotIn("secrets[", node)
        for workflow in [self.ci, self.release]:
            self.assertEqual(workflow["permissions"], {"contents": "read"})
            inspect(workflow)
            for job in workflow["jobs"].values():
                self.assertNotIn("environment", job)
                for step in job.get("steps", []):
                    if step.get("uses", "").startswith("actions/checkout@"):
                        self.assertEqual(step["with"]["persist-credentials"], "false")

    def test_tested_identity_outputs_are_produced_after_tests_without_failure_override(self):
        ios = self.ci["jobs"]["ios"]
        steps = ios["steps"]
        test_index = next(i for i, step in enumerate(steps) if step.get("run") == "bash scripts/ci.sh")
        output_index = next(i for i, step in enumerate(steps) if step.get("id") == "preview-version")
        self.assertGreater(output_index, test_index)
        self.assertNotIn("continue-on-error", ios)
        for step in [steps[test_index], steps[output_index]]:
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)
        self.assertEqual(ios["outputs"], {
            "version": "${{ steps.preview-version.outputs.version }}",
            "tested-commit": "${{ steps.preview-version.outputs.commit }}",
            "tested-tree": "${{ steps.preview-version.outputs.tree }}",
        })
        output_script = steps[output_index]["run"]
        self.assertIn('("commit", "HEAD"), ("tree", "HEAD^{tree}")', output_script)
        self.assertIn('os.environ["GITHUB_OUTPUT"]', output_script)
        self.assertIn('Path("VERSION")', output_script)

    def test_optional_pr_inputs_default_to_release_event_checkout(self):
        inputs = self.release["on"]["workflow_call"]["inputs"]
        for name in ["source-ref", "tested-commit", "tested-tree"]:
            self.assertEqual({key: inputs[name][key] for key in ["required", "type", "default"]},
                             {"required": "false", "type": "string", "default": ""})
        package = self.release["jobs"]["package"]
        self.assertEqual(package["env"], {
            "PREVIEW_SOURCE_REF": "${{ inputs.source-ref }}",
            "PREVIEW_TESTED_COMMIT": "${{ inputs.tested-commit }}",
            "PREVIEW_TESTED_TREE": "${{ inputs.tested-tree }}",
        })
        checkout = next(step for step in package["steps"] if step.get("uses", "").startswith("actions/checkout@"))
        self.assertEqual(checkout["with"]["ref"], "${{ inputs.source-ref }}")
        caller = self.workflows["release-pipeline.yml"]["jobs"]["build"]
        self.assertEqual(caller["uses"], "./.github/workflows/release-build.yml")
        self.assertEqual(set(caller["with"]), {"version", "channel"})

    def test_upload_follows_provenance_and_checksum_validation(self):
        steps = self.release["jobs"]["package"]["steps"]
        check = next(i for i, step in enumerate(steps) if step.get("run") == "python3 scripts/preview-provenance.py check")
        build = next(i for i, step in enumerate(steps) if "bash scripts/package-release.sh" in step.get("run", ""))
        record = next(i for i, step in enumerate(steps) if step.get("run") == "python3 scripts/preview-provenance.py record")
        verify = next(i for i, step in enumerate(steps) if step.get("run") == "shasum -a 256 -c SHA256SUMS")
        upload = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertEqual(sorted([check, build, record, verify, upload]), [check, build, record, verify, upload])
        for index in [check, build, record, verify, upload]:
            self.assertNotIn("if", steps[index])
            self.assertNotIn("continue-on-error", steps[index])
        self.assertEqual(steps[verify]["working-directory"], "release-dist")
        self.assertEqual(steps[upload]["with"]["path"], "release-dist/*")
        self.assertEqual(steps[upload]["with"]["if-no-files-found"], "error")
        for field in ["github.event.pull_request.number", "github.event.pull_request.head.sha", "github.run_attempt"]:
            self.assertIn(field, steps[upload]["with"]["name"])


if __name__ == "__main__":
    unittest.main()
