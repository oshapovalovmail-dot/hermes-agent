"""QYP MCP facade: exact published tools, native-issued per-call proof only."""
import json
from pathlib import Path
from atlas_bridge.contract import Denied,canonical
from .rpc import consume,validate_body,unix_exchange

class NativeReadFacade:
    def __init__(self,bundle,codec,profile_home,exchange):
        self.bundle=bundle;self.codec=codec;self.profile_home=Path(profile_home).resolve(strict=True);self.exchange=exchange;self._used={}
    async def call(self,name,args,meta):
        if Path.cwd().resolve()!=self.profile_home:raise Denied('private_native_mcp_cwd_required')
        await self.bundle.validate(name,args)
        if type(meta)is not dict or 'atlas.nativeSessionProof' not in meta:raise Denied('native_session_proof_required')
        envelope=meta['atlas.nativeSessionProof']
        # Request sender is QYP. Verify with the opposite role; never a JSON bool.
        from atlas_native_bridge.protocol import Codec
        frame=Codec(self.codec._key,self.codec.epoch,'mac').verify(envelope)
        if frame['kind']!='work_read':raise Denied('native_session_proof_required')
        body=validate_body(frame['body'])
        if (body['method']!=name or canonical(body['arguments'])!=canonical(args) or body['bundle_id']!=self.bundle.bundle_id
            or self.profile_home.name!=body['scope']['profile']):raise Denied('exact_native_mcp_call_required')
        import time
        self._used={k:v for k,v in self._used.items() if v>time.time()}
        if frame['nonce'] in self._used:raise Denied('replayed_native_call_proof')
        self._used[frame['nonce']]=frame['exp']
        pages=await self.exchange(envelope)
        return consume(self.codec,body,pages)
    async def server(self):
        from mcp import types
        from mcp.server.lowlevel import Server
        tools=list(await self.bundle.tools())
        async def listing(ctx,params):return types.ListToolsResult(tools=tools)
        async def calling(ctx,params):
            try:value=await self.call(params.name,params.arguments or {},params.meta)
            except PermissionError:
                value=self.bundle.module.result(False,'native_work_read_denied')
            # CancelledError/InterruptedError and native SDK errors are not success.
            return types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps(value,ensure_ascii=False))],structuredContent=value,isError=not value['ok'])
        return Server('atlas_read',version='1.0.0',instructions=self.bundle.server.instructions,on_list_tools=listing,on_call_tool=calling,
            get_tool_input_schema=self.bundle.server.get_tool_input_schema)

async def serve(bundle,codec,home,hub_socket):
    from mcp.server.stdio import stdio_server
    async def exchange(envelope):return await unix_exchange(hub_socket,envelope)
    facade=NativeReadFacade(bundle,codec,home,exchange);server=await facade.server()
    async with stdio_server() as (read,write):await server.run(read,write,server.create_initialization_options())
