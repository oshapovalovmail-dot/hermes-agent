"""Discovery-only substantive recall windows; raw read/scroll primitives stay unchanged.

Each keyset scan reads at most 2048 raw rows, in chunks of 128,
plus one id-only continuation probe. Hidden/tool/service rows consume work budget
but never message slots. A short window under that cap is NOT a session boundary:
``context_truncated`` and ``context_continuation`` expose unfinished scans. Cursor
ids are raw scan positions (exclusive), not claimed substantive neighbors.

Source bodies are returned through SessionDB's native hydrator without edits.
JSON inputs above 1,000,000 characters fail explicitly rather than incur unbounded
parsing or silently truncate evidence. Database/decoder errors propagate to the
caller's normal error boundary; there is no full-history or raw-window fallback.
"""

from typing import Any

_SCAN_ROW_LIMIT = 2048
_SCAN_CHUNK_SIZE = 128
_JSON_CHAR_LIMIT = 1_000_000
_HANDOFF_PREFIXES = ("[CONTEXT COMPACTION", "[CONTEXT SUMMARY]:")
_MERGED_HANDOFF = "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]"
_VISIBLE = "(active = 1 OR compacted = 1)"


# Limit raw rows BEFORE filtering, so a giant tool-only session cannot force a
# whole-session scan. CASE also avoids bringing tool payloads into Python.
def _candidate_content(conn):
    # Read-only legacy schemas need the same absent-column defaults as native hydration.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
    conditions = [_VISIBLE, "role IN ('user', 'assistant')"]
    if "display_kind" in columns:
        conditions.append("COALESCE(display_kind, '') IN ('', 'steer')")
    if "_compressed_summary" in columns:
        conditions.append("COALESCE(_compressed_summary, 0) = 0")
    return f"CASE WHEN {' AND '.join(conditions)} THEN content END AS content"


def _check_json_size(db, raw, *, encoded_content=False):
    is_json = isinstance(raw, str) and (not encoded_content or raw.startswith(db._CONTENT_JSON_PREFIX))
    if is_json and len(raw) > _JSON_CHAR_LIMIT:
        raise ValueError(f"recall context JSON character limit exceeded ({_JSON_CHAR_LIMIT})")


def _has_prose(content: Any) -> bool:
    """Inspect text parts only: a call's arguments/reasoning are not factual prose."""
    if isinstance(content, str):
        return bool(content.strip())
    parts = content if isinstance(content, list) else [content]
    for part in parts:
        if isinstance(part, str) and part.strip():
            return True
        if isinstance(part, dict) and part.get("type", "text") in ("text", "input_text", "output_text"):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return True
    return False


def _is_handoff(content):
    """Recognize historical carriers without importing the compressor/model stack."""
    parts = content if isinstance(content, list) else [content]
    text = "\n".join(part if isinstance(part, str) else part.get("text", "")
                     for part in parts if isinstance(part, str) or
                     isinstance(part, dict) and isinstance(part.get("text"), str))
    if _MERGED_HANDOFF in text:
        text = text.partition(_MERGED_HANDOFF)[2]
    return text.lstrip().startswith(_HANDOFF_PREFIXES)


def _scan(db, conn, session_id, *, candidate_content, direction, boundary, count, stop=None):
    """Select substantive ids within one exclusive bound; report any unfinished work."""
    found = []
    if count <= 0:
        return found, None
    ascending = direction == "after"
    op, order = (">", "ASC") if ascending else ("<", "DESC")
    # Head/tail scans walk toward their exclusive window boundary, not away from it.
    boundary_clause = "" if boundary is None else f" AND id {op} ?"
    base_params = [session_id] if boundary is None else [session_id, boundary]
    if stop is not None:
        boundary_clause += f" AND id {'<' if ascending else '>'} ?"
        base_params.append(stop)
    cursor = None
    scanned = 0
    while scanned < _SCAN_ROW_LIMIT:
        cursor_clause = "" if cursor is None else f" AND id {op} ?"
        params = [*base_params, *([] if cursor is None else [cursor])]
        limit = min(_SCAN_CHUNK_SIZE, _SCAN_ROW_LIMIT - scanned)
        rows = conn.execute(
            f"SELECT id, {candidate_content} FROM messages INDEXED BY idx_messages_session_id "
            f"WHERE session_id = ?{boundary_clause}{cursor_clause} ORDER BY id {order} LIMIT ?",
            (*params, limit),
        ).fetchall()
        for row in rows:
            cursor = row["id"]
            scanned += 1
            raw = row["content"]
            if raw is None:
                continue
            _check_json_size(db, raw, encoded_content=True)
            content = db._decode_content(raw)
            if _has_prose(content) and not _is_handoff(content):
                found.append(cursor)
                if len(found) == count:
                    return found, None
        if len(rows) < limit:
            return found, None
    more = conn.execute(
        "SELECT id FROM messages INDEXED BY idx_messages_session_id "
        f"WHERE session_id = ?{boundary_clause} AND id {op} ? ORDER BY id {order} LIMIT 1",
        (*base_params, cursor),
    ).fetchone()
    continuation = {"direction": direction, "message_id": cursor, "rows_scanned": scanned} if more else None
    return found, continuation


def _hydrate_ids(db, conn, session_id, ids):
    messages = {}
    for start in range(0, len(ids), _SCAN_CHUNK_SIZE):
        chunk = ids[start:start + _SCAN_CHUNK_SIZE]
        rows = conn.execute(
            f"SELECT * FROM messages WHERE session_id = ? AND {_VISIBLE} "
            f"AND id IN ({','.join('?' for _ in chunk)})",
            (session_id, *chunk),
        ).fetchall()
        for row in rows:
            _check_json_size(db, row["content"], encoded_content=True)
            for key in ("tool_calls", "display_metadata"):
                if key in row.keys():
                    _check_json_size(db, row[key])
            messages[row["id"]] = db._row_to_message_dict(
                row, warn_context="get_recall_anchored_view", summary_flag=False)
    return messages


def _build_view(db, conn, session_id, anchor, window, bookend):
    empty = {"window": [], "messages_before": 0, "messages_after": 0,
             "bookend_start": [], "bookend_end": []}
    continuations = {}
    candidate_content = _candidate_content(conn)

    def scan(name, direction, boundary, count, stop=None):
        ids, continuation = _scan(db, conn, session_id, candidate_content=candidate_content,
                                  direction=direction, boundary=boundary, count=count, stop=stop)
        if continuation:
            continuations[name] = continuation
        return ids

    automatic_anchor = anchor is None
    if automatic_anchor:
        anchors = scan("anchor", "after", None, 1)
        if not anchors:
            return _with_context_status(empty, continuations)
        anchor = anchors[0]
    elif not conn.execute(
        f"SELECT 1 FROM messages WHERE session_id = ? AND id = ? AND {_VISIBLE} LIMIT 1",
        (session_id, anchor),
    ).fetchone():
        return empty

    # The automatic scan already proved there are no substantive predecessors.
    # Don't re-spend its budget on before/head scans of those same raw rows.
    before = [] if automatic_anchor else list(reversed(scan("before", "before", anchor, window)))
    after = scan("after", "after", anchor, window)
    window_ids = [*before, anchor, *after]
    # Bookends start at session edges. A second exclusive bound keeps them outside
    # the window; use that bound as a stop, not as the initial keyset cursor.
    start_ids = [] if automatic_anchor else scan("bookend_start", "after", None, bookend, stop=window_ids[0])
    end_ids = list(reversed(scan("bookend_end", "before", None, bookend, stop=window_ids[-1])))
    messages = _hydrate_ids(db, conn, session_id, [*start_ids, *window_ids, *end_ids])
    result = {"window": [messages[i] for i in window_ids],
              "messages_before": len(before), "messages_after": len(after),
              "bookend_start": [messages[i] for i in start_ids],
              "bookend_end": [messages[i] for i in end_ids]}
    return _with_context_status(result, continuations)


def _with_context_status(view, continuations):
    if continuations:
        view.update(context_truncated=True, context_scan_limit=_SCAN_ROW_LIMIT,
                    context_continuation=continuations)
    return view


def get_recall_anchored_view(db, session_id, around_message_id, window=5, bookend=3):
    """Native-shaped recall window counting nonempty user/assistant prose per side.

    None selects the first substantive anchor within a bounded scan in the same
    snapshot as its window; a capped empty selection still returns context status.
    Preserve even an explicit empty/tool/service anchor when it belongs to this session and
    is active or compaction-archived. Rewound anchors/rows are never resurrected.
    ``messages_before/after`` count returned substantive neighbors, not raw rows.
    Extra ``context_*`` fields declare capped scans and raw continuation cursors.
    """
    with db._read_ctx() as conn:
        # One generation for ownership, selection, and hydration, including the
        # lock-held writer fallback. Never roll back a caller's transaction.
        began = not conn.in_transaction
        if began:
            conn.execute("BEGIN")
        try:
            return _build_view(db, conn, session_id, around_message_id, max(window, 0), max(bookend, 0))
        finally:
            if began and conn.in_transaction:
                conn.execute("ROLLBACK")
