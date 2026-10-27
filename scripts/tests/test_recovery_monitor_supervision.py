"""Cooperative DerivedData supervision, entirely injected children/syscalls."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
import stat
import unittest

import test_recovery_controller as fixtures

C = fixtures.controller


class MonitorSupervisionTests(fixtures.ControllerCase):
    fake_child = fixtures.CommandFailureTests.fake_child

    @contextmanager
    def world(self, *, entries=200, data_bytes=3, category="derived_data", cap=None, full_guard=False):
        run = self.run_fixture(output=False)
        run.output.mkdir(exist_ok=True)
        run.owns_output = True
        run.flush = Mock()
        root = run.derived if category == "derived_data" else run.output / category
        limit = C.DERIVED_CAP if cap is None else cap
        w = SimpleNamespace(run=run, root=root, events=[], walked=0, scan_done=False,
                            scanning=False, captured_hook=None, free=24 * C.GIB,
                            select_fault=None, read_fault=None, write_fault=None,
                            poll_fault=None, stat_fault=None, barrier_fault=None,
                            log_fault=None, bytes=data_bytes, keep_pipes=False,
                            sample=None, cleanup_hook=[], callbacks=0)
        def disk(_):
            w.events.append(("disk", w.walked))
            return SimpleNamespace(free=w.free)
        run.disk_usage = disk
        real_tree = C.tree_size
        def tree(path, *args, **kwargs):
            if full_guard and path == run.derived:
                w.scanning = True
                w.captured_hook = getattr(run, "_derived_scan_service", None)
                try:
                    result = real_tree(path, *args, **kwargs)
                    w.scan_done = True
                    return result
                finally:
                    w.scanning = False
            if path == run.output / "logs" and w.scanning and category == "derived_data":
                w.events.append(("log_check", w.walked))
                self.assertEqual(run.record["resource_scan"]["current"]["category"], category)
                self.assertEqual(kwargs["max_entries"], 256)
                self.assertEqual(args[0], C.LOG_CAP)
                self.assertEqual(args[1], run.tick)
                if w.log_fault:
                    w.log_fault()
            return real_tree(path, *args, **kwargs)
        def guard(force=False):
            run.tick()
            if not run.groups:
                return
            if force:
                self.assertIsNone(run._derived_scan_service)
                w.events.append(("barrier", w.walked))
                if w.barrier_fault:
                    w.barrier_fault()
                if not full_guard:
                    return
            if full_guard:
                return C.RecoveryRun.guard(run, force=force)
            if not w.scan_done:
                w.scanning = True
                w.captured_hook = getattr(run, "_derived_scan_service", None)
                try:
                    w.sample = run.resource_size(category, root, limit, cap_metric="allocated")
                    w.scan_done = True
                finally:
                    w.scanning = False
        run.guard = Mock(side_effect=guard)
        def on_poll():
            self.assertFalse(w.scanning, "collector callback inside scan")
            w.callbacks += 1
        w.invoke = lambda: run.command(["injected-owned-child"], "fake-command", cap=90, on_poll=on_poll)
        children = [("entry-" + str(n), fixtures.resource_info(n + 1, 1, inode=n + 1)) for n in range(entries)]
        with self.fake_child(active=True) as child, fixtures.injected_resource_tree({root: children}) as fs:
            w.child, w.fs = child, fs
            registered = {}
            def register(pipe, events, index):
                registered[pipe.fileno()] = SimpleNamespace(fileobj=pipe, data=index)
            child.selector.register.side_effect = register
            child.selector.unregister.side_effect = lambda pipe: registered.pop(pipe.fileno())
            child.selector.get_map.side_effect = lambda: registered
            def select(timeout):
                w.events.append(("select", w.walked, timeout))
                if w.select_fault:
                    w.select_fault()
                # Deliberately reverse order to keep fairness independent of fd.
                return [(key, 1) for key in reversed(list(registered.values()))]
            child.selector.select.side_effect = select
            def write(index, data):
                w.events.append(("write", w.walked, index, len(data)))
                if w.write_fault:
                    return w.write_fault(index, data)
                return len(data)
            def read(fd, amount):
                w.events.append(("read", w.walked, fd, amount))
                for index, stream in enumerate(child.log_streams):
                    stream.write.side_effect = lambda data, index=index: write(index, data)
                if w.read_fault:
                    return w.read_fault(fd, amount)
                return bytes([fd - 10]) * w.bytes if w.scanning or w.keep_pipes else b""
            def poll():
                w.events.append(("poll", w.walked))
                if w.poll_fault:
                    return w.poll_fault()
                return 0
            child.process.poll.side_effect = poll
            def stop(process, end, *, state, clock):
                w.cleanup_hook.append(getattr(run, "_derived_scan_service", None))
                state["returncode"] = 0
                return child.cleanup
            child.stop.side_effect = stop
            for entry in fs.entries.values():
                original = entry.stat.return_value
                def visit(*, follow_symlinks, info=original):
                    self.assertFalse(follow_symlinks)
                    w.walked += 1
                    w.events.append(("stat", w.walked))
                    if w.stat_fault:
                        return w.stat_fault(info)
                    return info
                entry.stat.side_effect = visit
            with patch.object(C.os, "read", side_effect=read), patch.object(C, "tree_size", side_effect=tree):
                yield w

    @staticmethod
    def captured(call):
        try:
            return call(), None
        except BaseException as error:
            return None, error

    def assert_cleaned(self, w):
        self.assertIsNone(w.run._derived_scan_service)
        self.assertEqual(w.cleanup_hook, [None])
        w.child.stop.assert_called_once()
        w.child.selector.close.assert_called_once()
        for stream in w.child.log_streams + [w.child.process.stdout, w.child.process.stderr]:
            stream.close.assert_called_once()

    def test_progress_both_pipes_and_walker_has_bounded_operation_gap(self):
        with self.world() as w:
            output = w.invoke()
            quanta = [e[1] for e in w.events if e[0] == "select" and e[2] == 0]
            self.assertEqual(quanta, [61, 125, 189])
            self.assertEqual(w.walked, 200)
            self.assertEqual(w.sample["entries"], 200)
            self.assertEqual(w.sample["allocated_bytes"], 200 * 512)
            self.assertEqual(output, b"e" * 9)
            for index, point in enumerate(quanta):
                batch = [e for e in w.events if e[1] == point]
                self.assertEqual(len([e for e in batch if e[0] == "read"]), 2)
                self.assertEqual(len([e for e in batch if e[0] == "poll"]), 1)
                self.assertEqual(len([e for e in batch if e[0] == "disk"]), 2)
                self.assertEqual(len([e for e in batch if e[0] == "log_check"]), 1)
            self.assertTrue(all(e[3] == 65536 for e in w.events if e[0] == "read"))
            self.assertEqual(w.callbacks, 1)
            self.assertEqual(w.run.flush.call_count, 2)
            self.assertEqual([e for e in w.events if e[0] == "barrier"], [("barrier", 200)])
            self.assertEqual(w.run.record["commands"][0]["stdout_sha256"], C.sha(output))
            self.assertEqual(w.run.record["commands"][0]["stderr_sha256"], C.sha(b"f" * 9))
            self.assert_cleaned(w)

    def test_elapsed_quantum_services_before_sixty_four_checkpoints(self):
        with self.world(entries=4) as w:
            def stat_value(info):
                self.clock.now += .051
                return info
            w.stat_fault = stat_value
            w.invoke()
            self.assertEqual([e[1] for e in w.events if e[0] == "select" and e[2] == 0], [1, 2, 3])

    def test_single_slot_backpressure_allows_producer_progress_during_walk(self):
        with self.world() as w:
            slots = {111: b"a", 112: b"b"}
            producer_progress = {111: 0, 112: 0}
            def read(fd, amount):
                if not w.scanning:
                    return b""
                # A fake producer cannot publish its next chunk while its one
                # slot is full. Each read frees exactly one slot, then the
                # producer refills it; no thread/process runs in this fixture.
                data, slots[fd] = slots[fd], None
                self.assertIsNotNone(data)
                producer_progress[fd] += 1
                slots[fd] = data
                return data
            w.read_fault = read
            self.assertEqual(w.invoke(), b"aaa")
            self.assertEqual(producer_progress, {111: 3, 112: 3})
            self.assertEqual(w.walked, 200)
            self.assert_cleaned(w)

    def test_continuous_stdout_and_stderr_stop_at_original_stream_cap(self):
        with self.world(entries=17000, data_bytes=65536) as w:
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("stream cap", str(error))
            self.assertEqual(w.walked, 16445)
            writes = [e for e in w.events if e[0] == "write"]
            self.assertEqual(sum(e[3] for e in writes if e[2] == 0), 16 * C.MIB)
            self.assertEqual(sum(e[3] for e in writes if e[2] == 1), 16 * C.MIB)
            self.assertFalse(w.scan_done)
            self.assert_cleaned(w)

    def test_early_zero_does_not_skip_late_allocation_or_unknown_blocks(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid), self.world(entries=130) as w:
                def visit(info):
                    if w.walked == 130:
                        info.st_blocks = None if invalid else C.DERIVED_CAP // 512
                    return info
                w.stat_fault = visit
                _, error = self.captured(w.invoke)
                self.assertIsInstance(error, C.ResourceAccountingFailure if invalid else C.RunFailure)
                self.assertEqual(w.walked, 130)
                self.assertFalse(w.scan_done)
                self.assertIsNone(w.sample)
                self.assertFalse(any(e[0] == "barrier" for e in w.events))
                w.child.process.wait.assert_not_called()
                self.assertEqual(w.run.record["commands"][0]["process_observation"]["first_observed_exit"]["returncode"], 0)
                self.assert_cleaned(w)

    def test_hardlink_growth_sparse_and_dense_accounting_survives_quanta(self):
        with self.world(entries=130) as w:
            def visit(info):
                info.st_ino = 7
                info.st_size = 8 * C.GIB
                info.st_blocks = 0 if w.walked <= 64 else 2
                return info
            w.stat_fault = visit
            w.invoke()
            self.assertEqual(w.sample["logical_bytes"], 130 * 8 * C.GIB)
            self.assertEqual(w.sample["allocated_bytes"], 66 * 1024)
            for entry in w.fs.entries.values():
                entry.stat.assert_called_once_with(follow_symlinks=False)

    def test_early_zero_does_not_bypass_entry_limit(self):
        with self.world(entries=130) as w:
            original = w.run.resource_size
            def bounded(category, root, cap, **kwargs):
                if category == "derived_data":
                    kwargs["max_entries"] = 129
                return original(category, root, cap, **kwargs)
            w.run.resource_size = bounded
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("entry-count", str(error))
            self.assertEqual(w.walked, 130)
            self.assertIsNone(w.sample)
            w.child.process.wait.assert_not_called()
            self.assert_cleaned(w)

    def test_collector_guard_can_pump_without_recursive_collector_or_flush(self):
        with self.world(entries=130) as w:
            original_guard = w.run.guard.side_effect
            first = True
            def guard(force=False):
                nonlocal first
                # The first active-loop guard waits for the collector's call.
                if w.run.groups and first and not force:
                    first = False
                    return
                return original_guard(force=force)
            w.run.guard.side_effect = guard
            callbacks = []
            def collector():
                self.assertFalse(w.scanning)
                callbacks.append("enter")
                w.run.guard()
                callbacks.append("returned")
            output = w.run.command(["fake-child"], "collector-test", cap=90, on_poll=collector)
            self.assertEqual(callbacks, ["enter", "returned"])
            self.assertEqual(output, b"e" * 6)
            self.assertEqual(w.run.flush.call_count, 2)
            self.assertEqual(len(w.run.record["commands"]), 1)
            w.child.start.assert_called_once()
            self.assert_cleaned(w)

    def test_blocking_io_error_does_not_starve_other_pipe_or_poll(self):
        with self.world(entries=130) as w:
            def read(fd, amount):
                if w.scanning and fd == 112:
                    raise BlockingIOError()
                return b"ok" if w.scanning else b""
            w.read_fault = read
            self.assertEqual(w.invoke(), b"okok")
            self.assertEqual(len([e for e in w.events if e[0] == "log_check"]), 2)
            self.assert_cleaned(w)

    def test_log_allocated_growth_and_entry_cap_fail_before_second_quantum(self):
        for mode in ("allocation", "entries"):
            with self.subTest(mode=mode), self.world() as w:
                logs = w.run.output / "logs"
                children = ([("allocation", fixtures.resource_info(1, C.LOG_CAP // 512))]
                            if mode == "allocation" else [(str(n), fixtures.resource_info()) for n in range(257)])
                # Retain the outer DerivedData entries, replace only log scan.
                original = C.os.scandir.side_effect
                def scan(path):
                    if path != logs:
                        return original(path)
                    @contextmanager
                    def entries():
                        yield iter(SimpleNamespace(path=str(logs / n), stat=lambda follow_symlinks, info=i: i)
                                   for n, i in children)
                    return entries()
                with patch.object(C.os, "scandir", side_effect=scan):
                    _, error = self.captured(w.invoke)
                self.assertIsInstance(error, C.RunFailure)
                self.assertEqual(len([e for e in w.events if e[0] == "select"]), 1)
                self.assertFalse(w.scan_done)
                self.assertEqual(w.run.record["resource_scan"]["last"]["category"], "derived_data")
                self.assertEqual(w.run.record["resource_scan"]["last"]["state"], "failed")
                if mode == "allocation":
                    self.assertEqual(w.run.record["resource_cap_crossing"]["category"], "logs")
                    self.assertEqual(w.run.record["resource_cap_crossing"]["cap_metric"], "max_logical_allocated")
                self.assert_cleaned(w)

    def test_output_and_logs_scans_do_not_pump(self):
        for category in ("output", "logs"):
            with self.subTest(category=category), self.world(category=category) as w:
                w.invoke()
                self.assertEqual([e for e in w.events if e[0] == "select" and e[2] == 0], [])
                self.assertEqual(w.walked, 400 if category == "logs" else 200)

    def test_full_terminal_guard_catches_output_growth_after_earlier_snapshot(self):
        with self.world(full_guard=True) as w:
            original = C.os.scandir.side_effect
            def scan(path):
                if path != w.run.output or not any(e[0] == "write" for e in w.events):
                    return original(path)
                @contextmanager
                def grown():
                    yield iter([SimpleNamespace(path=str(path / "grown-log-storage"),
                                                stat=lambda follow_symlinks: fixtures.resource_info(1, C.OUTPUT_CAP // 512))])
                return grown()
            with patch.object(C.os, "scandir", side_effect=scan), patch.object(C, "write_json"):
                _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertEqual(w.run.record["resource_cap_crossing"]["category"], "output")
            self.assertEqual(len(w.run.last_samples), 1)
            self.assertEqual(w.run.last_samples[0]["output"]["allocated_bytes"], 0)
            w.child.process.wait.assert_called_once_with(timeout=0)
            self.assert_cleaned(w)

    def test_full_guard_last_root_failure_does_not_publish_partial_sample(self):
        with self.world(full_guard=True) as w:
            original = C.os.scandir.side_effect
            primary = C.DeadlineFailure("late logs traversal")
            def scan(path):
                if path == w.run.output / "logs" and not w.scanning:
                    raise primary
                return original(path)
            with patch.object(C.os, "scandir", side_effect=scan), patch.object(C, "write_json") as writes:
                _, error = self.captured(w.invoke)
            self.assertIs(error, primary)
            self.assertEqual(w.run.last_samples, [])
            writes.assert_not_called()
            w.child.process.wait.assert_not_called()
            self.assert_cleaned(w)

    def test_full_guard_retains_sample_count_cap_after_hook_progress(self):
        with self.world(full_guard=True) as w:
            w.run.last_samples = [{}] * 2000
            with patch.object(C, "write_json") as writes:
                _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("observation cap", str(error))
            self.assertEqual(len(w.run.last_samples), 2001)
            writes.assert_not_called()
            w.child.process.wait.assert_not_called()
            self.assert_cleaned(w)

    def test_reentrant_hook_fails_closed_without_second_select(self):
        with self.world() as w:
            w.read_fault = lambda fd, amount: w.captured_hook()
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.ConfigurationFailure)
            self.assertIn("reentrant", str(error))
            self.assertEqual(len([e for e in w.events if e[0] == "select"]), 1)
            self.assertEqual(w.callbacks, 0)
            self.assert_cleaned(w)

    def test_descendant_held_pipes_after_zero_do_not_imply_eof_or_success(self):
        with self.world(entries=65) as w:
            w.keep_pipes = True
            def poll():
                if w.scan_done:
                    self.clock.now = w.run.command_deadline
                return 0
            w.poll_fault = poll
            original_select = w.child.selector.select.side_effect
            def select(timeout):
                if w.scan_done:
                    self.clock.now = min(self.clock.now + 20, w.run.command_deadline)
                return original_select(timeout)
            w.child.selector.select.side_effect = select
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.DeadlineFailure)
            observation = w.run.record["commands"][0]["process_observation"]
            self.assertNotIn("stdout_eof", observation)
            self.assertNotIn("stderr_eof", observation)
            w.child.process.wait.assert_not_called()
            self.assert_cleaned(w)

    def test_free_floor_between_quanta_prevents_next_read_and_write(self):
        with self.world() as w:
            def visit(info):
                if w.walked == 100:
                    w.free = C.ABORT_BYTES - 1
                return info
            w.stat_fault = visit
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("8 GiB", str(error))
            self.assertEqual(len([e for e in w.events if e[0] == "read"]), 2)
            self.assertEqual(len([e for e in w.events if e[0] == "write"]), 2)
            self.assertEqual(w.walked, 125)
            self.assert_cleaned(w)

    def test_single_blocked_query_has_no_service_until_return_and_then_fails(self):
        with self.world() as w:
            def delayed_disk(path):
                w.events.append(("blocked_disk", w.walked))
                self.assertEqual(len([e for e in w.events if e[0] == "select"]), 0)
                self.clock.now = w.run.command_deadline
                return SimpleNamespace(free=24 * C.GIB)
            w.run.disk_usage = delayed_disk
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.DeadlineFailure)
            self.assertEqual(len([e for e in w.events if e[0] == "read"]), 0)
            self.assertEqual(len([e for e in w.events if e[0] == "blocked_disk"]), 1)
            self.assertFalse(w.scan_done)
            self.assert_cleaned(w)

    def test_each_returning_service_boundary_checks_original_deadline(self):
        for point in ("stat", "select", "read", "write", "poll", "log", "barrier"):
            with self.subTest(point=point), self.world() as w:
                def expire(*args):
                    self.clock.now = w.run.command_deadline
                    if point == "stat":
                        return args[0]
                    if point == "read":
                        return b"data"
                    if point == "write":
                        return len(args[1])
                    if point == "poll":
                        return 0
                setattr(w, point + "_fault", expire)
                _, error = self.captured(w.invoke)
                self.assertIsInstance(error, C.DeadlineFailure)
                self.assertEqual(w.run.record["commands"][0]["end_deadline_elapsed"], 90)
                if point in ("stat", "select", "read"):
                    self.assertFalse(any(e[0] == "write" for e in w.events))
                self.assert_cleaned(w)

    def test_early_exit_zero_plus_final_barrier_cost_can_correctly_fail(self):
        with self.world() as w:
            def costly_barrier():
                self.assertIsNone(w.run._derived_scan_service)
                self.clock.now = w.run.command_deadline
            w.barrier_fault = costly_barrier
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.DeadlineFailure)
            self.assertTrue(w.scan_done)
            w.child.process.wait.assert_called_once_with(timeout=0)
            self.assertEqual(w.run.record["commands"][0]["exit_code"], 0)
            self.assert_cleaned(w)

    def test_primary_survives_diagnostic_and_sticky_cleanup_failure(self):
        with self.world() as w:
            primary = C.DeadlineFailure("original")
            def fail():
                raise primary
            w.select_fault = fail
            w.run.record_exception_origin = Mock(side_effect=KeyboardInterrupt("secondary"))
            w.child.cleanup["success"] = False
            w.child.cleanup["errors"] = ["sticky-owned-failure"]
            _, error = self.captured(w.invoke)
            self.assertIs(error, primary)
            self.assertFalse(w.run.record["commands"][0]["cleanup"]["success"])
            self.assert_cleaned(w)

    def test_short_or_error_write_cannot_succeed_or_skip_cleanup(self):
        for mode in ("short", "error"):
            with self.subTest(mode=mode), self.world() as w:
                def write(index, data):
                    if mode == "short":
                        return len(data) - 1
                    raise OSError("injected write error")
                w.write_fault = write
                _, error = self.captured(w.invoke)
                self.assertIsInstance(error, C.RunFailure if mode == "short" else OSError)
                self.assertFalse(w.scan_done)
                self.assertEqual(len([e for e in w.events if e[0] == "read"]), 1)
                self.assert_cleaned(w)

    def test_eof_is_only_recorded_after_empty_read(self):
        with self.world(entries=65, data_bytes=0) as w:
            w.invoke()
            observation = w.run.record["commands"][0]["process_observation"]
            self.assertTrue(observation["stdout_eof"]["observed"])
            self.assertTrue(observation["stderr_eof"]["observed"])
            self.assertEqual(len([e for e in w.events if e[0] == "read"]), 2)
            self.assertFalse(any(e[0] == "log_check" for e in w.events))
            self.assert_cleaned(w)

    def test_late_eof_observation_cannot_poll_after_work_deadline(self):
        with self.world(entries=65, data_bytes=0) as w:
            observe = w.run.observe_runtime
            def late(event, *args, **kwargs):
                value = observe(event, *args, **kwargs)
                if event == "stdout_eof":
                    self.clock.now = w.run.command_deadline
                return value
            w.run.observe_runtime = late
            _, error = self.captured(w.invoke)
            self.assertIsInstance(error, C.DeadlineFailure)
            w.child.process.poll.assert_not_called()
            self.assert_cleaned(w)

    def test_hook_is_cleared_before_cleanup_and_cannot_leak_next_command(self):
        with self.world(entries=65) as w:
            w.invoke()
            stale = w.captured_hook
            self.assert_cleaned(w)
            _, error = self.captured(stale)
            self.assertIsInstance(error, C.ConfigurationFailure)
            self.assertIn("Invalid", str(error))
            w.scan_done = False
            w.walked = 0
            w.cleanup_hook.clear()
            w.child.stop.reset_mock()
            w.child.selector.close.reset_mock()
            for stream in w.child.log_streams + [w.child.process.stdout, w.child.process.stderr]:
                stream.close.reset_mock()
            # New streams/Popen are fake and command name is deliberately new.
            w.run.command(["injected-owned-child"], "next-command", cap=90)
            self.assertIsNot(w.captured_hook, stale)
            self.assertIsNone(w.run._derived_scan_service)
            self.assertEqual(w.cleanup_hook, [None])

    def test_setup_failure_installs_no_hook(self):
        run = self.run_fixture()
        run.guard = Mock()
        run.flush = Mock()
        with self.fake_child() as child:
            child.selector.register.side_effect = OSError("registration failed")
            _, error = self.captured(lambda: run.command(["fake"], "setup"))
            self.assertIsInstance(error, OSError)
            self.assertIsNone(run._derived_scan_service)
            child.stop.assert_called_once()

    def test_cleanup_mode_uses_plain_tick(self):
        with self.world() as w:
            w.run.cleanup_mode = True
            w.invoke()
            self.assertIsNone(w.captured_hook)
            self.assertFalse(any(e[0] == "select" and e[2] == 0 for e in w.events))


if __name__ == "__main__":
    unittest.main()
