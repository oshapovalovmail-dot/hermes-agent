"""Persistent composer keyboards stay scoped and preserve topic routing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from gateway.config import PlatformConfig
from plugins.platforms.telegram.adapter import TelegramAdapter


@pytest.fixture
def adapter():
    result = TelegramAdapter(PlatformConfig(enabled=True, token="123:test", extra={
        "reply_keyboard": {"chat_ids": ["101"], "rows": [["статус?", "доделывай"]]},
    }))
    result._bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=900)),
        send_chat_action=AsyncMock(),
        do_api_request=AsyncMock(return_value={"message_id": 900}),
    )
    return result


def assert_keyboard(markup):
    assert markup is not None
    assert markup["keyboard"] == [["статус?", "доделывай"]]
    assert markup["is_persistent"] is True
    assert markup["resize_keyboard"] is True
    assert markup["one_time_keyboard"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_id", ["71", "72"])
async def test_each_topic_gets_persistent_composer_keyboard(adapter, thread_id):
    result = await adapter.send("101", "Done", reply_to="123", metadata={"thread_id": thread_id})
    assert result.success
    sent = adapter._bot.send_message.call_args.kwargs
    assert sent["message_thread_id"] == int(thread_id)
    assert_keyboard(sent["reply_markup"])


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", ["202", "-100123", "@channel"])
async def test_other_chats_do_not_get_owner_keyboard(adapter, chat_id):
    assert (await adapter.send(chat_id, "Done")).success
    assert adapter._bot.send_message.call_args.kwargs["reply_markup"] is None


@pytest.mark.asyncio
async def test_disabled_keyboard_keeps_normal_sends(adapter):
    adapter.config.extra.clear()
    assert (await adapter.send("101", "Done")).success
    assert adapter._bot.send_message.call_args.kwargs["reply_markup"] is None




@pytest.mark.asyncio
async def test_markdown_fallback_keeps_persistent_keyboard(adapter):
    adapter._bot.send_message.side_effect = [BadRequest("Can't parse entities"), SimpleNamespace(message_id=900)]
    assert (await adapter.send("101", "Done")).success
    calls = adapter._bot.send_message.call_args_list
    assert len(calls) == 2
    assert_keyboard(calls[1].kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_rich_send_has_same_composer_keyboard(adapter):
    assert (await adapter._try_send_rich("101", "Done", None, None)).success
    sent = adapter._bot.do_api_request.call_args.kwargs["api_kwargs"]
    assert_keyboard(sent.get("reply_markup"))


@pytest.mark.asyncio
async def test_rich_send_other_chat_has_no_keyboard(adapter):
    assert (await adapter._try_send_rich("202", "Done", None, None)).success
    sent = adapter._bot.do_api_request.call_args.kwargs["api_kwargs"]
    assert "reply_markup" not in sent
