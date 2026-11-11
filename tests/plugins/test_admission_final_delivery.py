"""Admission identity must not become a Telegram reply, nor uncertainty a retry grant.

Real authority/runner/Telegram adapter and PTB serializer; only model HTTP and
Bot API transport are fixtures. All durable state belongs to tmp_path.
"""
import asyncio
from contextlib import asynccontextmanager
from http.server import ThreadingHTTPServer
import json
import threading
import time
from types import SimpleNamespace

import pytest
pytest.importorskip('telegram')
from telegram import Message
from telegram.ext import ExtBot
from telegram.request import BaseRequest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import _reply_anchor_for_event, _thread_metadata_for_event
from gateway.platforms.event import MessageType
from gateway.session_authority import SessionAuthority, initialize_session_authority
from gateway.session_contract import SessionActor, SessionRef, Submission
from gateway.session_ingress_context import native_callback, register_transport_home
from hermes_state_runtime import get_session_admission
from plugins.platforms.telegram.adapter import TelegramAdapter
from tests.gateway.fixtures.shared_authority_peer import ModelPeer


class BotWire(BaseRequest):
    def __init__(self):
        self.calls = []
        self.committed = []
        self.fault = None

    @property
    def read_timeout(self):
        return 1

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit('/', 1)[-1]
        body = dict(request_data.parameters) if request_data else {}
        self.calls.append((endpoint, body))
        if endpoint == 'getMe':
            result = {'id': 987654321, 'is_bot': True, 'first_name': 'Fixture', 'username': 'fixture_bot'}
        elif endpoint in {'sendMessage', 'editMessageReplyMarkup'}:
            if endpoint == 'sendMessage':
                if self.fault == 'reject':
                    return 403, b'{"ok":false,"error_code":403,"description":"Forbidden: bot was blocked by the user"}'
                self.committed.append(body)
                if self.fault == 'lost_ack':
                    # Server accepted the content, but PTB cannot decode its response.
                    return 200, b'{"ok":true,"result":'
                if self.fault == 'cancel_after_commit':
                    raise asyncio.CancelledError()
            result = {'message_id': body.get('message_id', 1000 + len(self.committed)),
                      'date': 1800000000, 'chat': {'id': int(body['chat_id']), 'type': 'private'},
                      'text': body.get('text', '')}
        else:
            assert endpoint == 'sendChatAction', endpoint
            result = True
        return 200, json.dumps({'ok': True, 'result': result}).encode()


@asynccontextmanager
async def telegram(monkeypatch, tmp_path, *, qa=True):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token='987654321:fixture', typing_indicator=False,
        extra={'reply_keyboard': {'mode': 'inline', 'chat_ids': ['101'], 'rows': [['статус?']]}} if qa else {}))
    wire = BotWire()
    adapter._bot = ExtBot('987654321:fixture', request=wire, get_updates_request=BotWire())
    await adapter._bot.initialize()
    try:
        yield adapter, wire
    finally:
        await adapter._bot.shutdown()


def native_event(adapter, *, thread='71', chat_type='private'):
    raw = {'message_id': 427220, 'date': 1800000000,
           'from': {'id': 101, 'is_bot': False, 'first_name': 'Human'},
           'chat': {'id': 101, 'type': chat_type}, 'text': 'NATIVE',
           **({'message_thread_id': int(thread), 'is_topic_message': True} if thread else {})}
    return adapter._build_message_event(Message.de_json(raw, adapter._bot), MessageType.TEXT)


def ledger_rows():
    from gateway import delivery_ledger as ledger
    with ledger._connect() as conn:
        return [dict(zip(('id', 'state', 'last_error', 'content'), row)) for row in conn.execute(
            'SELECT obligation_id,state,last_error,content FROM delivery_obligations ORDER BY created_at')]


def assert_no_replay(monkeypatch, wire):
    from gateway import delivery_ledger as ledger
    count = len(wire.committed)
    due = time.time() + 300  # due for retry, but NOT old enough to be abandoned
    assert ledger.sweep_failed_for_runtime('telegram', now=due) == []
    # A restarted owner must not reinterpret an unknown receipt as a failed send.
    with monkeypatch.context() as dead:
        dead.setattr(ledger, '_owner_alive', lambda *a: False)
        assert ledger.sweep_recoverable(now=due) == []
    assert len(wire.committed) == count


@pytest.mark.asyncio
@pytest.mark.parametrize('qa,fault', [(True, None), (False, None), (True, 'lost_ack')],
                         ids=['qa-tail', 'native-no-qa', 'qa-uncertain-ack'])
async def test_operator_recovery_keeps_native_reply_identity(monkeypatch, tmp_path, qa, fault):
    from gateway.run import GatewayRunner
    home = tmp_path / 'state'
    home.mkdir()
    peer = ThreadingHTTPServer(('127.0.0.1', 0), ModelPeer)
    peer.requests, peer.metadata_requests = [], []
    peer.blocked, peer.release = threading.Event(), threading.Event()
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{peer.server_port}/v1'
    monkeypatch.setenv('OPENAI_API_KEY', 'owned-loopback-fixture')
    monkeypatch.setenv('OPENAI_BASE_URL', base)
    monkeypatch.setenv('TELEGRAM_ALLOWED_USERS', '101')
    monkeypatch.setenv('TELEGRAM_HOME_CHANNEL', '101')
    cfg = {'model': {'provider': 'custom', 'default': 'local-wire-stub', 'base_url': base},
           'auxiliary': {'title_generation': {'enabled': False}},
           'platform_toolsets': {'telegram': []}, 'terminal': {'cwd': str(home)},
           'display': {'streaming': False, 'tool_progress': False}}
    (home / 'config.yaml').write_text(json.dumps(cfg))
    monkeypatch.setattr(SessionAuthority, '_schedule', lambda self, ref: None)
    async with telegram(monkeypatch, home, qa=qa) as (adapter, wire):
        runner = GatewayRunner(GatewayConfig(sessions_dir=home / 'sessions'))
        from hermes_state import SessionDB
        runner.session_store._db = runner._session_db = SessionDB(home / 'state.db')
        runner.adapters[Platform.TELEGRAM] = adapter
        runner._wire_adapter_handlers(adapter)
        register_transport_home(runner, None, home)
        authority = await initialize_session_authority(runner, profile_id='default', instance_id='first')
        seen = []
        original = runner._handle_message

        async def observe(event):
            seen.append(event)
            return await original(event)
        monkeypatch.setattr(runner, '_handle_message', observe)
        try:
            human = native_event(adapter)
            with native_callback(runner, human, home):
                native = await authority.admit_native(human)
            ref = native.ref
            await asyncio.wait_for(authority._drain(ref), 60)
            assert get_session_admission(authority.db, admission_id=native.admission_id)['outcome'] == 'completed'
            assert peer.requests, 'Real inference transport was not exercised'
            assert len(wire.committed) == 1, wire.calls
            assert wire.committed[0]['reply_parameters']['message_id'] == 427220
            # Queue authenticated operator work, then recreate the owner before execution.
            actor = SessionActor('authenticated-operator', 'default', frozenset({'session:submit', 'session:read', 'session:operator'}), 'viewer')
            receipt = await authority.submit(actor, Submission('operator-1', ref,
                {'text': 'OPERATOR', 'api_text': 'OPERATOR_API'}, 'queue'))
            queued = get_session_admission(authority.db, admission_id=receipt.admission_id)
            assert queued['payload']['local_operator_v1']['principal_id'] == actor.subject
            cold = await initialize_session_authority(runner, profile_id='default', instance_id='second')
            assert await cold.recover_native_sessions([(ref.session_id, human.source, adapter)]) == {ref.session_id: 'ready'}
            wire.fault = fault
            await asyncio.wait_for(cold._drain(ref), 60)
            row = get_session_admission(cold.db, admission_id=receipt.admission_id)
            assert (row['status'], row['outcome']) == ('terminal', 'completed')
            assert len(peer.requests) == 2, peer.requests
            assert 'OPERATOR_API' in json.dumps(peer.requests[-1]['messages'][-1])
            assert len(wire.committed) == 2, {'calls': wire.calls, 'ledger': ledger_rows()}
            operator_event = seen[-1]
            assert operator_event.message_id == receipt.admission_id  # existing execution scope handle
            assert operator_event.ledger_message_id == receipt.admission_id
            assert operator_event.reply_anchor_override == '427220'
            assert _reply_anchor_for_event(operator_event) == '427220'
            send = wire.committed[-1]
            assert send['chat_id'] == 101
            assert send['reply_parameters']['message_id'] == 427220
            assert send.get('message_thread_id') == 71
            assert 'direct_messages_topic_id' not in send
            expected_state = 'unknown' if fault else 'delivered'
            assert [entry['state'] for entry in ledger_rows()] == ['delivered', expected_state]
            assert not cold.pending_deliveries
            # A second boot drains neither admission nor delivery again.
            again = await initialize_session_authority(runner, profile_id='default', instance_id='third')
            assert await again.recover_native_sessions([(ref.session_id, human.source, adapter)]) == {ref.session_id: 'ready'}
            await asyncio.wait_for(again._drain(ref), 10)
            assert len(wire.committed) == len(peer.requests) == 2
            # Delivery uncertainty must not rewrite execution cancellation/unknown semantics.
            cancelled = await again.submit(actor, Submission('cancelled', ref, {'text': 'CANCELLED'}, 'queue'))
            await again.cancel_queued(actor, ref, cancelled.admission_id)
            lost = await again.submit(actor, Submission('lost-started', ref, {'text': 'UNKNOWN'}, 'queue'))
            from hermes_state_runtime import claim_session_input
            claimed = claim_session_input(again.db, epoch=again.epoch, session_id=ref.session_id)
            assert claimed['admission_id'] == lost.admission_id
            fourth = await initialize_session_authority(runner, profile_id='default', instance_id='fourth')
            assert await fourth.recover_native_sessions([(ref.session_id, human.source, adapter)]) == {ref.session_id: 'unknown_execution'}
            await asyncio.wait_for(fourth._drain(ref), 10)
            assert get_session_admission(fourth.db, admission_id=cancelled.admission_id)['outcome'] == 'cancelled'
            assert get_session_admission(fourth.db, admission_id=lost.admission_id)['status'] == 'unknown'
            assert len(wire.committed) == len(peer.requests) == 2
            assert_no_replay(monkeypatch, wire)
            print(json.dumps({'native_admission': native.admission_id, 'operator_admission': receipt.admission_id,
                'operator_execution_id': operator_event.message_id, 'reply_anchor': _reply_anchor_for_event(operator_event),
                'wire_reply': send['reply_parameters'], 'wire_thread': send.get('message_thread_id'), 'ledger': ledger_rows()}))
        finally:
            # Runtime workers/reapers are not installed; close only this runner's state.
            runner.session_store.close_all_db_handles()
            peer.shutdown()
            peer.server_close()
            thread.join(10)


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['before-send', 'lost_ack', 'cancel_after_commit'])
async def test_final_send_unknown_is_finalized_without_retry_grant(monkeypatch, tmp_path, fault):
    async with telegram(monkeypatch, tmp_path) as (adapter, wire):
        event = native_event(adapter)
        schedules = []
        adapter.gateway_runner = SimpleNamespace(_schedule_flood_redelivery=lambda *a, **k: schedules.append((a, k)))
        wire.fault = fault
        # An invalid anchor fails in the real QA preflight, before transport dispatch.
        reply = 'not-a-platform-id' if fault == 'before-send' else event.message_id
        metadata = _thread_metadata_for_event(event)
        if fault == 'before-send':
            with pytest.raises(ValueError):
                await adapter.send_final_ledgered(event, 'owned-lane', 'ANSWER', metadata, reply_to=reply)
        elif fault == 'cancel_after_commit':
            with pytest.raises(asyncio.CancelledError):
                await adapter.send_final_ledgered(event, 'owned-lane', 'ANSWER', metadata, reply_to=reply)
        else:
            result, _ = await adapter.send_final_ledgered(event, 'owned-lane', 'ANSWER', metadata, reply_to=reply)
            assert result.delivery_uncertain and not result.success
        rows = ledger_rows()
        assert len(rows) == 1
        assert rows[0]['state'] == 'unknown', rows
        assert rows[0]['last_error'], rows
        assert len(wire.committed) == int(fault != 'before-send')
        assert not schedules
        assert_no_replay(monkeypatch, wire)
        print(json.dumps({'fault': fault, 'ledger': rows, 'committed': len(wire.committed)}))


@pytest.mark.asyncio
@pytest.mark.parametrize('fault,state', [(None, 'delivered'), ('reject', 'failed')])
async def test_final_send_positive_and_definitive_rejection_controls(monkeypatch, tmp_path, fault, state):
    async with telegram(monkeypatch, tmp_path) as (adapter, wire):
        event = native_event(adapter)
        wire.fault = fault
        result, owner = await adapter.send_final_ledgered(event, 'owned-lane', 'ANSWER',
            _thread_metadata_for_event(event), reply_to=event.message_id)
        assert owner is adapter
        assert result.success is (fault is None)
        assert ledger_rows()[0]['state'] == state
        assert not result.delivery_uncertain


@pytest.mark.asyncio
@pytest.mark.parametrize('platform,chat_type,thread,anchor,expected', [
    (Platform.TELEGRAM, 'dm', '71', None, ''),
    (Platform.TELEGRAM, 'forum', '71', '427220', ''),
    (Platform.TELEGRAM, 'dm', None, '427220', '427220'),
    (Platform.SLACK, 'group', 'native-thread', '427220.1', '427220.1'),
    (Platform.FEISHU, 'group', 'native-thread', 'om-native', 'om-native'),
])
async def test_operator_sibling_routes_keep_execution_scopes_and_platform_anchors(
        monkeypatch, tmp_path, platform, chat_type, thread, anchor, expected):
    from gateway.session import SessionSource
    from gateway.session_cli_turn import cli_turn
    from tests.gateway.test_surface_admission import _authority
    seen = []

    async def answer(event):
        seen.append((event, cli_turn(event.message_id)))
        return 'ok'
    authority = await _authority(tmp_path, monkeypatch, answer)
    authority.sessions['s'].source = SessionSource(platform=platform, chat_id='c', chat_type=chat_type,
        thread_id=thread, message_id=anchor, user_id='operator')
    actor = SessionActor('operator', 'p', frozenset({'session:submit'}), 'viewer')
    try:
        receipt = await authority.submit(actor, Submission('operator', SessionRef('p', 's'),
            {'text': 'question', 'api_text': 'API question'}, 'queue'))
        await authority.sessions['s'].task
        [(event, fields)] = seen
        assert event.message_id == event.ledger_message_id == receipt.admission_id
        assert event.reply_anchor_override == expected
        assert _reply_anchor_for_event(event) == expected
        assert fields == {'api_text': 'API question'}
    finally:
        authority.db.close()
