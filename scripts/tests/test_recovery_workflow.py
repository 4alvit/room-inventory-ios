"""Cross-file contracts for the hosted recovery boundary; never starts native work."""
from pathlib import Path
import hashlib
import json
import unittest
from unittest.mock import patch
import os
import subprocess
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[2]


class RecoveryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ci = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
        cls.gate = yaml.load((ROOT / ".github/workflows/quality-gate.yml").read_text(), Loader=yaml.BaseLoader)
        cls.job = cls.ci["jobs"]["recovery"]
        cls.profile_raw = (ROOT / "scripts/recovery-hosted-profile.json").read_bytes()
        cls.profile = json.loads(cls.profile_raw)

    def test_recovery_failure_is_on_required_gate_and_preview_path(self):
        self.assertEqual(self.ci["on"], {"workflow_call": ""})
        self.assertEqual(self.gate["jobs"]["check-0"]["uses"], "./.github/workflows/ci.yml")
        self.assertIn("check-0", self.gate["jobs"]["gate"]["needs"])
        self.assertEqual(self.job["needs"], "source-identity")
        self.assertEqual(self.ci["jobs"]["ios"]["needs"], "source-identity")
        self.assertEqual(self.ci["jobs"]["preview"]["needs"], ["ios", "recovery"])
        self.assertNotIn("if", self.job)
        self.assertNotIn("continue-on-error", self.job)
        for step in self.job["steps"]:
            self.assertNotIn("continue-on-error", step)

    def test_job_checks_out_exact_event_commit_and_receives_validated_identity(self):
        checkout = self.job["steps"][0]
        self.assertEqual(checkout["with"], {"persist-credentials": "false", "ref": "${{ github.sha }}"})
        self.assertEqual(self.job["env"], {
            "DEVELOPER_DIR": "/Applications/Xcode_27.1.app/Contents/Developer",
            "RECOVERY_TESTED_COMMIT": "${{ needs.source-identity.outputs.commit }}",
            "RECOVERY_TESTED_TREE": "${{ needs.source-identity.outputs.tree }}",
        })
        self.assertEqual(self.job["permissions"], {"contents": "read"})
        self.assertNotIn("secrets", self.job)

    def inline_script(self, name):
        steps = [step for job in self.ci["jobs"].values() for step in job.get("steps", [])]
        source = next(step["run"] for step in steps if step.get("name") == name)
        lines = source.splitlines()
        self.assertTrue(lines[0].startswith("python3 - <<'"))
        self.assertEqual(lines[-1], lines[0].split("'")[1])
        return "\n".join(lines[1:-1])

    def run_identity_script(self, name, *, commit="a" * 40, tree="b" * 40,
                            event="a" * 40, expected_commit="a" * 40,
                            expected_tree="b" * 40, status="", version="1.2.3"):
        script = self.inline_script(name)
        calls = []

        def git(args, **kwargs):
            self.assertEqual(args[0], "git")
            self.assertTrue(kwargs.get("text"))
            calls.append(args)
            if args[1:] == ["--no-replace-objects", "rev-parse", "HEAD", "HEAD^{tree}"]:
                return commit + "\n" + tree + "\n"
            if args[1:] == ["status", "--porcelain", "--untracked-files=all"]:
                return status
            self.fail("Unexpected Git operation: " + repr(args))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            env = {"GITHUB_SHA": event, "GITHUB_OUTPUT": str(output),
                   "EXPECTED_SOURCE_COMMIT": expected_commit, "EXPECTED_SOURCE_TREE": expected_tree}
            failure = None
            with patch.dict(os.environ, env), patch.object(subprocess, "check_output", side_effect=git), \
                    patch.object(Path, "read_text", return_value=version):
                try:
                    exec(compile(script, "<workflow-identity>", "exec"), {})
                except SystemExit as error:
                    failure = str(error)
            content = output.read_text() if output.exists() else ""
        return failure, content, calls

    def test_source_prerequisite_is_bounded_read_only_and_both_jobs_require_success(self):
        source = self.ci["jobs"]["source-identity"]
        self.assertEqual(source["runs-on"], "ubuntu-latest")
        self.assertEqual(source["timeout-minutes"], "5")
        self.assertEqual(source["permissions"], {"contents": "read"})
        self.assertNotIn("needs", source)
        self.assertEqual(source["outputs"], {"commit": "${{ steps.identity.outputs.commit }}",
                                             "tree": "${{ steps.identity.outputs.tree }}"})
        for job in (source, self.ci["jobs"]["ios"], self.job):
            self.assertNotIn("if", job)
            self.assertNotIn("continue-on-error", job)
            self.assertNotIn("secrets", job)
            for step in job["steps"]:
                self.assertNotIn("continue-on-error", step)
        for job in (source, self.ci["jobs"]["ios"]):
            checkout = job["steps"][0]
            self.assertEqual(checkout["with"], {"persist-credentials": "false", "ref": "${{ github.sha }}"})
            self.assertEqual(checkout["uses"], self.job["steps"][0]["uses"])
        self.assertEqual(self.ci["permissions"], {"contents": "read"})

    def test_shared_source_produces_only_valid_clean_event_identity(self):
        name = "Record immutable source identity"
        error, output, _ = self.run_identity_script(name)
        self.assertIsNone(error)
        self.assertEqual(output, "commit=" + "a" * 40 + "\ntree=" + "b" * 40 + "\n")
        for change in ({"commit": "c" * 40}, {"tree": ""}, {"tree": "b" * 40 + "\nextra"},
                       {"event": ""}, {"event": "a" * 40 + "\n"}, {"status": "?? untracked\n"},
                       {"status": " M tracked\n"}):
            with self.subTest(change=change):
                error, output, _ = self.run_identity_script(name, **change)
                self.assertIsNotNone(error)
                self.assertEqual(output, "")

    def test_core_checks_shared_identity_before_any_test_or_native_command(self):
        ios = self.ci["jobs"]["ios"]
        self.assertEqual(ios["env"]["EXPECTED_SOURCE_COMMIT"], "${{ needs.source-identity.outputs.commit }}")
        self.assertEqual(ios["env"]["EXPECTED_SOURCE_TREE"], "${{ needs.source-identity.outputs.tree }}")
        names = [step.get("name") for step in ios["steps"]]
        verify = names.index("Verify shared source identity before tests")
        self.assertLess(verify, names.index("Test bounded release CLI download retries"))
        self.assertLess(verify, names.index("Verify installed ARM toolchain"))
        self.assertLess(verify, names.index("Run source contracts, Core tests, Simulator build and app tests"))
        self.assertNotIn("if", ios["steps"][verify])
        self.assertIsNone(self.run_identity_script(names[verify])[0])

    def test_core_preflight_and_posttest_reject_missing_wrong_dirty_identity_without_outputs(self):
        for name in ("Verify shared source identity before tests", "Record validated source and preview version"):
            for change in ({"commit": "c" * 40}, {"tree": "c" * 40}, {"expected_commit": ""},
                           {"expected_tree": ""}, {"expected_tree": "c" * 40}, {"event": "c" * 40},
                           {"commit": "a" * 40 + "\nextra"}, {"status": " M tracked\n"},
                           {"status": "?? untracked\n"}):
                with self.subTest(name=name, change=change):
                    error, output, _ = self.run_identity_script(name, **change)
                    self.assertIsNotNone(error)
                    self.assertEqual(output, "")

    def test_preview_requires_both_successes_and_core_posttest_outputs(self):
        preview = self.ci["jobs"]["preview"]
        self.assertEqual(preview["needs"], ["ios", "recovery"])
        self.assertNotIn("continue-on-error", preview)
        self.assertEqual(preview["if"], "${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository }}")
        self.assertEqual(preview["with"]["tested-commit"], "${{ needs.ios.outputs.tested-commit }}")
        self.assertEqual(preview["with"]["tested-tree"], "${{ needs.ios.outputs.tested-tree }}")
        self.assertEqual(preview["with"]["version"], "${{ needs.ios.outputs.version }}")
        error, output, _ = self.run_identity_script("Record validated source and preview version")
        self.assertIsNone(error)
        self.assertEqual(output, "version=1.2.3\ncommit=" + "a" * 40 + "\ntree=" + "b" * 40 + "\n")
        for version in ("", "01.2.3", "1.2.3\ncommit=bad"):
            error, output, _ = self.run_identity_script("Record validated source and preview version", version=version)
            self.assertIsNotNone(error)
            self.assertEqual(output, "")

    def test_single_adapter_invocation_is_bound_to_exact_profile_bytes(self):
        runs = [step for step in self.job["steps"] if "run" in step]
        self.assertEqual(len(runs), 1)
        digest = hashlib.sha256(self.profile_raw).hexdigest()
        self.assertEqual(runs[0]["run"], "python3 scripts/recovery_hosted.py --profile-sha256 " + digest)
        self.assertNotIn("if", runs[0])
        self.assertEqual(int(runs[0]["timeout-minutes"]), 36)

    def test_profile_and_job_agree_on_standard_runner_and_finite_budgets(self):
        self.assertEqual(self.profile["workflow_path"], ".github/workflows/ci.yml")
        self.assertEqual(self.profile["job_id"], "recovery")
        self.assertEqual(self.profile["runner_label"], self.job["runs-on"])
        self.assertEqual(self.job["runs-on"], "xcode-27")
        self.assertEqual(self.profile["job_timeout_minutes"], int(self.job["timeout-minutes"]))
        stages = sum(self.profile[key] for key in ("discovery_seconds", "recovery_seconds", "retention_seconds"))
        self.assertLess(stages, 36 * 60)
        self.assertLess(36 + 5, self.profile["job_timeout_minutes"])
        self.assertEqual(self.profile["recovery_seconds"], 1800)
        self.assertEqual(self.profile["admission_free_bytes"], 24 * 2**30)
        self.assertEqual(self.profile["abort_free_bytes"], 8 * 2**30)
        self.assertEqual(set(self.profile["allowed_events"]),
                         {"pull_request", "merge_group", "push", "schedule", "workflow_dispatch"})

    def test_jobs_use_two_explicit_supported_toolchains(self):
        codeql = yaml.load((ROOT / ".github/workflows/codeql.yml").read_text(), Loader=yaml.BaseLoader)
        release = yaml.load((ROOT / ".github/workflows/release-build.yml").read_text(), Loader=yaml.BaseLoader)
        ios = self.ci["jobs"]["ios"]
        package = release["jobs"]["package"]
        analysis = codeql["jobs"]["swift"]
        self.assertEqual(self.profile["runner_arch"], "ARM64")
        self.assertEqual(self.profile["process_arch"], "arm64")
        self.assertEqual(self.profile["image_os"], "macos27")
        self.assertEqual(self.profile["xcode_version"], "Xcode 27.1\nBuild version 27A9275")
        self.assertEqual(self.profile["runtime_version"], "27.0")
        self.assertEqual(ios["env"]["SIMULATOR_RUNTIME_VERSION"], "26.2")
        self.assertEqual(self.profile["device_type"], "com.apple.CoreSimulator.SimDeviceType.iPhone-17")
        self.assertEqual(ios["env"]["SIMULATOR_DEVICE_TYPE"],
                         "com.apple.CoreSimulator.SimDeviceType.iPhone-16e")
        for job in (package, self.job):
            self.assertEqual(job["runs-on"], self.profile["runner_label"])
            self.assertEqual(job["env"]["DEVELOPER_DIR"], "/Applications/Xcode_27.1.app/Contents/Developer")
        for job in (ios, analysis):
            self.assertEqual(job["runs-on"], "macos-26")
            self.assertEqual(job["env"]["DEVELOPER_DIR"], "/Applications/Xcode_26.4.1.app/Contents/Developer")
        guards = []
        for job in (ios, package, analysis):
            steps = job["steps"]
            guards.append(next(step["run"] for step in steps if step.get("name") == "Verify installed ARM toolchain"))
            guard_index = next(i for i, step in enumerate(steps) if step.get("name") == "Verify installed ARM toolchain")
            build_index = next(i for i, step in enumerate(steps) if step.get("name") in {
                "Run source contracts, Core tests, Simulator build and app tests", "Build app for analysis", "Build committed preview assets"})
            self.assertLess(guard_index, build_index)
        common = guards[1]
        self.assertIn('test "$RUNNER_ARCH" = ' + self.profile["runner_arch"], common)
        self.assertIn('test "$(uname -m)" = ' + self.profile["process_arch"], common)
        self.assertIn('test "$ImageOS" = ' + self.profile["image_os"], common)
        self.assertIn('xcode_version="$(xcodebuild -version)"', common)
        self.assertIn('test "$xcode_version" = $\'' + self.profile["xcode_version"].replace("\n", "\\n") + "'", common)

        # Real StoreKit purchase tests retain the known-working iOS 26.2 stack.
        # CodeQL also needs Xcode 26 because Xcode 27 cannot support its tracing.
        # Both groups keep the same strict architecture, image and build guards.
        supported_guard = common.replace("macos27", "macos26").replace(
            "Xcode 27.1\\nBuild version 27A9275", "Xcode 26.4.1\\nBuild version 17E202")
        self.assertTrue(guards[0].startswith(supported_guard))
        self.assertEqual(guards[2], supported_guard)
        analysis_steps = analysis["steps"]
        initialization = next(step for step in analysis_steps
                              if step.get("uses", "").startswith("github/codeql-action/init@"))
        self.assertEqual(initialization["with"], {"languages": "swift", "build-mode": "manual"})

    def test_upload_keeps_only_compact_packet_even_on_failure(self):
        uploads = [step for step in self.job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertEqual(len(uploads), 1)
        upload = uploads[0]
        self.assertEqual(upload["if"], "${{ always() }}")
        self.assertEqual(upload["timeout-minutes"], "5")
        self.assertEqual(upload["with"], {
            "name": "recovery-${{ github.run_id }}-${{ github.run_attempt }}-${{ github.sha }}",
            "path": "${{ runner.temp }}/room-recovery-upload/",
            "include-hidden-files": "true", "if-no-files-found": "error",
            "compression-level": "0", "retention-days": "14",
        })

    def test_recovery_reuses_existing_immutable_action_pins(self):
        ios_pins = {step["uses"].split("@", 1)[0]: step["uses"]
                    for step in self.ci["jobs"]["ios"]["steps"] if "uses" in step}
        for step in self.job["steps"]:
            if "uses" in step:
                action, revision = step["uses"].split("@", 1)
                self.assertRegex(revision, r"^[0-9a-f]{40}$")
                self.assertEqual(step["uses"], ios_pins[action])


if __name__ == "__main__":
    unittest.main()
