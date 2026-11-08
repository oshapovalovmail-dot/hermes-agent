"""Independent read-only regressions for Honcho writer exit and dual-provider fan-out."""
import threading
from memory_test_plugins.honcho import HonchoMemoryProvider
from memory_test_plugins.honcho.client import HonchoClientConfig
from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider


def test_last_turn_is_not_stranded_when_enqueue_races_worker_return():
    finishing, release = threading.Event(), threading.Event()
    rows = []

    class Session:
        def add_message(self, role, content, **kwargs):
            rows.append((role, content))

    class Manager:
        def resolve_author_peer_id(self, *a, **kw):
            return None

        def save(self, session):
            self._flush_session(session)

        def get_or_create(self, key):
            return Session()

        def _flush_session(self, session):
            pass

        def flush_all(self):
            pass

    provider = HonchoMemoryProvider()
    provider._manager, provider._session_key = Manager(), "review-session"
    provider._session_initialized = True
    provider._config = HonchoClientConfig(enabled=True, save_messages=True)
    workers = []

    def trace(frame, event, arg):
        if frame.f_code.co_name == "_sync" and event == "return":
            finishing.set()
            assert release.wait(5)
        return trace

    previous = threading.gettrace()
    threading.settrace(trace)
    try:
        provider.sync_turn("first", "answer-one")
        workers.append(provider._sync_thread)
        assert finishing.wait(3)
        provider.sync_turn("last", "answer-last")
        workers.append(provider._sync_thread)
        release.set()
        for worker in workers:
            worker.join(3)
            assert not worker.is_alive()
        provider.on_session_end([])
        assert not provider._pending_turns
        assert rows == [("user", "first"), ("assistant", "answer-one"),
                        ("user", "last"), ("assistant", "answer-last")]
    finally:
        release.set()
        threading.settrace(previous)
        for worker in workers:
            worker.join(3)


def test_stalled_honcho_does_not_block_other_provider_next_turn():
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Session:
        def add_message(self, role, content, **kwargs):
            pass

    class Manager:
        def resolve_author_peer_id(self, *a, **kw):
            return None

        def save(self, session):
            self._flush_session(session)

        def get_or_create(self, key):
            return Session()

        def _flush_session(self, session):
            entered.set()
            assert release.wait(5)

    class Other(MemoryProvider):
        @property
        def name(self):
            return "independent-other"

        def is_available(self):
            return True

        def initialize(self, session_id, **kwargs):
            pass

        def sync_turn(self, user_content, assistant_content, **kwargs):
            calls.append(user_content)

        def system_prompt_block(self):
            return ""

        def get_tool_schemas(self):
            return []

        def handle_tool_call(self, tool_name, args, **kwargs):
            return "{}"

    provider = HonchoMemoryProvider()
    provider._manager, provider._session_key = Manager(), "review-session"
    provider._session_initialized = True
    provider._config = HonchoClientConfig(enabled=True, save_messages=True)
    manager = MemoryManager()
    manager.add_provider(provider)
    manager.add_provider(Other())
    try:
        manager.sync_all("first", "answer-one")
        assert entered.wait(3)
        assert manager.flush_pending(timeout=3)
        manager.sync_all("last", "answer-last")
        assert manager.flush_pending(timeout=2)
        assert calls == ["first", "last"]
    finally:
        release.set()
        manager.flush_pending(timeout=3)
        if provider._sync_thread:
            provider._sync_thread.join(3)
