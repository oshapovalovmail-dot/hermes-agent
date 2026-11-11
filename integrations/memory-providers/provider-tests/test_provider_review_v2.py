"""Review regressions at native SDK/HTTP serialization, never a live backend."""
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest
from honcho.peer import Peer
from honcho.session import Session

from test_honcho_sdk_egress import fixture
from test_provider_egress import migration_fixture


LITERALS = [
    'Literal: `<think>example</think>`',
    'A multiline code span: `quoted\n<think>literal</think>\n` ends here.',
    'Use this XML example:\n```xml\n<think>literal</think>\n```\nEnd.',
    'The opening tag is `<think>`; the rest of this final answer is technical content.',
    '> <analysis>quoted example</analysis>\nUseful prose about reasoning.',
    '~~~xml\n<reasoning>unclosed literal\n~~~\nEnd.',
    'Literal: "<thinking>example</thinking>"; reasoning is a technical subject.',
]


@pytest.mark.parametrize('provider', ['honcho', 'openviking'])
@pytest.mark.parametrize('literal', LITERALS)
@pytest.mark.parametrize('prefix', ['', '<think>RAW_PRIVATE_REASON</think>'])
def test_final_literals_survive_native_serialization(plugins, provider, literal, prefix):
    h, v = plugins
    rows = [{'role': 'user', 'content': 'human'},
            {'role': 'assistant', 'channel': 'final', 'content': prefix + literal}]
    original = deepcopy(rows)
    if provider == 'honcho':
        build = importlib.import_module(h.__name__ + '.capture').build_capture_turn
        manager, session, calls = fixture(plugins)
        for row in build('human', prefix + literal, messages=rows):
            session.add_message(**row)
        manager.flush_all()
        sent = calls[-1][1]['messages']
        assert [m['peer_id'] for m in sent] == ['human', 'agent']
        actual = sent[-1]['content']
        assert calls[-1][0] == '/v3/workspaces/fixture-workspace/sessions/fixture-session/messages'
    else:
        requests = []
        def receive(request):
            requests.append(request)
            return httpx.Response(200, json={'status': 'ok', 'result': {}})
        with httpx.Client(transport=httpx.MockTransport(receive)) as transport:
            client = v._VikingClient('http://offline.invalid', account='fixture-account',
                                     user='fixture-user', agent='fixture-agent', extra_headers={})
            client._httpx = transport
            batch = v.OpenVikingMemoryProvider._messages_to_openviking_batch(
                rows, assistant_peer_id='fixture-agent', user_peer_id='fixture-human')
            upload = v._TurnUpload(client, 'fixture-session', batch, 'RAW_SCALAR', 'RAW_SCALAR',
                                   'fixture-agent', 'fixture-human')
            assert upload.run() is client
            assert upload.next_index == 2
        assert requests
        request = requests[-1]
        assert request.url.path.startswith('/api/v1/sessions/fixture-session/messages')
        assert request.headers['X-OpenViking-Actor-Peer'] == 'fixture-agent'
        assert request.headers['X-OpenViking-Account'] == 'fixture-account'
        assert request.headers['X-OpenViking-User'] == 'fixture-user'
        payload = json.loads(request.content)
        sent = payload.get('messages', [payload])
        actual = ''.join(p['text'] for p in sent[-1]['parts'])
        assert sent[-1]['peer_id'] == 'fixture-agent'
    assert actual == literal
    assert 'RAW_' not in actual
    assert rows == original


def native_migration(plugins, tmp_path):
    manager, _ = migration_fixture(plugins, tmp_path)
    uploads = []
    def upload(path, *, files, data):
        uploads.append((path, deepcopy(files), deepcopy(data)))
        return []
    binding = SimpleNamespace(workspace_id='fixture-workspace', _ensure_workspace=lambda: None,
                              _http=SimpleNamespace(upload=upload))
    sdk = Session('fixture-session', binding)
    manager._sessions_cache['fixture-session'] = sdk
    manager._sdk_session = lambda sid: sdk
    manager._get_or_create_peer = lambda name: Peer(name, binding)
    return manager, uploads


@pytest.mark.parametrize('raw', [
    '<think>RAW_ONE</think><think>RAW_TWO</think>',
    '<think>\nRAW_ONE\n</think><analysis>RAW_TWO</analysis>\n',
    '<analysis>RAW_ONE</analysis><thinking>RAW_TWO</thinking>Curated suffix.\n',
])
def test_adjacent_import_envelopes_rescan_suffix_in_native_upload(plugins, tmp_path, raw):
    manager, uploads = native_migration(plugins, tmp_path)
    literal = '\n```xml\n<think>quoted technical example</think>\n```\n> <analysis>quoted</analysis>\n'
    (tmp_path / 'MEMORY.md').write_text('Curated prefix.\n' + raw + literal)
    assert manager.migrate_memory_files('fixture', str(tmp_path))
    assert len(uploads) == 1
    path, files, data = uploads[0]
    assert path == '/v3/workspaces/fixture-workspace/sessions/fixture-session/messages/upload'
    assert data['peer_id'] == 'human'
    text = files['file'][1].decode()
    assert 'RAW_' not in text
    assert 'Curated prefix.' in text
    assert literal in text
    if 'Curated suffix.' in raw:
        assert 'Curated suffix.' in text


@pytest.mark.parametrize('kind', ['reasoning', 'thinking', 'redacted_thinking', 'analysis', 'reasoning_content', 'summary_text'])
@pytest.mark.parametrize('container', ['bare', 'list', 'messages'])
def test_typed_import_reasoning_is_not_curated_prose_at_native_upload(plugins, tmp_path, kind, container):
    manager, uploads = native_migration(plugins, tmp_path)
    record = {'type': kind, 'text': 'RAW_IMPORT_REASON', 'thinking': 'RAW_IMPORT_THINK'}
    value = record if container == 'bare' else [record] if container == 'list' else {'messages': [record]}
    (tmp_path / 'MEMORY.md').write_text(json.dumps(value))
    (tmp_path / 'USER.md').write_text('I research reasoning and quote `<think>` tags.')
    assert manager.migrate_memory_files('fixture', str(tmp_path))
    assert len(uploads) == 1
    path, files, data = uploads[0]
    assert path.endswith('/fixture-session/messages/upload')
    assert data['peer_id'] == 'human'
    assert files['file'][0] == 'user_profile.md'
    assert 'RAW_' not in files['file'][1].decode()
    assert 'I research reasoning and quote `<think>` tags.' in files['file'][1].decode()


def test_message_wrapper_import_excludes_typed_service_not_human_quotes(plugins, tmp_path):
    manager, uploads = native_migration(plugins, tmp_path)
    value = {'messages': [
        {'role': 'user', 'source_kind': 'runtime_notification', 'content': 'RAW_IMPORT_SERVICE'},
        {'role': 'assistant', 'content': 'RAW_DERIVED'},
        {'role': 'user', 'content': 'Human quote: <think>literal</think>'},
        {'role': 'assistant', 'channel': 'final', 'content': 'Literal: `<think>example</think>`'},
    ]}
    (tmp_path / 'MEMORY.md').write_text(json.dumps(value))
    assert manager.migrate_memory_files('fixture', str(tmp_path))
    assert len(uploads) == 1
    text = uploads[0][1]['file'][1].decode()
    assert 'RAW_' not in text
    assert 'Human quote: <think>literal</think>' in text
    assert 'Literal: `<think>example</think>`' in text


@pytest.mark.parametrize('supplied', ['human', 'agent', 'caller-other-peer'])
def test_canonical_author_field_cannot_override_resolved_turn_binding(plugins, supplied):
    h, _ = plugins
    manager, session, calls = fixture(plugins)
    manager.resolve_author_peer_id = lambda *a: 'human'
    manager.get_or_create = lambda key, **kw: session
    manager._author_peer_for_session = lambda sdk, sid, peer: manager._get_or_create_peer(peer)
    build = importlib.import_module(h.__name__ + '.capture').build_capture_turn
    rows = [{'role': 'user', 'content': 'human', 'author_peer_id': supplied},
            {'role': 'assistant', 'content': 'final', 'author_peer_id': supplied}]
    capture = build('human', 'final', messages=rows)
    original = deepcopy(capture)
    provider = h.HonchoMemoryProvider()
    provider._config = h.HonchoClientConfig()
    assert provider._write_pending_turn(manager, (capture, {}, 'fixture')) is session
    manager.flush_all()
    sent = calls[-1][1]['messages']
    assert [m['peer_id'] for m in sent] == ['human', 'agent']
    assert [m['content'] for m in sent] == ['human', 'final']
    assert capture == original
