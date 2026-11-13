import asyncio, copy, sys, unittest
from pathlib import Path
from types import SimpleNamespace
R=Path(__file__).resolve().parent
from bootstrap import CORE, DELTA
from gateway.atlas_admission import AdmissionGate, StaffProof, install_gate
from gateway.session import SessionSource
from gateway.config import Platform
from telegram import Message
class Staff:
    async def verify(self,uid,name):return StaffProof(uid,'fixture',True,True,False,name)
class ProofTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import gateway.atlas_admission as a
        a._GATE=None
        self.gate=AdmissionGate(Staff());install_gate(self.gate)
        self.authority=SimpleNamespace(epoch='epoch',_current_owner=lambda s:s)
        self.row={'admission_id':'a','request_id':'17','principal_id':'native-41','target_session_id':'session','seq':1,'status':'queued','generation':None}
        m=Message.de_json({'message_id':17,'date':1,'from':{'id':41,'is_bot':False,'first_name':'Fixture','username':'fixture_41'},'chat':{'id':41,'type':'private'},'text':'test'},None)
        self.binding=await self.gate.admit_message(m,None)
        self.source=SessionSource(platform=Platform.TELEGRAM,chat_id='41',user_id='41',chat_type='dm',profile='tg-41',message_id='17')
        self.gate.stamp_source(self.source,self.binding)
        self.event=SimpleNamespace(source=self.source)
    def hooks(self):
        import importlib.util
        spec=importlib.util.find_spec('gateway.session_native_proofs')
        self.assertIsNotNone(spec,'durable FIFO lacks process-local admission proof handoff')
        from gateway import session_native_proofs
        return session_native_proofs
    def restored(self):return SimpleNamespace(source=SessionSource.from_dict(self.source.to_dict()))
    async def test_exact_admission_restores_same_opaque_not_wire(self):
        h=self.hooks();h.retain(self.authority,self.event,self.row,first_insert=True)
        e=self.restored();self.assertIsNone(getattr(e.source,'_atlas_binding',None))
        h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'generation':7,'status':'started'},e)
        self.assertIs(e.source._atlas_binding,self.binding);self.assertTrue(self.gate.source_authorized(e.source));self.assertEqual(len(self.authority._native_admission_proofs),0)
    async def test_foreign_origin_denied(self):
        for field,value in [('user_id','42'),('chat_id','42'),('profile','tg-42'),('thread_id','8'),('chat_type','group')]:
            h=self.hooks();h.retain(self.authority,self.event,self.row,first_insert=True);e=self.restored();setattr(e.source,field,value)
            with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'generation':1,'status':'started'},e)
    async def test_recovered_missing_proof_denied(self):
        h=self.hooks()
        with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'generation':1,'status':'started'},self.restored())
    async def test_revoke_cancel_expiry_and_replay(self):
        h=self.hooks();h.retain(self.authority,self.event,self.row,first_insert=True);h.drop(self.authority,'a');self.assertEqual(len(self.authority._native_admission_proofs),0)
        with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'generation':1,'status':'started'},self.restored())
        h.retain(self.authority,self.event,self.row,first_insert=True);self.gate._issued.clear()
        with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'generation':1,'status':'started'},self.restored())
    async def test_foreign_authority_session_principal_epoch(self):
        h=self.hooks()
        for field,value in [('principal_id','foreign'),('request_id','foreign'),('seq',2),('target_session_id','foreign')]:
            h.retain(self.authority,self.event,self.row,first_insert=True)
            with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,field:value,'generation':1,'status':'started'},self.restored())
        h.retain(self.authority,self.event,self.row,first_insert=True);self.authority.epoch='new'
        with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'generation':1,'status':'started'},self.restored())
    async def test_bound_expiry_and_inflight_consumption(self):
        h=self.hooks();old=h.MAX_PENDING;h.MAX_PENDING=2
        try:
            for index in range(3):h.retain(self.authority,self.event,{**self.row,'admission_id':str(index)},first_insert=True)
            self.assertEqual(len(self.authority._native_admission_proofs),2)
            with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'admission_id':'2','status':'started','generation':1},self.restored())
            proof=self.authority._native_admission_proofs['0'];self.authority._native_admission_proofs['0']=(proof[0]-601,*proof[1:])
            with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'admission_id':'0','status':'started','generation':1},self.restored())
        finally:h.MAX_PENDING=old
    async def test_rotation_uses_canonical_owner_not_latest_actor(self):
        h=self.hooks();h.retain(self.authority,self.event,self.row,first_insert=True)
        self.authority._current_owner=lambda owner:'rotated' if owner=='session' else owner
        e=self.restored();h.restore(self.authority,SimpleNamespace(session_id='rotated'),{**self.row,'target_session_id':'rotated','generation':1,'status':'started'},e)
        self.assertIs(e.source._atlas_binding,self.binding)
    async def test_duplicate_cannot_replace_original_capability(self):
        h=self.hooks();h.retain(self.authority,self.event,self.row,first_insert=True)
        old=self.binding
        self.gate._issued.pop(id(old))
        h.retain(self.authority,self.event,self.row,first_insert=False)
        with self.assertRaises(h.NativeAdmissionDenied):h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'status':'started','generation':1},self.restored())
    async def test_non_atlas_transport_unchanged(self):
        h=self.hooks();self.event.source.platform=Platform.DISCORD
        h.retain(self.authority,self.event,self.row,first_insert=True)
        h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'status':'started','generation':1},self.event)
        self.assertFalse(hasattr(self.authority,'_native_admission_proofs'))
if __name__=='__main__':unittest.main(verbosity=2)
