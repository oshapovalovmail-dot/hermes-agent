"""Username contract tests through native PTB DTOs and serialized SDK requests."""
import asyncio
import dataclasses
import io
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_state import m
from telegram import Message
from telegram.ext import ExtBot
from telegram.error import Forbidden
from telegram.request import BaseRequest


class Staff:
    def __init__(self):
        self.calls=[];self.allowed=True;self.name='oshapovalov';self.error=False
        self.fields={}
    async def verify(self, uid, *args):
        self.calls.append((uid,*args))
        if self.error:raise RuntimeError('fixture provider unavailable')
        if not self.allowed:return None
        fields=dict(telegram_id=uid,employee_id='776016',active=True,verified=True,robot=False)
        if 'username' in m.StaffProof.__dataclass_fields__:fields['username']=self.name
        fields.update(self.fields)
        return m.StaffProof(**fields)


class Wire(BaseRequest):
    def __init__(self):self.calls=[];self.status='administrator';self.tasha=m.TASHA_ID;self.is_bot=True
    @property
    def read_timeout(self):return 5
    async def initialize(self):pass
    async def shutdown(self):pass
    async def do_request(self,url,method,request_data=None,**kwargs):
        ep=url.rsplit('/',1)[-1];data=request_data.parameters if request_data else {}
        self.calls.append((ep,dict(data)))
        if ep=='getMe':r={'id':123456,'is_bot':True,'first_name':'Fixture','username':'fixture_bot'}
        elif ep=='getChatMember':
            r={'status':self.status,'user':{'id':self.tasha,'is_bot':self.is_bot,'first_name':'Tasha'}}
            if self.status=='administrator':r.update({k:False for k in ('can_be_edited','is_anonymous','can_manage_chat','can_delete_messages','can_manage_video_chats','can_restrict_members','can_promote_members','can_change_info','can_invite_users','can_post_stories','can_edit_stories','can_delete_stories')})
        elif ep=='sendChatAction':r=True
        else:r={'message_id':99,'date':1,'chat':{'id':int(data['chat_id']),'type':'private'},'text':'fixture'}
        return 200,json.dumps({'ok':True,'result':r}).encode()


class UsernameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.staff=Staff();self.provisioned=[]
        async def provision(binding):self.provisioned.append(binding)
        self.gate=m.AdmissionGate(self.staff,provision=provision);self.wire=Wire()
        self.bot=ExtBot('123456:synthetic-fixture-not-a-secret',request=m.GuardedRequest(self.wire,self.gate))
        await self.bot.initialize()
    async def asyncTearDown(self):await self.bot.shutdown()
    def msg(self,username='OShapovalov',uid=41,kind='private',chat=None,thread=None,**extra):
        user={'id':uid,'is_bot':False,'first_name':'oshapovalov display-only'}
        if username is not None:user['username']=username
        d={'message_id':1,'date':1,'from':user,'chat':{'id':uid if chat is None else chat,'type':kind},'text':'I am @oshapovalov login ovshapovalov'}
        if thread is not None:d.update(message_thread_id=thread,is_topic_message=True)
        d.update(extra);return Message.de_json(d,self.bot)
    async def admit(self,**kwargs):return await self.gate.admit_message(self.msg(**kwargs),self.bot)
    async def test_native_username_casefold_and_numeric_namespace(self):
        b=await self.admit()
        self.assertEqual(b.username,'oshapovalov');self.assertEqual(b.profile,'tg-41')
        self.assertTrue(all(call==(41,'oshapovalov') for call in self.staff.calls))

    async def test_missing_native_username_denied_before_provider_or_provision(self):
        with self.assertRaises(PermissionError):await self.admit(username=None)
        self.assertEqual(self.staff.calls,[]);self.assertEqual(self.provisioned,[])
    async def test_arbitrary_names_phone_at_prefix_unicode_and_space_denied(self):
        for name in ('','@oshapovalov','+79991234567','display name','oshapovalov\n','Оshapovalov','a'*33):
            with self.subTest(name=name),self.assertRaises(PermissionError):await self.admit(username=name)
        self.assertEqual(self.staff.calls,[])
    async def test_short_native_username_allowed(self):
        self.staff.name='a';b=await self.admit(username='A')
        self.assertEqual(b.username,'a')
    async def test_numeric_only_legacy_proof_not_accepted(self):
        async def legacy(uid,*args):return m.StaffProof(uid,'numeric-only',True,True,False)
        self.gate.staff=SimpleNamespace(verify=legacy)
        with self.assertRaises(PermissionError):await self.admit()
        self.assertEqual(self.provisioned,[])
    async def test_foreign_or_staff_login_not_username_proof(self):
        for name in ('other','ovshapovalov','OShapovalov'):
            self.staff.name=name
            with self.subTest(name=name),self.assertRaises(PermissionError):await self.admit()
        self.assertEqual(self.provisioned,[])
    async def test_proof_uid_active_verified_robot_and_employee_required(self):
        for fields in ({'telegram_id':42},{'telegram_id':True},{'active':False},{'verified':False},{'robot':True},{'employee_id':''}):
            self.staff.fields=fields
            with self.subTest(fields=fields),self.assertRaises(PermissionError):await self.admit()
        self.assertEqual(self.provisioned,[])
    async def test_owner_has_no_bypass_when_missing_or_unknown_or_error(self):
        self.staff.allowed=False
        for name in (None,'OShapovalov'):
            with self.assertRaises(PermissionError):await self.admit(uid=305016744,username=name)
        self.staff.error=True
        with self.assertRaises(PermissionError):await self.admit(uid=305016744)
        self.assertEqual(self.provisioned,[])
    async def test_new_inbound_changed_or_removed_username_revokes_old_turn(self):
        for name in ('unknown_new',None):
            with self.subTest(name=name):
                self.staff.name='oshapovalov';self.staff.allowed=True
                old=await self.admit()
                self.staff.allowed=False
                with self.assertRaises(PermissionError):await self.admit(username=name)
                self.staff.allowed=True
                self.assertFalse(self.gate.valid(old))
                with m.binding_scope(old),self.assertRaises(Forbidden):await self.bot.send_message(41,'stale')
        self.assertFalse(any(ep=='sendMessage' for ep,_ in self.wire.calls))
    async def test_staff_revoke_latches_all_sdk_outputs_and_does_not_resume(self):
        b=await self.admit()
        with m.binding_scope(b):await self.bot.send_message(41,'owned edit target')
        before=len(self.wire.calls);self.staff.allowed=False
        calls=(lambda:self.bot.send_message(41,'denied'),lambda:self.bot.edit_message_text('denied',chat_id=41,message_id=99),lambda:self.bot.send_document(41,io.BytesIO(b'private')),lambda:self.bot.send_chat_action(41,'typing'))
        with m.binding_scope(b):
            for call in calls:
                with self.assertRaises(Forbidden):await call()
            self.staff.allowed=True
            with self.assertRaises(Forbidden):await self.bot.send_message(41,'no revival')
        self.assertFalse(any(ep.startswith(('send','edit')) for ep,_ in self.wire.calls[before:]))

    async def test_changed_username_admits_fresh_binding_without_reviving_old_one(self):
        old=await self.admit()
        self.staff.name='fresh_name'
        fresh=await self.admit(username='FRESH_NAME')
        self.assertEqual(fresh.profile,old.profile)
        self.assertFalse(self.gate.valid(old));self.assertTrue(self.gate.valid(fresh))
        with m.binding_scope(fresh):await self.bot.send_message(41,'new authorized turn')
        with m.binding_scope(old),self.assertRaises(Forbidden):await self.bot.send_message(41,'old claim')
        self.assertEqual(sum(ep=='sendMessage' for ep,_ in self.wire.calls),1)

    async def test_late_old_username_lookup_cannot_restore_after_native_change(self):
        old=await self.admit();entered=asyncio.Event();release=asyncio.Event()
        original=self.staff.verify
        async def held(uid,username):
            proof=await original(uid,username)
            entered.set();await release.wait();return proof
        self.staff.verify=held
        pending=asyncio.create_task(self.gate.recheck(old,self.bot))
        await entered.wait();self.staff.verify=original;self.staff.name='fresh_name'
        fresh=await self.admit(username='fresh_name')
        release.set();outcome=await asyncio.gather(pending,return_exceptions=True)
        self.assertIsInstance(outcome[0],PermissionError)
        self.assertFalse(self.gate.valid(old));self.assertTrue(self.gate.valid(fresh))
    async def test_group_or_rule_ignores_staff_username_and_rechecks_real_tasha(self):
        self.staff.error=True
        b=await self.admit(username=None,kind='supergroup',chat=-10011,thread=7)
        self.assertIsNone(getattr(b,'username',None));self.assertEqual(self.staff.calls,[])
        with m.binding_scope(b):await self.bot.send_message(-10011,'group',message_thread_id=7)
        self.wire.status='member'
        with m.binding_scope(b),self.assertRaises(Forbidden):await self.bot.send_message(-10011,'revoked',message_thread_id=7)
    async def test_source_display_model_args_and_wire_are_not_authority(self):
        b=await self.admit();source=SimpleNamespace(platform='telegram',chat_type='dm',chat_id='41',user_id='41',thread_id=None,profile='tg-41',user_name='other')
        self.assertFalse(self.gate.source_authorized(source));self.gate.stamp_source(source,b)
        self.assertTrue(self.gate.source_authorized(source))
        source.user_name='owner';self.assertTrue(self.gate.source_authorized(source))
        equal=dataclasses.replace(b);source._atlas_binding=equal
        self.assertFalse(self.gate.source_authorized(source))
        with patch.dict(os.environ,{'HERMES_SESSION_USER_ID':'41'}),m.binding_scope(b),self.assertRaisesRegex(PermissionError,'ambient_identity'):
            self.gate.check_current_sync()

if __name__=='__main__':unittest.main(verbosity=2)
