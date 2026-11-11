"""Second RED batch: final transport, pending queues and typed block origins."""
from copy import deepcopy
import importlib
import json
import threading
from types import SimpleNamespace

import pytest
from test_provider_egress import capture, texts, wired_viking, VikingSink
from test_honcho_sdk_egress import fixture as honcho_fixture


@pytest.mark.parametrize('name',['honcho','openviking'])
def test_typed_text_block_provenance_is_not_discarded_before_filter(plugins,name):
    rows=[{'role':'user','content':[{'type':'text','text':'before\n'},{'type':'text','text':'RAW_SERVICE','source_kind':'task_assignment'},{'type':'text','text':'after  '}]},{'role':'assistant','content':'final'}]
    result=capture(plugins,name,rows,user='before\nafter  ')
    assert texts(result)==['before\nafter  ','final']


def test_upload_constructor_detaches_and_guards_native_dto_and_raw_fields(plugins):
    _,v=plugins
    rows=[{'role':'user','parts':[{'type':'text','text':'human'}],'peer_id':'fixture-human','metadata':{'reasoning':'RAW_META'}},
          {'role':'assistant','parts':[{'type':'tool','tool_output':'RAW_TOOL'},{'type':'reasoning','text':'RAW_REASON'},{'type':'text','text':'final'}],'peer_id':'fixture-agent'},
          {'role':'user','parts':[{'type':'text','text':'RAW_MACHINE'}],'source_kind':'machine_notification'},
          {'role':'assistant','parts':[{'type':'text','text':'RAW_DERIVED'}]}]
    sink=VikingSink()
    upload=v._TurnUpload(sink,'fixture-session',rows,'RAW_USER','RAW_ASSISTANT','fixture-agent','fixture-human')
    rows[0]['parts'][0]['text']='RAW_MUTATION'
    assert upload.run() is sink
    assert texts(upload.batch_messages)==['human','final']
    assert 'RAW_' not in json.dumps(sink.calls)
    assert upload.user_content=='human'
    assert upload.assistant_content=='final'


def test_empty_direct_upload_has_no_success_or_calls(plugins):
    _,v=plugins
    sink=VikingSink()
    upload=v._TurnUpload(sink,'fixture-session',[{'role':'user','source_kind':'reasoning','parts':[{'type':'text','text':'RAW_MACHINE'}]}],'RAW_USER','RAW_ASSISTANT','fixture-agent')
    assert upload.run() is None
    assert sink.calls==[]


def test_direct_mirror_worker_rechecks_legacy_typed_event(plugins,tmp_path):
    p,sink,module=wired_viking(plugins,tmp_path)
    p._build_memory_uri=lambda *a,**k:'viking://user/fixture-user/memories/fact.md'
    mm=importlib.import_module(module.__name__+'.native_memory_mirror')
    mirror=mm.NativeMemoryMirror(p)
    mirror._apply({'action':'add','target':'user','content':'RAW_MACHINE','metadata':{'source_kind':'runtime_notification'},'subdir':'preferences','client':sink,'connection':'fixture'})
    assert sink.calls==[]
    assert not (tmp_path/'openviking'/'memory_mirror_registry.json').exists()


def test_honcho_pending_turn_identity_is_allowlisted_and_turn_is_detached(plugins):
    h,_=plugins
    p=h.HonchoMemoryProvider()
    p._config=h.HonchoClientConfig(write_frequency='session')
    p._ready_or_kick_init=lambda:False
    rows=[{'role':'user','content':'human'},{'role':'assistant','content':'<think>RAW_REASON</think>final'}]
    author={'id':'fixture-human','name':'Human','is_bot':False,'reasoning_content':'RAW_AUTHOR'}
    p.sync_turn('human','RAW_SCALAR',messages=rows,turn_author=author)
    assert len(p._pending_turns)==1
    rows[0]['content']='RAW_MUTATION'
    assert 'RAW_' not in json.dumps(p._pending_turns)
    assert p._pending_turns[0][1]=={'id':'fixture-human','name':'Human','is_bot':False}


@pytest.mark.parametrize('rows',[[],[{'role':'user','source_kind':'task_assignment','content':'RAW_MACHINE'},{'role':'assistant','content':'RAW_DERIVED'}]])
def test_honcho_empty_sync_never_initializes_or_queues(plugins,rows):
    h,_=plugins
    p=h.HonchoMemoryProvider(); p._config=h.HonchoClientConfig()
    p._ready_or_kick_init=lambda:pytest.fail('empty turn initialized')
    p.sync_turn('RAW_MACHINE','RAW_DERIVED',messages=rows)
    assert p._pending_turns==[]


@pytest.mark.parametrize('enabled',[False,True])
def test_automatic_init_migration_gate_is_checked_before_import_method(plugins,monkeypatch,enabled):
    h,_=plugins
    sm=importlib.import_module(h.__name__+'.session'); cm=importlib.import_module(h.__name__+'.client')
    migrated=[]
    fake=SimpleNamespace(get_or_create=lambda key:SimpleNamespace(messages=[]),migrate_memory_files=lambda *a:migrated.append(a))
    monkeypatch.setattr(sm,'HonchoSessionManager',lambda **kw:fake)
    monkeypatch.setattr(cm,'get_honcho_client',lambda cfg:None)
    p=h.HonchoMemoryProvider(); cfg=h.HonchoClientConfig(save_messages=enabled,session_strategy='per-directory')
    p._config=cfg; p._resolve_session_key=lambda *a,**k:'fixture-session';p._drain_pending_turns=lambda:None
    p._do_session_init(cfg,'fixture-session')
    assert bool(migrated)==enabled


def test_sdk_flush_keeps_synced_human_context_for_later_final_only(plugins):
    manager,session,calls=honcho_fixture(plugins)
    session.add_message('user','human')
    manager.flush_all()
    session.add_message('assistant','<think>RAW_REASON</think>final')
    manager.flush_all()
    assert [m['content'] for m in calls[-1][1]['messages']]==['final']


def test_viking_sync_real_worker_uses_safe_scalars_and_scope(plugins,tmp_path):
    p,sink,v=wired_viking(plugins,tmp_path)
    seen=[]
    old=v._TurnUpload.run
    def record(upload):
        seen.append((upload.user_content,upload.assistant_content,upload.sid,upload.client))
        return old(upload)
    v._TurnUpload.run=record
    try:
        p.sync_turn('human','RAW_SCALAR',messages=[{'role':'user','content':'human'},{'role':'assistant','content':'<think>RAW_REASON</think>final'}])
        assert p._drain_writers('fixture-session',2.0)
        assert seen==[('human','final','fixture-session',sink)]
        assert p._turn_count==1
        assert 'RAW_' not in json.dumps(sink.calls)
    finally:
        v._TurnUpload.run=old
