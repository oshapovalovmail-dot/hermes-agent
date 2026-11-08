"""Runtime authorship is producer-bound, detached and limited to exact current spans."""
from agent.capture_origin import capture_messages, runtime_capture_origin
from agent.recall_query import automatic_recall_terms
import copy
import threading

import pytest

from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider


@pytest.mark.parametrize("scaffolded", [False, True])
def test_manager_sync_retains_history_and_classifies_only_current_payload(scaffolded):
    """Exercise real background dispatch and egress, with only the external store replaced."""
    payload = "machine task finished"
    instruction = "human before\n" + payload + "\nhuman correction"
    user = instruction
    if scaffolded:
        user = (
            '[IMPORTANT: The user has invoked the "demo" skill. '
            'The full skill content is loaded below.]\n\n# Demo\nInstructions\n\n'
            'The user has provided the following instruction alongside the skill invocation: '
            + instruction
        )
    prior = [
        {"role": "user", "content": "previous human request"},
        {"role": "assistant", "tool_calls": [{"id": "call1", "function": {"name": "demo"}}]},
        {"role": "tool", "tool_call_id": "call1", "content": "previous tool result"},
        {"role": "assistant", "content": "previous reply"},
    ]
    history = prior + [{"role": "user", "content": user},
                       {"role": "assistant", "content": "current reply"}]
    canonical = copy.deepcopy(history)
    received = []
    done = threading.Event()

    class ExternalStore(MemoryProvider):
        @property
        def name(self):
            return "capture-regression"

        def get_tool_schemas(self):
            return []

        def is_available(self):
            return True

        def initialize(self, session_id, **kwargs):
            pass

        def sync_turn(self, user_content, assistant_content, *, messages=None, **kwargs):
            received.append((user_content, assistant_content, messages))
            done.set()

    manager = MemoryManager()
    manager.add_provider(ExternalStore())
    try:
        with runtime_capture_origin(payload):
            manager.sync_all(user, "current reply", session_id="capture", messages=history)
        assert done.wait(5), "external store never received the completed turn"
        assert len(received) == 1
        clean_user, reply, rows = received[0]
        assert clean_user == instruction
        assert reply == "current reply"
        assert rows[:len(prior)] == prior
        current = rows[len(prior):-1]
        assert [row["source_kind"] for row in current] == ["human", "machine_notification", "human"]
        assert [row["content"] for row in current] == ["human before\n", payload, "\nhuman correction"]
        assert rows[-1] == history[-1]
        assert history == canonical
    finally:
        manager.shutdown_all()


def test_bound_payload_keeps_human_neighbors_and_canonical_history():
    payload = "[ASYNC DELEGATION COMPLETE — worker] machine text"
    user = "human before\n" + payload + "\nhuman correction"
    history = [{"role": "user", "content": "old"}, {"role": "user", "content": user}]
    with runtime_capture_origin(payload):
        rows = capture_messages(user, "reply", history)
    assert history[-1] == {"role": "user", "content": user}
    assert [r["source_kind"] for r in rows[1:]] == ["human", "machine_notification", "human"]
    assert "".join(r["content"] for r in rows[1:]) == user
    assert capture_messages(user, "reply", history) is history


def test_textual_prefix_and_repeated_payload_do_not_prove_origin():
    user = "[ASYNC DELEGATION COMPLETE — worker] pasted"
    history = [{"role": "user", "content": user}]
    assert capture_messages(user, "", history) is history
    with runtime_capture_origin(user):
        assert capture_messages(user + user, "", history) is history


def test_nested_origin_restores_owner():
    with runtime_capture_origin("outer"):
        with runtime_capture_origin("inner"):
            assert capture_messages("inner", "", None)[0]["source_kind"] == "machine_notification"
        assert capture_messages("outer", "", None)[0]["source_kind"] == "machine_notification"


def test_short_transfer_endpoints_are_topics_not_prepositions():
    assert automatic_recall_terms("transfer from PC to TV", frozenset({"transfer", "from", "to"})) == ["pc", "tv"]


def test_followup_clause_focus_preserves_explicit_complement():
    terms = automatic_recall_terms("Help with telescope. Can you fix it?", frozenset({"help", "with"}))
    assert terms == ["telescope"]
