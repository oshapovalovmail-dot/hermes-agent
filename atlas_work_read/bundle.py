"""Admit all eleven published files and reuse their exact native contract."""
import hashlib
import os
from pathlib import Path
import stat
import sys
import types

from atlas_bridge.contract import digest, Denied

FILES=frozenset(('sidecar.py','read_paging.py','read_snapshot_store.py','select_parser.py','work_services_backend.py','work_services_manifest.json','tracker_wiki_backend.py','tracker_wiki_catalog.json','datalens_backend.py','yt_backend.py','nirvana_backend.py'))
METHODS=frozenset(('integration_status','wiki_read','tracker_read','pr_read','trace_read','nirvana_read','yt_read','datalens_read','service_catalog','service_read'))

def read_pinned(root,name,pin):
    from atlas_native_bridge.protocol import directory
    fd=directory(root)
    try:
        f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            st=os.fstat(f)
            if not stat.S_ISREG(st.st_mode):raise Denied('reviewed_bundle_regular_files_required')
            with os.fdopen(f,'rb',closefd=False) as stream:data=stream.read()
        finally:os.close(f)
    finally:os.close(fd)
    if hashlib.sha256(data).hexdigest()!=pin:raise Denied('reviewed_bundle_integrity')
    return data

class Bundle:
    def __init__(self,root,pins):
        self.root=Path(root);self.pins=dict(pins)
        if not self.root.is_absolute() or set(pins)!=FILES:raise Denied('exact_eleven_file_bundle_required')
        self.bundle_id=digest(self.pins)
        sources={n:read_pinned(self.root,n,p) for n,p in self.pins.items()}
        name='_atlas_closed_read_'+self.bundle_id
        self.module=types.ModuleType(name);self.module.__file__=str(self.root/'sidecar.py')
        sys.modules[name]=self.module
        exec(compile(sources['sidecar.py'],self.module.__file__,'exec',dont_inherit=True),self.module.__dict__)
        # Build only policy/schema; no credentials and no service IO.
        self.server=self.module.build_server(self.module.ReadService(tracker_api=object()))
        self._tools=None
    def verify(self):
        for name,pin in self.pins.items():read_pinned(self.root,name,pin)
    async def tools(self):
        if self._tools is None:
            result=await self.server.get_request_handler('tools/list').handler(None,None)
            if {t.name for t in result.tools}!=METHODS:raise Denied('published_toolset_changed')
            self._tools=tuple(result.tools)
        return self._tools
    def operations(self):return self.module.service_manifest()
    async def validate(self,name,args):
        from jsonschema import Draft202012Validator
        self.verify()
        schemas={t.name:t.input_schema for t in await self.tools()}
        if name not in schemas or type(args)is not dict or not Draft202012Validator(schemas[name]).is_valid(args):raise Denied('invalid_argument')
        if name in ('service_catalog','service_read') and not self.module.service_input_valid(name,args):raise Denied('invalid_argument')
    async def call(self,name,args,service=None):
        await self.validate(name,args)
        from mcp import types as mt
        service=service or self.module.ReadService()
        server=self.module.build_server(service)
        reply=await server.get_request_handler('tools/call').handler(None,mt.CallToolRequestParams(name=name,arguments=args))
        value=reply.structured_content
        if type(value)is not dict or type(value.get('ok'))is not bool:raise Denied('published_serializer_required')
        return value
