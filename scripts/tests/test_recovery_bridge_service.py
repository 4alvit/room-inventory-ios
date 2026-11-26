"""Bridge responsiveness through actual guarded walks; all runtime I/O injected."""
import contextlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_recovery_device_service as fixtures
from test_recovery_vanished_xcresult import ResultWorld, info
from test_recovery_collector import C as K

C = fixtures.C


class BridgeWorld(ResultWorld):
    def __init__(self):
        super().__init__()
        self.count = 240
        self.walked = 0
        self.pending = self.acknowledged = False
        self.calls = []
        self.barriers = []
        self.callback_fault = self.entry_fault = None
        self.run.collector = self
        self.run.guard = lambda force=False: C.RecoveryRun.guard(self.run, force=force)
        self.stat_action = self.visit
        self.poll_action = lambda: 0 if len(self.run.last_samples) >= 2 else None
        self.read_action = self.read_pipe

    def __enter__(self):
        super().__enter__()
        self.run.device_root = self.root
        self.run.device_id = self.root.name
        self.run._owned_device_identity = None
        self.run.bind_device_resource_root()
        self.children[self.root] = []
        for index in range(self.count):
            child = self.root / str(index)
            self.children[self.root].append(child)
            self.infos[child] = info(size=1, blocks=1, inode=index + 100)
        return self

    def visit(self, path):
        if path.parent == self.root and self.stage == "active":
            self.walked += 1
            self.clock.now += .4
            if self.walked == 8:
                self.pending = True
                self.request_time = self.clock.now
            if self.entry_fault:
                self.entry_fault(path)

    def read_pipe(self, fd):
        if self.poll_action() is None:
            raise BlockingIOError()
        return b""

    def has_pending_bridge_request(self):
        return self.pending

    def poll_bridge(self):
        if not self.pending:
            return
        self.calls.append((self.clock.now, self.walked, len(self.run.last_samples)))
        assert self.run._resource_census is not None
        assert self.run._bridge_scan_guard is not None
        # Real collector reads/writes and _publish_ack all call this same guard.
        self.run.guard()
        self.clock.now += 2.1
        self.run.guard()
        if self.callback_fault:
            self.callback_fault()
        self.acknowledged = True
        self.barriers.append({"sequence": len(self.barriers) + 1})
        self.pending = False

    def invoke(self):
        args = ["xcodebuild", "test-without-building", "-xctestrun", self.run.xctestrun,
                "-only-testing:" + C.CASE, "-resultBundlePath", self.result]
        return self.run.command(args, "ui-test", cap=300, xcresult_producer=True,
                                on_poll=self.poll_bridge)


class BridgeServiceTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))

    def assert_closed(self, world):
        self.assertTrue(world.cleaned)
        self.assertIsNone(world.run._resource_census)
        self.assertIsNone(world.run._bridge_scan_guard)
        self.assertEqual(sum(e[0] == "cleanup" for e in world.events), 1)

    def test_request_during_slow_census_is_acknowledged_once_before_full_completion(self):
        with BridgeWorld() as w:
            self.assertEqual(w.invoke(), b"")
            self.assertTrue(w.acknowledged)
            self.assertEqual(len(w.calls), 1)
            at, visited, completed = w.calls[0]
            self.assertLess(at - w.request_time, 1)
            self.assertLess(visited, w.count)
            self.assertEqual(completed, 1)
            self.assertGreater(w.record["elapsed_seconds"], 60)
            self.assertGreaterEqual(len(w.run.last_samples), 3)
            self.assertEqual(w.run.last_samples[-1]["device"]["entries"], w.count)
            trace = w.record["bridge_scan_service"]["records"]
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0]["state"], "completed")
            self.assertEqual(trace[0]["sequence"], 1)
            self.assertEqual(trace[0]["incomplete_census"], "device")
            self.assertGreater(trace[0]["finished_elapsed"], trace[0]["started_elapsed"])
            self.assert_closed(w)

    def test_later_device_cap_crossing_fails_even_after_acknowledgement(self):
        with BridgeWorld() as w:
            def cross(path):
                if w.walked == 200:
                    w.infos[path].st_blocks = C.DEVICE_CAP // 512 + 1
            w.entry_fault = cross
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("cap reached", str(error))
            self.assertTrue(w.acknowledged)
            self.assertEqual(len(w.run.last_samples), 1)
            self.assert_closed(w)

    def test_owned_derived_walk_services_once_and_requires_final_census(self):
        for replace_owner in (False, True):
            with self.subTest(replace_owner=replace_owner), BridgeWorld() as w:
                w.children[w.root] = []
                w.root = w.run.derived
                w.children[w.root] = []
                for index in range(w.count):
                    child = w.root / str(index)
                    w.children[w.root].append(child)
                    w.infos[child] = info(size=1, blocks=1, inode=index + 500)
                # Use the production create/bind/validate path; only filesystem
                # syscalls are injected by the shared owned-directory fixture.
                w.run.prepare_derived_resource_root()
                if replace_owner:
                    def change_owner():
                        w.infos[w.root].st_ino += 1
                        w.run.guard()
                    w.callback_fault = change_owner
                    error = fixtures.failure(w.invoke)
                    self.assertIsInstance(error, C.ResourceAccountingFailure)
                    self.assertIn("DerivedData root replaced", str(error))
                    self.assertFalse(w.acknowledged)
                    self.assertEqual(len(w.run.last_samples), 1)
                else:
                    self.assertEqual(w.invoke(), b"")
                    self.assertTrue(w.acknowledged)
                    at, visited, completed = w.calls[0]
                    self.assertLess(at - w.request_time, 1)
                    self.assertLess(visited, w.count)
                    self.assertEqual(completed, 1)
                    self.assertGreater(w.record["elapsed_seconds"], 60)
                    self.assertGreaterEqual(len(w.run.last_samples), 3)
                    final = w.run.last_samples[-1]["derived_data"]
                    self.assertEqual(final["entries"], w.count)
                    self.assertEqual(final["logical_bytes"], w.count)
                    self.assertEqual(w.record["post_command_accounting"]["status"], "COMPLETED")
                self.assertEqual(len(w.calls), 1)
                trace = w.record["bridge_scan_service"]["records"]
                self.assertEqual(len(trace), 1)
                self.assertEqual(trace[0]["incomplete_census"], "derived_data")
                self.assertEqual(trace[0]["state"], "failed" if replace_owner else "completed")
                self.assertIsNone(w.run._derived_scan_service)
                self.assertIsNone(w.run._derived_scan_context)
                self.assert_closed(w)

    def test_callback_deadline_cancellation_and_io_errors_remain_primary(self):
        for mode in ("deadline", "cancel", "io"):
            with self.subTest(mode=mode), BridgeWorld() as w:
                def fail():
                    if mode == "deadline":
                        w.clock.now = w.run.command_deadline
                        w.run.guard()
                    raise KeyboardInterrupt("cancel") if mode == "cancel" else OSError("injected bridge I/O")
                w.callback_fault = fail
                error = fixtures.failure(w.invoke)
                self.assertIsInstance(error, C.DeadlineFailure if mode == "deadline" else KeyboardInterrupt if mode == "cancel" else OSError)
                self.assertFalse(w.acknowledged)
                self.assertEqual(len(w.calls), 1)
                self.assertEqual(len(w.run.last_samples), 1)
                self.assert_closed(w)

    def test_forced_nested_census_is_rejected_without_callback_replay(self):
        with BridgeWorld() as w:
            w.callback_fault = lambda: w.run.guard(force=True)
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.ConfigurationFailure)
            self.assertIn("Full census requested", str(error))
            self.assertEqual(len(w.calls), 1)
            self.assert_closed(w)

    def test_fresh_callback_output_cap_prevents_acknowledgement(self):
        with BridgeWorld() as w:
            def cross(path):
                if w.walked == 8:
                    w.infos[w.payload].st_blocks = C.OUTPUT_CAP // 512 + 1
            w.entry_fault = cross
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertFalse(w.acknowledged)
            self.assertEqual(w.calls, [])
            self.assert_closed(w)

    def test_recursive_service_and_changed_device_owner_fail_without_second_callback(self):
        for mode in ("recursive", "owner"):
            with self.subTest(mode=mode), BridgeWorld() as w:
                def fail():
                    if mode == "recursive":
                        w.run._device_scan_service[1]()
                    else:
                        w.run.device_root = Path("/foreign/device")
                        w.run.guard()
                w.callback_fault = fail
                error = fixtures.failure(w.invoke)
                self.assertIsInstance(error, C.ConfigurationFailure)
                self.assertEqual(len(w.calls), 1)
                self.assertFalse(w.acknowledged)
                self.assert_closed(w)

    def test_original_free_floor_remains_live_inside_callback(self):
        with BridgeWorld() as w:
            def low_disk():
                w.run.disk_usage = lambda path: type("Disk", (), {"free": C.ABORT_BYTES - 1})()
                w.run.guard()
            w.callback_fault = low_disk
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("Free disk", str(error))
            self.assertFalse(w.acknowledged)
            self.assert_closed(w)

    def test_actual_ack_publisher_checks_guard_after_fsync_before_link(self):
        collector = fixtures.load(Path(__file__).resolve().parents[1] / "recovery_collector.py",
                                  "recovery_bridge_publisher_under_test")
        for late in (False, True):
            with self.subTest(late=late), BridgeWorld() as w:
                w.bridge = Path("/owned/bridge")
                w._plain = lambda path: (w.run.guard(), path)[1]
                w.guard = w.run.guard
                w._sync = lambda path: None
                events = []
                stream = fixtures.Mock()
                stream.__enter__ = fixtures.Mock(return_value=stream)
                stream.__exit__ = fixtures.Mock(return_value=False)
                stream.fileno.return_value = 321
                def sync(fd):
                    events.append("fsync")
                    if late:
                        w.clock.now = w.run.command_deadline
                def publish():
                    with contextlib.ExitStack() as stack:
                        stack.enter_context(patch.object(collector.os, "open", return_value=321))
                        stack.enter_context(patch.object(collector.os, "fdopen", return_value=stream))
                        stack.enter_context(patch.object(collector.os, "fsync", side_effect=sync))
                        stack.enter_context(patch.object(collector.os, "link", side_effect=lambda *a, **k: events.append("link")))
                        stack.enter_context(patch.object(Path, "unlink"))
                        collector.Collector._publish_ack(w, "ack-02.json", b'{"success":true}\n')
                w.callback_fault = publish
                if late:
                    self.assertIsInstance(fixtures.failure(w.invoke), C.DeadlineFailure)
                    self.assertEqual(events, ["fsync"])
                else:
                    self.assertEqual(w.invoke(), b"")
                    self.assertEqual(events, ["fsync", "link"])
                    self.assertTrue(w.acknowledged)
                self.assertEqual(len(w.calls), 1)
                self.assert_closed(w)

    def test_pending_hint_is_post_installation_and_still_detects_untrusted_entries(self):
        collector = fixtures.load(Path(__file__).resolve().parents[1] / "recovery_collector.py",
                                  "recovery_bridge_hint_under_test")
        value = collector.Collector.__new__(collector.Collector)
        value.bridge = Path("/owned/bridge")
        value.barriers = []
        value._bridge_poll_active = False  # __new__ fixture supplies the constructor state.
        value.installation_state = "waiting"
        with patch.object(collector.os.path, "lexists", return_value=True) as exists:
            self.assertFalse(value.has_pending_bridge_request())
            exists.assert_not_called()
            value.installation_state = "accepted"
            self.assertTrue(value.has_pending_bridge_request())
            exists.assert_called_once_with(value.bridge / "request-01.json")
            # Presence is only a scheduling hint; poll_bridge must reject a
            # symlink/malformed request rather than silently ignoring it here.
            value.barriers = [{}] * 6
            self.assertFalse(value.has_pending_bridge_request())
            self.assertEqual(exists.call_count, 1)


class TransactionWorld(BridgeWorld):
    """Real controller/collector control flow, with only runtime I/O injected."""
    def __init__(self, mode, *, write_delay=2.1):
        super().__init__()
        self.mode = mode
        self.run.phase("test")  # The actual UI command runs in its existing 1320s phase.
        self.documents, self.evidence = {}, {}
        self.transaction_request_time = self.ack_time = None
        self.delayed = False
        self.write_delay = write_delay
        self.selection_samples_after_ack = []
        c = self.transaction = K.Collector.__new__(K.Collector)
        c.ids = {k: f'{n:08d}-1111-4111-8111-111111111111'
                 for n, k in enumerate(('journey_run_id', 'source_run_id', 'target_run_id'), 1)}
        c.bridge = Path('/owned/bridge')
        c.simulator = SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=1, st_ino=999))
        c.installation_device = {'device_id': 1, 'inode': 999}
        c.installation_state, c.installation_files = 'accepted', {}
        c.photos_isolated = True
        c.barriers, c.origins, c.nonces = [], [], set()
        c._bridge_poll_active = False
        c.baseline = {'exports': {}, 'saved': {'folder': None, 'identity': None, 'entries': {}}}
        c.guard = self.run.guard
        c._containers = self.containers
        c._poll_photos_seed = c._poll_photos_isolation = lambda: None
        c._entries = lambda path, budget: [SimpleNamespace(name=Path(n).name) for n in self.documents]
        c._read = self.read_document
        c._exports = lambda: self.guarded({})
        c._files = lambda: self.guarded(c.baseline['saved'])
        c._write, c._publish_ack = self.write_evidence, self.publish_ack
        self.run.collector = c

    def guarded(self, value):
        self.run.guard()
        return value

    def publish_request(self):
        if self.transaction_request_time is None:
            c = self.transaction
            req = {'schema_version': 1, **c.ids, 'sequence': 1,
                   'role': 'source_zip', 'phase': 'before',
                   'nonce': '55555555-5555-4555-8555-555555555555'}
            self.documents[str(c.bridge/'request-01.json')] = K.canonical(req)
            self.infos[c.bridge/'request-01.json'] = info(size=300, blocks=1, inode=997)
            self.transaction_request_time = self.clock.now

    def containers(self):
        self.run.guard()
        if (self.mode == 'ordinary' and self.run._device_scan_context is None
                and self.run._derived_scan_context is None):
            self.publish_request()

    def read_document(self, path, limit):
        self.run.guard()
        return self.documents[str(path)], None

    def write_evidence(self, relative, raw):
        if not self.delayed:
            self.delayed = True
            self.clock.now += self.write_delay  # The unchanged census cadence is two seconds.
            if self.callback_fault:
                self.callback_fault()
        self.run.guard()
        self.evidence[relative] = raw

    def publish_ack(self, name, raw):
        self.run.guard()
        assert all(f'bridge/{p}-01.json' in self.evidence for p in ('request', 'receipt', 'ack'))
        self.documents[str(self.transaction.bridge/name)] = raw
        self.ack_time = self.clock.now
        self.samples_at_ack = len(self.run.last_samples)

    def visit(self, path):
        super().visit(path)
        if self.mode == 'cooperative' and self.walked == 8 and self.stage == 'active':
            self.publish_request()

    def __enter__(self):
        super().__enter__()
        self.infos[self.transaction.bridge] = info(mode=fixtures.stat.S_IFDIR, inode=998)
        self.stack.enter_context(patch.object(K.os.path, 'lexists', lambda p: str(p) in self.documents))
        return self

    def select(self, timeout):
        # A zero-timeout select pumps the owned child DURING the full census.
        # Positive-timeout select is the normal command-loop continuation.
        if self.ack_time is not None and timeout > 0:
            self.selection_samples_after_ack.append(len(self.run.last_samples))
        return super().select(timeout)

    def invoke(self):
        args = ['xcodebuild', 'test-without-building', '-xctestrun', self.run.xctestrun,
                '-only-testing:' + C.CASE, '-resultBundlePath', self.result]
        return self.run.command(args, 'ui-test', cap=300, xcresult_producer=True,
                                on_poll=self.transaction.poll_bridge)


class RealCollectorBridgeServiceTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))

    def assert_closed(self, world):
        self.assertTrue(world.cleaned)
        self.assertIsNone(world.run._resource_census)
        self.assertIsNone(world.run._bridge_scan_guard)
        self.assertFalse(world.transaction._bridge_poll_active)
        self.assertEqual(sum(e[0] == "cleanup" for e in world.events), 1)

    def test_real_collector_ordinary_and_cooperative_ack_before_slow_census_finishes(self):
        for mode in ("ordinary", "cooperative"):
            with self.subTest(mode=mode), TransactionWorld(mode) as w:
                self.assertEqual(w.invoke(), b"")
                self.assertEqual(len(w.transaction.barriers), 1)
                self.assertLess(w.ack_time - w.transaction_request_time, 30)
                self.assertEqual(len(w.evidence), 3)
                self.assertIn(str(w.transaction.bridge / "ack-01.json"), w.documents)
                self.assertGreater(len(w.run.last_samples), w.samples_at_ack)
                self.assertEqual(w.run.last_samples[-1]["device"]["entries"], w.count)
                self.assertEqual(w.record["post_command_accounting"]["status"], "COMPLETED")
                self.assert_closed(w)

    def test_ordinary_callback_preserves_two_second_full_census_cadence(self):
        for delay, extra_census in ((0, 0), (2.1, 1)):
            with self.subTest(delay=delay), TransactionWorld("ordinary", write_delay=delay) as w:
                self.assertEqual(w.invoke(), b"")
                self.assertTrue(w.selection_samples_after_ack)
                self.assertEqual(w.selection_samples_after_ack[0], w.samples_at_ack + extra_census)
                self.assert_closed(w)

    def test_ack_history_survives_terminal_later_device_cap_failure(self):
        with TransactionWorld("ordinary") as w:
            def exceed_after_ack(path):
                if w.ack_time is not None:
                    w.infos[path].st_blocks = C.DEVICE_CAP // 512 + 1
            w.entry_fault = exceed_after_ack
            error = fixtures.failure(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("cap reached", str(error))
            self.assertEqual(len(w.transaction.barriers), 1)
            self.assertIn(str(w.transaction.bridge / "ack-01.json"), w.documents)
            self.assertEqual(len(w.evidence), 3)
            self.assertEqual(len(w.run.last_samples), w.samples_at_ack)
            self.assertEqual(w.selection_samples_after_ack, [])
            self.assertIsNone(w.record["post_command_accounting"])
            self.assert_closed(w)

    def test_ordinary_callback_rejects_changed_device_or_derived_owner_before_ack(self):
        for owner in ("device", "derived"):
            with self.subTest(owner=owner), TransactionWorld("ordinary") as w:
                w.run.prepare_derived_resource_root()
                def replace_owner():
                    if owner == "device":
                        w.run.device_id = "foreign"
                    else:
                        w.infos[w.run.derived].st_ino += 1
                w.callback_fault = replace_owner
                error = fixtures.failure(w.invoke)
                self.assertIsInstance(error, C.RunFailure)
                self.assertTrue("owner" in str(error) or "root replaced" in str(error))
                self.assertIsNone(w.ack_time)
                self.assertEqual(w.transaction.barriers, [])
                self.assert_closed(w)

    def test_ordinary_callback_failures_clear_scope_preserve_primary_and_never_ack(self):
        for mode in ("deadline", "cancel", "io"):
            with self.subTest(mode=mode), TransactionWorld("ordinary") as w:
                primary = KeyboardInterrupt("callback cancellation") if mode == "cancel" else OSError("callback I/O")
                def fail():
                    if mode == "deadline":
                        w.clock.now = w.run.command_deadline
                        w.run.guard()
                    raise primary
                w.callback_fault = fail
                error = fixtures.failure(w.invoke)
                if mode == "deadline":
                    self.assertIsInstance(error, C.DeadlineFailure)
                else:
                    self.assertIs(error, primary)
                self.assertIsNone(w.ack_time)
                self.assertEqual(w.transaction.barriers, [])
                self.assertTrue(w.transaction.has_pending_bridge_request())
                self.assertEqual(w.selection_samples_after_ack, [])
                self.assert_closed(w)

if __name__ == "__main__":
    unittest.main()
