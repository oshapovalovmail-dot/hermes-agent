"""Honcho real SDK Peer/Session JSON serialization against an offline sink."""
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace

import pytest
from honcho.peer import Peer
from honcho.session import Session


def fixture(plugins, frequency='session', fail_first=False):
    h,_=plugins
    mod=importlib.import_module(h.__name__+'.session')
    manager=mod.HonchoSessionManager(config=h.HonchoClientConfig(write_frequency=frequency))
    calls=[]
    def post(path,body,**kw):
        calls.append((path,deepcopy(body)))
        if fail_first and len(calls)==1: raise RuntimeError('offline failure')
        return []
    binding=SimpleNamespace(workspace_id='fixture-workspace',_ensure_workspace=lambda:None,_http=SimpleNamespace(post=post))
    peers={name:Peer(name,binding) for name in ['human','agent']}
    sdk=Session('fixture-session',binding)
    session=mod.HonchoSession('fixture','human','agent','fixture-session')
    manager._cache['fixture']=session
    manager._sessions_cache['fixture-session']=sdk
    manager._get_or_create_peer=lambda key:peers[key]
    manager._authed_call=lambda label,fn:fn()
    return manager,session,calls


@pytest.mark.parametrize('frequency',['turn','session','async',2])
def test_sdk_flush_retry_all_frequencies_drop_unsafe_cached_rows(plugins,frequency):
    manager,session,calls=fixture(plugins,frequency,True)
    # Raw legacy/direct pending cache, not the high-level turn builder.
    session.messages.extend([
        {'role':'user','content':'human'},
        {'role':'assistant','content':'RAW_INTERMEDIATE'},
        {'role':'tool','content':'RAW_TOOL'},
        {'role':'assistant','channel':'analysis','content':'RAW_ANALYSIS'},
        {'role':'assistant','content':'<think>RAW_REASON</think>final','metadata':{'reasoning_content':'RAW_META'}},
        {'role':'user','source_kind':'task_assignment','content':'RAW_MACHINE'},
        {'role':'assistant','content':'RAW_DERIVED'},
    ])
    try:
        manager.save(session)
        manager.flush_all()
        manager.shutdown()
        assert calls
        assert all('RAW_' not in json.dumps(body) for _,body in calls)
        assert [m['content'] for m in calls[-1][1]['messages']] == ['human','final']
        assert [m['peer_id'] for m in calls[-1][1]['messages']] == ['human','agent']
    finally:
        manager.shutdown()


def test_direct_add_machine_never_becomes_assistant_storage(plugins):
    manager,session,calls=fixture(plugins)
    session.add_message('user','RAW_MACHINE',metadata={'source_kind':'runtime_notification'})
    manager.flush_all()
    assert calls == []


def test_chunked_safe_builder_rows_survive_real_sdk_unchanged(plugins):
    h,_=plugins
    capture=importlib.import_module(h.__name__+'.capture').build_capture_turn
    human='   a human quote <think>literal</think>     '
    answer='  final answer with trailing whitespace     '
    rows=capture(human,'<think>RAW_REASON</think>'+answer,max_chars=5)
    manager,session,calls=fixture(plugins)
    for row in rows: session.add_message(**row)
    manager.flush_all()
    assert calls
    sent=calls[-1][1]['messages']
    assert ''.join(m['content'] for m in sent if m['peer_id']=='human')==human
    assert ''.join(m['content'] for m in sent if m['peer_id']=='agent')==answer
    assert 'RAW_' not in json.dumps(calls)


def test_pure_machine_legacy_queue_zero_sdk_messages(plugins):
    manager,session,calls=fixture(plugins)
    session.messages.extend([{'role':'user','content':'RAW_MACHINE','metadata':{'source_kind':'machine_notification'}},{'role':'assistant','content':'RAW_DERIVED'}])
    manager.flush_all(); manager.shutdown()
    assert calls == []
