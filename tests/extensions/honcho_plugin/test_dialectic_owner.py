"""Dialectic calls execute against their captured owner and discard stale generations."""
import threading
from types import SimpleNamespace

import pytest

from memory_test_plugins.honcho import HonchoMemoryProvider


@pytest.fixture
def dialectic():
    provider = HonchoMemoryProvider()
    calls = []

    def query(session, prompt, **kwargs):
        calls.append((session, prompt, kwargs))
        return "Telescope evidence."

    provider._manager = SimpleNamespace(dialectic_query=query)
    provider._session_key = "owner-session"
    provider._dialectic_depth = 2
    provider._activate_recall("telescope", "thread-a")
    return provider, calls


@pytest.mark.parametrize("captured", [False, True])
def test_depth_calls_backend_with_captured_or_current_owner(dialectic, captured):
    provider, calls = dialectic
    owner = (provider._manager, provider._session_key, provider._recall_generation)
    if captured:
        # A delayed worker must not dereference a replacement manager/session.
        provider._manager = None
        provider._session_key = "replacement-session"
    result = provider._run_dialectic_depth("telescope", **({"_owner": owner} if captured else {}))
    assert result == "Telescope evidence."
    assert len(calls) == 2
    assert all(session == "owner-session" and "telescope" in prompt for session, prompt, _ in calls)
    assert all(kw["raise_errors"] is True and kw["apply_injection_cap"] is False for _, _, kw in calls)


def test_depth_propagates_backend_exception(dialectic):
    provider, _ = dialectic
    def fail(*args, **kwargs):
        raise RuntimeError("backend boundary failure")
    provider._manager.dialectic_query = fail
    with pytest.raises(RuntimeError, match="backend boundary failure"):
        provider._run_dialectic_depth("telescope")


@pytest.mark.parametrize("aba", [False, True])
def test_depth_discards_pivot_during_final_backend_call(dialectic, aba):
    provider, calls = dialectic
    provider._dialectic_depth = 1
    def pivot(session, prompt, **kwargs):
        calls.append(session)
        provider._activate_recall("microscope", "thread-b")
        if aba:
            provider._activate_recall("telescope", "thread-a")
        return "Telescope stale evidence."
    provider._manager.dialectic_query = pivot
    assert provider._run_dialectic_depth("telescope") == ""
    assert calls == ["owner-session"]


def test_stale_captured_owner_never_calls_backend(dialectic):
    provider, calls = dialectic
    owner = (provider._manager, provider._session_key, provider._recall_generation)
    provider._activate_recall("microscope", "thread-b")
    assert provider._run_dialectic_depth("telescope", _owner=owner) == ""
    assert calls == []


@pytest.mark.parametrize("pivot", [False, True, "switch-hook"])
def test_automatic_worker_executes_real_depth_and_fences_session_aba(dialectic, pivot):
    provider, calls = dialectic
    started, release = threading.Event(), threading.Event()
    provider._dialectic_depth = 1
    def query(session, prompt, **kwargs):
        calls.append(session)
        started.set()
        assert release.wait(5), "test did not release backend"
        return "Telescope historical evidence."
    provider._manager.dialectic_query = query
    generation = provider._recall_generation
    provider._start_dialectic_refresh("telescope", generation)
    worker = provider._prefetch_thread
    try:
        assert started.wait(5), "real depth never reached the backend"
        if pivot:
            if pivot == "switch-hook":
                # A pinned backend session need not change before the next prefetch.
                provider.on_session_switch("thread-b")
                provider.on_session_switch("thread-a")
            else:
                provider._session_key = "other-session"
                provider._activate_recall("telescope", "thread-a")
                provider._session_key = "owner-session"
                provider._activate_recall("telescope", "thread-a")
            assert provider._recall_generation != generation
            provider._start_dialectic_refresh("telescope", provider._recall_generation)
            assert provider._prefetch_thread is worker
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert calls == ["owner-session"]
    assert provider._consume_pending_dialectic() == ("" if pivot else "Telescope historical evidence.")
    assert provider._dialectic_empty_streak == 0


def test_session_switch_discards_base_worker_with_pinned_backend(dialectic):
    provider, calls = dialectic
    started, release = threading.Event(), threading.Event()
    def fetch(session, query):
        calls.append(session)
        started.set()
        assert release.wait(5)
        return {"representation": "Telescope stale evidence."}
    provider._manager.get_prefetch_context = fetch
    generation = provider._recall_generation
    worker = provider._start_base_refresh("telescope", generation)
    try:
        assert started.wait(5)
        provider.on_session_switch("thread-b")
        provider.on_session_switch("thread-a")
        assert provider._recall_generation != generation
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert calls == ["owner-session"]
    assert provider._base_context_data == {}
