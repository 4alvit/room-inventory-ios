"""Producer-only xcresult races through real command, guard and tree walkers.

All children, filesystem syscalls, clocks and process cleanup are injected.
"""
import contextlib
import errno
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_recovery_device_service as fixtures

C = fixtures.C


def info(size=0, blocks=0, mode=stat.S_IFREG, inode=10):
    return SimpleNamespace(st_size=size, st_blocks=blocks, st_mode=mode,
                           st_dev=1, st_ino=inode)


def missing(label="renamed temporary"):
    return FileNotFoundError(errno.ENOENT, label)


class ResultWorld(fixtures.World):
    def __init__(self):
        super().__init__(actual_guard=True)
        self.output = self.run.output
        self.result = self.run.xcresult = self.output / "original.xcresult"
        self.data = self.result / "Data"
        self.temporary = self.data / "_tmp.example"
        self.payload = self.data / "payload"
        self.run.xctestrun = self.output / "selected.xctestrun"
        self.run.record.update(phase="test", test_count=1)
        self.infos = {self.output: info(mode=stat.S_IFDIR, inode=1),
                      self.run.derived: info(mode=stat.S_IFDIR, inode=2),
                      self.output / "logs": info(mode=stat.S_IFDIR, inode=3),
                      self.root: info(mode=stat.S_IFDIR, inode=4)}
        self.children = {}
        self.faults = {}
        self.category = None
        self.auto_result = True
        self.open_action = self.stat_action = self.close_action = None
        self.lstat_action = None
        self.observations = []
        self.run.guard = lambda force=False: C.RecoveryRun.guard(self.run, force=True)
        resource_size = self.run.resource_size

        def scoped_resource(category, *args, **kwargs):
            previous, self.category = self.category, category
            try:
                return resource_size(category, *args, **kwargs)
            finally:
                self.category = previous
        self.run.resource_size = scoped_resource

    @property
    def stage(self):
        return "terminal" if self.cleaned else "active" if self.run.groups else "initial"

    def install_result(self):
        self.infos[self.result] = info(mode=stat.S_IFDIR, blocks=1, inode=20)
        self.infos[self.data] = info(mode=stat.S_IFDIR, blocks=1, inode=21)
        self.infos[self.temporary] = info(size=5, blocks=1, inode=22)
        self.infos[self.payload] = info(size=7, blocks=2, inode=23)
        self.children[self.output] = [self.result]
        self.children[self.result] = [self.data]
        self.children[self.data] = [self.temporary, self.payload]

    def fault(self, operation, path):
        failure = self.faults.get((self.category, self.stage, operation, path))
        if failure is not None:
            raise failure

    def observe_entry(self, path):
        def observe(*, follow_symlinks):
            assert follow_symlinks is False
            self.observations.append((self.category, self.stage, "stat", path))
            if self.stat_action:
                self.stat_action(path)
            self.fault("stat", path)
            if path not in self.infos:
                raise missing(str(path))
            return self.infos[path]
        return SimpleNamespace(path=str(path), stat=observe)

    def scan(self, path):
        self.observations.append((self.category, self.stage, "open", path))
        if self.open_action:
            self.open_action(path)
        self.fault("open", path)

        @contextlib.contextmanager
        def opened():
            self.fault("enter", path)
            try:
                def entries():
                    yield from [self.observe_entry(child) for child in self.children.get(path, [])]
                    self.fault("iterate", path)
                yield entries()
            finally:
                if self.close_action:
                    self.close_action(path)
                self.fault("close", path)
        return opened()

    def lstat(self, path):
        self.observations.append((self.category, self.stage, "lstat", path))
        if self.lstat_action:
            self.lstat_action(path)
        if path not in self.infos:
            raise missing(str(path))
        return self.infos[path]

    def spawn(self, *args, **kwargs):
        if self.auto_result:
            self.install_result()
        return super().spawn(*args, **kwargs)

    def __enter__(self):
        super().__enter__()
        self.run.device_root = self.run.device_id = None
        for name, replacement in [
                ("lstat", lambda path: self.lstat(path)),
                ("exists", lambda path: path in self.infos),
                ("is_dir", lambda path: path in self.infos and stat.S_ISDIR(self.infos[path].st_mode)),
                ("is_symlink", lambda path: path in self.infos and stat.S_ISLNK(self.infos[path].st_mode))]:
            self.stack.enter_context(patch.object(Path, name, replacement))
        self.run.bind_output_resource_root()
        return self

    def invoke(self):
        args = ["xcodebuild", "test-without-building", "-xctestrun", self.run.xctestrun,
                "-only-testing:" + C.CASE, "-resultBundlePath", self.result]
        return self.run.command(args, "ui-test", cap=90, xcresult_producer=True,
                                on_poll=self.callback)


class VanishedResultTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))

    def assert_cleanup(self, world):
        self.assertEqual(sum(e[0] == "spawn" for e in world.events), 1)
        self.assertEqual(sum(e[0] == "cleanup" for e in world.events), 1)
        self.assertTrue(world.record["cleanup"]["leader_reaped"])
        self.assertEqual(world.record["cleanup"]["group_state"], "absent")

    def test_active_child_stat_race_in_both_walks_completes_fresh_terminal_accounting(self):
        for category in ("output", "original_xcresult"):
            with self.subTest(category=category), ResultWorld() as w:
                w.faults[category, "active", "stat", w.temporary] = missing()
                self.assertEqual(w.invoke(), b"")
                active = [s[category] for s in w.run.last_samples
                          if s["original_xcresult"]["lifecycle"] == "producing"]
                self.assertTrue(active)
                self.assertEqual(active[0]["vanished_entries"], 1)
                self.assertEqual(active[0]["attempted_entries"], active[0]["entries"] + 1)
                self.assertEqual(active[0]["logical_bytes"], 7)
                terminal = w.run.last_samples[-1][category]
                self.assertEqual(terminal["logical_bytes"], 12)
                self.assertNotIn("vanished_entries", terminal)
                self.assertEqual(w.record["post_command_accounting"]["status"], "COMPLETED")
                self.assert_cleanup(w)

    def test_queued_directory_race_preserves_already_observed_allocation(self):
        for category in ("output", "original_xcresult"):
            with self.subTest(category=category), ResultWorld() as w:
                w.faults[category, "active", "open", w.data] = missing("queued Data")
                w.invoke()
                active = next(s[category] for s in w.run.last_samples
                              if s["original_xcresult"]["lifecycle"] == "producing")
                self.assertEqual(active["vanished_directories"], 1)
                self.assertEqual(active["allocated_bytes"], 1024 if category == "output" else 512)
                self.assert_cleanup(w)

    def test_missing_root_before_first_creation_then_mid_output_appearance(self):
        with ResultWorld() as w:
            w.auto_result = False
            def appear(path):
                if w.stage == "active" and w.category == "output" and path == w.output:
                    w.install_result()
            w.open_action = appear
            w.faults["output", "active", "stat", w.temporary] = missing()
            w.invoke()
            self.assertEqual(w.record["post_command_accounting"]["status"], "COMPLETED")
            self.assert_cleanup(w)

    def test_mid_output_appearance_binds_before_descending_not_after_missing_child(self):
        with ResultWorld() as w:
            w.auto_result = False
            def appear(path):
                if w.stage == "active" and w.category == "output" and path == w.output:
                    w.install_result()
            def replace(path):
                if w.stage == "active" and w.category == "output" and path == w.temporary:
                    w.infos[w.result] = info(mode=stat.S_IFDIR, inode=999)
            w.open_action, w.stat_action = appear, replace
            w.faults["output", "active", "stat", w.temporary] = missing()
            self.assertIsInstance(fixtures.failure(w.invoke), C.ResourceAccountingFailure)
            self.assertIsNone(w.record["post_command_accounting"])
            self.assert_cleanup(w)

    def test_root_loss_replacement_and_symlink_after_observation_fail(self):
        for root_name in ("output", "result"):
            for mutation in ("missing", "inode", "symlink"):
                with self.subTest(root=root_name, mutation=mutation), ResultWorld() as w:
                    target = getattr(w, root_name)
                    def mutate(path):
                        if w.stage == "active" and w.category == "original_xcresult" and path == w.temporary:
                            if mutation == "missing":
                                del w.infos[target]
                            else:
                                w.infos[target] = info(mode=stat.S_IFLNK if mutation == "symlink" else stat.S_IFDIR,
                                                      inode=999)
                    w.stat_action = mutate
                    w.faults["original_xcresult", "active", "stat", w.temporary] = missing()
                    self.assertIsInstance(fixtures.failure(w.invoke), (C.RunFailure, FileNotFoundError))
                    self.assertIsNone(w.record["post_command_accounting"])
                    self.assert_cleanup(w)

    def test_output_sibling_and_original_root_enoent_are_never_excused(self):
        for name in ("other", "original.xcresult-lookalike", "original.xcresult"):
            with self.subTest(name=name), ResultWorld() as w:
                target = w.output / name
                original = missing(name)
                def include(path):
                    if w.stage == "active" and path == w.output and target not in w.children[w.output]:
                        w.children[w.output].append(target)
                w.open_action = include
                w.faults["output", "active", "stat", target] = original
                self.assertIsInstance(fixtures.failure(w.invoke), (C.RunFailure, FileNotFoundError))
                self.assertIsNone(w.record["post_command_accounting"])
                self.assert_cleanup(w)

    def test_non_enoent_and_iterator_context_errors_remain_original(self):
        for operation, failure in [("stat", OSError(errno.EIO, "io")),
                                   ("stat", PermissionError(errno.EACCES, "denied")),
                                   ("stat", FileNotFoundError(errno.EIO, "wrong errno")),
                                   ("enter", missing("enter")), ("iterate", missing("iterate")),
                                   ("close", missing("close"))]:
            with self.subTest(operation=operation, error=str(failure)), ResultWorld() as w:
                target = w.temporary if operation == "stat" else w.data
                w.faults["original_xcresult", "active", operation, target] = failure
                self.assertIs(fixtures.failure(w.invoke), failure)
                self.assert_cleanup(w)

    def test_terminal_stat_race_is_strict_after_actual_producer_cleanup(self):
        for category in ("output", "original_xcresult"):
            with self.subTest(category=category), ResultWorld() as w:
                original = missing("terminal temporary")
                w.faults[category, "active", "stat", w.temporary] = missing("active temporary")
                w.faults[category, "terminal", "stat", w.temporary] = original
                self.assertIs(fixtures.failure(w.invoke), original)
                self.assertEqual(w.record["post_command_accounting"]["status"], "FAILED")
                self.assertEqual(w.record["exit_code"], 0)
                self.assert_cleanup(w)

    def test_terminal_root_loss_after_cleanup_is_not_an_optional_empty_tree(self):
        for root_name in ("output", "result"):
            with self.subTest(root=root_name), ResultWorld() as w:
                target = getattr(w, root_name)
                w.cleanup_action = lambda: w.infos.pop(target)
                self.assertIsInstance(fixtures.failure(w.invoke), FileNotFoundError)
                self.assertEqual(w.record["post_command_accounting"]["status"], "FAILED")
                self.assertEqual(w.record["exit_code"], 0)
                self.assert_cleanup(w)

    def test_postscan_identity_check_detects_replacement_without_any_missing_child(self):
        with ResultWorld() as w:
            def replace(path):
                if w.stage == "active" and w.category == "original_xcresult" and path == w.result:
                    w.infos[w.result] = info(mode=stat.S_IFDIR, inode=999)
            w.close_action = replace
            self.assertIsInstance(fixtures.failure(w.invoke), C.ResourceAccountingFailure)
            self.assertIsNone(w.record["post_command_accounting"])
            self.assert_cleanup(w)

    def test_expired_stat_does_not_start_an_identity_query(self):
        with ResultWorld() as w:
            observed = []
            def expire(path):
                if w.stage == "active" and w.category == "original_xcresult" and path == w.temporary:
                    observed.append(len([x for x in w.observations if x[2] == "lstat"]))
                    w.clock.now = w.run.command_deadline
            w.stat_action = expire
            w.faults["original_xcresult", "active", "stat", w.temporary] = missing()
            self.assertIsInstance(fixtures.failure(w.invoke), C.DeadlineFailure)
            self.assertEqual(len([x for x in w.observations if x[2] == "lstat"]), observed[0])
            self.assert_cleanup(w)

    def test_stale_producer_during_missing_child_fails(self):
        for mode in ("phase", "count", "ledger"):
            with self.subTest(mode=mode), ResultWorld() as w:
                def stale(path):
                    if w.stage == "active" and w.category == "original_xcresult" and path == w.temporary:
                        if mode == "phase": w.run.record["phase"] = "collect"
                        elif mode == "count": w.run.record["test_count"] = 2
                        else: w.run.groups[-1] = dict(w.run.groups[-1])
                w.stat_action = stale
                w.faults["original_xcresult", "active", "stat", w.temporary] = missing()
                self.assertIsInstance(fixtures.failure(w.invoke), C.ConfigurationFailure)
                self.assert_cleanup(w)

    def test_first_observed_result_must_be_an_ordinary_directory(self):
        for mode in (stat.S_IFLNK, stat.S_IFREG):
            with self.subTest(mode=mode), ResultWorld() as w:
                w.auto_result = False
                def appear(path):
                    if w.stage == "active" and w.category == "output" and path == w.output:
                        w.install_result()
                        w.infos[w.result] = info(mode=mode, inode=20)
                w.open_action = appear
                self.assertIsInstance(fixtures.failure(w.invoke), C.ResourceAccountingFailure)
                self.assertFalse(any(x[2:] == ("open", w.result) for x in w.observations))
                self.assert_cleanup(w)

    def test_late_identity_read_cannot_authorize_vanished_child(self):
        with ResultWorld() as w:
            validating = []
            def notice(path):
                if w.stage == "active" and w.category == "original_xcresult" and path == w.temporary:
                    validating.append(True)
            def late(path):
                if validating and path == w.output:
                    w.clock.now = w.run.command_deadline
            w.stat_action, w.lstat_action = notice, late
            w.faults["original_xcresult", "active", "stat", w.temporary] = missing()
            self.assertIsInstance(fixtures.failure(w.invoke), C.DeadlineFailure)
            self.assertIsNone(w.record["post_command_accounting"])
            self.assert_cleanup(w)

    def test_active_byte_caps_are_not_discounted_by_missing_entries(self):
        for category, cap in (("output", C.OUTPUT_CAP), ("original_xcresult", C.ACTIVE_XCRESULT_CAP)):
            for metric in ("logical", "allocated"):
                with self.subTest(category=category, metric=metric), ResultWorld() as w:
                    def enlarge(path):
                        if w.stage == "active" and w.category == category and path == w.payload:
                            w.infos[path] = info(size=cap if metric == "logical" else 0,
                                                 blocks=cap // 512 if metric == "allocated" else 0)
                    w.stat_action = enlarge
                    w.faults[category, "active", "stat", w.temporary] = missing()
                    self.assertIsInstance(fixtures.failure(w.invoke), C.RunFailure)
                    self.assertEqual(w.run.record["resource_cap_crossing"]["category"], category)
                    self.assertEqual(w.run.record["resource_cap_crossing"]["cap_bytes"], cap)
                    self.assertIsNone(w.record["post_command_accounting"])
                    self.assert_cleanup(w)

    def test_active_original_root_scandir_failure_stays_strict(self):
        with ResultWorld() as w:
            original = missing("root open")
            w.faults["original_xcresult", "active", "open", w.result] = original
            self.assertIs(fixtures.failure(w.invoke), original)
            self.assert_cleanup(w)

    def test_callers_cannot_override_resource_observer_or_path_validation(self):
        for category in ("output", "original_xcresult", "device", "derived_data"):
            for keyword, value in (("entry_observer", lambda path, observed: None),
                                   ("vanished_path_check", lambda path: None)):
                with self.subTest(category=category, keyword=keyword), ResultWorld() as w:
                    self.assertIsInstance(fixtures.failure(lambda: w.run.resource_size(
                        category, w.output, C.OUTPUT_CAP, **{keyword: value})), C.ConfigurationFailure)
                    self.assertFalse(any(x[2] == "open" for x in w.observations))

    def test_generic_observer_error_is_not_reclassified_as_vanished_stat(self):
        with ResultWorld() as w:
            w.install_result()
            original = missing("observer")
            calls = []
            def observer(path, observed):
                calls.append(path)
                if path == w.temporary: raise original
            ignored = []
            self.assertIs(fixtures.failure(lambda: C.tree_size(
                w.result, C.XCRESULT_CAP, w.run.tick, vanished_path_check=ignored.append,
                entry_observer=observer)), original)
            self.assertEqual(ignored, [])
            self.assertEqual(calls[:2], [w.result, w.data])

    def test_mutually_exclusive_vanished_policies_fail_before_traversal(self):
        with ResultWorld() as w:
            self.assertIsInstance(fixtures.failure(lambda: C.tree_size(
                w.output, C.OUTPUT_CAP, w.run.tick, vanished_child_check=lambda: None,
                vanished_path_check=lambda path: None)), C.RunFailure)
            self.assertFalse(any(x[2] == "open" for x in w.observations))

    def test_vanished_attempts_remain_bounded(self):
        with ResultWorld() as w:
            w.install_result()
            w.category = "direct"
            w.faults["direct", "initial", "stat", w.temporary] = missing()
            w.faults["direct", "initial", "stat", w.payload] = missing()
            accepted = []
            error = fixtures.failure(lambda: C.tree_size(
                w.result, C.XCRESULT_CAP, w.run.tick, max_entries=2,
                vanished_path_check=accepted.append))
            self.assertIsInstance(error, C.RunFailure)
            self.assertIn("entry-count cap", str(error))
            self.assertEqual(accepted, [w.temporary])
            self.assertFalse(any(x[2:] == ("stat", w.payload) for x in w.observations))


if __name__ == "__main__":
    unittest.main()
