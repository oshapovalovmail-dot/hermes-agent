"""Native Telegram receipts through modern gateway consumer/reconciliation boundaries.

Only the remote Bot API and agent are replaced. The PTB Bot/ExtBot, adapter,
consumer, TurnContext and GatewayRunner delivery decisions are production code.
"""
import asyncio
import importlib.util
import json
import os
import tempfile
import sys
import types
from pathlib import Path

import pytest
from unittest.mock import Mock

# tests/gateway/conftest installs optional SDK stubs before collection. This
# native transport lane requires the installed PTB instead, never those stubs.
for _name, _module in list(sys.modules.items()):
    if (_name == 'telegram' or _name.startswith('telegram.')) and isinstance(_module, Mock):
        del sys.modules[_name]
pytest.importorskip("telegram", reason="Native QA tests require the optional Telegram SDK")
from telegram import Bot
from telegram.error import NetworkError
assert Bot.__module__ == 'telegram._bot'


from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig
from gateway.turn_context import TurnContext


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_h = _load('native_gateway_receipts', Path(__file__).parents[1] / 'plugins/telegram_qa/test_ordinary_qa.py')
_r = _load('native_gateway_runner', Path(__file__).with_name('test_stale_finalize_suppression.py'))
native = _h.native


def test_canonical_child_isolation_receipt(tmp_path, record_property):
    home = Path(os.environ['HOME']).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    child_temp = Path(os.environ['PYTEST_DEBUG_TEMPROOT']).resolve()
    receipt = {'home': str(home), 'hermes_home': os.environ['HERMES_HOME'],
               'tempfile': str(temp), 'tmp_path': str(tmp_path),
               'child_temp': str(child_temp), 'file_retries': os.environ.get('HERMES_TEST_FILE_RETRIES')}
    record_property('isolation', json.dumps(receipt, sort_keys=True))
    assert temp == child_temp and tmp_path.resolve().is_relative_to(child_temp)
    assert not Path(os.environ['HERMES_HOME']).resolve().is_relative_to(home / '.hermes')
    # The canonical CLI owns retry policy; its children need not receive the env alias.
    if receipt['file_retries'] is not None:
        assert receipt['file_retries'] == '0'


def _source():
    return SessionSource(platform=Platform.TELEGRAM, chat_id='101', chat_type='group', thread_id='71')


@pytest.mark.asyncio
@pytest.mark.parametrize('producer', ['fresh-final', 'fallback', 'segment-tail', 'split-head'])
async def test_all_additional_business_producers_retain_turn_uncertainty(native, producer):
    adapter, server, _ = native
    consumer = GatewayStreamConsumer(adapter, '101', StreamConsumerConfig(cursor=''), metadata={'thread_id': '71'})
    if producer in {'fresh-final', 'fallback', 'segment-tail'}:
        assert await consumer._send_or_edit('Confirmed preview')
    start = len(server.wire)
    server.corrupt_once('sendMessage', lambda receipt: NetworkError('postcommit parse retry after'))
    if producer == 'fresh-final':
        assert not await consumer._try_fresh_final('Unknown fresh final')
    elif producer == 'fallback':
        consumer._enter_fallback_mode('Confirmed preview')
        await consumer._send_fallback_final('Confirmed preview plus unknown tail')
    elif producer == 'segment-tail':
        consumer._accumulated = 'Confirmed preview plus unknown segment tail'
        consumer._enter_fallback_mode('Confirmed preview')
        await consumer._flush_segment_tail_on_edit_failure()
    else:
        await consumer._send_new_chunk('Unknown sealed head', None)
    consumer._reset_segment_state()
    consumer.on_commentary('Must not send commentary after unknown receipt')
    consumer.on_delta('Must not resend final after unknown receipt')
    consumer.finish()
    await consumer.run()
    mutations = [w for w in server.wire[start:] if w['endpoint'] in {'sendMessage', 'editMessageText'}]
    assert len(server.faults) == 1 and len(mutations) == 1
    assert consumer.delivery_uncertain
    assert not consumer.final_response_sent and not consumer.final_content_delivered
    assert not consumer.delivered_final_matches('Must not resend final after unknown receipt')


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['first', 'retry'])
@pytest.mark.parametrize('error', ['postcommit parse failure', 'postcommit retry after', 'Invalid server response'])
async def test_base_sender_typed_uncertainty_precedes_string_retry_and_plain_fallback(native, monkeypatch, phase, error):
    adapter, server, _ = native
    attempts = []
    def before(endpoint, params):
        if endpoint != 'sendMessage':
            return None
        attempts.append(params)
        if phase == 'retry' and len(attempts) == 1:
            return 429, json.dumps({'ok': False, 'description': 'Flood', 'parameters': {'retry_after': 1}}).encode()
    server.before = before
    server.corrupt_once('sendMessage', lambda receipt: NetworkError(error))
    original_sleep = asyncio.sleep
    async def yield_only(delay):
        await original_sleep(0)
    monkeypatch.setattr(asyncio, 'sleep', yield_only)
    result = await adapter._send_with_retry('101', 'One committed body', metadata={'thread_id': '71'}, max_retries=2, base_delay=0)
    assert result.delivery_uncertain and not result.success
    assert len(attempts) == (2 if phase == 'retry' else 1)
    assert len(server.faults) == 1 and len(server.ledger) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('metadata', [True, False])
@pytest.mark.parametrize('outcome', ['success', 'rejected', 'uncertain'])
async def test_transformed_final_uses_real_receipt_and_native_topic_metadata(native, metadata, outcome):
    adapter, server, _ = native
    runner = _r._make_runner(adapter)
    source = _source()
    consumer = GatewayStreamConsumer(adapter, '101', StreamConsumerConfig(cursor=''), metadata={'thread_id': '71'})
    assert await consumer._send_or_edit('Original streamed body')
    if not metadata:
        consumer.metadata = None
    final = 'Original streamed body with required transformed suffix'
    if outcome == 'rejected':
        server.before = lambda endpoint, params: (400, b'{"ok":false,"description":"Bad Request: fixture rejection"}') if endpoint == 'editMessageText' else None
    elif outcome == 'uncertain':
        server.corrupt_once('editMessageText', lambda receipt: b'{"ok":true,"result":')
    response = {'final_response': final, 'response_transformed': True}
    context = TurnContext(source=source, session_key='native-reconcile', stream_consumer_holder=[consumer])
    start = len(server.wire)
    await runner._run_agent_mark_streamed_delivery(response, context)
    edits = [w for w in server.wire[start:] if w['endpoint'] == 'editMessageText']
    assert edits and edits[0]['params']['text'] == final
    assert bool(response.get('already_sent')) == (outcome == 'success')
    assert bool(response.get('delivery_uncertain')) == (outcome == 'uncertain')
    if outcome != 'rejected':
        assert server.ledger[(101, int(consumer.message_id))]['text'] == final
    event = MessageEvent(text='Question', message_type=MessageType.TEXT, source=source)
    delivered = await runner._hmwa_deliver_turn_response(
        event, source, types.SimpleNamespace(session_id='native-reconcile'), 'native-reconcile', None,
        response, [], final, None, False)
    assert delivered == (final if outcome == 'rejected' else None)
    if delivered:
        server.before = None
        sent = await adapter._send_with_retry('101', delivered, metadata={'thread_id': '71'})
        assert sent.success
        assert len([p for p in server.ledger.values() if p.get('text') == final]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('uncertain', [True, False])
async def test_real_interim_callback_previewed_final_never_replays_unknown_commentary(native, monkeypatch, tmp_path, uncertain):
    import gateway.run as gateway_run

    adapter, server, _ = native
    runner = _r._make_runner(adapter)
    runner._draining = False
    (tmp_path / 'config.yaml').write_text('display:\n  tool_progress: off\n  interim_assistant_messages: true\n')
    monkeypatch.setattr(gateway_run, '_hermes_home', tmp_path)
    monkeypatch.setattr(gateway_run, '_resolve_runtime_agent_kwargs', lambda: {'api_key': 'offline-fixture'})
    body = 'Completed answer through native interim callback'
    if uncertain:
        server.corrupt_once('sendMessage', lambda receipt: b'{"ok":true,"result":')
    class Agent:
        def __init__(self, **kwargs):
            self.stream_delta_callback = kwargs.get('stream_delta_callback')
            self.tools = []
            self.interim_assistant_callback = None
        def run_conversation(self, message, conversation_history=None, task_id=None):
            assert callable(self.interim_assistant_callback)
            self.interim_assistant_callback(body, already_streamed=False)
            return {'final_response': body, 'response_previewed': True, 'messages': [], 'api_calls': 1}
    module = types.ModuleType('run_agent')
    module.AIAgent = Agent
    monkeypatch.setitem(sys.modules, 'run_agent', module)
    result = await asyncio.wait_for(runner._run_agent(
        message='Offline question', context_prompt='', history=[], source=_source(),
        session_id='native-interim', session_key='agent:main:telegram:group:101:71'), timeout=15)
    sends = [w for w in server.wire if w['endpoint'] == 'sendMessage']
    assert len(sends) == 1 and sends[0]['params']['text'] == body
    assert len(server.ledger) == 1 and len(server.faults) == int(uncertain)
    assert bool(result.get('delivery_uncertain')) == uncertain
    assert bool(result.get('already_sent')) == (not uncertain)
    event = MessageEvent(text='Question', message_type=MessageType.TEXT, source=_source())
    delivered = await runner._hmwa_deliver_turn_response(
        event, _source(), types.SimpleNamespace(session_id='native-interim'), 'native-interim', None,
        result, [], body, None, False)
    assert delivered is None
