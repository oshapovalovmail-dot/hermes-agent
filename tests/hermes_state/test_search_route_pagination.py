"""A filtered first page selects one route for the entire paginated search."""
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


def _pages(db, query, **kwargs):
    return [db.search_messages(query, limit=1, offset=i, fields=["id"], **kwargs)
            for i in range(4)]


@pytest.mark.parametrize("sort", ["oldest", "newest", None])
@pytest.mark.parametrize("route", ["exact", "trigram"])
def test_exhausted_strict_route_never_switches_to_or(db, route, sort):
    db.append_message("human", role="user", content="Nebula unrelated", timestamp=50)
    text = "Nebula comet" if route == "exact" else "NebulaX cometX"
    target = db.append_message("human", role="user", content=text, timestamp=100)
    db.append_message("human", role="user", content="comet unrelated", timestamp=150)
    assert _pages(db, "Nebula comet", sort=sort) == [[{"id": target}], [], [], []]


@pytest.mark.parametrize("strict_route", ["exact", "trigram", "morphology"])
@pytest.mark.parametrize("excluded_by", ["role", "source", "time", "inactive", "hidden"])
def test_first_page_route_probe_uses_identical_filters(db, strict_route, excluded_by):
    db.create_session("outside", source="cli")
    db._write_sql("UPDATE sessions SET started_at = 300 WHERE id = 'outside'")
    query = "Nebula файлами" if strict_route == "morphology" else "Nebula comet"
    text = {"exact": "Nebula comet", "trigram": "NebulaX cometX",
            "morphology": "Nebula Файлы"}[strict_route]
    strict = db.append_message("outside" if excluded_by in {"source", "time"} else "human",
                               role="assistant" if excluded_by == "role" else "user",
                               content=text, timestamp=100)
    filters = {"role": {"role_filter": ["user"]},
               "source": {"source_filter": ["telegram"]},
               "time": {"after_ts": 50, "before_ts": 200},
               "inactive": {}, "hidden": {}}[excluded_by]
    if excluded_by == "inactive":
        db._write_sql("UPDATE messages SET active = 0, compacted = 0 WHERE id = ?", (strict,))
    if excluded_by == "hidden":
        db._write_sql("UPDATE messages SET display_kind = 'hidden' WHERE id = ?", (strict,))
    first = db.append_message("human", role="user", content="Nebula distant", timestamp=50)
    second = db.append_message("human", role="user", content="Nebula nearby", timestamp=150)
    assert _pages(db, query, sort="oldest", **filters) == [[{"id": first}], [{"id": second}], [], []]


@pytest.mark.parametrize("sort", ["oldest", "newest"])
def test_genuine_strict_miss_can_paginate_or_results(db, sort):
    first = db.append_message("human", role="user", content="Nebula distant", timestamp=50)
    second = db.append_message("human", role="user", content="comet nearby", timestamp=150)
    expected = [first, second] if sort == "oldest" else [second, first]
    assert _pages(db, "Nebula comet", sort=sort) == [[{"id": i}] for i in expected] + [[], []]


def test_exhausted_morphology_route_does_not_select_or(db):
    db.append_message("human", role="user", content="Nebula distant", timestamp=50)
    target = db.append_message("human", role="user", content="Nebula Файлы", timestamp=100)
    assert _pages(db, "Nebula файлами", sort="oldest") == [[{"id": target}], [], [], []]


@pytest.mark.parametrize("sort", ["oldest", "newest", None])
@pytest.mark.parametrize("content_only", [False, True])
def test_pending_backfill_merges_stable_bounded_prefix_before_slicing(db, sort, content_only):
    indexed = db.append_message("human", role="user", content="Nebula comet", timestamp=200)
    earlier_gap = db.append_message("human", role="user", content="Nebula comet", timestamp=100)
    later_gap = db.append_message("human", role="assistant", content="Nebula comet", timestamp=300)
    db._execute_write(lambda conn: conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('delete-all')"))
    db._execute_write(lambda conn: conn.execute(
        "INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES('delete-all')"))
    db._execute_write(lambda conn: conn.execute(db._CHUNK_INSERT_SQL, (0, indexed)))
    db._execute_write(lambda conn: conn.execute(db._TRIGRAM_CHUNK_INSERT_SQL, (0, indexed)))
    db.set_meta("fts_rebuild_progress", str(indexed))
    db.set_meta("fts_rebuild_high_water", str(later_gap))
    expected = {"oldest": [earlier_gap, indexed, later_gap], "newest": [later_gap, indexed, earlier_gap],
                None: [indexed, later_gap, earlier_gap]}[sort]
    pages = _pages(db, "Nebula comet", sort=sort, content_only=content_only)
    assert pages == [[{"id": i}] for i in expected] + [[]]
    assert db.search_messages("Nebula comet", sort=sort, content_only=content_only,
                              limit=2, offset=1, fields=["id"]) == [{"id": i} for i in expected[1:]]
    assert _pages(db, "Nebula comet", sort=sort, content_only=content_only,
                  role_filter=["user"], before_ts=200)[-2:] == [[], []]
