"""Sealed collection lifecycle tests; all native commands are injected."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_recovery_controller import ControllerCase, controller


class OfflineCollectionTests(ControllerCase):
    def ready(self):
        run = self.run_fixture()
        run.bind_output_resource_root()
        run.prepare_derived_resource_root()
        run.device_id = "44444444-4444-4444-8444-444444444444"
        run.device_root = self.devices / run.device_id
        run.device_root.mkdir()
        run.bind_device_resource_root()
        root = run.output / "evidence/collection"
        copied = root / "xcresult/verified.xcresult"
        original = run.output / "original.xcresult"
        copied.mkdir(parents=True)
        original.mkdir()
        run.collector = Mock(root=root, xc_copy=copied, xc_original=original,
                             xc_limit=controller.XCRESULT_CAP, xc_files=10000,
                             xc_before={}, live_seal={"test": True}, seal_sha256="a" * 64)
        run.collector._snapshot.return_value = {}
        run.record["phase"] = "collect"
        run.record["commands"].append({"name": "ui-test", "exit_code": 0, "primary_error": None,
            "cleanup": {"success": True, "group_state": "absent", "leader_reaped": True}})
        run.groups = [{"state": {"group_state": "absent", "leader_reaped": True}}]
        run.command = Mock(return_value=json.dumps({"devices": {"runtime": [
            {"udid": run.device_id, "state": "Shutdown"}]}}).encode())
        return run

    def test_shutdown_readback_full_census_precede_first_reader_and_final_census(self):
        run = self.ready()
        events = []
        original_command, original_guard = run.command, run.guard
        run.command = Mock(side_effect=lambda *args, **kw: (events.append(args[1]), original_command(*args, **kw))[1])
        run.guard = Mock(side_effect=lambda *args, **kw: (events.append(("guard", kw)), original_guard(*args, **kw))[1])
        run.begin_offline_collection(run.collector.xc_copy)
        self.assertEqual(events[:3], ["collection-shutdown", "collection-device-state",
                                     ("guard", {"force": True, "full_resources": True})])
        self.assertIn("device", run.last_samples[-1])
        self.assertIn("derived_data", run.last_samples[-1])
        self.assertEqual(run.record["offline_collection"]["shutdown_state"], "Shutdown")
        run.read_collected_result(["get", "test-results", "summary", "--path", str(run.collector.xc_copy), "--compact"])
        self.assertEqual(run.command.call_args.kwargs["cap"], 40)
        run.finish_offline_collection()
        self.assertIsNone(run._offline_collection)
        self.assertEqual(run.record["offline_collection"]["status"], "CLOSED")
        self.assertIn("device", run.last_samples[-1])
        self.assertIn("derived_data", run.last_samples[-1])
        self.popen.assert_not_called()

    def test_ui_failure_or_uncertain_group_cannot_authorize_shutdown_or_readers(self):
        for fault in ("exit", "cleanup", "group"):
            with self.subTest(fault=fault):
                run = self.ready()
                if fault == "exit":
                    run.record["commands"][0]["exit_code"] = 65
                elif fault == "cleanup":
                    run.record["commands"][0]["cleanup"]["success"] = False
                else:
                    run.groups[0]["state"]["group_state"] = "unknown"
                with self.assertRaisesRegex(controller.RunFailure, "UI process group"):
                    run.begin_offline_collection(run.collector.xc_copy)
                run.command.assert_not_called()
                self.assertIsNone(run._offline_collection)
                # Retry is forbidden even after the cause is changed.
                with self.assertRaisesRegex(controller.ConfigurationFailure, "already attempted"):
                    run.begin_offline_collection(run.collector.xc_copy)
                self.remove_fixture(run)

    def remove_fixture(self, run):
        # Only private synthetic files in this test's TemporaryDirectory.
        import shutil
        shutil.rmtree(run.output)
        shutil.rmtree(run.device_root)

    def test_failed_shutdown_missing_duplicate_or_booted_readback_never_opens_scope(self):
        for fault in ("shutdown", "missing", "duplicate", "Booted"):
            with self.subTest(fault=fault):
                run = self.ready()
                if fault == "shutdown":
                    run.command.side_effect = controller.RunFailure("shutdown failure")
                else:
                    rows = [] if fault == "missing" else [{"udid": run.device_id, "state": "Booted" if fault == "Booted" else "Shutdown"}]
                    if fault == "duplicate":
                        rows *= 2
                    run.command.return_value = json.dumps({"devices": {"runtime": rows}}).encode()
                with self.assertRaises(controller.RunFailure):
                    run.begin_offline_collection(run.collector.xc_copy)
                self.assertIsNone(run._offline_collection)
                self.remove_fixture(run)

    def test_sealed_periodic_guard_omits_only_device_and_derived_not_live_output_caps(self):
        run = self.ready()
        run.begin_offline_collection(run.collector.xc_copy)
        original = run.resource_size
        calls = []
        run.resource_size = Mock(side_effect=lambda category, *args, **kw: (calls.append(category), original(category, *args, **kw))[1])
        run.guard(force=True)
        self.assertEqual(set(calls), {"output", "original_xcresult", "verified_xcresult", "attachments", "logs"})
        self.assertEqual(run.last_samples[-1]["sealed_offline_resources"]["omitted_categories"], ["derived_data", "device"])
        calls.clear()
        run.guard(force=True, full_resources=True)
        self.assertEqual(set(calls), {"output", "original_xcresult", "verified_xcresult", "attachments", "logs", "derived_data", "device"})
        for category in ("output", "attachments", "logs"):
            with self.subTest(category=category):
                run.resource_size.side_effect = lambda name, *a, **kw: (_ for _ in ()).throw(controller.RunFailure("cap")) if name == category else original(name, *a, **kw)
                with self.assertRaisesRegex(controller.RunFailure, "cap"):
                    run.guard(force=True)

    def test_entry_and_exit_census_caps_remain_fatal(self):
        for stage in ("entry", "exit"):
            for category in ("device", "derived_data"):
                with self.subTest(stage=stage, category=category):
                    run = self.ready()
                    if stage == "exit":
                        run.begin_offline_collection(run.collector.xc_copy)
                    original = run.resource_size
                    run.resource_size = Mock(side_effect=lambda name, *a, **kw: (_ for _ in ()).throw(controller.RunFailure("cap")) if name == category else original(name, *a, **kw))
                    with self.assertRaisesRegex(controller.RunFailure, "cap"):
                        (run.begin_offline_collection(run.collector.xc_copy) if stage == "entry" else run.finish_offline_collection())
                    self.assertIsNone(run._offline_collection)
                    self.remove_fixture(run)

    def test_scope_rejects_phase_change_root_replacement_and_low_disk(self):
        run = self.ready()
        run.begin_offline_collection(run.collector.xc_copy)
        run.record["phase"] = "test"
        with self.assertRaisesRegex(controller.ConfigurationFailure, "scope"):
            run.guard()
        run.record["phase"] = "collect"
        run.disk_usage = lambda _: SimpleNamespace(free=controller.ABORT_BYTES - 1)
        with self.assertRaisesRegex(controller.RunFailure, "Free disk"):
            run.guard()
        run.disk_usage = lambda _: SimpleNamespace(free=24 * controller.GIB)
        run.collector.xc_copy.rename(run.collector.xc_copy.with_name("old-copy"))
        run.collector.xc_copy.mkdir()
        with self.assertRaisesRegex(controller.ResourceAccountingFailure, "root replaced"):
            run.guard()

    def test_rebound_collector_paths_cannot_authorize_unsealed_reader(self):
        for attr in ("xc_copy", "xc_original", "root"):
            with self.subTest(attr=attr):
                run = self.ready()
                run.begin_offline_collection(run.collector.xc_copy)
                replacement = run.output / "replacement"
                replacement.mkdir()
                setattr(run.collector, attr, replacement)
                prior_calls = run.command.call_count
                with self.assertRaisesRegex(controller.ConfigurationFailure, "path rebound"):
                    run.read_collected_result(["get", "test-results", "summary", "--path", str(run.collector.xc_copy), "--compact"])
                self.assertEqual(run.command.call_count, prior_calls)
                self.remove_fixture(run)

    def test_final_census_still_attempted_when_content_check_fails(self):
        run = self.ready()
        run.begin_offline_collection(run.collector.xc_copy)
        original = run.guard
        run.guard = Mock(wraps=original)
        run.collector.verify_live_seal.side_effect = controller.RunFailure("seal changed")
        with self.assertRaisesRegex(controller.RunFailure, "seal changed"):
            run.finish_offline_collection()
        run.guard.assert_called_once_with(force=True, full_resources=True)
        self.assertEqual(run.record["offline_collection"]["status"], "FAILED")
        self.assertIsNone(run._offline_collection)

    def test_failed_final_census_does_not_relabel_intermediate_sample(self):
        run = self.ready()
        run.begin_offline_collection(run.collector.xc_copy)
        run.collector.verify_live_seal.side_effect = lambda: run.guard(force=True)
        original = run.resource_size
        def resource(category, *args, **kwargs):
            if category == "device":
                raise controller.RunFailure("final device cap")
            return original(category, *args, **kwargs)
        run.resource_size = Mock(side_effect=resource)
        with self.assertRaisesRegex(controller.RunFailure, "final device cap"):
            run.finish_offline_collection()
        self.assertIn("sealed_offline_resources", run.last_samples[-1])
        self.assertIsNone(run.record["offline_collection"]["final_sample"])

    def test_receipt_flush_failure_does_not_replace_final_check_error(self):
        run = self.ready()
        run.begin_offline_collection(run.collector.xc_copy)
        primary = controller.DeadlineFailure("final content deadline")
        run.collector.verify_live_seal.side_effect = primary
        run.flush = Mock(side_effect=OSError("receipt unavailable"))
        with self.assertRaises(controller.DeadlineFailure) as caught:
            run.finish_offline_collection()
        self.assertIs(caught.exception, primary)
        self.assertIsNone(run._offline_collection)
        self.assertTrue(any("receipt unavailable" in error
                            for error in run.record["offline_collection"]["final_errors"]))

    def test_no_reader_outside_scope_or_repeat_or_different_path(self):
        run = self.ready()
        args = ["get", "test-results", "summary", "--path", str(run.collector.xc_copy), "--compact"]
        with self.assertRaises(controller.ConfigurationFailure):
            run.read_collected_result(args)
        run.begin_offline_collection(run.collector.xc_copy)
        with self.assertRaisesRegex(controller.ConfigurationFailure, "Unexpected or repeated"):
            run.read_collected_result([*args[:-2], str(run.collector.xc_original), "--compact"])
        run.read_collected_result(args)
        with self.assertRaisesRegex(controller.ConfigurationFailure, "Unexpected or repeated"):
            run.read_collected_result(args)
        run.finish_offline_collection()
        with self.assertRaises(controller.ConfigurationFailure):
            run.read_collected_result(args)

    def test_finalization_error_does_not_replace_primary_reader_error(self):
        run = self.ready()
        run.xctestrun = run.output / "selected.xctestrun"
        run.xctestrun.write_bytes(b"selection")
        run.xctestrun_sha = controller.sha(b"selection")
        run.pin_sources = Mock()
        run.begin_offline_collection = Mock()
        primary = controller.DeadlineFailure("reader deadline")
        run.collector.collect.side_effect = primary
        run.finish_offline_collection = Mock(side_effect=controller.RunFailure("final census cap"))
        with self.assertRaises(controller.DeadlineFailure) as caught:
            run.test_and_collect()
        self.assertIs(caught.exception, primary)
        run.finish_offline_collection.assert_called_once()
        self.assertIn("final census cap", run.record["collection_finalization_error"]["message"])
        self.assertEqual(run.collector.collect.call_count, 1)
