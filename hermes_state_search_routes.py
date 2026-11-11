"""Miss-only Latin search routes; an exhausted page is not a routing miss."""
from typing import Any


def mark_search_route(rows, name):
    for row in rows or []:
        row["search_route"] = name
    return rows


def _first_page_exists(db: Any, table: str, query: str, route: dict) -> bool:
    """Probe one hit with the exact same scope, without counting or ranking the corpus."""
    return bool(route["offset"] and db._match_rows(
        table, query, fail_open="Search route probe", **{**route, "limit": 1, "offset": 0}))


def _canonical_after_failure(db: Any, query: str, route: dict, sort: str | None) -> list[dict]:
    return mark_search_route(db._search_messages_like_fallback(
        query, sort=sort, **{key: value for key, value in route.items() if key != "order_by_sql"}), "like")


def search_latin_fallbacks(
    db: Any, query: str, raw_query: str, matches: list[dict], route: dict, sort: str | None,
) -> list[dict]:
    """Choose exact → trigram → morphology → OR using filtered first-page existence.

    Every selected route honors the requested offset. Morphology's None means
    "not selected", whereas [] means its page is exhausted and must remain empty.
    """
    from hermes_state_morphology import search_russian_inflections
    from hermes_state_search import _quote_fts_tokens

    if matches or db._fts_stale:
        return mark_search_route(matches, "like" if db._fts_stale else "exact")
    if _first_page_exists(db, "messages_fts", query, route):
        return []
    if db._fts_stale:
        return _canonical_after_failure(db, query, route, sort)

    if db._trigram_available and db._trigram_eligible_tokens(query):
        fb_query = _quote_fts_tokens(query.strip('"').strip())
        matches = db._match_rows("messages_fts_trigram", fb_query, fail_open="Trigram", **route)
        if matches or _first_page_exists(db, "messages_fts_trigram", fb_query, route):
            return mark_search_route(matches or [], "trigram")
    if db._fts_stale:
        return _canonical_after_failure(db, query, route, sort)

    morphology_matches = search_russian_inflections(db, query, route, raw_query=raw_query)
    if morphology_matches is not None:
        return mark_search_route(morphology_matches, "morphology")
    if db._fts_stale:
        return _canonical_after_failure(db, query, route, sort)

    relaxed = db._or_relaxed_query(query)
    if relaxed is not None:
        matches = db._match_rows("messages_fts", relaxed, fail_open="OR-relaxed",
                                 operational_debug="OR-relaxed FTS retry failed; keeping empty result", **route)
    if db._fts_stale:
        return _canonical_after_failure(db, query, route, sort)
    return mark_search_route(matches or [], "or_relaxed")


def search_pending_page(
    db: Any, query: str, route: dict, sort: str | None, *, is_cjk: bool, wants_unindexed_rows: bool,
) -> list[dict] | None:
    """Merge page-sized prefixes before slicing, rather than repeating the gap's front.

    Timestamp sorts merge chronologically; rank sort keeps indexed relevance first
    and appends canonical gap hits. Work and memory are bounded by the requested
    prefix (offset + limit), not by corpus size. None is a strict miss across BOTH
    surfaces, allowing the normal substring/morphology/OR routes.
    """
    import logging
    import sqlite3

    offset = max(0, route["offset"])
    normalized_sort = sort.strip().lower() if isinstance(sort, str) else None
    prefix_route = {**route, "limit": offset + route["limit"], "offset": 0}
    if normalized_sort in {"oldest", "newest"}:
        order = "ASC" if normalized_sort == "oldest" else "DESC"
        # Both bounded surfaces must be prefixes of the merge's *total* order.
        prefix_route["order_by_sql"] = f"ORDER BY m.timestamp {order}, m.id {order}"
    if is_cjk:
        indexed = db._search_cjk(query, wants_unindexed_rows, prefix_route, sort=sort)
    else:
        indexed = db._match_rows("messages_fts", query, fail_open="Backfill search", **prefix_route)
    if db._fts_stale:
        return _canonical_after_failure(db, query, route, sort)
    gap_filters = {key: value for key, value in route.items() if key not in {"order_by_sql", "offset", "limit"}}
    try:
        gap = db._search_unindexed_gap(query, prefix_route["limit"], sort=sort, **gap_filters)
    except sqlite3.OperationalError as exc:
        logging.getLogger("hermes_state").debug("Unindexed-gap supplement skipped: %s", exc)
        gap = []
    if not indexed and not gap:
        return None
    merged = {}
    for row in [*(indexed or []), *gap]:
        merged.setdefault(row["id"], row)
    matches = list(merged.values())
    if normalized_sort in {"oldest", "newest"}:
        matches.sort(key=lambda row: (row["timestamp"], row["id"]), reverse=normalized_sort == "newest")
    return matches[offset:offset + route["limit"]]
