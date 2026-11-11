"""Allowlisted, detached conversational evidence for automatic knowledge capture.

This is NOT the session transcript or the checkpoint/context-engine evidence API.
Text is never an origin credential: only host-bound spans and typed DTO fields
can suppress a user message. In particular, quoted runtime markers stay human.
"""

from collections.abc import Mapping
from threading import Lock
from typing import Any

from agent.capture_origin import capture_messages, runtime_capture_is_ambiguous
from agent.conversation_compression_scaffolding import has_scaffolding_flag
from agent.skill_commands import extract_user_instruction_from_skill_message


_HUMAN_KINDS = frozenset({"", "steer", "skill_invocation"})
_HUMAN_SOURCES = frozenset({"", "human", "user", "human_statement"})


class PreviousUserMessage(str):
    """Local scalar plus its canonical row identity; never handed to a provider."""

    row: Mapping

    def __new__(cls, text, row):
        value = super().__new__(cls, text)
        value.row = row
        return value


def content_text(content: Any) -> str:
    """Only visible text leaves this boundary; typed thinking and media are not knowledge."""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "\n".join(part["text"] for part in content
                         if isinstance(part, Mapping) and part.get("type") in {"text", "input_text", "output_text"}
                         and isinstance(part.get("text"), str))
    return ""


def human_input(text: str) -> str:
    """Remove only the exact producer-bound runtime span, preserving neighboring human bytes."""
    if runtime_capture_is_ambiguous(text):
        return ""
    rows = capture_messages(text, "", None)
    if rows is None:
        return text
    return "".join(row["content"] for row in rows if row.get("source_kind") == "human")


def _human_row(message: Mapping) -> bool:
    metadata = message.get("display_metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    sources = [container.get("source_kind") or "" for container in (message, metadata, message.get("metadata"))
               if isinstance(container, Mapping)]
    return ((message.get("display_kind") or "") in _HUMAN_KINDS and all(source in _HUMAN_SOURCES for source in sources)
            and not has_scaffolding_flag(dict(message)) and not message.get("_compressed_summary")
            and not metadata.get("compaction_inflight_task_restatement")
            and message.get("channel") in (None, "", "final"))


def _user_view(message: Mapping) -> dict:
    """Unwrap only a producer-marked native carrier, retaining its source policy."""
    if message.get("_compressed_summary"):
        from agent.context_compressor import user_originated_turn_view

        live = user_originated_turn_view(dict(message))
        if live is not None:
            return {**message, "content": live.get("content"), "_compressed_summary": False, "display_kind": None}
    return dict(message)


def _user_text(message: Mapping) -> str:
    from agent.prompt_builder import STEER_MARKER_CLOSE, STEER_MARKER_OPEN

    message = _user_view(message)
    if not _human_row(message):
        return ""
    metadata = message.get("display_metadata")
    typed = metadata.get("typed_ask") if isinstance(metadata, Mapping) else None
    text = typed if isinstance(typed, str) else content_text(message.get("content"))
    if message.get("display_kind") == "steer":
        start, end = STEER_MARKER_OPEN + "\n", "\n" + STEER_MARKER_CLOSE
        if text.startswith(start) and text.endswith(end):
            text = text[len(start):-len(end)]
    return extract_user_instruction_from_skill_message(text) or ""


def current_user_text(user: str, messages: list | None) -> str:
    """The scalar sync argument must obey the same provenance as its transcript row."""
    rows = messages or []
    for index in range(len(rows) - 1, -1, -1):
        message = rows[index]
        if isinstance(message, Mapping) and message.get("role") == "user" and message.get("display_kind") != "steer":
            if message.get("capture_current_turn") is True:
                start = index
                while start > 0 and isinstance(rows[start - 1], Mapping) and rows[start - 1].get("capture_current_turn") is True:
                    start -= 1
                return "".join(_user_text(row) for row in rows[start:index + 1] if _human_row(row))
            if message.get("_compressed_summary"):
                return _user_text(message)
            if not _human_row(message):
                return ""
            return human_input(user)
    if messages is None:
        return human_input(user)
    return "".join(_user_text(row) for row in rows
                   if isinstance(row, Mapping) and row.get("role") == "user" and _human_row(row))


def _current_user(messages: list | None) -> dict | None:
    return next((message for message in reversed(messages or []) if isinstance(message, dict)
                 and message.get("role") == "user" and message.get("display_kind") != "steer"), None)


class CaptureOrigins:
    """Keep producer provenance alive until deferred extraction, without editing canonical DTOs.

    Durable message uids survive replay copies within this manager; object identity
    handles unpersisted rows. Never match historical content alone. A new process
    can only use provenance its producer persisted (e.g. display_kind).
    """

    def __init__(self):
        self._rows = {}
        self._lock = Lock()

    @staticmethod
    def _key(message):
        uid = message.get("message_uid")
        return ("uid", uid) if isinstance(uid, str) and uid else ("object", id(message))

    @staticmethod
    def _excluded():
        # A turn boundary prevents an omitted machine answer inheriting an earlier human turn.
        return {"role": "user", "content": "", "source_kind": "machine_notification",
                "capture_current_turn": True}

    @classmethod
    def _projection(cls, message, record):
        # Identity selects the record; only exact preimage coherence authorizes its reuse.
        # Native compression changes the carrier bytes but keeps the original live ask.
        live = _user_view(message)
        if live.get("content") == record[1] and _human_row(live):
            return [dict(row) for row in record[2]]
        return [cls._excluded()]

    def previous_text(self, value):
        if not isinstance(value, PreviousUserMessage):
            return value
        with self._lock:
            record = self._rows.get(self._key(value.row))
            if record is not None:
                return "".join(_user_text(row) for row in self._projection(value.row, record) if _human_row(row))
        return str(value)

    def prepare(self, messages, *, user=None, assistant="", original_user=None):
        current = _current_user(messages)
        live_current = _user_view(current) if current is not None else None
        with self._lock:
            prepared = []
            for message in messages or []:
                record = self._rows.get(self._key(message)) if isinstance(message, Mapping) else None
                prepared.extend(self._projection(message, record) if record is not None else [message])
            # Apply known origins before any new split, never overwrite them with carrier bytes.
            if current is not None and self._key(current) in self._rows:
                return prepared
            if live_current is not None and not _human_row(live_current):
                # Splitting a synthetic carrier would discard its producer/source flags.
                return prepared
            if user is None:
                user = content_text(live_current.get("content")) if live_current is not None else ""
            if current is not None and live_current is not None:
                if user == current.get("content"):
                    user = content_text(live_current.get("content"))
                if original_user == current.get("content"):
                    original_user = live_current.get("content")
            # Split only this row's native live preimage, not a synthetic summary or
            # previously projected historical spans. Keep caller scalar/original_user semantics.
            current_rows = [live_current] if live_current is not None else (None if messages is None else [])
            split = capture_messages(user, assistant, current_rows, original_user=original_user)
            if runtime_capture_is_ambiguous(user):
                split = [self._excluded()]
            if current is not None and live_current is not None and split is not current_rows:
                spans = [row for row in split or [] if row.get("capture_current_turn") is True]
                self._rows[self._key(current)] = (current, live_current.get("content"), spans)
                return [row for message in prepared for row in (spans if message is current else [message])]
            return split if messages is None else prepared


def _assistant_text(message: Mapping) -> str:
    if not _human_row(message) or message.get("tool_calls") or message.get("display_kind"):
        return ""
    return content_text(message.get("content"))


def final_answer_text(answer: Any, messages: list | None) -> str:
    """A transcript's channel cannot be bypassed through sync_turn's scalar argument."""
    if messages is not None:
        for message in reversed(messages):
            if isinstance(message, Mapping) and message.get("role") == "assistant":
                return _assistant_text(message)
            if isinstance(message, Mapping) and message.get("role") in {"user", "tool"}:
                return ""
        return ""
    return content_text(answer)


def knowledge_messages(messages: list | None) -> list[dict[str, str]]:
    """Project human turns and their LAST final answer; never reuse any caller containers.

    Tool-loop prose is superseded by the final response. Machine-only turns also
    lose their assistant response, rather than laundering it as an assistant fact.
    Typed steering and split trusted human spans extend (not replace) their turn.
    """
    result: list[dict[str, str]] = []
    pending = None
    human_turn = False
    previous_span = False
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        if role == "user":
            span = message.get("capture_current_turn") is True
            continuation = message.get("display_kind") == "steer" or (span and previous_span)
            if not continuation:
                if pending is not None:
                    result.append(pending)
                pending, human_turn = None, False
            previous_span = span
            if (text := _user_text(message)) and text.strip():
                result.append({"role": "user", "content": text})
                human_turn = True
        elif role == "assistant":
            pending = None
            previous_span = False
            if human_turn and (text := _assistant_text(message)) and text.strip():
                pending = {"role": "assistant", "content": text}
        elif role == "tool":
            pending = None
    if pending is not None:
        result.append(pending)
    return result


def capture_author(author: dict | None) -> dict | None:
    """Identity is not a free-form metadata/reasoning carrier."""
    if author is None:
        return None
    return {key: value for key, value in author.items() if key in {"id", "name", "is_bot"}
            and isinstance(value, (str, bool, int))}
