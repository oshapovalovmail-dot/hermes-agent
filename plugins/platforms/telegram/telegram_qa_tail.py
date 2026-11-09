"""Durable, latest-only ordinary shortcuts; special prompt UI stays native.

Locks serialize a single adapter instance, not distributed publishers. State is
written before exposing a row so an uncertain UI response cannot authorize replay.
"""
import asyncio
import hashlib
import json
import logging
from typing import Any, Optional

from hermes_constants import get_hermes_home
from gateway.platforms.base import SendResult
from gateway.platforms.event import MessageEvent
from utils import atomic_write_text
from .telegram_ids import normalize_telegram_chat_id
from .telegram_edit_delivery import TelegramEditDeliveryMixin
from .telegram_qa_callback import TelegramQACallbackMixin
from .telegram_qa_request import TelegramQARequestMixin, TelegramDeliveryUncertain

logger = logging.getLogger(__name__)


def _redact_telegram_error_text(error):
    from .adapter import _redact_telegram_error_text as redact
    return redact(error)


class TelegramQATailMixin(TelegramQACallbackMixin, TelegramQARequestMixin, TelegramEditDeliveryMixin):
    def _delivery_keyboard_markup(self, chat_id: str) -> Optional[dict[str, Any]]:
        # Ordinary inline rows are published only AFTER their message id is durable.
        markup = self._reply_keyboard_markup(chat_id)
        return None if isinstance(markup, dict) and "inline_keyboard" in markup else markup

    def _qa_scope(self, chat_id: str, metadata: Optional[dict[str, Any]] = None, reply_to=None):
        """One durable tail pointer and one lock per normalized conversation."""
        route = self._thread_kwargs_for_send(
            chat_id, self._metadata_thread_id(metadata), metadata,
            reply_to_message_id=int(reply_to) if reply_to else None,
            reply_to_mode=self._reply_to_mode,
        )
        direct_topic = route.get("direct_messages_topic_id")
        # Key the actual wire lane, not the optional DM fallback spelling.
        # Genuine direct topics remain distinct, including direct topic 1.
        thread = (["direct", int(direct_topic)] if direct_topic is not None else
                  route.get("message_thread_id"))
        if isinstance(thread, int):
            thread = str(thread)
        key = json.dumps([str(normalize_telegram_chat_id(chat_id)), thread])
        if not hasattr(self, "_qa_locks"):
            self._qa_locks = {}
        lock = self._qa_locks.setdefault(key, asyncio.Lock())
        path = get_hermes_home() / "telegram-qa-tail" / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        return lock, path

    @staticmethod
    def _qa_read(path):
        try:
            state = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        # Corrupt state must fail closed, never forget an exposed row.
        if not isinstance(state, dict) or not str(state.get("message_id", "")).isdigit() or type(state.get("active")) is not bool:
            raise ValueError("Invalid Telegram shortcut tail state")
        return state

    async def _qa_retire(self, chat_id: str, state) -> bool:
        from telegram.error import BadRequest

        if state is None:
            return True
        try:
            await self._qa_delivery_request(chat_id, "editMessageReplyMarkup",
                chat_id=normalize_telegram_chat_id(chat_id), message_id=int(state["message_id"]), reply_markup=None,
            )
            return True
        except Exception as exc:
            if isinstance(exc, BadRequest) and any(
                marker in str(exc).lower() for marker in ("not modified", "message to edit not found")
            ):
                return True
            logger.warning("[%s] Could not retire shortcut row: %s", self.name, _redact_telegram_error_text(exc), exc_info=True)
            return False

    async def _qa_prepare_input(self, event: MessageEvent) -> None:
        """Prepare the native identity/lane once before UI retirement and batching."""
        if self._drop_unresolved(event):
            return
        if event.source.chat_type == 'dm':
            await asyncio.to_thread(self._apply_topic_recovery, event)
        event._qa_topic_prepared = True
        await self._qa_retire_on_input(event)

    async def _qa_retire_on_input(self, event: MessageEvent) -> None:
        """Retire only this accepted input's ordinary tail before slow work."""
        try:
            chat_id = event.source.chat_id
            if not self._bot or not self._qa_enabled(chat_id):
                return
            # Use the same recovered source and native wire lane as replies.
            if self._drop_unresolved(event):
                return
            if event.source.chat_type == "dm" and not getattr(event, '_qa_topic_prepared', False):
                await asyncio.to_thread(self._apply_topic_recovery, event)
            from gateway.platforms.base import _thread_metadata_for_source

            metadata = _thread_metadata_for_source(event.source, event.message_id)
            direct_topic = getattr(event.raw_message, "direct_messages_topic", None)
            if direct_topic is not None:
                metadata = {"direct_messages_topic_id": str(direct_topic.topic_id)}
            lock, path = self._qa_scope(chat_id, metadata)
            async with lock:
                state = self._qa_read(path)
                if not state or not state["active"]:
                    return
                try:
                    # Fence late preview publication even if the clear times out.
                    atomic_write_text(path, json.dumps({**state, "active": False}))
                except Exception:
                    # A failed durable write must not lose the input or let this
                    # process reactivate the row after storage recovers.
                    if not hasattr(self, "_qa_input_retired"):
                        self._qa_input_retired = {}
                    self._qa_input_retired[path] = str(state["message_id"])
                    logger.warning("[%s] Could not persist input shortcut retirement", self.name, exc_info=True)
                await self._qa_retire(chat_id, state)
        except Exception as exc:
            # UI/state failures are cosmetic, never business-input retries.
            logger.warning("[Telegram] Could not retire input shortcut row: %s", _redact_telegram_error_text(exc), exc_info=True)

    async def _qa_publish(self, chat_id: str, path, message_id: str) -> None:
        try:
            # Write BEFORE exposing markup, including when the later edit times out.
            atomic_write_text(path, json.dumps({"message_id": str(message_id), "active": True}))
            await self._qa_delivery_request(chat_id, "editMessageReplyMarkup",
                chat_id=normalize_telegram_chat_id(chat_id), message_id=int(message_id),
                reply_markup=self._reply_keyboard_markup(chat_id),
            )
        except Exception as exc:
            # UI errors must never turn delivered business content into a retry.
            logger.warning("[%s] Could not publish shortcut row: %s", self.name, _redact_telegram_error_text(exc), exc_info=True)

    def _qa_enabled(self, chat_id: str, metadata=None) -> bool:
        markup = self._reply_keyboard_markup(chat_id)
        return bool(isinstance(markup, dict) and "inline_keyboard" in markup
                    and not (metadata or {}).get("kanban_details"))

    async def send(
        self, chat_id: str, content: str, reply_to: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SendResult:
        if not self._bot or not content or not content.strip() or not self._qa_enabled(chat_id, metadata):
            return await self._send_without_shortcuts(chat_id, content, reply_to, metadata)
        return await self._qa_send_operation(chat_id, self._send_without_shortcuts, content,
                                             reply_to=reply_to, metadata=metadata)

    async def _resume_partial_send(
        self, chat_id: str, result: SendResult, *, reply_to: Optional[str], metadata: Optional[dict[str, Any]],
    ) -> Optional[SendResult]:
        raw = result.raw_response if isinstance(result.raw_response, dict) else {}
        # A missing or uncertain tail must not retire UI or start any operation.
        if result.delivery_uncertain or not raw.get("undelivered_chunks") or not self._bot:
            return None
        if not self._qa_enabled(chat_id, metadata):
            return await self._resume_without_shortcuts(chat_id, result, reply_to=reply_to, metadata=metadata)
        return await self._qa_send_operation(chat_id, self._resume_without_shortcuts, result,
                                             reply_to=reply_to, metadata=metadata)

    async def _qa_send_operation(self, chat_id, operation, payload, *, reply_to, metadata):
        """Initial and resumed delivery share the same lane and publication fence."""
        lock, path = self._qa_scope(chat_id, metadata, reply_to)
        async with lock:
            try:
                state = self._qa_read(path)
                if state is not None:
                    atomic_write_text(path, json.dumps({**state, "active": False}))
                ready = await self._qa_retire(chat_id, state)
            except Exception as exc:
                logger.warning("[%s] Shortcut state unavailable: %s", self.name, _redact_telegram_error_text(exc), exc_info=True)
                ready = False
            result = await operation(chat_id, payload, reply_to=reply_to, metadata=metadata)
            if ready and result.success and not result.delivery_uncertain and result.message_id and not (result.raw_response or {}).get("thread_fallback"):
                ids = (result.raw_response or {}).get("message_ids") or [result.message_id]
                await self._qa_publish(chat_id, path, ids[-1])
            return result

    async def edit_message(
        self, chat_id: str, message_id: str, content: str, *, finalize: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SendResult:
        # The generic edit API has no original markup. Even with special-panel
        # metadata, never edit an unknown id: omitted markup clears its keyboard.
        if not self._bot or not self._qa_enabled(chat_id):
            return await self._edit_without_shortcuts(chat_id, message_id, content, finalize=finalize, metadata=metadata)
        lock, path = self._qa_scope(chat_id, metadata)
        async with lock:
            owned = False
            try:
                state = self._qa_read(path)
                owned = bool(state and state["message_id"] == str(message_id))
                current = bool(owned and state["active"]
                               and getattr(self, "_qa_input_retired", {}).get(path) != str(message_id))
                if current:
                    atomic_write_text(path, json.dumps({**state, "active": False}))
                ready = current and await self._qa_retire(chat_id, state)
            except Exception as exc:
                logger.warning("[%s] Shortcut state unavailable: %s", self.name, _redact_telegram_error_text(exc), exc_info=True)
                ready = False
            if not owned:
                # No mutation and no claimed delivery. Native status/stream
                # callers may send undelivered content via their normal fallback.
                return SendResult(success=False, retryable=False,
                                  error="Untracked Telegram edit refused: original keyboard unknown")
            try:
                result = await self._edit_without_shortcuts(chat_id, message_id, content, finalize=finalize, metadata=metadata)
            except TelegramDeliveryUncertain as error:
                result = SendResult(success=False, error=_redact_telegram_error_text(error),
                                    retryable=False, delivery_uncertain=True, raw_response={"delivery_uncertain": True})
            # Only the current active ordinary response may reclaim the tail.
            if ready and result.success and result.message_id:
                await self._qa_publish(chat_id, path, result.message_id)
            return result

    def _inline_keyboard_kwargs(self, chat_id):
        # Ordinary controls are exposed only by _qa_publish after identity persists.
        return {} if self._qa_enabled(chat_id) else self._native_inline_keyboard_kwargs(chat_id)

    def _send_retry_is_final(self, result):
        return result.delivery_uncertain or super()._send_retry_is_final(result)
