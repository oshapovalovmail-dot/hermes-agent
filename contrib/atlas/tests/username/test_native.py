"""Actual candidate native adapter + PTB Application boundary fixture."""
import asyncio
import dataclasses
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
import unittest.mock
ROOT=Path(os.environ['ATLAS_USERNAME_FIXTURE_ROOT'])
NATIVE=Path(os.environ['ATLAS_TEST_CORE'])
FIXTURE=ROOT/'fixtures/native-home'
FIXTURE.mkdir(parents=True,exist_ok=True)
os.environ['HERMES_HOME']=str(FIXTURE)
os.environ['PYTHONDONTWRITEBYTECODE']='1'
sys.path.insert(0,str(NATIVE))
import hermes_cli.config as native_config
# Refuse initialization before any native plugin/adapter import.
def refuse_load_config(*args,**kwargs):
    raise AssertionError('initializing_load_config_forbidden_in_pure_fixture')
native_config.load_config=refuse_load_config
import gateway
# Source overlay, not patches to the live runtime or monkeypatches at runtime.
gateway.__path__=[str(ROOT/'runtime/gateway'),str(NATIVE/'gateway')]
import gateway.platforms
gateway.platforms.__path__=[str(ROOT/'runtime/gateway/platforms'),str(NATIVE/'gateway/platforms')]
import gateway.platforms.base
importlib.reload(gateway.platforms.base)
import plugins.platforms.telegram
plugins.platforms.telegram.__path__=[str(ROOT/'runtime/plugins/platforms/telegram'),str(NATIVE/'plugins/platforms/telegram')]
import plugins.platforms.telegram.adapter
importlib.reload(plugins.platforms.telegram.adapter)
sys.path.insert(0,str(ROOT/'plugins'))
from gateway.atlas_admission import AdmissionGate, StaffProof, install_gate, binding_scope, GuardedRequest
from gateway.config import Platform,PlatformConfig
from qyp_guard.broker import OWNER
OWNER_ID=int(OWNER)
from gateway.session import SessionSource
from gateway.platforms.event import MessageEvent,MessageType
from gateway.platforms.base import BasePlatformAdapter
from plugins.platforms.telegram.update_admission import TelegramApplication
from plugins.platforms.telegram.adapter import TelegramAdapter
from telegram.ext import Application,TypeHandler,ExtBot
from telegram import Update
from telegram.request import BaseRequest

class Wire(BaseRequest):
    def __init__(self):self.status='administrator';self.calls=[]
    @property
    def read_timeout(self):return 2
    async def initialize(self):pass
    async def shutdown(self):pass
    async def do_request(self,url,method,request_data=None,**kw):
        ep=url.rsplit('/',1)[-1];self.calls.append(ep)
        if ep=='getMe':r={'id':123456,'is_bot':True,'first_name':'Atlas','username':'fixture_atlas_bot'}
        elif ep=='getChatMember':
            r={'status':self.status,'user':{'id':793835103,'is_bot':True,'first_name':'Tasha'}}
            if self.status=='administrator':r.update(can_be_edited=False,is_anonymous=False,can_manage_chat=True,can_delete_messages=True,can_manage_video_chats=False,can_restrict_members=False,can_promote_members=False,can_change_info=False,can_invite_users=False,can_post_stories=False,can_edit_stories=False,can_delete_stories=False)
        elif ep in ('sendMessage','sendDocument'):
            params=request_data.parameters
            r={'message_id':99,'date':1,'chat':{'id':int(params['chat_id']),'type':'supergroup'},'text':'fixture native delivery'}
            if 'message_thread_id' in params:r['message_thread_id']=int(params['message_thread_id'])
        else:r=True
        return 200,json.dumps({'ok':True,'result':r}).encode()
class Staff:
    async def verify(self,uid,username):return StaffProof(uid,'fixture',True,True,False,username)

class Native(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import gateway.atlas_admission as mod
        mod._GATE=None
        self.gate=AdmissionGate(Staff());install_gate(self.gate)
        self.wire=Wire()
        self.adapter=TelegramAdapter(PlatformConfig(enabled=True,extra={'atlas_admission':True}))
        self.receipt_dir=tempfile.TemporaryDirectory(dir=ROOT/'fixtures')
        self.adapter._update_receipt_dir=Path(self.receipt_dir.name)
        self.bot=ExtBot('123456:fixture-not-a-secret',request=GuardedRequest(self.wire,self.gate))
        self.adapter._bot=self.bot
        self.app=(Application.builder().bot(self.bot).application_class(TelegramApplication,{'adapter':self.adapter}).build())
        await self.app.initialize()
        self.received=[]
        async def plugin(update,ctx):self.received.append(update.update_id)
        self.app.add_handler(TypeHandler(Update,plugin))
    async def asyncTearDown(self):
        await self.app.shutdown()
        pending=self.adapter._update_receipt_flush
        if pending is not None:await pending
        self.receipt_dir.cleanup()
    def update(self,uid=41,chat=-10011,thread=7,kind='supergroup',index=1,username='Fixture_User'):
        d={'message_id':index,'date':1,'from':{'id':uid,'is_bot':False,'first_name':'human','username':'Fixture_User'},'chat':{'id':chat,'type':kind},'text':'hello @fixture_atlas_bot'}
        if username is None:d['from'].pop('username')
        else:d['from']['username']=username
        if thread is not None:d.update(message_thread_id=thread,is_topic_message=True)
        return Update.de_json({'update_id':index,'message':d},self.bot)
    async def test_plugin_gate_denied_before_callback_and_profile_creation(self):
        self.wire.status='member';await self.app.process_update(self.update())
        self.assertEqual(self.received,[]);self.assertFalse((FIXTURE/'profiles').exists())

    async def test_dm_username_missing_denied_before_every_ptb_handler(self):
        for uid in (41,OWNER_ID):
            await self.app.process_update(self.update(uid=uid,chat=uid,kind='private',thread=None,index=uid,username=None))
        self.assertEqual(self.received,[])
        self.assertFalse((FIXTURE/'profiles').exists())

    async def test_dm_current_username_not_display_or_model_text(self):
        calls=[]
        async def verify(uid,username):
            calls.append((uid,username))
            return StaffProof(uid,'fixture',True,True,False,username) if username=='fixture_user' else None
        self.gate.staff=SimpleNamespace(verify=verify)
        u=self.update(uid=OWNER_ID,chat=OWNER_ID,kind='private',thread=None,username='FIXTURE_USER')
        await self.app.process_update(u)
        source=self.adapter._build_message_event(u.message,MessageType.TEXT,update_id=1).source
        self.assertTrue(self.gate.source_authorized(source))
        self.assertEqual(self.gate.principal(source._atlas_binding,'native').role,'owner')
        self.assertEqual(calls,[(OWNER_ID,'fixture_user')])
        # The next actual message changes the username; it cannot reuse the
        # owner's historical SessionSource or text to admit a now-unknown name.
        u2=self.update(uid=OWNER_ID,chat=OWNER_ID,kind='private',thread=None,index=2,username='unknown_now')
        await self.app.process_update(u2)
        self.assertEqual(self.received,[1]);self.assertFalse(self.gate.source_authorized(source))
        with binding_scope(source._atlas_binding),self.assertRaises(Exception):
            await self.bot.send_message(OWNER_ID,'stale owner reply')
        self.assertNotIn('sendMessage',self.wire.calls)
    async def test_native_build_and_pregate_for_two_groups_and_dm(self):
        sources=[]
        for uid,chat,thread,kind,i in [(41,-10011,7,'supergroup',1),(41,-10012,7,'supergroup',2),(41,41,None,'private',3)]:
            update=self.update(uid,chat,thread,kind,i)
            await self.app.process_update(update)
            event=self.adapter._build_message_event(update.message,MessageType.TEXT,update_id=i)
            self.assertTrue(self.gate.source_authorized(event.source))
            sources.append(event.source)
        self.assertEqual(self.received,[1,2,3]);self.assertEqual(len({x.profile for x in sources}),3)
        self.assertFalse(any('Oleg' in str(x.to_dict()) for x in sources[:2]))

    async def test_native_dataclass_copy_preserves_opaque_not_wire_proof(self):
        u=self.update();await self.app.process_update(u)
        source=self.adapter._build_message_event(u.message,MessageType.TEXT,update_id=1).source
        self.assertTrue(self.gate.source_authorized(dataclasses.replace(source)))
        wire=source.to_dict();self.assertNotIn('_atlas_binding',wire)
        wire['_atlas_binding']=source._atlas_binding
        self.assertFalse(self.gate.source_authorized(SessionSource.from_dict(wire)))

    async def test_native_group_text_and_document_scoped_delivery(self):
        from qyp_guard.broker import Broker
        from qyp_guard.pending_media import register_pending
        import gateway.media_delivery_gate as media
        u=self.update();await self.app.process_update(u)
        event=self.adapter._build_message_event(u.message,MessageType.TEXT,update_id=1)
        binding=event.source._atlas_binding
        with tempfile.TemporaryDirectory(dir=ROOT/'fixtures') as tmp:
            os.chmod(tmp,0o700);broker=Broker(tmp);hooks={}
            ctx=SimpleNamespace(profile_name=binding.profile,register_hook=lambda name,fn:hooks.update({name:fn}))
            service=SimpleNamespace(admission=self.gate,broker=broker);register_pending(ctx,service)
            who=self.gate.principal(binding,'fixture-session');workspace=broker.workspace(who)
            (workspace/'report.txt').write_text('GROUP_ONLY_SENTINEL');issued=broker.export(who,'report.txt')['path']
            metadata={'thread_id':'7','hermes_profile':binding.profile}
            dispatch=lambda name,**kwargs:[hooks[name](**kwargs)]
            with unittest.mock.patch.object(media,'load_config_readonly',return_value={'media_delivery':{'required_policy':'qyp_guard'}}), unittest.mock.patch.object(media,'invoke_hook',side_effect=dispatch):
                with media.media_delivery_origin(event.source,session_key='fixture-session'):
                    text=await self.adapter.send('-10011','GROUP_ONLY_SENTINEL',metadata=metadata)
                    self.assertTrue(text.success,text.error)
                    result=await self.adapter.send_document('-10011',issued,metadata=metadata)
                    self.assertTrue(result.success,result.error)
                    before=self.wire.calls.count('sendDocument')
                    self.wire.status='member'
                    denied=await self.adapter.send_document('-10011',issued,metadata=metadata)
                    self.assertFalse(denied.success);self.assertEqual(self.wire.calls.count('sendDocument'),before)
            self.assertEqual(self.wire.calls.count('sendMessage'),1);self.assertEqual(before,1)

    async def test_native_llm_and_tool_hooks_use_fresh_per_turn_actor(self):
        from qyp_guard import Service
        from gateway.session_context import set_session_vars,clear_session_vars
        for uid,index in ((41,1),(42,2)):
            u=self.update(uid=uid,index=index);await self.app.process_update(u)
            event=self.adapter._build_message_event(u.message,MessageType.TEXT,update_id=index)
            binding=event.source._atlas_binding
            service=object.__new__(Service);service.admission=self.gate;service._trace_bindings={}
            service.ctx=SimpleNamespace(profile_name=binding.profile,get_config=lambda key,default=None:default)
            tokens=set_session_vars(platform='telegram',chat_id=binding.chat_id,chat_type='group',thread_id='7',user_id=str(uid),session_key='group-session',profile=binding.profile)
            try:
                with binding_scope(binding):
                    self.assertIsNone(await asyncio.to_thread(service.guard_llm))
                    self.assertIsNone(await asyncio.to_thread(service.guard_tool,'qyp_role',{}))
                    role=await asyncio.to_thread(service.authorized_principal)
                    self.assertEqual(role.user_id,str(uid));self.assertEqual(role.profile,binding.profile)
                    self.assertEqual((await asyncio.to_thread(service.guard_tool,'browser_exec',{}))['action'],'block')
            finally:clear_session_vars(tokens)
        with binding_scope(binding):
            self.wire.status='member'
            self.assertEqual((await asyncio.to_thread(service.guard_llm))['action'],'block')
    async def test_native_base_pre_busy_denied_before_handler(self):
        hit=[]
        async def downstream(event):hit.append(event)
        self.adapter._handle_admitted_message=downstream
        source=SessionSource(platform=Platform.TELEGRAM,chat_id='41',chat_type='dm',user_id='41',profile='tg-41')
        await self.adapter.handle_message(MessageEvent(text='/stop',source=source,message_type=MessageType.COMMAND))
        self.assertEqual(hit,[])
        u=self.update();await self.app.process_update(u)
        event=self.adapter._build_message_event(u.message,MessageType.TEXT,update_id=1)
        await self.adapter.handle_message(event);self.assertEqual(len(hit),1)
        self.wire.status='member';await self.adapter.handle_message(event);self.assertEqual(len(hit),1)

    async def test_dm_llm_and_tool_hooks_require_fresh_username_staff_check(self):
        from qyp_guard import Service
        from gateway.session_context import set_session_vars,clear_session_vars
        allowed=True;calls=[]
        async def verify(uid,username):
            calls.append((uid,username))
            return StaffProof(uid,'fixture',True,True,False,username) if allowed else None
        self.gate.staff=SimpleNamespace(verify=verify)
        u=self.update(chat=41,kind='private',thread=None)
        await self.app.process_update(u)
        event=self.adapter._build_message_event(u.message,MessageType.TEXT,update_id=1)
        binding=event.source._atlas_binding
        service=object.__new__(Service);service.admission=self.gate;service._trace_bindings={}
        service.ctx=SimpleNamespace(profile_name='tg-41')
        tokens=set_session_vars(platform='telegram',chat_id='41',chat_type='dm',user_id='41',session_key='private',profile='tg-41')
        try:
            with binding_scope(binding):
                self.assertIsNone(await asyncio.to_thread(service.guard_llm))
                self.assertIsNone(await asyncio.to_thread(service.guard_tool,'qyp_role',{}))
                self.assertEqual(calls,[(41,'fixture_user')]*3)
                allowed=False
                self.assertEqual((await asyncio.to_thread(service.guard_llm))['action'],'block')
                allowed=True
                self.assertEqual((await asyncio.to_thread(service.guard_tool,'qyp_role',{}))['action'],'block')
                self.assertFalse(self.gate.source_authorized(event.source))
        finally:clear_session_vars(tokens)


if __name__=='__main__':unittest.main(verbosity=2)
