"""Content-only search matches evidence in the body, never call metadata."""
from contextlib import closing
import json
import sqlite3

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(db_path=tmp_path / "state.db")
    assert database._trigram_available, "These contracts require real FTS5 trigram"
    database.create_session("human", source="telegram")
    database._write_sql("UPDATE sessions SET started_at = 100 WHERE id = 'human'")
    yield database
    database.close()


def _seed(db, body, metadata):
    calls = [{"id": "call1", "type": "function", "function": {
        "name": metadata, "arguments": json.dumps({"query": metadata}, ensure_ascii=False)}}]
    body_id = db.append_message("human", role="user", content=body, timestamp=100)
    mixed_id = db.append_message("human", role="assistant", content=body, tool_calls=calls, timestamp=200)
    name_id = db.append_message("human", role="assistant", content="unrelated body", tool_name=metadata,
                                timestamp=300)
    args_id = db.append_message("human", role="assistant", content="unrelated body", tool_calls=calls,
                                timestamp=400)
    return body_id, mixed_id, name_id, args_id


@pytest.mark.parametrize("query,body,metadata", [
    ("Nebula comet", "Nebula comet", "Nebula comet"),
    ("Nebula comet", "NebulaX cometX", "NebulaX cometX"),
    ("файлами", "Файлы сохранены", "Файлы сохранены"),
    ("Nebula absent", "Nebula comet", "Nebula comet"),
    ("搜索关键词", "现在搜索关键词结束", "搜索关键词"),
    ("搜索", "现在搜索结束", "搜索"),
])
def test_content_only_covers_all_native_routes_without_metadata_hits(db, query, body, metadata):
    body_id, mixed_id, name_id, args_id = _seed(db, body, metadata)
    rows = db.search_messages(query, content_only=True, sort="oldest", fields=["id", "snippet"])
    # The legacy short-CJK LIKE route intentionally ignores sort="oldest".
    expected_ids = [mixed_id, body_id] if query == "搜索" else [body_id, mixed_id]
    assert [row["id"] for row in rows] == expected_ids
    for row in rows:
        snippet = row["snippet"].replace(">>>", "").replace("<<<", "").replace("...", "")
        assert snippet in body
    legacy_ids = {r["id"] for r in db.search_messages(query)}
    assert name_id in legacy_ids
    assert db.search_messages(query, content_only=False) == db.search_messages(query)
    if query.isascii() and body == "Nebula comet":
        # Trigram omits tool_calls; serialized non-ASCII arguments may be escaped.
        assert args_id in legacy_ids


@pytest.mark.parametrize("state", ["stale", "gap", "tool"])
def test_content_only_canonical_routes_do_not_search_call_arguments(db, state):
    body_id, mixed_id, name_id, args_id = _seed(db, "Nebula comet", "Nebula comet")
    kwargs = {}
    if state == "stale":
        db._fts_stale = True
    elif state == "gap":
        db._execute_write(lambda conn: conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('delete-all')"))
        db._execute_write(lambda conn: conn.execute(
            "INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES('delete-all')"))
        db.set_meta("fts_rebuild_progress", "0")
        db.set_meta("fts_rebuild_high_water", str(args_id))
    else:
        db._write_sql("UPDATE messages SET role = 'tool' WHERE id IN (?, ?, ?, ?)",
                      (body_id, mixed_id, name_id, args_id))
        kwargs["role_filter"] = ["tool"]
    rows = db.search_messages("Nebula comet", content_only=True, fields=["id"], **kwargs)
    assert {r["id"] for r in rows} == {body_id, mixed_id}
    assert {r["id"] for r in db.search_messages("Nebula comet", **kwargs)} == {
        body_id, mixed_id, name_id, args_id}


@pytest.mark.parametrize("stale", [False, True])
@pytest.mark.parametrize("query", ['"Nebula comet"', "Nebula AND comet", "Nebula NOT draft", "build-42.log"])
def test_content_only_keeps_query_syntax_and_body_negation(db, stale, query):
    target = db.append_message("human", role="assistant", content="Nebula comet build-42.log",
                               tool_calls=[{"function": {"name": "draft", "arguments": "draft"}}])
    db.append_message("human", role="user", content="Nebula draft")
    db.append_message("human", role="assistant", content="unrelated", tool_name="Nebula comet build-42.log")
    db._fts_stale = stale
    assert db.search_messages(query, content_only=True, fields=["id"]) == [{"id": target}]


def test_content_only_keeps_visibility_role_time_and_projection(db):
    body_id, mixed_id, _, _ = _seed(db, "Nebula comet", "Nebula comet")
    db._write_sql("UPDATE messages SET active = 0, compacted = 1 WHERE id = ?", (body_id,))
    kwargs = dict(content_only=True, source_filter=["telegram"], role_filter=["user"],
                  after_ts=50, before_ts=200, fields=["id", "role"])
    assert db.search_messages("Nebula comet", **kwargs) == [{"id": body_id, "role": "user"}]
    assert db.search_messages("Nebula comet", **{**kwargs, "after_ts": 200}) == []
    db._write_sql("UPDATE messages SET display_kind = 'hidden' WHERE id = ?", (body_id,))
    assert db.search_messages("Nebula comet", **kwargs) == []
    assert mixed_id != body_id


def test_content_only_read_only_search_leaves_main_schema_unchanged(db):
    body_id, mixed_id, _, _ = _seed(db, "Файлы сохранены", "Файлы сохранены")
    with closing(SessionDB(db_path=db.db_path, read_only=True)) as reader:
        before = [tuple(r) for r in reader._read_all("SELECT name, sql FROM main.sqlite_master ORDER BY name")]
        assert {r["id"] for r in reader.search_messages("файлами", content_only=True)} == {body_id, mixed_id}
        after = [tuple(r) for r in reader._read_all("SELECT name, sql FROM main.sqlite_master ORDER BY name")]
        assert after == before


def test_content_only_corrupt_fts_fails_open_to_body_only(db, monkeypatch):
    body_id, mixed_id, _, _ = _seed(db, "Nebula comet", "Nebula comet")
    original = db._read_all

    def corrupt_match(sql, params=()):
        if "messages_fts MATCH" in sql:
            raise sqlite3.DatabaseError('fts5: corrupt structure record for table "messages_fts"')
        return original(sql, params)

    monkeypatch.setattr(db, "_read_all", corrupt_match)
    assert {r["id"] for r in db.search_messages("Nebula comet", content_only=True)} == {body_id, mixed_id}
    assert db._fts_stale


def test_content_only_route_probe_ignores_metadata_only_strict_hits(db):
    metadata = db.append_message("human", role="assistant", content="unrelated", tool_name="Nebula comet",
                                 timestamp=50)
    first = db.append_message("human", role="user", content="Nebula distant", timestamp=100)
    second = db.append_message("human", role="user", content="comet nearby", timestamp=200)
    pages = [db.search_messages("Nebula comet", content_only=True, sort="oldest", limit=1,
                                offset=i, fields=["id"]) for i in range(4)]
    assert pages == [[{"id": first}], [{"id": second}], [], []]
    assert db.search_messages("Nebula comet", content_only=False, fields=["id"]) == [{"id": metadata}]


@pytest.mark.parametrize("query,expected_indexes", [
    ('"搜索 关键词"', [0]),
    ("搜索 NOT 草稿", [0]),
    ("搜索 OR 关键词", [0, 1, 2]),
])
def test_content_only_short_cjk_keeps_boolean_and_phrase_syntax(db, query, expected_indexes):
    texts = ["搜索 关键词", "搜索 草稿", "关键词 单独"]
    ids = [db.append_message("human", role="user", content=text) for text in texts]
    db.append_message("human", role="assistant", content="unrelated", tool_name="搜索 关键词")
    assert {r["id"] for r in db.search_messages(query, content_only=True)} == {
        ids[index] for index in expected_indexes}


@pytest.mark.parametrize("query,expected_indexes", [
    ("Nebula NOT draft", [0, 2]),
    ("Nebula OR comet", [0, 1, 2, 3]),
    ('"Nebula comet"', [0]),
    ("build-42.log", [0]),
])
def test_content_only_gap_preserves_boolean_phrases_and_identifiers(db, query, expected_indexes):
    texts = ["Nebula comet build-42.log", "Nebula draft", "Nebula unrelated", "comet unrelated"]
    ids = [db.append_message("human", role="user", content=text) for text in texts]
    db._execute_write(lambda conn: conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('delete-all')"))
    db._execute_write(lambda conn: conn.execute(
        "INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES('delete-all')"))
    db.set_meta("fts_rebuild_progress", "0")
    db.set_meta("fts_rebuild_high_water", str(ids[-1]))
    assert {r["id"] for r in db.search_messages(query, content_only=True)} == {
        ids[index] for index in expected_indexes}
