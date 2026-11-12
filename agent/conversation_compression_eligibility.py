"""Read-only native structural eligibility, shared with the compressor's first guard."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class SummaryPhase:
    """Summary/preparation outcome; abort_prompt set means hand messages back unchanged."""

    messages: list
    compressed: Any = None
    messages_before_compression: list | None = None
    approx_tokens: int | None = None
    pre_msg_count: int = 0
    abort_prompt: str | None = None


def compression_message_floor(compressor: Any, messages: list) -> int:
    """At or below this size native compression cannot keep its head and minimum tail."""
    return compressor._protect_head_size(messages) + 3 + 1


def native_structural_no_op(compressor: Any, messages: list, *, force: bool, focus_topic: str | None) -> bool:
    """Only the unmodified native automatic path can elide the checkpoint and deep snapshot.

    The native compress() still runs under the ordinary lease/dispatch ownership and records its
    own structural backoff and telemetry. Plugins, overrides and explicit requests keep their
    existing checkpoint contract, even when native protection would make that packet too short.
    """
    from agent.context_compressor import ContextCompressor

    return (
        not force and not focus_topic
        and type(compressor) is ContextCompressor
        and getattr(compressor.compress, "__func__", None) is ContextCompressor.compress
        and len(messages) <= compression_message_floor(compressor, messages)
    )
