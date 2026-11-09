"""Receipt review regressions using native PTB Bot/ExtBot and an offline ledger.

Runnable by the canonical pytest runner or directly (unittest) without importing
portable pytest fixtures. Only the remote BaseRequest boundary is replaced.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import httpx
import pytest
telegram = pytest.importorskip("telegram", reason="Native QA tests require the optional Telegram SDK")
from telegram import Bot
from telegram.ext import ExtBot
from telegram.request import BaseRequest
from telegram.error import NetworkError
from gateway.config import PlatformConfig
from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig
from plugins.platforms.telegram import adapter as adapter_module
from plugins.platforms.telegram.adapter import TelegramAdapter

RECORDS = []
META = {"thread_id": "71"}
BUSINESS = {"sendMessage", "sendRichMessage", "editMessageText"}

class EnvPatch:
    def setenv(self, key, value):
        os.environ[key] = value

    def delenv(self, key, raising=True):
        os.environ.pop(key, None)


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


class ReceiptReviewCases:
    async def asyncSetUp(self):
        self.private = tempfile.TemporaryDirectory(prefix="receipt-review-")
        self.addCleanup(self.private.cleanup)
        env = patch.dict(os.environ, HERMES_HOME=str(Path(self.private.name) / "home"))
        env.start()
        self.addCleanup(env.stop)
        self.server = Server()
        self.bot = self.bot_type("123:offline", request=self.server, get_updates_request=Server())
        await self.bot.initialize()
        self.addAsyncCleanup(self.bot.shutdown)
        self.adapter = make_adapter(EnvPatch(), self.bot)
        self.consumer = GatewayStreamConsumer(self.adapter, "101", StreamConsumerConfig(cursor=""), metadata=META)
        self.addCleanup(self.record)

    def record(self):
        RECORDS.append({"case": self.id(), "sdk": telegram.__version__,
                        "source": adapter_module.__file__, "wire": self.server.wire,
                        "ledger": list(self.server.ledger.items()), "faults": self.server.faults})

    def mutations(self, start=0):
        return [w for w in self.server.wire[start:] if w["endpoint"] in BUSINESS]

    def assert_unknown(self, result):
        self.assertTrue(result.delivery_uncertain, vars(result))
        self.assertFalse(result.success)
        self.assertFalse(result.retryable)

    async def test_dto_error_after_raw_acceptance_never_resends(self):
        self.server.corrupt_once("sendMessage", lambda r: {**r, "chat": {"id": r["chat"]["id"]}})
        result = await self.adapter._send_with_retry("101", "DTO committed body", metadata=META, max_retries=1, base_delay=0)
        self.assertEqual(len(self.server.faults), 1)
        self.assertEqual([p["text"] for p in self.server.ledger.values()], ["DTO committed body"])
        self.assert_unknown(result)
        self.assertEqual(len(self.mutations()), 1)

    async def test_resumed_split_publishes_only_confirmed_final_tail(self):
        text = " ".join(f"resumed{i:04d}" for i in range(1300))
        rejected = []
        def before(endpoint, params):
            if endpoint == "sendMessage" and len(self.server.ledger) == 1 and len(rejected) < 3:
                rejected.append(dict(params))
                try:
                    raise httpx.ConnectTimeout("Offline proven presubmit")
                except httpx.ConnectTimeout as cause:
                    raise NetworkError("Offline connect failure") from cause
        self.server.before = before
        result = await self.adapter._send_with_retry("101", text, metadata=META, max_retries=1, base_delay=0)
        self.assertTrue(result.success, vars(result))
        self.assertFalse(result.delivery_uncertain)
        self.assertEqual(len(rejected), 3)
        bodies = [p["text"] for p in self.server.ledger.values()]
        import re
        self.assertEqual(re.findall(r"resumed\d{4}", " ".join(bodies)), text.split())
        ids = [mid for cid, mid in self.server.ledger]
        self.assertEqual(result.raw_response["message_ids"], [str(mid) for mid in ids])
        self.assertEqual(self.server.rows(), [(101, ("forum", 71), ids[-1])])
        sends = [w for w in self.mutations() if w["endpoint"] == "sendMessage"]
        self.assertTrue(all("reply_markup" not in w["params"] for w in sends))

    async def partial_seed(self):
        from gateway.platforms.base import SendResult
        seed = await self.adapter.send("101", "Committed head", metadata=META)
        return self.adapter._with_partial_send(SendResult(success=False, retryable=True),
                                               ["Resumed tail"], [seed.message_id])

    async def test_resume_uses_normalized_lane_lock_and_persists_before_markup(self):
        partial = await self.partial_seed()
        latest = await self.adapter.send("101", "Intervening latest", metadata=META)
        lock, path = self.adapter._qa_scope("101", META)
        observed = []
        def before(endpoint, params):
            if endpoint == "editMessageReplyMarkup" and params.get("reply_markup"):
                state = self.adapter._qa_read(path)
                self.assertEqual(state, {"message_id": str(params["message_id"]), "active": True})
                self.assertEqual(self.server.rows(), [])
                observed.append(state)
        self.server.before = before
        async with lock:
            start = len(self.server.wire)
            task = asyncio.create_task(self.adapter._resume_partial_send("101", partial, reply_to=None, metadata={"thread_id": "071"}))
            checkpoint = asyncio.Event()
            asyncio.get_running_loop().call_soon(checkpoint.set)
            await checkpoint.wait()
            self.assertEqual(len(self.server.wire), start)
        result = await task
        self.assertTrue(result.success, vars(result))
        self.assertEqual(len(observed), 1)
        tail = int(result.raw_response["message_ids"][-1])
        self.assertNotEqual(tail, int(latest.message_id))
        self.assertEqual(self.server.rows(), [(101, ("forum", 71), tail)])

    async def test_resume_uncertain_or_absent_tail_never_mutates(self):
        partial = await self.partial_seed()
        partial.delivery_uncertain = True
        start = len(self.server.wire)
        self.assertIsNone(await self.adapter._resume_partial_send("101", partial, reply_to=None, metadata=META))
        partial.delivery_uncertain = False
        partial.raw_response.pop("undelivered_chunks")
        self.assertIsNone(await self.adapter._resume_partial_send("101", partial, reply_to=None, metadata=META))
        self.assertEqual(len(self.server.wire), start)

    async def test_resume_retirement_failure_keeps_business_success_without_new_row(self):
        partial = await self.partial_seed()
        old_rows = self.server.rows()
        def before(endpoint, params):
            if endpoint == "editMessageReplyMarkup":
                raise NetworkError("Offline uncertain UI clear")
        self.server.before = before
        result = await self.adapter._resume_partial_send("101", partial, reply_to=None, metadata=META)
        self.assertTrue(result.success, vars(result))
        self.assertFalse(result.delivery_uncertain)
        self.assertEqual(len(self.server.ledger), 2)
        self.assertEqual(self.server.rows(), old_rows)
        _, path = self.adapter._qa_scope("101", META)
        self.assertFalse(self.adapter._qa_read(path)["active"])

    async def test_resume_persistence_failure_never_exposes_tail(self):
        from plugins.platforms.telegram import telegram_qa_tail as qa
        partial = await self.partial_seed()
        original = qa.atomic_write_text
        def write(path, text):
            if json.loads(text)["active"]:
                raise OSError("Offline storage failure")
            return original(path, text)
        with patch.object(qa, "atomic_write_text", write):
            result = await self.adapter._resume_partial_send("101", partial, reply_to=None, metadata=META)
        self.assertTrue(result.success, vars(result))
        self.assertEqual(len(self.server.ledger), 2)
        self.assertEqual(self.server.rows(), [])

    async def test_resume_committed_uncertain_tail_never_publishes_or_retries(self):
        partial = await self.partial_seed()
        self.server.corrupt_once("sendMessage", lambda r: {**r, "date": True})
        start = len(self.server.wire)
        result = await self.adapter._resume_partial_send("101", partial, reply_to=None, metadata=META)
        self.assert_unknown(result)
        self.assertNotIn("undelivered_chunks", result.raw_response)
        self.assertEqual(len(self.mutations(start)), 1)
        self.assertEqual(len(self.server.ledger), 2)
        self.assertEqual(self.server.rows(), [])

    async def test_dto_import_failure_after_commit_is_uncertain(self):
        import builtins
        original = builtins.__import__
        def importing(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "telegram" and "Message" in fromlist:
                raise ImportError("Offline DTO unavailable")
            return original(name, globals, locals, fromlist, level)
        with patch.object(builtins, "__import__", importing):
            result = await self.adapter._send_with_retry("101", "Import committed body", metadata=META, max_retries=1, base_delay=0)
        self.assert_unknown(result)
        self.assertEqual(len(self.server.ledger), 1)
        self.assertEqual(len(self.mutations()), 1)

    async def test_valid_dto_remains_confirmed(self):
        result = await self.adapter._send_with_retry("101", "Valid DTO", metadata=META, max_retries=1, base_delay=0)
        self.assertTrue(result.success)
        self.assertFalse(result.delivery_uncertain)
        self.assertEqual(len(self.server.ledger), 1)

    def flood_twice(self):
        attempts = []
        def before(endpoint, params):
            if endpoint == "editMessageText":
                attempts.append(dict(params))
                if len(attempts) <= 2:
                    return 429, b'{"ok":false,"description":"Flood","parameters":{"retry_after":1}}'
        self.server.before = before
        return attempts

    async def test_nested_flood_commit_fences_preview_restore_and_final(self):
        self.assertTrue(await self.consumer._send_or_edit("Seed preview"))
        attempts = self.flood_twice()
        self.server.corrupt_once("editMessageText", lambda r: {**r, "date": True})
        start = len(self.server.wire)
        self.assertFalse(await self.consumer._send_or_edit("Final answer after seed", finalize=True))
        await self.consumer._send_fallback_final("Final answer after seed")
        self.assertEqual(len(self.server.faults), 1)
        self.assertEqual(len(attempts), 3, self.server.wire[start:])
        self.assertTrue(self.consumer.delivery_uncertain)
        self.assertEqual(len(self.server.ledger), 1)
        self.assertEqual(next(iter(self.server.ledger.values()))["text"], "Final answer after seed")
        self.assertEqual(len(self.mutations(start)), 3)

    async def test_nested_flood_safe_retry_still_confirms(self):
        seed = await self.adapter.send("101", "Seed preview", metadata=META)
        attempts = self.flood_twice()
        result = await self.adapter.edit_message("101", seed.message_id, "Valid flood retry", finalize=True, metadata=META)
        self.assertTrue(result.success, vars(result))
        self.assertFalse(result.delivery_uncertain)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(self.server.ledger), 1)

    async def test_outer_deadline_after_commit_fences_stream_final(self):
        original = self.server.do_request
        entered = asyncio.Event()
        async def delayed(url, method, request_data=None, **kwargs):
            response = await original(url, method, request_data=request_data, **kwargs)
            if url.endswith("/sendMessage") and not entered.is_set():
                entered.set()
                await asyncio.Event().wait()
            return response
        self.server.do_request = delayed
        with patch.object(adapter_module, "_TEXT_SEND_DEADLINE", 0.05):
            ok = await self.consumer._send_or_edit("Deadline committed body")
        self.assertTrue(entered.is_set())
        self.assertFalse(ok)
        start = len(self.server.wire)
        await self.consumer._send_or_edit("Deadline committed body", finalize=True)
        await self.consumer._send_fallback_final("Deadline committed body")
        self.assertEqual(len(self.server.ledger), 1, self.server.ledger)
        self.assertTrue(self.consumer.delivery_uncertain)
        self.assertEqual(self.mutations(start), [])

    async def test_deadline_receipt_in_time_remains_confirmed(self):
        self.assertTrue(await self.consumer._send_or_edit("Timely body"))
        self.assertTrue(await self.consumer._send_or_edit("Timely body", finalize=True))
        self.assertFalse(self.consumer.delivery_uncertain)
        self.assertEqual(len(self.server.ledger), 1)

    async def test_status_unknown_edit_retains_id_without_replacement(self):
        seed = await self.adapter.send_or_update_status("101", "review", "Initial status", metadata=META)
        self.assertTrue(seed.success)
        self.server.corrupt_once("editMessageText", lambda r: {**r, "date": True})
        start = len(self.server.wire)
        result = await self.adapter.send_or_update_status("101", "review", "Updated status", metadata=META)
        self.assertEqual(len(self.server.faults), 1)
        self.assertEqual([p["text"] for p in self.server.ledger.values()], ["Updated status"])
        self.assert_unknown(result)
        self.assertEqual(self.adapter._status_message_ids[("101", "review")], seed.message_id)
        self.assertEqual([w["endpoint"] for w in self.mutations(start)], ["editMessageText"])

    async def test_status_deleted_edit_can_send_replacement(self):
        seed = await self.adapter.send_or_update_status("101", "review", "Initial status", metadata=META)
        del self.server.ledger[(101, int(seed.message_id))]
        result = await self.adapter.send_or_update_status("101", "review", "Replacement status", metadata=META)
        self.assertTrue(result.success, vars(result))
        self.assertFalse(result.delivery_uncertain)
        self.assertNotEqual(result.message_id, seed.message_id)
        self.assertEqual(len(self.server.ledger), 1)

    async def test_definite_presubmit_rejections_preserve_safe_retry(self):
        for kind in ("parse", "capability", "pool", "connect", "flood"):
            with self.subTest(kind=kind):
                attempts = []
                before_ledger = len(self.server.ledger)
                def before(endpoint, params):
                    if endpoint not in {"sendMessage", "sendRichMessage"}:
                        return None
                    attempts.append(endpoint)
                    if len(attempts) != 1:
                        return None
                    if kind in {"pool", "connect"}:
                        cls = httpx.PoolTimeout if kind == "pool" else httpx.ConnectTimeout
                        try:
                            raise cls("Offline pre-submit")
                        except cls as cause:
                            raise NetworkError("Offline pre-submit") from cause
                    if kind == "flood":
                        return 429, b'{"ok":false,"description":"Flood","parameters":{"retry_after":1}}'
                    description = "Bad Request: can't parse entities" if kind == "parse" else "Not Found"
                    return (400 if kind == "parse" else 404), json.dumps({"ok": False, "description": description}).encode()
                self.server.before = before
                self.adapter._rich_messages_enabled = kind == "capability"
                result = await self.adapter._send_with_retry("101", "- [x] Safe control", metadata=META, max_retries=1, base_delay=0)
                self.assertTrue(result.success, vars(result))
                self.assertFalse(result.delivery_uncertain)
                self.assertEqual(len(attempts), 2)
                self.assertEqual(len(self.server.ledger), before_ledger + 1)

    async def test_deadline_fences_rich_plain_and_overflow_siblings(self):
        for family in ("send-plain", "rich", "short-edit", "edit-plain", "rich-edit",
                       "overflow-head", "overflow-tail", "overflow-reply-retry"):
            with self.subTest(family=family):
                await self.deadline_sibling(family)

    async def deadline_sibling(self, family):
        self.server.before = None
        self.adapter = make_adapter(EnvPatch(), self.bot)
        seed = None
        if family not in {"send-plain", "rich"}:
            seed = await self.adapter.send("101", "Sibling preview", metadata=META)
            self.assertTrue(seed.success)
        self.adapter._rich_messages_enabled = family in {"rich", "rich-edit"}
        content = "- [x] Rich sibling" if self.adapter._rich_messages_enabled else "Sibling final"
        if family.startswith("overflow"):
            self.adapter.MAX_MESSAGE_LENGTH = 140
            content = " ".join(f"word{i:03d}" for i in range(70))
        target = "sendRichMessage" if family == "rich" else (
            "sendMessage" if family in {"send-plain", "overflow-tail", "overflow-reply-retry"} else "editMessageText")
        self.reject_sibling_once(family, target)
        original = self.server.do_request
        committed = []
        async def delayed(url, method, request_data=None, **kwargs):
            response = await original(url, method, request_data=request_data, **kwargs)
            if url.endswith("/" + target) and response[0] == 200 and not committed:
                committed.append(len(self.server.wire))
                await asyncio.Event().wait()
            return response
        with patch.object(self.server, "do_request", delayed), patch.object(adapter_module, "_TEXT_SEND_DEADLINE", 0.05):
            if seed is None:
                result = await self.adapter._send_with_retry("101", content, metadata=META, max_retries=1, base_delay=0)
            else:
                result = await self.adapter.edit_message("101", seed.message_id, content, finalize=family != "short-edit", metadata=META)
        self.assertEqual(len(committed), 1, family)
        self.assert_unknown(result)
        self.assertEqual(self.mutations(committed[0]), [], family)

    def reject_sibling_once(self, family, target):
        refusals = []
        def before(endpoint, params):
            if endpoint != target or refusals or family not in {"send-plain", "edit-plain", "overflow-reply-retry"}:
                return None
            refusals.append(dict(params))
            description = "Bad Request: reply message not found" if family == "overflow-reply-retry" else "Bad Request: can't parse entities"
            return 400, json.dumps({"ok": False, "description": description}).encode()
        self.server.before = before

    async def test_sdk_not_modified_edit_is_success(self):
        seed = await self.adapter.send("101", "Unchanged status", metadata=META)
        def before(endpoint, params):
            if endpoint == "editMessageText":
                return 400, b'{"ok":false,"description":"Bad Request: message is not modified"}'
        self.server.before = before
        result = await self.adapter.edit_message("101", seed.message_id, "Unchanged status", finalize=True, metadata=META)
        self.assertTrue(result.success, vars(result))
        self.assertFalse(result.delivery_uncertain)
        self.assertEqual(len(self.server.ledger), 1)


class TestBotReceiptReview(ReceiptReviewCases, unittest.IsolatedAsyncioTestCase):
    bot_type = Bot


class TestExtBotReceiptReview(ReceiptReviewCases, unittest.IsolatedAsyncioTestCase):
    bot_type = ExtBot


if __name__ == "__main__":
    evidence = Path(sys.argv.pop()) if len(sys.argv) == 2 and sys.argv[-1].endswith(".json") else None
    result = unittest.main(exit=False)
    if evidence is not None:
        evidence.write_text(json.dumps({"sdk": telegram.__version__, "records": RECORDS,
                                       "tests_run": result.result.testsRun,
                                       "failures": len(result.result.failures), "errors": len(result.result.errors)},
                                      ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    sys.exit(not result.result.wasSuccessful())
