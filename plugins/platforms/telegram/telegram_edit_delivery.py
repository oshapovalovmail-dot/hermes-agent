"""Telegram edit delivery phases, including overflow and bounded flood recovery."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from gateway.platforms.base import SendResult
from .telegram_qa_request import TelegramDeliveryUncertain

logger = logging.getLogger("plugins.platforms.telegram.adapter")


class TelegramEditDeliveryMixin:
    async def _edit_without_shortcuts(
        self, chat_id: str, message_id: str, content: str, *, finalize: bool = False, metadata: Optional[dict[str, Any]] = None,
   ) -> SendResult:
        """Edit a previously sent Telegram message.

        Telegram caps a message at 4096 UTF-16 codeunits. Streaming replies that outgrow it must NOT be truncated
        silently nor fail (the consumer would re-send a duplicate): edit with the first chunk, send the rest as
        continuations, and return the final chunk's id as the next edit target."""
        from .adapter import _strip_mdv2, utf16_len

        if not self._bot:
            return SendResult(success=False, error="Not connected")
        # Shared per-chat budget (#116312): an interim (preview) edit is SKIPPED when the slot is busy —
        # the text it would show is shown by the next edit anyway, so a burst of edits can't trip flood
        # control. A final edit is never gated (the completed answer is always delivered). Sends wait for
        # their slot; edits defer instead. Over-cap interim edits are exempt: the saturated-preview dedup
        # below already throttles them to one real edit per ~4096-char growth. Consumed only when the
        # edit actually fires. The skip is flagged in raw_response so the stream consumer does not
        # record never-shown text as the visible prefix (a later flood fallback would then drop the
        # tail the user never saw).
        if (
            not finalize
            and utf16_len(content) <= self.MAX_MESSAGE_LENGTH
            and self._chat_outbound_slot_remaining(chat_id) > 0
        ):
            logger.debug(
                "[%s] skipping interim edit for chat %s (shared send+edit budget: slot busy)",
                self.name, chat_id)
            return SendResult(success=True, message_id=message_id, raw_response={"skipped": True})
        self._hold_chat_outbound_slot(chat_id)
        # Rich finalize (Bot API 10.1): edit the preview IN PLACE via rich_message — no fresh send + delete.
        # Before the 4,096 pre-flight because the rich cap is 32,768; falls back to legacy on rejection.
        # Rich finalize (Bot API 10.1): when the completed content has constructs the legacy MarkdownV2 edit
        # degrades (tables → bullet lists, task lists, <details>, block math) and rich is available, edit
        # the preview IN PLACE via editMessageText's rich_message param. No fresh send + delete → no
        # duplicate preview (the problem #46206 reverted the fresh-final path for). Attempted before the
        # 4,096 overflow pre-flight because the rich text cap is 32,768 — a rich table that exceeds the
        # MarkdownV2 limit must not be split into legacy chunks. Falls back to the legacy edit path
        # (overflow split included) on capability/permanent rejection.
        if finalize and self._rich_eligible(content):
            rich_result = await self._try_edit_rich(chat_id, message_id, content, metadata=metadata)
            if rich_result is not None:
                return rich_result
        # Pre-flight: over-limit content is split-and-delivered on finalize; mid-stream we truncate instead
        # (splitting moves the edit target to a continuation → infinite duplication loop).
        # Pre-flight: if content already exceeds the limit, split-and-deliver without round-tripping a
        # doomed edit. During streaming (finalize=False) we truncate instead of splitting — splitting
        # creates continuation messages whose IDs become the new edit target, and on the next token chunk
        # the full accumulated text is re-edited into the continuation, triggering another split → infinite
        # duplication loop (#48648).
        _preview_key = (str(chat_id), str(message_id))
        _saturated_preview = False
        if finalize:
            self._last_overflow_preview.pop(_preview_key, None)  # the final edit always delivers full content
        if utf16_len(content) > self.MAX_MESSAGE_LENGTH:
            if finalize:
                return await self._edit_overflow_split(chat_id, message_id, content, finalize=finalize, metadata=metadata)
            content = self._truncate_stream_overflow_preview(content)
            _saturated_preview = True
            # Saturated-preview dedup: past the cap every progressive edit truncates to the same text;
            # re-sending is a visual no-op that still burns flood budget (200s+ penalties).
            if self._last_overflow_preview.get(_preview_key) == content:
                return SendResult(success=True, message_id=message_id)
        elif not finalize:
            # Content shrank back under the cap — clear stale saturation state so dedup can't mask an edit.
            self._last_overflow_preview.pop(_preview_key, None)
        try:
            if not finalize:
                await self._edit_text(chat_id, message_id, content)
                if _saturated_preview:
                    self._last_overflow_preview[_preview_key] = content
                return SendResult(success=True, message_id=message_id)
            await self._edit_markdown_or_plain(
                chat_id, message_id, self.format_message(content), _strip_mdv2(content) if content else content,
                "[%s] MarkdownV2 edit failed, falling back to plain text: %s")
            return SendResult(success=True, message_id=message_id)
        except Exception as e:
            logger.debug("Telegram edit delivery failed", exc_info=True)
            return await self._handle_edit_delivery_failure(
                e, chat_id, message_id, content, finalize=finalize, metadata=metadata, preview_key=_preview_key)

    async def _handle_edit_delivery_failure(
        self, e, chat_id, message_id, content, *, finalize, metadata, preview_key,
    ):
        from .adapter import (
            _FLOOD_INLINE_WAIT_CAP_SECS, _flood_cap_result,
            _redact_telegram_error_text, utf16_len,
        )

        if isinstance(e, TelegramDeliveryUncertain):
            return self._qa_uncertain_result(e)
        err_str = str(e).lower()
        if "not modified" in err_str:
            return SendResult(success=True, message_id=message_id)
        # Reactive split: MarkdownV2 escapes can inflate the payload past the limit even when raw text fit.
        if "message_too_long" in err_str or "too long" in err_str:
            logger.debug(
                "[%s] edit_message overflow (%d UTF-16 > %d), splitting", self.name, utf16_len(content), self.MAX_MESSAGE_LENGTH)
            if finalize:
                return await self._edit_overflow_split(chat_id, message_id, content, finalize=finalize, metadata=metadata)
            # Mid-stream: truncate and retry instead of splitting (saturated-preview dedup as above).
            # See #48648.
            truncated = self._truncate_stream_overflow_preview(content)
            if self._last_overflow_preview.get(preview_key) == truncated:
                return SendResult(success=True, message_id=message_id)
            await self._edit_text(chat_id, message_id, truncated)
            self._last_overflow_preview[preview_key] = truncated
            return SendResult(success=True, message_id=message_id)
        # Flood control: short waits retry inline; long waits fail immediately so streaming falls back
        # to a normal final send instead of a clipped partial.
        retry_after = getattr(e, "retry_after", None)
        if retry_after is not None or "retry after" in err_str:
            wait = retry_after if retry_after else 1.0
            if wait > _FLOOD_INLINE_WAIT_CAP_SECS:
                # Log AFTER the cap check: "waiting 33.0s" followed by no wait misled an investigation.
                logger.warning(
                    "[%s] Telegram flood control, refusing edit (retry_after %.1fs > %.0fs inline cap)",
                    self.name, wait, _FLOOD_INLINE_WAIT_CAP_SECS)
                return _flood_cap_result(wait)
            logger.warning("[%s] Telegram flood control, waiting %.1fs", self.name, wait)
            await asyncio.sleep(wait)
            try:
                await self._edit_text(chat_id, message_id, content)
                return SendResult(success=True, message_id=message_id)
            except Exception as retry_err:
                if isinstance(retry_err, TelegramDeliveryUncertain):
                    return self._qa_uncertain_result(retry_err)
                safe_retry_error = _redact_telegram_error_text(retry_err)
                logger.error("[%s] Edit retry failed after flood wait: %s", self.name, safe_retry_error, exc_info=True)
                retry_wait = getattr(retry_err, "retry_after", None)
                if retry_wait is not None or "retry after" in str(retry_err).lower():
                    # Still flooded after the inline wait, and typically for much longer than the
                    # first refusal asked for. Fail closed canonically so the ledger arms its
                    # timer on this delay rather than storing the platform's raw wording, which
                    # it would read as an ordinary failure and never redeliver.
                    return _flood_cap_result(
                        float(retry_wait) if retry_wait is not None else wait)
                return SendResult(success=False, error=safe_retry_error)
        safe_error = _redact_telegram_error_text(e)
        # Transient network errors must not permanently disable progress-message editing.
        _transient_markers = (
            "connecterror", "connect error", "connection error", "networkerror", "network error", "timed out", "readtimeout",
            "writetimeout", "server disconnected", "temporarily unavailable", "temporary failure", "httpx")
        if any(m in err_str for m in _transient_markers):
            logger.warning("[%s] Transient network error editing message %s (will retry): %s", self.name, message_id, safe_error)
            return SendResult(success=False, error=safe_error, retryable=True)
        logger.error("[%s] Failed to edit Telegram message %s: %s", self.name, message_id, safe_error)
        return SendResult(success=False, error=safe_error)
