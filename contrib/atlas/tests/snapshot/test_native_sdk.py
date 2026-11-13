"""Native handler function bodies -> real SDK sidecar calls, no native initialization."""
import ast
import asyncio
from contextlib import asynccontextmanager
import contextvars
from functools import partial
import inspect
import json
from pathlib import Path
from types import SimpleNamespace, ModuleType
import sys
from typing import Any
import pytest
from mcp import Client
from test_breaker import native, extract, SOURCE
from test_sdk import params


def bind_handler(n,core,client,monkeypatch,loop):
    relay=ModuleType('agent.tool_progress_relay');relay.current_tool_progress=lambda:None
    agent=ModuleType('agent');agent.__path__=[]
    monkeypatch.setitem(sys.modules,'agent',agent);monkeypatch.setitem(sys.modules,'agent.tool_progress_relay',relay)
    server=SimpleNamespace(session=client,_rpc_lock=asyncio.Lock(),_inflight_tasks=set())
    n.update(asyncio=asyncio,inspect=inspect,contextvars=contextvars,partial=partial,asynccontextmanager=asynccontextmanager,
        _trust_gate_check=lambda *a:None,_acquire_call_server=lambda *a:(server,None),
        _loop=SimpleNamespace(_run_on_mcp_loop=lambda call,timeout:asyncio.run_coroutine_threadsafe(call(),loop).result(timeout)),
        _handle_stdio_child_exited_and_retry=lambda *a:None,_handle_auth_error_and_retry=lambda *a:None,
        _handle_session_expired_and_retry=lambda *a,**kw:None,
        _mcp_call_failed_message=lambda exc:'fixture transport failed',
        _mcp_result_with_native_images=lambda text,images:text,
        mcp_field=lambda obj,snake,camel,default=None:getattr(obj,snake,getattr(obj,camel,default)),
        _sanitize_error=lambda text:text,_truncate_mcp_text_result=lambda text:text,
        _render_content_blocks=lambda result,server:(''.join(b.text for b in result.content),1,[]),
        _capped_structured_content=lambda result:result.structured_content,
        _strip_reserved_meta_keys=lambda meta:None,
        _content_dual_emits_structured=lambda result,structured:json.loads(result.content[0].text)==structured)
    extract('mcp_tool_handlers.py',{'_tool_is_read_only','_make_tool_handler','_track_inflight_rpc','_call_tool_racing_stdio_death',
        '_render_call_tool_result','_error_result_text'},n)
    return n['_make_tool_handler']('atlas_read','service_read',10),server


async def exercise(native,monkeypatch,home,optout):
    core,scope,n=native;scope[0]='owner'
    n['_record_scope_trust']('atlas_read',{'circuit_breaker':False} if optout else {},'owner')
    core._tool_read_only_hints[('owner','atlas_read')]={'service_read':True}
    async with Client(params(home),read_timeout_seconds=30) as client:
        await client.list_tools()
        handler,server=bind_handler(n,core,client,monkeypatch,asyncio.get_running_loop())
        bad={'operation':'nonexistent.fixture','arguments':{}}
        errors=[json.loads(await asyncio.to_thread(handler,bad)) for i in range(4)]
        good={'operation':'intrasearch.list_verticals','arguments':{},'max_chars':1200}
        result=json.loads(await asyncio.to_thread(handler,good))
        assert all('error' in result for result in errors)
        if optout:
            assert all('Paused' not in e['error'] for e in errors)
            assert json.loads(result['result'])['ok']
            assert not core._server_error_counts
        else:
            assert 'Paused' in errors[3]['error'] and 'Paused' in result['error']
        assert not server._inflight_tasks
        # The exact native handler must retain trust-before-transport ordering.
        n['_trust_gate_check']=lambda *a:'{"error":"fixture approval denied"}'
        assert json.loads(await asyncio.to_thread(handler,good))=={'error':'fixture approval denied'}
        # Cancellation remains an interruption, not a server strike.
        before=dict(core._server_error_counts)
        def interrupt(*a,**kw):raise InterruptedError()
        n['_loop']._run_on_mcp_loop=interrupt
        outcome=n['_dispatch']('atlas_read',server,'fixture',lambda:None,10,(),lambda exc:None,record_outcome=True)
        assert 'interrupted' in json.loads(outcome)['error']
        assert core._server_error_counts==before

@pytest.mark.parametrize('optout',[True,False])
def test_native_handler_real_sdk_four_errors_then_valid(native,monkeypatch,tmp_path,optout):
    asyncio.run(exercise(native,monkeypatch,tmp_path,optout))


def test_recovery_security_function_bodies_unchanged():
    root=Path(__file__).resolve().parents[1]
    def functions(folder):
        tree=ast.parse((root/folder/'runtime/tools/mcp_tool_handlers.py').read_text())
        return {n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    old,new=functions('baseline'),functions('candidate')
    changed={k for k in old if old[k]!=new[k]}
    assert changed=={'_check_circuit_breaker','_record_call_outcome'}
