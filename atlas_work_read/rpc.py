"""Closed work-read AppRPC over the existing authenticated stdio Hub.

Wire fragmentation is transport-only: the consumer receives the unchanged
published JSON result, not a host path or a clipped JSON string.
"""
import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from atlas_bridge.contract import Denied,canonical,digest
from atlas_native_bridge.protocol import Codec,MAX_FRAME,CHUNK
from .bundle import METHODS

ReadCodec=Codec
SCOPE=frozenset(('bot_id','user_id','chat_id','chat_type','thread_id','profile','username','origin','message_id','session_key','input_sha256'))
TURN=frozenset(('admission_id','session_id','generation','authority_epoch'))
BODY=frozenset(('scope','turn','method','arguments','bundle_id','challenge','call_sha256'))

def validate_body(body):
    if type(body)is not dict or set(body)!=BODY:raise Denied('closed_work_read_required')
    if body['method'] not in METHODS or type(body['arguments'])is not dict:raise Denied('closed_work_read_method')
    s=body['scope'];t=body['turn']
    if type(s)is not dict or set(s)!=SCOPE or type(t)is not dict or set(t)!=TURN:raise Denied('native_turn_scope_required')
    if (s['bot_id']!='9229862070' or s['chat_type'] not in ('dm','group')
        or any(type(s[k])is not str or not s[k] for k in SCOPE-{'thread_id','username'})
        or (s['thread_id'] is not None and (type(s['thread_id'])is not str or not re.fullmatch(r'[1-9][0-9]{0,19}',s['thread_id'])))
        or (s['username'] is not None and (type(s['username'])is not str or not re.fullmatch(r'[a-z0-9_]{1,32}',s['username'])))
        or not re.fullmatch(r'[1-9][0-9]{0,19}',s['user_id'])
        or type(t['generation'])is not int or t['generation']<=0
        or any(type(t[k])is not str or not 0<len(t[k])<=256 for k in TURN-{'generation'})
        or re.fullmatch(r'[1-9][0-9]{0,255}',t['authority_epoch'])is None
        or type(body['challenge'])is not str or not re.fullmatch(r'[0-9a-f]{32}',body['challenge'])
        or type(body['bundle_id'])is not str or not re.fullmatch(r'[0-9a-f]{64}',body['bundle_id'])):raise Denied('native_turn_scope_required')
    if body['call_sha256']!=digest({k:v for k,v in body.items() if k!='call_sha256'}):raise Denied('exact_read_call_required')
    return body

def request(scope,turn,method,arguments,bundle_id):
    body=json.loads(canonical({'scope':scope,'turn':turn,'method':method,'arguments':arguments,'bundle_id':bundle_id,'challenge':secrets.token_hex(16)}))
    body['call_sha256']=digest(body)
    return validate_body(body)

def respond(codec,body,value):
    raw=canonical(value);sha=hashlib.sha256(raw).hexdigest();parts=[raw[i:i+CHUNK] for i in range(0,len(raw),CHUNK)]
    return [codec.sign('work_read_result',{'challenge':body['challenge'],'call_sha256':body.get('call_sha256'),
        'index':i,'parts':len(parts),'sha256':sha,'json_utf8':base64.b64encode(part).decode()}) for i,part in enumerate(parts)]

def consume(codec,body,envelopes):
    raw=[];expected=None
    if type(envelopes)is not list or not envelopes:raise Denied('read_reply_required')
    nonces=set()
    for i,envelope in enumerate(envelopes):
        frame=codec.verify(envelope);p=frame['body']
        if frame['kind']!='work_read_result' or frame['nonce'] in nonces or set(p)!={'challenge','call_sha256','index','parts','sha256','json_utf8'}:raise Denied('closed_read_reply_required')
        nonces.add(frame['nonce'])
        if (p['challenge']!=body['challenge'] or p['call_sha256']!=body.get('call_sha256') or type(p['index'])is not int or p['index']!=i or type(p['parts'])is not int or p['parts']!=len(envelopes)
            or type(p['json_utf8'])is not str or type(p['sha256'])is not str or not re.fullmatch(r'[0-9a-f]{64}',p['sha256'])):raise Denied('exact_read_reply_required')
        if expected is None:expected=p['sha256']
        if expected!=p['sha256']:raise Denied('read_reply_integrity')
        try:part=base64.b64decode(p['json_utf8'],validate=True)
        except ValueError:raise Denied('read_reply_integrity') from None
        if len(part)>CHUNK:raise Denied('bounded_read_reply_required')
        raw.append(part)
    raw=b''.join(raw)
    if hashlib.sha256(raw).hexdigest()!=expected:raise Denied('read_reply_integrity')
    try:value=json.loads(raw)
    except (ValueError,UnicodeError):raise Denied('read_reply_integrity') from None
    if type(value)is not dict or type(value.get('ok'))is not bool:raise Denied('published_result_required')
    return value

def original_human_urls(text):
    """Lossless bare tokens only; ambiguous spelling is denied, never repaired.

    ASCII whitespace delimits plain URLs. Quotes, Markdown, raw non-ASCII and
    punctuation may belong to the query: reject the WHOLE token, not a prefix.
    Percent escapes stay byte-for-byte unchanged; no decode/strip/normalization.
    This extracts data only; SDK/native binding and trace policy remain required.
    """
    urls=[]
    for token in re.split(r'[ \t\r\n]+',text):
        if (not token.startswith('https://') or not token.isascii()
            or any(ord(c)<33 or ord(c)>126 or c in '\"\'<>()[]{}\\`|^' for c in token)
            or token.endswith(('.',',',';',':','!','?'))
            or re.search(r'%(?![0-9a-fA-F]{2})',token)):
            continue
        urls.append(token)
    return urls

class MacReadConnector:
    def __init__(self,edge,backend,*,trace=None,peer_bundle_pins=None):
        from .bundle import FILES
        if peer_bundle_pins is not None and (type(peer_bundle_pins)is not dict or set(peer_bundle_pins)!=FILES or any(type(v)is not str or not re.fullmatch(r'[0-9a-f]{64}',v) for v in peer_bundle_pins.values())):raise Denied('exact_reviewed_peer_bundle_required')
        self.peer_bundle_id=digest(peer_bundle_pins) if peer_bundle_pins is not None else backend.bundle_id
        self.edge=edge;self.backend=backend;self.trace=trace;self._seen={};self._human_urls={};self._active={};self._cancelled={}
    def remember_human(self,scope,message):
        """Called only by MacEdge.ingress with the actual admitted SDK Message."""
        from telegram import Message
        if not isinstance(message,Message) or message.from_user is None or message.from_user.is_bot or str(message.from_user.id)!=scope['user_id'] or str(message.chat.id)!=scope['chat_id']:raise Denied('original_sdk_human_required')
        self.edge.journal.check(scope)
        text=message.text or message.caption or ''
        # Identity is already the exact SDK journalled origin, not tool parameters.
        self._human_urls[scope['origin']]=frozenset(original_human_urls(text))
        remember=getattr(self.trace,'remember_human',None)
        if remember is not None:remember(scope,message)
    async def handle(self,envelope):
        frame=self.edge.codec.verify(envelope)
        if frame['kind']!='work_read':raise Denied('closed_read_kind')
        body=validate_body(frame['body'])
        now=time.time();self._seen={k:v for k,v in self._seen.items() if v>now}
        if frame['nonce'] in self._seen:raise Denied('replayed_application_frame')
        self._seen[frame['nonce']]=frame['exp']
        self._cancelled={k:v for k,v in self._cancelled.items() if v[1]>now}
        if self._cancelled.get(frame['nonce'],(None,))[0]==body['call_sha256']:raise asyncio.CancelledError()
        self._active[frame['nonce']]=(body['call_sha256'],asyncio.current_task())
        try:return await self._execute(body)
        finally:self._active.pop(frame['nonce'],None)
    async def cancel(self,envelope):
        frame=self.edge.codec.verify(envelope)
        if frame['kind']!='work_read_cancel' or set(frame['body'])!={'request'}:raise Denied('closed_read_cancel_required')
        original=self.edge.codec.verify(frame['body']['request'],for_reconciliation=True)
        if original['kind']!='work_read':raise Denied('original_read_cancel_required')
        body=validate_body(original['body']);nonce=original['nonce']
        self._cancelled[nonce]=(body['call_sha256'],time.time()+600)
        active=self._active.get(nonce)
        if active is not None:
            if active[0]!=body['call_sha256']:raise Denied('exact_read_cancel_required')
            active[1].cancel()
        return []
    async def _execute(self,body):
        scope=body['scope']
        if body['bundle_id']!=self.peer_bundle_id:raise Denied('reviewed_peer_bundle_required')
        await self.edge.recheck(scope)
        await self.backend.validate(body['method'],body['arguments'])
        if body['method']=='trace_read':
            if self.trace is None or body['arguments'].get('url') not in self._human_urls.get(scope['origin'],()):raise Denied('original_human_selected_trace_required')
            read_call=getattr(self.trace,'read_call',None)
            if read_call is not None:value=await read_call(body)
            else:value=await asyncio.to_thread(self.trace.read,scope,body['arguments']['url'],body['arguments'].get('max_chars',12000))
        else:value=await self.backend.call(scope,body['method'],body['arguments'])
        await self.edge.recheck(scope)
        return respond(self.edge.codec,body,value)

class HubReadChannel:
    """Hub-owned correlation table; never a second native gateway connection."""
    def __init__(self,hub):self.hub=hub;self.pending={};self.clients=set();self.cancelled={}
    async def exchange(self,envelope):
        peer=Codec(self.hub.codec._key,self.hub.codec.epoch,'mac')
        frame=peer.verify(envelope)
        if frame['kind']!='work_read':raise Denied('closed_read_kind')
        body=validate_body(frame['body']);challenge=body['challenge']
        if challenge in self.pending:raise Denied('read_already_pending')
        fut=asyncio.get_running_loop().create_future();self.pending[challenge]=(body,fut,[])
        try:
            await self.hub.write(envelope)
            return await fut
        except asyncio.CancelledError:
            self.cancelled[challenge]=(body['call_sha256'],time.time()+600)
            try:await self.hub.write(self.hub.codec.sign('work_read_cancel',{'request':envelope}))
            except (PermissionError,OSError):pass
            raise
        finally:self.pending.pop(challenge,None)
    def accept(self,envelope):
        frame=self.hub.codec.verify(envelope)
        if frame['kind']!='work_read_result':raise Denied('closed_read_reply_required')
        p=frame['body'];entry=self.pending.get(p.get('challenge'))
        self.cancelled={k:v for k,v in self.cancelled.items() if v[1]>time.time()}
        if entry is None:
            if self.cancelled.get(p.get('challenge'),(None,))[0]==p.get('call_sha256'):return
            raise Denied('unknown_read_challenge')
        body,fut,pages=entry
        if p.get('call_sha256')!=body['call_sha256'] or p.get('index')!=len(pages):raise Denied('exact_read_reply_required')
        pages.append(envelope)
        if p.get('parts')==len(pages):
            consume(self.hub.codec,body,pages)
            if not fut.done():fut.set_result(pages)
    async def close(self):
        tasks=list(self.clients)
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
    async def serve_client(self,reader,writer):
        task=asyncio.current_task();self.clients.add(task);running=[]
        try:
            from atlas_native_bridge.protocol import decode
            raw=await reader.readline()
            response=asyncio.create_task(self.exchange(decode(raw)))
            disconnected=asyncio.create_task(reader.read(1));running=[response,disconnected]
            done,_=await asyncio.wait(running,return_when=asyncio.FIRST_COMPLETED)
            if disconnected in done:raise Denied('closed_read_client_disconnected')
            pages=await response
            for page in pages:writer.write(canonical(page)+b'\n')
            await writer.drain()
        except PermissionError:pass
        finally:
            for child in running:
                if not child.done():child.cancel()
            if running:await asyncio.gather(*running,return_exceptions=True)
            writer.close();await writer.wait_closed();self.clients.discard(task)

async def unix_exchange(path,envelope):
    reader,writer=await asyncio.open_unix_connection(path,limit=MAX_FRAME+1)
    try:
        writer.write(canonical(envelope)+b'\n');await writer.drain();pages=[]
        from atlas_native_bridge.protocol import decode
        while True:
            line=await reader.readline()
            if not line:break
            pages.append(decode(line))
        return pages
    finally:writer.close();await writer.wait_closed()
