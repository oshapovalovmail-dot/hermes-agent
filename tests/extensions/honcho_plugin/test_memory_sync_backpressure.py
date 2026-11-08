"""Honcho transport latency must not become foreground turn backpressure."""
import threading
from memory_test_plugins.honcho.session import HonchoSession, HonchoSessionManager

from memory_test_plugins.honcho import HonchoMemoryProvider
from memory_test_plugins.honcho.client import HonchoClientConfig


def test_next_turn_queues_while_previous_transport_is_blocked():
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    rows = []

    class Session:
        def add_message(self, role, content, **kwargs):
            rows.append((role, content))

    class Manager:
        def resolve_author_peer_id(self, *a, **kw):
            return None

        def save(self, session):
            self._flush_session(session)

        def get_or_create(self, session_key):
            return Session()

        def _flush_session(self, session):
            entered.set()
            assert release.wait(5), "test transport was not released"

    p = HonchoMemoryProvider()
    p._manager = Manager()
    p._session_key = "scoped-session"
    p._session_initialized = True
    p._config = HonchoClientConfig(enabled=True, save_messages=True)
    p.sync_turn("first user", "first answer")
    assert entered.wait(3)

    def submit_second():
        p.sync_turn("second user", "second answer")
        returned.set()

    caller = threading.Thread(target=submit_second, daemon=True)
    caller.start()
    try:
        assert returned.wait(2), "sync_turn waited on previous Honcho network IO"
    finally:
        release.set()
        caller.join(3)
        if p._sync_thread:
            p._sync_thread.join(3)
    assert not caller.is_alive()
    assert rows == [("user", "first user"), ("assistant", "first answer"),
                    ("user", "second user"), ("assistant", "second answer")]


def test_long_multilingual_query_searches_topic_beyond_vendor_names(monkeypatch):
    from types import SimpleNamespace

    hit = SimpleNamespace(content="Weekend and weekday routing schedule: ServiceAlpha uses RouterBeta.",
                          peer_id="reader", session_id="schedule", metadata={})
    noise = SimpleNamespace(content="ProviderDelta ModelGamma ServiceAlpha RouterBeta price report",
                            peer_id="writer", session_id="prices", metadata={})
    queries = []

    class Client:
        def search(self, query, **kwargs):
            queries.append(query)
            return [hit] if query.casefold() in {"расписание", "выходные"} else [noise]

    client = Client()
    monkeypatch.setattr("memory_test_plugins.honcho.session.get_honcho_client", lambda *a, **k: client)
    cfg = HonchoClientConfig(enabled=True, base_url="http://localhost:1")
    manager = HonchoSessionManager(honcho=client, config=cfg)
    session = HonchoSession("local", "reader", "writer", "remote")
    manager._cache[session.key] = session
    text = manager.search_context(
        session.key,
        "Расписание ServiceAlpha RouterBeta ModelGamma ProviderDelta выходные",
        max_tokens=700,
    )
    assert "routing schedule" in text, "all fallback anchors were vendor/model names"
    assert any(q.casefold() in {"расписание", "выходные"} for q in queries)


def test_numeric_rule_is_not_lost_to_common_project_boilerplate(monkeypatch):
    from types import SimpleNamespace

    target = SimpleNamespace(
        content="QYP original50 work context. " + ("unrelated implementation details " * 90)
                + "Actual private-artifact rule: umask 0077 must be used for output.",
        peer_id="reader", session_id="private-rule", metadata={},
    )
    noise = [SimpleNamespace(content="QYP original50 work context and general deployment report " + str(i),
                             peer_id="writer", session_id=f"deployment-{i}", metadata={})
             for i in range(3)]

    class Client:
        def search(self, *args, **kwargs):
            return [target] + noise

    client = Client()
    monkeypatch.setattr("memory_test_plugins.honcho.session.get_honcho_client", lambda *a, **k: client)
    cfg = HonchoClientConfig(enabled=True, base_url="http://localhost:1")
    manager = HonchoSessionManager(honcho=client, config=cfg)
    session = HonchoSession("local", "reader", "writer", "remote")
    manager._cache[session.key] = session
    text = manager.search_context(session.key, "QYP original50 umask 0077", max_tokens=300)
    assert "umask 0077" in text, "excerpt retained common project names but lost the requested numeric rule"
