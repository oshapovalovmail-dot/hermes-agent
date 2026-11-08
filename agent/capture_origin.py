"""Trusted per-turn runtime origin, separate from model/user-visible text.

Only producers bind origin. A textual marker is never an origin credential.
The exact payload bounds the machine span; neighboring human text stays human.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_RUNTIME_PAYLOAD: ContextVar[str] = ContextVar("memory_runtime_payload", default="")


@contextmanager
def runtime_capture_origin(payload: str):
    token = _RUNTIME_PAYLOAD.set(payload if isinstance(payload, str) else "")
    try:
        yield
    finally:
        _RUNTIME_PAYLOAD.reset(token)


def capture_messages(user: str, assistant: str, messages: list[dict[str, Any]] | None,
                     *, original_user: str | None = None):
    """Snapshot trusted spans before background dispatch; never mutate canonical DTOs.

    An absent, changed or multiply repeated payload fails open as human input.
    Keep transcript tool messages and historical turns intact for their owners.
    """
    payload = _RUNTIME_PAYLOAD.get()
    if not payload or user.count(payload) != 1:
        return messages
    start = user.index(payload)
    spans = [("human", user[:start]), ("machine_notification", payload),
             ("human", user[start + len(payload):])]
    rows = [{"role": "user", "content": text, "source_kind": kind,
             "scope": "task" if kind == "machine_notification" else "human_statement",
             "capture_current_turn": True,
             "metadata": {"origin_verified": True}}
            for kind, text in spans if text]
    if messages is not None:
        copied = [dict(message) for message in messages]
        # Only typed /steer rows extend the current turn's user boundary.
        # Textual markers and historical byte matches do not establish origin.
        for index in range(len(copied) - 1, -1, -1):
            if copied[index].get("role") == "user":
                if copied[index].get("display_kind") == "steer":
                    continue
                # Skill scaffolding was removed from provider-facing text, not
                # from the canonical transcript used to locate this turn.
                if copied[index].get("content") == (user if original_user is None else original_user):
                    return copied[:index] + rows + copied[index + 1:]
                break
        # A supplied transcript is authoritative, even if empty or unmatched.
        return messages
    return rows + [{"role": "assistant", "content": assistant}]
