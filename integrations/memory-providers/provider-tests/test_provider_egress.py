"""Offline serialization contract; sinks are synthetic, policy/queues are real."""
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
import threading

import pytest


def capture(plugins, name, rows, user='human', answer='final', chunk=25000):
    h, v = plugins
    if name == 'honcho':
        return importlib.import_module(h.__name__ + '.capture').build_capture_turn(user, answer, messages=rows, max_chars=chunk)
    current = v.OpenVikingMemoryProvider._extract_current_turn_messages(rows, user, answer)
    return v.OpenVikingMemoryProvider._messages_to_openviking_batch(current, assistant_peer_id='agent-fixture', user_peer_id='human-fixture')


def texts(payloads):
    return [m['content'] if 'content' in m else ''.join(p['text'] for p in m['parts'] if p.get('type') == 'text') for m in payloads]


@pytest.mark.parametrize('provider', ['honcho', 'openviking'])
@pytest.mark.parametrize('rows', [[], [{'role':'tool','content':'RAW_TOOL'}], [{'role':'user','content':'RAW_MACHINE','source_kind':'machine_notification','capture_current_turn':True},{'role':'assistant','content':'RAW_DERIVED'}], [{'role':'user','content':'old'},{'role':'assistant','content':'old answer'}]])
def test_authoritative_empty_and_unmatched_never_resurrect_scalar_pair(plugins, provider, rows):
    assert capture(plugins, provider, rows, user='RAW_MACHINE', answer='RAW_DERIVED') == []


@pytest.mark.parametrize('provider', ['honcho', 'openviking'])
def test_mixed_provenance_keeps_exact_human_bytes_only(plugins, provider):
    rows = [
        {'role':'user','content':'old'}, {'role':'assistant','content':'old answer'},
        {'role':'user','content':'  human before\n','source_kind':'human','capture_current_turn':True,'metadata':{'reasoning_content':'RAW_META'}},
        {'role':'user','content':'RAW_MACHINE','source_kind':'task_assignment','capture_current_turn':True},
        {'role':'user','content':'\nafter  ','source_kind':'human','capture_current_turn':True},
        {'role':'assistant','channel':'commentary','content':'RAW_PROGRESS'},
        {'role':'assistant','content':'RAW_INTERMEDIATE','tool_calls':[{'id':'tool1','function':{'name':'terminal','arguments':'RAW_ARGS'}}]},
        {'role':'tool','content':'RAW_TOOL','tool_call_id':'tool1'},
        {'role':'assistant','reasoning_content':'RAW_SIDECAR','metadata':{'thinking':'RAW_META'},'content':[{'type':'reasoning','text':'RAW_REASON'},{'type':'text','text':'final'}]},
    ]
    original = deepcopy(rows)
    result = capture(plugins, provider, rows)
    assert texts(result) == ['  human before\n', '\nafter  ', 'final']
    assert 'RAW_' not in json.dumps(result)
    assert rows == original


@pytest.mark.parametrize('provider', ['honcho', 'openviking'])
@pytest.mark.parametrize('text', ['<think>literal quote</think>', '[ASYNC DELEGATION COMPLETE] I am quoting a marker', '```analysis\nreasoning is a technical subject\n```'])
def test_human_marker_and_think_quotes_are_not_origin_credentials(plugins, provider, text):
    result = capture(plugins, provider, [{'role':'user','content':text},{'role':'assistant','content':'final'}], user=text)
    assert texts(result) == [text, 'final']


@pytest.mark.parametrize('provider', ['honcho', 'openviking'])
@pytest.mark.parametrize('content', [
    [{'type':'thinking','text':'RAW_REASON'},{'type':'thinking','thinking':'RAW_THINK'},{'type':'text','text':'final'}],
    '<think>RAW_REASON</think>final',
    [{'type':'output_text','text':'final'},{'type':'summary_text','summary_text':'RAW_REASON'}],
])
def test_assistant_content_only_visible_final_text(plugins, provider, content):
    result = capture(plugins, provider, [{'role':'user','content':'human'},{'role':'assistant','content':content}])
    assert texts(result) == ['human','final']
    assert 'RAW_' not in json.dumps(result)


@pytest.mark.parametrize('provider', ['honcho', 'openviking'])
def test_unknown_structured_types_never_stringified(plugins, provider):
    result = capture(plugins, provider, [{'role':'user','content':'human'},{'role':'assistant','content':{'mystery':'RAW_UNKNOWN'}}])
    assert texts(result) == ['human']


@pytest.mark.parametrize('provider', ['honcho', 'openviking'])
def test_direct_serializer_removes_tools_and_intermediate(plugins, provider):
    _, v = plugins
    rows = [{'role':'user','content':'human'}, {'role':'assistant','content':'RAW_PROGRESS'}, {'role':'tool','content':'RAW_TOOL'}, {'role':'assistant','content':'final'}]
    if provider == 'openviking':
        result = v.OpenVikingMemoryProvider._messages_to_openviking_batch(rows)
    else:
        result = capture(plugins, provider, rows)
    assert texts(result) == ['human','final']


class VikingSink:
    _endpoint='http://offline.invalid'; _api_key='fixture'; _account='fixture-account'; _user='fixture-user'; _agent='fixture-agent'
    def __init__(self, fail=()): self.calls=[]; self.fail=set(fail)
    def post(self, path, payload=None, **kwargs):
        self.calls.append((path, deepcopy(payload)))
        if len(self.calls) in self.fail: raise RuntimeError('offline injected transport failure')
        return {'status':'ok','result':{'uri':(payload or {}).get('uri','')}}
    def get(self, path, **kwargs): return {'status':'ok','result':{'user':'fixture-user'}}
    def delete(self, path, **kwargs): self.calls.append((path, deepcopy(kwargs))); return {'status':'ok'}


def wired_viking(plugins, tmp_path):
    _, module=plugins
    p=module.OpenVikingMemoryProvider(); sink=VikingSink()
    p._hermes_home=str(tmp_path); p._agent='fixture-agent'; p._session_id='fixture-session'
    p._client=sink; p._ensure_client=lambda: sink; p._new_client=lambda: sink
    p._profile_config_and_env=lambda: ({},{})
    p._setting=lambda *a, **k: 0
    p._mark_session_pending=lambda *a, **k: None
    p._maybe_commit_live_session=lambda *a, **k: None
    return p,sink,module


@pytest.mark.parametrize('rows', [[], [{'role':'user','content':'RAW_MACHINE','source_kind':'machine_notification'},{'role':'assistant','content':'RAW_DERIVED'}]])
def test_viking_sync_empty_has_zero_uploads_or_pending_commit(plugins,tmp_path,rows):
    p,sink,_=wired_viking(plugins,tmp_path)
    spawned=[]; p._spawn_upload=lambda *a: spawned.append(a)
    p.sync_turn('RAW_MACHINE','RAW_DERIVED',messages=rows)
    assert spawned == []
    assert sink.calls == []
    assert p._turn_count == 0


@pytest.mark.parametrize('fail', [{1}, {2,3}, {1,2,3}])
def test_viking_real_upload_fallback_retry_stays_safe_and_bound(plugins, monkeypatch, fail):
    _,v=plugins
    monkeypatch.setattr(v,'_SESSION_MESSAGE_BATCH_LIMIT',1)
    sink=VikingSink(fail)
    rows=[{'role':'user','content':'human'},{'role':'assistant','content':'<think>RAW_REASON</think>final'}]
    batch=v.OpenVikingMemoryProvider._messages_to_openviking_batch(rows,assistant_peer_id='fixture-agent',user_peer_id='fixture-human')
    upload=v._TurnUpload(sink,'fixture-session',batch,'RAW_USER','RAW_ASSISTANT','fixture-agent','fixture-human')
    assert upload.run() is sink
    assert upload.next_index == len(batch)
    assert all('/fixture-session/messages' in path for path,_ in sink.calls)
    assert 'RAW_' not in json.dumps(sink.calls)
    assert texts(batch) == ['human','final']


def test_honcho_chunk_scrubs_before_split_and_keeps_whitespace(plugins):
    human='  [ASYNC DELEGATION COMPLETE] <think>quoted</think>\n '
    rows=[{'role':'user','content':human},{'role':'assistant','content':'<think>RAW_REASON</think>final'}]
    result=capture(plugins,'honcho',rows,user=human,chunk=7)
    assert ''.join(r['content'] for r in result if r['role']=='user') == human
    assert ''.join(r['content'] for r in result if r['role']=='assistant') == 'final'
    assert 'RAW_' not in json.dumps(result)


@pytest.mark.parametrize('provider',['honcho','openviking'])
@pytest.mark.parametrize('metadata',[{'source_kind':'runtime_notification'},{'channel':'analysis'},{'source_kind':'reasoning'},{'display_kind':'task_assignment'},{'source_kind':'human','display_metadata':{'source_kind':'machine_notification'}}])
def test_builtin_mirror_blocks_typed_service_and_reasoning(plugins,tmp_path,provider,metadata):
    h,_=plugins
    if provider=='openviking':
        p,sink,_=wired_viking(plugins,tmp_path)
        p.on_memory_write('add','user','RAW_MIRROR',metadata=metadata)
        mirror=getattr(p,'_native_memory_mirror',None)
        if mirror: mirror.shutdown()
        assert sink.calls == []
    else:
        p=h.HonchoMemoryProvider(); p._config=SimpleNamespace(save_messages=True)
        p._manager=SimpleNamespace(create_conclusion=lambda *a: pytest.fail('service mirrored'))
        p._ready_or_kick_init=lambda: True
        p._spawn_write=lambda fn,*a: fn()
        p.on_memory_write('add','user','RAW_MIRROR',metadata=metadata)


def test_viking_mirror_goodfacts_replace_remove_identity_is_preserved(plugins,tmp_path):
    p,sink,_=wired_viking(plugins,tmp_path)
    p._build_memory_uri=lambda *a,**k:'viking://user/fixture-user/memories/fact.md'
    p.on_memory_write('add','user','I research reasoning and quote <think> tags')
    mirror=p._native_memory_mirror
    # Join each current worker; the same mirror can restart for the next event.
    mirror._worker.join(2)
    p.on_memory_write('replace','user','I research type systems',metadata={'previous_content':'I research reasoning and quote <think> tags','reasoning_content':'RAW_META'})
    mirror._worker.join(2)
    p.on_memory_write('remove','user','',metadata={'source_kind':'runtime_notification','previous_content':'I research type systems'})
    mirror.shutdown()
    assert [path for path,_ in sink.calls] == ['/api/v1/content/write','/api/v1/content/write','/api/v1/fs']
    assert sink.calls[1][1]['uri'] == sink.calls[0][1]['uri']
    assert 'RAW_' not in json.dumps(sink.calls)


def migration_fixture(plugins,tmp_path,enabled=True):
    h,_=plugins
    mod=importlib.import_module(h.__name__+'.session')
    manager=mod.HonchoSessionManager(config=h.HonchoClientConfig(save_messages=enabled,write_frequency='session'))
    session=mod.HonchoSession('fixture','human','agent','fixture-session')
    manager._cache['fixture']=session
    uploads=[]
    sdk=SimpleNamespace(upload_file=lambda **kw:uploads.append(deepcopy(kw)))
    manager._sessions_cache['fixture-session']=sdk
    manager._declared_owner_peer_id=lambda:'human'
    manager._get_or_create_peer=lambda peer:peer
    manager._sdk_session=lambda sid:sdk
    manager._seed_once=lambda peer,key,content,write,**kw:(write('fixture-digest') or True)
    manager._authed_call=lambda label,fn:fn()
    return manager,uploads


def test_honcho_auto_import_hard_write_gate(plugins,tmp_path):
    manager,uploads=migration_fixture(plugins,tmp_path,False)
    (tmp_path/'MEMORY.md').write_text('ordinary curated fact')
    assert manager.migrate_memory_files('fixture',str(tmp_path)) is False
    assert uploads == []


@pytest.mark.parametrize('forbidden', ['<think>RAW_IMPORT</think>', '<think>\nRAW_IMPORT\n</think>\n',json.dumps({'role':'user','source_kind':'machine_notification','content':'RAW_IMPORT'}),json.dumps([{'role':'tool','content':'RAW_IMPORT'}])])
def test_honcho_import_skips_structural_service_reasoning_but_keeps_goodfacts(plugins,tmp_path,forbidden):
    manager,uploads=migration_fixture(plugins,tmp_path)
    (tmp_path/'MEMORY.md').write_text(forbidden)
    (tmp_path/'USER.md').write_text('I research reasoning and quote <think> tags')
    assert manager.migrate_memory_files('fixture',str(tmp_path)) is True
    bodies=[kw['file'][1].decode() for kw in uploads]
    assert len(bodies)==1
    assert 'I research reasoning and quote <think> tags' in bodies[0]
    assert 'RAW_' not in json.dumps(bodies)
