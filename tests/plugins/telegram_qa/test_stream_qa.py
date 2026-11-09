"""Native stream uncertainty and complete ordinary delivery-family contracts."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig

spec = importlib.util.spec_from_file_location('qa_stream_rig', Path(__file__).with_name('test_ordinary_qa.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
native = h.native


@pytest.mark.asyncio
@pytest.mark.parametrize('family', ['legacy', 'chunks', 'rich', 'short', 'final', 'rich-edit', 'overflow'])
async def test_latest_only_across_delivery_families_and_restart(native, monkeypatch, family):
    a, s, bot = native
    a._telegram_chat_outbound_slot_secs = 0
    meta = {'thread_id': '71'}
    old = await a.send('101', 'Older ordinary', metadata=meta)
    preview = await a.send('101', 'Latest preview', metadata=meta)
    a._rich_messages_enabled = family in {'rich', 'rich-edit'}
    text = '- [x] Rich final' if a._rich_messages_enabled else ' '.join(f'part{i:03d}' for i in range(80)) if family in {'chunks', 'overflow'} else 'Current body'
    if family in {'chunks', 'overflow'}:
        a.MAX_MESSAGE_LENGTH = 140
    result = await a.send('101', text, metadata=meta) if family in {'legacy', 'chunks', 'rich'} else await a.edit_message('101', preview.message_id, text, finalize=family != 'short', metadata=meta)
    assert result.success
    ids = (result.raw_response or {}).get('message_ids') or [result.message_id]
    assert s.rows() == [(101, ('forum', 71), int(ids[-1]))]
    before = len(s.wire)
    late = await a.edit_message('101', old.message_id, 'Late old preview', finalize=True, metadata=meta)
    assert not late.success and len(s.wire) == before
    clone = h.make_adapter(monkeypatch, bot)
    clone._telegram_chat_outbound_slot_secs = 0
    current = await clone.send('101', 'After adapter restart', metadata=meta)
    assert current.success and s.rows() == [(101, ('forum', 71), int(current.message_id))]


@pytest.mark.asyncio
@pytest.mark.parametrize('origin', ['first', 'edit', 'overflow', 'commentary'])
@pytest.mark.parametrize('corruption', ['malformed', 'wrong-chat'])
async def test_native_consumer_fences_uncertain_receipt_without_confirming_or_resending(native, origin, corruption):
    a, s, _ = native
    a._telegram_chat_outbound_slot_secs = 0
    c = GatewayStreamConsumer(a, '101', StreamConsumerConfig(cursor=''), metadata={'thread_id': '71'})
    if origin in {'edit', 'overflow'}:
        assert await c._send_or_edit('Original preview')
    if origin == 'overflow':
        a.MAX_MESSAGE_LENGTH = 140
    s.corrupt_once('editMessageText' if origin == 'edit' else 'sendMessage',
                   (lambda r: b'{"ok":true,"result":') if corruption == 'malformed' else (lambda r: {**r, 'chat': {'id': 202}}))
    start = len(s.wire)
    body = ' '.join(f'content{i:03d}' for i in range(70)) if origin == 'overflow' else 'Possibly committed final body'
    if origin == 'commentary':
        c.on_commentary(body)
        c.on_commentary('Must not send after unknown commentary')
        c.on_segment_break()
    c.on_delta(body)
    c.finish()
    await c.run()
    mutations = [w for w in s.wire[start:] if w['endpoint'] in {'sendMessage', 'sendRichMessage', 'editMessageText'}]
    assert len(s.faults) == 1
    assert len(mutations) == (2 if origin == 'overflow' else 1)
    assert c.delivery_uncertain and not c.final_content_delivered and not c.final_response_sent


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['parse', 'pool', 'connect', 'flood', 'capability'])
async def test_proven_presubmit_rejections_keep_native_safe_retry(native, monkeypatch, kind):
    import httpx
    from telegram.error import NetworkError

    a, s, _ = native
    a._telegram_chat_outbound_slot_secs = 0
    a._rich_messages_enabled = kind == 'capability'
    attempts = []
    def before(endpoint, params):
        if endpoint not in {'sendMessage', 'sendRichMessage'}:
            return None
        attempts.append(endpoint)
        if len(attempts) != 1:
            return None
        if kind in {'pool', 'connect'}:
            try:
                raise (httpx.PoolTimeout if kind == 'pool' else httpx.ConnectTimeout)('pre-submit')
            except httpx.HTTPError as cause:
                raise NetworkError('typed pre-submit') from cause
        result = {'ok': False, 'description': "Can't parse entities" if kind == 'parse' else 'Unknown endpoint' if kind == 'capability' else 'Flood'}
        if kind == 'flood':
            result['parameters'] = {'retry_after': 1}
        return (400 if kind == 'parse' else 404 if kind == 'capability' else 429), json.dumps(result).encode()
    s.before = before
    original = asyncio.sleep
    async def yield_only(delay):
        await original(0)
    monkeypatch.setattr(asyncio, 'sleep', yield_only)
    result = await a._send_with_retry('101', '- [x] Rich retry' if kind == 'capability' else 'Safe native retry', max_retries=1, base_delay=0)
    assert result.success and len(attempts) == 2 and len(s.ledger) == 1 and len(s.rows()) == 1
