"""Exact producer capabilities do not turn authenticated public text into runtime origin."""
from types import SimpleNamespace

import pytest
from aiohttp import web

from agent.capture_origin import capture_messages
from gateway.platforms.api_server_capture import capture_runtime_turn, runtime_wake_kwargs


def test_runtime_ticket_is_exact_single_use_and_not_public_metadata():
    adapter = SimpleNamespace(_runtime_wake_tickets={"ticket": ("session", "machine")})
    request = SimpleNamespace(headers={"X-Hermes-Runtime-Wake": "ticket"})
    rows = [{"role": "user", "content": "machine"}]
    assert runtime_wake_kwargs(adapter, request, "session", "machine", rows, False) == {"_runtime_payload": "machine"}
    with pytest.raises(web.HTTPForbidden):
        runtime_wake_kwargs(adapter, request, "session", "machine", rows, False)
    assert runtime_wake_kwargs(adapter, SimpleNamespace(headers={}), "session", "machine", rows, False) == {}


@pytest.mark.parametrize("session,text,stream", [("foreign", "machine", False), ("session", "changed", False), ("session", "machine", True)])
def test_foreign_or_changed_ticket_is_consumed_without_origin(session, text, stream):
    adapter = SimpleNamespace(_runtime_wake_tickets={"ticket": ("session", "machine")})
    request = SimpleNamespace(headers={"X-Hermes-Runtime-Wake": "ticket"})
    with pytest.raises(web.HTTPForbidden):
        runtime_wake_kwargs(adapter, request, session, text, [{"role": "user", "content": text}], stream)
    assert not adapter._runtime_wake_tickets


@pytest.mark.asyncio
async def test_api_scope_wraps_native_dispatch_and_restores_caller():
    class Adapter:
        @capture_runtime_turn
        async def run(self, user_message):
            return capture_messages(user_message, "answer", None)
    rows = await Adapter().run(user_message="machine", _runtime_payload="machine")
    assert rows[0]["source_kind"] == "machine_notification"
    assert capture_messages("machine", "answer", None) is None
