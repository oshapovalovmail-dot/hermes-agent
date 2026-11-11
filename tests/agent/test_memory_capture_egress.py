"""Automatic knowledge capture excludes runtime context without editing session evidence."""

import json
from typing import Any

import pytest

from agent.capture_origin import runtime_capture_origin
from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider
from agent.prompt_builder import steer_user_row


class FrozenDict(dict):
    """A real transcript DTO that rejects writes, including nested writes."""

    def _deny(self, *args, **kwargs):
        raise AssertionError("canonical DTO was mutated")

    __setitem__ = __delitem__ = pop = popitem = clear = update = setdefault = _deny


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenDict({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return [freeze(v) for v in value]
    return value


class RecordingProvider(MemoryProvider):
    """The external boundary only; all policy/lifecycle/background code is real."""

    def __init__(self, version=1):
        self.pre_compress_checkpoint_api_version = version
        self.received = []

    @property
    def name(self):
        return "capture-receiver"

    def is_available(self):
        return True

    def initialize(self, session_id, **kwargs):
        self.session_id = session_id

    def get_tool_schemas(self):
        return []

    def sync_turn(self, user_content, assistant_content, **kwargs):
        self.received.append(("sync", user_content, assistant_content, kwargs))

    def on_session_end(self, messages):
        self.received.append(("end", messages))

    def on_pre_compress(self, messages, **kwargs):
        self.received.append(("compress", messages, kwargs))
        return "checkpoint-receipt"

    def on_turn_start(self, turn_number, message, **kwargs):
        self.received.append(("start", message, kwargs))

    def queue_prefetch(self, query, **kwargs):
        self.received.append(("prefetch", query))


@pytest.fixture
def capture_manager():
    manager = MemoryManager()
    provider = RecordingProvider()
    manager.add_provider(provider)
    manager.initialize_all("capture-session")
    yield manager, provider
    assert manager.flush_pending(timeout=5)
    manager.shutdown_all()


def deliver(manager, path, rows, user="Real question", answer="Public answer"):
    if path == "sync":
        manager.sync_all(user, answer, messages=rows)
        assert manager.flush_pending(timeout=5)
    elif path == "end":
        manager.on_session_end(rows)
    elif path == "boundary":
        manager.commit_session_boundary_async(rows, new_session_id="next")
        assert manager.flush_pending(timeout=5)
    else:
        manager.on_pre_compress(rows)


def transcript():
    return [
        {"role": "system", "content": "SERVICE_SYSTEM"},
        {"role": "user", "content": "Real question", "api_content": "SERVICE_RECALL",
         "metadata": {"nested": {"reasoning": "SERVICE_METADATA"}}},
        {"role": "assistant", "content": "SERVICE_EARLIER_PROSE"},
        {"role": "assistant", "content": "SERVICE_TOOL_PROSE", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "content": "SERVICE_TOOL", "tool_call_id": "a"},
        {"role": "assistant", "content": "SERVICE_ANALYSIS", "channel": "analysis"},
        {"role": "assistant", "content": "SERVICE_PROGRESS", "channel": "commentary"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "SERVICE_THINKING"},
            {"type": "reasoning", "text": "SERVICE_REASONING_BLOCK"},
            {"type": "text", "text": "Public answer", "extras": {"text": "SERVICE_EXTRA"}},
        ], "reasoning": "SERVICE_REASONING", "reasoning_details": [{"text": "SERVICE_DETAIL"}],
         "_anthropic_content_blocks": [{"thinking": "SERVICE_ANTHROPIC"}],
         "extra_content": {"reasoning": "SERVICE_EXTRA_CONTENT"},
         "api_content": "SERVICE_API_CONTENT", "display_metadata": {"extra": "SERVICE_DISPLAY"}},
    ]


@pytest.mark.parametrize("path", ["sync", "end", "boundary", "compress"])
def test_actual_lifecycle_delivers_only_human_and_final_text(capture_manager, path):
    manager, provider = capture_manager
    rows = freeze(transcript())
    original = json.dumps(rows, sort_keys=True)
    deliver(manager, path, rows)
    assert len(provider.received) == 1
    payload = provider.received[0]
    assert "SERVICE_" not in json.dumps(payload)
    messages = payload[3]["messages"] if path == "sync" else payload[1]
    assert messages == [{"role": "user", "content": "Real question"},
                        {"role": "assistant", "content": "Public answer"}]
    messages[0]["content"] = "provider mutation"
    assert json.dumps(rows, sort_keys=True) == original


@pytest.mark.parametrize("path", ["sync", "end", "compress"])
@pytest.mark.parametrize("kind", ["internal_notification", "async_delegation_complete", "process_complete",
                                  "hidden", "model_switch", "personality_switch", "auto_continue"])
def test_typed_machine_only_turn_never_captures_its_answer(capture_manager, path, kind):
    manager, provider = capture_manager
    rows = freeze([{"role": "user", "content": "SERVICE_CALLBACK", "display_kind": kind},
                   {"role": "assistant", "content": "SERVICE_CALLBACK_ANSWER"}])
    deliver(manager, path, rows, user="SERVICE_CALLBACK", answer="SERVICE_CALLBACK_ANSWER")
    assert provider.received == ([("end", [])] if path == "end" else [])


@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_runtime_span_suppressed_but_human_neighbors_and_steering_survive(capture_manager, path):
    manager, provider = capture_manager
    machine = "SERVICE_BOUND_PAYLOAD"
    user = "human prefix\n" + machine + "\nhuman suffix"
    rows = freeze([{"role": "user", "content": user},
                   {"role": "assistant", "content": "SERVICE_PROGRESS", "tool_calls": [{"id": "a"}]},
                   {"role": "tool", "content": "SERVICE_TOOL"}, steer_user_row("human correction"),
                   {"role": "assistant", "content": "Public answer"}])
    original = json.dumps(rows)
    with runtime_capture_origin(machine):
        deliver(manager, path, rows, user=user)
    assert len(provider.received) == 1
    payload = json.dumps(provider.received)
    assert "SERVICE_" not in payload
    for text in ("human prefix", "human suffix", "human correction", "Public answer"):
        assert text in payload
    assert "OUT-OF-BAND USER MESSAGE" not in payload
    assert json.dumps(rows) == original


@pytest.mark.parametrize("user", ["Human quote: SERVICE_BOUND_PAYLOAD\nSERVICE_BOUND_PAYLOAD",
                                  "Human prefix with changed runtime payload"])
def test_ambiguous_bound_origin_skips_capture_but_not_unbound_quotes(capture_manager, user):
    from agent.turn_context import _previous_user_message_text

    manager, provider = capture_manager
    rows = freeze([{"role": "user", "content": user, "message_uid": "ambiguous-bound-turn"},
                   {"role": "assistant", "content": "Public answer"}])
    canonical = json.dumps(rows)
    with runtime_capture_origin("SERVICE_BOUND_PAYLOAD"):
        manager.sync_all(user, "Public answer", messages=rows)
        manager.on_turn_start(1, user)
    assert manager.flush_pending(timeout=5)
    assert provider.received == []
    # Deferred paths and next-turn previous_message must not resurrect ambiguous provenance.
    replay = json.loads(json.dumps(rows))
    manager.on_session_end(replay)
    manager.on_pre_compress(replay)
    manager.on_turn_start(2, "Next question", previous_message=_previous_user_message_text(replay))
    assert provider.received == [("end", []), ("start", "Next question", {"previous_message": ""})]
    provider.received.clear()
    quote = freeze([{"role": "user", "content": user, "message_uid": "unbound-quote"}, rows[1]])
    manager.sync_all(user, "Public answer", messages=quote)
    manager.on_turn_start(3, user)
    assert manager.flush_pending(timeout=5)
    sync = next(record for record in provider.received if record[0] == "sync")
    assert sync[1:3] == (user, "Public answer")
    assert sync[3]["messages"] == [{"role": "user", "content": user},
                                    {"role": "assistant", "content": "Public answer"}]
    assert ("start", user, {}) in provider.received
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("with_rows", [False, True])
def test_bound_machine_callback_skips_sync_not_assistant_reclassification(capture_manager, with_rows):
    manager, provider = capture_manager
    machine = "SERVICE_BOUND_PAYLOAD"
    rows = [{"role": "user", "content": machine}, {"role": "assistant", "content": "not human fact"}]
    with runtime_capture_origin(machine):
        manager.sync_all(machine, "not human fact", messages=rows if with_rows else None)
    assert manager.flush_pending(timeout=5)
    assert provider.received == []


@pytest.mark.parametrize("text", ["[ASYNC DELEGATION COMPLETE — worker] quoted example",
                                 "Working is my favorite word; explain reasoning.",
                                 "[System note: quoted]", "<think>literal user text</think>"])
def test_real_user_quotes_are_not_provenance(capture_manager, text):
    manager, provider = capture_manager
    rows = freeze([{"role": "user", "content": text}, {"role": "assistant", "content": "Public answer"}])
    deliver(manager, "sync", rows, user=text)
    assert provider.received[0][1:3] == (text, "Public answer")
    assert provider.received[0][3]["messages"] == list(rows)


@pytest.mark.parametrize("path", ["end", "compress"])
def test_native_todo_snapshot_is_not_human_knowledge(capture_manager, path):
    from types import SimpleNamespace

    from agent.conversation_compression import _fold_todo_snapshot

    manager, provider = capture_manager
    # An identical literal human quote must survive the producer-stamped row.
    quote = "[Your active task list was preserved across context compression] quoted example"
    rows = [{"role": "user", "content": quote}, {"role": "assistant", "content": "Public answer"}]
    _fold_todo_snapshot(SimpleNamespace(_todo_store=SimpleNamespace(format_for_injection=lambda: quote)), rows)
    assert rows[-1]["_todo_snapshot_synthetic"] is True
    canonical = json.dumps(rows)
    deliver(manager, path, freeze(rows))
    assert provider.received[0][1] == rows[:2]
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("flag", ["_todo_snapshot_synthetic", "_empty_recovery_synthetic",
                                  "_verification_stop_synthetic", "_pre_verify_synthetic",
                                  "_dropped_toolcall_nudge"])
def test_native_scaffolding_flags_do_not_seed_sync_scalars(capture_manager, flag):
    manager, provider = capture_manager
    rows = freeze([{"role": "user", "content": "producer text", flag: True},
                   {"role": "assistant", "content": "not a human answer"}])
    deliver(manager, "sync", rows, user="producer text", answer="not a human answer")
    assert provider.received == []


def test_replayed_typed_provenance_cannot_reimport_machine_history(capture_manager):
    manager, provider = capture_manager
    rows = freeze([
        {"role": "user", "content": "SERVICE_OLD", "display_kind": "internal_notification"},
        {"role": "assistant", "content": "SERVICE_OLD_ANSWER"},
        {"role": "user", "content": "Real question"},
        {"role": "assistant", "content": "Public answer"},
        {"role": "user", "content": "SERVICE_SPAN", "source_kind": "machine_notification",
         "metadata": {"origin_verified": True}},
        {"role": "assistant", "content": "SERVICE_SPAN_ANSWER"},
    ])
    manager.on_session_end(rows)
    assert provider.received == [("end", [{"role": "user", "content": "Real question"},
                                         {"role": "assistant", "content": "Public answer"}])]


def test_v2_checkpoint_evidence_is_not_replaced_by_knowledge_projection(capture_manager):
    manager, provider = capture_manager
    provider.pre_compress_checkpoint_api_version = 2
    evidence = freeze([{"role": "user", "content": "checkpoint task", "timestamp": 123},
                       {"role": "assistant", "content": "checkpoint evidence", "message_uid": "evidence-id"}])
    result = manager.on_pre_compress(transcript(), evidence_messages=evidence, require_checkpoint=True)
    assert result == "checkpoint-receipt"
    assert provider.received == [("compress", evidence, {"require_checkpoint": True})]


def test_agent_turn_finalizer_and_shutdown_use_same_real_filter(capture_manager):
    from run_agent import AIAgent

    manager, provider = capture_manager
    agent = AIAgent.__new__(AIAgent)
    agent._memory_manager = manager
    agent.session_id = "capture-session"
    agent._context_engine = None
    rows = freeze(transcript())
    agent._sync_external_memory_for_turn(original_user_message="Real question", final_response="Public answer",
                                         interrupted=False, messages=rows)
    assert manager.flush_pending(timeout=5)
    agent.shutdown_memory_provider(rows)
    assert {record[0] for record in provider.received} >= {"sync", "end"}
    assert "SERVICE_" not in json.dumps(provider.received)


def test_machine_turn_start_and_queued_recall_cannot_seed_provider(capture_manager):
    manager, provider = capture_manager
    with runtime_capture_origin("SERVICE_CALLBACK"):
        manager.on_turn_start(1, "SERVICE_CALLBACK")
        manager.queue_prefetch_all("SERVICE_CALLBACK")
    assert manager.flush_pending(timeout=5)
    assert provider.received == []


@pytest.mark.parametrize("replay", [False, True])
def test_previous_message_keeps_identity_bound_human_projection(capture_manager, replay):
    from agent.turn_context import _previous_user_message_text

    manager, provider = capture_manager
    user = "Human prefix\nSERVICE_PREVIOUS\nhuman suffix"
    row = {"role": "user", "content": user}
    if replay:
        row["message_uid"] = "prior-mixed-turn"
    rows = freeze([row, {"role": "assistant", "content": "Public answer"}])
    canonical = json.dumps(rows)
    with runtime_capture_origin("SERVICE_PREVIOUS"):
        manager.sync_all(user, "Public answer", messages=rows)
    assert manager.flush_pending(timeout=5)
    history = json.loads(json.dumps(rows)) if replay else rows
    previous = _previous_user_message_text(history)
    manager.on_turn_start(2, "Next human question", previous_message=previous)
    assert provider.received[-1] == (
        "start", "Next human question", {"previous_message": "Human prefix\n\nhuman suffix"})
    # Same bytes in a different real human row are not the bound prior turn.
    quote = freeze([{"role": "user", "content": user, "message_uid": "independent-human-quote"}])
    manager.on_turn_start(3, "Explain my quote", previous_message=_previous_user_message_text(quote))
    assert provider.received[-1] == ("start", "Explain my quote", {"previous_message": user})
    assert json.dumps(rows) == canonical


def test_bound_callback_after_human_turn_does_not_launder_its_answer(capture_manager):
    manager, provider = capture_manager
    rows = [{"role": "user", "content": "Real question"},
            {"role": "assistant", "content": "Public answer"},
            {"role": "user", "content": "SERVICE_CALLBACK"},
            {"role": "assistant", "content": "SERVICE_CALLBACK_ANSWER"}]
    with runtime_capture_origin("SERVICE_CALLBACK"):
        manager.on_session_end(rows)
    assert "SERVICE_" not in json.dumps(provider.received)
    assert provider.received == [("end", rows[:2])]


@pytest.mark.parametrize("path", ["end", "compress", "sync"])
def test_origin_survives_later_lifecycle_in_same_manager(capture_manager, path):
    manager, provider = capture_manager
    machine = "SERVICE_TRANSIENT"
    user = "human prefix\n" + machine + "\nhuman suffix"
    rows = freeze([{"role": "user", "content": user, "message_uid": "current-user"},
                   {"role": "assistant", "content": "Public answer"}])
    with runtime_capture_origin(machine):
        manager.sync_all(user, "Public answer", messages=rows)
    assert manager.flush_pending(timeout=5)
    # Session end occurs outside the per-turn runtime ContextVar, often with replayed copies.
    deliver(manager, path, json.loads(json.dumps(rows)), user=user)
    assert "SERVICE_" not in json.dumps(provider.received)
    assert "human prefix" in json.dumps(provider.received[-1])
    assert "human suffix" in json.dumps(provider.received[-1])


@pytest.mark.parametrize("force_user_leading", [False, True])
@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_native_mixed_compaction_carrier_preserves_real_ask(capture_manager, force_user_leading, path):
    from agent.context_compressor import ContextCompressor, user_originated_turn_view

    manager, provider = capture_manager
    ask = "Remember that I prefer tea"
    compressor = ContextCompressor.__new__(ContextCompressor)
    compressor._summary_has_user_turn = True
    carrier = {"role": "user", "content": ask}
    compressor._merge_summary_into_tail_row(carrier, "[CONTEXT COMPACTION] SERVICE_SUMMARY", "user", force_user_leading)
    assert carrier["_compressed_summary"] is True
    assert user_originated_turn_view(carrier)["content"] == ask
    rows = freeze([carrier, {"role": "assistant", "content": "Public answer"}])
    canonical = json.dumps(rows)
    # Even a raw carrier scalar must yield only the native human portion.
    deliver(manager, path, rows, user=carrier["content"])
    assert len(provider.received) == 1
    record = provider.received[0]
    projected = record[3]["messages"] if path == "sync" else record[1]
    assert projected == [{"role": "user", "content": ask}, {"role": "assistant", "content": "Public answer"}]
    if path == "sync":
        assert record[1:3] == (ask, "Public answer")
    assert "SERVICE_SUMMARY" not in json.dumps(record)
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("provenance", [
    {"_compressed_summary": True},
    {"source_kind": "runtime_notification"},
    {"metadata": {"source_kind": "machine_notification", "origin_verified": True}},
])
@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_compaction_and_machine_assistant_provenance_is_not_final(capture_manager, provenance, path):
    manager, provider = capture_manager
    rows = freeze([{"role": "user", "content": "Real question"},
                   {"role": "assistant", "content": "SERVICE_SYNTHETIC", **provenance}])
    deliver(manager, path, rows, answer="SERVICE_SYNTHETIC")
    assert "SERVICE_" not in json.dumps(provider.received)
    assert "Real question" in json.dumps(provider.received)


@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_persisted_producer_metadata_is_also_typed_provenance(capture_manager, path):
    manager, provider = capture_manager
    rows = freeze([{"role": "user", "content": "SERVICE_CALLBACK",
                    "metadata": {"source_kind": "machine_notification", "origin_verified": True}},
                   {"role": "assistant", "content": "SERVICE_CALLBACK_ANSWER"}])
    deliver(manager, path, rows, user="SERVICE_CALLBACK", answer="SERVICE_CALLBACK_ANSWER")
    assert provider.received == ([("end", [])] if path == "end" else [])


def test_typed_machine_origin_cannot_escape_through_differently_rendered_scalar(capture_manager):
    manager, provider = capture_manager
    rows = freeze([{"role": "user", "content": "SERVICE_CALLBACK", "display_kind": "internal_notification"},
                   {"role": "assistant", "content": "SERVICE_ANSWER"}])
    manager.sync_all("SERVICE_CALLBACK\nextra surface rendering", "SERVICE_ANSWER", messages=rows)
    assert manager.flush_pending(timeout=5)
    assert provider.received == []


@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_unfinished_tool_loop_is_not_a_final_answer(capture_manager, path):
    manager, provider = capture_manager
    rows = freeze([{"role": "user", "content": "Real question"},
                   {"role": "assistant", "content": "SERVICE_INTERMEDIATE"},
                   {"role": "tool", "content": "SERVICE_TOOL"}])
    deliver(manager, path, rows, answer="SERVICE_INTERMEDIATE")
    assert "SERVICE_" not in json.dumps(provider.received)
    assert "Real question" in json.dumps(provider.received)


@pytest.mark.parametrize("rows", [[], [{"role": "system", "content": "SERVICE_SYSTEM"}]])
def test_authoritative_empty_transcript_cannot_resurrect_raw_scalars(capture_manager, rows):
    manager, provider = capture_manager
    canonical = json.dumps(rows)
    manager.sync_all("SCALAR_SERVICE_INPUT", "<think>SCALAR_REASONING</think>Public answer", messages=freeze(rows))
    assert manager.flush_pending(timeout=5)
    assert provider.received == []
    # Only an omitted transcript retains the legacy scalar-only compatibility path.
    manager.sync_all("Real human question", "Public answer", messages=None)
    assert manager.flush_pending(timeout=5)
    assert provider.received == [("sync", "Real human question", "Public answer", {"session_id": ""})]
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("rows", [[], [{"role": "system", "content": "SERVICE_SYSTEM"}]])
def test_authoritative_empty_transcript_has_no_scalar_final_answer(rows):
    from agent.memory_capture import final_answer_text

    assert final_answer_text("<think>SCALAR_REASONING</think>Public answer", rows) == ""
    assert final_answer_text("Public answer", None) == "Public answer"


@pytest.mark.parametrize("channel", ["analysis", "commentary", "progress", "internal"])
def test_nonfinal_channel_cannot_escape_in_scalar_sync_argument(capture_manager, channel):
    manager, provider = capture_manager
    rows = [{"role": "user", "content": "Real question"},
            {"role": "assistant", "content": "SERVICE_CHANNEL", "channel": channel}]
    deliver(manager, "sync", rows, answer="SERVICE_CHANNEL")
    assert "SERVICE_" not in json.dumps(provider.received)


def test_structured_scalar_answer_uses_only_allowlisted_visible_text(capture_manager):
    manager, provider = capture_manager
    answer = [{"type": "reasoning", "text": "SERVICE_REASONING"},
              {"type": "thinking", "thinking": "SERVICE_THINKING"},
              {"type": "redacted_thinking", "data": "SERVICE_REDACTED"},
              {"type": "output_text", "text": "Public answer", "metadata": {"extra": "SERVICE_EXTRA"}}]
    manager.sync_all("Real question", freeze(answer))
    assert manager.flush_pending(timeout=5)
    assert provider.received[0][2] == "Public answer"
    assert "SERVICE_" not in json.dumps(provider.received)


def test_assistant_sidecar_and_author_metadata_never_escape(capture_manager):
    manager, provider = capture_manager
    rows = transcript()
    rows[-1].update({key: [{"text": "SERVICE_SIDECAR"}] for key in (
        "reasoning_content", "codex_reasoning_items", "codex_message_items")})
    manager.sync_all("Real question", "Public answer", messages=freeze(rows),
                     turn_author=freeze({"id": "person", "name": "Human", "is_bot": False,
                                         "metadata": {"reasoning": "SERVICE_AUTHOR"}}))
    assert manager.flush_pending(timeout=5)
    assert "SERVICE_" not in json.dumps(provider.received)
    assert provider.received[0][3]["turn_author"] == {"id": "person", "name": "Human", "is_bot": False}


def test_core_precompress_dispatch_keeps_checkpoint_and_knowledge_contracts_separate(capture_manager):
    from types import SimpleNamespace

    from agent.conversation_compression import _pre_compress_memory_context

    manager, knowledge_provider = capture_manager

    class CheckpointReceiver(RecordingProvider):
        @property
        def name(self):
            return "context-checkpoint-receiver"

    checkpoint = CheckpointReceiver(version=2)
    manager.add_provider(checkpoint)
    raw = freeze(transcript())
    original = json.dumps(raw, sort_keys=True)
    context = _pre_compress_memory_context(SimpleNamespace(_memory_manager=manager), raw, True)
    assert context.split() == ["checkpoint-receipt", "checkpoint-receipt"]
    assert "SERVICE_" not in json.dumps(knowledge_provider.received)
    # V2 remains the host-normalized direct-evidence API, not the knowledge API:
    # it preserves identities/carriers while excluding system/tool rows as before.
    checkpoint_rows = checkpoint.received[0][1]
    assert all(row["role"] in {"user", "assistant"} for row in checkpoint_rows)
    assert "SERVICE_REASONING" in json.dumps(checkpoint_rows)
    assert checkpoint.received[0][2] == {"require_checkpoint": True}
    assert json.dumps(raw, sort_keys=True) == original


def test_context_engine_receives_canonical_evidence_not_knowledge_projection(capture_manager):
    from run_agent import AIAgent

    manager, provider = capture_manager
    received = []

    class ContextReceiver:
        def on_session_end(self, session_id, messages):
            received.append((session_id, messages))

    agent = AIAgent.__new__(AIAgent)
    agent._memory_manager = manager
    agent.context_compressor = ContextReceiver()
    agent.session_id = "context-session"
    rows = freeze(transcript())
    agent.commit_memory_session(rows)
    assert "SERVICE_" not in json.dumps(provider.received)
    assert received == [("context-session", rows)]
    assert received[0][1] is rows


def test_sqlite_replay_preserves_canonical_history_but_not_machine_egress(capture_manager, tmp_path):
    from hermes_state import SessionDB

    manager, provider = capture_manager
    db = SessionDB(db_path=tmp_path / "capture.db")
    try:
        db.create_session("replay", source="cli")
        db.append_message("replay", "user", "SERVICE_CALLBACK", display_kind="internal_notification")
        db.append_message("replay", "assistant", "SERVICE_CALLBACK_ANSWER", reasoning="SERVICE_REASONING")
        db.append_message("replay", "user", "Real question")
        db.append_message("replay", "assistant", "Public answer", reasoning="SERVICE_HUMAN_TURN_REASONING")
        canonical = db.get_messages("replay")
        replay = db.get_messages_as_conversation("replay")
        manager.on_session_end(freeze(replay))
        assert "SERVICE_" not in json.dumps(provider.received)
        assert "Real question" in json.dumps(provider.received)
        assert "Public answer" in json.dumps(provider.received)
        assert db.get_messages("replay") == canonical
        assert "SERVICE_REASONING" in json.dumps(canonical)
    finally:
        db.close()


def _composed_native_history(user, *, historical=False):
    rows = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "head question"},
        {"role": "assistant", "content": "head answer"},
        {"role": "user", "content": "middle question"},
        {"role": "assistant", "content": "middle answer"},
        {"role": "user", "content": "middle extra"},
        {"role": "user", "content": user, "message_uid": "composed-bound"},
    ]
    if historical:
        rows.extend([{"role": "assistant", "content": "Prior public answer"},
                     {"role": "user", "content": "Next real question", "message_uid": "later-human"}])
    else:
        rows.extend([
            {"role": "assistant", "content": "Working", "tool_calls": [
                {"id": "call1", "type": "function", "function": {"name": "probe", "arguments": "{}"}}]},
            {"role": "tool", "content": "Tool output", "tool_call_id": "call1"},
        ])
    return freeze(rows)


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_composed_actual_compress_keeps_bound_projection(capture_manager, monkeypatch, historical, path):
    from types import SimpleNamespace

    from agent.context_compressor import ContextCompressor, user_originated_turn_view
    from agent.conversation_compression import _pre_compress_memory_context
    from agent.turn_context import _previous_user_message_text

    manager, provider = capture_manager
    user = "Human prefix\nRAW_SENTINEL_BOUND\nhuman suffix"
    rows = _composed_native_history(user, historical=historical)
    canonical = json.dumps(rows)
    if historical:
        with runtime_capture_origin("RAW_SENTINEL_BOUND"):
            manager.sync_all(user, "Prior public answer", messages=rows[:-1])
        assert manager.flush_pending(timeout=5)
        assert "RAW_SENTINEL_" not in json.dumps(provider.received)
        provider.received.clear()
    compressor = ContextCompressor(model="test", config_context_length=100000, quiet_mode=True,
                                   protect_first_n=2, protect_last_n=3)
    compressor.tail_token_budget = 1
    # Only the external summary completion is replaced, never window/merge selection.
    monkeypatch.setattr("agent.context_compressor.call_llm", lambda **kwargs: {
        "choices": [{"message": {"content": "RAW_SENTINEL_SUMMARY"}, "finish_reason": "stop"}]})

    def compress_and_deliver():
        _pre_compress_memory_context(SimpleNamespace(_memory_manager=manager), rows, False)
        assert "RAW_SENTINEL_" not in json.dumps(provider.received)
        provider.received.clear()
        compressed = compressor.compress(rows, force=True)
        assert compressor.compression_count == 1
        carrier = next(row for row in compressed if row.get("message_uid") == "composed-bound")
        assert carrier["_compressed_summary"] is True
        live = user_originated_turn_view(carrier)
        assert live is not None and live["content"] == user
        assert "RAW_SENTINEL_SUMMARY" in carrier["content"]
        answer = "Next public answer" if historical else "Public answer"
        compressed.append({"role": "assistant", "content": answer})
        compressed = freeze(compressed)
        before_capture = json.dumps(compressed)
        deliver(manager, path, compressed, user="Next real question" if historical else user, answer=answer)
        assert json.dumps(compressed) == before_capture
        return compressed, answer

    if historical:
        compressed, answer = compress_and_deliver()
    else:
        with runtime_capture_origin("RAW_SENTINEL_BOUND"):
            compressed, answer = compress_and_deliver()
    assert len(provider.received) == 1
    record = provider.received[0]
    assert "RAW_SENTINEL_" not in json.dumps(record)
    for text in ("Human prefix", "human suffix", answer):
        assert text in json.dumps(record)
    if path == "sync":
        assert record[1:3] == ("Next real question" if historical else "Human prefix\n\nhuman suffix", answer)
    manager.on_turn_start(2, "Fresh question", previous_message=_previous_user_message_text(compressed))
    assert provider.received[-1] == (
        "start", "Fresh question", {"previous_message": "Next real question" if historical else "Human prefix\n\nhuman suffix"})
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("force_user_leading", [False, True])
@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_composed_native_helper_keeps_origin_and_next_previous(capture_manager, force_user_leading, replay, path):
    from agent.context_compressor import ContextCompressor, user_originated_turn_view
    from agent.turn_context import _previous_user_message_text

    manager, provider = capture_manager
    user = "Human prefix\nRAW_SENTINEL_BOUND\nhuman suffix"
    row = {"role": "user", "content": user}
    if replay:
        row["message_uid"] = "composed-helper"
    compressor = ContextCompressor.__new__(ContextCompressor)
    compressor._summary_has_user_turn = True
    with runtime_capture_origin("RAW_SENTINEL_BOUND"):
        manager.on_pre_compress([row])
        assert "RAW_SENTINEL_" not in json.dumps(provider.received)
        provider.received.clear()
        compressor._merge_summary_into_tail_row(row, "[CONTEXT COMPACTION] RAW_SENTINEL_SUMMARY", "user", force_user_leading)
        live = user_originated_turn_view(row)
        assert live is not None and live["content"] == user
        # Object identity remains the credential for an unpersisted in-place carrier.
        carrier = freeze(row) if replay else row
        rows = [carrier, {"role": "assistant", "content": "Public answer"}]
        canonical = json.dumps(rows)
        deliver(manager, path, rows, user=user)
    assert len(provider.received) == 1
    assert "RAW_SENTINEL_" not in json.dumps(provider.received)
    for text in ("Human prefix", "human suffix", "Public answer"):
        assert text in json.dumps(provider.received)
    manager.on_turn_start(2, "Fresh question", previous_message=_previous_user_message_text(rows))
    assert provider.received[-1] == ("start", "Fresh question", {"previous_message": "Human prefix\n\nhuman suffix"})
    # A different UID with identical bytes is a genuine independent human quotation.
    quote = {"role": "user", "content": user, "message_uid": "independent-composed-quote"}
    compressor._merge_summary_into_tail_row(quote, "[CONTEXT COMPACTION] OTHER_SUMMARY", "user", force_user_leading)
    manager.on_turn_start(3, "Explain my quotation", previous_message=_previous_user_message_text([quote]))
    assert provider.received[-1] == ("start", "Explain my quotation", {"previous_message": user})
    manager.on_session_end(freeze([quote, {"role": "assistant", "content": "Quote answer"}]))
    assert provider.received[-1] == ("end", [{"role": "user", "content": user},
                                          {"role": "assistant", "content": "Quote answer"}])
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_composed_unknown_rewrite_of_bound_uid_does_not_fall_back_to_raw(capture_manager, path):
    from agent.context_compressor import ContextCompressor
    from agent.turn_context import _previous_user_message_text

    manager, provider = capture_manager
    user = "Human prefix\nRAW_SENTINEL_BOUND\nhuman suffix"
    row = {"role": "user", "content": user, "message_uid": "unresolved-bound"}
    with runtime_capture_origin("RAW_SENTINEL_BOUND"):
        manager.on_pre_compress(freeze([row]))
    provider.received.clear()
    compressor = ContextCompressor.__new__(ContextCompressor)
    compressor._summary_has_user_turn = True
    compressor._merge_summary_into_tail_row(row, "[CONTEXT COMPACTION] RAW_SENTINEL_SUMMARY", "user", False)
    # A known identity whose live preimage no longer agrees is not an unmarked human fallback.
    row["content"] = row["content"].replace("human suffix", "changed human suffix")
    rows = freeze([row, {"role": "assistant", "content": "Public answer"}])
    canonical = json.dumps(rows)
    deliver(manager, path, rows, user=user)
    assert provider.received == ([("end", [])] if path == "end" else [])
    manager.on_turn_start(2, "Fresh question", previous_message=_previous_user_message_text(rows))
    assert provider.received[-1] == ("start", "Fresh question", {"previous_message": ""})
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("producer", ["compress", "helper-prior", "helper-leading"])
def test_composed_previous_lookup_before_any_post_transform_capture(capture_manager, monkeypatch, producer):
    from agent.context_compressor import ContextCompressor
    from agent.turn_context import _previous_user_message_text

    manager, provider = capture_manager
    user = "Human prefix\nRAW_SENTINEL_BOUND\nhuman suffix"
    rows = _composed_native_history(user)
    with runtime_capture_origin("RAW_SENTINEL_BOUND"):
        manager.on_pre_compress(rows)
    provider.received.clear()
    if producer == "compress":
        compressor = ContextCompressor(model="test", config_context_length=100000, quiet_mode=True,
                                       protect_first_n=2, protect_last_n=3)
        compressor.tail_token_budget = 1
        monkeypatch.setattr("agent.context_compressor.call_llm", lambda **kwargs: {
            "choices": [{"message": {"content": "RAW_SENTINEL_SUMMARY"}, "finish_reason": "stop"}]})
        rows = compressor.compress(rows, force=True)
        assert compressor.compression_count == 1
        assert next(row for row in rows if row.get("message_uid") == "composed-bound")["_compressed_summary"] is True
    else:
        carrier = dict(rows[6])
        compressor = ContextCompressor.__new__(ContextCompressor)
        compressor._summary_has_user_turn = True
        compressor._merge_summary_into_tail_row(carrier, "[CONTEXT COMPACTION] RAW_SENTINEL_SUMMARY", "user",
                                                producer == "helper-leading")
        rows = [carrier]
    canonical = json.dumps(rows)
    manager.on_turn_start(2, "Fresh question", previous_message=_previous_user_message_text(freeze(rows)))
    assert provider.received == [("start", "Fresh question", {"previous_message": "Human prefix\n\nhuman suffix"})]
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("force_user_leading", [False, True])
@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_composed_first_seen_carrier_splits_only_native_live_ask(capture_manager, force_user_leading, path):
    from agent.context_compressor import ContextCompressor
    from agent.turn_context import _previous_user_message_text

    manager, provider = capture_manager
    user = "Human prefix\nRAW_SENTINEL_BOUND\nhuman suffix"
    row = {"role": "user", "content": user, "message_uid": "first-seen-carrier"}
    compressor = ContextCompressor.__new__(ContextCompressor)
    compressor._summary_has_user_turn = True
    compressor._merge_summary_into_tail_row(row, "[CONTEXT COMPACTION] RAW_SENTINEL_SUMMARY", "user", force_user_leading)
    rows = freeze([row, steer_user_row("Human correction"), {"role": "assistant", "content": "Public answer"}])
    canonical = json.dumps(rows)
    with runtime_capture_origin("RAW_SENTINEL_BOUND"):
        deliver(manager, path, rows, user=row["content"])
    assert len(provider.received) == 1
    assert "RAW_SENTINEL_" not in json.dumps(provider.received)
    for text in ("Human prefix", "human suffix", "Human correction", "Public answer"):
        assert text in json.dumps(provider.received)
    manager.on_turn_start(2, "Fresh question", previous_message=_previous_user_message_text(rows))
    assert provider.received[-1] == ("start", "Fresh question", {"previous_message": "Human prefix\n\nhuman suffix"})
    assert json.dumps(rows) == canonical


@pytest.mark.parametrize("force_user_leading", [False, True])
@pytest.mark.parametrize("path", ["sync", "end", "compress"])
def test_composed_summary_only_carrier_cannot_be_split_into_human_prefix(capture_manager, force_user_leading, path):
    from agent.context_compressor import ContextCompressor, user_originated_turn_view

    manager, provider = capture_manager
    compressor = ContextCompressor.__new__(ContextCompressor)
    compressor._summary_has_user_turn = True
    carrier = {"role": "user", "content": "", "message_uid": "summary-only"}
    compressor._merge_summary_into_tail_row(carrier, "[CONTEXT COMPACTION] RAW_SENTINEL_BOUND", "user", force_user_leading)
    assert user_originated_turn_view(carrier) is None
    earlier = [{"role": "user", "content": "Earlier human question"},
               {"role": "assistant", "content": "Earlier public answer"}]
    rows = freeze([*earlier, carrier, {"role": "assistant", "content": "RAW_SENTINEL_MACHINE_ANSWER"}])
    canonical = json.dumps(rows)
    with runtime_capture_origin("RAW_SENTINEL_BOUND"):
        deliver(manager, path, rows, user=carrier["content"], answer="RAW_SENTINEL_MACHINE_ANSWER")
    if path == "sync":
        assert provider.received == []
    else:
        expected = ("end", earlier) if path == "end" else ("compress", earlier, {})
        assert provider.received == [expected]
    assert json.dumps(rows) == canonical


def test_composed_skill_scalar_original_user_and_independent_bound_rows(capture_manager):
    from agent.context_compressor import ContextCompressor
    from agent.turn_context import _previous_user_message_text

    manager, provider = capture_manager
    history = []
    compressor = ContextCompressor.__new__(ContextCompressor)
    compressor._summary_has_user_turn = True
    for index in range(2):
        instruction = f"Human prefix {index}\nRAW_SENTINEL_BOUND_{index}\nhuman suffix {index}"
        original = ('[IMPORTANT: The user has invoked the "demo" skill. '
                    'The full skill content is loaded below.]\n\n# Demo\nInstructions\n\n'
                    'The user has provided the following instruction alongside the skill invocation: ' + instruction)
        row = {"role": "user", "content": original, "message_uid": f"skill-bound-{index}"}
        compressor._merge_summary_into_tail_row(row, "[CONTEXT COMPACTION] RAW_SENTINEL_SUMMARY", "user", bool(index))
        rows = freeze([*history, row, steer_user_row(f"Human correction {index}"),
                       {"role": "assistant", "content": f"Public answer {index}"}])
        canonical = json.dumps(rows)
        # MemoryManager strips the skill before CaptureOrigins; original_user still locates the raw ask.
        with runtime_capture_origin(f"RAW_SENTINEL_BOUND_{index}"):
            manager.sync_all(original, f"Public answer {index}", messages=rows)
        assert manager.flush_pending(timeout=5)
        record = provider.received[-1]
        assert record[0] == "sync"
        assert record[1:3] == (f"Human prefix {index}\n\nhuman suffix {index}", f"Public answer {index}")
        assert "RAW_SENTINEL_" not in json.dumps(record)
        assert f"Human correction {index}" in json.dumps(record)
        manager.on_turn_start(index + 2, "Fresh question", previous_message=_previous_user_message_text(rows))
        assert provider.received[-1] == ("start", "Fresh question", {
            "previous_message": f"Human prefix {index}\n\nhuman suffix {index}"})
        assert json.dumps(rows) == canonical
        history = rows
    provider.received.clear()
    manager.on_session_end(history)
    assert provider.received == [("end", [
        {"role": "user", "content": "Human prefix 0\n"},
        {"role": "user", "content": "\nhuman suffix 0"},
        {"role": "user", "content": "Human correction 0"},
        {"role": "assistant", "content": "Public answer 0"},
        {"role": "user", "content": "Human prefix 1\n"},
        {"role": "user", "content": "\nhuman suffix 1"},
        {"role": "user", "content": "Human correction 1"},
        {"role": "assistant", "content": "Public answer 1"},
    ])]
