"""Authenticated fixed-vocabulary shortcuts through ordinary native ingress."""
from datetime import UTC, datetime
import json
import logging
from typing import Optional

from gateway.platforms.event import MessageType
from utils import atomic_write_text
from .telegram_qa_request import TelegramDeliveryUncertain


logger = logging.getLogger(__name__)


class TelegramQACallbackMixin:
    async def _handle_quick_action_callback(self, query, data: str, update_id: Optional[int]) -> None:
        """Text shortcuts use ordinary human ingress, never approval resolvers."""
        from .adapter import _QUICK_ACTION_TEXT
        message = query.message
        chat = getattr(message, "chat", None)
        chat_id = getattr(message, "chat_id", None)
        chat_type = getattr(chat, "type", None)
        markup = self._reply_keyboard_markup(str(chat_id))
        text = _QUICK_ACTION_TEXT.get(data)
        if (
            message is None or not hasattr(message, "text") or not text
            or not isinstance(markup, dict) or "inline_keyboard" not in markup
            or not any(button["callback_data"] == data for row in markup["inline_keyboard"] for button in row)
        ):
            await query.answer(text="Кнопка больше недоступна.")
            return
        if not self._is_callback_user_authorized(
            str(getattr(query.from_user, "id", "")), chat_id=chat_id,
            chat_type=str(chat_type) if chat_type is not None else None,
            thread_id=self._effective_message_thread_id(message), user_name=getattr(query.from_user, "first_name", None),
        ):
            await query.answer(text="⛔ Нет доступа.")
            return
        event = self._build_message_event(message, MessageType.TEXT, update_id=update_id, user_override=query.from_user)
        event.text = text
        event.message_id = None
        event.reply_to_message_id = str(message.message_id)
        event.reply_to_text = message.text or message.caption or self._extract_rich_reply_text(message)
        event.reply_to_is_own_message = True
        event.raw_message = query
        event.timestamp = datetime.now(UTC)
        callback_metadata = {"thread_id": event.source.thread_id}
        direct_topic = getattr(message, "direct_messages_topic", None)
        if direct_topic is not None:
            callback_metadata = {"direct_messages_topic_id": str(direct_topic.topic_id)}
        lock, path = self._qa_scope(str(chat_id), callback_metadata)
        async with lock:
            try:
                state = self._qa_read(path)
            except Exception:
                logger.warning("Could not read Telegram shortcut callback state", exc_info=True)
                state = None
            if (not state or state["message_id"] != str(message.message_id) or not state["active"]
                    or getattr(self, "_qa_input_retired", {}).get(path) == str(message.message_id)):
                await query.answer(text="Кнопка больше недоступна.")
                return
            try:
                await self._qa_delivery_request(str(chat_id), "answerCallbackQuery",
                                                callback_query_id=query.id, text=text)
            except TelegramDeliveryUncertain as error:
                from telegram.error import TimedOut

                # Preserve the existing callback timeout signal. The row
                # is still active: neither claim nor business dispatch ran.
                if isinstance(error.__cause__, TimedOut):
                    raise error.__cause__ from None
                return
            try:
                # Claim durably before an uncertain clear/echo. Duplicate/stale
                # callbacks must not repeat a business action, even after restart.
                atomic_write_text(path, json.dumps({**state, "active": False}))
                business = {"business_connection_id": message.business_connection_id} if getattr(message, "business_connection_id", None) else {}
                await self._qa_delivery_request(str(chat_id), "editMessageReplyMarkup",
                    chat_id=chat_id, message_id=message.message_id,
                    reply_markup=None, **business,
                )
                await self._qa_delivery_request(str(chat_id), "sendMessage",
                    chat_id=chat_id,
                    text=f"Команда: {text}",
                    **self._thread_kwargs_for_send(
                        str(chat_id), event.source.thread_id, callback_metadata,
                        reply_to_mode=self._reply_to_mode,
                    ),
                    reply_markup={"remove_keyboard": True},
                    **business,
                )
            except Exception:
                logger.warning("Could not claim or echo Telegram shortcut callback", exc_info=True)
                await query.answer(text="Не удалось обработать нажатие.")
                return
        await self.handle_message(event)
        return
