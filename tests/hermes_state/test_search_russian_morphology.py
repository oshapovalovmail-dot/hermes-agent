"""Native session search recovers inflections without changing explicit query semantics."""
import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(db_path=tmp_path / "state.db")
    database.create_session("human", source="telegram")
    database._write_sql("UPDATE sessions SET started_at = 100 WHERE id = 'human'")
    yield database
    database.close()


@pytest.mark.parametrize("query,text", [
    ("вложением", "Вложение передано в исходном формате."),
    ("файлами", "Файлы остаются в рабочем каталоге."),
    ("документами", "Документы не разрешено публиковать без согласования."),
    ("слайдами", "Слайды готовы к просмотру."),
    ("регрессиями", "Регрессия воспроизведена."),
    ("ёлками", "Елка находится рядом с домом."),
])
def test_native_search_recovers_russian_inflected_word(db, query, text):
    target = db.append_message("human", role="user", content=text)
    rows = db.search_messages(query, fields=["id", "snippet", "role"])
    assert [row["id"] for row in rows] == [target]
    assert rows[0]["role"] == "user"
    assert ">>>" in rows[0]["snippet"]


def test_existing_exact_word_hits_are_not_replaced_by_morphology(db):
    exact = db.append_message("human", role="user", content="Работа с файлами завершена.")
    db.append_message("human", role="user", content="Файлы сохранены.")
    assert [r["id"] for r in db.search_messages("файлами")] == [exact]


def test_prefix_false_friend_does_not_become_a_morphology_hit(db):
    db.append_message("human", role="user", content="Документирование интерфейса завершено.")
    assert db.search_messages("документами") == []


@pytest.mark.parametrize("query", [
    '"файлами"', "файлами OR несуществующий", "файлами AND несуществующий",
    "файлами NOT черновик", "файлами*", "/work/файлами/report.txt",
])
def test_explicit_fts_syntax_and_paths_are_not_morphologically_relaxed(db, query):
    db.append_message("human", role="user", content="Файлы сохранены.")
    assert db.search_messages(query) == []


def test_morphology_keeps_role_source_and_session_date_filters(db):
    target = db.append_message("human", role="user", content="Файлы не публиковать.")
    db.append_message("human", role="assistant", content="Файлы проверены.")
    db.create_session("automation", source="cron")
    db._write_sql("UPDATE sessions SET started_at = 300 WHERE id = 'automation'")
    db.append_message("automation", role="user", content="Файлы сформированы.")
    rows = db.search_messages("файлами", role_filter=["user"], source_filter=["telegram"],
                              after_ts=50, before_ts=200, fields=["id"])
    assert rows == [{"id": target}]
    assert db.search_messages("файлами", source_filter=["telegram"], after_ts=200) == []
    assert db.search_messages("файлами", exclude_sources=["telegram", "cron"]) == []


def test_morphology_pagination_has_no_repeated_message(db):
    targets = [db.append_message("human", role="user", content=f"Файлы в каталоге номер {i}.")
               for i in range(3)]
    pages = [db.search_messages("файлами", limit=1, offset=i, fields=["id"]) for i in range(3)]
    assert all(len(page) == 1 for page in pages)
    assert {page[0]["id"] for page in pages} == set(targets)


def test_exhausted_morphology_page_does_not_switch_to_or_results(db):
    assert db._trigram_available, "Fixture requires the real trigram index"
    db.append_message("human", role="user", content="Nebula Сертификаты", timestamp=100)
    target = db.append_message("human", role="user", content="Nebula Файлы", timestamp=200)
    pages = [db.search_messages("Nebula файлами", sort="oldest", limit=1, offset=i, fields=["id"])
             for i in range(3)]
    assert pages == [[{"id": target}], [], []]


def test_no_morphology_conjunction_match_keeps_or_fallback(db):
    target = db.append_message("human", role="user", content="Nebula Сертификаты", timestamp=100)
    db.append_message("human", role="user", content="Orion Файлы", timestamp=200)
    pages = [db.search_messages("Nebula файлами", sort="oldest", limit=1, offset=i, fields=["id"])
             for i in range(3)]
    assert pages == [[{"id": target}], [], []]


def test_morphology_keeps_negation_in_the_original_evidence(db):
    db.append_message("human", role="user", content="Документы не разрешено публиковать без согласования.")
    rows = db.search_messages("документами", fields=["snippet"])
    assert len(rows) == 1
    assert "не разрешено публиковать без согласования" in rows[0]["snippet"]


def test_exhausted_exact_page_does_not_switch_to_morphological_results(db):
    db.append_message("human", role="user", content="Работа с файлами завершена.")
    db.append_message("human", role="user", content="Файлы сохранены.")
    assert db.search_messages("файлами", limit=1, offset=1) == []


def test_morphology_works_with_read_only_connection_without_main_schema_writes(db):
    target = db.append_message("human", role="user", content="Файлы не публиковать.")
    from contextlib import closing

    with closing(SessionDB(db_path=db.db_path, read_only=True)) as reader:
        before = reader._read_all("SELECT name, sql FROM main.sqlite_master ORDER BY name")
        assert reader.search_messages("файлами", fields=["id"]) == [{"id": target}]
        after = reader._read_all("SELECT name, sql FROM main.sqlite_master ORDER BY name")
        assert [tuple(row) for row in after] == [tuple(row) for row in before]


def test_morphology_does_not_drop_literal_project_anchor(db):
    target = db.append_message("human", role="user", content="Nebula: файлы сохранены.")
    db.append_message("human", role="user", content="Orion: файлы сохранены.")
    db.append_message("human", role="user", content="Nebula: сертификаты обновлены.")
    assert db.search_messages("Nebula файлами", fields=["id"]) == [{"id": target}]


def test_morphology_respects_timestamp_sort(db):
    older = db.append_message("human", role="user", content="Файлы сохранены.", timestamp=100)
    newer = db.append_message("human", role="user", content="Файлы проверены.", timestamp=200)
    assert [r["id"] for r in db.search_messages("файлами", sort="newest")] == [newer, older]
    assert [r["id"] for r in db.search_messages("файлами", sort="oldest")] == [older, newer]


def test_native_session_tool_exposes_original_morphology_evidence(db):
    import json
    from tools.session_search_tool import session_search

    target = db.append_message("human", role="user", content="Файлы не публиковать без согласования.")
    payload = json.loads(session_search(query="файлами", db=db, detail="compact"))
    assert "Файлы" in str(payload)
    assert "не публиковать без согласования" in str(payload)
    assert str(target) in str(payload)


def test_two_inflected_words_must_both_match(db):
    target = db.append_message("human", role="user", content="Файлы Документы")
    db.append_message("human", role="user", content="Файлы Слайды")
    assert db.search_messages("файлами документами", fields=["id"]) == [{"id": target}]


def test_expanded_multiword_query_executes_as_an_fts_conjunction(db):
    from hermes_state_morphology import russian_fts_query

    target = db.append_message("human", role="user", content="Nebula Файлы Документы")
    db.append_message("human", role="user", content="Nebula Сертификаты")
    with db._read_ctx() as conn:
        query = russian_fts_query(conn, "Nebula файлами")
        assert query is not None
        # Keep RED an assertion failure even when the old expression has invalid syntax.
        import sqlite3

        rows = []
        error = None
        try:
            rows = conn.execute("SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?", (query,)).fetchall()
        except sqlite3.OperationalError as exc:
            error = str(exc)
        assert error is None, f"Expanded conjunction must be executable FTS5: {error}"
    assert [row[0] for row in rows] == [target]


def test_exhausted_trigram_page_does_not_repeat_a_morphology_hit(db):
    assert db._trigram_available, "Fixture requires the real trigram index"
    target = db.append_message("human", role="user", content="файламиX файлы дополнительное описание")
    db.append_message("human", role="user", content="Файлы.")
    pages = [db.search_messages("файлами", limit=1, offset=i, fields=["id"]) for i in range(3)]
    assert pages == [[{"id": target}], [], []]


def test_trigram_first_page_guard_uses_the_same_role_filter(db):
    assert db._trigram_available, "Fixture requires the real trigram index"
    db.append_message("human", role="assistant", content="файламиX файлы дополнительное описание")
    targets = [db.append_message("human", role="user", content=f"Файлы номер {i}.") for i in range(2)]
    pages = [db.search_messages("файлами", role_filter=["user"], limit=1, offset=i, fields=["id"])
             for i in range(3)]
    assert {page[0]["id"] for page in pages if page} == set(targets)
    assert pages[-1] == []


@pytest.mark.parametrize("query,text", [
    ("перелётами", "Перелёты запланированы."),
    ("перелетами", "Перелёты запланированы."),
    ("чертежами", "Чертёж готов."),
])
def test_morphology_covers_mixed_e_yo_positions(db, query, text):
    target = db.append_message("human", role="user", content=text)
    assert db.search_messages(query, fields=["id"]) == [{"id": target}]


@pytest.mark.parametrize("query", ["/файлами", "файлами/", "файлами:", '"файлами'])
def test_raw_special_syntax_is_not_morphologically_relaxed_after_sanitization(db, query):
    db.append_message("human", role="user", content="Файлы сохранены.")
    assert db.search_messages(query) == []


def test_raw_special_syntax_keeps_existing_exact_search(db):
    target = db.append_message("human", role="user", content="Работа с файлами завершена.")
    assert db.search_messages("/файлами", fields=["id"]) == [{"id": target}]


def test_vocabulary_probe_budget_is_shared_between_words(db, monkeypatch):
    import hermes_state_morphology as morphology

    monkeypatch.setattr(morphology, "_MAX_VOCAB_TERMS", 3)
    db.append_message("human", role="user", content="Файлы Слайды")
    with db._read_ctx() as conn:
        assert morphology.russian_fts_query(conn, "файлами слайдами") is None


def test_vocabulary_probe_budget_is_shared_between_e_yo_variants(db, monkeypatch):
    import hermes_state_morphology as morphology

    monkeypatch.setattr(morphology, "_MAX_VOCAB_TERMS", 2)
    db.append_message("human", role="user", content="Елка Ёлка")
    with db._read_ctx() as conn:
        assert morphology.russian_fts_query(conn, "ёлками") is None


def test_many_e_yo_positions_abort_with_bounded_vocabulary_probes(db, monkeypatch):
    import hermes_state_morphology as morphology

    monkeypatch.setattr(morphology, "_MAX_VOCAB_TERMS", 8)
    db.append_message("human", role="user", content="Файлы")
    probes = []
    with db._read_ctx() as conn:
        conn.set_trace_callback(lambda sql: probes.append(sql) if sql.startswith("SELECT term FROM") else None)
        try:
            query = morphology.russian_fts_query(conn, "б" + "е" * 12 + "тами файлами")
        finally:
            conn.set_trace_callback(None)
    assert query is None
    assert len(probes) <= morphology._MAX_VOCAB_TERMS


def test_vocabulary_range_overflow_abandons_expansion(db):
    from hermes_state_morphology import _MAX_VOCAB_TERMS, russian_fts_query

    db.append_message("human", role="user", content=" ".join(f"файл{i}" for i in range(_MAX_VOCAB_TERMS + 1)))
    with db._read_ctx() as conn:
        assert russian_fts_query(conn, "файлами") is None


def test_inflection_form_overflow_abandons_expansion(db, monkeypatch):
    import hermes_state_morphology as morphology

    monkeypatch.setattr(morphology, "_MAX_FORMS", 2)
    db.append_message("human", role="user", content="Файл Файлы Файлом")
    with db._read_ctx() as conn:
        assert morphology.russian_fts_query(conn, "файлами") is None
