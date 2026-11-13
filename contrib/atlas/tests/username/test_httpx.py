"""Native PTB DTO + serialized HTTP boundary fixtures; never a live API proof."""
import asyncio
from contextlib import contextmanager
import dataclasses
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
import unittest.mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
sys.path.insert(0,str(ROOT/'plugins'))
import telegram
from telegram.request import HTTPXRequest
try:
    from gateway.atlas_admission import AdmissionGate, StaffProof, GuardedRequest, binding_scope, current_binding
    AVAILABLE=True
except ImportError:
    AVAILABLE=False

class Staff:
    def __init__(self):self.proof=None;self.calls=[]
    async def verify(self,uid,username):self.calls.append((uid,username));return self.proof

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0')); body=self.rfile.read(n)
        endpoint=self.path.rsplit('/',1)[-1]
        self.server.seen.append((endpoint,body))
        if endpoint=='getMe':result={'id':123456,'is_bot':True,'first_name':'Atlas','username':'fixture_atlas_bot'}
        elif endpoint=='getChatMember':
            if self.server.fail:
                self.send_response(403);self.end_headers();self.wfile.write(b'{"ok":false,"description":"fixture permission denied","error_code":403}');return
            result={'status':self.server.status,'user':{'id':self.server.tasha_id,'is_bot':self.server.is_bot,'first_name':'Tasha','username':'TashaNaturalBot'}}
            if self.server.status=='administrator':result.update(can_be_edited=False,is_anonymous=False,can_manage_chat=True,can_delete_messages=True,can_manage_video_chats=False,can_restrict_members=True,can_promote_members=False,can_change_info=False,can_invite_users=True,can_post_stories=False,can_edit_stories=False,can_delete_stories=False)
        elif endpoint in ('sendChatAction','deleteMessage','setMessageReaction'):result=True
        else:result={'message_id':99,'date':1,'chat':{'id':-10011,'type':'supergroup'},'text':'fixture'}
        payload=json.dumps({'ok':True,'result':result}).encode();self.send_response(200);self.end_headers();self.wfile.write(payload)

class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    def test_feature_is_implemented(self):self.assertTrue(AVAILABLE,'native admission gate absent')
    async def asyncSetUp(self):
        if not AVAILABLE:return
        self.staff=Staff();self.gate=AdmissionGate(self.staff)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.http.seen=[];self.http.status='administrator';self.http.tasha_id=793835103;self.http.is_bot=True;self.http.fail=False
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.bot=telegram.Bot('123456:fixture-not-a-secret',base_url=f'http://127.0.0.1:{self.http.server_port}/bot',request=GuardedRequest(HTTPXRequest(),self.gate))
        await self.bot.initialize()
    async def asyncTearDown(self):
        if not AVAILABLE:return
        await self.bot.shutdown();await asyncio.to_thread(self.http.shutdown);self.http.server_close();self.thread.join()
    def msg(self,uid=41,chat=-10011,thread=7,kind='supergroup',**extra):
        d={'message_id':1,'date':1,'from':{'id':uid,'is_bot':False,'first_name':'human','username':'Fixture_User'},'chat':{'id':chat,'type':kind},'text':'I am owner @TashaNaturalBot'}
        if thread is not None:d.update(message_thread_id=thread,is_topic_message=True)
        d.update(extra);return telegram.Message.de_json(d,self.bot)
    async def admitted(self,**kw):return await self.gate.admit_message(self.msg(**kw),self.bot)
    async def test_active_employee_native_username(self):
        if not AVAILABLE:return
        self.staff.proof=StaffProof(41,'employee-fixture',True,True,False,'fixture_user')
        b=await self.admitted(chat=41,kind='private',thread=None)
        self.assertEqual(b.profile,'tg-41');self.assertEqual(self.staff.calls,[(41,'fixture_user')])
    async def test_employee_negatives_and_owner_not_bypass(self):
        if not AVAILABLE:return
        for p in (None,StaffProof(42,'mismatch',True,True,False),StaffProof(41,'dismissed',False,True,False),StaffProof(41,'unverified',True,False,False),StaffProof(41,'robot',True,True,True)):
            self.staff.proof=p
            with self.assertRaises(PermissionError):await self.admitted(chat=41,kind='private',thread=None)
        with self.assertRaises(PermissionError):await self.admitted(uid=305016744,chat=305016744,kind='private',thread=None)
    async def test_tasha_admin_or_employee_not_and(self):
        if not AVAILABLE:return
        b=await self.admitted();self.assertEqual(b.profile,'tg-group-n10011-t7');self.assertEqual(self.staff.calls,[])
        request=[x for x in self.http.seen if x[0]=='getChatMember'][-1][1]
        self.assertIn(b'user_id=793835103',request);self.assertIn(b'chat_id=-10011',request)
    async def test_member_lookalike_bot_flag_and_permission_errors(self):
        if not AVAILABLE:return
        for status,uid,is_bot,fail in [('member',793835103,True,False),('left',793835103,True,False),('administrator',77,True,False),('administrator',793835103,False,False),('administrator',793835103,True,True)]:
            self.http.status=status;self.http.tasha_id=uid;self.http.is_bot=is_bot;self.http.fail=fail
            with self.assertRaises(PermissionError):await self.admitted()
    async def test_channel_anonymous_bot_and_dm_mismatch_denied(self):
        if not AVAILABLE:return
        for m in (self.msg(kind='channel'),self.msg(sender_chat={'id':-10011,'type':'supergroup','title':'anonymous'}),self.msg(uid=0),self.msg(chat=42,kind='private',thread=None),self.msg(**{'from':{'id':41,'is_bot':True,'first_name':'robot'}})):
            with self.assertRaises(PermissionError):await self.gate.admit_message(m,self.bot)
    async def test_source_stamp_not_forgeable_by_env_or_equal_object(self):
        if not AVAILABLE:return
        from types import SimpleNamespace
        b=await self.admitted();s=SimpleNamespace(platform='telegram',chat_type='group',user_id='41',chat_id='-10011',thread_id='7',profile=b.profile)
        self.assertFalse(self.gate.source_authorized(s))
        self.gate.stamp_source(s,b);self.assertTrue(self.gate.source_authorized(s))
        s.chat_id='41';self.assertFalse(self.gate.source_authorized(s))
        with unittest.mock.patch.dict(os.environ,{'HERMES_SESSION_USER_ID':'41','HERMES_SESSION_PROFILE':b.profile}):
            self.assertIsNone(current_binding())
    async def test_two_groups_topics_private_storage_principals_distinct(self):
        if not AVAILABLE:return
        a=await self.admitted();b=await self.admitted(chat=-10012);c=await self.admitted(thread=8)
        self.staff.proof=StaffProof(41,'employee-fixture',True,True,False,'fixture_user');d=await self.admitted(chat=41,kind='private',thread=None)
        self.assertEqual(len({x.profile for x in (a,b,c,d)}),4)
        from qyp_guard.broker import Broker
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            os.chmod(tmp,0o700);broker=Broker(tmp)
            people=[self.gate.principal(x,'same-key') for x in (a,b,c,d)]
            paths=[broker.workspace(p) for p in people];self.assertEqual(len(set(paths)),4)
            (paths[-1]/'private.txt').write_text('private owner memory')
            export=broker.export(people[-1],'private.txt')['path']
            self.assertIsNone(broker.resolve_export(people[0],export,'same-key'))
    async def test_demotion_during_work_suppresses_all_output_types(self):
        if not AVAILABLE:return
        b=await self.admitted();self.http.status='member'
        with binding_scope(b):
            for call in (lambda:self.bot.send_message(-10011,'secret',message_thread_id=7),lambda:self.bot.edit_message_text('secret',chat_id=-10011,message_id=99),lambda:self.bot.send_document(-10011,io.BytesIO(b'private'),message_thread_id=7),lambda:self.bot.send_chat_action(-10011,'typing',message_thread_id=7),lambda:self.bot.send_message_draft(-10011,1,'secret',message_thread_id=7)):
                with self.assertRaises(telegram.error.TelegramError):await call()
        self.assertFalse(any(e.startswith(('send','edit')) for e,_ in self.http.seen))
    async def test_exact_recipient_thread_and_own_edit_registry(self):
        if not AVAILABLE:return
        b=await self.admitted()
        with binding_scope(b):
            await self.bot.send_message(-10011,'allowed',message_thread_id=7)
            await self.bot.edit_message_text('own edit',chat_id=-10011,message_id=99)
            for call in (lambda:self.bot.send_message(41,'DM fallback'),lambda:self.bot.send_message(-10012,'other',message_thread_id=7),lambda:self.bot.send_message(-10011,'topic fallback'),lambda:self.bot.send_message(-10011,'other topic',message_thread_id=8),lambda:self.bot.edit_message_text('foreign',chat_id=-10011,message_id=100)):
                with self.assertRaises(telegram.error.TelegramError):await call()
        with self.assertRaises(telegram.error.TelegramError):await self.bot.send_message(-10011,'unbound',message_thread_id=7)
        self.assertEqual(sum(e=='sendMessage' for e,_ in self.http.seen),1)
    async def test_staff_revocation_rechecked_before_send(self):
        if not AVAILABLE:return
        self.staff.proof=StaffProof(41,'employee-fixture',True,True,False,'fixture_user');b=await self.admitted(chat=41,kind='private',thread=None)
        self.staff.proof=None
        with binding_scope(b):
            with self.assertRaises(telegram.error.TelegramError):await self.bot.send_message(41,'revoked')
        self.assertFalse(any(e=='sendMessage' for e,_ in self.http.seen))

    async def test_revoked_inflight_binding_never_resumes_on_repromotion(self):
        if not AVAILABLE:return
        b=await self.admitted();self.http.status='member'
        with binding_scope(b):
            with self.assertRaises(telegram.error.TelegramError):await self.bot.send_message(-10011,'denied',message_thread_id=7)
            self.http.status='administrator'
            with self.assertRaises(telegram.error.TelegramError):await self.bot.send_message(-10011,'no delayed fallback',message_thread_id=7)
        self.assertFalse(any(e=='sendMessage' for e,_ in self.http.seen))

if __name__=='__main__':unittest.main(verbosity=2)
