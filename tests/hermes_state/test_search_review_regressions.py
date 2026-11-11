"""Synthetic pending-prefix ordering and fail-open route regressions."""
import json
import sqlite3

import pytest

from hermes_state import SessionDB
from tools.registry import registry
import tools.session_search_tool  # Register the real handler.


@pytest.fixture
def db(tmp_path):
    store = SessionDB(tmp_path / "history.db")
    store.create_session("s", source="cli")
    yield store
    store.close()


def _pending(db, ids):
    for table in ("messages_fts", "messages_fts_trigram"):
        db._execute_write(lambda conn, table=table: conn.execute(f"INSERT INTO {table}({table}) VALUES('delete-all')"))
    db._execute_write(lambda conn: conn.execute(db._CHUNK_INSERT_SQL, (0, ids[1])))
    db.set_meta("fts_rebuild_progress", str(ids[1]))
    db.set_meta("fts_rebuild_high_water", str(ids[-1]))


@pytest.mark.parametrize("content_only", [False, True])
@pytest.mark.parametrize("sort", ["oldest", "newest", None])
@pytest.mark.parametrize("timestamps", [(100, 200, 300), (100, 100, 100)])
def test_short_cjk_pending_prefixes_match_total_page_order(db, content_only, sort, timestamps):
    ids = [db.append_message("s", "user", "搜索 record", timestamp=t) for t in timestamps]
    _pending(db, ids)
    expected = ids if sort == "oldest" else ids[::-1]
    wide = db.search_messages("搜索", content_only=content_only, sort=sort, limit=20, fields=["id"])
    pages = [row for offset in range(6) for row in db.search_messages(
        "搜索", content_only=content_only, sort=sort, limit=1, offset=offset, fields=["id"])]
    assert wide == [{"id": mid} for mid in expected]
    assert pages == wide
    assert db.search_messages("搜索", content_only=content_only, sort=sort,
                              limit=2, offset=1, fields=["id"]) == wide[1:3]


@pytest.mark.parametrize("sort", ["oldest", "newest"])
def test_pending_timestamp_ties_use_the_same_order_on_both_surfaces(db, sort):
    ids = [db.append_message("s", "user", "Nebula comet " + "filler " * n, timestamp=100)
           for n in (8, 0, 4, 2, 1)]
    _pending(db, ids)
    expected = ids if sort == "oldest" else ids[::-1]
    wide = db.search_messages("Nebula comet", sort=sort, fields=["id"])
    pages = [row for offset in range(7) for row in db.search_messages(
        "Nebula comet", sort=sort, limit=1, offset=offset, fields=["id"])]
    assert wide == [{"id": mid} for mid in expected]
    assert pages == wide


def test_public_corruption_fallback_reports_like_not_cjk(db, monkeypatch):
    anchor = db.append_message("s", "user", "NebulaX cometX")
    original = db._read_all

    def corrupt_trigram(sql, params=()):
        if "messages_fts_trigram MATCH" in sql:
            raise sqlite3.DatabaseError('fts5: corrupt structure record for table "messages_fts_trigram"')
        return original(sql, params)

    monkeypatch.setattr(db, "_read_all", corrupt_trigram)
    entry = registry.get_entry("session_search")
    result = json.loads(entry.handler({"query": "Nebula comet"}, db=db))
    assert result["success"] is True
    assert result["results"][0]["match_message_id"] == anchor
    assert result["results"][0]["search_route"] == "like"
    assert result["results"][0]["partial_match"] is False
