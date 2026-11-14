"""Thin Mac Telegram SDK edge. No agent, model, shell tool or project workspace."""
import asyncio
import json
import secrets
import time
from pathlib import Path
from telegram import Update, InputFile, ReactionTypeEmoji
from gateway.atlas_admission import binding_scope,canonical_username
from gateway.session import SessionSource, build_session_key
from gateway.config import Platform
from atlas_bridge.contract import PrivateStore, validate, native_event, origin_id, digest
from .protocol import Denied
from .remote import scope_for


class DeliveryJournal(PrivateStore):
    def __init__(self,path):
        super().__init__(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS origins(origin TEXT PRIMARY KEY,scope TEXT NOT NULL,revoked INTEGER NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS sends(obligation TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,origin TEXT NOT NULL,status TEXT NOT NULL,message TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS own(uid TEXT,profile TEXT,chat TEXT,topic TEXT,message TEXT,PRIMARY KEY(uid,profile,chat,topic,message))')
        self.db.execute('CREATE TABLE IF NOT EXISTS frames(nonce TEXT PRIMARY KEY)')
        self.db.execute('CREATE TABLE IF NOT EXISTS sdk_origins(origin TEXT PRIMARY KEY,metadata TEXT NOT NULL,attachments TEXT NOT NULL)')
    def remember_sdk(self,origin,metadata,attachments):
        old=self.db.execute('SELECT metadata FROM sdk_origins WHERE origin=?',(origin,)).fetchone()
        encoded=json.dumps(metadata,sort_keys=True)
        if old and old[0]!=encoded:raise Denied('original_SDK_metadata_conflict')
        self.db.execute('INSERT OR REPLACE INTO sdk_origins VALUES (?,?,?)',(origin,encoded,json.dumps(attachments,sort_keys=True)))
    def sdk(self,origin):
        row=self.db.execute('SELECT metadata,attachments FROM sdk_origins WHERE origin=?',(origin,)).fetchone()
        if not row:raise Denied('original_journalled_SDK_metadata_required')
        return json.loads(row[0]),json.loads(row[1])
    def seen(self,nonce):
        with self.transaction():
            try:self.db.execute('INSERT INTO frames VALUES (?)',(nonce,))
            except Exception:raise Denied('replayed_application_frame') from None
    def register(self,scope):
        with self.transaction():
            old=self.db.execute('SELECT scope,revoked FROM origins WHERE origin=?',(scope['origin'],)).fetchone()
            if old:
                if json.loads(old[0])!=scope:raise Denied('origin_scope_conflict')
                if old[1]:raise Denied('origin_revoked')
            else:self.db.execute('INSERT INTO origins VALUES (?,?,0)',(scope['origin'],json.dumps(scope,sort_keys=True)))
    def revoke(self,origin):self.db.execute('UPDATE origins SET revoked=1 WHERE origin=?',(origin,))
    def check(self,scope):
        old=self.db.execute('SELECT scope,revoked FROM origins WHERE origin=?',(scope['origin'],)).fetchone()
        if not old or old[1] or json.loads(old[0])!=scope:raise Denied('original_unrevoked_recipient_required')
    def reserve(self,body):
        scope=body['scope'];action=body['action'];op=action['op'];obligation=body['obligation']
        if type(obligation) is not str or len(obligation)!=64 or any(c not in '0123456789abcdef' for c in obligation):raise Denied('stable_obligation_required')
        fingerprint=digest(body)
        with self.transaction():
            self.check(scope)
            if op in ('edit','delete','react'):
                own=(scope['user_id'],scope['profile'],scope['chat_id'],scope['thread_id'] or '',str(action.get('message_id','')))
                if not self.db.execute('SELECT 1 FROM own WHERE uid=? AND profile=? AND chat=? AND topic=? AND message=?',own).fetchone():raise Denied('own_UID_topic_message_receipt_required')
            old=self.db.execute('SELECT fingerprint,status,message FROM sends WHERE obligation=?',(obligation,)).fetchone()
            if old:
                if old[0]!=fingerprint:raise Denied('obligation_identity_conflict')
                return {'status':old[1],'message_id':old[2]}
            self.db.execute('INSERT INTO sends VALUES (?,?,?,?,NULL)',(obligation,fingerprint,scope['origin'],'intent'))
            return {'status':'new','message_id':None}
    def ack(self,body,result):
        scope=body['scope'];op=body['action']['op'];mid=None
        if op in ('send','send_media','edit'):
            if (str(result.chat.id)!=scope['chat_id'] or type(result.message_id) is not int):raise Denied('actual_sdk_recipient_required')
            topic=str(result.message_thread_id) if result.message_thread_id is not None else None
            if scope['thread_id']=='1' and topic is None:topic='1'
            if topic!=scope['thread_id']:raise Denied('actual_sdk_topic_required')
            mid=str(result.message_id)
        elif result is not True:raise Denied('actual_sdk_result_required')
        with self.transaction():
            self.db.execute('UPDATE sends SET status=?,message=? WHERE obligation=?',('acked',mid,body['obligation']))
            if mid:self.db.execute('INSERT OR IGNORE INTO own VALUES (?,?,?,?,?)',(scope['user_id'],scope['profile'],scope['chat_id'],scope['thread_id'] or '',mid))
        return mid
    def close(self):self.db.close()


class MacEdge:
    def __init__(self,codec,gate,root,*,bot=None,streams=None,memory=None,thread_sessions_per_user=False):
        self.codec=codec;self.gate=gate;self.bot=bot;self.root=Path(root)
        self.journal=DeliveryJournal(self.root/'delivery.sqlite')
        self.origins={};self._attachment_manifests={};self.streams=streams;self.memory=memory;self.thread_sessions_per_user=thread_sessions_per_user
    def close(self):self.journal.close()
    def session_key(self,b):
        source=SessionSource(platform=Platform.TELEGRAM,chat_id=b.chat_id,chat_type=b.chat_type,user_id=b.user_id,thread_id=b.thread_id,profile=b.profile)
        return build_session_key(source,profile=b.profile,thread_sessions_per_user=self.thread_sessions_per_user)
    def scope(self,raw):
        record=self.origins.get(origin_id(raw))
        if not record:raise Denied('native_origin_unavailable')
        return dict(record[1])
    async def ingress(self,update):
        if type(update) is not Update or type(update.update_id) is not int or update.update_id<0 or update.message is None:raise Denied('actual_sdk_message_update_required')
        message=update.message
        b=await self.gate.admit_message(message,self.bot)
        # Topic creation is an admitted SDK service event, not a human turn.
        # Preserve text/caption/media inputs, including empty-text attachments.
        if (message.forum_topic_created is not None and not message.text
                and not message.caption and not message.effective_attachment):
            raise Denied('non_conversational_forum_topic_created')
        # Only actual PTB fields. Display names/text never supply usernames.
        now=int(time.time())
        raw={'version':1,'kind':'telegram_input','bot_id':'9229862070','epoch':self.codec.epoch,
             'nonce':secrets.token_hex(16),'issued_at':now,'expires_at':now+30,
             'update_id':str(update.update_id),'message_id':str(message.message_id),
             'user_id':b.user_id,'username':b.username,'is_bot':False,'chat_id':b.chat_id,
             'chat_type':b.chat_type,'thread_id':b.thread_id,'profile':b.profile,
             'text':message.text or message.caption or '',
             'eligibility':({'kind':'staff_username','active':True,'verified':True,'robot':False} if b.chat_type=='dm'
                            else {'kind':'tasha_admin','bot_id':'793835103','is_bot':True,'status':'administrator'})}
        validate(raw);scope=scope_for(raw,self.session_key(b));self.journal.register(scope)
        old=self.origins.get(scope['origin'])
        if old:
            if old[1]!=scope or not self.gate.valid(old[0]):raise Denied('origin_identity_conflict_or_revoked')
            b=old[0]
        self.origins[scope['origin']]=(b,scope)
        attachments=[]
        if message.effective_attachment:
            if self.streams is None:raise Denied('attachment_stream_not_configured')
            attachments=await self.streams.snapshot_sdk(message,b,scope,self.bot,self.gate)
        self._attachment_manifests[scope['origin']]=json.loads(json.dumps(attachments))
        # Metadata-only durable receipt from the actual SDK Update, never its
        # text/history, a model claim or a serialized native Binding.
        metadata={'epoch':self.codec.epoch,'update_id':update.update_id,'message':{
            'message_id':message.message_id,'date':int(message.date.timestamp()),
            'from':{k:v for k,v in message.from_user.to_dict().items() if k in ('id','is_bot','first_name','last_name','username','language_code')},
            'chat':{k:v for k,v in message.chat.to_dict().items() if k in ('id','type','is_forum')},
            'is_topic_message':message.is_topic_message}}
        if message.message_thread_id is not None:metadata['message']['message_thread_id']=message.message_thread_id
        self.journal.remember_sdk(scope['origin'],metadata,attachments)
        reads=getattr(self,'read_connector',None)
        if reads is not None:reads.remember_human(scope,message)
        return self.codec.sign('input',{'input':raw,'session_key':scope['session_key'],'attachments':attachments})
    def _binding(self,scope):
        if type(scope) is not dict:raise Denied('original_scope_required')
        self.journal.check(scope)
        pair=self.origins.get(scope['origin'])
        if not pair or pair[1]!=scope or not self.gate.valid(pair[0]):raise Denied('process_native_origin_required')
        return pair[0]
    async def recover(self,scope):
        self.journal.check(scope)
        metadata,attachments=self.journal.sdk(scope['origin'])
        if metadata.pop('epoch')!=self.codec.epoch:raise Denied('original_transport_epoch_revoked')
        if scope['chat_type']=='dm':
            current=await self.bot.get_chat(int(scope['user_id']))
            self.journal.check(scope)
            if (type(current.id) is not int or str(current.id)!=scope['user_id'] or current.type!='private'
                    or canonical_username(current.username)!=scope['username']):
                self.journal.revoke(scope['origin']);raise Denied('current_actual_SDK_username_required')
        # PTB reconstructs only the private journal's genuine SDK metadata. It
        # never accepts a from_user/username/body selected by QYP or a model.
        update=Update.de_json(metadata,self.bot)
        binding=await self.gate.admit_message(update.message,self.bot)
        self.journal.check(scope)
        if ((binding.user_id,binding.chat_id,binding.chat_type,binding.thread_id,binding.profile,binding.username)
                !=tuple(scope[k] for k in ('user_id','chat_id','chat_type','thread_id','profile','username'))
                or self.session_key(binding)!=scope['session_key']):
            self.gate._issued.pop(id(binding),None);raise Denied('original_native_recovery_scope_required')
        self.origins[scope['origin']]=(binding,dict(scope));self._attachment_manifests[scope['origin']]=attachments
        return binding
    async def recheck(self,scope):
        if type(scope) is not dict:raise Denied('original_scope_required')
        # A malformed/foreign scope cannot revoke a legitimate origin. Once
        # this exact receipt is matched, any unknown lookup latches its denial.
        self.journal.check(scope);b=None
        try:
            b=await self.recover(scope) if scope.get('origin') not in self.origins else self._binding(scope)
            await self.gate.recheck(b,self.bot)
            if not self.gate.valid(b):raise Denied('binding_revoked_during_verification')
            self.journal.check(scope);return b
        except BaseException as error:
            self.journal.revoke(scope['origin'])
            if b is not None:self.gate._issued.pop(id(b),None)
            if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt)):raise
            raise Denied('native_fresh_verification_denied') from None
    async def handle(self,envelope):
        frame=self.codec.verify(envelope);body=frame['body'];kind=frame['kind']
        self.journal.seen(frame['nonce'])
        if kind in ('work_read','work_read_cancel'):
            reads=getattr(self,'read_connector',None)
            if reads is None:raise Denied('work_read_connector_not_configured')
            return await (reads.handle(envelope) if kind=='work_read' else reads.cancel(envelope))
        if kind=='recheck':
            if set(body)!={'challenge','scope'} or type(body['challenge']) is not str or len(body['challenge'])!=32:raise Denied('closed_recheck_schema')
            try:await self.recheck(body['scope']);allowed=True
            except PermissionError:allowed=False
            return self.codec.sign('recheck_result',{**body,'allowed':allowed})
        if kind=='refresh_input':
            if set(body)!={'input','session_key','attachments'}:raise Denied('closed_refresh_input_schema')
            validate(body['input']);scope=scope_for(body['input'],body['session_key'])
            if body['input']['epoch']!=self.codec.epoch:raise Denied('original_transport_epoch_required')
            await self.recheck(scope)
            if body['attachments']!=self._attachment_manifests.get(scope['origin']):raise Denied('original_SDK_attachments_required')
            return self.codec.sign('input',body)
        if kind=='egress':return self.codec.sign('egress_result',await self.deliver(body))
        if kind in ('stream_open','stream_chunk','stream_close'):
            if self.streams is None:raise Denied('stream_provider_not_configured')
            # Authenticated exact-owner deletion is permitted after revocation;
            # receiver schema/owner checks still deny reads, publication and foreign cleanup.
            if not (kind=='stream_close' and body.get('abort') is True):await self.recheck(body['scope'])
            return self.codec.sign('stream_result',await self.streams.handle(kind,body))
        if kind=='memory':
            if self.memory is None:raise Denied('shared_Honcho_provider_not_configured')
            await self.recheck(body['scope']);result=await self.memory.handle(body)
            await self.recheck(body['scope'])
            return self.codec.sign('memory_result',result)
        raise Denied('unreviewed_application_kind')
    async def deliver(self,body):
        if type(body) is not dict or set(body)!={'scope','obligation','action'}:raise Denied('closed_egress_schema')
        scope=body['scope'];action=body['action']
        if type(action) is not dict or not action.get('op'):raise Denied('closed_output_action')
        op=action['op']
        shapes={'send':{'op','content'},'edit':{'op','message_id','content'},'delete':{'op','message_id'},
                'react':{'op','message_id','emoji','remove'},'typing':{'op'},'send_media':{'op','export_id','caption','kind'}}
        # Compatibility with old trusted frames; native adapters always send a
        # bounded boolean. This never widens the SDK operation dispatch surface.
        if op=='react' and 'remove' not in action:action={**action,'remove':False}
        if op=='send_media' and 'filename' in action:
            shapes[op]=shapes[op]|{'filename'}
            if type(action['filename']) is not str or action['filename'] not in {'atlas-export.'+ext for ext in ('bin','docx','pptx','xlsx','pdf','csv','txt','png','jpg')}:raise Denied('closed_export_filename_required')
        if op not in shapes or set(action)!=shapes[op]:raise Denied('unreviewed_output_operation')
        if op=='react' and type(action['remove']) is not bool:raise Denied('boolean_reaction_remove_required')
        if 'content' in action and (type(action['content']) is not str or len(action['content'].encode('utf-16-le'))//2>4096):raise Denied('bounded_output_required')
        b=await self.recheck(scope)
        state=self.journal.reserve(body)
        base={'obligation':body['obligation'],'chat_id':b.chat_id,'thread_id':b.thread_id,'message_id':state['message_id']}
        if state['status']=='acked':return {**base,'success':True,'deduplicated':True}
        if state['status']!='new':return {**base,'success':False,'ambiguous':True}
        if op in ('edit','delete','react'):
            # reserve() just verified an actual persisted SDK ACK bound to this
            # exact UID/profile/chat/topic/message. Rehydrate only that receipt
            # for the native SDK guard, not an unbounded historical cache.
            self.gate._sent[(b.profile,b.chat_id,str(action['message_id']))]=b.thread_id
            while len(self.gate._sent)>4096:self.gate._sent.popitem(last=False)
        kwargs={'chat_id':int(b.chat_id)}
        topic={'message_thread_id':int(b.thread_id)} if b.thread_id is not None else {}
        try:
            # GuardedRequest checks the final serialized recipient and native
            # policy after its awaits, immediately before the SDK delegate.
            with binding_scope(b):
                if op=='send':result=await self.bot.send_message(**kwargs,**topic,text=action['content'],parse_mode=None)
                elif op=='edit':result=await self.bot.edit_message_text(**kwargs,message_id=int(action['message_id']),text=action['content'],parse_mode=None)
                elif op=='delete':result=await self.bot.delete_message(**kwargs,message_id=int(action['message_id']))
                elif op=='react':result=await self.bot.set_message_reaction(**kwargs,message_id=int(action['message_id']),reaction=[] if action['remove'] else [ReactionTypeEmoji(action['emoji'])])
                elif op=='typing':result=await self.bot.send_chat_action(**kwargs,**topic,action='typing')
                else:
                    if self.streams is None:raise Denied('export_stream_not_configured')
                    with self.streams.open_completed(action['export_id'],scope,transport_cap=50_000_000) as file:
                        # PTB's default eagerly reads file handles. Explicitly
                        # retain incremental multipart streaming at this boundary.
                        document=InputFile(file,filename=action.get('filename','atlas-export.bin'),read_file_handle=False)
                        result=await self.bot.send_document(**kwargs,**topic,document=document,caption=action['caption'] or None)
            mid=self.journal.ack(body,result)
            if op=='send_media' and callable(getattr(self.streams,'discard_outbound',None)):
                self.streams.discard_outbound(action['export_id'],scope)
            await self.recheck(scope)
            return {**base,'message_id':mid,'success':True}
        except PermissionError:raise
        except (Exception,SystemExit):
            # INTENT remains durable even when bytes might have been posted.
            # No blind retry, alternate send or text fallback can follow.
            return {**base,'success':False,'ambiguous':True}


if __name__=='__main__':
    from .edge_cli import main
    main()
