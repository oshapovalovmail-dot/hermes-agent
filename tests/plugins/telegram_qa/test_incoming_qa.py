"""Accepted input retires ordinary controls before native batching/business.

Real adapter, native DTOs, Bot and ExtBot; only external transport/business are fake.
"""
import asyncio
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

import pytest
import pytest_asyncio
telegram = pytest.importorskip("telegram", reason="Native QA tests require the optional Telegram SDK")
from telegram import Bot, Message, Update
from telegram.error import TimedOut
from telegram.ext import ExtBot

from gateway.config import Platform
from gateway.run import GatewayRunner

_spec = importlib.util.spec_from_file_location('incoming_native_server', Path(__file__).with_name('test_ordinary_qa.py'))
assert _spec is not None and _spec.loader is not None
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


class IncomingServer(h.Server):
    def __init__(self):
        super().__init__()
        self.slow_boundaries = []
        self.enqueue_boundaries = []
        self.file_calls = []
        self.check_boundary = None

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit('/', 1)[-1]
        if endpoint in {'getFile', 'setMyCommands'} or method == 'GET':
            self.file_calls.append(endpoint)
            if self.check_boundary:
                self.slow_boundaries.append(self.check_boundary())
            if method == 'GET':
                return 200, PNG
            result = True if endpoint == 'setMyCommands' else {
                'file_id': 'fixture-file', 'file_unique_id': 'fixture-unique',
                'file_size': len(PNG), 'file_path': 'fixtures/image.png'}
            return 200, json.dumps({'ok': True, 'result': result}).encode()
        return await super().do_request(url, method, request_data=request_data, **kwargs)


@pytest_asyncio.fixture(params=[Bot, ExtBot], ids=['Bot', 'ExtBot'])
async def incoming(request, monkeypatch, tmp_path):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home'))
    s = IncomingServer()
    async with request.param('123:offline', request=s, get_updates_request=IncomingServer()) as bot:
        a = h.make_adapter(monkeypatch, bot)
        # Native policy settings, not mocked authorization or routing.
        a.config.extra['allow_from'] = ['101']
        a.config.extra['group_allow_from'] = ['101']
        a.config.extra['require_mention'] = False
        a._text_batch_delay_seconds = 0.01
        a._text_batch_split_delay_seconds = 0.02
        a._media_batch_delay_seconds = 0.01
        a.MEDIA_GROUP_WAIT_SECONDS = 0.01
        yield a, s, bot
        tasks = set(a._background_tasks)
        for attr in ['_pending_text_batch_tasks', '_pending_photo_batch_tasks', '_media_group_tasks']:
            tasks.update(getattr(a, attr).values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        h.save_evidence(tmp_path, 'incoming-wire.json', {
            'wire': s.wire, 'rows': s.rows(), 'faults': s.faults,
            'slow_boundaries': s.slow_boundaries, 'enqueue_boundaries': s.enqueue_boundaries,
            'file_calls': s.file_calls, 'sdk': type(bot).__name__,
        })



def update(bot, kind='text', *, thread=71, chat=101, caller=101, forum=False, direct=None, topic=True, mid=800, text=None, reply=None):
    raw = {'message_id': mid, 'date': 1, 'chat': {'id': chat, 'type': 'supergroup' if forum else 'private', 'is_forum': forum},
           'from': {'id': caller, 'first_name': 'User', 'is_bot': False}}
    if thread is not None:
        raw['message_thread_id'] = thread
        raw['is_topic_message'] = topic
    if direct is not None:
        raw['direct_messages_topic'] = {'topic_id': direct}
    if reply is not None:
        raw['reply_to_message'] = reply
    if kind in {'text', 'command', 'long-command'}:
        raw['text'] = text if text is not None else ('/status' if kind == 'command' else '/queue ' + 'x' * 4000 if kind == 'long-command' else 'New user input')
    elif kind == 'location':
        raw['location'] = {'latitude': 55.75, 'longitude': 37.62}
    elif kind == 'venue':
        raw['venue'] = {'location': {'latitude': 55.75, 'longitude': 37.62}, 'title': 'Fixture', 'address': 'Offline'}
    else:
        file = {'file_id': 'fixture-file', 'file_unique_id': 'fixture-unique', 'file_size': len(PNG)}
        if kind in {'photo', 'album'}:
            raw['photo'] = [{**file, 'width': 1, 'height': 1}]
            if kind == 'album':
                raw['media_group_id'] = 'offline-album'
        elif kind == 'sticker':
            raw['sticker'] = {**file, 'width': 1, 'height': 1, 'type': 'regular', 'is_animated': True, 'is_video': False, 'emoji': '🙂'}
        else:
            key = 'document' if kind in {'document', 'image-document'} else kind
            raw[key] = {**file, 'duration': 1, 'width': 1, 'height': 1}
            if key == 'document':
                raw[key].update(file_name='fixture.png' if kind == 'image-document' else 'fixture.bin',
                                mime_type='image/png' if kind == 'image-document' else 'application/octet-stream')
    return Update(mid, message=Message.de_json(raw, bot))


async def receive(a, bot, kind='text', **kwargs):
    handler = a._handle_command if kind in {'command', 'long-command'} else a._handle_location_message if kind in {'location', 'venue'} else a._handle_text_message if kind == 'text' else a._handle_media_message
    await handler(update(bot, kind, **kwargs), None)


def blocked_business(a):
    entered, release = asyncio.Event(), asyncio.Event()
    events = []

    async def business(event):
        events.append(event)
        entered.set()
        await release.wait()

    a.set_message_handler(business)
    return entered, release, events


async def wait_business(entered):
    await asyncio.wait_for(entered.wait(), 3)


def watch_enqueue(a, s, monkeypatch):
    snapshots = s.enqueue_boundaries
    original = a._enqueue_text_event

    def enqueue(event):
        snapshots.append(s.rows())
        original(event)

    monkeypatch.setattr(a, '_enqueue_text_event', enqueue)
    return snapshots


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['text', 'command', 'long-command', 'location', 'venue', 'photo', 'album', 'voice', 'audio', 'video', 'document', 'image-document', 'sticker'])
async def test_accepted_input_row_absent_before_enqueue_slow_work_and_blocked_business(incoming, monkeypatch, kind):
    a, s, bot = incoming
    seed = await a.send('101', 'Previous ordinary answer', metadata={'thread_id': '71'})
    assert seed.success and len(s.rows()) == 1
    entered, release, events = blocked_business(a)
    snapshots = watch_enqueue(a, s, monkeypatch)
    s.check_boundary = s.rows
    start = len(s.wire)
    await receive(a, bot, kind)
    # This is observed before any reply; native enqueue and external cache work
    # retain their own entry snapshots so delayed cleanup cannot satisfy it.
    assert all(rows == [] for rows in snapshots + s.slow_boundaries), 'Row survived into enqueue/cache work'
    assert s.rows() == [], 'Previous QA row survived accepted input'
    if kind in {'photo', 'album', 'voice', 'audio', 'video', 'document', 'image-document'}:
        assert s.file_calls == ['getFile', 'image.png']
    await wait_business(entered)
    assert len(events) == 1 and not release.is_set()
    assert not [w for w in s.wire[start:] if w['endpoint'] in {'sendMessage', 'sendRichMessage'}]
    assert events[0].source.user_id == '101' and events[0].message_id == '800'
    if kind in {'photo', 'album', 'voice', 'audio', 'video', 'document', 'image-document'}:
        assert len(events[0].media_urls) == 1
    assert a._qa_read(a._qa_scope('101', {'thread_id': '71'})[1])['active'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['text', 'command', 'location', 'photo'])
@pytest.mark.parametrize('denial', ['unauthorized', 'unmentioned', 'off-chat'])
async def test_native_rejected_input_does_not_touch_any_row(incoming, kind, denial):
    a, s, bot = incoming
    await a.send('101', 'Previous', metadata={'thread_id': '71'})
    kwargs = {}
    if denial == 'unauthorized':
        kwargs['caller'] = 404
    else:
        kwargs.update(chat=-100777, forum=True)
        await a.send('-100777', 'Other row', metadata={'thread_id': '71'})
        if denial == 'unmentioned':
            a.config.extra['require_mention'] = True
            # Commands are accepted by native policy even without a mention.
            if kind == 'command':
                kwargs['text'] = '/status@another_bot'
        else:
            a.config.extra['allowed_chats'] = ['101']
    entered, _, events = blocked_business(a)
    before = s.rows()
    start = len(s.wire)
    await receive(a, bot, kind, **kwargs)
    assert s.rows() == before and not s.wire[start:]
    assert not events and not entered.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['forum-topic', 'general-none', 'general-one', 'dm-fallback', 'dm-fallback-off', 'direct-one', 'direct-other', 'recovered'])
async def test_only_actual_native_lane_retires_general_alias_and_direct_topics_are_distinct(incoming, case):
    a, s, bot = incoming
    runner = object.__new__(GatewayRunner)
    if case == 'recovered':
        a.set_topic_recovery_fn(lambda source: '72')
    if case == 'dm-fallback-off':
        a._reply_to_mode = 'off'
    forum = case.startswith('forum') or case.startswith('general')
    thread = None if case == 'general-none' else 1 if case == 'general-one' else 71
    meta = runner._thread_metadata_for_target(Platform.TELEGRAM, '101', str(thread or 1),
        chat_type='group' if forum else 'dm', reply_to_message_id='800')
    if case.startswith('direct'):
        meta = {'direct_messages_topic_id': '1' if case == 'direct-one' else '71'}
    elif case == 'recovered':
        meta = {'thread_id': '72'}
    seed = await a.send('101', 'Target lane', metadata=meta)
    await a.send('101', 'Other topic', metadata={'thread_id': '73'})
    await a.send('101', 'Other direct topic', metadata={'direct_messages_topic_id': '2'})
    if case.startswith('direct'):
        await a.send('101', 'Not a true direct topic', metadata={'thread_id': '1' if case == 'direct-one' else '71'})
    await a.send('-100777', 'Other chat', metadata={'thread_id': '71'})
    before = s.rows()
    entered, _, events = blocked_business(a)
    await receive(a, bot, thread=thread, forum=forum,
                  direct=(1 if case == 'direct-one' else 71) if case.startswith('direct') else None)
    assert s.rows() == [row for row in before if row[2] != int(seed.message_id)]
    await wait_business(entered)
    assert len(events) == 1
    if case == 'recovered':
        assert events[0].source.thread_id == '72'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout-precommit', 'timeout-postcommit', 'invalid-true', 'invalid-false', 'invalid-id', 'malformed-json', 'corrupt-state', 'state-write'])
async def test_cosmetic_failure_keeps_one_native_business_dispatch_without_reply_or_retry(incoming, monkeypatch, failure):
    a, s, bot = incoming
    seed = await a.send('101', 'Old row', metadata={'thread_id': '71'})
    path = a._qa_scope('101', {'thread_id': '71'})[1]
    if failure == 'corrupt-state':
        path.write_text('{corrupt')
    elif failure == 'state-write':
        import plugins.platforms.telegram.telegram_qa_tail as module
        original_write = module.atomic_write_text

        def fail_write(target, text, **kwargs):
            if Path(target) == path:
                raise OSError('Fixture state write unavailable')
            return original_write(target, text, **kwargs)

        monkeypatch.setattr(module, 'atomic_write_text', fail_write)
    elif failure == 'timeout-precommit':
        def before(endpoint, params):
            if endpoint == 'editMessageReplyMarkup':
                s.faults.append({'precommit': params})
                raise TimedOut('Fixture precommit timeout')
        s.before = before
    else:
        value = {'timeout-postcommit': TimedOut('Fixture postcommit timeout'), 'invalid-true': True,
                 'invalid-false': False, 'invalid-id': {'message_id': True}, 'malformed-json': b'{"ok":true,"result":'}[failure]
        s.corrupt_once('editMessageReplyMarkup', lambda result: value)
    entered, _, events = blocked_business(a)
    start = len(s.wire)
    await receive(a, bot)
    await wait_business(entered)
    assert len(events) == 1
    mutations = [w for w in s.wire[start:] if w['endpoint'] != 'sendChatAction']
    assert all(w['endpoint'] == 'editMessageReplyMarkup' for w in mutations)
    assert len(mutations) <= 1
    if failure not in {'corrupt-state', 'state-write'}:
        assert len(s.faults) == 1 and a._qa_read(path)['active'] is False
    # Late preview edits must never expose the old row after a failed cleanup.
    s.before = s.after = None
    if failure == 'state-write':
        monkeypatch.setattr(module, 'atomic_write_text', original_write)
    before_edit = s.rows()
    edit_start = len(s.wire)
    await a.edit_message('101', seed.message_id, 'Late preview', finalize=True, metadata={'thread_id': '71'})
    if failure == 'corrupt-state':
        # Unknown durable identity cannot safely authorize a UI mutation.
        assert s.rows() == before_edit and not s.wire[edit_start:]
    else:
        assert not s.rows(), 'Late preview restored retired controls'
    callback_start = len(s.wire)
    await a._handle_callback_query(h.callback(bot, int(seed.message_id)), None)
    assert [w['endpoint'] for w in s.wire[callback_start:]] == ['answerCallbackQuery']
    assert len(events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('finalize', [False, True])
async def test_input_then_late_preview_and_next_ordinary_response_restores_exactly_one_row(incoming, finalize):
    a, s, bot = incoming
    meta = {'thread_id': '71'}
    seed = await a.send('101', 'Old preview', metadata=meta)
    entered, release, events = blocked_business(a)
    await receive(a, bot)
    assert not s.rows()
    await wait_business(entered)
    await a.edit_message('101', seed.message_id, 'Late old preview', finalize=finalize, metadata=meta)
    assert not s.rows() and len(events) == 1
    release.set()
    for task in list(a._background_tasks):
        await task
    next_reply = await a.send('101', 'Normal next answer', metadata=meta)
    assert next_reply.success and s.rows() == [(101, ('forum', 71), int(next_reply.message_id))]
    assert not [v for v in s.ledger.values() if v.get('text', '').startswith('Команда:')]


@pytest.mark.asyncio
async def test_split_batch_and_repeated_inputs_clear_once_without_duplicate_dispatch(incoming):
    a, s, bot = incoming
    await a.send('101', 'Old answer', metadata={'thread_id': '71'})
    entered, _, events = blocked_business(a)
    start = len(s.wire)
    await receive(a, bot, 'long-command')
    assert not s.rows()
    await receive(a, bot, text='continuation', mid=801)
    await receive(a, bot, text='last split', mid=802)
    await wait_business(entered)
    assert len(events) == 1
    assert events[0].text.endswith('\ncontinuation\nlast split')
    assert [w['endpoint'] for w in s.wire[start:]] == ['editMessageReplyMarkup']


@pytest.mark.asyncio
@pytest.mark.parametrize('panel', ['approval', 'clarify', 'details'])
async def test_special_panels_untouched_when_managed_ordinary_row_is_retired(incoming, panel):
    a, s, bot = incoming
    await a.send('101', 'Ordinary', metadata={'thread_id': '71'})
    callback = {'approval': 'approval:fixture', 'clarify': 'clarify:fixture', 'details': 'kd:default:fixture'}[panel]
    special = await bot.send_message(chat_id=101, text='Special UI', message_thread_id=71,
        reply_markup={'inline_keyboard': [[{'text': panel, 'callback_data': callback}]]})
    original = dict(s.ledger[(101, special.message_id)])
    entered, _, events = blocked_business(a)
    await receive(a, bot)
    assert not s.rows()
    await wait_business(entered)
    assert s.ledger[(101, special.message_id)] == original and len(events) == 1


@pytest.mark.asyncio
async def test_unsupported_input_does_not_clear_ordinary_row(incoming):
    a, s, bot = incoming
    await a.send('101', 'Ordinary', metadata={'thread_id': '71'})
    before = s.rows()
    # Unsupported DTOs never pass the native text/location shape gates.
    raw = update(bot).message.to_dict()
    raw.pop('text')
    unsupported = Update(55, message=Message.de_json(raw, bot))
    start = len(s.wire)
    await a._handle_text_message(unsupported, None)
    await a._handle_command(unsupported, None)
    await a._handle_location_message(unsupported, None)
    assert s.rows() == before and not s.wire[start:]


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['text', 'command'])
@pytest.mark.parametrize('boundary', ['forum-registration', 'replied-media'])
async def test_input_retirement_precedes_native_forum_registration_and_reply_cache(incoming, kind, boundary):
    a, s, bot = incoming
    await a.send('101', 'Ordinary', metadata={'thread_id': '71'})
    entered, _, events = blocked_business(a)
    s.check_boundary = s.rows
    kwargs = {'forum': True} if boundary == 'forum-registration' else {'reply': update(bot, 'photo', mid=700).message.to_dict()}
    await receive(a, bot, kind, **kwargs)
    assert not s.rows() and s.slow_boundaries and all(rows == [] for rows in s.slow_boundaries)
    assert s.file_calls == (['setMyCommands'] if boundary == 'forum-registration' else ['getFile', 'image.png'])
    await wait_business(entered)
    assert len(events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['retirement', 'batch'])
async def test_real_sessiondb_lock_never_blocks_heartbeat_or_unrelated_lane(incoming, monkeypatch, tmp_path, boundary):
    """Contend on the real SQLite lock, including the topic-mode predicate."""
    import threading
    from hermes_state import SessionDB
    a, s, bot = incoming
    db = SessionDB(db_path=tmp_path / 'routing.db')
    db.enable_telegram_topic_mode(chat_id='101', user_id='101')
    db.create_session(session_id='bound-topic', source='telegram', user_id='101')
    db.bind_telegram_topic(chat_id='101', thread_id='71', user_id='101',
                           session_key='test-topic', session_id='bound-topic')
    # Writable WAL readers bypass the writer lock by design. The native
    # read-only handle uses its locked connection, guaranteeing contention.
    db.close()
    db = SessionDB(db_path=tmp_path / 'routing.db', read_only=True)
    runner = object.__new__(GatewayRunner)
    runner._session_db = db
    # This is only the transport registry seam, not recovery or the DB predicate.
    runner._delivery_adapter_for = lambda source: a
    a.set_topic_recovery_fn(runner._recover_telegram_topic_thread_id)
    await a.send('101', 'Topic awaiting input', metadata={'thread_id': '71'})
    await a.send('-100777', 'Unrelated forum input', metadata={'thread_id': '73'})
    held, release, released, attempted = (threading.Event() for _ in range(4))
    arm = threading.Event()
    def holder():
        if not arm.wait(5):
            return
        with db._lock:
            held.set()
            release.wait(5)  # external bounded release also makes a broken loop terminate
        released.set()
    thread = threading.Thread(target=holder)
    thread.start()
    original_predicate = db.is_telegram_topic_mode_enabled
    recovery_threads = []
    loop_thread = threading.get_ident()
    def predicate(**kwargs):
        recovery_threads.append(threading.get_ident())
        if held.is_set() and not released.is_set():
            attempted.set()
        return original_predicate(**kwargs)
    monkeypatch.setattr(db, 'is_telegram_topic_mode_enabled', predicate)
    async def hold_lock():
        arm.set()
        assert await asyncio.to_thread(held.wait, 3)
    if boundary == 'retirement':
        await hold_lock()
    else:
        original_build = a._build_triggered_event
        async def build(*args, **kwargs):
            event = await original_build(*args, **kwargs)
            await hold_lock()
            return event
        monkeypatch.setattr(a, '_build_triggered_event', build)
    entered, business_release, events = blocked_business(a)
    task = asyncio.create_task(receive(a, bot, thread=None))
    try:
        assert await asyncio.to_thread(attempted.wait, 3), 'Real recovery did not reach the locked DB'
        # Both must complete before the external holder releases. A sync call on
        # the loop cannot satisfy this even though it eventually returns correctly.
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), 3)
        await receive(a, bot, 'location', chat=-100777, thread=73, forum=True, mid=801)
        await wait_business(entered)
        released_before_dispatch = released.is_set()
        assert not released_before_dispatch, 'SessionDB recovery blocked the event loop until external release'
        expected_rows = [(101, ('forum', 71), 4001)] if boundary == 'retirement' else []
        assert s.rows() == expected_rows
        release.set()
        await asyncio.wait_for(task, 3)
        from tests.waiting import async_wait_until
        await async_wait_until(lambda: len(events) == 2, timeout=3)
        routed = next(event for event in events if event.source.chat_id == '101')
        assert len(events) == 2 and routed.source.thread_id == '71' and not s.rows()
        h.save_evidence(tmp_path, 'lock.json', {
            'boundary': boundary, 'recovery_threads': recovery_threads, 'loop_thread': loop_thread,
            'holder_released_before_unrelated_dispatch': released_before_dispatch,
            'events': [{'chat': event.source.chat_id, 'thread': event.source.thread_id} for event in events],
        })
        assert recovery_threads and loop_thread not in recovery_threads, 'Recovery acquired SessionDB on the event loop'
    finally:
        release.set()
        business_release.set()
        await asyncio.to_thread(thread.join, 6)
        await asyncio.wait_for(task, 3)
        await h.drain(a)
        db.close()
