"""Injected hosted adapter boundaries. No subprocesses, signals or native tools."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("recovery_hosted_under_test", SCRIPTS / "recovery_hosted.py")
hosted = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hosted)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class HostedCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="recovery-hosted-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root, self.temp = self.base / "checkout", self.base / "runner-temp"
        self.root.mkdir()
        self.temp.mkdir()
        (self.root / "scripts").mkdir()
        (self.root / ".github/workflows").mkdir(parents=True)
        self.profile_raw = json.dumps(hosted.POLICY).encode()
        self.profile_sha = hosted.controller.sha(self.profile_raw)
        (self.root / hosted.PROFILE_PATH).write_bytes(self.profile_raw)
        (self.root / ".github/workflows/ci.yml").write_text("name: source fixture\n")
        for filename in ("run-recovery-journey.py", "recovery_collector.py", "recovery_hosted.py", "recovery_retention.py", "install-xcodegen.py"):
            (self.root / "scripts" / filename).write_text("# injected fixture only\n")
        self.developer = self.base / "Xcode.app/Contents/Developer"
        self.developer.mkdir(parents=True)
        self.xcodegen = self.root / ".build/tools/xcodegen-2.46.0/xcodegen/bin/xcodegen"
        self.xcodegen.parent.mkdir(parents=True)
        self.xcodegen.write_text("injected fixture, never executed")
        self.xcodegen.chmod(0o755)
        self.env = {"GITHUB_ACTIONS": "true", "CI": "true", "RUNNER_ENVIRONMENT": "github-hosted",
                    "RUNNER_OS": "macOS", "ImageOS": "macos15", "ImageVersion": "20261020.1",
                    "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "4alvit/room-inventory-ios",
                    "GITHUB_JOB": "recovery", "RUNNER_ARCH": "ARM64", "GITHUB_SHA": "a" * 40,
                    "GITHUB_WORKFLOW_SHA": "c" * 40, "RECOVERY_TESTED_COMMIT": "a" * 40,
                    "RECOVERY_TESTED_TREE": "b" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main",
                    "GITHUB_WORKSPACE": str(self.root), "RUNNER_TEMP": str(self.temp),
                    "GITHUB_WORKFLOW_REF": "4alvit/room-inventory-ios/.github/workflows/release-pipeline.yml@refs/heads/main",
                    "GITHUB_EVENT_PATH": str(self.base / "event.json"), "PATH": "/usr/bin:/bin",
                    "HOME": str(self.base), "GH_TOKEN": "must-never-be-retained"}
        self.event = {"repository": {"full_name": self.env["GITHUB_REPOSITORY"], "default_branch": "main"},
                      "after": "a" * 40, "ref": "refs/heads/main"}
        self.save_event()
        self.clock = Clock()
        self.free = 24 * hosted.controller.GIB
        self.popen = self.mock(hosted.subprocess, "Popen", side_effect=AssertionError("real subprocess forbidden"))
        self.mock(hosted.os, "killpg", side_effect=AssertionError("real process signal forbidden"))
        self.mock(hosted.platform, "system", return_value="Darwin")
        self.mock(hosted.platform, "machine", return_value="arm64")
        self.timer = self.mock(hosted.signal, "getitimer", return_value=(0.0, 0.0))
        self.previous_handler = object()
        self.mock(hosted.signal, "getsignal", return_value=self.previous_handler)
        self.handlers = self.mock(hosted.signal, "signal")
        self.timers = self.mock(hosted.signal, "setitimer")
        self.mock(hosted.signal, "pthread_sigmask", return_value=set())

    def mock(self, owner, name, **kwargs):
        p = patch.object(owner, name, **kwargs)
        result = p.start()
        self.addCleanup(p.stop)
        return result

    def save_event(self):
        Path(self.env["GITHUB_EVENT_PATH"]).write_text(json.dumps(self.event))

    def inventory(self):
        return {"runtimes": [{"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-1", "version": "26.1", "isAvailable": True}],
                "devicetypes": [{"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "minRuntimeVersion": 26 << 16, "maxRuntimeVersion": 0xffffffff}],
                "devices": {}}

    def run_adapter(self):
        return hosted.run_hosted(self.profile_sha, root=self.root, env=self.env, clock=self.clock,
                                 disk_usage=lambda _: SimpleNamespace(free=self.free))

    def fake_execution(self, *, code=0, primary=None, cleanup=None, complete=True):
        self.calls = []
        values = {"source-head": ("a" * 40 + "\n" + "b" * 40 + "\n").encode(), "source-status": b"",
                  "xcode-select": str(self.developer).encode(), "xcode-version": b"Xcode 26.1\nBuild version 17B55",
                  "sdk-version": b"26.1\n", "simulator-inventory": json.dumps(self.inventory()).encode(),
                  "install-xcodegen": str(self.xcodegen).encode()}
        self.command_values = values

        def command(instance, args, name, cap=20):
            self.calls.append((name, args, dict(instance.env)))
            return values[name]
        self.mock(hosted.Discovery, "command", autospec=True, side_effect=command)
        self.runner = SimpleNamespace(record={"exit_code": code, "primary_error": primary, "cleanup_errors": cleanup or []},
                                      collector=object(), execute=Mock(return_value=code))
        self.runner_class = self.mock(hosted, "HostedRecoveryRun", return_value=self.runner)
        self.package = Mock(return_value={"status": "COMPLETE" if complete else "PARTIAL", "complete": complete, "failures": []})
        self.capture = Mock()
        replacement = SimpleNamespace(package_evidence=self.package, capture_build_identity=self.capture)
        p = patch.dict(sys.modules, {"recovery_retention": replacement})
        p.start()
        self.addCleanup(p.stop)


class ContextTests(HostedCase):
    def test_local_rejected_without_commands_or_output(self):
        self.env.clear()
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(list(self.temp.iterdir()))
        self.popen.assert_not_called()

    def test_self_hosted_and_wrong_class_rejected(self):
        for key, value in (("RUNNER_ENVIRONMENT", "self-hosted"), ("ImageOS", "macos14"), ("GITHUB_JOB", "ios"),
                           ("GITHUB_SERVER_URL", "https://enterprise.invalid"), ("RUNNER_ARCH", "X64")):
            with self.subTest(key=key), self.assertRaises(hosted.Failure):
                hosted.validate_host({**self.env, key: value}, hosted.POLICY, self.root)

    def test_intel_and_arm_same_image_os_supported(self):
        for arch, machine in (("ARM64", "arm64"), ("X64", "x86_64")):
            value = hosted.validate_host({**self.env, "RUNNER_ARCH": arch}, hosted.POLICY, self.root, machine=machine)
            self.assertEqual(value["runner_arch"], arch)
            self.assertEqual(value["image_os"], "macos15")

    def test_image_version_is_required_bounded_and_retained_exactly(self):
        for value in (None, "", " ", "a" * 129, "20261020.1\ninjected"):
            env = {**self.env, "ImageVersion": value}
            with self.subTest(value=value), self.assertRaises(hosted.Failure):
                hosted.validate_host(env, hosted.POLICY, self.root)
        self.assertEqual(hosted.validate_host(self.env, hosted.POLICY, self.root)["image_version"], self.env["ImageVersion"])

    def test_prior_ios_source_mismatch_and_missing_pin_rejected(self):
        for key, value in (("RECOVERY_TESTED_COMMIT", "d" * 40), ("RECOVERY_TESTED_TREE", "")):
            with self.subTest(key=key), self.assertRaises(hosted.Failure):
                hosted.validate_host({**self.env, key: value}, hosted.POLICY, self.root)

    def test_caller_sha_distinct_from_merge_head_is_bound(self):
        identity = hosted.validate_host(self.env, hosted.POLICY, self.root)
        self.assertEqual(identity["workflow_sha"], "c" * 40)
        self.assertNotIn("GH_TOKEN", identity)

    def test_unapproved_caller_or_wrong_ref_rejected(self):
        for value in ("4alvit/room-inventory-ios/.github/workflows/ci.yml@refs/heads/main",
                      "other/repo/.github/workflows/quality-gate.yml@refs/heads/main",
                      "4alvit/room-inventory-ios/.github/workflows/quality-gate.yml@refs/heads/other"):
            with self.subTest(value=value), self.assertRaises(hosted.Failure):
                hosted.validate_host({**self.env, "GITHUB_WORKFLOW_REF": value}, hosted.POLICY, self.root)

    def test_profile_hash_policy_and_json_types_are_enforced(self):
        for profile, digest in ((hosted.POLICY, "0" * 64), ({**hosted.POLICY, "schema_version": True}, None),
                                ({**hosted.POLICY, "admission_free_bytes": 1}, None)):
            raw = json.dumps(profile).encode()
            (self.root / hosted.PROFILE_PATH).write_bytes(raw)
            with self.subTest(profile=profile), self.assertRaises(hosted.Failure):
                hosted.load_profile(self.root, digest or hosted.controller.sha(raw))

    def test_all_five_events_bind_event_identity(self):
        cases = [("push", "refs/heads/main", self.event),
                 ("schedule", "refs/heads/main", {"repository": self.event["repository"]}),
                 ("workflow_dispatch", "refs/heads/main", {"repository": self.event["repository"], "inputs": {"expected_sha": "a" * 40}}),
                 ("merge_group", "refs/heads/gh-readonly-queue/main/pr-7", {"repository": self.event["repository"],
                    "merge_group": {"head_sha": "a" * 40, "head_ref": "refs/heads/gh-readonly-queue/main/pr-7", "base_ref": "refs/heads/main"}}),
                 ("pull_request", "refs/pull/7/merge", {"repository": self.event["repository"], "number": 7,
                    "pull_request": {"merge_commit_sha": "a" * 40, "base": {"sha": "b" * 40, "repo": self.event["repository"]},
                                     "head": {"sha": "c" * 40, "repo": {"full_name": "fork-owner/room-inventory-ios"}}}})]
        for kind, ref, event in cases:
            with self.subTest(kind=kind):
                result = hosted.validate_event(event, {**self.env, "GITHUB_EVENT_NAME": kind, "GITHUB_REF": ref})
                self.assertEqual(result["kind"], kind)
                if kind == "pull_request":
                    self.assertEqual(result["head"]["repository"], "fork-owner/room-inventory-ios")

    def test_event_mismatches_fail_closed(self):
        for kind, ref, event in (
            ("push", "refs/heads/main", {**self.event, "after": "d" * 40}),
            ("push", "refs/heads/main", {**self.event, "repository": {"full_name": "wrong/repo"}}),
            ("workflow_dispatch", "refs/heads/main", {"repository": self.event["repository"], "inputs": {"expected_sha": "d" * 40}}),
            ("schedule", "refs/heads/other", {"repository": self.event["repository"]}),
            ("pull_request", "refs/pull/7/merge", {"repository": self.event["repository"], "number": 7, "pull_request": {"merge_commit_sha": "d" * 40}}),
            ("merge_group", "refs/heads/gh-readonly-queue/main/pr-7", {"repository": self.event["repository"], "merge_group": {"head_sha": "d" * 40}})):
            with self.subTest(kind=kind), self.assertRaises(hosted.Failure):
                hosted.validate_event(event, {**self.env, "GITHUB_EVENT_NAME": kind, "GITHUB_REF": ref})


class SelectionTests(HostedCase):
    def test_same_major_minor_selects_highest_available_patch_only(self):
        inventory = self.inventory()
        for ver, available in (("26.1.1", True), ("26.1.9", False), ("26.2", True)):
            inventory["runtimes"].append({"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-" + ver.replace(".", "-"),
                                          "version": ver, "isAvailable": available})
        self.assertEqual(hosted.select_runtime(inventory, "26.1")["runtime_version"], "26.1.1")
        with self.assertRaises(hosted.Failure):
            hosted.select_runtime(inventory, "27.0")

    def test_type_requires_compatibility_evidence_and_iphone(self):
        inventory = self.inventory()
        device = inventory["devicetypes"][0]
        device.pop("minRuntimeVersion")
        device.pop("maxRuntimeVersion")
        with self.assertRaises(hosted.Failure):
            hosted.select_runtime(inventory, "26.1")
        runtime = inventory["runtimes"][0]
        runtime["supportedDeviceTypes"] = [{"identifier": device["identifier"]}]
        self.assertEqual(hosted.select_runtime(inventory, "26.1")["device_type"], device["identifier"])
        device["identifier"] = "com.apple.CoreSimulator.SimDeviceType.iPad-Pro"
        with self.assertRaises(hosted.Failure):
            hosted.select_runtime(inventory, "26.1")

    def test_available_existing_device_is_compatibility_evidence(self):
        inventory = self.inventory()
        device = inventory["devicetypes"][0]
        device.pop("minRuntimeVersion")
        device.pop("maxRuntimeVersion")
        inventory["devices"][inventory["runtimes"][0]["identifier"]] = [{"deviceTypeIdentifier": device["identifier"], "isAvailable": True}]
        self.assertEqual(hosted.select_runtime(inventory, "26.1")["device_type"], device["identifier"])


class IntegrationTests(HostedCase):
    def test_full_injected_path_validates_grant_and_packages_bound_source(self):
        self.fake_execution()
        validator = self.mock(hosted.controller, "validate_grant", wraps=hosted.controller.validate_grant)
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(validator.call_count, 2)
        self.assertEqual([name for name, _, _ in self.calls], ["source-head", "source-status", "xcode-select", "xcode-version", "sdk-version", "simulator-inventory", "install-xcodegen"])
        self.assertEqual(sum(name == "simulator-inventory" for name, _, _ in self.calls), 1)
        self.assertTrue(all("GH_TOKEN" not in env for _, _, env in self.calls))
        work = self.temp / "room-recovery-work"
        envelope = json.loads((work / "hosted-grant-envelope.json").read_text())
        self.assertEqual(envelope["source_tree"], "b" * 40)
        self.assertEqual(envelope["profile_sha256"], self.profile_sha)
        self.assertEqual(set(envelope["tool_hashes"]), {"controller", "collector", "adapter", "retention", "xcodegen_installer", "xcodegen"})
        self.assertNotIn("must-never-be-retained", (work / "hosted-grant-envelope.json").read_text())
        self.assertEqual((work / "preflight/recovery-hosted-profile.json").read_bytes(), self.profile_raw)
        self.assertEqual(self.package.call_args.kwargs["collector"], self.runner.collector)
        self.assertEqual(self.package.call_args.args[2]["controller_exit_code"], 0)
        self.assertEqual(self.handlers.call_args.args, (hosted.signal.SIGALRM, self.previous_handler))

    def test_existing_output_is_preserved_and_no_commands(self):
        self.fake_execution()
        existing = self.temp / "room-recovery-upload"
        existing.mkdir()
        (existing / "sentinel").write_text("preserve")
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual((existing / "sentinel").read_text(), "preserve")
        self.assertFalse(self.calls)
        self.package.assert_not_called()

    def test_below_admission_never_calls_native(self):
        self.fake_execution()
        self.free -= 1
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse(self.calls)
        self.assertFalse(list(self.temp.iterdir()))

    def test_source_tree_mismatch_rejects_before_native_and_retains_partial(self):
        self.fake_execution()
        self.command_values["source-head"] = ("a" * 40 + "\n" + "f" * 40 + "\n").encode()
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual([name for name, _, _ in self.calls], ["source-head"])
        self.runner.execute.assert_not_called()
        self.package.assert_called_once()
        self.assertFalse((self.temp / "room-recovery-work/hosted-grant-envelope.json").exists())

    def test_dirty_checkout_and_wrong_developer_reject(self):
        self.fake_execution()
        self.command_values["source-status"] = b" M scripts/recovery_hosted.py\n"
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(len(self.calls), 2)
        self.runner.execute.assert_not_called()

    def test_developer_env_mismatch_prevents_build_and_installer(self):
        self.fake_execution()
        self.env["DEVELOPER_DIR"] = "/different/Developer"
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(self.calls[-1][0], "xcode-select")
        self.runner.execute.assert_not_called()

    def test_missing_matching_runtime_does_not_install_or_retry(self):
        self.fake_execution()
        self.command_values["sdk-version"] = b"27.0"
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(self.calls[-1][0], "simulator-inventory")
        self.assertEqual(sum(name == "simulator-inventory" for name, _, _ in self.calls), 1)
        self.runner.execute.assert_not_called()

    def test_controller_failure_and_cleanup_remain_primary_if_retention_fails(self):
        self.fake_execution(code=124, primary={"message": "original deadline"}, cleanup=[{"error": "shutdown uncertain"}])
        self.package.side_effect = ValueError("archive failed")
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual(result["primary_error"]["message"], "original deadline")
        self.assertEqual(self.package.call_args.args[2]["cleanup_errors"], [{"error": "shutdown uncertain"}])

    def test_cleanup_error_cannot_return_success(self):
        self.fake_execution(cleanup=[{"error": "uncertain"}])
        self.assertNotEqual(self.run_adapter()["exit_code"], 0)

    def test_partial_retention_cannot_return_success(self):
        self.fake_execution(complete=False)
        self.assertEqual(self.run_adapter()["exit_code"], 1)

    def test_retention_crossing_absolute_outer_deadline_fails(self):
        self.fake_execution()
        def package(*args, **kwargs):
            self.clock.advance(2101)
            args[3]()
        self.package.side_effect = package
        self.assertEqual(self.run_adapter()["exit_code"], 124)

    def test_retention_phase_cannot_borrow_unused_controller_time(self):
        self.fake_execution()
        def package(*args, **kwargs):
            self.clock.advance(181)
            args[3]()
        self.package.side_effect = package
        self.assertEqual(self.run_adapter()["exit_code"], 124)

    def test_disk_drop_after_controller_prevents_retention_writes(self):
        self.fake_execution()
        def execute():
            self.free = 8 * hosted.controller.GIB - 1
            return 0
        self.runner.execute.side_effect = execute
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Retention disk abort", result["primary_error"]["message"])
        self.package.assert_not_called()
        self.assertFalse((self.temp / "room-recovery-work/preflight/adapter-result.json").exists())

    def test_disk_drop_inside_packaging_aborts_via_injected_guard(self):
        self.fake_execution()
        def package(*args, **kwargs):
            args[3]()
            self.free = 8 * hosted.controller.GIB - 1
            args[3]()
            self.fail("guard must stop further copying")
        self.package.side_effect = package
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Retention disk abort", result["primary_error"]["message"])

    def test_retention_at_exact_disk_floor_is_allowed(self):
        self.fake_execution()
        def execute():
            self.free = 8 * hosted.controller.GIB
            return 0
        self.runner.execute.side_effect = execute
        self.assertEqual(self.run_adapter()["exit_code"], 0)
        self.package.assert_called_once()

    def test_active_external_timer_rejected_without_replacing_it(self):
        self.timer.return_value = (10.0, 0.0)
        result = self.run_adapter()
        self.assertEqual(result["exit_code"], 2)
        self.timers.assert_not_called()
        self.handlers.assert_not_called()
        self.popen.assert_not_called()

    def test_build_hook_snapshots_only_after_base_build(self):
        captured = Mock()
        p = patch.dict(sys.modules, {"recovery_retention": SimpleNamespace(capture_build_identity=captured)})
        with p, patch.object(hosted.controller.RecoveryRun, "build") as build:
            runner = object.__new__(hosted.HostedRecoveryRun)
            runner.output = self.temp / "room-recovery-work/run"
            runner.guard = Mock()
            hosted.HostedRecoveryRun.build(runner)
            build.assert_called_once()
            captured.assert_called_once_with(runner, runner.output.parent / "build-identity", runner.guard)
            build.side_effect = RuntimeError("build failed")
            with self.assertRaises(RuntimeError):
                hosted.HostedRecoveryRun.build(runner)
            self.assertEqual(captured.call_count, 1)


class CommandTests(HostedCase):
    def discovery(self):
        output = self.temp / "preflight"
        output.mkdir()
        return hosted.Discovery(self.root, output, {}, hosted.Alarm(self.clock() + 120, self.clock),
                                disk_usage=lambda _: SimpleNamespace(free=self.free))

    def fake_process(self):
        self.process = SimpleNamespace(pid=12345, stdout=Mock(), stderr=Mock(), poll=Mock(return_value=0), wait=Mock(return_value=0))
        self.popen.side_effect = None
        self.popen.return_value = self.process
        self.selector = Mock()
        self.selector.get_map.return_value = {}
        self.mock(hosted.selectors, "DefaultSelector", return_value=self.selector)
        self.mock(hosted.os, "set_blocking")
        self.cleanup = self.mock(hosted.controller, "kill_owned", return_value={"success": True})

    def test_no_popen_when_insufficient_time_or_disk(self):
        discovery = self.discovery()
        with self.assertRaises(hosted.Deadline):
            discovery.command(["fake"], "short", cap=7)
        self.free = 8 * hosted.controller.GIB - 1
        with self.assertRaises(hosted.controller.RunFailure):
            discovery.command(["fake"], "lowdisk")
        self.popen.assert_not_called()

    def test_exact_abort_floor_allowed_and_owned_group_reaped(self):
        discovery = self.discovery()
        self.fake_process()
        self.free = 8 * hosted.controller.GIB
        self.assertEqual(discovery.command(["fake"], "okay", cap=10), b"")
        self.cleanup.assert_called_once()
        self.assertTrue(self.popen.call_args.kwargs["start_new_session"])
        self.assertEqual(self.cleanup.call_args.args[1], 110.0)

    def test_slow_guard_cannot_spawn_after_command_deadline(self):
        discovery = self.discovery()
        calls = 0
        def slow_guard():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.clock.advance(7)
        discovery.check = slow_guard
        with self.assertRaises(hosted.Deadline):
            discovery.command(["fake"], "slowguard", cap=10)
        self.popen.assert_not_called()

    def test_popen_failure_is_recorded_and_no_unowned_cleanup(self):
        discovery = self.discovery()
        self.fake_process()
        self.popen.side_effect = OSError("injected spawn failed")
        with self.assertRaisesRegex(OSError, "spawn failed"):
            discovery.command(["fake"], "spawn")
        self.cleanup.assert_not_called()
        self.assertEqual(discovery.records[0]["primary_error"]["type"], "OSError")

    def test_cleanup_failure_keeps_original_exit_failure(self):
        discovery = self.discovery()
        self.fake_process()
        self.process.wait.return_value = 7
        self.cleanup.return_value = {"success": False}
        with self.assertRaisesRegex(hosted.controller.RunFailure, "command failed"):
            discovery.command(["fake"], "failed")
        self.assertEqual(discovery.records[0]["exit_code"], 7)
        self.assertEqual(discovery.cleanup_errors[0]["operation"], "owned_group")

    def test_cleanup_consuming_deadline_skips_subsequent_closes(self):
        discovery = self.discovery()
        self.fake_process()
        def cleanup(*args, **kwargs):
            self.clock.advance(10)
            return {"success": True}
        self.cleanup.side_effect = cleanup
        with self.assertRaises(hosted.controller.RunFailure):
            discovery.command(["fake"], "cleanup", cap=10)
        self.selector.close.assert_not_called()
        self.process.stdout.close.assert_not_called()

    def test_receipt_crossing_discovery_deadline_fails(self):
        discovery = self.discovery()
        self.fake_process()
        def write(*args):
            self.clock.advance(121)
        self.mock(hosted.controller, "write_json", side_effect=write)
        with self.assertRaises(hosted.Deadline):
            discovery.command(["fake"], "receipt")
        self.assertEqual(discovery.cleanup_errors[-1]["operation"], "receipt")

    def test_output_cap_stops_drain_and_cleans_group(self):
        discovery = self.discovery()
        self.fake_process()
        self.selector.get_map.return_value = {"pipe": True}
        self.selector.select.return_value = [(SimpleNamespace(fileobj=self.process.stdout, data=0), None)]
        self.mock(hosted.os, "read", return_value=b"x" * (4 * hosted.controller.MIB + 1))
        with self.assertRaisesRegex(hosted.controller.RunFailure, "stream cap"):
            discovery.command(["fake"], "overflow")
        self.cleanup.assert_called_once()

    def test_alarm_restores_handler_on_error_without_renewal(self):
        end = self.clock() + 10
        with self.assertRaises(hosted.Deadline):
            with hosted.Alarm(end, self.clock) as alarm:
                self.clock.advance(11)
                alarm.check()
        self.assertEqual(self.timers.call_args.args, (hosted.signal.ITIMER_REAL, 0))
        self.assertEqual(self.handlers.call_args.args, (hosted.signal.SIGALRM, self.previous_handler))


if __name__ == "__main__":
    unittest.main()
