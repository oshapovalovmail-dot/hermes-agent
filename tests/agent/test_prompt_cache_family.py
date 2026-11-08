"""Behavioral tests for prompt-cache family derivation and observability."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import logging
from types import SimpleNamespace

import pytest

from agent import prompt_cache_scope
from agent.transports.codex import ResponsesApiTransport


def _family_api():
    """Return the family module once implemented; keep the initial RED run assertion-based."""
    if importlib.util.find_spec("agent.prompt_cache_family") is None:
        return None
    return importlib.import_module("agent.prompt_cache_family")


def _tool(name: str, description: str = "lookup") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _resolve_isolation_scope(agent):
    resolver = getattr(prompt_cache_scope, "resolve_prompt_cache_isolation_scope", None)
    assert resolver is not None, "resolve_prompt_cache_isolation_scope is required"
    return resolver(agent)


def _family(**overrides):
    values = dict(
        wire_model="gpt-5.6",
        api_mode="codex_responses",
        isolation_scope="piso_alice",
        stable_prompt_prefix="stable identity and instructions",
        tools=[_tool("lookup")],
    )
    values.update(overrides)
    api = _family_api()
    assert api is not None, "agent.prompt_cache_family is required"
    return api.derive_prompt_cache_family(**values)


def test_family_key_is_deterministic_and_bounded():
    first = _family()
    second = _family()

    assert first.key == second.key
    assert first.key.startswith("pck_")
    assert len(first.key) <= 64
    assert first.serialized
    assert first.stable_prefix_hash == hashlib.sha256(
        b"stable identity and instructions"
    ).hexdigest()


def test_tool_schema_fingerprint_preserves_wire_order():
    api = _family_api()
    assert api is not None, "agent.prompt_cache_family is required"
    first = api.tool_schema_fingerprint([_tool("lookup", "a"), _tool("lookup", "b")])
    second = api.tool_schema_fingerprint([_tool("lookup", "b"), _tool("lookup", "a")])

    assert first != second


def test_family_changes_for_stable_model_mode_isolation_and_tool_changes():
    baseline = _family().key

    assert _family(stable_prompt_prefix="different stable instructions").key != baseline
    assert _family(wire_model="gpt-5.5").key != baseline
    assert _family(api_mode="chat_completions").key != baseline
    assert _family(isolation_scope="piso_bob").key != baseline
    assert _family(tools=[_tool("search")]).key != baseline


def test_non_json_tool_schema_fails_closed():
    family = _family(tools=[{"type": "function", "callable": object()}])

    assert family.key is None
    assert family.fallback_reason == "invalid_tool_schema"


@pytest.mark.parametrize(
    ("user_id_alt", "user_id", "expected_distinct"),
    [
        ("alice-alt", "alice", False),
        ("bob-alt", "alice", True),
        (None, "alice", True),
    ],
)
def test_isolation_scope_prefers_alt_principal(monkeypatch, tmp_path, user_id_alt, user_id, expected_distinct):
    monkeypatch.setenv("HERMES_TENANT", "tenant-a")
    home = tmp_path / "profile" / "state.db"
    home.parent.mkdir()
    base = SimpleNamespace(
        _session_db=SimpleNamespace(db_path=home),
        platform="telegram",
        _user_id_alt="alice-alt",
        _user_id="alice",
    )
    changed = SimpleNamespace(
        _session_db=SimpleNamespace(db_path=home),
        platform="telegram",
        _user_id_alt=user_id_alt,
        _user_id=user_id,
    )

    first = _resolve_isolation_scope(base)
    second = _resolve_isolation_scope(changed)

    assert first != second if expected_distinct else first == second


def test_isolation_scope_separates_tenant_and_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_TENANT", "tenant-a")
    first = SimpleNamespace(
        _session_db=SimpleNamespace(db_path=tmp_path / "profile-a" / "state.db"),
        platform="telegram",
        _user_id="same-user",
    )
    second = SimpleNamespace(
        _session_db=SimpleNamespace(db_path=tmp_path / "profile-b" / "state.db"),
        platform="telegram",
        _user_id="same-user",
    )

    first_scope = _resolve_isolation_scope(first)
    second_scope = _resolve_isolation_scope(second)
    monkeypatch.setenv("HERMES_TENANT", "tenant-b")
    third_scope = _resolve_isolation_scope(first)

    assert first_scope != second_scope
    assert first_scope != third_scope


def test_family_debug_log_contains_hashes_not_raw_values(caplog):
    caplog.set_level(logging.DEBUG, logger="agent.transports.codex")
    raw_prompt = "RAW_PROMPT_SENTINEL"
    raw_isolation = "RAW_ISOLATION_SENTINEL"
    raw_session = "RAW_SESSION_SENTINEL"

    ResponsesApiTransport().build_kwargs(
        model="gpt-5.6",
        messages=[{"role": "system", "content": raw_prompt}],
        tools=[_tool("lookup")],
        session_id=raw_session,
        stable_prompt_prefix=raw_prompt,
        cache_isolation_scope=raw_isolation,
        api_mode="codex_responses",
    )

    output = caplog.text
    assert raw_prompt not in output
    assert raw_isolation not in output
    assert raw_session not in output
    assert "stable_prefix_hash" in output
    assert "tool_schema_hash" in output
    assert "isolation_hash" in output
    assert "api_mode=codex_responses" in output