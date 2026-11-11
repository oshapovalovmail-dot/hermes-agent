"""Empty knowledge projections still close accepted provider buffers, never raw tails."""
import json

import pytest

from agent.memory_manager import MemoryManager
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tests.agent.test_memory_capture_egress import RecordingProvider, freeze, transcript


class BufferedProvider(RecordingProvider):
    def __init__(self):
        super().__init__()
        self.pending = []
        self.committed = []

    def sync_turn(self, user_content, assistant_content, **kwargs):
        self.pending.extend(kwargs["messages"])

    def on_session_end(self, messages):
        self.received.append(("end", list(messages)))
        self.committed.extend(self.pending)
        self.pending.clear()
        # Receiver mutation must not affect the canonical empty or machine transcript.
        messages.append({"role": "user", "content": "receiver mutation"})

    def shutdown(self):
        self.received.append(("shutdown",))


@pytest.mark.parametrize("tail", [[], [
    {"role": "user", "content": "RAW_MACHINE", "display_kind": "internal_notification"},
    {"role": "assistant", "content": "RAW_ANSWER", "reasoning": "RAW_REASONING"},
]])
@pytest.mark.parametrize("accepted", [False, True])
def test_empty_end_flushes_only_previously_accepted_knowledge_before_shutdown(tail, accepted):
    manager = MemoryManager()
    provider = BufferedProvider()
    manager.add_provider(provider)
    manager.initialize_all("empty-end")
    if accepted:
        manager.sync_all("Real question", "Public answer", messages=freeze(transcript()))
        assert manager.flush_pending(timeout=5)
    rows = freeze(tail)
    canonical = json.dumps(rows)
    manager.on_session_end(rows)
    manager.shutdown_all()
    assert provider.received == [("end", []), ("shutdown",)]
    assert provider.committed == ([{"role": "user", "content": "Real question"},
                                   {"role": "assistant", "content": "Public answer"}] if accepted else [])
    assert provider.pending == []
    assert json.dumps(rows) == canonical
    assert "RAW_" not in json.dumps(provider.received + provider.committed)


@pytest.mark.parametrize("guard", ["fork", "owner"])
def test_empty_end_does_not_bypass_owner_or_fork_guard(tmp_path, guard):
    manager = MemoryManager()
    provider = RecordingProvider()
    manager.add_provider(provider)
    manager.initialize_all("guarded", agent_context="subagent" if guard == "fork" else "primary")
    token = set_hermes_home_override(str(tmp_path / "other-owner")) if guard == "owner" else None
    try:
        manager.on_session_end([])
        assert provider.received == []
    finally:
        if token is not None:
            reset_hermes_home_override(token)
        manager.shutdown_all()
