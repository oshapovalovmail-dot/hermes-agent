"""QYP application connector. Fixed signed stdio <-> native loopback WebSocket.

Not an HTTP/SOCKS/TCP/Bot-API proxy. One native gateway connection, no model.
"""
import argparse
import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
import websockets
from atlas_bridge.contract import native_event, validate, origin_id, canonical, input_fingerprint, digest
from .protocol import Codec, Denied, MAX_FRAME, decode, load_key
from .stores import PendingInbox

DESCRIPTOR={'contract_version':1,'platform':'telegram','label':'Atlas Mac Telegram',
            'max_message_length':4096,'supports_draft_streaming':False,'supports_edit':True,
            'supports_threads':True,'markdown_dialect':'plain','len_unit':'utf16',
            'supported_ops':['send','edit','delete','react','typing','send_media']}


def upgrade_secret(key):return hmac.new(key,b'atlas-native-ws-upgrade-v1\0',hashlib.sha256).hexdigest()


def authenticated(headers,gateway_id,secret):
    try:
        values=headers.get_all('Authorization')
        if len(values)!=1 or not values[0].startswith('Bearer '):return False
        token=values[0][7:];raw=base64.urlsafe_b64decode(token+'='*(-len(token)%4)).decode()
        subject,exp,sig=raw.rsplit(':',2);stamp=int(exp);now=int(time.time())
        expected=hmac.new(secret.encode(),(subject+':'+exp).encode(),hashlib.sha256).hexdigest()
        return subject==gateway_id and now<stamp<=now+300 and hmac.compare_digest(expected,sig)
    except (ValueError,UnicodeError,KeyError):return False


class ConnectorHub:
    def __init__(self,root,codec,*,gateway_id,write):
        self.codec=codec;self.gateway_id=gateway_id;self.write=write
        self.secret=upgrade_secret(codec._key);self.inbox=PendingInbox(Path(root)/'pending.sqlite')
        self.inbox.db.execute('CREATE TABLE IF NOT EXISTS attestations(origin TEXT PRIMARY KEY,envelope TEXT NOT NULL)')
        self.native=None;self.hello=False;self._egress={};self._sent=set();self._lock=asyncio.Lock()
        from atlas_work_read.rpc import HubReadChannel
        self.read_channel=HubReadChannel(self)
    def close(self):self.inbox.close()
    async def send(self,frame):
        if self.native is None or not self.hello:raise Denied('native_transport_unavailable')
        await self.native.send(canonical(frame).decode()+'\n')
    async def forward(self,body,envelope):
        origin=origin_id(body['input'])
        await self.send({'type':'inbound','bufferId':origin,'event':native_event(body['input']),'atlas_envelope':envelope})
    async def application(self,envelope):
        frame=self.codec.verify(envelope);kind=frame['kind'];body=frame['body']
        if kind=='work_read_result':
            channel=getattr(self,'read_channel',None)
            if channel is None:raise Denied('work_read_channel_not_configured')
            channel.accept(envelope);return
        if kind=='input':
            if set(body)!={'input','session_key','attachments'}:raise Denied('closed_signed_input_schema')
            validate(body['input'])
            if body['input']['epoch']!=self.codec.epoch:raise Denied('original_transport_epoch_required')
            if type(body['session_key']) is not str or type(body['attachments']) is not list:raise Denied('canonical_input_required')
            # No unreviewed URLs, paths, arbitrary nested carriers or SDK tokens.
            from .attachments import check_manifest
            for attachment in body['attachments']:check_manifest(attachment)
            origin=origin_id(body['input'])
            self.inbox.nonce(frame['nonce'],frame)
            disposition=self.inbox.put(origin,body,fingerprint=digest({'input_sha256':input_fingerprint(body['input']),'session_key':body['session_key'],'attachments':body['attachments']}))
            if disposition=='acked':
                await self.write(self.codec.sign('input_receipt',{'origin':origin,'receipt':self.inbox.receipt(origin)}));return
            self.inbox.db.execute('INSERT OR REPLACE INTO attestations VALUES (?,?)',(origin,canonical(envelope).decode()))
            # Durable payload is committed BEFORE native socket I/O. Offline is
            # pending, not a fingerprint-only loss window.
            await self.write(self.codec.sign('input_receipt',{'origin':origin,'receipt':{'status':'pending','admission_id':origin}}))
            if self.native is not None and self.hello:await self.forward(body,envelope)
            return
        if kind in ('recheck_result','memory_result','stream_result','denied'):
            await self.send({'type':'atlas_control_result','envelope':envelope});return
        if kind=='egress_result':
            obligation=body.get('obligation');record=self._egress.pop(obligation,None)
            if record is None:raise Denied('unknown_output_obligation')
            request,scope=record
            if body.get('chat_id')!=scope['chat_id'] or body.get('thread_id')!=scope['thread_id']:raise Denied('exact_recipient_ACK_required')
            await self.send({'type':'outbound_result','requestId':request,'result':body});return
        raise Denied('unreviewed_application_kind')
    async def relay(self,ws):
        if ws.request.path!='/relay' or not authenticated(ws.request.headers,self.gateway_id,self.secret):
            await ws.close(code=4401,reason='unauthorized');return
        async with self._lock:
            if self.native is not None:
                await ws.close(code=4409,reason='single_gateway_only');return
            self.native=ws;self.hello=False
        try:
            async for raw in ws:
                if not isinstance(raw,str) or len(raw.encode())>MAX_FRAME:raise Denied('bounded_native_frame_required')
                for line in raw.splitlines():
                    frame=decode(line);kind=frame.get('type')
                    if frame=={'type':'hello','platform':'telegram','botId':'9229862070'}:
                        self.hello=True
                        await self.send({'type':'descriptor','descriptor':DESCRIPTOR})
                        for body in self.inbox.pending():
                            origin=origin_id(body['input']);row=self.inbox.db.execute('SELECT envelope FROM attestations WHERE origin=?',(origin,)).fetchone()
                            if row:await self.forward(body,json.loads(row[0]))
                    elif kind=='atlas_inbound_ack' and set(frame)=={'type','bufferId','receipt'}:
                        self.inbox.ack(frame['bufferId'],frame['receipt'])
                        self.inbox.db.execute('DELETE FROM attestations WHERE origin=?',(frame['bufferId'],))
                        await self.write(self.codec.sign('input_receipt',{'origin':frame['bufferId'],'receipt':frame['receipt']}))
                    elif kind=='atlas_need_refresh' and set(frame)=={'type','bufferId'}:
                        row=self.inbox.db.execute('SELECT payload FROM inbox WHERE origin=? AND receipt IS NULL',(frame['bufferId'],)).fetchone()
                        if row:await self.write(self.codec.sign('refresh_input',json.loads(row[0])))
                    elif kind=='inbound_ack':
                        # Stock native socket ACK is NOT durable canonical-ledger
                        # reconciliation; it cannot erase the pending inbox.
                        continue
                    elif kind=='atlas_control' and set(frame)=={'type','envelope'}:
                        # This is a QYP->Mac frame; validate with the peer role.
                        check=Codec(self.codec._key,self.codec.epoch,'mac').verify(frame['envelope'])
                        if check['kind'] not in ('recheck','memory','stream_open','stream_chunk','stream_close'):raise Denied('unreviewed_control_kind')
                        await self.write(frame['envelope'])
                    elif kind=='outbound' and type(frame.get('requestId')) is str:
                        action=frame.get('action')
                        if type(action) is not dict or set(action)!={'op','envelope'} or action['op']!='atlas_egress':raise Denied('native_issued_output_required')
                        check=Codec(self.codec._key,self.codec.epoch,'mac').verify(action['envelope'])
                        if check['kind']!='egress' or set(check['body'])!={'scope','obligation','action'}:raise Denied('closed_egress_required')
                        body=check['body'];self._egress[body['obligation']]=(frame['requestId'],body['scope'])
                        await self.write(action['envelope'])
                    elif frame=={'type':'going_idle'}:await self.send({'type':'going_idle_ack'})
                    else:raise Denied('unreviewed_native_frame')
        except (Denied,ValueError,UnicodeError):await ws.close(code=4400,reason='invalid_fixed_application_frame')
        finally:
            if self.native is ws:self.native=None;self.hello=False;self._egress.clear()


def read_config(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise Denied('explicit_operator_config_required')
    cfg=decode(path.read_bytes())
    if cfg.get('enabled') is not True:raise Denied('bridge_disabled')
    if set(cfg)-{'enabled','key_file','epoch','root','gateway_id','port','role','ssh_host','remote_python','remote_config','remote_entry','bot_token_file','staff_admin_home','staff_reviewed_service_files','thread_sessions_per_user','honcho','work_read','ssh_peer_address'}:raise Denied('closed_operator_configuration')
    if type(cfg.get('port')) is not int or not 0<=cfg['port']<=65535:raise Denied('loopback_port_required')
    if cfg.get('role') not in ('mac','qyp'):raise Denied('fixed_role_required')
    return cfg


async def run(cfg):
    key=load_key(cfg['key_file']);codec=Codec(key,cfg['epoch'],'qyp')
    root=Path(cfg['root']);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=asyncio.Lock()
    async def write(frame):
        async with lock:
            sys.stdout.write(canonical(frame).decode()+'\n');sys.stdout.flush()
    hub=ConnectorHub(root,codec,gateway_id=cfg['gateway_id'],write=write)
    reads=None;socket_path=root/'work-read.sock';socket_inode=None
    try:
        if cfg.get('work_read') is not None:
            if cfg['work_read']!={'enabled':True}:raise Denied('explicit_closed_read_channel_required')
            from .protocol import directory
            import os
            fd=directory(root)
            try:
                info=os.fstat(fd)
                if info.st_uid!=os.getuid() or info.st_mode&0o777!=0o700:raise Denied('private_read_channel_root_required')
            finally:os.close(fd)
            if socket_path.exists() or socket_path.is_symlink():raise Denied('read_channel_already_exists')
            reads=await asyncio.start_unix_server(hub.read_channel.serve_client,path=str(socket_path),limit=MAX_FRAME+1)
            socket_path.chmod(0o600);socket_inode=socket_path.stat().st_ino
        async with websockets.serve(hub.relay,'127.0.0.1',cfg['port'],max_size=MAX_FRAME) as server:
            await write(codec.sign('ready',{'port':server.sockets[0].getsockname()[1],'bot_id':'9229862070'}))
            while True:
                raw=await asyncio.to_thread(sys.stdin.buffer.readline,MAX_FRAME+1)
                if not raw:return
                try:await hub.application(decode(raw))
                except PermissionError:
                    await write(codec.sign('denied',{'code':'application_denied'}))
    finally:
        if reads is not None:
            reads.close();await reads.wait_closed()
            await hub.read_channel.close()
            if not socket_path.is_symlink() and socket_path.exists() and socket_path.stat().st_ino==socket_inode:socket_path.unlink()
        hub.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True,type=Path);a=parser.parse_args()
    cfg=read_config(a.config)
    if cfg['role']!='qyp':raise SystemExit('qyp_role_required')
    asyncio.run(run(cfg))

if __name__=='__main__':main()
