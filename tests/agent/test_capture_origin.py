"""Runtime authorship is producer-bound, detached and limited to exact current spans."""
from agent.capture_origin import capture_messages, runtime_capture_origin
from agent.recall_query import automatic_recall_terms
import copy
import threading

import pytest

from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider
from agent.prompt_builder import steer_user_row


@pytest.mark.parametrize("steers", [0, 1, 2])
@pytest.mark.parametrize("scaffolded", [False, True])
def test_manager_sync_retains_history_and_classifies_only_current_payload(scaffolded, steers):
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
        {"role": "user", "content": user},
        {"role": "assistant", "tool_calls": [{"id": "call1", "function": {"name": "demo"}}]},
        {"role": "tool", "tool_call_id": "call1", "content": "previous tool result"},
        {"role": "assistant", "content": "previous reply"},
    ]
    suffix = [
        {"role": "assistant", "tool_calls": [{"id": "current", "function": {"name": "demo"}}]},
        {"role": "tool", "tool_call_id": "current", "content": "current tool result"},
    ]
    for index in range(steers):
        suffix += [steer_user_row(f"human correction {index}"),
                   {"role": "assistant", "tool_calls": [{"id": str(index), "function": {"name": "demo"}}]},
                   {"role": "tool", "tool_call_id": str(index), "content": "steered tool result"}]
    suffix.append({"role": "assistant", "content": "current reply"})
    history = prior + [{"role": "user", "content": user}] + suffix
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
        current = rows[len(prior):len(prior) + 3]
        assert [row["source_kind"] for row in current] == ["human", "machine_notification", "human"]
        assert [row["content"] for row in current] == ["human before\n", payload, "\nhuman correction"]
        assert rows[len(prior) + 3:] == suffix
        assert sum(row.get("source_kind") == "machine_notification" for row in rows) == 1
        assert history == canonical
    finally:
        manager.shutdown_all()


@pytest.mark.parametrize("case", [
    "empty", "no-user", "historical-duplicate", "untyped-steer", "only-steer",
    "absent-payload", "repeated-payload", "no-origin", "none", "none-no-origin",
])
def test_manager_sync_preserves_unmatched_transcript_without_historical_search(case):
    payload = "machine task finished"
    user = "human before\n" + payload + "\nhuman correction"
    history = [{"role": "user", "content": user}, {"role": "assistant", "content": "old reply"}]
    if case == "empty":
        history = []
    elif case == "no-user":
        history = [{"role": "assistant", "content": "reply"}]
    elif case == "only-steer":
        history = [steer_user_row("human correction")]
    elif case == "historical-duplicate":
        history += [{"role": "user", "content": "changed current input"},
                    {"role": "assistant", "content": "reply"}, steer_user_row("human correction")]
    elif case == "untyped-steer":
        history += [{"role": "user", "content": steer_user_row("human correction")["content"]}]
    elif case == "absent-payload":
        user = "human only"
    elif case == "repeated-payload":
        user += payload
    elif case.startswith("none"):
        history = None
    canonical = copy.deepcopy(history)
    received = []
    done = threading.Event()

    class ExternalStore(MemoryProvider):
        @property
        def name(self):
            return "capture-mismatch-regression"

        def get_tool_schemas(self):
            return []

        def is_available(self):
            return True

        def initialize(self, session_id, **kwargs):
            return None

        def sync_turn(self, user_content, assistant_content, *, messages=None, **kwargs):
            received.append(messages)
            done.set()

    manager = MemoryManager()
    manager.add_provider(ExternalStore())
    try:
        with runtime_capture_origin("" if case in {"no-origin", "none-no-origin"} else payload):
            manager.sync_all(user, "reply", session_id="capture-mismatch", messages=history)
        assert done.wait(5), "external store never received the completed turn"
        assert len(received) == 1
        if case == "none":
            assert [row.get("source_kind") for row in received[0]] == [
                "human", "machine_notification", "human", None]
            assert "".join(row["content"] for row in received[0][:-1]) == user
            assert received[0][-1] == {"role": "assistant", "content": "reply"}
        else:
            assert received[0] == canonical
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
