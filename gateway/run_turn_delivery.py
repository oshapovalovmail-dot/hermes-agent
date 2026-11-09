"""Receipt-aware stream reconciliation for the modern gateway turn facade."""
from __future__ import annotations

import inspect
import logging

logger = logging.getLogger("gateway.run")


class GatewayTurnDeliveryMixin:
    """Keep unknown acceptance distinct from confirmed delivery and safe fallback."""

    async def _hmwa_deliver_turn_response(
        self, event, source, session_entry, session_key, run_generation,
        agent_result, agent_messages, response, _footer_line, _intentional_silence,
    ):
        """Uncertain stream acceptance is not confirmed delivery or permission to resend."""
        if agent_result.get("delivery_uncertain") is True:
            logger.warning("Final delivery receipt uncertain for session %s; not resending body.", session_key)
            return None
        return await super()._hmwa_deliver_turn_response(
            event, source, session_entry, session_key, run_generation,
            agent_result, agent_messages, response, _footer_line, _intentional_silence,
        )


    async def _run_agent_edit_streamed_message(
        self, _sc, source, response, content, *, _sk, ok, fail_result: str, fail_exc: str,
    ) -> None:
        """Edit the stream consumer's message in place with ``content``; on success mark
        ``response["already_sent"]`` and log ``ok``. A returned failure logs ``fail_result`` as
        ``(session, error)`` and an exception logs ``fail_exc`` as ``(session, exc)``; either way
        ``already_sent`` stays unset so the normal final send delivers the content."""
        try:
            kwargs = dict(chat_id=source.chat_id, message_id=_sc.message_id,
                          content=content, finalize=True)
            params = inspect.signature(_sc.adapter.edit_message).parameters
            if "metadata" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
                kwargs["metadata"] = getattr(_sc, "metadata", None) or self._thread_metadata_for_source(source)
            _res = await _sc.adapter.edit_message(**kwargs)
        except Exception as _edit_err:
            logger.warning(fail_exc, _sk, _edit_err, exc_info=True)
            return
        if getattr(_res, "delivery_uncertain", False) is True:
            response["delivery_uncertain"] = True
            logger.warning("Stream reconciliation receipt uncertain for session %s; not resending.", _sk)
            return
        if getattr(_res, "success", False) is not True:
            logger.warning(fail_result, _sk, getattr(_res, "error", None))
            return
        response["already_sent"] = True
        logger.info(*ok)
