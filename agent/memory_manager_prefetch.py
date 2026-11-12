"""Start bounded provider recall before collecting it in registration order."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from functools import partial
from typing import Callable


def start_prefetch(manager, provider, query: str, *, session_id: str = "") -> Callable[[], str]:
    """Return a caller-owned collector; only an admitted external call gets a thread.

    The builtin stays inline (no new worker on builtin-only agents). All external
    calls start before any collector waits, including a preceding builtin collector.
    """
    from agent import memory_manager as mm

    if provider.name == "builtin":
        return partial(provider.prefetch, query, session_id=session_id)

    started_at = time.monotonic()
    deadline = started_at + manager._external_prefetch_timeout
    outcome: Future = Future()
    key = manager._registry_key(provider)

    def run() -> None:
        ok = False
        try:
            value = provider.prefetch(query, session_id=session_id) or ""
        except BaseException as exc:  # health: allow BLE001 -- forward every provider exception across the thread boundary, including cancellation
            # Transport thread boundaries must FORWARD cancellation/SystemExit as
            # well as ordinary errors, never convert them to successful empty recall.
            outcome.set_result((time.monotonic(), "", exc))
        else:
            ok = True
            outcome.set_result((time.monotonic(), value, None))
        finally:
            manager._PREFETCH_GATE.leave(key, thread, ok=ok)

    thread = mm.spawn_context_thread(run, name=f"memory-prefetch-{provider.name}")
    skipped = manager._PREFETCH_GATE.enter(key, thread, manager._external_prefetch_timeout)
    if skipped:
        mm.logger.debug("Memory provider '%s' prefetch skipped (%d stuck, %d in flight)",
                        provider.name, *skipped[:2])
        return lambda: ""
    try:
        thread.start()
    finally:
        # Native start registers the thread before launching it; enumerate includes
        # that pending-bootstrap state, where is_alive() is still False. Only an
        # unregistered thread with no identity proves no worker owns this slot.
        if thread.ident is None and thread not in threading.enumerate():
            manager._PREFETCH_GATE.leave(key, thread, ok=False)

    def collect() -> str:
        # Waiting for earlier providers must not give later providers another full
        # timeout. Completion time also fences results that finish before collection
        # but AFTER their own deadline. Late threads own only this private outcome.
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive() or outcome.result()[0] > deadline:
            mm.logger.warning(
                "Memory provider '%s' prefetch timed out after %.1fs; the call keeps running in the "
                "background (later turns may skip it while the provider stays stuck)", provider.name,
                manager._external_prefetch_timeout,
            )
            return ""
        completed_at, result, error = outcome.result()
        mm.logger.debug("Memory provider '%s' prefetch completed in %.3fs", provider.name, completed_at - started_at)
        if error is not None:
            raise error
        if result and result.strip():
            result = mm.spill_if_oversized(
                result, session_id=session_id, source=f"{provider.name} memory prefetch",
                config=manager._external_prefetch_spill_config,
            )
        return result

    return collect


def prefetch_providers(manager, query: str, *, session_id: str = "") -> str:
    """Fan out a snapshot, then return an immutable merge; failures stay per-provider."""
    from agent import memory_manager as mm

    pending = []
    for provider in manager.providers:
        try:
            pending.append((provider, start_prefetch(manager, provider, query, session_id=session_id)))
        except Exception as exc:  # health: allow BLE001 -- isolate and log backend-specific provider startup failures; cancellation still propagates
            mm.logger.debug("Memory provider '%s' prefetch failed (non-fatal): %s", provider.name, exc)
    parts = []
    for provider, collect in pending:
        try:
            result = collect()
            if result and result.strip():
                parts.append(result)
        except Exception as exc:  # health: allow BLE001 -- preserve per-provider nonfatal recall failures without dropping healthy peers
            mm.logger.debug("Memory provider '%s' prefetch failed (non-fatal): %s", provider.name, exc)
    return "\n\n".join(parts)
