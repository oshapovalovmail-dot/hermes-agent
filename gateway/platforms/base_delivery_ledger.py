"""Final-delivery ledger settlement shared by platform adapters."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from gateway.platforms.base import BasePlatformAdapter
    from gateway.platforms.event import MessageEvent

logger = logging.getLogger(__name__)


async def finalize_delivery_obligation(
    adapter: BasePlatformAdapter, obligation_id: str, result: Any, event: MessageEvent,
    delivery_adapter: BasePlatformAdapter,
) -> None:
    """Settle a receipt; an uncertain send never grants an automatic replay."""
    try:
        from gateway.dead_targets import classify_dead_error
        from gateway.delivery_ledger import _update_state, is_reconnect_only, mark_delivered, mark_failed
        if getattr(result, "delivery_uncertain", False) is True:
            await asyncio.to_thread(_update_state, obligation_id, "unknown",
                                    error=str(getattr(result, "error", "") or "Delivery receipt unknown"))
            return
        if getattr(result, "success", False):
            await asyncio.to_thread(mark_delivered, obligation_id)
            return
        error = str(getattr(result, "error", "") or "")
        await asyncio.to_thread(mark_failed, obligation_id, error)
        if is_reconnect_only(error):
            redeliver: Any = getattr(
                adapter.gateway_runner, "_redeliver_failed_obligations_for_platform", None)
            live = adapter._final_delivery_adapter(event.source)
            if live is not delivery_adapter and callable(redeliver):
                await redeliver(event.source.platform,
                                profile=getattr(delivery_adapter, "_owner_profile", None))
        elif classify_dead_error(error) is None:
            schedule = getattr(adapter.gateway_runner, "_schedule_flood_redelivery", None)
            if callable(schedule):
                schedule(event.source.platform,
                         profile=getattr(delivery_adapter, "_owner_profile", None))
    except Exception:
        logger.debug("delivery ledger update failed", exc_info=True)
