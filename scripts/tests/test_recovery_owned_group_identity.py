"""AST-loaded actual cleanup with inert clocks/processes/signals only."""
import ast
import errno
from pathlib import Path
import signal
import subprocess
from types import SimpleNamespace
import unittest

def forbidden(*args, **kwargs): raise AssertionError("real operation forbidden")
source = Path(__file__).resolve().parents[1] / "run-recovery-journey.py"
node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "kill_owned")
scope = {"os":SimpleNamespace(killpg=forbidden), "time":SimpleNamespace(monotonic=forbidden,sleep=forbidden),
         "subprocess":SimpleNamespace(TimeoutExpired=subprocess.TimeoutExpired),"signal":signal,"errno":errno}
exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),"exec"),scope)
kill_owned = scope["kill_owned"]

class Clock:
    now=100.0
    def __call__(self): return self.now
    def sleep(self,seconds): self.now+=seconds
class Process:
    pid=4242
    def __init__(self,running=True,returncode=None): self.running,self.returncode,self.waits=running,returncode,0
    def wait(self,timeout):
        self.waits+=1
        if self.running: raise subprocess.TimeoutExpired("inert",timeout)
        self.returncode=0 if self.returncode is None else self.returncode
        return self.returncode

class PostReapIdentityTests(unittest.TestCase):
    def run_cleanup(self,process,action,state=None,clock=None):
        clock=clock or Clock()
        result=kill_owned(process,clock()+100,state={} if state is None else state,clock=clock,sleep=clock.sleep,killpg=action)
        return result,clock

    def test_reaped_present_never_signals_and_cannot_renew_deadline(self):
        calls=[];state={};process=Process(running=False)
        result,clock=self.run_cleanup(process,lambda p,s:calls.append(s),state)
        self.assertFalse(result["success"]);self.assertTrue(result["leader_reaped"])
        self.assertTrue(result["budget_exhausted"]);self.assertEqual(result["signals"],[])
        self.assertTrue(calls and all(s==0 for s in calls));self.assertEqual(clock(),104.0)
        later,_=self.run_cleanup(process,forbidden,state,clock)
        self.assertFalse(later["success"]);self.assertEqual(state["cleanup_deadline_monotonic"],104.0)

    def test_known_returncode_is_not_reaped_again_or_signalled(self):
        process=Process(returncode=0);process.wait=forbidden;calls=[]
        result,_=self.run_cleanup(process,lambda p,s:calls.append(s))
        self.assertFalse(result["success"]);self.assertTrue(result["leader_reaped"])
        self.assertTrue(all(s==0 for s in calls))

    def test_reap_between_probe_and_send_blocks_destructive_signal(self):
        process=Process();calls=[]
        def probe(pid,sig): calls.append(sig);process.returncode=0
        result,_=self.run_cleanup(process,probe)
        self.assertFalse(result["success"]);self.assertEqual(result["signals"],[])
        self.assertTrue(all(s==0 for s in calls))

    def test_reap_after_term_prevents_later_kill(self):
        process=Process();calls=[]
        def action(pid,sig):
            calls.append(sig)
            if sig==signal.SIGTERM: process.running=False
        result,_=self.run_cleanup(process,action)
        self.assertFalse(result["success"]);self.assertEqual(result["signals"],["SIGTERM"])
        self.assertNotIn(signal.SIGKILL,calls)

    def test_eperm_after_reap_is_sticky_even_after_absence(self):
        process=Process(running=False);calls=[];state={}
        def probe(pid,sig):
            calls.append(sig)
            if len(calls)==1: raise PermissionError(errno.EPERM,"inert denied")
            raise ProcessLookupError(errno.ESRCH,"inert absent")
        result,clock=self.run_cleanup(process,probe,state)
        self.assertFalse(result["success"]);self.assertEqual(result["signals"],[])
        self.assertEqual(state["observation_errors"][0]["errno"],errno.EPERM)
        later,_=self.run_cleanup(process,forbidden,state,clock)
        self.assertFalse(later["success"]);self.assertEqual(later["group_state"],"absent")

    def test_unreaped_owned_group_still_gets_term_then_kill(self):
        process=Process();calls=[]
        def action(pid,sig):
            calls.append(sig)
            if sig==signal.SIGKILL: process.running,process.returncode=False,-9
            if process.returncode is not None: raise ProcessLookupError(errno.ESRCH,"inert absent")
        result,_=self.run_cleanup(process,action)
        self.assertTrue(result["success"])
        self.assertEqual([s for s in calls if s],[signal.SIGTERM,signal.SIGKILL])

    def test_reaped_absent_succeeds_without_destructive_signal(self):
        process=Process(returncode=0);calls=[]
        def absent(pid,sig): calls.append(sig);raise ProcessLookupError(errno.ESRCH,"inert absent")
        result,_=self.run_cleanup(process,absent)
        self.assertTrue(result["success"]);self.assertEqual(calls,[0]);self.assertEqual(process.waits,0)

if __name__=="__main__": unittest.main()
