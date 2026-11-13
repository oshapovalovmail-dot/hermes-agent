import asyncio
import json
import os
from pathlib import Path
import sys
from contextlib import AsyncExitStack
import pytest
from mcp import Client, StdioServerParameters
from test_capacity import SOURCE
from test_safety import reconstruct

SERVER=Path(__file__).with_name('sdk_fixture_server.py')


def params(home):
    return StdioServerParameters(command=sys.executable,args=['-I','-B',str(SERVER),str(SOURCE)],cwd=str(home),
        env={'HOME':str(home),'PATH':'/usr/bin:/bin','TMPDIR':os.environ['TMPDIR']})


def payload(result):
    assert not result.is_error, ''.join(b.text for b in result.content if hasattr(b,'text'))
    value=result.structured_content
    assert value['ok']
    assert len(result.model_dump_json(by_alias=True).encode())<=10000
    assert 'fixture-private-upstream-cursor-not-for-model' not in result.model_dump_json()
    return value


async def run_many(tmp_path):
    a=tmp_path/'owner';b=tmp_path/'member';a.mkdir();b.mkdir()
    async with AsyncExitStack() as stack:
        first=await stack.enter_async_context(Client(params(a),read_timeout_seconds=30))
        second=await stack.enter_async_context(Client(params(b),read_timeout_seconds=30))
        tools=await first.list_tools()
        assert {'service_read','service_catalog','datalens_read'}<=set(t.name for t in tools.tools)
        held=[]
        for i in range(108):
            op=['monium_mcp.list_metric_functions','intrasearch.list_verticals','staff_api_mcp.person-photo','monium_mcp.list_agents'][i%4]
            args={'project':'fixture'} if op=='monium_mcp.list_agents' else {}
            answer=payload(await first.call_tool('service_read',{'operation':op,'arguments':args,'max_chars':1200}))
            held.append((op,answer))
        total_pages=0;native_follows=0
        for op,answer in held:
            first_answer=answer;records=[]
            while True:
                total_pages+=1;records+=json.loads(answer['text'])['records']
                cursor=answer['pagination']['cursor']
                if not cursor:break
                answer=payload(await first.call_tool('service_read',{'operation':op,'arguments':{'continuation':cursor},'max_chars':1200}))
            data=reconstruct(records)
            assert data['items']==[{'id':i,'value':i+17,'text':'fixture row '+str(i)} for i in range(80)]
            native=first_answer['pagination']['upstream'].get('continuation')
            if native:
                follow=payload(await first.call_tool('service_read',{**native,'max_chars':1200}))
                assert not follow['pagination']['upstream'].get('has_more',False)
                native_follows+=1
            # Completed snapshots remain replayable until the original TTL.
            cursor=first_answer['pagination']['cursor']
            own=payload(await first.call_tool('service_read',{'operation':op,'arguments':{'continuation':cursor},'max_chars':1200}))
            foreign=await second.call_tool('service_read',{'operation':op,'arguments':{'continuation':cursor},'max_chars':1200})
            assert foreign.is_error and foreign.structured_content['code']=='continuation_unavailable'
            assert own['pagination']['page']==2
        dl=[];url='https://datalens.yandex-team.ru/abcdefghijklm'
        for i in range(12):dl.append(payload(await first.call_tool('datalens_read',{'url':url,'view':'data','max_chars':1200})))
        for answer in dl:
            records=[]
            while True:
                records+=json.loads(answer['text'])['records'];cursor=answer['pagination']['cursor']
                if not cursor:break
                answer=payload(await first.call_tool('datalens_read',{'url':url,'view':'data','max_chars':1200,'cursor':cursor}))
            assert reconstruct(records)['charts'][0]['series'][0]['data']==[[i,i+1] for i in range(300)]
        return {'initial_reads':len(held),'reconstructed_pages':total_pages,'native_followups':native_follows,'datalens_active_captures':len(dl),'isolated_profiles':2}


def test_sdk_lossless_many_reads_and_native_private_cursors(tmp_path):
    evidence=asyncio.run(run_many(tmp_path))
    assert evidence['initial_reads']==108 and evidence['native_followups']==27
    print(json.dumps(evidence,sort_keys=True))
