"""Real SDK stdio wrapper around the exact pinned sidecar with fixture upstreams.
No credentials or network. Only synthetic backend results replace upstream IO.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys

source=Path(sys.argv[1])/'services/atlas-read'
spec=importlib.util.spec_from_file_location('fixture_sidecar',source/'sidecar.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
w=s.load_service_backend('work_services')
PRIVATE='fixture-private-upstream-cursor-not-for-model'

def upstream(self,operation,arguments,max_chars,native_capture=None):
    data={'items':[{'id':i,'value':i+17,'text':'fixture row '+str(i)} for i in range(80)]}
    if operation=='monium_mcp.list_agents':
        if arguments.get('page_token') is not None:
            if arguments['page_token']!=PRIVATE:raise AssertionError('private upstream argument lost')
            data['has_more']=False
        else:
            data.update(next_page_token=PRIVATE,has_more=True)
    if native_capture is not None:native_capture(data)
    return {'ok':True,'code':'ok','text':json.dumps(data),'_data':data,'pagination':{}}

w.Backend.read_full=upstream
# Hard-stop every unselected host IO path; a wrong operation must not
# accidentally consult native authentication or a work-service endpoint.
def forbidden(*args,**kwargs):
    raise AssertionError('fixture forbids upstream IO')
t=s.load_service_backend('tracker_wiki')
TRACKER_PRIVATE='synthetic_private_native_cursor_'*3

def tracker_upstream(argv):
    if 'get_issue_changelog' not in argv:raise AssertionError('fixture forbids unselected native tools')
    follow=any(arg=='cursor:'+TRACKER_PRIVATE for arg in argv)
    data={'events':[{'id':i,'value':i+1} for i in range(20)],'hasMore':not follow}
    if not follow:data['nextCursor']=TRACKER_PRIVATE
    return json.dumps({'result':{'structuredContent':data}})

t.fixed_cli=tracker_upstream
s.subprocess.run=forbidden
s.build_opener=forbidden
d=s.load_extension('datalens_read')

def dashboard(self,url,view='summary',max_chars=12000,cursor=None):
    if cursor:return d.continue_page(cursor,url,view,max_chars)
    return d.capture_pages({'charts':[{'series':[{'data':[[i,i+1] for i in range(300)]}]}],'metadata':[]},url,view,max_chars)

d.Backend.read=dashboard

async def main():
    from mcp.server.stdio import stdio_server
    server=s.build_server(s.ReadService(runner=forbidden, tracker_api=object()))
    async with stdio_server() as streams:
        await server.run(streams[0],streams[1],server.create_initialization_options())

asyncio.run(main())
