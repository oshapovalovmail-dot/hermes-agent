"""Non-initializing native AST harness; real function bodies, scoped ledgers."""
import ast
import asyncio
import contextvars
import inspect
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace, ModuleType
from typing import Any, Optional, Callable
import pytest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('ATLAS_FIX_SOURCE',ROOT/'candidate'))


def extract(file, names, ns):
    tree=ast.parse((SOURCE/'runtime/tools'/file).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE/'runtime/tools'/file),'exec'),ns)

@pytest.fixture
def native(monkeypatch):
    core=SimpleNamespace(_server_error_counts={},_server_breaker_opened_at={},_server_errors_all_application={},
        _CIRCUIT_BREAKER_THRESHOLD=3,_CIRCUIT_BREAKER_COOLDOWN_SEC=60.0,
        _server_circuit_breaker_enabled={},_server_trust_levels={},_tool_read_only_hints={},
        _server_cost_policies={},_lock=threading.RLock(),_TRUST_FULL='full',_TRUST_UNTRUSTED='untrusted')
    scope=[None]
    def own(name,scope_arg=None,**kw):
        s=scope[0] if scope_arg is None and kw.get('current',True) else scope_arg
        return name if s is None else (s,name)
    def resolved(name):
        return ('owner',name) if scope[0]=='adopter' else own(name)
    pkg=ModuleType('tools');pkg.__path__=[]
    mod=ModuleType('tools.mcp_tool_scope');mod._server_key=own;mod._resolve_server_key=resolved
    monkeypatch.setitem(sys.modules,'tools',pkg);monkeypatch.setitem(sys.modules,'tools.mcp_tool_scope',mod)
    ns=dict(_core=core,time=time,Optional=Optional,Any=Any,Callable=Callable,json=json,logger=logging.getLogger('fixture'),
        tool_error=lambda text,**kw:json.dumps({'error':text,**kw}),_server_key=own,
        _normalize_server_trust=lambda value:value or 'full',_record_cost_policy=lambda *a:None)
    for name,value in vars(core).items():ns[name]=value
    extract('mcp_tool.py',{'_circuit_breaker_enabled','_bump_server_error','_reset_server_error'},ns)
    core._bump_server_error=ns['_bump_server_error'];core._reset_server_error=ns['_reset_server_error']
    if '_circuit_breaker_enabled' in ns:core._circuit_breaker_enabled=ns['_circuit_breaker_enabled']
    extract('mcp_tool_handlers.py',{'_check_circuit_breaker','_record_call_outcome','_result_is_error','_dispatch'},ns)
    extract('mcp_tool_registration.py',{'_record_scope_trust','_record_tool_trust_metadata'},ns)
    ns['_annotation_read_only_hint']=lambda tool:True
    return core,scope,ns


def test_explicit_optout_allows_four_errors_then_healthy(native):
    core,scope,n=native
    n['_record_scope_trust']('atlas_read',{'circuit_breaker':False},'owner');scope[0]='owner'
    calls=[]
    for i in range(5):
        blocked=n['_check_circuit_breaker']('atlas_read')
        if blocked is None:
            calls.append(i)
            n['_record_call_outcome']('atlas_read',json.dumps({'error':'fixture rejected'}) if i<4 else '{"result":"healthy"}')
    assert calls==list(range(5))
    assert not core._server_error_counts


@pytest.mark.parametrize('value',[None,True,'false',0,{},[]])
def test_legacy_and_malformed_values_still_pause(native,value):
    core,scope,n=native;scope[0]='owner'
    n['_record_scope_trust']('legacy',{'circuit_breaker':value},'owner')
    for _ in range(3):n['_record_call_outcome']('legacy','{"error":"fixture"}')
    assert 'Paused' in json.loads(n['_check_circuit_breaker']('legacy'))['error']
    assert n['_check_circuit_breaker']('another') is None


def test_optout_policy_does_not_follow_shared_connection(native):
    core,scope,n=native
    n['_record_scope_trust']('atlas_read',{'circuit_breaker':False},'owner')
    n['_record_scope_trust']('atlas_read',{},'adopter')
    scope[0]='adopter'
    for _ in range(3):n['_record_call_outcome']('atlas_read','{"error":"fixture"}')
    assert n['_check_circuit_breaker']('atlas_read') is not None
    scope[0]='owner'
    assert n['_check_circuit_breaker']('atlas_read') is None
    n['_record_call_outcome']('atlas_read','{"error":"fixture"}')
    assert core._server_error_counts[('owner','atlas_read')]==3


def test_transport_errors_do_not_open_optout_breaker(native):
    core,scope,n=native;scope[0]='owner'
    n['_record_scope_trust']('atlas_read',{'circuit_breaker':False},'owner')
    for _ in range(5):core._bump_server_error('atlas_read')
    assert n['_check_circuit_breaker']('atlas_read') is None
    assert not core._server_error_counts
