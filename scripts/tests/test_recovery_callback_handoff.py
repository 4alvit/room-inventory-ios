"""Real command/guard regression tests with injected filesystem and child I/O."""
import contextlib
import hashlib
import stat
from types import SimpleNamespace
import unittest

import test_recovery_device_service as fixtures

C = fixtures.C


class CallbackWorld(fixtures.World):
    """Exercise both owned resource roots through RecoveryRun.guard itself."""

    def __init__(self, *, completion_stage="outer", completion_category="device"):
        super().__init__(actual_guard=True, count=200)
        self.completion_stage = completion_stage
        self.completion_category = completion_category
        self.stage, self.category = "setup", None
        self.child_finished = False
        self.callback_calls = self.callback_completions = 0
        self.visits = {}
        self.callback_fault = self.callback_finished_fault = self.entry_fault = None
        self.callback_polls = 0
        self.callback_reads = []
        self.finished_before_callback = None
        self.sent = set()
        self.run.guard = self.guard
        self.poll_action = self.child_poll
        self.read_action = self.child_read

    def __enter__(self):
        super().__enter__()
        self.run.prepare_derived_resource_root()
        return self

    def can_finish(self):
        return (self.child_finished or
                (self.stage == self.completion_stage and
                 self.category == self.completion_category))

    def child_poll(self):
        if self.stage == "callback":
            self.callback_polls += 1
        if self.can_finish():
            self.child_finished = True
            return 0
        return None

    def child_read(self, fd):
        if not self.can_finish():
            raise BlockingIOError()
        if self.stage == "callback":
            self.callback_reads.append(fd)
            # First-observation cases must service bytes as well as exit/EOF.
            if self.completion_stage == "callback" and fd not in self.sent:
                self.sent.add(fd)
                return b"out" if fd == 111 else b"err"
        return b""

    def guard(self, force=False):
        previous = self.stage
        if force and self.cleaned:
            self.stage = "terminal"
            self.events.append(("terminal_start",))
        elif self.stage != "callback":
            self.stage = "outer" if self.run.groups else "precommand"
        try:
            return C.RecoveryRun.guard(self.run, force=force)
        finally:
            self.stage = previous

    def callback(self):
        self.callback_calls += 1
        self.events.append(("callback_enter", self.callback_calls))
        self.finished_before_callback = self.child_finished
        assert not self.scanning
        self.stage = "callback"
        try:
            # A real collector callback can reach its periodic guard after I/O.
            self.clock.now += 2.1
            if self.callback_fault:
                self.callback_fault()
            self.run.guard()
            if self.callback_finished_fault:
                self.callback_finished_fault()
            self.callback_completions += 1
            self.events.append(("callback_complete", self.callback_completions))
        finally:
            self.stage = "setup"

    @contextlib.contextmanager
    def scan(self, root):
        category = ("derived_data" if root == self.run.derived else
                    "device" if root == self.root else None)
        previous_category, previous_scanning = self.category, self.scanning
        self.category, self.scanning = category, category is not None
        stage = self.stage

        def entries():
            for number in range(self.count if category is not None else 0):
                def inspect(*, follow_symlinks, number=number):
                    assert follow_symlinks is False
                    key = (stage, category)
                    self.visits[key] = self.visits.get(key, 0) + 1
                    info = SimpleNamespace(st_size=1, st_blocks=1,
                                           st_mode=stat.S_IFREG, st_dev=1,
                                           st_ino=number + 2)
                    if self.entry_fault:
                        self.entry_fault(stage, category, info)
                    return info
                yield SimpleNamespace(path=str(root / str(number)), stat=inspect)

        try:
            yield entries()
        finally:
            self.category, self.scanning = previous_category, previous_scanning


class CallbackHandoffTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        denials = stack.enter_context(fixtures.runtime_guard())
        self.addCleanup(lambda: self.assertEqual(denials, []))
        self.addCleanup(lambda: self.assertEqual(fixtures._IMPORT_DENIALS, []))

    def assert_single_cleanup(self, world):
        self.assertTrue(world.cleaned)
        self.assertEqual(sum(event[0] == "spawn" for event in world.events), 1)
        self.assertEqual(sum(event[0] == "cleanup" for event in world.events), 1)

    def assert_callback_failure(self, world, *, completed=0):
        self.assertEqual(world.callback_calls, 1)
        self.assertEqual(world.callback_completions, completed)
        self.assertIsNone(world.record["post_command_accounting"])
        self.assertFalse(any(stage == "terminal" for stage, _ in world.visits))
        self.assert_single_cleanup(world)

    def assert_complete(self, world):
        self.assertEqual(world.callback_calls, 1)
        self.assertEqual(world.callback_completions, 1)
        self.assertGreater(world.callback_polls, 0)
        for category in ("derived_data", "device"):
            self.assertEqual(world.visits[("callback", category)], world.count)
            self.assertEqual(world.visits[("terminal", category)], world.count)
            self.assertEqual(world.run.last_samples[-1][category]["entries"], world.count)
        record = world.record
        self.assertEqual(record["post_command_accounting"]["status"], "COMPLETED")
        self.assertTrue(record["cleanup"]["leader_reaped"])
        self.assertEqual(record["cleanup"]["group_state"], "absent")
        order = [event[0] for event in world.events]
        self.assertLess(order.index("callback_complete"), order.index("cleanup"))
        self.assertLess(order.index("cleanup"), order.index("terminal_start"))
        self.assert_single_cleanup(world)

    def test_outer_device_handoff_callback_completes_full_guard_once(self):
        with CallbackWorld(completion_category="device") as world:
            self.assertEqual(world.invoke(), b"")
            self.assertEqual(world.record["device_scan_handoff"]["state"], "incomplete")
            self.assertTrue(world.finished_before_callback)
            self.assertLess(world.visits[("outer", "device")], world.count)
            self.assert_complete(world)

    def test_outer_derived_handoff_callback_completes_full_guard_once(self):
        with CallbackWorld(completion_category="derived_data") as world:
            self.assertEqual(world.invoke(), b"")
            self.assertEqual(world.record["derived_scan_handoff"]["state"], "incomplete")
            self.assertTrue(world.finished_before_callback)
            self.assertLess(world.visits[("outer", "derived_data")], world.count)
            self.assert_complete(world)

    def test_callback_first_observes_exit_and_drains_both_pipes_during_full_guard(self):
        for category in ("derived_data", "device"):
            with self.subTest(category=category), CallbackWorld(
                    completion_stage="callback", completion_category=category) as world:
                self.assertEqual(world.invoke(), b"out")
                self.assertFalse(world.finished_before_callback)
                self.assertEqual(sorted(world.callback_reads), [111, 111, 112, 112])
                self.assertEqual(world.record["stdout_sha256"], hashlib.sha256(b"out").hexdigest())
                self.assertEqual(world.record["stderr_sha256"], hashlib.sha256(b"err").hexdigest())
                self.assertNotIn("derived_scan_handoff", world.record)
                self.assertNotIn("device_scan_handoff", world.record)
                self.assert_complete(world)

    def test_callback_deadline_is_enforced_inside_each_scan_and_after_return(self):
        for point in ("derived_data", "device", "return"):
            with self.subTest(point=point), CallbackWorld() as world:
                def expire(stage, category, info):
                    if stage == "callback" and category == point:
                        world.clock.now = world.run.command_deadline
                world.entry_fault = expire
                if point == "return":
                    world.callback_finished_fault = lambda: setattr(
                        world.clock, "now", world.run.command_deadline)
                self.assertIsInstance(fixtures.failure(world.invoke), C.DeadlineFailure)
                self.assert_callback_failure(world, completed=int(point == "return"))

    def test_callback_ownership_checks_remain_active_in_each_scan(self):
        for target in ("derived_data", "device"):
            with self.subTest(category=target), CallbackWorld() as world:
                def replace_ledger(stage, category, info):
                    if stage == "callback" and category == target:
                        world.run.groups[-1]["record"] = {}
                world.entry_fault = replace_ledger
                error = fixtures.failure(world.invoke)
                self.assertIsInstance(error, C.ConfigurationFailure)
                self.assertIn("scan owner", str(error))
                self.assert_callback_failure(world)

    def test_callback_resource_caps_and_scan_errors_remain_primary(self):
        for target in ("derived_data", "device"):
            for mode in ("cap", "stat"):
                with self.subTest(category=target, mode=mode), CallbackWorld() as world:
                    original = OSError("callback stat failed")
                    def reject_entry(stage, category, info):
                        if stage == "callback" and category == target:
                            if mode == "stat":
                                raise original
                            cap = C.DERIVED_CAP if target == "derived_data" else C.DEVICE_CAP
                            info.st_blocks = cap // 512 + 1
                    world.entry_fault = reject_entry
                    error = fixtures.failure(world.invoke)
                    if mode == "stat":
                        self.assertIs(error, original)
                    else:
                        self.assertIsInstance(error, C.RunFailure)
                        self.assertEqual(world.run.record["resource_cap_crossing"]["category"], target)
                    self.assert_callback_failure(world)

    def test_fresh_terminal_scan_rejects_growth_after_successful_callback(self):
        for target in ("derived_data", "device"):
            with self.subTest(category=target), CallbackWorld() as world:
                def grow(stage, category, info):
                    if stage == "terminal" and category == target:
                        cap = C.DERIVED_CAP if target == "derived_data" else C.DEVICE_CAP
                        info.st_blocks = cap // 512 + 1
                world.entry_fault = grow
                self.assertIsInstance(fixtures.failure(world.invoke), C.RunFailure)
                self.assertEqual(world.callback_calls, 1)
                self.assertEqual(world.callback_completions, 1)
                self.assertEqual(world.record["post_command_accounting"]["status"], "FAILED")
                self.assertEqual(world.run.record["resource_cap_crossing"]["category"], target)
                self.assert_single_cleanup(world)


if __name__ == "__main__":
    unittest.main()
