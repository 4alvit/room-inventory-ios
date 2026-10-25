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
        self.assertEqual(self.job["runs-on"], "macos-15")
        self.assertEqual(self.profile["job_timeout_minutes"], int(self.job["timeout-minutes"]))
        stages = sum(self.profile[key] for key in ("discovery_seconds", "recovery_seconds", "retention_seconds"))
        self.assertLess(stages, 36 * 60)
        self.assertLess(36 + 5, self.profile["job_timeout_minutes"])
        self.assertEqual(self.profile["recovery_seconds"], 1800)
        self.assertEqual(self.profile["admission_free_bytes"], 24 * 2**30)
        self.assertEqual(self.profile["abort_free_bytes"], 8 * 2**30)
        self.assertEqual(set(self.profile["allowed_events"]),
                         {"pull_request", "merge_group", "push", "schedule", "workflow_dispatch"})

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
