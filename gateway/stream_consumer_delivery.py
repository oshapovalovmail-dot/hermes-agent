"""Typed delivery receipt fence for the stream consumer's business producers.

Uncertainty is turn-scoped, not segment-scoped. A missing receipt must neither
confirm the final nor trigger a resend through another consumer producer.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from gateway.platforms.base import SendResult

logger = logging.getLogger("gateway.stream_consumer")


class StreamDeliveryMixin:
    """Delivery-aware producers, ahead of transport/fallback mechanics in the MRO."""

    def _record_delivery_uncertainty(self, result) -> bool:
        if getattr(result, "delivery_uncertain", False) is True:
            self._delivery_uncertain = True
            self._final_response_sent = False
            self._final_content_delivered = False
            self._delivered_final_text = None
        return self._delivery_uncertain

    def _uncertain_result(self):
        return SendResult(success=False, error="Prior delivery receipt is uncertain",
                          delivery_uncertain=True)

    async def _send_content(self, **kwargs):
        if self._delivery_uncertain:
            return self._uncertain_result()
        result = await self.adapter.send(**kwargs)
        self._record_delivery_uncertainty(result)
        return result

    async def _edit_message(self, **kwargs):
        if self._delivery_uncertain:
            return self._uncertain_result()
        result = await super()._edit_message(**kwargs)
        self._record_delivery_uncertainty(result)
        return result

    async def _send_or_edit(self, *args, **kwargs):
        if self._delivery_uncertain:
            return False
        return await super()._send_or_edit(*args, **kwargs)

    async def _on_edit_failure(self, result, *args, **kwargs):
        if self._record_delivery_uncertainty(result):
            return False
        return await super()._on_edit_failure(result, *args, **kwargs)

    async def _send_fallback_final(self, text):
        if not self._delivery_uncertain:
            await super()._send_fallback_final(text)

    def _fallback_flood_retry_delay(self, result):
        if self._delivery_uncertain:
            return None
        return super()._fallback_flood_retry_delay(result)

    async def _try_fresh_final(self, text: str, *, is_turn_final: bool = True) -> bool:
        """Send ``text`` fresh and best-effort delete the preview(s); False on any failure so
        the caller falls back to edit.  ``is_turn_final=False`` leaves the delivery flag unset.

        ``is_turn_final`` is False when finalizing an interim segment at a tool boundary (a preamble) rather
        than the turn-final answer; the final-delivery flag is then left unset so the gateway still delivers
        the real answer from the next API call (#29346).
        Ported from openclaw/openclaw#72038.
        """
        if self._delivery_uncertain:
            return False
        # Replacing every preview is only sound while ``text`` holds the whole answer;
        # after a split, deleting sealed heads would erase delivered text.
        if self._turn_split_delivery:
            return False
        stale_ids = self._stale_preview_ids()
        try:
            result = await self._send_content(
                chat_id=self.chat_id, content=text, metadata=self._metadata_for_send(final=True))
        except Exception as e:
            logger.debug("Fresh-final send failed, falling back to edit: %s", e, exc_info=True)
            return False
        if not getattr(result, "success", False):
            return False
        new_message_id = getattr(result, "message_id", None)
        # Best-effort preview cleanup; never delete the message just sent.
        await self._delete_previews(stale_ids, skip=new_message_id, label="Fresh-final")
        self._preview_message_ids = set()
        self._adopt_message_id(new_message_id)
        self._already_sent = True
        self._last_sent_text = text
        if is_turn_final:
            self._final_response_sent = True
            self._record_turn_final_payload(text)
        return True


    async def _first_send(self, text: str, *, finalize: bool) -> bool:
        """First send, threaded to the user's message (correct topic/thread)."""
        if self._delivery_uncertain:
            return False
        if getattr(self, "_egress_declined", False):
            # The connector refused this destination earlier in the run (see
            # _send_draft_frame). This is where every fallback path converges,
            # so the check belongs here rather than at each caller.
            logger.warning(
                "suppressing the plain-send fallback: the connector already "
                "declined this destination for this run"
            )
            return False
        result = await self._send_content(
            chat_id=self.chat_id, content=text, reply_to=self._initial_reply_to_id,
            metadata=self._metadata_for_send(final=finalize, expect_edits=not finalize))
        if not result.success:
            self._edit_supported = False
            return False
        self._already_sent = True
        self._last_sent_text = text
        if result.message_id:
            self._adopt_message_id(result.message_id)
            self._track_preview_ids_from_result(result)
        else:
            # No editable id: fallback mode + sentinel so we don't re-enter first-send.
            self._enter_fallback_mode(self._visible_prefix())
            self._message_id = "__no_edit__"
        self._notify_new_message()
        return True


    async def _send_new_chunk(self, text: str, reply_to_id: Optional[str], *,
                              final: bool = False) -> Optional[str]:
        """Send a new chunk threaded to ``reply_to_id``; returns the new message_id."""
        if self._delivery_uncertain:
            return reply_to_id
        text = self._clean_for_display(text)
        if not text.strip():
            return reply_to_id
        try:
            result = await self._send_content(
                chat_id=self.chat_id, content=text, reply_to=reply_to_id,
                metadata=self._metadata_for_send(final=final, expect_edits=not final))
            if not (result.success and result.message_id):
                self._edit_supported = False
                return reply_to_id
            self._message_id = str(result.message_id)
            self._track_preview_ids_from_result(result)
            self._already_sent = True
            self._last_sent_text = text
            self._notify_new_message()
            return str(result.message_id)
        except Exception as e:
            logger.error("Stream send chunk error: %s", e, exc_info=True)
            return reply_to_id


    async def _send_with_flood_retry(self, *, content: str, retry_log: str, reply_to=None):
        """adapter.send(final metadata) with ONE bounded flood retry; returns the last
        SendResult.  Exceptions propagate (callers decide whether a raise is "ambiguous")."""
        if self._delivery_uncertain:
            return self._uncertain_result()
        kwargs = dict(chat_id=self.chat_id, content=content,
                      metadata=self._metadata_for_send(final=True))
        if reply_to is not None:
            kwargs["reply_to"] = reply_to
        result = None
        for attempt in range(2):
            result = await self._send_content(**kwargs)
            if getattr(result, "success", False):
                break
            retry_delay = self._fallback_flood_retry_delay(result)
            if attempt or retry_delay is None:
                break  # non-flood error, long flood wait, or second failure
            raw = getattr(result, "raw_response", None)
            if isinstance(raw, dict) and raw.get("partial_overflow"):
                break  # split head already on screen: re-sending the whole content duplicates it
            logger.debug(retry_log, retry_delay)
            await asyncio.sleep(retry_delay)
        return result


    async def _flush_segment_tail_on_edit_failure(self) -> None:
        """Before a segment reset, send the unseen tail as a new message (and best-effort
        strip the stuck cursor from the partial)."""
        if self._delivery_uncertain:
            return
        if getattr(self, "_egress_declined", False):
            return  # a new message is exactly the re-addressing the egress guard refused
        if not self._fallback_final_send:
            await self._try_strip_cursor()
        visible = self._fallback_prefix or self._visible_prefix()
        # Clean the whole buffer before cutting: a trailing silence marker cut off on its own
        # would read as a bare marker and survive the cleaner.
        tail = self._clean_for_display(self._accumulated)
        if visible and tail.startswith(visible):
            tail = tail[len(visible):].lstrip()
        if not tail.strip():
            return
        try:
            # Interim: must never seal a native stream (see _send_commentary).
            _md = dict(self.metadata) if self.metadata else {}
            _md["_interim_send"] = True
            result = await self._send_content(chat_id=self.chat_id, content=tail, metadata=_md)
            if result.success:
                self._already_sent = True
        except Exception as e:
            logger.error("Segment-break tail flush error: %s", e, exc_info=True)


    async def _send_commentary(self, text: str) -> bool:
        """Send a completed interim assistant commentary message."""
        if self._delivery_uncertain:
            return False
        text = self._clean_for_display(text)
        if not text.strip():
            return False
        try:
            # Interim: a stream-is-the-message adapter's seal-interception must not
            # turn this into draft(final=true), which would seal the live stream
            # with interim text and orphan the true final.
            _md = self._metadata_for_send(final=False) or {}
            _md["_interim_send"] = True
            # reply_to only for reply-anchored threading; Discord/Telegram use
            # thread_id metadata and reply_to on every commentary is spam.
            _plat = getattr(getattr(self.adapter, "platform", None), "value", None)
            _platform_name = str(_plat or getattr(self.adapter, "name", "")).lower()
            _needs_reply_anchor = _platform_name in ("buzz", "slack", "mattermost", "feishu")
            result = await self._send_content(
                chat_id=self.chat_id, content=text,
                reply_to=self._initial_reply_to_id if _needs_reply_anchor else None, metadata=_md)
            # Do NOT set _already_sent: commentary is interim, and the flag would
            # suppress the real final after multiple tool calls.
            if result.success:
                self._notify_new_message()
                # Lets run.py confirm whether an interim send carried the final.
                # Record the exact delivered text so run.py can confirm whether an interim "preview"
                # actually carried the final response, vs. unrelated commentary delivered during a session
                # split (#14238).
                self._delivered_commentary_texts.append(text)
            return result.success
        except Exception as e:
            logger.error("Commentary send error: %s", e, exc_info=True)
            return False
