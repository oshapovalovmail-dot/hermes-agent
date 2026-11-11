"""Two preservation regressions, exercised at offline native wire boundaries."""
from copy import deepcopy
import importlib
import json

import httpx
import pytest

from test_honcho_sdk_egress import fixture


@pytest.mark.parametrize('max_chars', [64, 25000])
@pytest.mark.parametrize('boundary', [1, 2])
@pytest.mark.parametrize('offset', [-7, 0, 5])
@pytest.mark.parametrize('context', ['fence', 'inline'])
def test_honcho_logical_literal_context_survives_chunk_rechecks(
        plugins, max_chars, boundary, offset, context):
    h, _ = plugins
    opening = '  ```xml\n' if context == 'fence' else '  Code span: `quoted\n'
    closing = '\n```\n' if context == 'fence' else '\n`\n'
    tag_start = max_chars * boundary + offset
    literal = (opening + 'x' * (tag_start - len(opening) - 1)
               + '\n<think>literal</think>' + closing + '  End.\n  ')
    human = '  <think>human literal</think>\n  '
    raw = '<analysis>RAW_PREFIX</analysis>' + literal
    transcript = [{'role': 'user', 'content': human},
                  {'role': 'assistant', 'channel': 'final', 'content': raw}]
    original = deepcopy(transcript)
    manager, session, calls = fixture(plugins, fail_first=True)
    manager.resolve_author_peer_id = lambda *a: 'human'
    manager.get_or_create = lambda key, **kw: session
    manager._author_peer_for_session = lambda sdk, sid, peer: manager._get_or_create_peer(peer)
    provider = h.HonchoMemoryProvider()
    provider._config = h.HonchoClientConfig(write_frequency='session')
    if max_chars == 25000:
        assert provider._config.message_max_chars == 25000
    else:
        provider._config.message_max_chars = max_chars
    provider._session_key = 'fixture'
    provider._ready_or_kick_init = lambda: False
    provider.sync_turn(human, raw, messages=transcript)
    assert len(provider._pending_turns) == 1
    turn = provider._pending_turns[0]
    assert ''.join(row['content'] for row in turn[0] if row['role'] == 'assistant') == literal
    assert provider._write_pending_turn(manager, turn) is session
    manager.flush_all()  # First native request intentionally fails.
    manager.flush_all()  # Retry must revalidate the same logical content.
    manager.shutdown()
    assert len(calls) == 2
    for path, payload in calls:
        assert path == '/v3/workspaces/fixture-workspace/sessions/fixture-session/messages'
        sent = payload['messages']
        assert ''.join(m['content'] for m in sent if m['peer_id'] == 'human') == human
        assert ''.join(m['content'] for m in sent if m['peer_id'] == 'agent') == literal
        assert all(0 < len(m['content']) <= max_chars for m in sent)
        assert {m['peer_id'] for m in sent} == {'human', 'agent'}
        assert 'RAW_' not in json.dumps(payload)
    assert transcript == original


@pytest.mark.parametrize('provider', ['honcho', 'openviking'])
@pytest.mark.parametrize('opening, false_close, real_close', [
    ('```text', '```xml', '```'),
    ('~~~text', '~~~xml', '~~~'),
    ('```text', '```` not-a-close', '```` \t'),
    ('~~~~text', '~~~~~xml', '~~~~~\t '),
])
@pytest.mark.parametrize('raw_tail', ['<think>RAW_AFTER</think>', '<reasoning>RAW_UNCLOSED'])
def test_fence_info_suffix_is_literal_until_whitespace_only_close(
        plugins, provider, opening, false_close, real_close, raw_tail):
    h, v = plugins
    literal = ('  ' + opening + '\n' + false_close
               + '\n<think>literal</think>\n<analysis>unclosed literal\n'
               + real_close + '\n  End.\n')
    human = '  Human `<think>` quote.\n  '
    raw = '<thinking>RAW_PREFIX</thinking>' + literal + raw_tail
    rows = [{'role': 'user', 'content': human},
            {'role': 'assistant', 'channel': 'final', 'content': raw}]
    original = deepcopy(rows)
    if provider == 'honcho':
        build = importlib.import_module(h.__name__ + '.capture').build_capture_turn
        manager, session, calls = fixture(plugins)
        for row in build(human, raw, messages=rows):
            session.add_message(**row)
        manager.flush_all()
        manager.shutdown()
        assert len(calls) == 1
        assert calls[0][0] == '/v3/workspaces/fixture-workspace/sessions/fixture-session/messages'
        sent = calls[0][1]['messages']
        assert [m['peer_id'] for m in sent] == ['human', 'agent']
        assert [m['content'] for m in sent] == [human, literal]
        assert 'RAW_' not in json.dumps(calls)
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
        assert len(requests) == 1
        request = requests[0]
        assert request.url.path == '/api/v1/sessions/fixture-session/messages/batch'
        assert request.headers['X-OpenViking-Actor-Peer'] == 'fixture-agent'
        assert request.headers['X-OpenViking-Account'] == 'fixture-account'
        assert request.headers['X-OpenViking-User'] == 'fixture-user'
        payload = json.loads(request.content)
        sent = payload['messages']
        assert [m['peer_id'] for m in sent] == ['fixture-human', 'fixture-agent']
        assert [''.join(p['text'] for p in m['parts']) for m in sent] == [human, literal]
        assert 'RAW_' not in json.dumps(payload)
    assert rows == original


@pytest.mark.parametrize('entry', ['direct', 'legacy', 'changed_builder_row'])
def test_chunk_markers_do_not_authorize_raw_reasoning(plugins, entry):
    h, _ = plugins
    build = importlib.import_module(h.__name__ + '.capture').build_capture_turn
    manager, session, calls = fixture(plugins)
    unsafe = {'role': 'assistant', 'content': '<think>RAW_TAMPER</think>  final\n  ',
              '_capture_final': True}
    if entry == 'changed_builder_row':
        safe = build('human', '```xml\n<think>literal</think>\n```')[-1]
        unsafe = {**safe, **unsafe}
    if entry == 'legacy':
        session.messages.extend([{'role': 'user', 'content': 'human'}, unsafe])
    else:
        session.add_message('user', 'human')
        session.add_message(**unsafe)
    manager.flush_all()
    manager.shutdown()
    sent = calls[-1][1]['messages']
    assert [m['content'] for m in sent] == ['human', '  final\n  ']
    assert [m['peer_id'] for m in sent] == ['human', 'agent']
    assert 'RAW_' not in json.dumps(calls)
