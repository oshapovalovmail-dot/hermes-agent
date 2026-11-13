import sys, asyncio, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_inherited_proofs import ProofTests
from types import SimpleNamespace
from telegram import Message

class IndependentTests(ProofTests):
    async def revoke_original(self):
        staff=self.gate.staff
        class DeniedStaff:
            async def verify(self,uid,name): return None
        self.gate.staff=DeniedStaff()
        with self.assertRaises(PermissionError): await self.gate.recheck(self.binding,None)
        self.gate.staff=staff
    async def test_expired_redelivery_cannot_rebind_original(self):
        h=self.hooks();h.retain(self.authority,self.event,self.row,first_insert=True)
        proof=self.authority._native_admission_proofs['a']
        self.authority._native_admission_proofs['a']=(proof[0]-601,*proof[1:])
        # Same native UID/message/username and source wire fields after revocation.
        await self.revoke_original()
        m=Message.de_json({'message_id':17,'date':1,'from':{'id':41,'is_bot':False,'first_name':'Fixture','username':'fixture_41'},'chat':{'id':41,'type':'private'},'text':'test'},None)
        newer=await self.gate.admit_message(m,None)
        self.assertFalse(self.gate.valid(self.binding))
        self.gate.stamp_source(self.source,newer)
        h.retain(self.authority,self.event,self.row,first_insert=False)
        restored=self.restored()
        with self.assertRaises(h.NativeAdmissionDenied):
            h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'generation':1,'status':'started'},restored)
    async def test_duplicate_before_expiry_keeps_original(self):
        h=self.hooks();h.retain(self.authority,self.event,self.row,first_insert=True)
        original=self.binding
        await self.revoke_original()
        m=Message.de_json({'message_id':17,'date':1,'from':{'id':41,'is_bot':False,'first_name':'Fixture','username':'fixture_41'},'chat':{'id':41,'type':'private'},'text':'test'},None)
        newer=await self.gate.admit_message(m,None);self.gate.stamp_source(self.source,newer)
        h.retain(self.authority,self.event,self.row,first_insert=False)
        self.assertIs(self.authority._native_admission_proofs['a'][5],original)
        with self.assertRaises(h.NativeAdmissionDenied):
            h.restore(self.authority,SimpleNamespace(session_id='session'),{**self.row,'generation':1,'status':'started'},self.restored())
if __name__=='__main__':
    suite=unittest.TestSuite(IndependentTests(name) for name in ['test_expired_redelivery_cannot_rebind_original','test_duplicate_before_expiry_keeps_original'])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
