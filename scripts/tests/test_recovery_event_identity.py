"""Injected event/source identity regressions; no real processes or native tools."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from test_recovery_hosted import HostedCase, hosted


COMMIT, TREE, BASE, HEAD = (character * 40 for character in "abde")
SECRET = "PRIVATE_EVENT_OR_COMMIT_SENTINEL"


def commit_object(*, tree=TREE, parents=(BASE, HEAD), metadata=None, message=None):
    lines = ["tree " + tree] + ["parent " + parent for parent in parents]
    lines.extend(metadata if metadata is not None else [
        "author " + SECRET + " <private-author@example.invalid> 1 +0000",
        "committer " + SECRET + " <private-committer@example.invalid> 1 +0000",
        "gpgsig -----BEGIN SIGNATURE-----", " " + SECRET, " -----END SIGNATURE-----",
    ])
    return ("\n".join(lines) + "\n\n" + (message or SECRET + " private message\n")).encode()


class IdentityCase(HostedCase):
    def setUp(self):
        super().setUp()
        self.mock(hosted.subprocess, "run", side_effect=AssertionError("real subprocess.run forbidden"))
        self.mock(hosted.os, "system", side_effect=AssertionError("real shell forbidden"))
        self.env.update(GITHUB_EVENT_NAME="pull_request", GITHUB_REF="refs/pull/7/merge")
        self.env["GITHUB_WORKFLOW_REF"] = (
            self.env["GITHUB_REPOSITORY"] + "/.github/workflows/release-pipeline.yml@refs/pull/7/merge"
        )
        self.event = {
            "repository": {"full_name": self.env["GITHUB_REPOSITORY"], "default_branch": "main"},
            "number": 7,
            "pull_request": {
                "merge_commit_sha": COMMIT,
                "base": {"sha": BASE, "repo": {"full_name": self.env["GITHUB_REPOSITORY"]}},
                "head": {"sha": HEAD, "repo": {"full_name": "fork-owner/room-inventory-ios"}},
                "body": SECRET + " body",
            },
        }
        self.save_event()

    def assert_safe_audit(self, audit):
        value = audit.snapshot() if hasattr(audit, "snapshot") else audit
        self.assertIs(type(value["schema_version"]), int)
        self.assertEqual(value["schema_version"], 1)
        self.assertIsInstance(value["stage"], str)
        self.assertIsInstance(value["checks"], dict)
        self.assertTrue(all(isinstance(k, str) and type(v) is bool for k, v in value["checks"].items()))
        self.assertIsInstance(value["observed"], dict)
        raw = json.dumps(value).encode()
        self.assertLessEqual(len(raw), 8192)
        for forbidden in (SECRET, "private-author@example.invalid", "private-committer@example.invalid",
                          self.env["GH_TOKEN"]):
            self.assertNotIn(forbidden.encode(), raw)
        return value

    def rejected_event(self, event, env=None):
        audit = hosted.IdentityAudit()
        with self.assertRaises(hosted.Failure) as caught:
            hosted.validate_event(event, env or self.env, audit)
        snapshot = self.assert_safe_audit(audit)
        self.assertIn(False, snapshot["checks"].values())
        self.assertNotIn(SECRET, str(caught.exception))
        self.popen.assert_not_called()
        return snapshot

    def source_stub(self, raw=None):
        output = self.temp / "source-only"
        output.mkdir(exist_ok=True)
        values = {"source-head": (COMMIT + "\n" + TREE + "\n").encode(),
                  "source-status": b"", "source-commit": commit_object() if raw is None else raw}
        calls = []

        def command(args, name, cap=20, **kwargs):
            calls.append((name, args, cap, kwargs))
            value = values[name]
            if isinstance(value, BaseException):
                raise value
            return value

        return SimpleNamespace(output=output, check=Mock(), command=command, calls=calls, values=values)

    def fake_pr_execution(self, raw=None):
        self.fake_execution()
        self.command_values["source-commit"] = commit_object() if raw is None else raw
        self.identity_calls = []

        def command(instance, args, name, cap=20, **kwargs):
            self.calls.append((name, args, dict(instance.env)))
            self.identity_calls.append((name, args, kwargs))
            return self.command_values[name]

        hosted.Discovery.command.side_effect = command

    def assert_early_failure(self, result):
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIsNone(result["upload_root"])
        self.assertFalse(list(self.temp.iterdir()))
        self.popen.assert_not_called()
        self.assertFalse(self.calls)
        self.runner.execute.assert_not_called()
        self.package.assert_not_called()
        value = self.assert_safe_audit(result["identity_audit"])
        raw = json.dumps(result)
        self.assertNotIn(SECRET, raw)
        self.assertNotIn(self.env["GH_TOKEN"], raw)
        self.assertLessEqual(len(json.dumps(value).encode()), 8192)
        return value


class PullRequestEventTests(IdentityCase):
    def test_missing_null_current_and_stale_merge_sha_are_advisory(self):
        for state, value in (("missing", None), ("null", None), ("sha", COMMIT), ("sha", "f" * 40)):
            with self.subTest(state=state, value=value):
                event = deepcopy(self.event)
                if state == "missing":
                    event["pull_request"].pop("merge_commit_sha")
                else:
                    event["pull_request"]["merge_commit_sha"] = value
                audit = hosted.IdentityAudit()
                identity = hosted.validate_event(event, self.env, audit)
                self.assertEqual(identity["source_commit"], COMMIT)
                self.assertEqual(identity["merge_metadata_state"], state)
                self.assertEqual(identity["merge_metadata_matches_run"], value == COMMIT)
                self.assertEqual(identity["head"], {"sha": HEAD, "repository": "fork-owner/room-inventory-ios"})
                self.assert_safe_audit(audit)

    def test_base_and_head_may_belong_to_same_repository(self):
        self.event["pull_request"]["head"]["repo"] = deepcopy(self.event["repository"])
        identity = hosted.validate_event(self.event, self.env)
        self.assertEqual(identity["head"]["repository"], self.env["GITHUB_REPOSITORY"])

    def test_max_exact_integer_pr_number_is_accepted_with_canonical_ref(self):
        self.event["number"] = 2**53 - 1
        self.env["GITHUB_REF"] = "refs/pull/9007199254740991/merge"
        self.assertEqual(hosted.validate_event(self.event, self.env)["number"], 2**53 - 1)

    def test_invalid_pr_number_and_noncanonical_ref_fail(self):
        for number in (None, True, False, 0, -1, 7.0, "7", 2**53):
            with self.subTest(number=number):
                self.rejected_event({**self.event, "number": number})
        for ref in ("refs/pull/07/merge", "refs/pull/7/head", "refs/pull/8/merge",
                    "refs/heads/main", "refs/pull/7/merge\n", SECRET):
            with self.subTest(ref=ref):
                self.rejected_event(self.event, {**self.env, "GITHUB_REF": ref})

    def test_bad_merge_metadata_type_or_format_is_not_advisory(self):
        for value in (False, 0, 1, [], {}, "", "A" * 40, "a" * 39, "a" * 41, COMMIT + "\n", SECRET * 1000):
            with self.subTest(type=type(value).__name__, length=len(value) if isinstance(value, str) else None):
                event = deepcopy(self.event)
                event["pull_request"]["merge_commit_sha"] = value
                self.rejected_event(event)

    def test_missing_or_wrong_nested_object_types_fail_with_safe_diagnostics(self):
        paths = [("repository",), ("pull_request",), ("pull_request", "base"),
                 ("pull_request", "head"), ("pull_request", "base", "repo"),
                 ("pull_request", "head", "repo")]
        for path in paths:
            for value in (None, False, 4, [], SECRET, "missing"):
                with self.subTest(path=path, type=type(value).__name__, missing=value == "missing"):
                    event = deepcopy(self.event)
                    parent = event
                    for part in path[:-1]:
                        parent = parent[part]
                    if value == "missing":
                        parent.pop(path[-1])
                    else:
                        parent[path[-1]] = value
                    self.rejected_event(event)
        for event in (None, [], SECRET, 7, True):
            with self.subTest(event_type=type(event).__name__):
                self.rejected_event(event)

    def test_missing_malformed_and_mismatched_repository_names_fail(self):
        for path in (("repository",), ("pull_request", "base", "repo"), ("pull_request", "head", "repo")):
            for value in (None, False, 42, [], {}, "", "owner", "owner/repo/extra", "../repo", SECRET * 1000):
                with self.subTest(path=path, value_type=type(value).__name__):
                    event = deepcopy(self.event)
                    target = event
                    for part in path:
                        target = target[part]
                    target["full_name"] = value
                    self.rejected_event(event)
            event = deepcopy(self.event)
            target = event
            for part in path:
                target = target[part]
            target.pop("full_name")
            self.rejected_event(event)
        for path in (("repository",), ("pull_request", "base", "repo")):
            event = deepcopy(self.event)
            target = event
            for part in path:
                target = target[part]
            target["full_name"] = "different-owner/room-inventory-ios"
            self.rejected_event(event)

    def test_missing_or_malformed_base_and_head_sha_fail(self):
        for side in ("base", "head"):
            for value in (None, False, 42, [], {}, "", "A" * 40, "a" * 39, "a" * 41, HEAD + "\n", SECRET * 1000):
                with self.subTest(side=side, value_type=type(value).__name__):
                    event = deepcopy(self.event)
                    event["pull_request"][side]["sha"] = value
                    self.rejected_event(event)
            event = deepcopy(self.event)
            event["pull_request"][side].pop("sha")
            self.rejected_event(event)

    def test_large_arbitrary_event_fields_are_neither_retained_nor_mutated(self):
        self.event["pull_request"]["body"] = SECRET * 10000
        self.event["sender"] = {"email": "private-author@example.invalid", "token": self.env["GH_TOKEN"]}
        before_event, before_env = deepcopy(self.event), deepcopy(self.env)
        audit = hosted.IdentityAudit()
        identity = hosted.validate_event(self.event, self.env, audit)
        self.assert_safe_audit(audit)
        self.assertNotIn(SECRET, json.dumps(identity))
        self.assertNotIn("private-author@example.invalid", json.dumps(identity))
        self.assertEqual(self.event, before_event)
        self.assertEqual(self.env, before_env)


class CommitHeaderTests(IdentityCase):
    def parse(self, raw):
        audit = hosted.IdentityAudit()
        result = hosted.parse_commit_identity(raw, audit)
        self.assert_safe_audit(audit)
        return result

    def test_only_first_header_is_parsed_no_author_signature_or_message_retained(self):
        raw = commit_object(metadata=["author " + SECRET + " <private-author@example.invalid> 1 +0000",
                                     "gpgsig " + SECRET, " tree " + "f" * 40, " parent " + "f" * 40],
                            message="tree " + "f" * 40 + "\nparent " + "f" * 40 + "\n" + SECRET)
        self.assertEqual(self.parse(raw), {"tree": TREE, "parents": [BASE, HEAD]})

    def test_root_and_single_parent_objects_parse_before_pr_policy_check(self):
        for parents in ((), (BASE,)):
            with self.subTest(parents=parents):
                self.assertEqual(self.parse(commit_object(parents=parents)), {"tree": TREE, "parents": list(parents)})

    def test_missing_duplicate_or_malformed_tree_header_fails(self):
        for header in (b"", b"author someone", b"tree short", b"tree " + b"B" * 40,
                       b"tree " + TREE.encode() + b" ", b"tree " + TREE.encode() + b"\r",
                       ("tree " + TREE + "\ntree " + TREE).encode(),
                       ("author ignored\ntree " + TREE).encode()):
            with self.subTest(header=header[:55]), self.assertRaises(hosted.Failure):
                hosted.parse_commit_identity(header + b"\n\n" + SECRET.encode(), hosted.IdentityAudit())

    def test_malformed_parent_sha_and_more_than_two_parent_headers_fail(self):
        for raw in (commit_object(parents=("short", HEAD)), commit_object(parents=(BASE, "E" * 40)),
                    commit_object(parents=(BASE, HEAD + " ")), commit_object(parents=(BASE, HEAD, "f" * 40))):
            with self.subTest(raw_size=len(raw)), self.assertRaises(hosted.Failure):
                hosted.parse_commit_identity(raw, hosted.IdentityAudit())

    def test_header_and_total_byte_bounds_and_missing_separator(self):
        prefix = ("tree " + TREE + "\nparent " + BASE + "\nparent " + HEAD + "\nauthor ").encode()
        bounded_header = prefix + b"x" * (65536 - len(prefix))
        self.assertEqual(self.parse(bounded_header + b"\n\n"), {"tree": TREE, "parents": [BASE, HEAD]})
        for raw in (bounded_header + b"x\n\n", prefix, b"\n" + prefix):
            with self.subTest(size=len(raw)), self.assertRaises(hosted.Failure):
                hosted.parse_commit_identity(raw, hosted.IdentityAudit())
        raw = commit_object()
        at_cap = raw + b"x" * (4 * 1024 * 1024 - len(raw))
        self.assertEqual(self.parse(at_cap), {"tree": TREE, "parents": [BASE, HEAD]})
        with self.assertRaises(hosted.Failure):
            hosted.parse_commit_identity(at_cap + b"x", hosted.IdentityAudit())

    def test_nonbytes_commit_objects_fail_without_type_errors(self):
        for raw in (None, False, {}, [], "tree " + TREE, bytearray(commit_object())):
            with self.subTest(type=type(raw).__name__), self.assertRaises(hosted.Failure):
                hosted.parse_commit_identity(raw, hosted.IdentityAudit())


class SourceIdentityTests(IdentityCase):
    def test_shallow_merge_uses_only_raw_object_and_accepts_either_parent_order(self):
        for parents in ((BASE, HEAD), (HEAD, BASE)):
            with self.subTest(parents=parents):
                discovery = self.source_stub(commit_object(parents=parents))
                audit = hosted.IdentityAudit()
                event_identity = hosted.validate_event(self.event, self.env, audit)
                result = hosted.source_identity(discovery, self.env, event_identity, audit)
                self.assertEqual(result, [COMMIT, TREE])
                self.assertEqual([call[0] for call in discovery.calls], ["source-head", "source-status", "source-commit"])
                self.assertEqual(discovery.calls[-1], (
                    "source-commit", ["git", "--no-replace-objects", "cat-file", "commit", COMMIT], 10,
                    {"retain_output": False}))
                receipt = json.loads((discovery.output / "source-identity.json").read_text())
                self.assertEqual(receipt, {"tree": TREE, "parents": list(parents)})
                self.assertEqual(self.assert_safe_audit(audit)["stage"], "source_verified")
                self.assertEqual(discovery.check.call_count, 2)
        self.popen.assert_not_called()

    def test_missing_or_wrong_pr_event_identity_fails_before_raw_lookup(self):
        for identity in (None, [], {"kind": "push"}):
            with self.subTest(identity=identity):
                discovery = self.source_stub()
                with self.assertRaises(hosted.Failure):
                    hosted.source_identity(discovery, self.env, identity, hosted.IdentityAudit())
                self.assertEqual([c[0] for c in discovery.calls], ["source-head", "source-status"])

    def test_wrong_checkout_commit_tree_shape_or_dirty_source_fails_before_raw_lookup(self):
        cases = [("source-head", ("f" * 40 + "\n" + TREE + "\n").encode()),
                 ("source-head", (COMMIT + "\n" + "f" * 40 + "\n").encode()),
                 ("source-head", (COMMIT + "\n" + TREE + "\nextra\n").encode()),
                 ("source-head", b""), ("source-status", (" M " + SECRET).encode())]
        identity = hosted.validate_event(self.event, self.env)
        for key, value in cases:
            with self.subTest(key=key, value_size=len(value)):
                discovery = self.source_stub()
                discovery.values[key] = value
                audit = hosted.IdentityAudit()
                with self.assertRaises(hosted.Failure):
                    hosted.source_identity(discovery, self.env, identity, audit)
                self.assertNotIn("source-commit", [c[0] for c in discovery.calls])
                self.assertFalse((discovery.output / "source-identity.json").exists())
                self.assert_safe_audit(audit)

    def test_raw_tree_wrong_head_advanced_base_and_invalid_parent_count_fail(self):
        identity = hosted.validate_event(self.event, self.env)
        cases = [("raw-tree", commit_object(tree="f" * 40)),
                 ("wrong-head", commit_object(parents=(BASE, "f" * 40))),
                 ("advanced-base", commit_object(parents=("f" * 40, HEAD))),
                 ("root", commit_object(parents=())), ("single", commit_object(parents=(HEAD,))),
                 ("duplicate", commit_object(parents=(HEAD, HEAD))),
                 ("octopus", commit_object(parents=(BASE, HEAD, "f" * 40)))]
        for name, raw in cases:
            with self.subTest(name=name):
                discovery = self.source_stub(raw)
                audit = hosted.IdentityAudit()
                with self.assertRaises(hosted.Failure):
                    hosted.source_identity(discovery, self.env, identity, audit)
                self.assert_safe_audit(audit)
                self.assertFalse((discovery.output / "source-identity.json").exists())

    def test_parent_multiset_rejects_equal_event_sides_with_only_one_actual_occurrence(self):
        self.event["pull_request"]["base"]["sha"] = HEAD
        identity = hosted.validate_event(self.event, self.env)
        audit = hosted.IdentityAudit()
        with self.assertRaises(hosted.Failure):
            hosted.source_identity(self.source_stub(), self.env, identity, audit)
        checks = self.assert_safe_audit(audit)["checks"]
        self.assertTrue(checks["pr_head_is_parent"])
        self.assertTrue(checks["pr_base_is_parent"])
        self.assertFalse(checks["pr_snapshot_parents_match"])

    def test_push_does_not_query_raw_merge_parents(self):
        discovery = self.source_stub()
        env = {**self.env, "GITHUB_EVENT_NAME": "push"}
        self.assertEqual(hosted.source_identity(discovery, env), [COMMIT, TREE])
        self.assertEqual([c[0] for c in discovery.calls], ["source-head", "source-status"])


class AdapterIdentityEvidenceTests(IdentityCase):
    def test_full_injected_fork_run_accepts_null_advisory_and_retains_only_identity(self):
        self.event["pull_request"]["merge_commit_sha"] = None
        self.save_event()
        self.fake_pr_execution(commit_object(parents=(HEAD, BASE)))
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 0, result)
        self.assert_safe_audit(result["identity_audit"])
        self.runner.execute.assert_called_once()
        self.package.assert_called_once()
        preflight = self.temp / "room-recovery-work/preflight"
        self.assertEqual(json.loads((preflight / "source-identity.json").read_text()),
                         {"tree": TREE, "parents": [HEAD, BASE]})
        receipt = json.loads((preflight / "adapter-result.json").read_text())
        self.assertEqual(receipt["identity_audit"], result["identity_audit"])
        self.assertFalse((preflight / "source-commit.stdout").exists())
        self.assertFalse((preflight / "source-commit.stderr").exists())
        self.assertEqual(self.identity_calls[2][2], {"retain_output": False})
        for path in preflight.iterdir():
            if path.is_file():
                self.assertNotIn(SECRET.encode(), path.read_bytes(), str(path))
        self.popen.assert_not_called()

    def test_stale_advisory_does_not_override_actual_parent_mismatch(self):
        self.event["pull_request"]["merge_commit_sha"] = "f" * 40
        self.save_event()
        self.fake_pr_execution(commit_object(parents=(BASE, "f" * 40)))
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual([c[0] for c in self.calls], ["source-head", "source-status", "source-commit"])
        self.runner.execute.assert_not_called()
        self.assert_safe_audit(result["identity_audit"])
        self.assertFalse((self.temp / "room-recovery-work/hosted-grant-envelope.json").exists())

    def test_early_event_failure_logs_bounded_audit_without_creating_directories(self):
        self.event["pull_request"]["head"]["sha"] = SECRET * 10000
        self.event["pull_request"]["body"] = SECRET * 10000
        self.save_event()
        self.fake_pr_execution()
        original_run = hosted.run_hosted

        def run_injected(expected):
            return original_run(expected, root=self.root, env=self.env, clock=self.clock,
                                disk_usage=lambda _: SimpleNamespace(free=self.free))

        with patch.object(hosted, "run_hosted", side_effect=run_injected), \
                patch.object(hosted.controller, "emit_summary") as emit:
            self.assertEqual(hosted.main(["--profile-sha256", self.profile_sha]), 2)
        emit.assert_called_once()
        result = emit.call_args.args[0]
        audit = self.assert_early_failure(result)
        self.assertEqual(audit["stage"], "event")
        self.assertFalse(audit["checks"]["pr_head_sha"])
        self.assertLessEqual(len(json.dumps(result).encode()), 8192)

    def test_private_missing_event_filename_is_redacted_on_early_read_failure(self):
        self.fake_pr_execution()
        self.env["GITHUB_EVENT_PATH"] = str(self.base / (SECRET + ".json"))
        audit = self.assert_early_failure(self.run_adapter())
        self.assertEqual(audit["stage"], "event_read")
        self.assertFalse(audit["checks"]["event_file_readable"])

    def test_symlink_directory_and_oversized_event_file_fail_without_paths(self):
        self.fake_pr_execution()
        ordinary = Path(self.env["GITHUB_EVENT_PATH"])
        link = self.base / (SECRET + "-link.json")
        link.symlink_to(ordinary)
        directory = self.base / (SECRET + "-directory")
        directory.mkdir()
        oversized = self.base / (SECRET + "-oversized.json")
        with oversized.open("wb") as stream:
            stream.truncate(4 * 1024 * 1024 + 1)
        for path in (link, directory, oversized):
            with self.subTest(kind=path.suffix):
                self.env["GITHUB_EVENT_PATH"] = str(path)
                audit = self.assert_early_failure(self.run_adapter())
                self.assertFalse(audit["checks"]["event_file_bounded_regular"])

    def test_malformed_json_utf8_and_deep_nesting_have_safe_early_evidence(self):
        self.fake_pr_execution()
        path = self.base / (SECRET + "-bad.json")
        self.env["GITHUB_EVENT_PATH"] = str(path)
        for raw in (b'{"body":"' + SECRET.encode(), b'"\xff' + SECRET.encode() + b'"',
                    b"[" * 3000 + b"0" + b"]" * 3000):
            with self.subTest(size=len(raw)):
                path.write_bytes(raw)
                audit = self.assert_early_failure(self.run_adapter())
                # Python versions differ in their JSON nesting limit. An array
                # must fail either parsing or the mandatory event-object check.
                failure = "event_object" if raw.startswith(b"[") and audit["checks"]["event_json"] else "event_json"
                self.assertFalse(audit["checks"][failure])


class PrivateCommitCommandTests(IdentityCase):
    def injected_command(self, *, exit_code=0, cleanup=True, overflow=False):
        output = self.temp / "command-evidence"
        output.mkdir()
        discovery = hosted.Discovery(self.root, output, {}, hosted.Alarm(self.clock() + 120, self.clock),
                                     disk_usage=lambda _: SimpleNamespace(free=self.free))
        stdout, stderr = Mock(), Mock()
        stdout.fileno.return_value, stderr.fileno.return_value = 10, 11
        process = SimpleNamespace(pid=12345, stdout=stdout, stderr=stderr,
                                  poll=Mock(return_value=exit_code), wait=Mock(return_value=exit_code))
        # Replace the deny mock with an in-memory process object, never a real spawn.
        self.popen.side_effect = None
        self.popen.return_value = process
        selector = Mock()
        selector.get_map.side_effect = [{10: True, 11: True}, {}]
        events = [(SimpleNamespace(fileobj=stdout, data=0), None),
                  (SimpleNamespace(fileobj=stderr, data=1), None)]
        raw, error_raw = commit_object(), (SECRET + " stderr").encode()
        chunks = [raw, error_raw]
        if overflow:
            events.append((SimpleNamespace(fileobj=stdout, data=0), None))
            chunks.append(b"x" * (4 * 1024 * 1024))
        selector.select.return_value = events
        self.mock(hosted.selectors, "DefaultSelector", return_value=selector)
        self.mock(hosted.os, "set_blocking")
        self.mock(hosted.os, "read", side_effect=chunks)
        killer = self.mock(hosted.controller, "kill_owned", return_value={"success": cleanup})
        return discovery, raw, error_raw, killer

    def assert_private_receipt(self, discovery, raw, stderr):
        self.assertEqual({p.name for p in discovery.output.iterdir()}, {"commands.json"})
        receipt_raw = (discovery.output / "commands.json").read_bytes()
        for forbidden in (SECRET.encode(), b"private-author@example.invalid", b"private-committer@example.invalid",
                          hosted.controller.sha(raw).encode(), hosted.controller.sha(stderr).encode()):
            self.assertNotIn(forbidden, receipt_raw)
        receipt = json.loads(receipt_raw)[0]
        self.assertIs(receipt["output_retained"], False)
        self.assertEqual(receipt["stdout_bytes"], len(raw))
        self.assertEqual(receipt["stderr_bytes"], len(stderr))
        self.assertNotIn("stdout_sha256", receipt)
        self.assertNotIn("stderr_sha256", receipt)
        return receipt

    def test_raw_stdout_and_stderr_are_suppressed_on_success(self):
        discovery, raw, stderr, killer = self.injected_command()
        self.assertEqual(discovery.command(["git", "--no-replace-objects", "cat-file", "commit", COMMIT],
                                           "source-commit", 10, retain_output=False), raw)
        receipt = self.assert_private_receipt(discovery, raw, stderr)
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIsNone(receipt["primary_error"])
        self.assertTrue(receipt["cleanup"]["success"])
        killer.assert_called_once()

    def test_nonzero_exit_and_cleanup_failure_preserve_primary_without_raw_output(self):
        discovery, raw, stderr, killer = self.injected_command(exit_code=7, cleanup=False)
        with self.assertRaisesRegex(hosted.controller.RunFailure, "Discovery command failed"):
            discovery.command(["git", "--no-replace-objects", "cat-file", "commit", COMMIT],
                              "source-commit", 10, retain_output=False)
        receipt = self.assert_private_receipt(discovery, raw, stderr)
        self.assertEqual(receipt["exit_code"], 7)
        self.assertIn("Discovery command failed", receipt["primary_error"]["message"])
        self.assertFalse(receipt["cleanup"]["success"])
        self.assertEqual(discovery.cleanup_errors[0]["operation"], "owned_group")
        killer.assert_called_once()

    def test_cleanup_failure_alone_cannot_succeed_or_retain_raw_output(self):
        discovery, raw, stderr, killer = self.injected_command(cleanup=False)
        with self.assertRaisesRegex(hosted.controller.RunFailure, "cleanup/receipt incomplete"):
            discovery.command(["git", "--no-replace-objects", "cat-file", "commit", COMMIT],
                              "source-commit", 10, retain_output=False)
        receipt = self.assert_private_receipt(discovery, raw, stderr)
        self.assertEqual(receipt["exit_code"], 0)
        self.assertFalse(receipt["cleanup"]["success"])
        self.assertTrue(discovery.cleanup_errors)
        killer.assert_called_once()

    def test_stream_overflow_keeps_only_admitted_byte_counts_and_failure_evidence(self):
        discovery, raw, stderr, killer = self.injected_command(overflow=True)
        with self.assertRaisesRegex(hosted.controller.RunFailure, "stream cap"):
            discovery.command(["git", "--no-replace-objects", "cat-file", "commit", COMMIT],
                              "source-commit", 10, retain_output=False)
        receipt = self.assert_private_receipt(discovery, raw, stderr)
        self.assertIsNone(receipt["exit_code"])
        self.assertIn("stream cap", receipt["primary_error"]["message"])
        self.assertTrue(receipt["cleanup"]["success"])
        killer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
