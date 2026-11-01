"""Cross-file contracts for the hosted recovery boundary; never starts native work."""
from pathlib import Path
import hashlib
import json
import unittest

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
        self.assertEqual(self.job["needs"], "ios")
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
            "RECOVERY_TESTED_COMMIT": "${{ needs.ios.outputs.tested-commit }}",
            "RECOVERY_TESTED_TREE": "${{ needs.ios.outputs.tested-tree }}",
        })
        self.assertEqual(self.job["permissions"], {"contents": "read"})
        self.assertNotIn("secrets", self.job)

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

    def test_native_jobs_share_toolchain_and_codeql_keeps_supported_tracing_toolchain(self):
        codeql = yaml.load((ROOT / ".github/workflows/codeql.yml").read_text(), Loader=yaml.BaseLoader)
        release = yaml.load((ROOT / ".github/workflows/release-build.yml").read_text(), Loader=yaml.BaseLoader)
        ordinary = (self.ci["jobs"]["ios"], release["jobs"]["package"])
        self.assertEqual(self.profile["runner_arch"], "ARM64")
        self.assertEqual(self.profile["process_arch"], "arm64")
        self.assertEqual(self.profile["image_os"], "macos27")
        self.assertEqual(self.profile["xcode_version"], "Xcode 27.1\nBuild version 27A9275")
        self.assertEqual(self.profile["runtime_version"], "27.0")
        self.assertEqual(self.ci["jobs"]["ios"]["env"]["SIMULATOR_RUNTIME_VERSION"],
                         self.profile["runtime_version"])
        self.assertEqual(self.profile["device_type"], "com.apple.CoreSimulator.SimDeviceType.iPhone-17")
        self.assertEqual(self.ci["jobs"]["ios"]["env"]["SIMULATOR_DEVICE_TYPE"],
                         self.profile["device_type"])
        for job in (*ordinary, self.job):
            self.assertEqual(job["runs-on"], self.profile["runner_label"])
            self.assertEqual(job["env"]["DEVELOPER_DIR"], "/Applications/Xcode_27.1.app/Contents/Developer")
        guards = []
        for job in ordinary:
            steps = job["steps"]
            guards.append(next(step["run"] for step in steps if step.get("name") == "Verify installed ARM toolchain"))
            guard_index = next(i for i, step in enumerate(steps) if step.get("name") == "Verify installed ARM toolchain")
            build_index = next(i for i, step in enumerate(steps) if step.get("name") in {
                "Run source contracts, Core tests, Simulator build and app tests", "Build app for analysis", "Build committed preview assets"})
            self.assertLess(guard_index, build_index)
        common = guards[1]
        self.assertTrue(guards[0].startswith(common))
        self.assertIn('test "$RUNNER_ARCH" = ' + self.profile["runner_arch"], common)
        self.assertIn('test "$(uname -m)" = ' + self.profile["process_arch"], common)
        self.assertIn('test "$ImageOS" = ' + self.profile["image_os"], common)
        self.assertIn('xcode_version="$(xcodebuild -version)"', common)
        self.assertIn('test "$xcode_version" = $\'' + self.profile["xcode_version"].replace("\n", "\\n") + "'", common)

        # CodeQL cannot trace compiled-language builds on macOS 27 or Xcode 27.
        # Keep its required source analysis on an explicit supported toolchain.
        analysis = codeql["jobs"]["swift"]
        self.assertEqual(analysis["runs-on"], "macos-26")
        self.assertEqual(analysis["env"]["DEVELOPER_DIR"],
                         "/Applications/Xcode_26.4.1.app/Contents/Developer")
        analysis_steps = analysis["steps"]
        guard_index = next(i for i, step in enumerate(analysis_steps)
                           if step.get("name") == "Verify installed ARM toolchain")
        build_index = next(i for i, step in enumerate(analysis_steps)
                           if step.get("name") == "Build app for analysis")
        self.assertLess(guard_index, build_index)
        analysis_guard = analysis_steps[guard_index]["run"]
        self.assertEqual(analysis_guard, common.replace("macos27", "macos26").replace(
            "Xcode 27.1\\nBuild version 27A9275", "Xcode 26.4.1\\nBuild version 17E202"))
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
