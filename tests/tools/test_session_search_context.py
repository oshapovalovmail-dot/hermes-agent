"""Synthetic recall context regressions; ordinary raw reads keep their contract."""

import importlib
import sqlite3

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "state.db")
    database.create_session("s", source="cli")
    yield database
    database.close()


def _view(db, anchor, **kwargs):
    from tools.session_search_context import get_recall_anchored_view

    return get_recall_anchored_view(db, "s", anchor, **kwargs)


def _ids(rows):
    return [row["id"] for row in rows]


def _call(db):
    return db.append_message(
        "s", "assistant", content=None,
        tool_calls=[{"id": "call", "type": "function",
                     "function": {"name": "terminal", "arguments": '{"q":"not a fact"}'}}],
    )


def _state(db, message_id, *, active, compacted):
    db._execute_write(lambda conn: conn.execute(
        "UPDATE messages SET active = ?, compacted = ? WHERE id = ?",
        (active, compacted, message_id),
    ))


@pytest.mark.parametrize("call_rows", [24, 160])
def test_substantive_support_survives_long_call_runs_each_side(db, call_rows):
    before = db.append_message("s", "assistant", "Actual supporting answer before")
    for _ in range(call_rows):
        _call(db)
        db.append_message("s", "tool", "Not a factual neighbor", tool_name="terminal")
    anchor = db.append_message("s", "user", "Recall question")
    for _ in range(call_rows):
        _call(db)
        db.append_message("s", "tool", "Not a factual neighbor", tool_name="terminal")
    after = db.append_message("s", "assistant", "Actual supporting answer after")

    view = _view(db, anchor, window=1, bookend=0)
    assert _ids(view["window"]) == [before, anchor, after]
    assert (view["messages_before"], view["messages_after"]) == (1, 1)
    assert not view.get("context_truncated", False)
    # The public raw primitive is intentionally NOT changed by recall discovery.
    assert _ids(db.get_messages_around("s", anchor, window=1)["window"]) != [before, anchor, after]


@pytest.mark.parametrize("missing", [False, True])
def test_foreign_or_missing_anchor_returns_empty_without_bookends(db, missing):
    db.append_message("s", "user", "Local question")
    db.create_session("other", source="cli")
    foreign = db.append_message("other", "assistant", "Foreign private answer")
    view = _view(db, foreign + 100 if missing else foreign)
    assert view == {"window": [], "messages_before": 0, "messages_after": 0,
                    "bookend_start": [], "bookend_end": []}


def test_visibility_never_resurrects_rewind_but_includes_compaction_archive(db):
    head = db.append_message("s", "user", "Archived goal")
    _state(db, head, active=0, compacted=1)
    hidden_head = db.append_message("s", "assistant", "Rewound head")
    _state(db, hidden_head, active=0, compacted=0)
    archived = db.append_message("s", "assistant", "Archived real answer")
    _state(db, archived, active=0, compacted=1)
    hidden = db.append_message("s", "assistant", "Rewound adjacent answer")
    _state(db, hidden, active=0, compacted=0)
    anchor = db.append_message("s", "user", "Current question")
    after = db.append_message("s", "assistant", "Current answer")
    hidden_tail = db.append_message("s", "assistant", "Rewound tail")
    _state(db, hidden_tail, active=0, compacted=0)
    tail = db.append_message("s", "assistant", "Archived conclusion")
    _state(db, tail, active=0, compacted=1)

    view = _view(db, anchor, window=1, bookend=2)
    assert _ids(view["window"]) == [archived, anchor, after]
    assert _ids(view["bookend_start"]) == [head]
    assert _ids(view["bookend_end"]) == [tail]
    assert _ids(_view(db, archived, window=0, bookend=0)["window"]) == [archived]
    assert _view(db, hidden)["window"] == []


@pytest.mark.parametrize("anchor_role", ["assistant", "tool"])
def test_explicit_nonprose_anchor_is_retained_with_native_hydration(db, anchor_role):
    before = db.append_message("s", "user", "Question")
    anchor = _call(db) if anchor_role == "assistant" else db.append_message(
        "s", "tool", "Tool investigation payload", tool_name="terminal")
    after = db.append_message("s", "assistant", "Answer")
    view = _view(db, anchor, window=1, bookend=3)
    assert _ids(view["window"]) == [before, anchor, after]
    native = db.get_messages_around("s", anchor, window=0)["window"][0]
    assert view["window"][1] == native
    assert view["bookend_start"] == view["bookend_end"] == []


def test_bookends_and_neighbors_skip_service_handoffs_and_empty_structured_calls(db):
    from agent.context_compressor import SUMMARY_PREFIX

    def noise():
        db.append_message("s", "user", "  " + SUMMARY_PREFIX + "\nsynthetic summary")
        db.append_message("s", "user", [{"type": "text", "text": "[CONTEXT SUMMARY]: old handoff"}])
        db.append_message("s", "user", "Flagged handoff", _compressed_summary=True)
        db.append_message("s", "assistant", "Hidden scaffolding", display_kind="hidden")
        db.append_message("s", "tool", "Tool payload", tool_name="terminal")
        db.append_message("s", "assistant", " \n\t")
        db.append_message("s", "assistant", [{"type": "text", "text": " \n"}])
        db.append_message("s", "assistant", [])
        _call(db)

    good = []
    for i in range(9):
        noise()
        good.append(db.append_message("s", "user" if i % 2 else "assistant", f"Real prose {i}"))
    noise()
    view = _view(db, good[4], window=1, bookend=2)
    assert _ids(view["window"]) == good[3:6]
    assert _ids(view["bookend_start"]) == good[:2]
    assert _ids(view["bookend_end"]) == good[-2:]
    combined = [row["id"] for key in ("bookend_start", "window", "bookend_end") for row in view[key]]
    assert len(combined) == len(set(combined))
    assert all(row["session_id"] == "s" for key in ("bookend_start", "window", "bookend_end") for row in view[key])


def test_source_bodies_are_not_flattened_trimmed_or_truncated(db):
    multiline = "  Первая строка\n\n" + "long body\n" * 1200 + "\tlast line  "
    structured = [{"type": "text", "text": "  exact\ntext  "},
                  {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]
    start = db.append_message("s", "user", multiline)
    before = db.append_message("s", "assistant", structured)
    anchor = db.append_message("s", "user", "Anchor", timestamp=1)
    after = db.append_message("s", "assistant", multiline, timestamp=0)
    end = db.append_message("s", "assistant", structured)
    view = _view(db, anchor, window=1, bookend=1)
    assert _ids(view["window"]) == [before, anchor, after]  # id, not regressing clock
    assert view["window"][0]["content"] == structured
    assert view["window"][-1]["content"] == multiline
    assert view["bookend_start"][0]["id"] == start
    assert view["bookend_start"][0]["content"] == multiline
    assert view["bookend_end"][0]["id"] == end
    assert view["bookend_end"][0]["content"] == structured


@pytest.mark.parametrize("carrier", ["[CONTEXT COMPACTION — REFERENCE ONLY] shortened handoff",
    "Preserved text\n[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]\n[CONTEXT SUMMARY]: handoff"])
def test_short_or_merged_handoff_does_not_consume_a_prose_slot(db, carrier):
    support = db.append_message("s", "assistant", "Actual previous answer")
    db.append_message("s", "user", carrier)
    anchor = db.append_message("s", "user", "Current question")
    assert _ids(_view(db, anchor, window=1, bookend=0)["window"]) == [support, anchor]


def test_raw_scan_hard_cap_reports_continuation_instead_of_claiming_boundary(db, monkeypatch):
    context = importlib.import_module("tools.session_search_context")
    monkeypatch.setattr(context, "_SCAN_ROW_LIMIT", 32)
    db.append_message("s", "assistant", "Distant support beyond cap")
    # Raw tool rows must count towards the work cap, not disappear in an unbounded SQL filter.
    db._execute_write(lambda conn: conn.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s', 'tool', ?, 0)",
        [("Not a factual neighbor",)] * 12000,
    ))
    anchor = db.append_message("s", "user", "Anchor")
    decode = db._decode_content
    decoded = []

    def count_decode(content):
        decoded.append(content)
        return decode(content)

    monkeypatch.setattr(db, "_decode_content", count_decode)
    steps = []
    with db._read_ctx() as conn:
        conn.set_progress_handler(lambda: steps.append(1) and 0, 100)
        try:
            view = _view(db, anchor, window=1, bookend=0)
        finally:
            conn.set_progress_handler(None, 0)
    assert _ids(view["window"]) == [anchor]
    assert view["messages_before"] == 0
    assert view["context_truncated"] is True
    assert view["context_scan_limit"] == 32
    cursor = view["context_continuation"]["before"]
    assert cursor["direction"] == "before"
    assert cursor["message_id"] < anchor
    assert cursor["rows_scanned"] == 32
    assert len(decoded) < 100
    assert len(steps) < 500  # actual SQLite VM work, not only Python decode count


def test_bookend_scan_cap_is_reported_too(db, monkeypatch):
    context = importlib.import_module("tools.session_search_context")
    monkeypatch.setattr(context, "_SCAN_ROW_LIMIT", 8)
    for _ in range(12):
        _call(db)
    anchor = db.append_message("s", "user", "Anchor")
    view = _view(db, anchor, window=0, bookend=1)
    assert view["bookend_start"] == []
    assert view["context_truncated"] is True
    assert "bookend_start" in view["context_continuation"]


def test_exact_work_cap_at_session_boundary_is_not_reported_as_incomplete(db, monkeypatch):
    context = importlib.import_module("tools.session_search_context")
    monkeypatch.setattr(context, "_SCAN_ROW_LIMIT", 8)
    for _ in range(8):
        _call(db)
    anchor = db.append_message("s", "user", "Anchor")
    view = _view(db, anchor, window=1, bookend=0)
    assert _ids(view["window"]) == [anchor]
    assert not view.get("context_truncated", False)


def test_oversized_structured_json_fails_honestly_without_decoding(db, monkeypatch):
    context = importlib.import_module("tools.session_search_context")
    monkeypatch.setattr(context, "_JSON_CHAR_LIMIT", 128)
    db.append_message("s", "assistant", [{"type": "text", "text": "x" * 200}])
    anchor = db.append_message("s", "user", "Anchor")
    with pytest.raises(ValueError, match="JSON.*limit"):
        _view(db, anchor, window=1, bookend=0)


def test_reader_failure_propagates_without_fabricating_empty_success(db, monkeypatch):
    anchor = db.append_message("s", "user", "Anchor")

    def broken_reader():
        raise sqlite3.OperationalError("synthetic read path unavailable")

    monkeypatch.setattr(db, "_read_ctx", broken_reader)
    with pytest.raises(sqlite3.OperationalError, match="synthetic read path unavailable"):
        _view(db, anchor)


def test_readonly_database_uses_same_visibility_and_never_needs_writer(db):
    before = db.append_message("s", "assistant", "Archived support")
    _state(db, before, active=0, compacted=1)
    anchor = db.append_message("s", "user", "Anchor")
    reader = SessionDB(db.db_path, read_only=True)
    try:
        view = _view(reader, anchor, window=1, bookend=0)
    finally:
        reader.close()
    assert _ids(view["window"]) == [before, anchor]


@pytest.mark.parametrize("window,bookend", [(0, 0), (-1, -1)])
def test_nonpositive_sizes_return_only_anchor(db, window, bookend):
    db.append_message("s", "assistant", "Before")
    anchor = db.append_message("s", "user", "Anchor")
    db.append_message("s", "assistant", "After")
    view = _view(db, anchor, window=window, bookend=bookend)
    assert _ids(view["window"]) == [anchor]
    assert (view["messages_before"], view["messages_after"]) == (0, 0)
    assert view["bookend_start"] == view["bookend_end"] == []
