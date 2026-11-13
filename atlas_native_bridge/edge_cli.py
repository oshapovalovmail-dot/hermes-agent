"""Production Mac CLI; only explicit operator configuration can start polling."""
import argparse
import asyncio
from pathlib import Path
import re
import shlex
import sys
from types import SimpleNamespace
from telegram.ext import ExtBot
from telegram.request import HTTPXRequest
from gateway.atlas_admission import AdmissionGate, GuardedRequest
from .protocol import Codec, Denied, MAX_FRAME, canonical, decode, load_key
from .hub import read_config
from .edge import MacEdge
from .attachments import EdgeMedia


def ssh_argv(cfg):
    host=cfg.get('ssh_host')
    if type(host) is not str or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',host) is None:raise Denied('existing_trusted_SSH_alias_required')
    python=cfg.get('remote_python');config=cfg.get('remote_config')
    for value in (python,config):
        if type(value) is not str or not value.startswith('/') or '\x00' in value or '..' in Path(value).parts:raise Denied('fixed_operator_remote_path_required')
    entry=cfg.get('remote_entry')
    if (type(entry)is not str or not entry.startswith('/') or '\x00' in entry
            or '..' in Path(entry).parts or Path(entry).parts[-2:]!=('atlas_native_bridge','hub_entry.py')):
        raise Denied('fixed_source_hub_entrypoint_required')
    remote=shlex.join([python,'-I','-B',entry,'--config',config])
    peer_options=[]
    if 'ssh_peer_address' in cfg:
        from ipaddress import IPv6Address
        peer=cfg['ssh_peer_address']
        if (cfg.get('role')!='mac' or host!='qyp-dev' or type(peer)is not dict
                or set(peer)!={'hostname','address'}
                or peer.get('hostname')!='ovshapovalov-dev.klg.yp-c.yandex.net'
                or type(peer.get('address'))is not str
                or re.fullmatch('[0-9a-f:]{2,39}',peer['address'])is None):
            raise Denied('fixed_operator_QYP_peer_address_required')
        try:address=IPv6Address(peer['address'])
        except ValueError:raise Denied('fixed_operator_QYP_peer_address_required') from None
        if not address.is_global or address.ipv4_mapped is not None or str(address)!=peer['address']:
            raise Denied('fixed_operator_QYP_peer_address_required')
        # Preserve original host identity; this changes only the fixed app route.
        # No global resolver, trust, forwarding or model-facing target is changed.
        peer_options=['-o','HostName='+str(address),'-o','HostKeyAlias='+peer['hostname'],
                      '-o','StrictHostKeyChecking=yes']
    return ['/usr/bin/ssh','-T','-o','ClearAllForwardings=yes','-o','ForwardAgent=no','-o','PermitLocalCommand=no','-o','BatchMode=yes',*peer_options,host,remote]


async def poll_updates(bot,offset):
    from telegram.error import Conflict,InvalidToken
    from telegram.ext._utils.networkloop import network_retry_loop
    updates=None
    async def action():
        nonlocal updates
        try:updates=await bot.get_updates(offset=offset,timeout=30,allowed_updates=['message'])
        except Conflict:raise Denied('telegram_polling_conflict') from None
        except InvalidToken:raise Denied('telegram_polling_token_rejected') from None
    await network_retry_loop(action_cb=action,description='Atlas Telegram input',interval=0,max_retries=-1)
    return updates


def check_reader(read_task):
    if read_task.done():
        read_task.result()  # Preserve the authenticated reader's original denial.
        raise Denied('QYP_application_channel_closed')


async def await_reader(read_task,operation):
    """Race one owned operation against the shared reader; never cancel the reader."""
    check_reader(read_task)
    owned=asyncio.ensure_future(operation())
    try:
        await asyncio.wait((read_task,owned),return_when=asyncio.FIRST_COMPLETED)
        check_reader(read_task)
        return await owned
    finally:
        if not owned.done():owned.cancel()
        # Only the owned competitor is collected here, never the reader's cause.
        await asyncio.gather(owned,return_exceptions=True)


async def run(cfg):
    if cfg.get('role')!='mac':raise Denied('mac_role_required')
    key=load_key(cfg['key_file']);codec=Codec(key,cfg['epoch'],'mac')
    from .staff_provider import build_staff_provider
    settings={'admin_home':cfg['staff_admin_home'],'reviewed_service_files':cfg['staff_reviewed_service_files']}
    staff=build_staff_provider(SimpleNamespace(get_config=lambda k,d=None:settings.get(k,d)))
    gate=AdmissionGate(staff)
    token=load_key(cfg['bot_token_file']).decode('ascii').strip()
    # Credentials live in the SDK only; no credential is sent through application
    # frames, native payloads, model context, diagnostics or subprocess argv.
    from gateway.config import PlatformConfig
    from plugins.platforms.telegram.adapter import TelegramAdapter
    general_request,get_updates_request=await TelegramAdapter(PlatformConfig(enabled=True))._build_ptb_requests()
    request=GuardedRequest(general_request,gate)
    bot=ExtBot(token,request=request,get_updates_request=get_updates_request);del token
    root=Path(cfg['root']);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    streams=EdgeMedia(root/'media')
    from .memory_config import local_honcho
    memory,http=local_honcho(cfg.get('honcho'),root)
    edge=MacEdge(codec,gate,root,bot=bot,streams=streams,memory=memory,thread_sessions_per_user=cfg.get('thread_sessions_per_user',False))
    read_backend=None
    if cfg.get('work_read') is not None:
        from atlas_work_read.cli import build_mac_connector
        edge.read_connector=build_mac_connector(edge,cfg['work_read'])
        read_backend=edge.read_connector.backend
    proc=None;tasks=set();pending={};lock=asyncio.Lock();ready=asyncio.Event()
    async def write(frame):
        async with lock:
            if proc is None or proc.stdin is None:raise Denied('application_channel_closed')
            proc.stdin.write(canonical(frame)+b'\n');await proc.stdin.drain()
    async def handle(wire):
        try:response=await edge.handle(wire)
        except PermissionError:
            request=codec.verify(wire);body=request['body']
            if request['kind']=='egress':
                scope=body.get('scope') or {}
                response=codec.sign('egress_result',{'obligation':body.get('obligation'),'success':False,
                    'chat_id':scope.get('chat_id'),'thread_id':scope.get('thread_id'),'error':'telegram egress declined: Atlas admission denied','code':'egress_declined'})
            elif request['kind']=='work_read_cancel':response=[]
            elif request['kind']=='work_read':
                from atlas_work_read.rpc import respond
                value={'ok':False,'code':'native_work_read_denied','message':'','source':'','text':'','truncated':False,'returned_chars':0,'untrusted':True}
                response=respond(codec,body,value)
            else:response=codec.sign('denied',{'challenge':body.get('challenge'),'code':'atlas_authorization_denied'})
        for page in response if isinstance(response,list) else [response]:await write(page)
    async def reader():
        while True:
            raw=await proc.stdout.readline()
            if not raw:return
            if len(raw)>MAX_FRAME:raise Denied('bounded_application_frame_required')
            wire=decode(raw);frame=codec.verify(wire)
            if frame['kind']=='ready':
                if frame['body'].get('bot_id')!='9229862070':raise Denied('fixed_bot_required')
                ready.set()
            elif frame['kind']=='input_receipt':
                origin=frame['body'].get('origin');receipt=frame['body'].get('receipt') or {}
                if receipt.get('status') not in ('pending',None):streams.drop_origin(origin)
                fut=pending.get(origin)
                if fut is not None and not fut.done():fut.set_result(frame['body'])
            else:
                task=asyncio.create_task(handle(wire));tasks.add(task);task.add_done_callback(tasks.discard)
    try:
        await bot.initialize()
        if bot.id!=9229862070 or bot.bot.is_bot is not True:raise Denied('actual_Atlas_bot_identity_required')
        # One forward application channel. Never -R/-D/-L or shell commands from
        # messages. Existing SSH trust/keychain selection is not modified.
        proc=await asyncio.create_subprocess_exec(*ssh_argv(cfg),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=MAX_FRAME+1,
            env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'LANG':'en_US.UTF-8'})
        read_task=asyncio.create_task(reader());tasks.add(read_task)
        await await_reader(read_task,lambda:asyncio.wait_for(ready.wait(),30))
        offset=None
        while True:
            updates=await await_reader(read_task,lambda:poll_updates(bot,offset))
            for update in updates:
                check_reader(read_task)
                try:wire=await edge.ingress(update)
                except PermissionError:
                    check_reader(read_task)
                    offset=update.update_id+1;continue
                body=wire['body']
                origin='9229862070:'+body['input']['update_id'];fut=asyncio.get_running_loop().create_future();pending[origin]=fut
                try:
                    await await_reader(read_task,lambda:write(wire))
                    receipt=await await_reader(read_task,lambda:asyncio.wait_for(fut,30))
                    if receipt['receipt']['status'] not in ('pending','queued','started','terminal','unknown','refused','command'):raise Denied('durable_input_receipt_required')
                    offset=update.update_id+1
                finally:pending.pop(origin,None)
    finally:
        primary=sys.exception();errors=[]
        async def cleanup(name,action,asynchronous=False):
            # Isolate every resource, including cancellation/SystemExit. Keep
            # the operation's error (or first cleanup error) as the primary.
            try:
                result=action()
                if asynchronous:await result
            except BaseException as error:errors.append((name,error))
        for task in tasks:await cleanup('task_cancel',task.cancel)
        if tasks:await cleanup('tasks',lambda:asyncio.gather(*tasks,return_exceptions=True),True)
        if proc is not None:
            if proc.stdin is not None:await cleanup('stdin',proc.stdin.close)
            async def stop_process():
                try:await asyncio.wait_for(proc.wait(),5)
                except TimeoutError:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(),5)
            await cleanup('process',stop_process,True)
        if read_backend is not None:
            trace=getattr(edge.read_connector,'trace',None)
            if getattr(trace,'close',None) is not None:await cleanup('trace',trace.close,True)
            await cleanup('backend',read_backend.close,True)
        await cleanup('bot',bot.shutdown,True)
        for name,resource in (('edge',edge),('streams',streams),('memory',memory),('http',http)):
            await cleanup(name,resource.close)
        if errors:
            if primary is None:primary=errors[0][1]
            for name,error in errors:
                if error is not primary:primary.add_note('Mac edge cleanup failed: '+name+' ('+type(error).__name__+')')
            raise primary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True,type=Path);a=p.parse_args()
    try:asyncio.run(run(read_config(a.config)))
    except PermissionError as error:raise SystemExit(str(error)) from None

if __name__=='__main__':main()
