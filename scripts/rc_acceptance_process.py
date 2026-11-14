"""Bounded process ownership for the separate hosted RC acceptance workflow.

kill_owned is copied byte-for-byte from the reviewed Recovery controller.
After a leader is reaped, only non-destructive group observation is permitted.
"""
import errno
import os
import math
import selectors
import signal
import subprocess
import threading
import time

def kill_owned(process, deadline, *, state=None, clock=time.monotonic, sleep=time.sleep, killpg=os.killpg):
    state = {} if state is None else state
    state.setdefault("group_state", "unverified")
    state.setdefault("leader_reaped", False)
    state.setdefault("returncode", None)
    state.setdefault("observation_errors", [])
    start = clock()
    end = min(deadline, start + 4, state.get("cleanup_deadline_monotonic", float("inf")))
    state["cleanup_deadline_monotonic"] = end
    report = {"pgid": process.pid, "signals": [], "errors": [], "success": False, "budget_exhausted": False}

    def error(operation, exception):
        item = {"operation": operation, "errno": getattr(exception, "errno", None), "error": type(exception).__name__}
        report["errors"].append(item)
        state["observation_errors"].append(item)

    def note_known_reap():
        code = getattr(process, "returncode", None)
        if code is not None:
            state["returncode"] = code
            state["leader_reaped"] = True

    def observe():
        if clock() >= end:
            report["budget_exhausted"] = True
            return False
        note_known_reap()
        if not state["leader_reaped"]:
            try:
                state["returncode"] = process.wait(timeout=0)
                state["leader_reaped"] = True
            except subprocess.TimeoutExpired:
                pass
            except OSError as exception:
                error("leader_reap", exception)
        if clock() >= end:
            report["budget_exhausted"] = True
            return False
        if state["group_state"] == "absent":
            return state["leader_reaped"]
        try:
            killpg(process.pid, 0)
            state["group_state"] = "present"
        except OSError as exception:
            if exception.errno == errno.ESRCH:
                state["group_state"] = "absent"
            else:
                state["group_state"] = "unknown"
                error("group_probe", exception)
        return state["group_state"] == "absent" and state["leader_reaped"]

    def send(sig):
        # Reaping releases the leader PID; its numeric PGID is no longer a
        # destructive-signal capability. Unknown observations stay failures.
        note_known_reap()
        if (clock() >= end or state["leader_reaped"]
                or state["group_state"] != "present" or state["observation_errors"]):
            return
        try:
            killpg(process.pid, sig)
            report["signals"].append(sig.name)
        except OSError as exception:
            if exception.errno == errno.ESRCH:
                state["group_state"] = "absent"
            else:
                state["group_state"] = "unknown"
                error("group_signal_" + sig.name, exception)

    done = observe()
    for sig, phase_end in ((signal.SIGTERM, min(start + 2, max(start, end - 2))), (signal.SIGKILL, end)):
        if done or clock() >= end:
            break
        send(sig)
        done = observe()
        while not done and clock() < phase_end:
            sleep(min(.05, max(0, phase_end - clock())))
            done = observe()
    report.update({key: state[key] for key in ("group_state", "leader_reaped", "returncode")})
    report["success"] = done and not state["observation_errors"]
    report["budget_exhausted"] |= not done and clock() >= end
    report["elapsed_seconds"] = clock() - start
    return report


class CaptureFailure(RuntimeError):
    pass


class CaptureTrace:
    """Optional bounded scalar observations, never command acceptance evidence."""
    PHASES = frozenset(('admitted', 'popen_begin', 'popen_end', 'poll_begin', 'poll_end',
        'select_begin', 'select_end', 'read_begin', 'read_end', 'stdout_callback_begin',
        'stdout_callback_end', 'work_expired', 'work_completed', 'cleanup_begin',
        'cleanup_end', 'pipe_close_begin', 'pipe_close_end', 'persist_begin', 'persist_end'))
    FIELDS = frozenset(('timeout_seconds', 'pid', 'returncode', 'ready', 'stream', 'bytes'))
    TERMINAL = frozenset(('work_expired', 'cleanup_begin', 'cleanup_end', 'pipe_close_end', 'persist_end'))
    MAX_EVENTS = 2048
    MAX_COUNT = 65535

    def __init__(self):
        self._lock = threading.Lock()
        self.events, self.counts, self.last, self.terminal = [], {}, None, {}
        self.max_gap_ns, self.max_gap_pair = 0, None
        self.dropped, self.incomplete = 0, False

    def __call__(self, phase, **fields):
        with self._lock:
            if not isinstance(phase, str) or phase not in self.PHASES or set(fields) - self.FIELDS:
                self.incomplete = True
                return
            row = {'phase': phase, 'monotonic_ns': time.monotonic_ns(),
                   'cpu_ns': time.process_time_ns()}
            if any(type(row[key]) is not int or not 0 <= row[key] < 2**63
                   for key in ('monotonic_ns', 'cpu_ns')):
                self.incomplete = True
                return
            for key, value in fields.items():
                if value is None:
                    continue
                if (type(value) not in (int, float) or not -2**63 < value < 2**63
                        or not math.isfinite(value)):
                    self.incomplete = True
                    return
                row[key] = value
            if self.last is not None:
                gap = row['monotonic_ns'] - self.last['monotonic_ns']
                if gap < 0:
                    self.incomplete = True
                if gap > self.max_gap_ns:
                    self.max_gap_ns = gap
                    self.max_gap_pair = {'previous': dict(self.last), 'next': dict(row)}
            self.last = row
            self.counts[phase] = min(self.MAX_COUNT, self.counts.get(phase, 0) + 1)
            if phase in self.TERMINAL:
                self.terminal[phase] = row
            if len(self.events) < self.MAX_EVENTS:
                self.events.append(row)
            else:
                self.dropped = min(self.MAX_COUNT, self.dropped + 1)
                self.incomplete = True

    def result(self):
        with self._lock:
            return {'events': [dict(row) for row in self.events], 'counts': dict(self.counts),
                'last': None if self.last is None else dict(self.last),
                'terminal': {key: dict(row) for key, row in self.terminal.items()},
                'max_gap_ns': self.max_gap_ns,
                'max_gap_pair': None if self.max_gap_pair is None else {
                    key: dict(row) for key, row in self.max_gap_pair.items()},
                'dropped': self.dropped, 'incomplete': self.incomplete,
                'diagnostic_only': True}


def bounded_capture(argv, *, cwd=None, env=None, timeout=8, limit=4 * 1024**2, receipt=None, stdout_path=None, stderr_path=None, cleanup_parent_deadline=None, on_stdout=None, work_deadline=None, phase_sink=None):
    """One isolated process with cooperative deadlines; preserve primary errors.

    An explicit absolute parent deadline lets cleanup retain one four-second
    window after late work. It never extends that parent or renews cleanup.
    Other callers retain the original combined work-plus-cleanup deadline.
    An optional absolute work deadline also debits delayed capture entry. Its
    pre-spawn/return checks are cooperative; a blocked OS call is not preempted.
    An optional nonblocking scalar phase observer consumes these same deadlines.
    It receives no argv or stream data; on_stdout retains that separate role.
    """
    record = {} if receipt is None else receipt
    start = time.monotonic()
    work_end = start + timeout
    end = work_end + 4 if cleanup_parent_deadline is None else cleanup_parent_deadline
    process = None
    selector = selectors.DefaultSelector()
    output = {'stdout': bytearray(), 'stderr': bytearray()}
    failure = None
    finalizing = observer_disabled = False

    def phase(name, **fields):
        nonlocal failure, observer_disabled
        if observer_disabled:
            return
        try:
            phase_sink(name, **fields)
        except Exception:
            observer_disabled = True
            record['phase_observer_error'] = True
        except BaseException as error:
            observer_disabled = True
            record['phase_observer_aborted'] = True
            if failure is None:
                failure = error
            if not finalizing:
                raise failure
        if time.monotonic() >= (end if finalizing else work_end):
            if failure is None:
                failure = CaptureFailure('Phase observer exceeded existing command deadline')
            if not finalizing:
                raise failure

    def observed_poll():
        phase('poll_begin')
        value = process.poll()
        phase('poll_end', returncode=value)
        return value

    record.update(command=list(argv), timeout_seconds=timeout, cleanup_reserved_seconds=4)
    try:
        if work_deadline is not None:
            if type(work_deadline) not in (int,float) or not math.isfinite(work_deadline):
                raise CaptureFailure('Invalid absolute work deadline')
            work_end=min(work_end,work_deadline,end-4)
            record.update(timeout_seconds=max(0,work_end-start),
                          work_deadline_monotonic=work_end,cleanup_deadline_monotonic=end)
            if time.monotonic()>=work_end:
                raise CaptureFailure('Metadata command work deadline exceeded before spawn')
        if phase_sink is not None:
            phase('admitted', timeout_seconds=record['timeout_seconds'])
            phase('popen_begin')
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        record.update(pid=process.pid, pgid=process.pid)
        for label, pipe in (('stdout', process.stdout), ('stderr', process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, label)
        # Publish the spawn boundary only after both pipe registrations, so a
        # cancelled observer cannot interrupt ownership bookkeeping.
        if phase_sink is not None:
            phase('popen_end', pid=process.pid)
        while selector.get_map() or (process.poll() if phase_sink is None else observed_poll()) is None:
            if time.monotonic() >= work_end:
                failure = CaptureFailure('Metadata command work deadline exceeded')
                if phase_sink is not None:
                    phase('work_expired')
                raise failure
            if phase_sink is not None:
                phase('select_begin')
            ready = selector.select(min(.05, max(0, work_end - time.monotonic())))
            if phase_sink is not None:
                phase('select_end', ready=len(ready))
            for key, _ in ready:
                if phase_sink is not None:
                    phase('read_begin', stream=0 if key.data == 'stdout' else 1)
                chunk = os.read(key.fd, 65536)
                if phase_sink is not None:
                    phase('read_end', stream=0 if key.data == 'stdout' else 1, bytes=len(chunk))
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                else:
                    if len(output[key.data]) + len(chunk) > limit:
                        raise CaptureFailure('Metadata command stream cap exceeded')
                    output[key.data].extend(chunk)
                    if key.data == 'stdout' and on_stdout is not None:
                        if phase_sink is not None:
                            phase('stdout_callback_begin')
                        if time.monotonic() >= work_end:
                            raise CaptureFailure('Metadata command work deadline exceeded')
                        on_stdout(chunk, work_end)
                        if time.monotonic() >= work_end:
                            raise CaptureFailure('Metadata command work deadline exceeded')
                        if phase_sink is not None:
                            phase('stdout_callback_end')
        if time.monotonic() >= work_end:
            raise CaptureFailure('Metadata command completed after work deadline')
        record['returncode'] = process.returncode
        if process.returncode != 0:
            raise CaptureFailure('Metadata command exited ' + str(process.returncode))
        if phase_sink is not None:
            phase('work_completed')
    except BaseException as error:
        failure = error
    finally:
        finalizing = True
        if process is not None:
            state = {}
            if phase_sink is not None:
                phase('cleanup_begin')
            record['cleanup'] = kill_owned(process, end, state=state)
            record['cleanup_state'] = state
            if not record['cleanup']['success'] and failure is None:
                failure = CaptureFailure('Metadata command terminal group state unproved')
            if phase_sink is not None:
                phase('cleanup_end')
        if phase_sink is not None:
            phase('pipe_close_begin')
        for key in list(selector.get_map().values()):
            key.fileobj.close()
        selector.close()
        if phase_sink is not None:
            phase('pipe_close_end')
        record.update(elapsed_seconds=time.monotonic() - start,
                      stdout_bytes=len(output['stdout']), stderr_bytes=len(output['stderr']))
        # Preserve the actual bounded streams even on a timeout/nonzero exit.
        if phase_sink is not None:
            phase('persist_begin')
        for path, label in ((stdout_path, 'stdout'), (stderr_path, 'stderr')):
            if path is not None:
                with open(path, 'xb') as stream:
                    stream.write(output[label])
        if phase_sink is not None:
            phase('persist_end')
        if failure is not None:
            record['error'] = type(failure).__name__ + ': ' + str(failure)
    if failure is not None:
        raise failure
    return bytes(output['stdout'])
