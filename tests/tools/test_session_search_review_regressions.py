"""Synthetic legacy hydration and title-discovery boundary regressions."""
import json
import sqlite3

import pytest

from hermes_state import SessionDB
from tools.registry import registry
from tools.session_search_context import get_recall_anchored_view
import tools.session_search_tool  # Register the real handler.


@pytest.fixture
def db(tmp_path):
    store = SessionDB(tmp_path / "history.db")
    store.create_session("s", source="cli")
    yield store
    store.close()


def _dispatch(db, **args):
    return json.loads(registry.get_entry("session_search").handler(args, db=db))


def _drop_optional_columns(db, columns):
    path = db.db_path
    db.close()
    with sqlite3.connect(path) as conn:
        for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='messages'").fetchall():
            conn.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        for column in columns:
            conn.execute(f'ALTER TABLE messages DROP COLUMN "{column}"')
    return path


@pytest.mark.parametrize("columns", [
    ("display_metadata",), ("display_kind",), ("_compressed_summary",),
    ("display_metadata", "display_kind", "_compressed_summary"),
])
def test_legacy_native_recall_without_optional_columns(db, columns):
    before = db.append_message("s", "user", "Recorded first note")
    hidden = db.append_message("s", "user", "Rewound note")
    anchor = db.append_message("s", "assistant", "Recorded second note")
    db._write_sql("UPDATE messages SET active=0, compacted=0 WHERE id=?", (hidden,))
    db._write_sql("UPDATE messages SET active=0, compacted=1 WHERE id=?", (before,))
    reader = SessionDB(_drop_optional_columns(db, columns), read_only=True)
    try:
        schema = reader._conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
        native = reader.get_anchored_view("s", anchor, window=2, bookend=0)
        view = get_recall_anchored_view(reader, "s", anchor, window=2, bookend=0)
        assert view["window"] == [m for m in native["window"] if m["active"] or m["compacted"]]
        assert [m["id"] for m in view["window"]] == [before, anchor]
        assert reader._conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema
        assert not reader._conn.in_transaction
    finally:
        reader.close()


def test_public_legacy_readonly_discovery_retains_the_hit(db):
    anchor = db.append_message("s", "user", "Nebula comet")
    reader = SessionDB(_drop_optional_columns(db, ("display_metadata", "_compressed_summary")), read_only=True)
    try:
        assert reader.search_messages("Nebula comet", fields=["id"]) == [{"id": anchor}]
        payload = _dispatch(reader, query="Nebula comet")
        assert payload["success"] is True
        assert payload["count"] == 1
        assert payload["results"][0]["messages"][0]["content"] == "Nebula comet"
    finally:
        reader.close()


def test_title_discovery_selects_first_substantive_anchor_without_raw_bookends(db):
    db.set_session_title("s", "lavender ledger")
    raw = db.append_message("s", "tool", "RAW_TOOL_PAYLOAD", tool_name="terminal")
    db.append_message("s", "assistant", "")
    db.append_message("s", "user", "Service carrier", display_kind="hidden")
    db.append_message("s", "user", "[CONTEXT SUMMARY]: prior context")
    rewound = db.append_message("s", "user", "Rewound note")
    db._write_sql("UPDATE messages SET active=0, compacted=0 WHERE id=?", (rewound,))
    anchor = db.append_message("s", "user", "Real human goal")
    db._write_sql("UPDATE messages SET active=0, compacted=1 WHERE id=?", (anchor,))
    entry = _dispatch(db, query="lavender ledger")["results"][0]
    assert entry["match_message_id"] == anchor
    assert entry["messages"][0]["anchor"] is True
    assert [m["id"] for key in ("messages", "bookend_start", "bookend_end") for m in entry[key]] == [anchor]
    explicit = _dispatch(db, query="lavender ledger", include_tool_calls=True)["results"][0]
    assert explicit["match_message_id"] == raw
    assert explicit["messages"][0]["content"] == "RAW_TOOL_PAYLOAD"
    for args in ({"session_id": "s"}, {"session_id": "s", "around_message_id": raw}):
        assert any(m["id"] == raw and m["content"] == "RAW_TOOL_PAYLOAD"
                   for m in _dispatch(db, **args)["messages"])


@pytest.mark.parametrize("capped", [False, True])
def test_title_without_substantive_anchor_never_falls_back_to_raw(db, monkeypatch, capped):
    import tools.session_search_context as context
    monkeypatch.setattr(context, "_SCAN_ROW_LIMIT", 8)
    db.set_session_title("s", "lavender ledger")
    for _ in range(12 if capped else 2):
        db.append_message("s", "tool", "RAW_TOOL_PAYLOAD", tool_name="terminal")
    if capped:
        db.append_message("s", "user", "Substantive but beyond the work cap")
    entry = _dispatch(db, query="lavender ledger")["results"][0]
    assert entry["match_message_id"] is None
    assert all(entry[key] == [] for key in ("messages", "bookend_start", "bookend_end"))
    if capped:
        assert entry["context_truncated"] is True
        assert entry["context_scan_limit"] == 8
        cursor = entry["context_continuation"]["anchor"]
        assert cursor == {"direction": "after", "message_id": 8, "rows_scanned": 8}
    else:
        assert "context_truncated" not in entry


def test_automatic_title_anchor_and_hydration_share_one_snapshot(db, monkeypatch):
    import tools.session_search_context as context
    db.set_session_title("s", "lavender ledger")
    db.append_message("s", "tool", "RAW_TOOL_PAYLOAD")
    anchor = db.append_message("s", "user", "Original substantive note")
    original = context._hydrate_ids

    def mutate(db_arg, conn, session_id, ids):
        db._write_sql("UPDATE messages SET active=0, compacted=0, content='Changed' WHERE id=?", (anchor,))
        return original(db_arg, conn, session_id, ids)

    monkeypatch.setattr(context, "_hydrate_ids", mutate)
    entry = _dispatch(db, query="lavender ledger")["results"][0]
    assert entry["match_message_id"] == anchor
    assert entry["messages"][0]["content"] == "Original substantive note"
    assert db._read_one("SELECT content FROM messages WHERE id=?", (anchor,))[0] == "Changed"


def test_automatic_anchor_does_not_expand_the_four_scan_work_budget(db, monkeypatch):
    import tools.session_search_context as context
    monkeypatch.setattr(context, "_SCAN_ROW_LIMIT", 32)
    for _ in range(31):
        db.append_message("s", "user", " ")
    anchor = db.append_message("s", "user", "First substantive note")
    for _ in range(200):
        db.append_message("s", "user", " ")
    decoded = []
    decode = db._decode_content

    def count_decode(raw):
        decoded.append(raw)
        return decode(raw)

    monkeypatch.setattr(db, "_decode_content", count_decode)
    view = get_recall_anchored_view(db, "s", None)
    assert [m["id"] for m in view["window"]] == [anchor]
    assert view["context_truncated"] is True
    # Every raw row in this fixture requires a decode. Include anchor hydration.
    assert len(decoded) <= 4 * context._SCAN_ROW_LIMIT + 1
