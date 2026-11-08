"""Independent providers fan out without sacrificing first-writer tool ownership."""
from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider, is_trivial_prompt
from agent.agent_init_memory_provider import resolve_memory_provider_names as _resolve_memory_provider_names


class Provider(MemoryProvider):
    def __init__(self, name):
        self._name = name
        self.calls = []

    @property
    def name(self):
        return self._name

    def is_available(self):
        return True

    def initialize(self, **kwargs):
        self.calls.append("init")

    def get_tool_schemas(self):
        return [{"name": "shared_memory_query", "description": "query", "parameters": {"type": "object", "properties": {}}}]

    def handle_tool_call(self, name, args, **kwargs):
        return self.name

    def prefetch(self, query, **kwargs):
        self.calls.append(query)
        return self.name

    def shutdown(self):
        self.calls.append("shutdown")


def test_config_names_preserve_order_and_legacy_fallback():
    assert _resolve_memory_provider_names({"provider": "legacy"}) == ["legacy"]
    assert _resolve_memory_provider_names({"providers": [" a ", "b", "a", None, ""]}) == ["a", "b"]
    assert _resolve_memory_provider_names({"providers": [], "provider": "legacy"}) == []


def test_multiple_providers_recall_and_shutdown_in_registration_order():
    manager = MemoryManager()
    a, b = Provider("memory_a"), Provider("memory_b")
    for provider in (a, b, a):
        manager.add_provider(provider)
    assert manager.providers == [a, b]
    assert manager.prefetch_all("replica recovery") == "memory_a\n\nmemory_b"
    assert manager.handle_tool_call("shared_memory_query", {}) == "memory_a"
    manager.shutdown_all()
    assert a.calls == ["replica recovery", "shutdown"]
    assert b.calls == ["replica recovery", "shutdown"]


def test_subject_free_consent_is_not_a_recall_topic():
    assert is_trivial_prompt("Go ahead, you have my permission")
    assert is_trivial_prompt("Делай, разрешаю только для текущей задачи")
    assert not is_trivial_prompt("Continue with Nebula recovery")


def test_registration_failure_does_not_disable_other_providers(monkeypatch):
    from types import SimpleNamespace
    from agent import agent_init_memory_provider as init

    healthy = Provider("healthy")

    def resolve(name, **kwargs):
        if name == "broken":
            raise RuntimeError("fixture provider unavailable")
        return healthy

    monkeypatch.setattr(init, "resolve_memory_provider", resolve)
    monkeypatch.setattr(init, "_memory_provider_init_kwargs", lambda *args: {"session_id": "fixture"})
    agent = SimpleNamespace(_emit_startup_warning=lambda message: None)
    manager = init.initialize_memory_providers(agent, {"providers": ["broken", "healthy"]}, "cli")
    assert manager.providers == [healthy]
    assert healthy.calls == ["init"]
