"""Real native Atlas authority for an authenticated Mac application transport.

Bindings remain process-local objects issued by AdmissionGate. No JSON boolean,
ambient session variable or deserialized Binding is ever an authorization grant.
"""
import asyncio
from contextlib import contextmanager
import json
import secrets
import time
from pathlib import Path
from gateway.atlas_admission import AdmissionGate, Binding, current_binding, binding_scope
from gateway.relay.ws_transport import WebSocketRelayTransport, _event_from_wire
from gateway.session_ingress_context import _relay_callback, relay_callback
from atlas_bridge.contract import validate, native_event, input_fingerprint, origin_id, digest
from .protocol import Denied, Codec, decode


def scope_for(raw,session_key):
    return {k:raw[k] for k in ('bot_id','user_id','chat_id','chat_type','thread_id','profile','username')} | {
        'origin':origin_id(raw),'message_id':raw['message_id'],'session_key':session_key,
        'input_sha256':input_fingerprint(raw)}


@contextmanager
def turn_scope(binding):
    with binding_scope(binding):yield


class RemoteAdmissionGate(AdmissionGate):
    def __init__(self,codec,*,exchange=None,provision=None,replay_store=None):
        super().__init__(provision=provision)
        self.codec=codec;self.exchange=exchange;self._remote={};self._origins={};self._texts={}
        self._pending={};self._active=set()
        # Reuse the hub's durable fingerprint store, never retain raw retired
        # inputs or infer a new grant from an empty process-local cache.
        if replay_store is None:
            from hermes_constants import get_hermes_home
            from .stores import PendingInbox
            replay_store=PendingInbox(get_hermes_home()/'atlas-bridge'/'pending.sqlite')
        self._replay=replay_store
    def activate_source(self,source):
        if not self.source_authorized(source):raise Denied('issued_native_source_required')
        b=source._atlas_binding;handle=self._pending.pop(id(b),None)
        if handle is not None:handle.cancel()
        self._active.add(id(b))
    def expire_pending(self,b):
        if id(b) not in self._active:self.revoke(b)
    def queue_source(self,source):
        if not self.source_authorized(source):raise Denied('issued_native_source_required')
        b=source._atlas_binding;self._active.discard(id(b))
        handle=self._pending.pop(id(b),None)
        if handle is not None:handle.cancel()
        self._pending[id(b)]=asyncio.get_running_loop().call_later(600,self.expire_pending,b)
    def complete_source(self,source):
        # Invoked only by the closed native lifecycle, after all native media,
        # tool and post-delivery callbacks; no model-facing completion operation.
        b=getattr(source,'_atlas_binding',None)
        if self.valid(b):self.revoke(b)
    def close(self):
        for b,_,_ in list(self._issued.values()):self.revoke(b)
        self._replay.close()
    def canonical_text(self,b):
        if not self.valid(b):raise Denied('unissued_remote_binding')
        return self._texts[id(b)]
    def scope(self,b):
        if not self.valid(b) or id(b) not in self._remote:raise Denied('unissued_remote_binding')
        return dict(self._remote[id(b)])
    def revoke(self,b):
        self._issued.pop(id(b),None)
        scope=self._remote.pop(id(b),None);self._texts.pop(id(b),None)
        self._active.discard(id(b))
        handle=self._pending.pop(id(b),None)
        if handle is not None:handle.cancel()
        if scope is not None:self._origins.pop(scope['origin'],None)
        # The durable claim fingerprint survives; no raw origin/scope/text is
        # needed to latch revocation or a late positive verification response.
    async def recheck(self,b,bot=None):
        if not self.valid(b):raise Denied('unissued_binding')
        scope=self.scope(b);challenge=secrets.token_hex(16)
        request={'challenge':challenge,'scope':scope}
        try:
            if self.exchange is None:raise Denied('mac_verification_unavailable')
            response=await asyncio.wait_for(self.exchange('recheck',request),5)
            frame=self.codec.verify(response)
            if (frame['kind']!='recheck_result' or frame['body']!={**request,'allowed':True}):raise Denied('fresh_verification_denied')
            if not self.valid(b) or self.scope(b)!=scope:raise Denied('binding_revoked_during_verification')
        except BaseException:
            self.revoke(b);raise
        self._issued[id(b)]=(b,None,time.monotonic())
        return b

    async def admit_transport(self,event,envelope,transport,runner):
        delivered=_relay_callback.get()
        if (not isinstance(transport,WebSocketRelayTransport) or transport._ws is None or transport.auth_revoked
                or transport._closing or delivered is None or delivered[0] is not transport or delivered[1] is not event
                or transport._bot_id_for('telegram')!='9229862070' or not transport._gateway_id or not transport._upgrade_secret):
            raise Denied('native_authenticated_reader_required')
        frame=self.codec.verify(envelope)
        if frame['kind']!='input' or set(frame['body'])!={'input','session_key','attachments'}:raise Denied('signed_native_input_required')
        raw=validate(frame['body']['input'])
        if raw['epoch']!=self.codec.epoch:raise Denied('original_transport_epoch_required')
        scope=scope_for(raw,frame['body']['session_key'])
        if type(scope['session_key']) is not str or not scope['session_key']:raise Denied('canonical_session_required')
        expected=_event_from_wire(native_event(raw))
        if (event.source.to_dict()!=expected.source.to_dict() or event.text!=expected.text
                or event.message_id!=expected.message_id or event.message_type!=expected.message_type
                or event.media_urls):raise Denied('canonical_native_dto_mismatch')
        # Fresh actual SDK identity supersedes old username claims before lookup.
        for old,_,_ in list(self._issued.values()):
            if old.chat_type=='dm' and old.user_id==raw['user_id'] and old.username!=raw['username']:self.revoke(old)
        origin=scope['origin']
        previous=self._origins.get(origin)
        if previous:
            b,old_scope=previous
            if old_scope!=scope:raise Denied('input_identity_conflict')
            if not self.valid(b):raise Denied('input_authority_revoked')
        else:
            if not self._replay.nonce('native:'+digest({'origin':origin}),scope):
                raise Denied('input_authority_retired')
            b=Binding(raw['user_id'],raw['chat_id'],raw['chat_type'],raw['thread_id'],raw['profile'],raw['username'])
            self._remote[id(b)]=scope;self._origins[origin]=(b,scope);self._texts[id(b)]=raw['text']
            self._issued[id(b)]=(b,None,0)
        try:
            await self.recheck(b)
            self._loop=asyncio.get_running_loop()
            if self.provision is not None:
                await self.provision(b)
                await self.recheck(b)
            if runner._session_key_for_source(event.source)!=scope['session_key']:raise Denied('canonical_native_session_mismatch')
            if not self.valid(b):raise Denied('binding_revoked_during_provision')
            self.stamp_source(event.source,b)
            # Only queued proof lifetime; active native work has no TTL/cap.
            if id(b) not in self._active and id(b) not in self._pending:
                self._pending[id(b)]=self._loop.call_later(600,self.expire_pending,b)
            return b
        except BaseException:
            self.revoke(b);raise

    async def outbound(self,action):
        b=current_binding()
        if not self.valid(b):raise Denied('outbound_without_bound_source')
        scope=self.scope(b)
        if str(action.get('chat_id',''))!=b.chat_id:raise Denied('exact_recipient_required')
        md=action.get('metadata') or {}
        tid=md.get('thread_id',b.thread_id);tid=str(tid) if tid is not None else None
        if b.thread_id is not None and tid is None and b.thread_id=='1':tid='1'
        if tid!=b.thread_id:raise Denied('exact_topic_required')
        # Profile/user caches are not authority. The selected wire scope below
        # comes exclusively from this issued original turn, never the last chat actor.
        op=action.get('op')
        if op not in ('send','edit','delete','react','typing','send_media'):raise Denied('unreviewed_output_operation')
        allowed={'op','chat_id','content','reply_to','message_id','emoji','metadata','export_id','caption','kind'}
        if op=='react':allowed.add('remove')
        if op=='send_media':allowed.add('filename')
        if set(action)-allowed:raise Denied('closed_output_schema')
        if 'filename' in action and (type(action['filename']) is not str or action['filename'] not in {'atlas-export.'+ext for ext in ('bin','docx','pptx','xlsx','pdf','csv','txt','png','jpg')}):raise Denied('closed_export_filename_required')
        if op=='react' and 'remove' in action and type(action['remove']) is not bool:raise Denied('boolean_reaction_remove_required')
        content=action.get('content','')
        if type(content) is not str or len(content.encode('utf-16-le'))//2>4096:raise Denied('bounded_text_required')
        await self.recheck(b)
        # The authenticated original turn is the ONLY recipient, irrespective of
        # the adapter's last-chat actor cache or model-provided metadata.
        selected={k:action[k] for k in ('op','content','message_id','emoji','export_id','caption','kind') if k in action}
        if op=='send_media' and 'filename' in action:selected['filename']=action['filename']
        if op=='react':selected['remove']=action.get('remove',False)
        obligation=digest({'scope':scope,'action':selected})
        return {'scope':scope,'obligation':obligation,'action':selected}


def native_receipt(runner,event):
    """Reconcile against the actual canonical native ledger BEFORE minting a binding.

    Replayed committed rows are acknowledged without issuing authority, even
    after process restart/expiry/proof loss. Never replay a model generation.
    """
    from gateway.session_authorities import authority_for_home
    home=runner._resolve_profile_home_for_source(event.source)
    authority=authority_for_home(runner,home)
    if authority is None:return None
    s=event.source
    principal='messaging:'+json.dumps([s.profile,s.platform.value,s.chat_id,s.thread_id,s.user_id],separators=(',',':'))
    rows=authority.db._read_all('SELECT admission_id,status,payload_json FROM session_admissions WHERE principal_id=? AND request_id=?',(principal,event.message_id))
    if not rows:return None
    if len(rows)!=1:raise Denied('native_ledger_identity_conflict')
    stored=json.loads(rows[0]['payload_json'])['native_text_v1']
    # Native durable fingerprints include rewritten content. Scope cannot be
    # borrowed; original content is independently pinned in the hub inbox.
    source=stored['source']
    if any(source.get(k)!=getattr(s,k) for k in ('user_id','chat_id','thread_id','profile')):raise Denied('native_ledger_scope_conflict')
    return {'status':rows[0]['status'],'admission_id':rows[0]['admission_id']}


def _diagnose_admission_refusal(error):
    """Closed diagnostic vocabulary only; telemetry cannot alter admission/ACK."""
    try:
        import logging
        codes = frozenset((
            'native_receipt_absent', 'profile_admin_capability_required', 'native_profile_provision_failed',
            'native_profile_not_served', 'native_profile_receipt_mismatch',
            'native_profile_interpreter_required', 'trusted_native_helper_required',
            'input_authority_retired', 'fresh_verification_denied',
            'binding_revoked_during_provision', 'canonical_native_session_mismatch',
        ))
        reason = (error.args[0] if len(error.args) == 1 and type(error.args[0]) is str
                  and error.args[0] in codes else 'unclassified')
        kind = type(error).__name__ if type(error) in (PermissionError, KeyError, ValueError, Denied) else 'subclass'
        logging.getLogger(__name__).warning(
            'ATLAS_ADMISSION_REFUSAL_V1 phase=native_admit_after type=%s reason=%s', kind, reason)
    except Exception:
        pass


class AtlasWebSocketRelayTransport(WebSocketRelayTransport):
    """Native reader/provenance preserved; fresh checks run OFF its reader."""
    def __init__(self,*args,gate,**kwargs):
        super().__init__(*args,**kwargs);self.gate=gate;self._control={};self._admissions={};self._tasks=set()
        self.gate.exchange=self.exchange
    async def exchange(self,kind,body):
        request=body.get('challenge') or secrets.token_hex(16)
        fut=asyncio.get_running_loop().create_future();self._control[request]=fut
        try:
            await self._send({'type':'atlas_control','envelope':self.gate.codec.sign(kind,body)})
            return await asyncio.wait_for(fut,5)
        finally:self._control.pop(request,None)
    async def _handle_frame(self,line):
        frame=decode(line)
        if frame.get('type')=='atlas_control_result' and set(frame)=={'type','envelope'}:
            signed=self.gate.codec.verify(frame['envelope']);request=signed['body'].get('challenge')
            fut=self._control.get(request)
            if fut is not None and not fut.done():
                # request is only transport correlation; remove it from the
                # signed response by retaining original envelope to gate check.
                fut.set_result(frame['envelope'])
            return
        if frame.get('type')=='inbound':
            if set(frame)!={'type','event','bufferId','atlas_envelope'}:raise Denied('closed_native_input_frame')
            event=_event_from_wire(frame['event'])
            # Context is minted here by the actual native transport's reader,
            # never by DTO flags or a gateway-client session.submit call.
            with relay_callback(self,event):
                previous=self._admissions.get(event.source.chat_id)
                task=asyncio.create_task(self._admit_after(previous,event,frame))
            self._admissions[event.source.chat_id]=task;self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            chat_id=event.source.chat_id
            def completed(done):
                if self._admissions.get(chat_id) is done:self._admissions.pop(chat_id,None)
            task.add_done_callback(completed)
            return
        if frame.get('type') not in ('descriptor','outbound_result','going_idle_ack'):raise Denied('unreviewed_native_frame')
        return await super()._handle_frame(line)
    async def _admit_after(self,previous,event,frame):
        if previous is not None:await asyncio.wait([previous])
        runner=getattr(self._inbound,'__self__',None)
        runner=getattr(getattr(runner,'_message_handler',None),'__self__',None)
        if runner is None:raise Denied('native_gateway_runner_required')
        snapshots=[];b=None;receipt=None
        try:
            # Expired authentic signatures can ONLY reconcile an existing native
            # durable row. They never enter the authority constructor below.
            proof=self.gate.codec.verify(frame['atlas_envelope'],for_reconciliation=True)
            if proof['kind']!='input' or set(proof['body'])!={'input','session_key','attachments'}:raise Denied('signed_input_required')
            raw=validate(proof['body']['input'])
            expected=_event_from_wire(native_event(raw))
            if event.source.to_dict()!=expected.source.to_dict() or event.text!=expected.text:raise Denied('canonical_native_dto_mismatch')
            if runner._session_key_for_source(event.source)!=proof['body']['session_key']:raise Denied('canonical_native_session_mismatch')
            receipt=native_receipt(runner,event)
            if receipt is None:
                if int(time.time())>=proof['exp']:
                    await self._send({'type':'atlas_need_refresh','bufferId':frame['bufferId']});return
                b=await self.gate.admit_transport(event,frame['atlas_envelope'],self,runner)
                # Native attachment/provision work is active work, not queue TTL.
                self.gate.activate_source(event.source)
                if proof['body']['attachments']:
                    from .attachments import fetch_attachments
                    home=runner._resolve_profile_home_for_source(event.source)
                    async def exchange(kind,body):
                        signed=await self.exchange(kind,body);response=self.gate.codec.verify(signed)
                        if response['kind']!='stream_result':raise Denied('signed_attachment_response_required')
                        return response['body']
                    snapshots=await fetch_attachments(proof['body']['attachments'],self.gate.scope(b),home/'bridge-inputs',exchange,fresh=lambda:self.gate.recheck(b))
                    event._atlas_streamed_snapshots=tuple(snapshots)
                    event.media_urls=[item.local_path for item in snapshots]
                    event.media_types=['application/octet-stream']*len(snapshots)
                    event.media_filenames=[item.manifest['filename'] for item in snapshots]
                await self.gate.recheck(b)
                admitting=await self._inbound(event)
                if admitting is not None:await admitting
                receipt=native_receipt(runner,event)
                if receipt is None:
                    # Command path is native bound /stop (no arbitrary interrupt RPC).
                    receipt={'status':'command' if event.get_command() else 'refused','admission_id':frame['bufferId']}
                    if not event.get_command():_diagnose_admission_refusal(Denied('native_receipt_absent'))
            await self._send({'type':'atlas_inbound_ack','bufferId':frame['bufferId'],'receipt':receipt})
        except (PermissionError,KeyError,ValueError) as error:
            _diagnose_admission_refusal(error)
            # Fixed rejection, no private content/SDK responses. Refusal is
            # terminal transport evidence, never a forged native queued receipt.
            await self._send({'type':'atlas_inbound_ack','bufferId':frame['bufferId'],
                              'receipt':{'status':'refused','admission_id':frame['bufferId']}})
        finally:
            if b is not None:
                # A cancelled caller can lose the receipt after the native
                # shielded commit. Its queued proof, not this caller, now owns
                # completion; never invalidate legitimate committed work here.
                committed=receipt if receipt is not None else native_receipt(runner,event)
                # A cold command can be accepted into the adapter's native
                # background lifecycle even while a durable FIFO worker is busy
                # (the FIFO owns no adapter guard). Its complete_source finally,
                # not this intent-only ACK, now owns the issued source lifetime.
                command_handoff=(event.get_command() and getattr(event,'_gateway_accepted',False) is True)
                if (committed is None or committed['status'] in ('command','refused')) and not command_handoff:self.gate.revoke(b)
            receivers={id(item.receiver):item.receiver for item in snapshots}
            for item in snapshots:item.discard()
            for receiver in receivers.values():receiver.close()
    async def local_media_ready(self,event):
        b=getattr(event.source,'_atlas_binding',None)
        if not self.gate.source_authorized(event.source):raise Denied('issued_native_media_source_required')
        snapshots=getattr(event,'_atlas_streamed_snapshots',())
        if event.media_urls!=[item.local_path for item in snapshots]:raise Denied('typed_local_attachment_paths_required')
        await self.gate.recheck(b)
    async def send_export(self,*,chat_id,media_kind,source,source_is_path,caption=None,filename=None,reply_to=None,metadata=None):
        from gateway.platforms.base import SendResult
        from gateway.media_delivery_gate import resolve_media_upload
        from .media import open_export,push_export,abort_stream
        b=current_binding();export=None;exchange=None
        try:
            if not source_is_path or not self.gate.valid(b):raise Denied('native_issued_export_required')
            await self.gate.recheck(b)
            mandatory,safe=resolve_media_upload(source,chat_id)
            if mandatory is not True or safe!=source:raise Denied('native_immutable_export_policy_required')
            scope=self.gate.scope(b)
            export=await open_export(safe,scope)
            # Only the broker-approved immutable path supplies a finite label.
            # Caller filename and basename never grant path or metadata authority.
            suffix=Path(safe).suffix.lower().lstrip('.')
            label='atlas-export.'+(suffix if suffix in ('docx','pptx','xlsx','pdf','csv','txt','png','jpg') else 'bin')
            # The path is never transferred when the public transport cannot
            # accept the upload; the 2 GiB QYP export remains valid internally.
            if export.manifest['size']>50_000_000:
                return SendResult(success=False,error='Telegram_public_upload_cap_50MB',raw_response={'success':False,'code':'transport_capacity'})
            export.export_id=digest({'scope':scope,'sha256':export.manifest['sha256'],'size':export.manifest['size']})[:32]
            export.manifest['export_id']=export.export_id
            async def exchange(kind,body):
                signed=await self.exchange(kind,body);verified=self.gate.codec.verify(signed)
                if verified['kind']!='stream_result':raise Denied('signed_stream_result_required')
                return verified['body']
            await push_export(export,exchange,fresh=lambda:self.gate.recheck(b))
            # Mac receives only this opaque export ID, never a QYP filesystem path.
            result=await self.send_outbound({'op':'send_media','chat_id':chat_id,
                'export_id':export.export_id,'caption':caption or '', 'kind':media_kind,
                'filename':label,
                'metadata':metadata or {}},platform='telegram')
            if not result.get('success'):await abort_stream(exchange,export.scope,export.export_id,export.transfer_id)
            return SendResult(success=bool(result.get('success')),message_id=result.get('message_id'),error=result.get('error'),raw_response=result)
        except (PermissionError,OSError,ValueError):
            if export is not None and exchange is not None:await abort_stream(exchange,export.scope,export.export_id,export.transfer_id)
            return SendResult(success=False,error='atlas_export_stream_denied',raw_response={'success':False,'code':'egress_declined'})
        except BaseException:
            if export is not None and exchange is not None:await abort_stream(exchange,export.scope,export.export_id,export.transfer_id)
            raise
        finally:
            if export is not None:export.close()
    async def send_outbound(self,action,*,platform=None):
        try:
            if platform not in (None,'telegram'):raise Denied('fixed_bot_only')
            body=await self.gate.outbound(action)
            envelope=self.gate.codec.sign('egress',body)
            result=await super().send_outbound({'op':'atlas_egress','envelope':envelope},platform='telegram')
            if not result.get('success') and result.get('code')!='egress_declined':
                result={**result,'ambiguous':True}
            return result
        except PermissionError:return {'success':False,'error':'telegram egress declined: Atlas admission denied','code':'egress_declined'}
    async def send_follow_up(self,action,*,platform=None):return await self.send_outbound(action,platform=platform)
    async def disconnect(self,**kwargs):
        tasks=list(self._tasks)
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        await super().disconnect(**kwargs)
