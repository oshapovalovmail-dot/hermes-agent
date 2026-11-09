"""Fresh independent contract probes. Real PTB; local server/LLM boundaries only."""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
telegram = pytest.importorskip("telegram", reason="Native QA tests require the optional Telegram SDK")
from telegram import Bot, CallbackQuery, Chat, DirectMessagesTopic, Message, Update, User
from telegram import LinkPreviewOptions, MessageEntity, ReplyKeyboardRemove, ReplyParameters
from telegram.error import BadRequest, EndPointNotFound, InvalidToken, NetworkError
from telegram.ext import ExtBot
from telegram.request import BaseRequest
from gateway.config import GatewayConfig, Platform, PlatformConfig, StreamingConfig
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig
from plugins.platforms.telegram.adapter import TelegramAdapter



class Server(BaseRequest):
    """State changes occur before an independently injectable response corruption."""
    def __init__(self):
        self.wire = []
        self.ledger = {}
        self.serial = 4000
        self.before = None
        self.after = None
        self.faults = []

    @property
    def read_timeout(self):
        return 6

    async def initialize(self):
        return None

    async def shutdown(self):
        return None

    async def do_request(self, url, method, request_data=None, **timeouts):
        endpoint = url.rsplit('/', 1)[-1]
        strings = {'text', 'parse_mode', 'business_connection_id', 'callback_query_id', 'inline_message_id'}
        params = {}
        for k, v in request_data.json_parameters.items():
            if k in strings or (k == 'chat_id' and v.startswith('@')):
                params[k] = v
            else:
                params[k] = json.loads(v)
        self.wire.append({'endpoint': endpoint, 'params': params, 'timeouts': {k: repr(v) for k, v in timeouts.items()}})
        if self.before:
            rejected = self.before(endpoint, params)
            if rejected is not None:
                return rejected
        handler = {
            'getMe': self._get_me,
            'sendMessage': self._send,
            'sendRichMessage': self._send,
            'editMessageText': self._edit,
            'editMessageReplyMarkup': self._edit,
            'answerCallbackQuery': self._boolean,
            'sendChatAction': self._boolean,
        }.get(endpoint)
        if handler is None:
            raise AssertionError(endpoint)
        status, result = handler(params)
        if status != 200:
            return status, result
        if self.after:
            altered = self.after(endpoint, params, result)
            if altered is not None:
                return altered
        await asyncio.sleep(0)
        return 200, json.dumps({'ok': True, 'result': result}).encode()

    @staticmethod
    def _get_me(params):
        return 200, {'id': 999, 'first_name': 'Offline', 'is_bot': True, 'username': 'offline_fixture_bot'}

    @staticmethod
    def _boolean(params):
        return 200, True

    def _send(self, params):
        self.serial += 1
        key = (params['chat_id'], self.serial)
        self.ledger[key] = dict(params)
        return 200, self.receipt(key)

    def _edit(self, params):
        if 'inline_message_id' in params:
            return 200, True
        key = (params['chat_id'], params['message_id'])
        if key not in self.ledger:
            return 400, b'{"ok":false,"description":"Bad Request: message to edit not found"}'
        self.ledger[key].update(params)
        if 'reply_markup' not in params:
            self.ledger[key].pop('reply_markup', None)
        return 200, self.receipt(key)

    def receipt(self, key):
        p = self.ledger[key]
        r = {'message_id': key[1], 'chat': {'id': key[0], 'type': 'private'}, 'date': 1, 'text': p.get('text', 'rich')}
        for k in ['reply_markup', 'message_thread_id', 'business_connection_id']:
            if k in p:
                if k == 'reply_markup' and 'inline_keyboard' not in (p[k] or {}):
                    continue
                r[k] = p[k]
        return r

    def rows(self):
        rows = []
        for (cid, mid), p in self.ledger.items():
            markup = p.get('reply_markup') or {}
            if 'inline_keyboard' in markup and markup['inline_keyboard'][0][0]['callback_data'].startswith('qa:'):
                lane = ('direct', p['direct_messages_topic_id']) if 'direct_messages_topic_id' in p else ('forum', p.get('message_thread_id'))
                rows.append((cid, lane, mid))
        return rows

    def corrupt_once(self, endpoint, corrupt, predicate=None):
        def after(e, p, result):
            if e == endpoint and not self.faults and (predicate is None or predicate(p)):
                self.faults.append({'endpoint': e, 'committed': dict(p), 'receipt_before': result})
                value = corrupt(result)
                if isinstance(value, bytes):
                    return 200, value
                if isinstance(value, Exception):
                    raise value
                return 200, json.dumps({'ok': True, 'result': value}).encode()
            return None
        self.after = after


def make_adapter(monkeypatch, bot):
    monkeypatch.setenv('TELEGRAM_ALLOWED_USERS', '101')
    monkeypatch.delenv('GATEWAY_ALLOW_ALL_USERS', raising=False)
    a = TelegramAdapter(PlatformConfig(enabled=True, token='123:offline', extra={
        'reply_keyboard': {'mode': 'inline', 'chat_ids': ['101', '-100777'], 'rows': [['статус?', 'доделывай', 'разрешаю']]}}))
    a._bot = bot
    a._rich_messages_enabled = False
    a._telegram_chat_outbound_slot_secs = 0
    return a


def save_evidence(tmp_path, name, payload):
    payload.update(home=os.environ['HOME'], tmp=tempfile.gettempdir(), pytest_tmp=str(tmp_path),
                   retries=os.environ.get('HERMES_TEST_FILE_RETRIES'), sdk_version=telegram.__version__,
                   source_modules={name: module.__file__ for name, module in sys.modules.items()
                       if name in {'plugins.platforms.telegram.adapter', 'plugins.platforms.telegram.telegram_qa_request',
                                   'plugins.platforms.telegram.telegram_qa_tail', 'plugins.platforms.telegram.telegram_qa_callback'}})
    text = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
    (tmp_path / name).write_text(text)
    root = os.environ.get('TELEGRAM_QA_EVIDENCE_DIR')
    if root:
        target = Path(root)
        target.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:16]
        (target / (identity + '-' + name)).write_text(text)


@pytest_asyncio.fixture(params=[Bot, ExtBot], ids=['Bot', 'ExtBot'])
async def native(request, monkeypatch, tmp_path):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'home'))
    s = Server()
    async with request.param('123:offline', request=s, get_updates_request=Server()) as bot:
        a = make_adapter(monkeypatch, bot)
        yield a, s, bot
        save_evidence(tmp_path, 'wire.json', {
            'wire': s.wire, 'ledger': list(s.ledger.items()), 'faults': s.faults,
            'sdk': telegram.__version__, 'class': type(bot).__name__,
        })



def callback(bot, mid, *, thread=71, direct=None, forum=False, caller=101):
    raw = {'message_id': mid, 'date': 1, 'chat': {'id': 101, 'type': 'supergroup' if forum else 'private', 'is_forum': forum},
           'from': {'id': 999, 'first_name': 'Offline', 'is_bot': True}, 'text': 'Original quote', 'business_connection_id': 'bc-fresh'}
    if thread is not None:
        raw.update(message_thread_id=thread, is_topic_message=True)
    if direct is not None:
        raw['direct_messages_topic'] = {'topic_id': direct}
    message = Message.de_json(raw, bot)
    query = CallbackQuery('fresh-callback', User(caller, 'Real human', False), 'fresh-instance', message=message, data='qa:continue')
    query.set_bot(bot)
    return Update(141, callback_query=query)


async def drain(a):
    if a._background_tasks:
        await asyncio.gather(*list(a._background_tasks))


@pytest.mark.asyncio
async def test_lossy_dto_control_then_raw_guard_and_early_dates(native):
    a, s, bot = native
    s.corrupt_once('sendMessage', lambda r: {**r, 'date': True})
    decoded = await bot.send_message(chat_id=101, text='Native lossy date')
    assert isinstance(decoded, Message) and isinstance(decoded.date, datetime) and decoded.date.timestamp() == 1
    s.faults.clear()
    result = await a._send_with_retry('101', 'Guard rejects same boolean', max_retries=1, base_delay=0)
    assert result.delivery_uncertain and not result.success and not result.retryable
    assert len(s.faults) == 1 and len(s.ledger) == 2 and not s.rows()
    for date in (0, 1):
        s.after = lambda e,p,r: (200, json.dumps({'ok': True, 'result': {**r, 'date': date, 'unknown_future': True}}).encode()) if isinstance(r,dict) and 'message_id' in r else None
        sent = await a.send('-100777', 'Valid group early date')
        assert sent.success and not sent.delivery_uncertain
        edited = await a.edit_message('-100777', sent.message_id, 'Valid edited early date', finalize=True)
        assert edited.success and not edited.delivery_uncertain


@pytest.mark.asyncio
@pytest.mark.parametrize('family,fault', [
    ('legacy', 'truncated'), ('rich', 'date-float'), ('short', 'wrong-message'),
    ('final', 'wrong-chat'), ('rich-edit', 'date-bool'), ('overflow-first', 'true'), ('overflow-tail', 'network')])
async def test_independent_sparse_faults_never_resend_or_confirm(native, family, fault):
    a,s,_ = native
    meta = {'thread_id': '71'}
    seed = None if family in {'legacy','rich'} else await a.send('101', 'Preview', metadata=meta)
    a._rich_messages_enabled = family in {'rich','rich-edit'}
    text = '- [x] Fresh rich final' if a._rich_messages_enabled else 'Fresh short final'
    if family.startswith('overflow'):
        a.MAX_MESSAGE_LENGTH = 140
        text = ' '.join(f'unique{i:03d}' for i in range(70))
    endpoint = 'sendRichMessage' if family=='rich' else 'sendMessage' if family in {'legacy','overflow-tail'} else 'editMessageText'
    transform = {
        'truncated': lambda r: b'{"ok":true,"result":', 'date-float': lambda r: {**r,'date':1.0},
        'wrong-message': lambda r: {**r,'message_id':r['message_id']+1}, 'wrong-chat': lambda r: {**r,'chat':{'id':-100777}},
        'date-bool': lambda r: {**r,'date':False}, 'true': lambda r: True,
        'network': lambda r: NetworkError('postcommit parse retry after not modified reply message not found')}
    start = len(s.wire)
    s.corrupt_once(endpoint, transform[fault])
    result = await a._send_with_retry('101',text,metadata=meta,max_retries=1,base_delay=0) if seed is None else await a.edit_message('101',seed.message_id,text,finalize=family!='short',metadata=meta)
    mutations = [w for w in s.wire[start:] if w['endpoint'] in {'sendMessage','sendRichMessage','editMessageText'}]
    assert len(s.faults)==1 and len(mutations)==(2 if family=='overflow-tail' else 1)
    assert result.delivery_uncertain and not result.success and not result.retryable and not s.rows()


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['ack','clear','echo','positive'])
async def test_callback_stage_replay_and_real_handler_order(native, monkeypatch, stage):
    a,s,bot = native
    meta={'thread_id':'71'}
    sent=await a.send('101','Clickable original',metadata=meta)
    assert sent.success
    if stage!='positive':
        endpoint={'ack':'answerCallbackQuery','clear':'editMessageReplyMarkup','echo':'sendMessage'}[stage]
        s.corrupt_once(endpoint, (lambda r: 1.0) if stage=='ack' else (lambda r: {**r,'chat':{'id':202}}) if stage=='clear' else (lambda r: {**r,'message_id':True}))
    events=[]; entered=asyncio.Event(); release=asyncio.Event()
    async def business(event):
        events.append(event)
        assert not s.rows() and event.source.user_id=='101' and event.message_id is None
        assert event.reply_to_message_id==sent.message_id and event.reply_to_text=='Original quote'
        echoes=[w['params'] for w in s.wire if w['endpoint']=='sendMessage' and w['params']['text'].startswith('Команда:')]
        assert len(echoes)==1 and echoes[0]['text']=='Команда: доделывай' and echoes[0]['reply_markup']=={'remove_keyboard':True}
        entered.set();await release.wait()
        await a.send('101','Independent business completion',metadata=meta)
    a.set_message_handler(business)
    start=len(s.wire)
    try:
        await a._handle_callback_query(callback(bot,int(sent.message_id)),None)
        if stage=='positive':
            await asyncio.wait_for(entered.wait(),2)
            assert len(events)==1 and not s.rows()
            assert [w['endpoint'] for w in s.wire[start:]][:3]==['answerCallbackQuery','editMessageReplyMarkup','sendMessage']
            wire=[w['params'] for w in s.wire[start:] if w['endpoint'] in {'editMessageReplyMarkup','sendMessage'}]
            assert all(p['business_connection_id']=='bc-fresh' for p in wire)
        else:
            await drain(a)
            assert not events and len(s.faults)==1
            _,path=a._qa_scope('101',meta);state=a._qa_read(path)
            assert state['active']==(stage=='ack')
            if stage!='ack':
                s.after=None
                clone=make_adapter(monkeypatch,bot);clone.set_message_handler(business)
                before=len(s.wire)
                await clone._handle_callback_query(callback(bot,int(sent.message_id)),None)
                await drain(clone)
                assert not events and [w['endpoint'] for w in s.wire[before:]]==['answerCallbackQuery']
    finally:
        release.set();await drain(a)
    if stage=='positive':
        assert len(s.rows())==1 and len(events)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['publish','retire'])
async def test_uncertain_ui_never_replays_confirmed_business_and_pointer_recovers(native,stage):
    a,s,_=native
    if stage=='retire':
        assert (await a.send('101','Previous business')).success
    s.corrupt_once('editMessageReplyMarkup',lambda r: b'{"ok":true,"result":')
    result=await a._send_with_retry('101','Fresh body once',max_retries=1,base_delay=0)
    assert result.success and not result.delivery_uncertain and len(s.faults)==1
    bodies=[w for w in s.wire if w['endpoint']=='sendMessage' and w['params']['text']=='Fresh body once']
    assert len(bodies)==1
    _,path=a._qa_scope('101');state=a._qa_read(path)
    assert state['active']==(stage=='publish')
    if stage=='retire':assert not s.rows()
    s.after=None
    assert (await a.send('101','Later independent')).success and len(s.rows())==1


@pytest.mark.asyncio
async def test_effective_lane_lock_general_direct_and_native_private_aliases(native,monkeypatch):
    a,s,bot=native
    runner=object.__new__(GatewayRunner)
    meta=runner._thread_metadata_for_target(Platform.TELEGRAM,'101','71',chat_type='dm',reply_to_message_id='800')
    root=await a.send('101','Root',metadata={'thread_id':'1'})
    results=await asyncio.gather(a.send('101','General absent'),a.send('101','Direct one',metadata={'direct_messages_topic_id':1}),
                                 a.send('101','Private native',metadata=meta),a.send('101','Private alias',reply_to='800',metadata={'thread_id':'71'}))
    assert all(r.success for r in results) and len(s.rows())==3
    assert {lane for cid,lane,mid in s.rows()}=={('forum',None),('forum',71),('direct',1)}
    start=len(s.wire)
    stale=await a.edit_message('101',root.message_id,'Must not restore',finalize=True)
    assert not stale.success and s.wire[start:]==[]
    direct_mid=next(mid for cid,lane,mid in s.rows() if lane==('direct',1))
    events=[]
    async def business(event):events.append(event)
    a.set_message_handler(business)
    await a._handle_callback_query(callback(bot,direct_mid,thread=None,direct=1),None)
    await drain(a)
    assert len(events)==1 and len(s.rows())==2
    echo=[w['params'] for w in s.wire if w['endpoint']=='sendMessage' and w['params']['text'].startswith('Команда:')]
    assert len(echo)==1 and echo[0]['direct_messages_topic_id']==1 and 'message_thread_id' not in echo[0]

@pytest.mark.asyncio
@pytest.mark.parametrize('family', ['legacy', 'markdown-fallback', 'multichunk', 'rich', 'rich-reject', 'short', 'plain-edit', 'rich-edit', 'overflow', 'overflow-plain', 'overflow-missing-anchor', 'reactive-one', 'reactive-one-plain'])
async def test_ordinary_transport_matrix_keeps_only_final_row(native, monkeypatch, family):
    a, s, bot = native
    meta = {'thread_id': '71'}
    prior = await a.send('101', 'Earlier ordinary answer', metadata=meta)
    edits = family in {'short', 'plain-edit', 'rich-edit', 'overflow', 'overflow-plain', 'overflow-missing-anchor', 'reactive-one', 'reactive-one-plain'}
    seed = await a.send('101', 'Current preview', metadata=meta) if edits else None
    a._rich_messages_enabled = family in {'rich', 'rich-reject', 'rich-edit'}
    text = '- [x] Completed rich answer' if a._rich_messages_enabled else 'Normal final answer'
    if family in {'multichunk', 'overflow', 'overflow-plain', 'overflow-missing-anchor'}:
        a.MAX_MESSAGE_LENGTH = 140
        text = ' '.join(f'matrix{i:03d}' for i in range(75))
    if family.startswith('reactive-one'):
        # First edit rejects as too long, then the actual splitter returns one
        # chunk. This exercises the reactive branch rather than preflight.
        monkeypatch.setattr(a, 'truncate_message', lambda *args, **kwargs: [text])
    rejected = []
    def before(endpoint, params):
        reason = None
        if family == 'rich-reject' and endpoint == 'sendRichMessage':
            reason = 'Bad Request: unsupported rich_message'
        elif family.startswith('reactive-one') and endpoint == 'editMessageText' and len(rejected) < 2:
            reason = 'Bad Request: message is too long'
        elif family == 'reactive-one-plain' and endpoint == 'editMessageText' and len(rejected) == 2 or family in {'markdown-fallback', 'plain-edit', 'overflow-plain'} and params.get('parse_mode') and endpoint in {'sendMessage', 'editMessageText'}:
            reason = "Bad Request: can't parse entities"
        elif family == 'overflow-missing-anchor' and endpoint == 'sendMessage' and params.get('reply_parameters'):
            reason = 'Bad Request: reply message not found'
        if reason:
            rejected.append((endpoint, reason))
            return 400, json.dumps({'ok': False, 'description': reason}).encode()
        return None
    s.before = before
    start = len(s.wire)
    result = (await a.edit_message('101', seed.message_id, text, finalize=family != 'short', metadata=meta)
              if edits else await a.send('101', text, metadata=meta))
    assert result.success and not result.delivery_uncertain
    last_id = (result.raw_response['message_ids'][-1] if family == 'multichunk' else result.message_id)
    assert s.rows() == [(101, ('forum', 71), int(last_id))]
    assert not (s.ledger[(101, int(prior.message_id))].get('reply_markup') or {}).get('inline_keyboard')
    endpoints = [w['endpoint'] for w in s.wire[start:]]
    if a._rich_messages_enabled:
        assert ('editMessageText' if edits else 'sendRichMessage') in endpoints
    if family in {'markdown-fallback', 'plain-edit', 'overflow-plain', 'overflow-missing-anchor', 'rich-reject'} or family.startswith('reactive-one'):
        assert rejected, 'Fault must fire on the intended native path'
    if family.startswith('overflow'):
        assert endpoints.count('sendMessage') >= 1 and result.continuation_message_ids
    # A restarted adapter uses the persisted final pointer, never a process-local cache.
    s.before = None
    clone = make_adapter(monkeypatch, bot)
    next_reply = await clone.send('101', 'After adapter restart', metadata=meta)
    assert next_reply.success and s.rows() == [(101, ('forum', 71), int(next_reply.message_id))]


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,value', [('answerCallbackQuery', False), ('answerCallbackQuery', None), ('answerCallbackQuery', 1), ('editMessageReplyMarkup', True), ('editMessageReplyMarkup', False), ('sendMessage', True), ('sendMessage', {'date': 1})])
async def test_callback_requires_endpoint_positive_receipt(native, stage, value):
    a, s, bot = native
    seed = await a.send('101', 'Clickable', metadata={'thread_id': '71'})
    s.corrupt_once(stage, lambda result: value)
    events = []
    async def business(event):
        events.append(event)
    a.set_message_handler(business)
    await a._handle_callback_query(callback(bot, int(seed.message_id)), None)
    await drain(a)
    assert len(s.faults) == 1 and not events
    state = a._qa_read(a._qa_scope('101', {'thread_id': '71'})[1])
    assert state['active'] is (stage == 'answerCallbackQuery')
    if stage == 'answerCallbackQuery':
        assert len(s.rows()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('denial', ['unauthorized', 'unknown', 'off', 'other-chat', 'stale', 'wrong-topic'])
async def test_callback_native_negative_controls_never_mutate_or_dispatch(native, denial):
    a, s, bot = native
    seed = await a.send('101', 'Clickable', metadata={'thread_id': '71'})
    query_update = callback(bot, int(seed.message_id), caller=404 if denial == 'unauthorized' else 101,
                            thread=72 if denial == 'wrong-topic' else 71)
    raw = query_update.to_dict()
    mutations = {
        'unknown': lambda: raw['callback_query'].update(data='qa:arbitrary user text'),
        'off': lambda: a.config.extra['reply_keyboard'].update(mode='off'),
        'other-chat': lambda: raw['callback_query']['message']['chat'].update(id=202),
    }
    mutate = mutations.get(denial)
    if mutate is not None:
        mutate()
        query_update = Update.de_json(raw, bot)
    if denial == 'stale':
        await a.send('101', 'New ordinary answer', metadata={'thread_id': '71'})
    events = []
    async def business(event):
        events.append(event)
    a.set_message_handler(business)
    start = len(s.wire)
    before = s.rows()
    await a._handle_callback_query(query_update, None)
    await drain(a)
    assert s.rows() == before and not events
    assert [w['endpoint'] for w in s.wire[start:]] == ['answerCallbackQuery']


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['expired-ack', 'timeout-ack', 'clear-error', 'clear-not-modified', 'concurrent'])
async def test_callback_ack_clear_errors_and_concurrent_clicks(native, fault):
    from telegram.error import TimedOut
    a, s, bot = native
    seed = await a.send('101', 'Clickable', metadata={'thread_id': '71'})
    events = []
    entered, release = asyncio.Event(), asyncio.Event()
    async def business(event):
        events.append(event)
        entered.set()
        await release.wait()
    a.set_message_handler(business)
    def before(endpoint, params):
        if fault == 'expired-ack' and endpoint == 'answerCallbackQuery':
            return 400, b'{"ok":false,"description":"Bad Request: query is too old"}'
        if fault == 'timeout-ack' and endpoint == 'answerCallbackQuery':
            raise TimedOut('offline ACK timeout')
        if fault in {'clear-error', 'clear-not-modified'} and endpoint == 'editMessageReplyMarkup':
            reason = 'message is not modified' if fault == 'clear-not-modified' else 'cannot edit message'
            return 400, json.dumps({'ok': False, 'description': 'Bad Request: ' + reason}).encode()
        return None
    s.before = before
    start = len(s.wire)
    try:
        if fault in {'expired-ack', 'timeout-ack'}:
            with pytest.raises(BadRequest if fault == 'expired-ack' else TimedOut):
                await a._handle_callback_query(callback(bot, int(seed.message_id)), None)
            assert s.rows() == [(101, ('forum', 71), int(seed.message_id))]
            assert [w['endpoint'] for w in s.wire[start:]] == ['answerCallbackQuery']
            assert not events
        elif fault == 'concurrent':
            await asyncio.gather(*(a._handle_callback_query(callback(bot, int(seed.message_id)), None) for _ in range(2)))
            await asyncio.wait_for(entered.wait(), 3)
            assert len(events) == 1 and not s.rows()
            assert len([w for w in s.wire[start:] if w['endpoint'] == 'sendMessage']) == 1
        else:
            await a._handle_callback_query(callback(bot, int(seed.message_id)), None)
            await drain(a)
            assert not events and not [w for w in s.wire[start:] if w['endpoint'] == 'sendMessage']
    finally:
        release.set()
        await drain(a)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['off', 'reply', 'other-chat'])
async def test_noninline_native_send_and_edit_do_not_acquire_qa_tail(native, mode):
    a, s, _ = native
    chat = '202' if mode == 'other-chat' else '101'
    if mode != 'other-chat':
        a.config.extra['reply_keyboard']['mode'] = mode
    result = await a.send(chat, 'Native response')
    assert result.success and not s.rows()
    edited = await a.edit_message(chat, result.message_id, 'Native final response', finalize=True)
    assert edited.success and not s.rows()
    assert 'editMessageReplyMarkup' not in [w['endpoint'] for w in s.wire]
    assert not a._qa_scope(chat)[1].exists()
    if mode == 'reply':
        sent = next(w['params'] for w in s.wire if w['endpoint'] == 'sendMessage')
        assert 'keyboard' in sent['reply_markup']


@pytest.mark.asyncio
async def test_raw_guard_preserves_extbot_defaults_and_explicit_overrides(monkeypatch, tmp_path):
    from telegram.ext import Defaults
    defaults = Defaults(parse_mode='HTML', disable_notification=True, protect_content=True,
                        allow_sending_without_reply=True,
                        link_preview_options=LinkPreviewOptions(is_disabled=True, prefer_small_media=True))
    s = Server()
    async with ExtBot('123:offline', request=s, get_updates_request=Server(), defaults=defaults) as bot:
        a = make_adapter(monkeypatch, bot)
        for overrides in ({}, {'parse_mode': None, 'disable_notification': False, 'protect_content': False,
                              'link_preview_options': LinkPreviewOptions(is_disabled=False),
                              'reply_parameters': ReplyParameters(42, allow_sending_without_reply=False, quote_parse_mode=None)}):
            args = {'chat_id': 101, 'text': 'Default parity', 'reply_parameters': ReplyParameters(42), **overrides}
            await bot.send_message(**args)
            expected = s.wire[-1]
            await a._qa_delivery_request('101', 'sendMessage', **args)
            assert s.wire[-1] == expected
        save_evidence(tmp_path, 'defaults-wire.json', {'wire': s.wire, 'class': type(bot).__name__})


@pytest.mark.asyncio
async def test_native_wire_objects_aliases_omission_and_typed_rejections(native):
    a,s,bot=native
    args={'chat_id':101,'text':'bold','entities':[MessageEntity('bold',0,4)],'parse_mode':None,
          'reply_parameters':ReplyParameters(42,allow_sending_without_reply=False),
          'link_preview_options':LinkPreviewOptions(is_disabled=False), 'reply_markup':ReplyKeyboardRemove(),
          'disable_notification':False,'business_connection_id':'bc','direct_messages_topic_id':1}
    native_result=await bot.send_message(**args)
    wire=s.wire[-1]
    guard=await a._qa_delivery_request('101','sendMessage',**args)
    assert isinstance(native_result,Message) and type(guard) is dict and s.wire[-1]==wire
    aliases={**args};aliases.pop('reply_parameters');aliases.pop('link_preview_options')
    aliases.update(reply_to_message_id=42,allow_sending_without_reply=False,disable_web_page_preview=False,
                   read_timeout=None,connect_timeout=4,write_timeout=5,pool_timeout=6)
    await bot.send_message(**aliases);wire=s.wire[-1]
    await a._qa_delivery_request('101','sendMessage',**aliases)
    assert s.wire[-1]==wire
    for endpoint in ['editMessageText','editMessageReplyMarkup']:
        assert await a._qa_delivery_request('101',endpoint,inline_message_id='native-inline',text='inline') is True
    for endpoint in ['sendMessage','editMessageText','editMessageReplyMarkup','answerCallbackQuery']:
        for code in [401,404]:
            s.before=lambda e,p: (code,b'{"ok":false,"description":"Native auth rejected"}') if e==endpoint else None
            with pytest.raises(InvalidToken):
                await a._qa_delivery_request('101',endpoint,chat_id=101,message_id=4001,text='Never committed')
    s.before=lambda e,p: (404,b'{"ok":false,"description":"Unknown method"}') if e=='sendRichMessage' else None
    with pytest.raises(EndPointNotFound):
        await a._qa_delivery_request('101','sendRichMessage',api_kwargs={'chat_id':101,'rich_message':{'text':'rich'}})
