"""Typed SDK attachment capabilities; no wire paths, URLs or raw Bot API calls."""
import asyncio
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit
import httpx
from atlas_bridge.contract import digest
from .protocol import CHUNK, Denied, directory
from .media import StreamReceiver,identifier,MAX_EXPORT,abort_stream,LEASE_SECONDS


def check_manifest(row):
    if type(row) is not dict or set(row)!={'export_id','size','sha256','filename'}:raise Denied('closed_attachment_manifest')
    identifier(row['export_id'])
    if (type(row['size']) is not int or not 0<=row['size']<=MAX_EXPORT or type(row['sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None or type(row['filename']) is not str
            or not row['filename'] or len(row['filename'].encode())>255 or '/' in row['filename'] or '\\' in row['filename'] or '\x00' in row['filename']):raise Denied('bounded_attachment_manifest_required')
    return row


class EdgeMedia:
    def __init__(self,root,*,client=None):
        self.root=Path(root);self.receiver=StreamReceiver(self.root/'outbound')
        self.sources=StreamReceiver(self.root/'inbound');self.client=client;self._owns_client=False;self.readers={};self._downloads=set();self.reader_deadlines={};self._reader_timer=None
    def close(self):
        if self._reader_timer is not None:self._reader_timer.cancel();self._reader_timer=None
        self.readers.clear();self.reader_deadlines.clear();self.receiver.close();self.sources.close()
    def _drop_reader(self,key):
        self.readers.pop(key,None);self.reader_deadlines.pop(key,None)
    def reap_readers(self,*,now=None):
        now=time.time() if now is None else now
        for key,deadline in list(self.reader_deadlines.items()):
            if deadline<=now:self._drop_reader(key)
        if self._reader_timer is not None:self._reader_timer.cancel();self._reader_timer=None
        if self.reader_deadlines:
            self._reader_timer=asyncio.get_running_loop().call_later(max(0,min(self.reader_deadlines.values())-time.time()),self.reap_readers)
    def open_completed(self,*args,**kwargs):return self.receiver.open_completed(*args,**kwargs)
    def discard_outbound(self,eid,scope):self.receiver.discard(eid,scope)
    def drop_origin(self,origin):
        for eid,raw in self.sources.db.execute('SELECT id,scope FROM exports').fetchall():
            scope=json.loads(raw)
            if scope.get('origin')==origin:self.sources.discard(eid,scope)
    async def snapshot_sdk(self,message,b,scope,bot,gate):
        item=message.effective_attachment
        if isinstance(item,(list,tuple)):item=item[-1] if item else None
        if item is None or not hasattr(item,'file_id'):raise Denied('actual_sdk_file_metadata_required')
        await gate.recheck(b,bot);file=await bot.get_file(item.file_id);await gate.recheck(b,bot)
        url=urlsplit(str(file.file_path))
        if (url.scheme!='https' or url.hostname!='api.telegram.org' or url.port not in (None,443)
                or url.username or url.password or url.query or url.fragment
                or not url.path.startswith('/file/bot9229862070:')):raise Denied('actual_fixed_Telegram_SDK_file_required')
        # The privileged URL comes ONLY from the actual SDK response and is never
        # exposed to QYP, logs, journals, tools or a model.
        filename=getattr(item,'file_name',None) or 'attachment.bin'
        if type(filename) is not str or '/' in filename or '\\' in filename or '\x00' in filename or len(filename.encode())>255:filename='attachment.bin'
        eid=digest({'scope':scope,'SDK_file_unique_id':file.file_unique_id})[:32]
        old=self.sources.db.execute('SELECT scope,size,sha FROM exports WHERE id=?',(eid,)).fetchone()
        if old:
            if json.loads(old[0])!=scope:raise Denied('attachment_scope_conflict')
            return [check_manifest({'export_id':eid,'size':old[1],'sha256':old[2],'filename':filename})]
        if eid in self._downloads:raise Denied('attachment_download_in_progress')
        ceiling=file.file_size if file.file_size is not None else MAX_EXPORT
        self.sources.budget.reserve(self.sources.root,eid,scope,ceiling)
        try:fd=os.open(eid+'.partial',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=self.sources.dfd)
        except BaseException:self.sources.budget.release(self.sources.root,eid);raise
        size=0;sha=hashlib.sha256();published=False;client=self.client
        self._downloads.add(eid)
        try:
            if client is None:client=httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30)
            async with client.stream('GET',str(file.file_path)) as response:
                if response.status_code!=200:raise Denied('SDK_attachment_download_failed')
                async for chunk in response.aiter_bytes(CHUNK):
                    if not gate.valid(b):raise Denied('binding_revoked_during_download')
                    size+=len(chunk)
                    if size>ceiling:raise Denied('logical_attachment_ceiling')
                    view=memoryview(chunk)
                    while view:
                        written=os.write(fd,view)
                        if written<=0:raise OSError('short attachment write')
                        view=view[written:]
                    sha.update(chunk)
            if self.client is None:await client.aclose()
            await gate.recheck(b,bot)
            if file.file_size is not None and size!=file.file_size:raise Denied('SDK_attachment_length_mismatch')
            self.sources.budget.reserve(self.sources.root,eid,scope,size)
            os.fsync(fd);os.fchmod(fd,0o400);os.rename(eid+'.partial',eid,src_dir_fd=self.sources.dfd,dst_dir_fd=self.sources.dfd);os.fsync(self.sources.dfd);published=True
            with self.sources.transaction():
                self.sources.db.execute('INSERT INTO exports VALUES (?,?,?,?)',(eid,json.dumps(scope,sort_keys=True),size,sha.hexdigest()))
                self.sources.db.execute('INSERT INTO owners VALUES (?,?,?)',(eid,secrets.token_hex(16),time.time()+LEASE_SECONDS))
            self.sources._schedule()
            return [check_manifest({'export_id':eid,'size':size,'sha256':sha.hexdigest(),'filename':filename})]
        except BaseException:
            for name in (eid+'.partial',eid):
                try:os.unlink(name,dir_fd=self.sources.dfd)
                except FileNotFoundError:pass
            self.sources.db.execute('DELETE FROM exports WHERE id=?',(eid,))
            self.sources.db.execute('DELETE FROM owners WHERE id=?',(eid,))
            self.sources.budget.release(self.sources.root,eid)
            raise
        finally:
            self._downloads.discard(eid);os.close(fd)
            if self.client is None and client is not None and not client.is_closed:
                try:await client.aclose()
                except BaseException:pass
    async def handle(self,kind,body):
        self.reap_readers()
        if body.get('pull') is not True:return await self.receiver.handle(kind,body)
        base={'scope','challenge','export_id','pull'}
        shape=base|({'offset'} if kind=='stream_chunk' else set())
        optional={'transfer_id'}|({'abort'} if kind=='stream_close' else set())
        if kind not in ('stream_open','stream_chunk','stream_close') or not shape<=set(body) or set(body)-shape-optional:raise Denied('closed_attachment_read_schema')
        if 'abort' in body and type(body['abort']) is not bool:raise Denied('boolean_stream_abort_required')
        eid=identifier(body['export_id']);scope=body['scope'];challenge=body['challenge']
        owner=identifier(body.get('transfer_id',eid))
        row=self.sources.db.execute('SELECT scope,size,sha FROM exports WHERE id=?',(eid,)).fetchone()
        if not row or json.loads(row[0])!=scope:raise Denied('original_UID_attachment_required')
        result={'challenge':challenge,'export_id':eid}
        key=(eid,digest(scope),owner)
        if body.get('abort'):
            if 'transfer_id' not in body:raise Denied('owned_stream_abort_required')
            self._drop_reader(key);return {**result,'status':'closed'}
        if kind=='stream_open':
            self.readers[key]=0;self.reader_deadlines[key]=time.time()+LEASE_SECONDS;self.reap_readers()
            return {**result,'size':row[1],'sha256':row[2]}
        if key not in self.readers:raise Denied('attachment_read_not_open')
        if kind=='stream_close':self._drop_reader(key);return {**result,'status':'closed'}
        offset=body['offset']
        if type(offset) is not int or offset!=self.readers[key]:raise Denied('ordered_attachment_read_required')
        fd=os.open(eid,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.sources.dfd)
        try:data=os.pread(fd,CHUNK,offset)
        finally:os.close(fd)
        self.readers[key]+=len(data)
        return {**result,'offset':offset,'data':base64.b64encode(data).decode()}


@dataclass(frozen=True)
class BoundSnapshot:
    scope:dict
    manifest:dict
    receiver:StreamReceiver
    transfer_id:str|None=None
    def discard(self):
        if self.transfer_id is not None:self.receiver.abort(self.manifest['export_id'],self.scope,self.transfer_id)
    @property
    def local_path(self):return str(self.receiver.objects/self.manifest['export_id'])
    def stage(self,broker,who,gate,binding):
        scope=self.scope
        if (not gate.valid(binding) or who.user_id!=scope['user_id'] or who.profile!=scope['profile'] or who.session_key!=scope['session_key']):raise Denied('original_native_attachment_principal_required')
        suffix=Path(self.manifest['filename']).suffix
        if re.fullmatch(r'\.[A-Za-z0-9]{1,10}',suffix) is None:suffix='.bin'
        name='attachment-'+self.manifest['export_id']+suffix
        with self.receiver.open_completed(self.manifest['export_id'],scope,transport_cap=MAX_EXPORT) as file:
            broker.stage_input_stream(who,name,file,size=self.manifest['size'],sha256=self.manifest['sha256'],cancel_check=lambda:not gate.valid(binding))
        if not gate.valid(binding):raise Denied('binding_revoked_during_input_staging')
        return '/inputs/'+name


async def fetch_attachments(manifests,scope,root,exchange,*,fresh=None):
    if type(manifests) is not list:raise Denied('closed_attachment_batch_required')
    receiver=StreamReceiver(root);snapshots=[];attempted=[];pending=None;owner=secrets.token_hex(16)
    async def call(kind,body):
        if fresh is not None:await fresh()
        challenge=secrets.token_hex(16)
        response=await exchange(kind,{'scope':scope,'challenge':challenge,'pull':True,'transfer_id':owner,**body})
        if response.get('challenge')!=challenge or response.get('export_id')!=body['export_id']:raise Denied('signed_attachment_reply_required')
        if fresh is not None:await fresh()
        return response
    try:
        for manifest in manifests:
            check_manifest(manifest);eid=manifest['export_id'];attempted.append(eid);pending=eid
            opened=await call('stream_open',{'export_id':eid})
            if opened.get('size')!=manifest['size'] or opened.get('sha256')!=manifest['sha256']:raise Denied('immutable_attachment_manifest_mismatch')
            common={'scope':scope,'export_id':eid,'transfer_id':owner}
            local=await receiver.handle('stream_open',{**common,'challenge':secrets.token_hex(16),'size':manifest['size'],'sha256':manifest['sha256']})
            if local['status']!='complete':
                offset=0
                while offset<manifest['size']:
                    chunk=await call('stream_chunk',{'export_id':eid,'offset':offset})
                    if chunk.get('offset')!=offset:raise Denied('attachment_offset_mismatch')
                    await receiver.handle('stream_chunk',{**common,'challenge':secrets.token_hex(16),'offset':offset,'data':chunk['data']})
                    offset+=len(base64.b64decode(chunk['data'],validate=True))
                await receiver.handle('stream_close',{**common,'challenge':secrets.token_hex(16)})
            # Track published OWN object before the next cancellation/ACK edge.
            snapshots.append(BoundSnapshot(dict(scope),dict(manifest),receiver,owner))
            closed=await call('stream_close',{'export_id':eid})
            if closed.get('status')!='closed':raise Denied('attachment_close_ACK_required')
            pending=None
        return snapshots
    except BaseException:
        for eid in attempted:
            try:receiver.abort(eid,scope,owner)
            except BaseException:pass
        try:receiver.close()
        except BaseException:pass
        if pending is not None:await abort_stream(exchange,scope,pending,owner,pull=True)
        raise
