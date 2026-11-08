"""Self-post acknowledges only 2xx, with no redirect or leaked wake capability."""
import logging
from types import SimpleNamespace

import aiohttp
import pytest

from gateway import wake


@pytest.fixture
def transport(monkeypatch, caplog):
    adapter = SimpleNamespace(_api_key="fixture-only", _host="127.0.0.1", _port=8642)
    state = SimpleNamespace(statuses=[], calls=[], reads=[], closed=0, tickets=[])

    class Response:
        def __init__(self, status):
            self.status = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def text(self):
            return "fixture response"

        async def read(self):
            state.reads.append(self.status)
            return b"{}"

    class Session:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            state.closed += 1
            return False

        def post(self, url, *, json, headers, allow_redirects):
            assert allow_redirects is False
            ticket = headers["X-Hermes-Runtime-Wake"]
            assert adapter._runtime_wake_tickets == {ticket: ("saved-session", "wake body")}
            state.calls.append((url, json, headers))
            state.tickets.append(ticket)
            status = state.statuses.pop(0)
            if isinstance(status, Exception):
                raise status
            return Response(status)

    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    monkeypatch.setattr(wake, "_RETRY_DELAYS_SECONDS", (0, 0))
    caplog.set_level(logging.INFO, logger=wake.logger.name)
    return adapter, state


async def send(adapter):
    await wake._self_post_chat_completion(adapter, text="wake body", session_id="saved-session")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [100, 199, 301, 302, 307, 308, 400, 401, 403, 500])
async def test_non_success_is_not_delivered_and_cleans_capability(transport, caplog, status):
    adapter, state = transport
    state.statuses = [status]
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        await send(adapter)
    assert len(state.calls) == state.closed == 1
    assert state.reads == []
    assert adapter._runtime_wake_tickets == {}
    assert "wake self-post delivered" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
async def test_success_consumes_body_and_cleans_capability(transport, caplog, status):
    adapter, state = transport
    state.statuses = [status]
    await send(adapter)
    assert state.reads == [status]
    assert len(state.calls) == state.closed == 1
    assert adapter._runtime_wake_tickets == {}
    assert "wake self-post delivered" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("first", [429, TimeoutError(), aiohttp.ClientError("offline"), OSError("offline")])
async def test_transient_retry_uses_fresh_capability(transport, caplog, first):
    adapter, state = transport
    state.statuses = [first, 200]
    await send(adapter)
    assert len(state.calls) == state.closed == 2
    assert len(set(state.tickets)) == 2
    assert state.reads == [200]
    assert adapter._runtime_wake_tickets == {}
    assert caplog.text.count("wake self-post delivered") == 1


@pytest.mark.asyncio
async def test_exhausted_concurrency_retries_never_acknowledge_delivery(transport, caplog):
    adapter, state = transport
    state.statuses = [429, 429, 429]
    with pytest.raises(RuntimeError, match="gave up.*after 3 attempts"):
        await send(adapter)
    assert len(state.calls) == state.closed == 3
    assert len(set(state.tickets)) == 3
    assert adapter._runtime_wake_tickets == {}
    assert "wake self-post delivered" not in caplog.text
