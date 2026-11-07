"""Retain real source checks and full releases when documentation skips native CI."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


def require_full_release(workflow):
    scope = workflow["jobs"]["scope"]
    decision = next(step for step in scope["steps"] if step.get("id") == "scope")
    if decision["env"].get("FORCE_FULL") != "true":
        raise ValueError("Release scope must remain full")
    if "$FORCE_FULL" not in decision["run"] or "--force" not in decision["run"]:
        raise ValueError("Release scope must forward force-full")
    if workflow["jobs"]["checks"]["with"].get("force-full") is not True:
        raise ValueError("Release quality must remain full")


class DocumentationScopeTests(unittest.TestCase):
    def setUp(self):
        self.quality = yaml.safe_load((ROOT / ".github/workflows/quality-gate.yml").read_text())
        self.release = yaml.safe_load((ROOT / ".github/workflows/release-pipeline.yml").read_text())

    def test_current_source_metadata_privacy_and_localizations(self):
        subprocess.run([sys.executable, str(ROOT / "scripts/verify-source.py")], cwd=ROOT, check=True)

    def test_invalid_source_metadata_still_fails(self):
        spec = importlib.util.spec_from_file_location("scope_source_check", ROOT / "scripts/verify-source.py")
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        with tempfile.TemporaryDirectory() as temporary:
            checker.ROOT = Path(temporary)
            (checker.ROOT / "VERSION").write_text("invalid\n")
            with self.assertRaisesRegex(SystemExit, "VERSION"):
                checker.main()

    def test_source_contracts_and_codeql_always_run(self):
        jobs = self.quality["jobs"]
        self.assertNotIn("if", jobs["workflow-contracts"])
        self.assertNotIn("if", jobs["check-1"])
        self.assertEqual(jobs["check-1"]["uses"], "./.github/workflows/codeql.yml")
        command = "python3 -m unittest discover -s .github/workflow-tests -p 'test_*.py'"
        steps = [step for step in jobs["workflow-contracts"]["steps"] if step.get("run") == command]
        self.assertEqual(len(steps), 1)
        self.assertNotIn("if", steps[0])
        self.assertFalse(steps[0].get("continue-on-error", False))
        self.assertFalse(jobs["workflow-contracts"].get("continue-on-error", False))

    def test_owner_cancellation_semantics_are_preserved(self):
        self.assertEqual(self.quality["jobs"]["gate"]["if"], "${{ !cancelled() }}")

    def test_documentation_gate_requires_real_checks_and_skipped_native_ci(self):
        gate = self.quality["jobs"]["gate"]
        command = next(step["run"] for step in gate["steps"] if "run" in step)
        results = {name: {"result": "skipped"} for name in gate["needs"]}
        results.update(scope={"result": "success", "outputs": {"run": "false", "reason": "documentation-only"}},
                       **{"check-1": {"result": "success"}, "workflow-contracts": {"result": "success"}})
        cases = [(results, True)]
        for name in ["scope", "check-1", "workflow-contracts"]:
            for outcome in ["skipped", "failure", "cancelled"]:
                changed = deepcopy(results)
                changed[name]["result"] = outcome
                cases.append((changed, False))
        native_ran = deepcopy(results)
        native_ran["check-0"]["result"] = "success"
        cases.append((native_ran, False))
        for vector, expected in cases:
            with self.subTest(results=vector):
                checked = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", command],
                                         env={**os.environ, "RESULTS": json.dumps(vector)},
                                         capture_output=True, check=False)
                self.assertEqual(checked.returncode == 0, expected)

    def test_declared_document_paths_keep_source_and_mode_changes_full(self):
        spec = importlib.util.spec_from_file_location("room_scope", ROOT / "scripts/change_scope.py")
        classifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(classifier)
        policy = json.loads((ROOT / ".release-policy.json").read_text())["change_scope"]
        explicit, required = policy["documentation_paths"], policy["required_paths"]
        def raw(path, mode="100644"):
            return f":100644 {mode} {'1' * 40} {'2' * 40} M\0{path}\0".encode()
        cases = [(raw("Core/README.md"), False), (raw("docs/release-workflow.md"), False),
                 (raw("CHANGELOG.md"), True), (raw("App/Views.swift"), True),
                 (raw("Core/README.md", "120000"), True),
                 (raw("Core/README.md") + raw("App/Views.swift"), True)]
        for diff, expected in cases:
            with self.subTest(diff=diff):
                self.assertIs(classifier.classify_diff(diff, explicit, required)["run"], expected)

    def test_release_retains_outer_and_inner_full_qualification(self):
        require_full_release(self.release)
        for value in [False, "false", None]:
            changed = deepcopy(self.release)
            changed["jobs"]["checks"]["with"]["force-full"] = value
            with self.assertRaises(ValueError):
                require_full_release(changed)
        changed = deepcopy(self.release)
        decision = next(step for step in changed["jobs"]["scope"]["steps"] if step.get("id") == "scope")
        decision["env"]["FORCE_FULL"] = "false"
        with self.assertRaises(ValueError):
            require_full_release(changed)


if __name__ == "__main__":
    unittest.main()
