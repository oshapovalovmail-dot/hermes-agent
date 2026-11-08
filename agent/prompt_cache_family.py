"""Deterministic prompt-cache family identity for reusable prompt prefixes.

The family key is a routing hint, not a correctness boundary.  It is only
selected when every identity axis is present and JSON-safe; callers retain a
physical-session fallback otherwise.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PromptCacheFamily:
    """A derived family key and the hash-only evidence used to construct it."""

    key: Optional[str]
    serialized: Optional[bytes]
    stable_prefix_hash: Optional[str]
    tool_schema_hash: Optional[str]
    isolation_hash: Optional[str]
    fallback_reason: Optional[str] = None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utf8_bytes(value: Any) -> Optional[bytes]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        return None


def stable_prefix_fingerprint(stable_prompt_prefix: Any) -> Optional[str]:
    """Hash the exact UTF-8 bytes that precede the volatile prompt suffix."""
    encoded = _utf8_bytes(stable_prompt_prefix)
    return _sha256_bytes(encoded) if encoded is not None else None


def _canonical_json_bytes(value: Any) -> Optional[bytes]:
    try:
        serialized = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        return serialized.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        return None


def _canonical_tool_bytes(tools: Any) -> Optional[bytes]:
    """Serialize wire tools in exact sequence order with canonical mappings."""
    if tools is None:
        tools = []
    if not isinstance(tools, (list, tuple)):
        return None
    entries: list[bytes] = []
    for tool in tools:
        if not isinstance(tool, dict):
            return None
        entry = _canonical_json_bytes(tool)
        if entry is None:
            return None
        entries.append(entry)
    return b"[" + b",".join(entries) + b"]"


def tool_schema_fingerprint(tools: Any) -> Optional[str]:
    """Hash canonical wire tools in emitted order; None means invalid JSON."""
    serialized = _canonical_tool_bytes(tools)
    return _sha256_bytes(serialized) if serialized is not None else None


def _fingerprint_scope(isolation_scope: Any) -> Optional[str]:
    encoded = _utf8_bytes(isolation_scope)
    return _sha256_bytes(encoded) if encoded is not None else None


def derive_prompt_cache_family(
    *,
    wire_model: Any,
    api_mode: Any,
    isolation_scope: Any,
    stable_prompt_prefix: Any,
    tools: Any,
) -> PromptCacheFamily:
    """Build a bounded provider key from complete main-path family inputs.

    The helper deliberately returns a missing key instead of coercing malformed
    values through ``str``/``repr``. Callers then retain their existing
    session-scoped derivation.
    """
    stable_hash = stable_prefix_fingerprint(stable_prompt_prefix)
    if stable_hash is None:
        return PromptCacheFamily(None, None, None, None, None, "missing_stable_prefix")

    isolation_hash = _fingerprint_scope(isolation_scope)
    if isolation_hash is None:
        return PromptCacheFamily(None, None, stable_hash, None, None, "missing_isolation_scope")

    tool_hash = tool_schema_fingerprint(tools)
    if tool_hash is None:
        return PromptCacheFamily(None, None, stable_hash, None, isolation_hash, "invalid_tool_schema")

    if not isinstance(wire_model, str) or not wire_model:
        return PromptCacheFamily(None, None, stable_hash, tool_hash, isolation_hash, "missing_wire_model")
    if not isinstance(api_mode, str) or not api_mode:
        return PromptCacheFamily(None, None, stable_hash, tool_hash, isolation_hash, "missing_api_mode")

    serialized = _canonical_json_bytes(
        {
            "api_mode": api_mode,
            "isolation_fingerprint": isolation_hash,
            "stable_prefix_fingerprint": stable_hash,
            "tool_schema_fingerprint": tool_hash,
            "version": 1,
            "wire_model": wire_model,
        }
    )
    if serialized is None:
        return PromptCacheFamily(None, None, stable_hash, tool_hash, isolation_hash, "invalid_family_input")
    return PromptCacheFamily(
        key="pck_" + _sha256_bytes(serialized)[:24],
        serialized=serialized,
        stable_prefix_hash=stable_hash,
        tool_schema_hash=tool_hash,
        isolation_hash=isolation_hash,
    )


def _safe_value_hash(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return _sha256_bytes(str(value).encode("utf-8", errors="replace"))
    except (TypeError, ValueError, UnicodeError):
        return None


def log_prompt_cache_family(
    log: logging.Logger,
    *,
    family: PromptCacheFamily,
    selected_key: Any,
    legacy_key: Any,
    wire_model: Any,
    api_mode: Any,
) -> None:
    """Emit DEBUG-only fingerprints; never include raw prompt or scope values."""
    log.debug(
        "prompt-cache family: new_key_hash=%s selected_key_hash=%s legacy_key_hash=%s "
        "stable_prefix_hash=%s tool_schema_hash=%s isolation_hash=%s model=%s api_mode=%s fallback_reason=%s",
        _safe_value_hash(family.key),
        _safe_value_hash(selected_key),
        _safe_value_hash(legacy_key),
        family.stable_prefix_hash,
        family.tool_schema_hash,
        family.isolation_hash,
        wire_model,
        api_mode,
        family.fallback_reason,
    )
