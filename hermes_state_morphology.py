"""Read-only Russian inflection expansion over the existing FTS5 vocabulary.

The connection-local vocabulary view needs no persistent index, rebuild, UDF or
write trigger. Expanded terms must share a full stem: prefix similarity alone
would confuse documents with documentation and projects with projectors.
"""
from __future__ import annotations

from itertools import product
import logging
import re
import sqlite3
from typing import Any

from agent.recall_morphology import russian_stem

logger = logging.getLogger("hermes_state")
_PLAIN_QUERY = re.compile(r"[A-Za-zА-Яа-яЁё0-9\s]+")
_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
_MAX_WORDS = 16
_MAX_VOCAB_TERMS = 256  # Query-wide budget: prefix probes plus returned vocabulary terms.
_MAX_FORMS = 32
_VOCAB_SQL = "CREATE VIRTUAL TABLE IF NOT EXISTS temp.hermes_memory_vocab USING fts5vocab(main, messages_fts, row)"


def _inflections(conn: sqlite3.Connection, word: str, stem: str, remaining: int) -> tuple[list[str], int]:
    forms = {word.casefold()}
    # Each е can independently stand for ё. Enumerate lazily so even many such
    # positions cannot exceed the shared budget or allocate an exponential list.
    for letters in product(*("её" if char == "е" else char for char in stem)):
        if remaining <= 0:
            return [], remaining
        remaining -= 1
        prefix = "".join(letters)
        terms = conn.execute(
            "SELECT term FROM temp.hermes_memory_vocab WHERE term >= ? AND term < ? LIMIT ?",
            (prefix, prefix + "\uffff", remaining + 1),
        ).fetchall()
        remaining -= len(terms)
        if remaining < 0:
            return [], remaining
        forms.update(row[0] for row in terms if russian_stem(row[0]) == stem)
        if len(forms) > _MAX_FORMS:
            return [], remaining
    return sorted(forms), remaining


def russian_fts_query(conn: sqlite3.Connection, query: str) -> str | None:
    """Expand only a bounded plain query; explicit FTS syntax remains literal."""
    if len(query) > 512 or not _PLAIN_QUERY.fullmatch(query):
        return None
    words = query.split()
    if not words or len(words) > _MAX_WORDS or any(w.upper() in _OPERATORS for w in words):
        return None
    stems = [russian_stem(word) for word in words]
    if not any(stems):
        return None
    conn.execute(_VOCAB_SQL)
    groups = []
    expanded = False
    remaining = _MAX_VOCAB_TERMS
    for word, stem in zip(words, stems):
        forms = [word.casefold()]
        if stem:
            forms, remaining = _inflections(conn, word, stem, remaining)
        if not forms:
            return None
        expanded |= len(forms) > 1
        groups.append("(" + " OR ".join('"' + form + '"' for form in forms) + ")")
    return " AND ".join(groups) if expanded else None


def search_russian_inflections(db: Any, query: str, route: dict, *, raw_query: str) -> list[dict] | None:
    """Use the same FTS ranking, projections, pagination and filters as the main route."""
    if route.get("offset", 0):
        # An exhausted exact page is not a miss: switching routes would duplicate
        # earlier hits or silently change the meaning of subsequent pages.
        first_page = {**route, "limit": 1, "offset": 0}
        if db._match_rows("messages_fts", query, fail_open="Russian morphology", **first_page):
            return None
        if db._trigram_available and db._trigram_eligible_tokens(query):
            from hermes_state_search import _quote_fts_tokens

            fb_query = _quote_fts_tokens(query.strip('"').strip())
            if db._match_rows("messages_fts_trigram", fb_query, fail_open="Russian morphology", **first_page):
                return None
    try:
        with db._read_ctx() as conn:
            expanded = russian_fts_query(conn, raw_query)
    except sqlite3.OperationalError:
        logger.debug("Russian vocabulary expansion unavailable; retaining existing search routes", exc_info=True)
        return None
    except sqlite3.DatabaseError as exc:
        if not db._enter_fts_fail_open(exc):
            raise
        return None
    if expanded is None:
        return None
    matches = db._match_rows("messages_fts", expanded, fail_open="Russian morphology", **route)
    if matches is None or matches:
        return matches
    # An empty page selects morphology only if the filtered first page exists.
    if route.get("offset", 0) and db._match_rows(
        "messages_fts", expanded, fail_open="Russian morphology", **{**route, "limit": 1, "offset": 0}
    ):
        return []
    return None
