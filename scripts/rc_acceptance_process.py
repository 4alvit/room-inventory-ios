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


def bounded_capture(argv, *, cwd=None, env=None, timeout=8, limit=4 * 1024**2, receipt=None, stdout_path=None, stderr_path=None, cleanup_parent_deadline=None, on_stdout=None, work_deadline=None):
    """One isolated process with cooperative deadlines; preserve primary errors.

    An explicit absolute parent deadline lets cleanup retain one four-second
    window after late work. It never extends that parent or renews cleanup.
    Other callers retain the original combined work-plus-cleanup deadline.
    An optional absolute work deadline also debits delayed capture entry. Its
    pre-spawn/return checks are cooperative; a blocked OS call is not preempted.
    """
    record = {} if receipt is None else receipt
    start = time.monotonic()
    work_end = start + timeout
    end = work_end + 4 if cleanup_parent_deadline is None else cleanup_parent_deadline
    process = None
    selector = selectors.DefaultSelector()
    output = {'stdout': bytearray(), 'stderr': bytearray()}
    failure = None
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
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        record.update(pid=process.pid, pgid=process.pid)
        for label, pipe in (('stdout', process.stdout), ('stderr', process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, label)
        while selector.get_map() or process.poll() is None:
            if time.monotonic() >= work_end:
                raise CaptureFailure('Metadata command work deadline exceeded')
            for key, _ in selector.select(min(.05, max(0, work_end - time.monotonic()))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                else:
                    if len(output[key.data]) + len(chunk) > limit:
                        raise CaptureFailure('Metadata command stream cap exceeded')
                    output[key.data].extend(chunk)
                    if key.data == 'stdout' and on_stdout is not None:
                        if time.monotonic() >= work_end:
                            raise CaptureFailure('Metadata command work deadline exceeded')
                        on_stdout(chunk, work_end)
                        if time.monotonic() >= work_end:
                            raise CaptureFailure('Metadata command work deadline exceeded')
        if time.monotonic() >= work_end:
            raise CaptureFailure('Metadata command completed after work deadline')
        record['returncode'] = process.returncode
        if process.returncode != 0:
            raise CaptureFailure('Metadata command exited ' + str(process.returncode))
    except BaseException as error:
        failure = error
    finally:
        if process is not None:
            state = {}
            record['cleanup'] = kill_owned(process, end, state=state)
            record['cleanup_state'] = state
            if not record['cleanup']['success'] and failure is None:
                failure = CaptureFailure('Metadata command terminal group state unproved')
        for key in list(selector.get_map().values()):
            key.fileobj.close()
        selector.close()
        record.update(elapsed_seconds=time.monotonic() - start,
                      stdout_bytes=len(output['stdout']), stderr_bytes=len(output['stderr']))
        # Preserve the actual bounded streams even on a timeout/nonzero exit.
        for path, label in ((stdout_path, 'stdout'), (stderr_path, 'stderr')):
            if path is not None:
                with open(path, 'xb') as stream:
                    stream.write(output[label])
        if failure is not None:
            record['error'] = type(failure).__name__ + ': ' + str(failure)
    if failure is not None:
        raise failure
    return bytes(output['stdout'])
