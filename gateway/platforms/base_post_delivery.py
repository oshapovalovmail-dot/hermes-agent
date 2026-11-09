"""Running a turn's one-shot post-delivery callback (``BasePlatformAdapter.register_post_delivery_callback``).

Shared by the adapter task that delivered a messaging reply (``_process_message_background``) and the
session authority's drain, which settles every turn no adapter task brackets (``session_ingress``).
"""
import asyncio
import contextlib
import inspect
from contextvars import ContextVar
from typing import Any

final_delivery_succeeded: ContextVar[bool] = ContextVar("final_delivery_succeeded", default=False)

async def run_post_delivery_callback(callback: Any, timeout: float, *, delivery_succeeded: bool = False) -> None:
    """Run *callback* (a no-op when None): bounded, errors swallowed, so a stuck or failing callback
    never holds up the session whose reply it follows."""
    if callable(callback):
        token = final_delivery_succeeded.set(delivery_succeeded)
        try:
            with contextlib.suppress(asyncio.TimeoutError, Exception):
                result = callback()
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, timeout=timeout)
        finally:
            final_delivery_succeeded.reset(token)
