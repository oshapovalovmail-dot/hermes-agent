"""Opt-in text shortcuts use native transport and ordinary human message ingress.

Only Telegram I/O and the downstream gateway handler are replaced; formatting,
routing, ACL evaluation, MessageEvent construction and base ingress remain real.
"""

import asyncio
from datetime import datetime, UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.error import BadRequest, TimedOut

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType
from plugins.platforms.telegram.adapter import TelegramAdapter

CHAT = "-1001001"
ROWS = [["статус?", "доделывай", "разрешаю"]]
INLINE = {"inline_keyboard": [[
    {"text": "статус?", "callback_data": "qa:status"},
    {"text": "доделывай", "callback_data": "qa:continue"},
    {"text": "разрешаю", "callback_data": "qa:approve"},
]]}
RICH = "| Case | Status |\n|---|---|\n| rich | ok |"
META = {"thread_id": "71"}


@pytest.fixture
def adapter():
    result = TelegramAdapter(PlatformConfig(
        enabled=True, token="123:test", typing_indicator=False,
        extra={"rich_messages": False, "reply_keyboard": {
            "mode": "inline", "chat_ids": [CHAT], "rows": ROWS,
        }},
    ))
    result._notifications_mode = "important"
    result._bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=900)),
        edit_message_text=AsyncMock(return_value=SimpleNamespace(message_id=800)),
        do_api_request=AsyncMock(return_value={"message_id": 900}),
        send_chat_action=AsyncMock(),
        answer_callback_query=AsyncMock(return_value=True),
        edit_message_reply_markup=AsyncMock(return_value=True),
    )
    return result


def test_reply_default_is_unchanged_and_inline_requires_opt_in(adapter):
    settings = adapter.config.extra["reply_keyboard"]
    settings.pop("mode")
    expected = {"keyboard": ROWS, "is_persistent": True,
                "resize_keyboard": True, "one_time_keyboard": False}
    assert adapter._reply_keyboard_markup(CHAT) == expected
    settings["mode"] = "reply"
    assert adapter._reply_keyboard_markup(CHAT) == expected
    settings["mode"] = "inline"
    assert adapter._reply_keyboard_markup(CHAT) == INLINE
    assert adapter._reply_keyboard_markup("-1002002") is None
    adapter.config.extra.clear()
    assert adapter._reply_keyboard_markup(CHAT) is None


@pytest.mark.parametrize("change", [
    {"mode": "unknown"}, {"mode": None}, {"mode": []},
    {"rows": [["unknown"]]}, {"rows": [[" статус?"]]},
    {"rows": []}, {"rows": [[]]}, {"rows": [[""]]},
    {"rows": [[123]]}, {"rows": "статус?"},
    {"chat_ids": CHAT}, {"chat_ids": []},
])
def test_invalid_shortcuts_fail_closed(adapter, change):
    adapter.config.extra["reply_keyboard"].update(change)
    assert adapter._reply_keyboard_markup(CHAT) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("multipart", [False, True])
@pytest.mark.parametrize("failure", [None, "parse", "anchor"])
async def test_send_last_chunk_keyboard_preserves_routing(adapter, multipart, failure):
    content = "hello " * (2000 if multipart else 1)
    if failure:
        message = "Can't parse entities" if failure == "parse" else "message to be replied not found"
        adapter._bot.send_message.side_effect = [
            BadRequest(message), *[SimpleNamespace(message_id=900 + i) for i in range(10)],
        ]
    result = await adapter.send(CHAT, content, reply_to="123", metadata=META)
    assert result.success
    calls = [c.kwargs for c in adapter._bot.send_message.await_args_list]
    successful = calls[1:] if failure else calls
    assert len(successful) > 1 if multipart else len(successful) == 1
    assert successful[-1]["reply_markup"] == INLINE
    assert all(c["reply_markup"] is None for c in successful[:-1])
    for call in calls:
        assert call["chat_id"] == int(CHAT)
        assert call["message_thread_id"] == 71
        assert call["disable_notification"] is True
    assert calls[0]["reply_to_message_id"] == 123
    if failure == "anchor":
        assert successful[0]["reply_to_message_id"] is None
    if failure == "parse":
        assert successful[0]["parse_mode"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("notify", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
async def test_rich_send_and_legacy_fallback_keep_inline_and_metadata(adapter, notify, fallback):
    adapter._rich_messages_enabled = True
    if fallback:
        adapter._bot.do_api_request.side_effect = BadRequest("can't parse rich_message")
    result = await adapter.send(CHAT, RICH, reply_to="123", metadata={**META, "notify": notify})
    assert result.success
    payload = adapter._bot.do_api_request.await_args.kwargs["api_kwargs"]
    assert payload["reply_markup"] == INLINE
    assert payload["reply_parameters"] == {"message_id": 123}
    assert payload["message_thread_id"] == 71
    assert payload.get("disable_notification", False) is not notify
    if fallback:
        sent = adapter._bot.send_message.await_args.kwargs
        assert sent["reply_markup"] == INLINE
        assert sent["message_thread_id"] == 71
        assert sent["reply_to_message_id"] == 123
        assert sent.get("disable_notification", False) is not notify
    else:
        adapter._bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("finalize", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
async def test_edit_including_plain_fallback_keeps_inline(adapter, finalize, fallback):
    if fallback:
        adapter._bot.edit_message_text.side_effect = [
            BadRequest("Can't parse entities"), SimpleNamespace(message_id=800),
        ]
    result = await adapter.edit_message(CHAT, "800", "Done **now**", finalize=finalize, metadata=META)
    if not finalize and fallback:
        assert not result.success  # raw preview has no markdown retry
    else:
        assert result.success
    for call in adapter._bot.edit_message_text.await_args_list:
        assert call.kwargs["reply_markup"] == INLINE
        assert "message_thread_id" not in call.kwargs
        assert "disable_notification" not in call.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [False, True])
async def test_rich_finalize_keeps_inline_without_edit_routing(adapter, fallback):
    adapter._rich_messages_enabled = True
    if fallback:
        adapter._bot.do_api_request.side_effect = BadRequest("can't parse rich_message")
    result = await adapter.edit_message(CHAT, "800", RICH, finalize=True, metadata=META)
    assert result.success
    payload = adapter._bot.do_api_request.await_args.kwargs["api_kwargs"]
    assert payload["reply_markup"] == INLINE
    assert "message_thread_id" not in payload
    assert "disable_notification" not in payload
    if fallback:
        assert adapter._bot.edit_message_text.await_args.kwargs["reply_markup"] == INLINE


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "parse", "anchor"])
async def test_edit_overflow_only_last_continuation_gets_buttons(adapter, failure):
    if failure:
        message = "Can't parse entities" if failure == "parse" else "reply message not found"
        adapter._bot.send_message.side_effect = [
            SimpleNamespace(message_id=901), BadRequest(message),
            *[SimpleNamespace(message_id=902 + i) for i in range(10)],
        ]
    result = await adapter.edit_message(CHAT, "800", "hello " * 2000, finalize=True, metadata=META)
    assert result.success
    assert adapter._bot.edit_message_text.await_args.kwargs.get("reply_markup") is None
    calls = [c.kwargs for c in adapter._bot.send_message.await_args_list]
    assert len(calls) >= 2
    assert calls[0].get("reply_markup") is None
    assert calls[-1]["reply_markup"] == INLINE
    for call in calls:
        assert call["message_thread_id"] == 71
        assert call["disable_notification"] is True
    assert calls[0]["reply_to_message_id"] == 800
    if failure == "anchor":
        assert "reply_to_message_id" not in calls[-1]


@pytest.mark.asyncio
async def test_short_edit_flood_retry_keeps_inline(adapter, monkeypatch):
    class FloodError(Exception):
        retry_after = 1

    # External transport response; no real wait in this test.
    monkeypatch.setattr("plugins.platforms.telegram.adapter.asyncio.sleep", AsyncMock())
    adapter._bot.edit_message_text.side_effect = [FloodError("Retry after 1"), SimpleNamespace(message_id=800)]
    assert (await adapter.edit_message(CHAT, "800", "Done")).success
    assert adapter._bot.edit_message_text.await_count == 2
    assert all(c.kwargs["reply_markup"] == INLINE for c in adapter._bot.edit_message_text.await_args_list)


def callback_update(adapter, data="qa:status", *, user_id=501, chat_id=int(CHAT), message=True, thread_id=71, is_forum=True):
    human = User(user_id, "Reader", False, last_name="Human", username="reader")
    bot_user = User(700, "Assistant", True)
    chat = Chat(chat_id, "supergroup", title="Fixture group", is_forum=is_forum)
    msg = Message(800, datetime(2026, 1, 1, tzinfo=UTC), chat,
                  from_user=bot_user, text="Assistant answer", message_thread_id=thread_id,
                  is_topic_message=thread_id is not None) if message else None
    if msg is not None:
        msg.set_bot(adapter._bot)
    query = CallbackQuery("fixture-query", human, "fixture-instance", message=msg, data=data)
    query.set_bot(adapter._bot)
    return Update(901, callback_query=query)


@pytest.mark.asyncio
@pytest.mark.parametrize("data,text", [("qa:status", "статус?"), ("qa:continue", "доделывай"), ("qa:approve", "разрешаю")])
async def test_shortcut_is_real_human_message_not_approval(adapter, monkeypatch, data, text):
    resolver = Mock(side_effect=AssertionError("shortcut must not resolve approvals"))
    monkeypatch.setattr("tools.approval.resolve_gateway_approval_card", resolver)
    handler = AsyncMock(return_value=None)
    adapter.set_message_handler(handler)
    seen_auth = []

    def authorize(user_id, chat_type=None, chat_id=None, **context):
        seen_auth.append((user_id, {"chat_type": chat_type, "chat_id": chat_id, **context}))
        return user_id == "501"

    adapter.set_authorization_check(authorize)
    update = callback_update(adapter, data)
    await adapter._handle_callback_query(update, None)
    adapter._bot.answer_callback_query.assert_awaited_once()
    await asyncio.gather(*list(adapter._session_tasks.values()))
    handler.assert_awaited_once()
    assert handler.await_args is not None
    event = handler.await_args.args[0]
    assert event.text == text
    assert event.message_type == MessageType.TEXT
    assert event.internal is False
    assert event.prompt_response is None
    assert event.source.platform.value == "telegram"
    assert event.source.user_id == "501"
    assert event.source.user_name == "Reader Human"
    assert event.source.is_bot is False
    assert event.source.chat_id == CHAT
    assert event.source.thread_id == "71"
    assert event.source.chat_type == "group"
    assert event.message_id is None
    assert event.platform_update_id == 901
    assert event.reply_to_message_id == "800"
    assert event.reply_to_text == "Assistant answer"
    assert event.reply_to_is_own_message is True
    assert event.raw_message is update.callback_query
    assert event.timestamp > datetime(2026, 1, 1, tzinfo=UTC)
    assert seen_auth and seen_auth[0][0] == "501"
    assert seen_auth[0][1]["thread_id"] == "71"
    assert seen_auth[0][1]["chat_id"] == CHAT
    assert event.get_command() is None
    resolver.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["denied", "unscoped", "reply_mode", "removed", "unknown", "malformed", "no_message", "missing_user"])
async def test_rejected_or_stale_callback_never_reaches_ingress(adapter, case):
    handler = AsyncMock(return_value=None)
    adapter.set_message_handler(handler)
    adapter.set_authorization_check(
        lambda user_id, chat_type=None, chat_id=None, **context: user_id == "501" and case != "denied")
    data = {"unknown": "qa:unknown", "malformed": "qa:approve:always"}.get(case, "qa:status")
    if case == "reply_mode":
        adapter.config.extra["reply_keyboard"]["mode"] = "reply"
    if case == "removed":
        adapter.config.extra["reply_keyboard"]["rows"] = [["доделывай"]]
    update = callback_update(adapter, data, user_id=0 if case == "missing_user" else 501,
                             chat_id=-1002002 if case == "unscoped" else int(CHAT),
                             message=case != "no_message")
    await adapter._handle_callback_query(update, None)
    adapter._bot.answer_callback_query.assert_awaited_once()
    handler.assert_not_awaited()
    assert not adapter._session_tasks
    adapter._bot.edit_message_reply_markup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("data,text", [("qa:status", "статус?"), ("qa:continue", "доделывай"), ("qa:approve", "разрешаю")])
async def test_click_dismisses_only_clicked_row_before_ordinary_ingress(adapter, monkeypatch, data, text):
    resolver = Mock(side_effect=AssertionError("shortcut must not resolve approvals"))
    monkeypatch.setattr("tools.approval.resolve_gateway_approval_card", resolver)
    adapter.set_authorization_check(lambda *args, **kwargs: True)
    order = []

    async def ack(**kwargs):
        order.append(("ack", kwargs["text"]))

    async def dismiss(**kwargs):
        assert order == [("ack", text)]
        order.append(("dismiss", kwargs))

    async def handler(event):
        assert [step[0] for step in order] == ["ack", "dismiss"]
        adapter._bot.send_message.assert_awaited_once_with(
            chat_id=CHAT, text=f"Команда: {text}", message_thread_id=71,
            reply_markup={"remove_keyboard": True},
        )
        assert event.text == text
        assert event.source.user_id == "501"
        assert event.source.is_bot is False
        assert event.source.thread_id == "71"
        assert event.internal is False and event.prompt_response is None
        order.append(("ingress", event.text))
        assert (await adapter.send(CHAT, "Next answer", metadata=META)).success

    adapter._bot.answer_callback_query.side_effect = ack
    adapter._bot.edit_message_reply_markup.side_effect = dismiss
    adapter.set_message_handler(handler)
    await adapter._handle_callback_query(callback_update(adapter, data), None)
    await asyncio.gather(*list(adapter._session_tasks.values()))
    assert [step[0] for step in order] == ["ack", "dismiss", "ingress"]
    adapter._bot.edit_message_reply_markup.assert_awaited_once()
    edit = adapter._bot.edit_message_reply_markup.await_args.kwargs
    assert edit["chat_id"] == int(CHAT)
    assert edit["message_id"] == 800
    assert edit["reply_markup"] is None
    assert edit.get("inline_message_id") is None
    assert "message_thread_id" not in edit
    adapter._bot.edit_message_text.assert_not_awaited()
    adapter._bot.do_api_request.assert_not_awaited()
    assert adapter._bot.send_message.await_count == 2
    assert adapter._bot.send_message.await_args_list[0].kwargs["reply_markup"] == {"remove_keyboard": True}
    assert adapter._bot.send_message.await_args.kwargs["reply_markup"] == INLINE
    resolver.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [BadRequest("Message is not modified"), TimedOut(), RuntimeError("private transport details")])
async def test_dismiss_failure_is_generic_feedback_without_event_or_approval(adapter, monkeypatch, error):
    resolver = Mock(side_effect=AssertionError("shortcut must not resolve approvals"))
    monkeypatch.setattr("tools.approval.resolve_gateway_approval_card", resolver)
    adapter.set_authorization_check(lambda *args, **kwargs: True)
    handler = AsyncMock()
    adapter.set_message_handler(handler)
    adapter._bot.edit_message_reply_markup.side_effect = error
    await adapter._handle_callback_query(callback_update(adapter, "qa:approve"), None)
    adapter._bot.edit_message_reply_markup.assert_awaited_once()
    assert [c.kwargs["text"] for c in adapter._bot.answer_callback_query.await_args_list] == [
        "разрешаю", "Не удалось обработать нажатие."]
    handler.assert_not_awaited()
    assert not adapter._session_tasks
    adapter._bot.send_message.assert_not_awaited()
    resolver.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [BadRequest("Query is too old"), TimedOut()])
async def test_failed_ack_does_not_dismiss_or_dispatch(adapter, error):
    adapter.set_authorization_check(lambda *args, **kwargs: True)
    handler = AsyncMock()
    adapter.set_message_handler(handler)
    adapter._bot.answer_callback_query.side_effect = error
    with pytest.raises(type(error)):
        await adapter._handle_callback_query(callback_update(adapter), None)
    adapter._bot.edit_message_reply_markup.assert_not_awaited()
    adapter._bot.send_message.assert_not_awaited()
    handler.assert_not_awaited()
    assert not adapter._session_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("data,text", [("qa:status", "статус?"), ("qa:continue", "доделывай"), ("qa:approve", "разрешаю")])
@pytest.mark.parametrize("thread_id,is_forum,expected_thread", [(None, False, None), (None, True, 1), (71, True, 71)])
async def test_echo_removes_reply_keyboard_before_real_ingress(adapter, data, text, thread_id, is_forum, expected_thread):
    adapter.set_authorization_check(lambda *args, **kwargs: True)
    events = []

    async def handler(event):
        adapter._bot.edit_message_reply_markup.assert_awaited_once()
        adapter._bot.send_message.assert_awaited_once_with(
            chat_id=CHAT, text=f"Команда: {text}", message_thread_id=expected_thread,
            reply_markup={"remove_keyboard": True},
        )
        events.append(event)

    adapter.set_message_handler(handler)
    await adapter._handle_callback_query(callback_update(adapter, data, thread_id=thread_id, is_forum=is_forum), None)
    await asyncio.gather(*list(adapter._session_tasks.values()))
    assert len(events) == 1
    assert events[0].text == text
    assert events[0].source.thread_id == (str(expected_thread) if expected_thread else None)
    assert events[0].internal is False and events[0].prompt_response is None


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [BadRequest("private details"), TimedOut(), RuntimeError("private details")])
async def test_echo_failure_does_not_dispatch_or_resolve_approval(adapter, monkeypatch, error):
    resolver = Mock(side_effect=AssertionError("shortcut must not resolve approvals"))
    monkeypatch.setattr("tools.approval.resolve_gateway_approval_card", resolver)
    adapter.set_authorization_check(lambda *args, **kwargs: True)
    handler = AsyncMock()
    adapter.set_message_handler(handler)
    adapter._bot.send_message.side_effect = error
    await adapter._handle_callback_query(callback_update(adapter, "qa:approve"), None)
    adapter._bot.edit_message_reply_markup.assert_awaited_once()
    adapter._bot.send_message.assert_awaited_once()
    assert [c.kwargs["text"] for c in adapter._bot.answer_callback_query.await_args_list] == [
        "разрешаю", "Не удалось обработать нажатие."]
    handler.assert_not_awaited()
    assert not adapter._session_tasks
    resolver.assert_not_called()
