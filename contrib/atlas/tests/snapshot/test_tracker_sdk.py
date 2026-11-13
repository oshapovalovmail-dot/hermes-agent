import asyncio
import json
from mcp import Client
from test_sdk import params, payload


async def exercise(home):
    async with Client(params(home),read_timeout_seconds=30) as client:
        await client.list_tools();held=[]
        for i in range(24):
            answer=payload(await client.call_tool('service_read',{'operation':'tracker.get_issue_changelog','arguments':{'issue':'FIXTURE-1'},'max_chars':1200}))
            assert 'synthetic_private_native_cursor_'*3 not in json.dumps(answer)
            request=answer['pagination']['upstream']['continuation']
            assert request['arguments']['continuation'].startswith('ac1-')
            held.append(request)
        for request in held:
            answer=payload(await client.call_tool('service_read',{**request,'max_chars':1200}))
            assert answer['pagination']['upstream']['has_more'] is False
        return len(held)


def test_tracker_sdk_private_one_hour_handles(tmp_path):
    assert asyncio.run(exercise(tmp_path))==24
