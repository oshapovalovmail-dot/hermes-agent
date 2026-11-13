import sys, ast, asyncio, threading, unittest, contextvars, uuid
from pathlib import Path
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch
R=Path(__file__).resolve().parent
sys.path.insert(0,str(R))
from test_inherited_proofs import ProofTests
from bootstrap import AUTHORITY
C=AUTHORITY.parent.parent

def method(name):
    tree=ast.parse((C/'gateway/session_authority.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SessionAuthority')
    fn=next(n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    mod=ast.Module(body=[fn],type_ignores=[])
    ns={'asyncio':asyncio,'partial':partial,'uuid':uuid,'SessionRef':lambda profile_id,session_id:SimpleNamespace(profile_id=profile_id,session_id=session_id),'native_write_started':contextvars.ContextVar('test_write_started',default=False)}
    exec(compile(mod,str(C/'gateway/session_authority.py'),'exec'),ns)
    return ns[name]

class AtomicTests(ProofTests):
    async def test_commit_callback_survives_cancel_and_claim_waits(self):
        from gateway import session_envelope, session_retry_admission
        from gateway import session_native_proofs as h
        native=method('_admit_native')
        a=self.authority;a.profile_id='fixture';a.db=None
        a._require_admission_open=lambda:None
        a._publish_route=lambda source,*args:SimpleNamespace(session_id='session')
        a._reserve_route=lambda source:()
        a._admission_gate=lambda fence:None
        a._schedule_admitted=lambda ref:None
        visible=threading.Event();release=threading.Event();seen=[]
        def write(**kwargs):
            visible.set()
            if not release.wait(3):raise TimeoutError('test barrier')
            return self.row
        a._admit_native_write=write
        a._admitted=lambda ref,event,row:(h.retain(a,event,row,first_insert=True) or row)
        async def prepare(runner,event):return {'native_text_v1':{'event':{'message_id':'17'}}}
        a.runner=SimpleNamespace()
        with patch.object(session_envelope,'prepare_native',prepare),patch.object(session_envelope,'restore_native_source',lambda payload:self.source),patch.object(session_retry_admission,'take',lambda *args:None),patch.object(session_retry_admission,'compose',lambda *args:None):
            caller=asyncio.create_task(native(a,self.event))
            self.assertTrue(await asyncio.to_thread(visible.wait,2))
            async def claim():
                async with h.handoff(a):seen.append('a' in a._native_admission_proofs)
            drainer=asyncio.create_task(claim())
            await asyncio.sleep(0)
            self.assertFalse(drainer.done())
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):await caller
            self.assertTrue(h.handoff(a).locked())
            self.assertFalse(drainer.done())
            release.set()
            await asyncio.wait_for(drainer,2)
            self.assertEqual(seen,[True])
            await asyncio.sleep(0)
            self.assertFalse([t for t in getattr(a,'_mutation_tasks',()) if not t.done()])

    async def test_missing_proof_typed_failure_records_failed(self):
        from gateway import session_finite
        from gateway.session_native_proofs import NativeAdmissionDenied
        execute=method('_execute_claimed')
        a=self.authority;a.pending_results={};a.executing={'session':1}
        live=SimpleNamespace(review=None,event_stream=SimpleNamespace(lock=threading.RLock()))
        async def denied(*args):raise NativeAdmissionDenied('native_admission_proof_unavailable')
        with patch.object(session_finite,'execute_finite_admission',denied):
            response,outcome=await execute(a,SimpleNamespace(session_id='session'),live,self.row)
        self.assertIsNone(response);self.assertEqual(outcome,'failed')
        self.assertTrue(a.pending_results['a']['result']['failed'])
        self.assertFalse(a.pending_results['a']['result']['completed'])
        self.assertEqual(a.executing,{})

if __name__=='__main__':
    suite=unittest.TestSuite(AtomicTests(n) for n in ['test_commit_callback_survives_cancel_and_claim_waits','test_missing_proof_typed_failure_records_failed'])
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not r.wasSuccessful())
