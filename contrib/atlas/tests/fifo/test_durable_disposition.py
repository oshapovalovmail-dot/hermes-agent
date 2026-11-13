import ast, asyncio, contextvars, tempfile, unittest, uuid
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from bootstrap import CORE, AUTHORITY
from test_inherited_proofs import ProofTests
import hermes_state_runtime as rt
from hermes_state import SessionDB


def method(name):
    tree=ast.parse(AUTHORITY.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SessionAuthority')
    fn=next(n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    ns={'admit_session_input':rt.admit_session_input,'mark_producer_admission':lambda *args:None}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(AUTHORITY),'exec'),ns)
    return ns[name]


class DurableDispositionTests(ProofTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.tmp=tempfile.TemporaryDirectory()
        self.db=SessionDB(db_path=Path(self.tmp.name)/'state.db')
        self.db.create_session('session',source='test')
        self.authority.db=self.db
        self.authority.epoch=rt.begin_runtime_epoch(self.db,instance_id='fixture')
        self.authority._publish_pending=lambda ref:None
        self.authority._receipt=lambda row:dict(row)
        self.write=method('_admit_native_write')
        self.admitted=method('_admitted')
        self.args=dict(principal_id='native-41',session_id='session',request_id='17',payload={'native_text_v1':{'event':{'message_id':'17'},'media':[]}},authorize=lambda conn:None)
    async def asyncTearDown(self):
        self.db.close();self.tmp.cleanup()
    def commit(self):
        row=self.write(self.authority,**self.args)
        receipt=self.admitted(self.authority,SimpleNamespace(session_id='session'),self.event,row)
        self.assertNotIn('_native_first_insert',receipt)
        self.assertNotIn('_native_first_insert',rt.get_session_admission(self.db,admission_id=row['admission_id']))
        return row
    async def test_sqlite_first_insert_retains_exact_original(self):
        row=self.commit()
        self.assertIs(self.authority._native_admission_proofs[row['admission_id']][5],self.binding)
        self.assertEqual(len(rt.list_session_admissions(self.db,session_id='session')),1)
    async def test_sqlite_replay_after_proof_loss_never_reissues(self):
        row=self.commit();self.hooks().drop(self.authority,row['admission_id'])
        self.assertEqual(self.commit()['admission_id'],row['admission_id'])
        self.assertNotIn(row['admission_id'],self.authority._native_admission_proofs)
    async def test_sqlite_terminal_exact_replay_never_reissues(self):
        row=self.commit();self.hooks().drop(self.authority,row['admission_id'])
        claimed=rt.claim_session_input(self.db,epoch=self.authority.epoch,session_id='session')
        rt.settle_session_input(self.db,epoch=self.authority.epoch,admission_id=row['admission_id'],generation=claimed['generation'],outcome='failed')
        self.assertEqual(self.commit()['status'],'terminal')
        self.assertNotIn(row['admission_id'],self.authority._native_admission_proofs)
    async def test_sqlite_retired_terminal_early_return_never_reissues(self):
        row=self.commit();self.hooks().drop(self.authority,row['admission_id'])
        claimed=rt.claim_session_input(self.db,epoch=self.authority.epoch,session_id='session')
        rt.settle_session_input(self.db,epoch=self.authority.epoch,admission_id=row['admission_id'],generation=claimed['generation'],outcome='failed')
        rt.mutate_runtime_session(self.db,epoch=self.authority.epoch,principal_id='human',session_id='session',request_id='delete',expected_revision=self.db.get_session('session')['runtime_revision'],expected_generation=claimed['generation'],operation='delete',payload={})
        self.assertEqual(self.commit()['status'],'terminal')
        self.assertNotIn(row['admission_id'],self.authority._native_admission_proofs)
    async def test_sqlite_replay_signal_stays_denied_across_write_retry(self):
        row=self.commit();self.hooks().drop(self.authority,row['admission_id'])
        import sqlite3
        original=self.db._execute_write
        sleep=self.db._sleep_before_write_retry
        seen=[]
        def retry(write):
            def attempt(conn):
                result=write(conn);seen.append(result['admission_id'])
                if len(seen)==1:raise sqlite3.OperationalError('database is locked')
                return result
            return original(attempt)
        def between_attempts(*args):
            # Real _execute_write rolled back and released its lock. A competing
            # retirement removes the row before the actual SQLite callback retry.
            original(lambda conn:conn.execute('DELETE FROM session_admissions WHERE admission_id=?',(row['admission_id'],)))
            return True
        self.db._execute_write=retry
        self.db._sleep_before_write_retry=between_attempts
        try:new=self.commit()
        finally:
            self.db._execute_write=original
            self.db._sleep_before_write_retry=sleep
        self.assertEqual(seen,[row['admission_id'],new['admission_id']])
        self.assertNotIn(new['admission_id'],self.authority._native_admission_proofs)
    async def test_sqlite_expired_revoked_binding_cannot_regrant(self):
        from telegram import Message
        row=self.commit();h=self.hooks()
        proof=self.authority._native_admission_proofs[row['admission_id']]
        self.authority._native_admission_proofs[row['admission_id']]=(proof[0]-601,*proof[1:])
        staff=self.gate.staff
        class DeniedStaff:
            async def verify(self,uid,name):return None
        self.gate.staff=DeniedStaff()
        try:
            with self.assertRaises(PermissionError):await self.gate.recheck(self.binding,None)
        finally:self.gate.staff=staff
        m=Message.de_json({'message_id':17,'date':1,'from':{'id':41,'is_bot':False,'first_name':'Fixture','username':'fixture_41'},'chat':{'id':41,'type':'private'},'text':'test'},None)
        newer=await self.gate.admit_message(m,None)
        self.gate.stamp_source(self.source,newer)
        replay=self.commit()
        self.assertEqual(replay['admission_id'],row['admission_id'])
        claimed=rt.claim_session_input(self.db,epoch=self.authority.epoch,session_id='session')
        with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),claimed,self.restored())
    async def test_sqlite_insert_rollback_retry_retains_original(self):
        import sqlite3
        original=self.db._execute_write;sleep=self.db._sleep_before_write_retry;attempts=[]
        def retry(write):
            def attempt(conn):
                result=write(conn);attempts.append(result['admission_id'])
                if len(attempts)==1:raise sqlite3.OperationalError('database is locked')
                return result
            return original(attempt)
        self.db._execute_write=retry;self.db._sleep_before_write_retry=lambda *args:True
        try:row=self.commit()
        finally:self.db._execute_write=original;self.db._sleep_before_write_retry=sleep
        self.assertEqual(len(attempts),2)
        self.assertNotEqual(*attempts)
        self.assertIs(self.authority._native_admission_proofs[row['admission_id']][5],self.binding)
        self.assertEqual(len(rt.list_session_admissions(self.db,session_id='session')),1)
    async def test_missing_disposition_cannot_mint(self):
        self.admitted(self.authority,SimpleNamespace(session_id='session'),self.event,self.row)
        self.assertNotIn('a',getattr(self.authority,'_native_admission_proofs',{}))
    async def test_capacity_refusal_cannot_mint_on_redelivery(self):
        h=self.hooks();old=h.MAX_PENDING;h.MAX_PENDING=0
        try:row=self.commit()
        finally:h.MAX_PENDING=old
        self.commit()
        self.assertNotIn(row['admission_id'],self.authority._native_admission_proofs)

if __name__=='__main__':
    names=[n for n in DurableDispositionTests.__dict__ if n.startswith('test_')]
    r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(DurableDispositionTests(n) for n in names))
    raise SystemExit(not r.wasSuccessful())
