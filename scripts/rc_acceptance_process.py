"""Bounded process ownership for the separate hosted RC acceptance workflow.

kill_owned retains the reviewed Recovery controller's ownership rules.
After a leader is reaped, only non-destructive group observation is permitted.
"""
import errno
import os
import selectors
import signal
import subprocess
import time

def _phase(sink, name, **fields):
    # Diagnostics never replace a command's primary error or ownership decision.
    if sink is not None:
        try:
            sink(name, **fields)
        except Exception:
            pass


def kill_owned(process, deadline, *, state=None, clock=time.monotonic, sleep=time.sleep, killpg=os.killpg, phase_sink=None):
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
                _phase(phase_sink, 'wait_begin')
                state["returncode"] = process.wait(timeout=0)
                _phase(phase_sink, 'wait_end', returncode=state["returncode"])
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
            _phase(phase_sink, 'group_probe_begin')
            killpg(process.pid, 0)
            _phase(phase_sink, 'group_probe_end')
            state["group_state"] = "present"
        except OSError as exception:
            _phase(phase_sink, 'group_probe_error', errno=exception.errno)
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
            _phase(phase_sink, 'signal_begin', signal=int(sig))
            killpg(process.pid, sig)
            _phase(phase_sink, 'signal_end', signal=int(sig))
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


def bounded_capture(argv, *, cwd=None, env=None, timeout=8, limit=4 * 1024**2, receipt=None, stdout_path=None, stderr_path=None, phase_sink=None, stream_sink=None):
    """One isolated process, bounded pipes/work/cleanup; preserve primary errors."""
    record = {} if receipt is None else receipt
    start = time.monotonic()
    work_end = start + timeout
    end = work_end + 4
    process = None
    selector = selectors.DefaultSelector()
    output = {'stdout': bytearray(), 'stderr': bytearray()}
    failure = None
    record.update(command=list(argv), timeout_seconds=timeout, cleanup_reserved_seconds=4)
    _phase(phase_sink, 'admitted', timeout=timeout)
    try:
        _phase(phase_sink, 'popen_begin')
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        record.update(pid=process.pid, pgid=process.pid)
        _phase(phase_sink, 'popen_end', pid=process.pid)
        for label, pipe in (('stdout', process.stdout), ('stderr', process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, label)
        def poll():
            _phase(phase_sink, 'poll_begin')
            code = process.poll()
            _phase(phase_sink, 'poll_end', returncode=code)
            return code
        while selector.get_map() or poll() is None:
            _phase(phase_sink, 'loop')
            if time.monotonic() >= work_end:
                _phase(phase_sink, 'work_expired')
                raise CaptureFailure('Metadata command work deadline exceeded')
            _phase(phase_sink, 'select_begin')
            ready = selector.select(min(.05, max(0, work_end - time.monotonic())))
            _phase(phase_sink, 'select_end')
            for key, _ in ready:
                _phase(phase_sink, 'read_begin')
                chunk = os.read(key.fd, 65536)
                _phase(phase_sink, 'read_end', bytes=len(chunk))
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                else:
                    if len(output[key.data]) + len(chunk) > limit:
                        if stream_sink is not None:
                            output[key.data].extend(chunk[:max(0, limit-len(output[key.data]))])
                        raise CaptureFailure('Metadata command stream cap exceeded')
                    output[key.data].extend(chunk)
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
            _phase(phase_sink, 'cleanup_begin')
            record['cleanup'] = kill_owned(process, end, state=state, **({'phase_sink': phase_sink} if phase_sink is not None else {}))
            _phase(phase_sink, 'cleanup_end')
            record['cleanup_state'] = state
            if not record['cleanup']['success'] and failure is None:
                failure = CaptureFailure('Metadata command terminal group state unproved')
        _phase(phase_sink, 'pipe_close_begin')
        for key in list(selector.get_map().values()):
            key.fileobj.close()
        selector.close()
        _phase(phase_sink, 'pipe_close_end')
        record.update(elapsed_seconds=time.monotonic() - start,
                      stdout_bytes=len(output['stdout']), stderr_bytes=len(output['stderr']))
        if stream_sink is not None:
            try:
                stream_sink(bytes(output['stdout']), bytes(output['stderr']))
            except Exception:
                record['stream_sink_failed'] = True
        # Preserve the actual bounded streams even on a timeout/nonzero exit.
        _phase(phase_sink, 'persist_begin')
        for path, label in ((stdout_path, 'stdout'), (stderr_path, 'stderr')):
            if path is not None:
                with open(path, 'xb') as stream:
                    stream.write(output[label])
        _phase(phase_sink, 'persist_end')
        if failure is not None:
            record['error'] = type(failure).__name__ + ': ' + str(failure)
    if failure is not None:
        raise failure
    return bytes(output['stdout'])
