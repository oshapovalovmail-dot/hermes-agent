"""Native Atlas Telegram identity/recipient authority; never model or env claims.

StaffProof is a provider contract, NOT a guessed Staff API schema. Until a reviewed
provider is installed private intake fails closed, including the operator.
"""
import asyncio
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import re
import os
import time
from typing import Protocol
from telegram import Message
from telegram.error import Forbidden
from telegram.request import BaseRequest

TASHA_ID=793835103

class AdmissionDenied(Forbidden):pass
_BINDING=ContextVar('atlas_authenticated_binding',default=None)
_GATE=None

@dataclass(frozen=True)
class StaffProof:
    telegram_id:int
    employee_id:str
    active:bool
    verified:bool
    robot:bool
    # Username proof only. telegram_id scopes this response to the native
    # transport principal; it is NOT an authoritative Staff numeric binding.
    username:str | None=None

class StaffProvider(Protocol):
    async def verify(self, telegram_id:int, username:str) -> StaffProof | None: ...

class DenyStaffProvider:
    async def verify(self,telegram_id,username):return None

@dataclass(frozen=True,eq=False)
class Binding:
    user_id:str
    chat_id:str
    chat_type:str
    thread_id:str | None
    profile:str
    username:str | None=None

def canonical_username(value):
    # No @ prefix, display names, phone numbers, normalization of whitespace,
    # or Unicode confusables. Telegram can issue short/collectible usernames.
    if not isinstance(value,str) or re.fullmatch(r'[A-Za-z0-9_]{1,32}',value) is None:
        return None
    return value.casefold()

@contextmanager
def binding_scope(binding):
    token=_BINDING.set(binding)
    try:yield
    finally:_BINDING.reset(token)

def current_binding():return _BINDING.get()
def installed_gate():return _GATE

def install_gate(gate):
    global _GATE
    if _GATE is not None and _GATE is not gate:raise PermissionError('admission_authority_already_installed')
    _GATE=gate

class AdmissionGate:
    def __init__(self,staff=None,provision=None):
        self.staff=staff or DenyStaffProvider();self.provision=provision
        self._issued=OrderedDict();self._messages=OrderedDict();self._sent=OrderedDict();self._loop=None
    @staticmethod
    def profile_for(chat_type,chat_id,user_id,thread_id):
        if chat_type=='dm':return 'tg-'+user_id
        return 'tg-group-n'+chat_id[1:]+'-t'+(thread_id or '0')
    def valid(self,b):return isinstance(b,Binding) and self._issued.get(id(b),(None,))[0] is b
    async def recheck(self,b,bot):
        if not self.valid(b):raise PermissionError('unissued_binding')
        try:
            if b.chat_type=='dm':
                if b.username is None or canonical_username(b.username)!=b.username:
                    raise PermissionError('native_telegram_username_required')
                p=await asyncio.wait_for(self.staff.verify(int(b.user_id),b.username),5)
                if not (type(p) is StaffProof and type(p.telegram_id) is int and p.telegram_id==int(b.user_id)
                        and p.username==b.username and isinstance(p.username,str)
                        and isinstance(p.employee_id,str) and p.employee_id and p.active is True and p.verified is True and p.robot is False):
                    raise PermissionError('active_verified_username_employee_required')
            else:
                member=await asyncio.wait_for(bot.get_chat_member(int(b.chat_id),TASHA_ID),5)
                if not (member.status=='administrator' and type(member.user.id) is int and member.user.id==TASHA_ID and member.user.is_bot is True):
                    raise PermissionError('official_tasha_administrator_required')
        except (Exception,SystemExit) as error:
            # A revoked/unknown in-flight turn must never resume via a retry or
            # format/media fallback, even if the external role later reappears.
            self._issued.pop(id(b),None)
            raise PermissionError('admission_verification_denied') from None
        # Another awaited check can revoke this turn while this lookup is in
        # flight. A late positive result cannot issue the same turn again.
        if not self.valid(b):raise PermissionError('binding_revoked_during_verification')
        self._issued[id(b)]=(b,bot,time.monotonic())
        return b
    async def admit_message(self,message,bot):
        if not isinstance(message,Message):raise PermissionError('native_telegram_message_required')
        u=message.from_user;c=message.chat
        if u is None or type(u.id) is not int or u.id<=0 or u.is_bot is not False or message.sender_chat is not None:
            raise PermissionError('authenticated_human_sender_required')
        if c.type not in ('private','group','supergroup') or type(c.id) is not int:
            raise PermissionError('private_or_group_only')
        kind='dm' if c.type=='private' else 'group'
        if (kind=='dm' and c.id!=u.id) or (kind=='group' and c.id>=0):raise PermissionError('chat_identity_mismatch')
        username=canonical_username(u.username) if kind=='dm' else None
        if kind=='dm':
            # The actual new Telegram DTO supersedes old in-flight username
            # claims even when this new name is absent or fails Staff lookup.
            for key,(old,_,_) in list(self._issued.items()):
                if old.chat_type=='dm' and old.user_id==str(u.id) and old.username!=username:
                    self._issued.pop(key,None)
            if username is None:raise PermissionError('native_telegram_username_required')
        thread=message.message_thread_id if message.is_topic_message or (c.type=='supergroup' and c.is_forum) else None
        if thread is not None and (type(thread) is not int or thread<=0):raise PermissionError('canonical_topic_required')
        # Match native General topic routing; ordinary group has no synthetic topic.
        if kind=='group' and c.is_forum and thread is None:thread=1
        tid=str(thread) if thread is not None else None
        b=Binding(str(u.id),str(c.id),kind,tid,self.profile_for(kind,str(c.id),str(u.id),tid),username)
        self._issued[id(b)]=(b,bot,0)
        try:await self.recheck(b,bot)
        except BaseException:
            self._issued.pop(id(b),None);raise
        self._loop=asyncio.get_running_loop()
        if self.provision is not None:
            try:
                await self.provision(b)
                await self.recheck(b,bot)
            except BaseException:
                self._issued.pop(id(b),None);raise
        while len(self._issued)>4096:self._issued.popitem(last=False)
        self._messages[id(message)]=(message,b)
        while len(self._messages)>512:
            _,(_,old)=self._messages.popitem(last=False)
            # Pending detached contexts may still hold issued bindings. Lifetime is
            # per process and exact-source; no serialization/env recovery grants.
        return b
    def message_binding(self,message):
        record=self._messages.get(id(message))
        return record[1] if record and record[0] is message else None
    def stamp_source(self,source,b):
        if not self.valid(b):raise PermissionError('unissued_binding')
        source.profile=b.profile;source._atlas_binding=b
    def source_authorized(self,source):
        b=getattr(source,'_atlas_binding',None)
        platform=getattr(source,'platform',None)
        return bool(self.valid(b) and getattr(platform,'value',platform)=='telegram'
                    and getattr(source,'user_id',None)==b.user_id and getattr(source,'chat_id',None)==b.chat_id
                    and getattr(source,'chat_type',None) in (('dm',) if b.chat_type=='dm' else ('group','forum'))
                    and (getattr(source,'thread_id',None) or None)==b.thread_id and getattr(source,'profile',None)==b.profile)
    def fresh_source_authorized(self,source):
        if not self.source_authorized(source):return False
        return time.monotonic()-self._issued[id(source._atlas_binding)][2]<=5
    def check_current_sync(self):
        if any(key in os.environ for key in ('HERMES_SESSION_PLATFORM','HERMES_SESSION_USER_ID','HERMES_SESSION_KEY','HERMES_SESSION_CHAT_TYPE')):
            raise PermissionError('ambient_identity_forbidden')
        b=current_binding()
        if not self.valid(b):raise PermissionError('bound_native_admission_required')
        bot=self._issued[id(b)][1]
        try:running=asyncio.get_running_loop()
        except RuntimeError:running=None
        if running is self._loop:raise PermissionError('sync_recheck_on_gateway_loop_forbidden')
        if self._loop is None or not self._loop.is_running():raise PermissionError('verification_loop_unavailable')
        future=asyncio.run_coroutine_threadsafe(self.recheck(b,bot),self._loop)
        try:future.result(timeout=6)
        except BaseException:
            future.cancel();raise PermissionError('fresh_verification_required') from None
        return b
    def principal(self,b,session_key):
        if not self.valid(b):raise PermissionError('bound_native_admission_required')
        from qyp_guard.broker import Principal, OWNER
        return Principal(b.user_id,session_key,'owner' if b.user_id==OWNER else 'member',b.profile,b.chat_id,b.thread_id or '')
    async def authorize_request(self,endpoint,data):
        # Explicit non-output control/read surface. Unknown methods fail closed.
        controls={'getMe','getUpdates','getFile','getChat','getChatMember','getWebhookInfo','setWebhook','deleteWebhook','setMyCommands','getMyCommands','setMyDescription','setMyShortDescription','getMyDescription','getMyShortDescription','getUserProfilePhotos'}
        if endpoint in controls:return
        outputs={'sendMessage','sendMessageDraft','sendRichMessageDraft','sendDocument','sendPhoto','sendVideo','sendAnimation','sendAudio','sendVoice','sendVideoNote','sendMediaGroup','sendChatAction','editMessageText','editMessageCaption','editMessageReplyMarkup','editMessageMedia','deleteMessage','setMessageReaction'}
        if endpoint not in outputs:raise PermissionError('unreviewed_bot_operation')
        b=current_binding()
        if not self.valid(b):raise PermissionError('outbound_without_bound_source')
        if str(data.get('chat_id',''))!=b.chat_id:raise PermissionError('exact_recipient_required')
        tid=data.get('message_thread_id');tid=str(tid) if tid is not None else None
        # Telegram's native adapter omits the General forum topic (1). This
        # alias applies only to an already-bound General topic in this chat.
        if b.chat_type=='group' and b.thread_id=='1' and tid is None:tid='1'
        if endpoint.startswith('edit') or endpoint in ('deleteMessage','setMessageReaction'):
            key=(b.profile,b.chat_id,str(data.get('message_id','')))
            if key not in self._sent or self._sent[key]!=b.thread_id:raise PermissionError('own_scoped_message_required')
        elif tid!=b.thread_id:raise PermissionError('exact_topic_required')
        bot=self._issued[id(b)][1]
        await self.recheck(b,bot)
    def record_sent(self,endpoint,result):
        b=current_binding()
        if not self.valid(b):return
        rows=result if isinstance(result,list) else [result]
        for row in rows:
            if isinstance(row,dict) and str((row.get('chat') or {}).get('id'))==b.chat_id and type(row.get('message_id')) is int:
                self._sent[(b.profile,b.chat_id,str(row['message_id']))]=b.thread_id
        while len(self._sent)>4096:self._sent.popitem(last=False)

class GuardedRequest(BaseRequest):
    """PTB-supported request implementation; tokens stay opaque inside its SDK.

    Checks the final serialized recipient before every request/retry. Permission
    errors may be wrapped by PTB; neither wrapper can dispatch denied bytes.
    """
    def __init__(self,delegate,gate):self.delegate=delegate;self.gate=gate
    @property
    def read_timeout(self):return self.delegate.read_timeout
    async def initialize(self):await self.delegate.initialize()
    async def shutdown(self):await self.delegate.shutdown()
    async def do_request(self,url,method,request_data=None,**kwargs):
        endpoint=url.rsplit('/',1)[-1]
        data=request_data.parameters if request_data is not None else {}
        try:await self.gate.authorize_request(endpoint,data)
        except PermissionError:raise AdmissionDenied('Atlas admission denied') from None
        code,payload=await self.delegate.do_request(url,method,request_data=request_data,**kwargs)
        if code==200:
            import json
            parsed=json.loads(payload)
            if parsed.get('ok'):self.gate.record_sent(endpoint,parsed.get('result'))
        return code,payload
