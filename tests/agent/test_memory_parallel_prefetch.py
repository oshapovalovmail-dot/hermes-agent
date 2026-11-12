"""Native memory fan-out contracts: overlap, deadlines and profile isolation."""

from asyncio import CancelledError
import contextvars
import threading

import pytest

from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider, spawn_context_thread


class CallbackProvider(MemoryProvider):
    def __init__(self, name, callback):
        self._name = name
        self.callback = callback

    @property
    def name(self):
        return self._name

    def is_available(self):
        return True

    def initialize(self, session_id, **kwargs):
        pass

    def get_tool_schemas(self):
        return []

    def prefetch(self, query, *, session_id=""):
        return self.callback(query, session_id)


def test_independent_providers_start_before_either_completes():
    """Both real provider threads must enter before the test releases either."""
    started = [threading.Event(), threading.Event()]
    completed = [threading.Event(), threading.Event()]
    release = threading.Event()
    results = []

    def recall(index, query, session_id):
        started[index].set()
        assert release.wait(10), "test did not release recall"
        completed[index].set()
        return f"memory {index}"

    manager = MemoryManager(external_prefetch_timeout=10)
    for index in range(2):
        manager.add_provider(CallbackProvider(
            f"parallel-{index}", lambda q, s, i=index: recall(i, q, s)))
    caller = spawn_context_thread(
        lambda: results.append(manager.prefetch_all("project details", session_id="session")),
        name="test-memory-fanout")
    caller.start()
    try:
        assert started[0].wait(2), "first provider did not start"
        assert started[1].wait(2), "second provider must start before first completes"
        assert not any(event.is_set() for event in completed)
    finally:
        release.set()
        caller.join(10)
    assert not caller.is_alive()
    assert results == ["memory 0\n\nmemory 1"]


def test_reverse_completion_keeps_registration_order():
    second_finished = threading.Event()
    completion_order = []

    def first(query, session_id):
        assert second_finished.wait(5)
        completion_order.append("first")
        return "first memory"

    def second(query, session_id):
        completion_order.append("second")
        second_finished.set()
        return "second memory"

    manager = MemoryManager(external_prefetch_timeout=10)
    manager.add_provider(CallbackProvider("first", first))
    manager.add_provider(CallbackProvider("second", second))
    assert manager.prefetch_all("project details") == "first memory\n\nsecond memory"
    assert completion_order == ["second", "first"]


def test_timeout_does_not_suppress_peer_or_deliver_late_results(monkeypatch):
    from agent import memory_manager as mm

    release = threading.Event()
    started = threading.Event()
    peer_started = threading.Event()
    worker = []
    spills = []
    callbacks = []
    monkeypatch.setattr(mm, "spill_if_oversized", lambda text, **kw: spills.append(text) or text)

    def slow(query, session_id):
        if query != "old topic":
            return "current memory"
        worker.append(threading.current_thread())
        started.set()
        assert release.wait(10)
        return "expired memory"

    def healthy(query, session_id):
        peer_started.set()
        return "healthy memory"

    manager = MemoryManager(external_prefetch_timeout=2)
    manager.add_provider(CallbackProvider("slow", slow))
    manager.add_provider(CallbackProvider("healthy", healthy))
    try:
        callbacks.append(manager.prefetch_all("old topic", session_id="old"))
        assert started.is_set() and peer_started.is_set()
        assert callbacks == ["healthy memory"]
        callbacks.append(manager.prefetch_all("new topic", session_id="new"))
        assert callbacks[-1] == "current memory\n\nhealthy memory"
        before = list(spills)
    finally:
        release.set()
        for thread in worker:
            thread.join(5)
            assert not thread.is_alive()
    assert callbacks == ["healthy memory", "current memory\n\nhealthy memory"]
    assert spills == before
    assert "expired memory" not in spills
    assert not manager._PREFETCH_GATE.calls.get(manager._registry_key(manager.providers[0]))


@pytest.mark.parametrize("error", [RuntimeError("unavailable"), PermissionError("denied")])
def test_provider_error_is_isolated_without_partial_recall(error):
    def fail(query, session_id):
        raise error

    manager = MemoryManager()
    manager.add_provider(CallbackProvider("failed", fail))
    manager.add_provider(CallbackProvider("healthy", lambda q, s: "healthy memory"))
    assert manager.prefetch_all("project details") == "healthy memory"


def test_provider_cancellation_propagates_instead_of_becoming_empty_recall():
    from asyncio import CancelledError

    cancelled = CancelledError("caller cancelled")

    def cancel(query, session_id):
        raise cancelled

    manager = MemoryManager()
    provider = CallbackProvider("cancelled", cancel)
    manager.add_provider(provider)
    with pytest.raises(CancelledError) as caught:
        manager.prefetch_all("project details")
    assert caught.value is cancelled
    assert manager._registry_key(provider) not in manager._PREFETCH_GATE.calls


def test_parallel_calls_keep_profile_home_secrets_and_context_identity(tmp_path):
    from agent.secret_scope import (get_secret, reset_multiplex_context, reset_secret_scope,
                                    set_multiplex_context, set_secret_scope)
    from hermes_constants import (get_hermes_home, reset_hermes_home_override,
                                 set_hermes_home_override)

    identity = contextvars.ContextVar("prefetch_test_identity", default="unbound")
    entered = [threading.Event() for _ in range(4)]
    release = threading.Event()
    observations = []
    results = {}
    callers = []
    multiplex_token = set_multiplex_context(True)

    def recall(index, query, session_id):
        observations.append((str(get_hermes_home()), get_secret("MEMORY_TEST_KEY"),
                             identity.get(), query, session_id))
        entered[index].set()
        assert release.wait(10)
        return f"context {index}"

    try:
        for profile in range(2):
            home = tmp_path / f"profile-{profile}"
            home.mkdir()
            home_token = set_hermes_home_override(str(home))
            secret_token = set_secret_scope({"MEMORY_TEST_KEY": f"key-{profile}"}, profile_home=str(home))
            identity_token = identity.set(f"identity-{profile}")
            try:
                manager = MemoryManager(external_prefetch_timeout=10)
                for provider in range(2):
                    index = profile * 2 + provider
                    manager.add_provider(CallbackProvider(
                        f"provider-{provider}", lambda q, s, i=index: recall(i, q, s)))
                manager.initialize_all(f"session-{profile}", agent_identity=f"identity-{profile}")
                caller = spawn_context_thread(
                    lambda m=manager, p=profile: results.update({p: m.prefetch_all(
                        f"topic {p}", session_id=f"session-{p}")}), name=f"test-profile-{profile}")
                callers.append(caller)
                caller.start()
            finally:
                identity.reset(identity_token)
                reset_secret_scope(secret_token)
                reset_hermes_home_override(home_token)
        assert all(event.wait(2) for event in entered)
    finally:
        release.set()
        for caller in callers:
            caller.join(10)
            assert not caller.is_alive()
        reset_multiplex_context(multiplex_token)
    assert results == {0: "context 0\n\ncontext 1", 1: "context 2\n\ncontext 3"}
    for profile in range(2):
        expected = (str(tmp_path / f"profile-{profile}"), f"key-{profile}",
                    f"identity-{profile}", f"topic {profile}", f"session-{profile}")
        assert observations.count(expected) == 2


def test_individual_deadlines_reject_finished_but_overdue_peer(monkeypatch):
    """Native workers + a controlled clock: collecting late cannot extend a budget."""
    from types import SimpleNamespace
    from agent import memory_manager_prefetch as prefetch

    now = [0.0]
    monkeypatch.setattr(prefetch, "time", SimpleNamespace(monotonic=lambda: now[0]))
    releases = [threading.Event(), threading.Event()]
    entered = [threading.Event(), threading.Event()]
    workers: dict[int, threading.Thread] = {}

    def recall(index, query, session_id):
        workers[index] = threading.current_thread()
        entered[index].set()
        assert releases[index].wait(10)
        return f"memory {index}"

    manager = MemoryManager(external_prefetch_timeout=2)
    providers = [CallbackProvider(f"deadline-{i}", lambda q, s, i=i: recall(i, q, s)) for i in range(2)]
    collectors = []
    try:
        for provider in providers:
            manager.add_provider(provider)
            collectors.append(prefetch.start_prefetch(manager, provider, "topic"))
        assert all(event.wait(2) for event in entered)
        now[0] = 1.0
        releases[0].set()
        workers[0].join(5)
        assert not workers[0].is_alive()
        now[0] = 3.0
        releases[1].set()
        workers[1].join(5)
        assert not workers[1].is_alive()
        assert collectors[0]() == "memory 0"
        assert collectors[1]() == ""
    finally:
        for event in releases:
            event.set()
        for worker in workers.values():
            worker.join(5)
            assert not worker.is_alive()


def test_inflight_cap_skips_only_wedged_provider_across_managers(monkeypatch):
    from agent import memory_manager as mm

    monkeypatch.setattr(mm, "_MAX_INFLIGHT_CALLS", 1)
    release = threading.Event()
    entered = threading.Event()
    workers = []
    calls = []

    def wedged(query, session_id):
        calls.append(query)
        workers.append(threading.current_thread())
        entered.set()
        assert release.wait(10)
        return "expired memory"

    provider = CallbackProvider("capped", wedged)
    manager = MemoryManager(external_prefetch_timeout=2)
    manager.add_provider(provider)
    try:
        assert manager.prefetch_all("old topic") == ""
        assert entered.is_set()
        for _ in range(3):
            another = MemoryManager(external_prefetch_timeout=2)
            another.add_provider(provider)
            another.add_provider(CallbackProvider("healthy", lambda q, s: "peer"))
            assert another.prefetch_all("current topic") == "peer"
        assert calls == ["old topic"]
        assert len(manager._PREFETCH_GATE.calls[manager._registry_key(provider)]) == 1
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive()
    assert manager._registry_key(provider) not in manager._PREFETCH_GATE.calls


@pytest.mark.parametrize("failure", [RuntimeError("thread start failed"), KeyboardInterrupt("cancel start")])
def test_thread_start_failure_releases_admission_and_preserves_exception(monkeypatch, failure):
    from agent import memory_manager as mm

    def not_started(target, **kwargs):
        thread = spawn_context_thread(target, **kwargs)
        thread.start = lambda: throw()
        return thread

    def throw():
        raise failure

    monkeypatch.setattr(mm, "spawn_context_thread", not_started)
    manager = MemoryManager()
    provider = CallbackProvider("start-failed", lambda q, s: "must not be called")
    manager.add_provider(provider)
    with pytest.raises(type(failure)) as caught:
        manager._prefetch_provider(provider, "topic")
    assert caught.value is failure
    assert manager._registry_key(provider) not in manager._PREFETCH_GATE.calls


@pytest.mark.parametrize("stage", ["before-bootstrap", "provider-running"])
@pytest.mark.parametrize("failure", [KeyboardInterrupt("cancel start ACK"), CancelledError("cancel start ACK")])
def test_start_ack_cancellation_keeps_real_worker_admitted(monkeypatch, stage, failure):
    """A real OS worker owns its slot even before Thread.start's bootstrap ACK."""
    from agent import memory_manager as mm

    bootstrap_entered = threading.Event()
    bootstrap_release = threading.Event()
    provider_entered = threading.Event()
    provider_release = threading.Event()
    workers = []
    calls = []
    real_os_start = threading._start_joinable_thread

    def recall(query, session_id):
        calls.append(query)
        provider_entered.set()
        assert provider_release.wait(10), "test did not release real provider"
        return "private late outcome"

    def make_worker(target, **kwargs):
        thread = spawn_context_thread(target, **kwargs)
        workers.append(thread)
        bootstrap = thread._bootstrap

        def delayed_bootstrap():
            bootstrap_entered.set()
            assert bootstrap_release.wait(10), "test did not release bootstrap"
            bootstrap()

        if stage == "before-bootstrap":
            thread._bootstrap = delayed_bootstrap
        return thread

    def interrupt_start_ack(*args, **kwargs):
        real_os_start(*args, **kwargs)
        entered = bootstrap_entered if stage == "before-bootstrap" else provider_entered
        assert entered.wait(2), "real OS worker did not enter injected boundary"
        raise failure

    monkeypatch.setattr(mm, "spawn_context_thread", make_worker)
    monkeypatch.setattr(mm, "_MAX_INFLIGHT_CALLS", 1)
    manager = MemoryManager(external_prefetch_timeout=10)
    provider = CallbackProvider("cancel-start-ack", recall)
    manager.add_provider(provider)
    key = manager._registry_key(provider)
    try:
        with monkeypatch.context() as startup:
            startup.setattr(threading, "_start_joinable_thread", interrupt_start_ack)
            with pytest.raises(type(failure)) as caught:
                manager.prefetch_all("cancelled topic")
        assert caught.value is failure
        if stage == "before-bootstrap":
            assert not workers[0].is_alive(), "fixture must precede the bootstrap ACK"
        assert workers[0] in manager._PREFETCH_GATE.calls.get(key, {}), (
            "real OS worker lost admission after cancelled start ACK")
        another = MemoryManager(external_prefetch_timeout=10)
        another.add_provider(provider)
        assert another.prefetch_all("must be capped") == ""
        assert len(workers) == 2  # the rejected worker is constructed, never started
        assert calls == ([] if stage == "before-bootstrap" else ["cancelled topic"])
    finally:
        bootstrap_release.set()
        provider_release.set()
        if workers:
            assert provider_entered.wait(2), "real provider never reached cleanup"
            workers[0].join(5)
            assert not workers[0].is_alive()
    assert key not in manager._PREFETCH_GATE.calls


def test_native_no_start_failure_releases_admission(monkeypatch):
    from agent import memory_manager as mm

    failure = RuntimeError("OS refused to create a thread")
    calls = []

    def fail_os_start(*args, **kwargs):
        raise failure

    manager = MemoryManager()
    provider = CallbackProvider("native-no-start", lambda q, s: calls.append(q))
    manager.add_provider(provider)
    with monkeypatch.context() as startup:
        startup.setattr(threading, "_start_joinable_thread", fail_os_start)
        with pytest.raises(RuntimeError) as caught:
            manager._prefetch_provider(provider, "topic")
    assert caught.value is failure
    assert calls == []
    assert manager._registry_key(provider) not in manager._PREFETCH_GATE.calls
