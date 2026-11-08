"""Rotation-stable logical cache scope for prompt_cache_key derivation.

Legacy compression rotation mints a new physical ``session_id`` mid-conversation, moving it
into a fresh cache bucket. ``resolve_prompt_cache_scope()`` maps the physical id to the ROOT
of its compression lineage — NOT ``get_conversation_root`` (the Portal-attribution walk),
which would collapse /branch children and delegate trees into one id. ``/new`` starts a
fresh scope; fork children (branch, delegate, tool-tagged) are isolated. Hosts minting one id
per RESPONSE declare the conversation via ``gateway_session_key``, which wins over the lineage
walk and is hashed to ``gwk_<sha256[:24]>`` (it embeds platform/chat/user identifiers).
"""

import hashlib
import json
import os
from pathlib import Path
import logging
from typing import Any, Optional

from utils import base_url_hostname

logger = logging.getLogger(__name__)

_MEMO_ATTR = "_prompt_cache_scope_memo"
_DECLARED_SCOPE_PREFIX = "gwk_"


def _lineage_root(session_id: str, session_db: Any) -> Optional[str]:
    """Compression-lineage root of *session_id*, or None (tolerates test-double results)."""
    if session_db is None:
        return None
    try:
        lineage = session_db.get_compression_lineage(session_id)
    except Exception:
        logger.debug("prompt-cache scope lineage walk failed", exc_info=True)
        return None
    if isinstance(lineage, (list, tuple)) and lineage:
        root = lineage[0]
        if isinstance(root, str) and root:
            return root
    return None


def conversation_id(agent: Any) -> str:
    """The id plugins key per-conversation state on: the compression-lineage root of ``agent.session_id``
    (the cache scope's walk, plus ``--source tool`` rotations), so compression rotation keeps it while
    ``/new`` and ``/branch`` start a new one. A delegated child or review fork reports its parent's, stamped
    at spawn. Memoized per physical id."""
    inherited = getattr(agent, "_inherited_conversation_id", None)
    if isinstance(inherited, str) and inherited:
        return inherited
    sid = str(getattr(agent, "session_id", None) or "")
    memo = getattr(agent, "_conversation_id_memo", None)
    if isinstance(memo, tuple) and len(memo) == 2 and memo[0] == sid:
        return memo[1]
    # A plugin hook can ask first from a tool callback Relay drives on its loop, where WorkerRPC
    # refuses a synchronous read for the rest of the turn (#139029): both walks run off the loop.
    from agent.runtime_session_store import call_off_event_loop
    db = getattr(agent, "_session_db", None)
    root = call_off_event_loop(_lineage_root, sid, db) if sid else None
    if root == sid:
        try:
            root = call_off_event_loop(db.get_tool_rotation_root, sid)
        except Exception:
            # Not memoized: the physical id is right for now, and a later call retries the walk.
            logger.debug("tool-source rotation walk failed", exc_info=True)
            return sid
    if root is not None:
        agent._conversation_id_memo = (sid, root)
    return root or sid


def _agent_source(
    agent: Any, session_id: str, session_db: Any, row_source: Optional[str] = None
) -> str:
    """The ``sessions.source`` this agent's conversation is recorded under.

    ``row_source``: the row's value if already read (``""`` = read, none; ``None`` = look it
    up). Before the row lands, use the SAME resolver persistence uses, not ``agent.platform``:
    they diverge under ``HERMES_SESSION_SOURCE`` and the declared scope is memoized at once,
    so both sides of a ``/new`` would otherwise hash the same scope.
    """
    if row_source is None and session_id and session_db is not None:
        try:
            row = session_db.get_session(session_id)
        except Exception:
            logger.debug("declared-scope source lookup failed", exc_info=True)
            row = None
        row_source = str(row.get("source") or "").strip() if row else ""
    if row_source:
        return row_source
    platform = getattr(agent, "platform", None)
    from agent.session_source import session_source_for
    return str(session_source_for(platform)).strip()


def _conversation_generation(session_key: str, source: str, session_db: Any) -> str:
    """Durable generation for *session_key*'s current conversation (``""`` if none).

    The declared key survives ``/new``, so hashing it alone would reuse one scope across
    conversations. The counter advances with each reset boundary, independent of prunable
    rows and wall-clock; compression does not advance it.

    The declared key names a chat and deliberately survives `/new` and policy resets. See #79017, #86733.
    """
    reader = getattr(session_db, "latest_conversation_boundary", None)
    if not callable(reader):
        return ""
    generation = reader(session_key, source)
    return "" if generation is None else str(int(generation))


def declared_conversation_scope(agent: Any) -> Optional[str]:
    """Host-declared logical conversation scope (``gwk_<sha256[:24]>``), or None.

    Hashes ``(source, gateway_session_key, generation)``. None (fall back to the physical id)
    when no key is declared, for a background-review fork (``_persist_disabled``), for an
    explicit fork child, and on any DB error (fail closed rather than merge a fork onto its
    parent's key).

    The one sanctioned exception is a same-model cache-parity fork (#109964): its whole purpose
    is prefix parity with the parent, yet ``_persist_disabled`` + ``_session_db=None`` made both
    resolvers key it into a different bucket (one cold ~full-context request per review).
    ``build_cache_parity_fork`` stamps the parent's ALREADY-RESOLVED scope as
    ``_inherited_cache_scope`` (no DB access from the fork). Only a ``gwk_`` value is a declared
    scope; a physical lineage root stays out of the affinity header so the fork publishes
    exactly what its parent publishes (None → consumers fall back to the conversation root).
    """
    inherited = getattr(agent, "_inherited_cache_scope", None)
    if isinstance(inherited, str) and inherited.startswith(_DECLARED_SCOPE_PREFIX):
        return inherited
    key = str(getattr(agent, "_gateway_session_key", "") or "").strip()
    if not key or getattr(agent, "_persist_disabled", False):
        return None
    sid = str(getattr(agent, "session_id", None) or "")
    db = getattr(agent, "_session_db", None)
    generation = ""
    row_source: Optional[str] = None
    if sid and db is not None:
        try:
            # One read for both halves of the row identity (fork verdict + source).
            # One read for both halves of the row's identity: the fork verdict and the source the peer
            # queries match on live on the same ``sessions`` row, and asking for them separately read it
            # twice per resolution (@teknium1 on #98811). A SessionDB without the combined view keeps the
            # original call, so nothing that predates it — including the doubles that certify the
            # fail-closed contract below — changes behaviour.
            identity = getattr(db, "declared_scope_identity", None)
            if callable(identity):
                is_fork, row_source = identity(sid)
            else:
                is_fork = db.is_explicit_fork_child(sid)
            if is_fork:
                return None
        except Exception:
            logger.debug("declared-scope fork check failed", exc_info=True)
            return None
    source = _agent_source(agent, sid, db, row_source)
    if db is not None:
        try:
            generation = _conversation_generation(key, source, db)
        except Exception:
            logger.debug("declared-scope generation read failed", exc_info=True)
            return None
    # Same identity tuple the peer queries use: same key under different sources must not collapse.
    carrier = f"{source}|{key}|{generation}"
    digest = hashlib.sha256(carrier.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"{_DECLARED_SCOPE_PREFIX}{digest}"


def resolve_prompt_cache_scope(agent: Any) -> str:
    """Rotation-stable cache-scope id: the inherited parent scope of a same-model cache-parity
    fork, else the declared scope, else the compression-lineage root of ``agent.session_id``
    (the physical id without ancestry/DB). Memoized on the agent."""
    inherited = getattr(agent, "_inherited_cache_scope", None)
    if isinstance(inherited, str) and inherited:
        return _apply_fork_tag(agent, inherited)
    sid = str(getattr(agent, "session_id", None) or "")
    if not sid:
        return ""
    db = getattr(agent, "_session_db", None)
    # DB presence is part of the key: an agent that gains a DB handle later must re-resolve.
    key = (sid, db is not None)
    memo = getattr(agent, _MEMO_ATTR, None)
    if isinstance(memo, tuple) and len(memo) == 2 and memo[0] == key:
        return _apply_fork_tag(agent, memo[1])
    root = declared_conversation_scope(agent) or _lineage_root(sid, db)
    scope = root or sid
    # Memoize on success, with no DB, or when the agent never persists a row. A failed/empty
    # walk on a persisting agent is NOT memoized: the physical id is right for now (row not
    # yet persisted) but would stay wrong for the whole segment once it lands.
    if root is not None or db is None or getattr(agent, "_persist_disabled", False):
        try:
            setattr(agent, _MEMO_ATTR, (key, scope))
        except Exception:
            pass  # frozen/slotted doubles: resolution works, just unmemoized
    return _apply_fork_tag(agent, scope)


# ``<scope>::<tag>`` — double colon so gateway session keys that already contain single
# colons are never mistaken for a fork scope.
FORK_SCOPE_SEPARATOR = "::"

# Aggregator slugs that front xAI Grok (OpenRouter and friends).
GROK_AGGREGATOR_MODEL_PREFIXES = ("x-ai/grok-", "xai/grok-")


def is_slot_keyed_cache_route(provider: Any, model: Any, base_url: Any = "") -> bool:
    """True when the cache key selects ONE server-side slot per conversation.

    xAI (``xai``/``xai-oauth``, ``api.x.ai``, or Grok via OpenRouter ``x-ai/grok-*``) pins its
    prompt cache to the server picked by ``x-grok-conv-id`` / ``prompt_cache_key``: two divergent
    request streams under one key evict each other. Anthropic, DeepSeek and Gemini caches are
    content-addressed and OpenAI's ``prompt_cache_key`` only routes over a prefix match, so the
    shared scope (#109964) stays a win there. Only the OpenRouter profile reads ``cache_scope_id``
    for the sticky header; other aggregators fronting Grok change only the body key.
    """
    if str(provider or "").strip().lower() in {"xai", "xai-oauth"}:
        return True
    if base_url_hostname(str(base_url or "")) == "api.x.ai":
        return True
    return str(model or "").strip().lower().startswith(GROK_AGGREGATOR_MODEL_PREFIXES)


def is_fork_cache_scope(scope: Any) -> bool:
    """True when *scope* is a fork-derived scope (``<scope>::<tag>``)."""
    return isinstance(scope, str) and FORK_SCOPE_SEPARATOR in scope


def _apply_fork_tag(agent: Any, scope: str) -> str:
    """``<scope>::<tag>`` for a tagged fork on a slot-keyed route, once the fork's OWN compaction
    committed: before it the fork extends the parent's prefix (warm read, #109964); after it the
    rewritten stream would evict the parent's xAI slot. Read per call, so fallbacks re-evaluate."""
    tag = getattr(agent, "_prompt_cache_fork_tag", None)
    if not scope or not isinstance(tag, str) or not tag:
        return scope
    if getattr(getattr(agent, "context_compressor", None), "compression_count", 0) < 1:
        return scope
    if not is_slot_keyed_cache_route(
        getattr(agent, "provider", ""), getattr(agent, "model", ""), getattr(agent, "base_url", ""),
    ):
        return scope
    return f"{scope}{FORK_SCOPE_SEPARATOR}{tag}"


def declared_conversation_scope_safe(agent: Any) -> Optional[str]:
    """Never-raising variant of :func:`declared_conversation_scope`."""
    try:
        return declared_conversation_scope(agent)
    except Exception:
        logger.debug("declared conversation scope resolution failed", exc_info=True)
        return None


def resolve_prompt_cache_scope_safe(agent: Any) -> Optional[str]:
    """Never-raising variant of :func:`resolve_prompt_cache_scope` (None = use the physical id).
    At turn_context an exception inside ``set_runtime_main(...)`` would skip the whole binding.

    Returns None on any failure (or when there is no scope). Consumers treat None/empty as "fall back to the
    physical session_id", so a resolution failure degrades to pre-#79017 behavior instead of blocking the
    caller — important at turn_context's call site, where an exception raised inside the
    ``set_runtime_main(...)`` argument list would otherwise skip the whole runtime binding, not just the
    cache scope.
    """
    try:
        return resolve_prompt_cache_scope(agent) or None
    except Exception:
        logger.debug("prompt-cache scope resolution failed", exc_info=True)
        return None


_LOCAL_NO_USER_PLATFORMS = frozenset({"cli", "tui", "desktop", "acp", "cron"})


def _profile_identity(agent: Any) -> Optional[tuple[str, str]]:
    """Return resolved active profile home/name, or ``None`` on failure."""
    try:
        from agent.system_prompt import _agent_home, _profile_name_for_home
        from hermes_constants import get_hermes_home

        home = _agent_home(agent)
        if home is None:
            home = get_hermes_home()
        resolved_home = Path(home).expanduser().resolve()
        if not str(resolved_home):
            return None
        profile_name = _profile_name_for_home(resolved_home)
        if not isinstance(profile_name, str) or not profile_name.strip():
            return None
        return str(resolved_home), profile_name.strip()
    except Exception as exc:  # health: allow BLE001 -- identity failures must not log private profile paths
        logger.debug(
            "prompt-cache profile identity resolution failed (%s)",
            type(exc).__name__,
        )
        return None


def _principal_identity(agent: Any) -> Optional[Any]:
    """Return a platform-scoped principal or an approved local owner."""
    try:
        platform_value = getattr(agent, "platform", None)
        platform = platform_value.strip().lower() if isinstance(platform_value, str) else ""

        concrete_user_id: Optional[str] = None
        for attribute in ("_user_id_alt", "_user_id"):
            value = getattr(agent, attribute, None)
            if isinstance(value, bool):
                continue
            if isinstance(value, (str, int)) and str(value).strip():
                concrete_user_id = str(value).strip()
                break

        if concrete_user_id is None:
            # Only explicitly reviewed local first-party surfaces may reuse a
            # profile-wide family without a concrete gateway principal.
            return "profile-owner" if platform in _LOCAL_NO_USER_PLATFORMS else None

        if not platform:
            # Never collapse the same raw user id across an unknown platform.
            return None
        return {"platform": platform, "user_id": concrete_user_id}
    except (AttributeError, TypeError, ValueError):
        return None


def _tenant_identity(agent: Any) -> Optional[str]:
    """Resolve the tenant authority without falling back to a user value."""
    for attribute in ("_tenant_id", "tenant_id", "tenant"):
        value = getattr(agent, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = os.getenv("HERMES_TENANT")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "local"


def resolve_prompt_cache_isolation_scope(agent: Any) -> Optional[str]:
    """Return ``piso_<sha256[:24]>`` for the family isolation tuple.

    The returned digest is the only value transported to the family builder;
    raw home, tenant, platform, and principal values never enter request fields
    or logs. ``session_id`` and volatile prompt content are intentionally
    excluded so a fresh physical session can reuse a proven family.
    """
    if getattr(agent, "_prompt_cache_scope_invalid", False):
        return None
    tenant = _tenant_identity(agent)
    profile = _profile_identity(agent)
    principal = _principal_identity(agent)
    if tenant is None:
        return None
    if profile is None:
        return None
    if principal is None:
        return None

    identity = {
        "profile_home": profile[0],
        "profile_name": profile[1],
        "principal": principal,
        "tenant": tenant,
        "version": 1,
    }
    try:
        serialized = json.dumps(
            identity,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        return None
    digest = hashlib.sha256(serialized).hexdigest()[:24]
    return f"piso_{digest}"


def resolve_prompt_cache_isolation_scope_safe(agent: Any) -> Optional[str]:
    """Never-raising wrapper for request-builder call sites."""
    try:
        return resolve_prompt_cache_isolation_scope(agent)
    except Exception as exc:  # health: allow BLE001 -- fail-closed identity boundary cannot log principal-bearing exceptions
        logger.debug(
            "prompt-cache isolation scope resolution failed (%s)",
            type(exc).__name__,
        )
        return None
