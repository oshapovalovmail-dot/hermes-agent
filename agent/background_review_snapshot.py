"""Detached request state captured before dispatching a background review.

Control/cancellation stays on the live parent. Only request assembly and accounting
consume this snapshot; service objects (credentials, memory store, DB) stay shared.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from types import MappingProxyType, SimpleNamespace
from collections.abc import Mapping
from typing import Any

_REQUEST_FIELDS = (
    "model", "provider", "platform", "session_id", "session_start", "tools", "valid_tool_names",
    "reasoning_config", "ephemeral_system_prompt", "prefill_messages", "enabled_toolsets",
    "disabled_toolsets", "_cached_system_prompt", "_cached_system_prompt_static",
    "_cached_system_prompt_static_tiered", "_cached_system_prompt_static_version",
    "_static_rebuild_failed_for", "_user_id", "_user_id_alt", "_gateway_session_key",
    "_tenant_id", "_background_profile_home", "_memory_enabled", "_user_profile_enabled",
    "providers_allowed", "providers_ignored", "providers_order", "provider_sort",
    "provider_require_parameters", "provider_data_collection",
)


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(v) for v in value)
    return copy.deepcopy(value)


def _thaw(value):
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    if isinstance(value, frozenset):
        return {_thaw(v) for v in value}
    return copy.deepcopy(value)


@dataclass(frozen=True)
class BackgroundReviewSnapshot:
    fields: Mapping[str, Any]
    runtime: Mapping[str, Any]
    messages: tuple
    task_config: Mapping[str, Any]
    cache_scope: str | None
    conversation_root: str
    memory_store: Any
    session_db: Any
    credential_pool: Any

    def materialize(self):
        parent = SimpleNamespace(**_thaw(self.fields))
        runtime = _thaw(self.runtime)
        runtime["credential_pool"] = self.credential_pool
        parent._current_main_runtime = lambda: runtime
        parent._background_review_runtime = runtime
        parent._background_review_cache_scope = self.cache_scope
        parent._conversation_root_id = lambda: self.conversation_root
        parent._inherited_conversation_id = self.conversation_root
        parent._memory_store = self.memory_store
        parent._session_db = self.session_db
        return parent


def capture_background_review_snapshot(agent, messages, task_cfg):
    from agent.background_review import _resolve_review_runtime
    from agent.prompt_cache_scope import conversation_id, resolve_prompt_cache_scope_safe

    runtime = dict(_resolve_review_runtime(agent, task_cfg))
    credential_pool = runtime.pop("credential_pool", None)
    fields = {name: getattr(agent, name) for name in _REQUEST_FIELDS if hasattr(agent, name)}
    return BackgroundReviewSnapshot(
        fields=_freeze(fields), runtime=_freeze(runtime), messages=_freeze(messages),
        task_config=_freeze(task_cfg), cache_scope=resolve_prompt_cache_scope_safe(agent),
        conversation_root=conversation_id(agent), memory_store=getattr(agent, "_memory_store", None),
        session_db=getattr(agent, "_session_db", None), credential_pool=credential_pool,
    )
