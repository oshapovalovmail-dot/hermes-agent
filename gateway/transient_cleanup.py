"""Turn-owned temporary messages; never infer transience from message text."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from gateway.platforms.base_post_delivery import final_delivery_succeeded


class TransientCleanup:
    """Keep the owner and live receipt list after the session slot has moved on."""

    def __init__(self, adapter: Any, chat_id: str, ids: list[str], generation: int | None = None):
        self.adapter, self.chat_id, self.ids = adapter, chat_id, ids
        self.generation = generation
        self.loop = asyncio.get_running_loop()
        self.delivered = False
        self._deleted: set[str] = set()

    def track(self, result: Any) -> None:
        if not (getattr(result, "success", False) and getattr(result, "message_id", None)):
            return
        mid = str(result.message_id)
        if mid not in self.ids:
            self.ids.append(mid)
        if self.delivered:
            # Status receipts may arrive on the executor thread after final delivery.
            self.loop.call_soon_threadsafe(lambda: self.loop.create_task(self.delete_pending()))

    async def delete_pending(self) -> None:
        if not self.delivered:
            return
        for mid in list(self.ids):
            if mid in self._deleted:
                continue
            self._deleted.add(mid)
            with suppress(Exception):
                await self.adapter.delete_message(self.chat_id, mid)

    async def after_delivery(self) -> None:
        if self.delivered or final_delivery_succeeded.get():
            await self.confirm_delivery()

    async def confirm_delivery(self) -> None:
        self.delivered = True
        await self.delete_pending()


def cleanup_for_context(ctx: Any, adapter: Any) -> TransientCleanup:
    if ctx._transient_cleanup is None:
        ctx._transient_cleanup = TransientCleanup(
            adapter, ctx.source.chat_id, ctx._cleanup_msg_ids, ctx.run_generation)
    return ctx._transient_cleanup


def bind_turn_cleanup(runner: Any, ctx: Any, adapter: Any) -> None:
    """Adopt startup receipts only for exactly the same session generation and transport."""
    state = runner._peek_session_state(ctx.session_key) if ctx.session_key else None
    if state is None or state.persistent.run_generation != ctx.run_generation:
        return
    cleanup = state.turn.transient_cleanup
    if (cleanup is not None and cleanup.generation == ctx.run_generation
            and cleanup.adapter is adapter and cleanup.chat_id == ctx.source.chat_id):
        ctx._transient_cleanup, ctx._cleanup_msg_ids = cleanup, cleanup.ids
    else:
        state.turn.transient_cleanup = cleanup_for_context(ctx, adapter)


def busy_ack_cleanup(runner: Any, event: Any, adapter: Any) -> TransientCleanup | None:
    from gateway.bot_peer_notices import automatic_notices_allowed
    from gateway.config import Platform
    from gateway.display_config import resolve_display_setting
    from gateway.platforms.base import BasePlatformAdapter
    from gateway.run import _load_gateway_config, _platform_config_key

    if event.source.platform != Platform.TELEGRAM or not automatic_notices_allowed(event.source):
        return None
    if getattr(type(adapter), "delete_message", None) in (None, BasePlatformAdapter.delete_message):
        return None
    state = runner._peek_session_state(runner._session_key_for_source(event.source))
    if state is None:
        return None
    generation = state.persistent.run_generation
    ctx = state.turn.ctx
    if ctx is not None and ctx.run_generation == generation:
        return cleanup_for_context(ctx, adapter) if ctx._cleanup_progress else None
    if not resolve_display_setting(_load_gateway_config(), _platform_config_key(event.source.platform), "cleanup_progress"):
        return None
    cleanup = state.turn.transient_cleanup
    if cleanup is None or cleanup.generation != generation or cleanup.adapter is not adapter:
        cleanup = state.turn.transient_cleanup = TransientCleanup(adapter, event.source.chat_id, [], generation)
    return cleanup


def queued_cleanup_callback(runner: Any, ctx: Any, adapter: Any, *, failed: bool):
    """A recursive queued turn shares its generation, not the previous answer's receipts."""
    if not getattr(ctx, "_cleanup_progress", False) or adapter is None:
        return None
    cleanup = cleanup_for_context(ctx, adapter)
    state = runner._peek_session_state(ctx.session_key) if ctx.session_key else None
    if state is not None and state.turn.transient_cleanup is cleanup:
        state.turn.transient_cleanup = None
    return None if failed else cleanup.confirm_delivery
