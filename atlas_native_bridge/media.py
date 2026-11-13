"""Immutable exact-owner streams, bounded physical staging and abort recovery."""
import asyncio
import base64
from contextlib import contextmanager
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from atlas_bridge.contract import PrivateStore, digest
from .protocol import Denied, CHUNK, directory
from .staging import StagingBudget

MAX_EXPORT=2*1024**3
LEASE_SECONDS=24*60*60


def identifier(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{32}',value) is None:raise Denied('opaque_export_ID_required')
    return value


def fingerprint(st):return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,st.st_mode,st.st_nlink)


class ImmutableExport:
    """Created only after native broker.resolve_export for an issued principal."""
    def __init__(self,path,scope):
        path=Path(path);dfd=directory(path.parent)
        try:self.fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dfd)
        finally:os.close(dfd)
        try:
            st=os.fstat(self.fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_mode&0o222 or st.st_size>MAX_EXPORT):raise Denied('immutable_single_link_export_required')
            self.before=fingerprint(st);self.scope=dict(scope);self.export_id=secrets.token_hex(16)
            self.transfer_id=secrets.token_hex(16)
            h=hashlib.sha256()
            while data:=os.read(self.fd,CHUNK):h.update(data)
            if fingerprint(os.fstat(self.fd))!=self.before:raise Denied('export_changed')
            os.lseek(self.fd,0,os.SEEK_SET)
            self.manifest={'scope':self.scope,'export_id':self.export_id,'size':st.st_size,'sha256':h.hexdigest()}
        except BaseException:self.close();raise
    def read(self):
        if fingerprint(os.fstat(self.fd))!=self.before:raise Denied('export_changed')
        return os.read(self.fd,CHUNK)
    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None


async def open_export(path,scope):
    # Cancellation cannot abandon a descriptor constructed in the worker thread.
    task=asyncio.create_task(asyncio.to_thread(ImmutableExport,path,scope))
    try:return await asyncio.shield(task)
    except BaseException:
        def dispose(done):
            try:done.result().close()
            except BaseException:pass
        task.add_done_callback(dispose)
        raise


class StreamReceiver(PrivateStore):
    def __init__(self,root):
        if not os.environ.get('HERMES_HOME'):raise Denied('fixed_staging_home_required')
        self.root=Path(root).absolute();self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        dfd=directory(self.root)
        try:self.lock=os.open('stream.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=dfd)
        finally:os.close(dfd)
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:os.close(self.lock);raise Denied('stream_store_in_use') from None
        self.active={};self._closed=False;self._timer=None
        try:
            super().__init__(self.root/'stream.sqlite')
            self.objects=self.root/'objects';self.objects.mkdir(mode=0o700,exist_ok=True)
            self.dfd=directory(self.objects)
            self.db.execute('CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,scope TEXT NOT NULL,size INTEGER NOT NULL,sha TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS owners(id TEXT PRIMARY KEY,owner TEXT NOT NULL,expires REAL NOT NULL)')
            # HERMES_HOME is the fixed host process home, not a per-turn ContextVar.
            budget_root=Path(os.environ['HERMES_HOME'])/'bridge-staging'
            self.budget=StagingBudget(budget_root)
            complete={r[0] for r in self.db.execute('SELECT id FROM exports')}
            for p in self.objects.iterdir():
                if re.fullmatch(r'[0-9a-f]{32}(\.partial)?',p.name) and p.name not in complete:
                    p.unlink();self.budget.release(self.root,p.name.removesuffix('.partial'))
            for (eid,) in self.budget.db.execute('SELECT id FROM reservations WHERE store=?',(str(self.root),)).fetchall():
                if eid not in complete:self.budget.release(self.root,eid)
            for eid,raw,size,sha in self.db.execute('SELECT * FROM exports').fetchall():
                self.budget.reserve(self.root,eid,json.loads(raw),size)
            self.reap()
        except BaseException:
            for name in ('dfd','lock'):
                fd=getattr(self,name,None)
                if fd is not None:os.close(fd)
            if hasattr(self,'db'):self.db.close()
            if hasattr(self,'budget'):self.budget.close()
            raise
    def _schedule(self):
        if self._timer is not None:self._timer.cancel();self._timer=None
        deadlines=[r['expires'] for r in self.active.values()]+[r[0] for r in self.db.execute('SELECT expires FROM owners')]
        if deadlines:
            try:self._timer=asyncio.get_running_loop().call_later(max(0,min(deadlines)-time.time()),self.reap)
            except RuntimeError:pass # synchronous callers reap on next operation
    def reap(self,*,now=None):
        if self._closed:return
        now=time.time() if now is None else now
        for eid,r in list(self.active.items()):
            if r['expires']<=now:self._drop_active(eid)
        for (eid,) in self.db.execute('SELECT id FROM owners WHERE expires<=?',(now,)).fetchall():
            row=self.db.execute('SELECT scope FROM exports WHERE id=?',(eid,)).fetchone()
            if row:self.discard(eid,json.loads(row[0]))
        self._schedule()
    def _unlink(self,name):
        try:os.unlink(name,dir_fd=self.dfd)
        except FileNotFoundError:pass
    def _drop_active(self,eid):
        record=self.active.pop(eid,None)
        if record is not None:
            try:self._unlink(eid+'.partial');os.fsync(self.dfd)
            finally:os.close(record['fd'])
            self.budget.release(self.root,eid)
    def close(self):
        if self._closed:return
        if self._timer is not None:self._timer.cancel();self._timer=None
        try:
            for eid in list(self.active):self._drop_active(eid)
        finally:
            self._closed=True;os.close(self.dfd);self.db.close();self.budget.close();os.close(self.lock)
    def abort(self,eid,scope,owner):
        """Only this transfer's exact object; never delete a reused completion."""
        identifier(eid);identifier(owner)
        if self._closed:return
        record=self.active.get(eid)
        if record is not None:
            if record['scope']!=scope or record['owner']!=owner:raise Denied('exact_stream_owner_required')
            self._drop_active(eid);return
        row=self.db.execute('SELECT scope FROM exports WHERE id=?',(eid,)).fetchone()
        if row is None:return
        if json.loads(row[0])!=scope:raise Denied('exact_export_cleanup_scope_required')
        found=self.db.execute('SELECT owner FROM owners WHERE id=?',(eid,)).fetchone()
        if found and found[0]==owner:self.discard(eid,scope)
        # A reused complete belongs to its original owner and is deliberately kept.
    async def handle(self,kind,body):
        self.reap()
        common={'scope','challenge','export_id'}
        shapes={'stream_open':common|{'size','sha256'},'stream_chunk':common|{'offset','data'},'stream_close':common}
        if kind not in shapes or type(body) is not dict:raise Denied('closed_stream_schema')
        optional={'transfer_id'}|({'abort'} if kind=='stream_close' else set())
        if not shapes[kind]<=set(body) or set(body)-shapes[kind]-optional:raise Denied('closed_stream_schema')
        if 'abort' in body and type(body['abort']) is not bool:raise Denied('boolean_stream_abort_required')
        eid=identifier(body['export_id']);scope=body['scope'];challenge=body['challenge']
        if type(scope) is not dict or type(challenge) is not str or re.fullmatch('[0-9a-f]{32}',challenge) is None:raise Denied('bound_stream_required')
        owner=identifier(body.get('transfer_id',eid))
        if body.get('abort'):
            if 'transfer_id' not in body:raise Denied('owned_stream_abort_required')
            self.abort(eid,scope,owner)
            return {'challenge':challenge,'export_id':eid,'status':'aborted'}
        if kind=='stream_open':
            if type(body['size']) is not int or not 0<=body['size']<=MAX_EXPORT or type(body['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',body['sha256']) is None:raise Denied('bounded_export_manifest_required')
            old=self.active.get(eid)
            if old:
                if old['scope']!=scope or old['owner']!=owner or old['size']!=body['size'] or old['sha']!=body['sha256']:raise Denied('stream_already_open')
                if 'transfer_id' not in body:raise Denied('stream_already_open')
                self._drop_active(eid) # explicit same-operation restart from zero
            row=self.db.execute('SELECT scope,size,sha FROM exports WHERE id=?',(eid,)).fetchone()
            if row:
                if json.loads(row[0])!=scope or row[1:]!=(body['size'],body['sha256']):raise Denied('immutable_export_identity_conflict')
                return {'challenge':challenge,'export_id':eid,'status':'complete'}
            self.budget.reserve(self.root,eid,scope,body['size'])
            try:fd=os.open(eid+'.partial',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=self.dfd)
            except BaseException:self.budget.release(self.root,eid);raise
            self.active[eid]={'fd':fd,'owner':owner,'scope':json.loads(json.dumps(scope)),'size':body['size'],'sha':body['sha256'],'hash':hashlib.sha256(),'offset':0,'expires':time.time()+LEASE_SECONDS}
            self._schedule()
        else:
            record=self.active.get(eid)
            if not record or record['scope']!=scope or record['owner']!=owner:raise Denied('exact_stream_scope_required')
            if kind=='stream_chunk':
                if type(body['offset']) is not int or body['offset']!=record['offset'] or type(body['data']) is not str or len(body['data'])>4*((CHUNK+2)//3):raise Denied('ordered_bounded_chunk_required')
                try:data=base64.b64decode(body['data'],validate=True)
                except ValueError:raise Denied('invalid_chunk') from None
                if not data or len(data)>CHUNK or record['offset']+len(data)>record['size']:raise Denied('exact_stream_length_required')
                try:
                    view=memoryview(data)
                    while view:
                        count=os.write(record['fd'],view)
                        if count<=0:raise OSError('short stream write')
                        view=view[count:]
                    record['offset']+=len(data);record['hash'].update(data)
                except BaseException:self._drop_active(eid);raise
            else:
                try:
                    if record['offset']!=record['size'] or record['hash'].hexdigest()!=record['sha']:raise Denied('stream_length_hash_mismatch')
                    os.fsync(record['fd']);os.fchmod(record['fd'],0o400)
                    os.rename(eid+'.partial',eid,src_dir_fd=self.dfd,dst_dir_fd=self.dfd);os.fsync(self.dfd)
                    with self.transaction():
                        self.db.execute('INSERT INTO exports VALUES (?,?,?,?)',(eid,json.dumps(scope,sort_keys=True),record['size'],record['sha']))
                        self.db.execute('INSERT INTO owners VALUES (?,?,?)',(eid,owner,time.time()+LEASE_SECONDS))
                except BaseException:
                    self._unlink(eid);self._drop_active(eid);raise
                else:self.active.pop(eid);os.close(record['fd']);self._schedule()
        return {'challenge':challenge,'export_id':eid,'status':'complete' if kind=='stream_close' else 'ok'}
    def discard(self,eid,scope):
        identifier(eid)
        if self._closed:return
        row=self.db.execute('SELECT scope FROM exports WHERE id=?',(eid,)).fetchone()
        if row is None:return
        if json.loads(row[0])!=scope:raise Denied('exact_export_cleanup_scope_required')
        self._unlink(eid);os.fsync(self.dfd)
        with self.transaction():
            self.db.execute('DELETE FROM exports WHERE id=?',(eid,))
            self.db.execute('DELETE FROM owners WHERE id=?',(eid,))
        self.budget.release(self.root,eid)

    @contextmanager
    def open_completed(self,eid,scope,*,transport_cap):
        self.reap()
        identifier(eid);row=self.db.execute('SELECT scope,size,sha FROM exports WHERE id=?',(eid,)).fetchone()
        if not row or json.loads(row[0])!=scope:raise Denied('exact_export_principal_session_required')
        if row[1]>transport_cap:raise Denied('external_Telegram_upload_cap')
        fd=os.open(eid,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.dfd)
        with os.fdopen(fd,'rb') as file:
            before=fingerprint(os.fstat(fd))
            if not stat.S_ISREG(before[5]) or before[5]&0o222 or before[6]!=1 or before[2]!=row[1]:raise Denied('immutable_export_required')
            if hashlib.file_digest(file,'sha256').hexdigest()!=row[2] or fingerprint(os.fstat(fd))!=before:raise Denied('immutable_export_hash_mismatch')
            file.seek(0);yield file
            if fingerprint(os.fstat(fd))!=before:raise Denied('immutable_export_changed_during_upload')


async def abort_stream(exchange,scope,eid,owner,*,pull=False):
    """Bounded best effort; never mask the original error or claim offline ACK."""
    body={'scope':scope,'export_id':eid,'transfer_id':owner,'abort':True,'challenge':secrets.token_hex(16)}
    if pull:body['pull']=True
    try:await asyncio.wait_for(exchange('stream_close',body),timeout=0.5)
    except BaseException:pass


async def push_export(export,exchange,*,fresh=None):
    async def call(kind,body):
        if fresh is not None:await fresh()
        challenge=secrets.token_hex(16);body={**body,'transfer_id':export.transfer_id,'challenge':challenge}
        response=await exchange(kind,body)
        if response.get('challenge')!=challenge or response.get('export_id')!=export.export_id or response.get('status') not in ('ok','complete'):raise Denied('signed_export_reply_required')
        if fresh is not None:await fresh()
        return response
    try:
        result=await call('stream_open',export.manifest)
        if result['status']=='complete':return export.manifest
        offset=0
        # Regular-file bounded read avoids a cancelled to_thread retaining/reusing fd.
        while data:=export.read():
            await call('stream_chunk',{'scope':export.scope,'export_id':export.export_id,'offset':offset,'data':base64.b64encode(data).decode()})
            offset+=len(data)
        await call('stream_close',{'scope':export.scope,'export_id':export.export_id})
        return export.manifest
    except BaseException:
        await abort_stream(exchange,export.scope,export.export_id,export.transfer_id)
        export.close()
        raise
