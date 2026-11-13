"""Mac-only private native MCP workers. No shared cursor connection fallback."""
import asyncio
import os
from pathlib import Path
import stat
from atlas_bridge.contract import Denied,canonical

IDENTITY=('user_id','profile','chat_id','thread_id','session_key')

class OwnedMCPConnection:
    """Enter/exit the SDK's AnyIO scopes in one dedicated task.

    Requests can originate in different native tool tasks. Cancellation cancels
    the in-flight SDK request, not the connection owner's lifetime.
    """
    def __init__(self,parameters):
        self.parameters=parameters;self.queue=asyncio.Queue();self.task=None;self.ready=None
    async def start(self):
        if self.task is None:
            self.ready=asyncio.get_running_loop().create_future()
            self.task=asyncio.create_task(self._owner())
        await self.ready
        return self
    async def _owner(self):
        from mcp import Client
        try:
            async with Client(self.parameters,read_timeout_seconds=60) as client:
                self.ready.set_result(True)
                while True:
                    item=await self.queue.get()
                    if item is None:break
                    operation,args,kwargs,future=item
                    if future.cancelled():continue
                    async def invoke():
                        if operation=='list':return await client.list_tools()
                        return await client.call_tool(*args,**kwargs)
                    active=asyncio.create_task(invoke())
                    def cancelled(done):
                        if done.cancelled():active.cancel()
                    future.add_done_callback(cancelled)
                    try:
                        result=await active
                        if not future.done():future.set_result(result)
                    except BaseException as error:
                        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
                        if not future.done():future.set_exception(error)
                    finally:future.remove_done_callback(cancelled)
        except BaseException as error:
            if not self.ready.done():self.ready.set_exception(error)
            raise
    async def _call(self,operation,*args,**kwargs):
        await self.start()
        if self.task.done():return self.task.result()
        future=asyncio.get_running_loop().create_future()
        await self.queue.put((operation,args,kwargs,future))
        return await future
    async def list_tools(self):return await self._call('list')
    async def call_tool(self,name,args,**kwargs):return await self._call('call',name,args,**kwargs)
    async def close(self):
        if self.task is not None:
            await self.queue.put(None);await self.task


def identity(scope):return tuple(scope[k] for k in IDENTITY)

class PrivateBackendPool:
    """One reviewed stdio process/cwd per original UID/profile/topic/session.

    worker_parameters is provisioner-owned code, never model args. It must
    supply a distinct exact cwd; the pool refuses any reused connection route.
    """
    def __init__(self,bundle,worker_parameters):
        self.bundle=bundle;self.bundle_id=bundle.bundle_id;self.parameters=worker_parameters
        self._workers={};self._routes={};self._locks={}
    async def _worker(self,scope):
        key=identity(scope)
        lock=self._locks.setdefault(key,asyncio.Lock())
        async with lock:
            if key in self._workers:return self._workers[key]
            params=self.parameters(scope)
            home=Path(params.cwd)
            if not home.is_absolute() or home.is_symlink() or not home.is_dir():raise Denied('private_worker_cwd_required')
            st=home.stat()
            if st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o700:raise Denied('private_worker_cwd_required')
            route=(params.command,tuple(params.args),str(home.resolve()))
            if route in self._routes and self._routes[route]!=key:raise Denied('private_connection_identity_required')
            self._routes[route]=key
            client=await OwnedMCPConnection(params).start()
            try:
                actual=await client.list_tools();expected=await self.bundle.tools()
                if canonical([t.model_dump(mode='json',by_alias=True,exclude_none=True) for t in actual.tools])!=canonical([t.model_dump(mode='json',by_alias=True,exclude_none=True) for t in expected]):raise Denied('native_worker_schema_mismatch')
            except BaseException:
                await client.close();self._routes.pop(route,None);raise
            self._workers[key]=client
            return client
    async def validate(self,name,args):await self.bundle.validate(name,args)
    async def call(self,scope,name,args):
        await self.validate(name,args)
        if name=='trace_read':raise Denied('trace_requires_selected_connector')
        worker=await self._worker(scope)
        result=await worker.call_tool(name,args)
        value=result.structured_content
        if type(value)is not dict or type(value.get('ok'))is not bool or result.is_error is value['ok']:raise Denied('published_native_result_required')
        return value
    async def close(self):
        for client in self._workers.values():await client.close()
        self._workers.clear();self._routes.clear()

async def serve_worker(bundle):
    from mcp.server.stdio import stdio_server
    service=bundle.module.ReadService()
    server=bundle.module.build_server(service)
    async with stdio_server() as (read,write):await server.run(read,write,server.create_initialization_options())
