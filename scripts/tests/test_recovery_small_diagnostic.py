"""Small failure packet tests use synthetic files and injected adapter boundaries only."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_recovery_hosted import HostedCase, hosted


class SmallDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="recovery-small-diagnostic-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.work = self.root / "room-recovery-work"
        (self.work / "preflight").mkdir(parents=True)
        (self.work / "run/logs").mkdir(parents=True)
        self.output = self.root / "room-recovery-diagnostic"
        self.context = {"source_commit": "a" * 40, "source_tree": "b" * 40,
                        "hosted_identity": {"run_id": "123", "run_attempt": "1"}}
        self.primary = {"type": "RunFailure", "message": "Command failed: ui-test"}
        self.result = {"primary_error": self.primary, "commands": [
            {"name": "ui-test", "exit_code": 65, "primary_error": self.primary}], "cleanup_errors": []}
        (self.work / "preflight/adapter-result.json").write_text(json.dumps(self.context))
        self.save_result()
        (self.work / "run/logs/ui-test.stdout").write_bytes(b"exact stdout\n")
        (self.work / "run/logs/ui-test.stderr").write_bytes(b"exact stderr\n")
        self.guard = Mock()

    def save_result(self):
        (self.work / "run/result.json").write_text(json.dumps(self.result))

    def collect(self):
        return hosted.small_failure_diagnostic(self.work, self.context, self.guard)

    def test_exact_result_summary_and_failed_command_bytes(self):
        report = self.collect()
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["source_commit"], self.context["source_commit"])
        self.assertEqual(report["run_id"], "123")
        for source, output in [("preflight/adapter-result.json", "run-summary.json"),
                               ("run/result.json", "result.json"),
                               ("run/logs/ui-test.stdout", "failed-command.stdout.tail"),
                               ("run/logs/ui-test.stderr", "failed-command.stderr.tail")]:
            raw = (self.work / source).read_bytes()
            self.assertEqual((self.output / output).read_bytes(), raw)
            self.assertEqual(report["files"][output]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertLessEqual(sum(p.stat().st_size for p in self.output.iterdir()), 4 * hosted.controller.MIB)
        self.assertTrue(self.guard.called)

    def test_large_log_has_exact_tail_offset_and_explicit_partial_line(self):
        raw = b"prefix\n" * 100000 + b"last line\n"
        (self.work / "run/logs/ui-test.stdout").write_bytes(raw)
        report = self.collect()["files"]["failed-command.stdout.tail"]
        self.assertEqual((self.output / "failed-command.stdout.tail").read_bytes(), raw[-512 * 1024:])
        self.assertEqual(report["start_byte"], len(raw) - 512 * 1024)
        self.assertEqual(report["end_byte_exclusive"], len(raw))
        self.assertTrue(report["truncated"])
        self.assertTrue(report["first_line_may_be_partial"])

    def test_oversize_result_is_omitted_without_guessing_log(self):
        (self.work / "run/result.json").write_bytes(b"x" * (2 * hosted.controller.MIB + 1))
        report = self.collect()
        self.assertEqual(report["files"]["result.json"]["status"], "OMITTED")
        self.assertEqual(report["files"]["result.json"]["read_cap_bytes"], 2 * hosted.controller.MIB)
        self.assertIsNone(report["failed_command"])
        self.assertFalse((self.output / "failed-command.stdout.tail").exists())

    def test_missing_result_keeps_summary_and_explicit_omission(self):
        (self.work / "run/result.json").unlink()
        report = self.collect()
        self.assertEqual(report["status"], "COMPLETE_WITH_OMISSIONS")
        self.assertEqual(report["files"]["result.json"]["error_type"], "FileNotFoundError")
        self.assertTrue((self.output / "run-summary.json").is_file())

    def test_symlink_result_is_not_followed(self):
        result = self.work / "run/result.json"
        result.unlink()
        result.symlink_to(self.work / "preflight/adapter-result.json")
        report = self.collect()
        self.assertEqual(report["files"]["result.json"]["status"], "OMITTED")
        self.assertFalse((self.output / "result.json").exists())

    def test_symlink_log_parent_is_not_followed(self):
        logs = self.work / "run/logs"
        logs.rename(self.work / "saved-logs")
        logs.symlink_to(self.work / "saved-logs", target_is_directory=True)
        report = self.collect()
        self.assertEqual(report["files"]["failed-command.stdout.tail"]["status"], "OMITTED")
        self.assertFalse((self.output / "failed-command.stdout.tail").exists())

    def test_ambiguous_primary_command_does_not_guess(self):
        self.result["commands"].append(dict(self.result["commands"][0], name="other"))
        self.save_result()
        self.assertIsNone(self.collect()["failed_command"])

    def test_command_path_escape_does_not_authorize_read(self):
        self.result["commands"][0]["name"] = "../../outside"
        self.save_result()
        self.assertIsNone(self.collect()["failed_command"])

    def test_excess_command_records_do_not_expand_work(self):
        self.result["commands"] *= 1001
        self.save_result()
        self.assertIsNone(self.collect()["failed_command"])

    def test_existing_output_is_not_reused(self):
        self.output.mkdir()
        (self.output / "keep").write_bytes(b"unchanged")
        with self.assertRaises(FileExistsError):
            self.collect()
        self.assertEqual((self.output / "keep").read_bytes(), b"unchanged")

    def test_control_exception_propagates_without_new_command(self):
        self.guard.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.collect()
        self.assertFalse(self.output.exists())

    def test_interruption_leaves_honest_incomplete_manifest(self):
        def guard():
            if (self.output / "diagnostic.json").exists():
                raise hosted.Deadline("injected deadline")
        with self.assertRaises(hosted.Deadline):
            hosted.small_failure_diagnostic(self.work, self.context, guard)
        self.assertEqual(json.loads((self.output / "diagnostic.json").read_text())["status"], "INCOMPLETE")


class SmallDiagnosticAdapterTests(HostedCase):
    def test_diagnostic_failure_cannot_replace_controller_failure(self):
        primary = {"type": "RunFailure", "message": "Command failed: ui-test"}
        self.fake_execution(code=1, primary=primary)
        with patch.object(hosted, "small_failure_diagnostic", side_effect=ValueError("injected diagnostic error")) as collect:
            result = self.run_adapter()
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["primary_error"], primary)
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(self.package.call_count, 1)

    def test_success_with_result_does_not_create_failure_packet(self):
        self.fake_execution()
        def execute():
            p = self.temp / "room-recovery-work/run/result.json"
            p.parent.mkdir()
            p.write_text("{}")
            return 0
        self.runner.execute.side_effect = execute
        with patch.object(hosted, "small_failure_diagnostic") as collect:
            result = self.run_adapter()
        self.assertEqual(result["exit_code"], 0)
        collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
