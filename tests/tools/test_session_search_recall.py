"""Discovery recalls message text; raw tool-call investigations are explicit."""
import json

import pytest

from hermes_state import SessionDB
from tools.registry import registry
from tools.session_search_tool import _shape_message


@pytest.fixture
def db(tmp_path):
    store = SessionDB(tmp_path / "history.db")
    yield store
    store.close()


def _call(marker):
    return [{"id": "call_fixture", "type": "function", "function": {
        "name": "terminal", "arguments": json.dumps({"command": f"printf {marker}"})}}]


def _discover(db, query, **kwargs):
    entry = registry.get_entry("session_search")
    assert entry is not None
    return json.loads(entry.handler(
        {"query": query, **kwargs}, db=db))


def test_call_arguments_are_not_recalled_as_recorded_facts(db):
    db.create_session("arguments-only", source="cli")
    db.append_message("arguments-only", "assistant", "", tool_calls=_call("falcon-scope-7"))
    payload = _discover(db, "falcon-scope-7")
    assert payload["success"] is True
    assert payload["results"] == []


def test_nonempty_comment_does_not_turn_call_arguments_into_facts(db):
    db.create_session("comment-and-call", source="cli")
    db.append_message("comment-and-call", "assistant", "Checking the filesystem.",
                      tool_calls=_call("falcon-scope-7"))
    assert _discover(db, "falcon-scope-7")["results"] == []


def test_explicit_call_investigation_preserves_raw_requests(db):
    db.create_session("call-investigation", source="cli")
    calls = _call("marigold-calls")
    mid = db.append_message("call-investigation", "assistant", "", tool_calls=calls)
    payload = _discover(db, "marigold-calls", include_tool_calls=True)
    assert payload["success"] is True
    assert payload["results"][0]["match_message_id"] == mid
    assert payload["results"][0]["messages"][0]["tool_calls"] == calls


def test_call_search_requires_an_actual_boolean_opt_in(db):
    db.create_session("no-implicit-calls", source="cli")
    db.append_message("no-implicit-calls", "assistant", "", tool_calls=_call("marigold-calls"))
    assert _discover(db, "marigold-calls", include_tool_calls="false")["results"] == []


def test_actual_body_match_is_retained_with_tool_calls(db):
    db.create_session("body-and-call", source="cli")
    mid = db.append_message("body-and-call", "assistant", "falcon-scope-7 is the recorded identifier.",
                            tool_calls=_call("some-other-marker"))
    payload = _discover(db, "falcon-scope-7")
    assert payload["success"] is True
    assert payload["results"][0]["match_message_id"] == mid


def test_empty_calls_do_not_displace_the_supporting_answer(db):
    sid = "instruction"
    db.create_session(sid, source="cli")
    anchor = db.append_message(sid, "user", "Read saffron-step-guide before continuing.")
    for _ in range(20):
        db.append_message(sid, "assistant", "", tool_calls=_call("progress-only"))
    answer = db.append_message(sid, "assistant", "Copy the existing workflow. Keep execution not started.")
    for n in range(10):
        db.append_message(sid, "assistant", f"Later unrelated note {n}.")
    payload = _discover(db, "saffron-step-guide")
    result = payload["results"][0]
    assert result["match_message_id"] == anchor
    assert answer in [m["id"] for m in result["messages"]]
    assert all(m.get("content") for m in result["messages"])


def test_a_negative_comparison_remains_searchable(db):
    db.create_session("comparison", source="cli")
    mid = db.append_message("comparison", "assistant", "FalconScope is not HeronScope. Their permissions differ.")
    payload = _discover(db, "HeronScope")
    assert payload["results"][0]["match_message_id"] == mid
    assert "not HeronScope" in payload["results"][0]["messages"][0]["content"]


def test_factual_discovery_does_not_return_serialized_call_arguments(db):
    db.create_session("factual-body", source="cli")
    db.append_message("factual-body", "assistant", "lilac-evidence is recorded in the answer.",
                      tool_calls=_call("private-request-arguments"))
    hit = _discover(db, "lilac-evidence")["results"][0]
    assert hit["messages"][0]["content"] == "lilac-evidence is recorded in the answer."
    assert "tool_calls" not in hit["messages"][0]
    raw_hit = _discover(db, "lilac-evidence", include_tool_calls=True)["results"][0]
    assert raw_hit["messages"][0]["tool_calls"]


def test_any_term_fallback_is_explicitly_a_partial_lexical_candidate(db):
    db.create_session("nearby-object", source="cli")
    db.append_message("nearby-object", "assistant", "The cobalt deployment concerns another object.")
    hit = _discover(db, "cobalt unrecordedfacet")["results"][0]
    assert hit["search_route"] == "or_relaxed"
    assert hit["partial_match"] is True


def test_structured_body_cannot_escape_the_discovery_character_cap(db):
    db.create_session("structured-answer", source="cli")
    body = [{"type": "text", "text": "orchid-evidence " + "x" * 80_000}]
    mid = db.append_message("structured-answer", "assistant", body)
    hit = _discover(db, "orchid-evidence")["results"][0]
    message = next(m for m in hit["messages"] if m["id"] == mid)
    assert message["content_truncated"] is True
    assert isinstance(message["content"], str) and len(message["content"]) <= 4001
    assert message["original_content_chars"] > 80_000
    entry = registry.get_entry("session_search")
    assert entry is not None
    raw = json.loads(entry.handler(
        {"session_id": "structured-answer", "around_message_id": mid}, db=db))
    assert raw["messages"][0]["content"] == body


def test_small_structured_body_remains_native():
    body = [{"type": "text", "text": "exact caption"}]
    shaped = _shape_message({"id": 1, "role": "user", "content": body}, max_content_len=4000)
    assert shaped["content"] == body
    assert "content_truncated" not in shaped


def test_structured_bookend_does_not_break_discovery(db):
    db.create_session("structured-bookend", source="cli")
    body = [{"type": "text", "text": "Original structured goal"}]
    first = db.append_message("structured-bookend", "user", body)
    for n in range(7):
        db.append_message("structured-bookend", "assistant", f"Intermediate prose {n}")
    db.append_message("structured-bookend", "user", "orchid-anchor")
    hit = _discover(db, "orchid-anchor")["results"][0]
    assert next(m for m in hit["bookend_start"] if m["id"] == first)["content"] == body


def test_discovery_excerpt_stops_before_a_partial_paragraph():
    complete = "A complete first paragraph. " * 110
    omitted = "This second paragraph must not be cut in half. " * 30
    text = complete + "\n\n" + omitted + "\n\nFinal paragraph."
    rendered = _shape_message({"id": 7, "role": "assistant", "content": text}, max_content_len=4000)
    assert rendered["content_truncated"] is True
    assert rendered["content"].removesuffix("…").rstrip() == complete.rstrip()
    assert rendered["original_content_chars"] == len(text)


@pytest.mark.parametrize("title_match", [False, True])
def test_scan_work_cap_is_visible_in_public_discovery(db, monkeypatch, title_match):
    import tools.session_search_context as context
    monkeypatch.setattr(context, "_SCAN_ROW_LIMIT", 8)
    db.create_session("bounded-history", source="cli")
    if title_match:
        db.set_session_title("bounded-history", "lavender-window")
    db.append_message("bounded-history", "user", "lavender-window")
    for _ in range(30):
        db.append_message("bounded-history", "assistant", "", tool_calls=_call("not-a-fact"))
    payload = _discover(db, "lavender-window")
    result = payload["results"][0]
    assert result["context_truncated"] is True
    assert result["context_scan_limit"] == 8
    assert result["context_continuation"]
