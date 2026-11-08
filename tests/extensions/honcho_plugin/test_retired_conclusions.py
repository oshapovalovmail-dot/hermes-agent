"""Retirement is ID-based and profile/perspective scoped, never deletion."""
import json
from types import SimpleNamespace as NS

import pytest
import memory_test_plugins.honcho.session as hs


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    calls = []
    rows = [NS(id="old-id", content="Harness standing constraint."),
            NS(id="new-id", content="Harness standing constraint."),
            NS(id="valid-id", content="Harness current task context.")]
    scope = NS(query=lambda query, **kw: calls.append((query, kw)) or rows)
    def context(**kw):
        return NS(peer_representation="Wrong cached representation.", peer_card=["Stable full card."])
    peer = NS(context=context, representation=lambda **kw: "Wrong fallback.",
              get_card=lambda **kw: ["Stable full card."],
              conclusions_of=lambda target: calls.append(("target", target)) or scope)
    client = NS(workspace_id="fixture", peer=lambda name: peer)
    monkeypatch.setattr(hs, "get_honcho_client", lambda *a, **kw: client)
    manager = hs.HonchoSessionManager(config=NS(write_frequency="turn",enabled=True,
        dialectic_reasoning_level="low",dialectic_dynamic=True,dialectic_max_chars=600,
        observation_mode="directional",user_observe_me=True,user_observe_others=True,
        ai_observe_me=True,ai_observe_others=True,message_max_chars=25000,
        dialectic_max_input_chars=10000))
    ledger = {"schema_version":1,"workspace_id":"fixture","retired":[
        {"observer_id":"assistant","observed_id":"owner","id":"old-id"}]}
    path = tmp_path / "honcho-corrections.json"
    path.write_text(json.dumps(ledger))
    return manager, path, rows, scope, calls


def test_retired_id_removed_but_later_same_content_remains(setup):
    manager, _, _, _, calls = setup
    ctx = manager._fetch_peer_context("assistant", search_query="Harness", target="owner")
    assert "Wrong cached" not in ctx["representation"]
    assert ctx["representation"].count("Harness standing constraint.") == 1
    assert "Harness current task context." in ctx["representation"]
    assert ctx["card"] == ["Stable full card."]
    assert ("target", "owner") in calls


def test_no_query_does_not_inject_unidentified_cached_conclusions(setup):
    manager, _, _, _, _ = setup
    ctx = manager._fetch_peer_context("assistant", target="owner")
    assert ctx["representation"] == ""
    assert ctx["card"] == ["Stable full card."]


@pytest.mark.parametrize("change", ["workspace", "observer", "observed"])
def test_retirement_does_not_cross_perspective_or_workspace(setup, change):
    manager, path, _, _, calls = setup
    data = json.loads(path.read_text())
    if change == "workspace": data["workspace_id"] = "other"
    elif change == "observer": data["retired"][0]["observer_id"] = "other"
    else: data["retired"][0]["observed_id"] = "other"
    path.write_text(json.dumps(data))
    ctx = manager._fetch_peer_context("assistant", search_query="Harness", target="owner")
    assert ctx["representation"] == "Wrong cached representation."
    assert calls == []


def test_id_capable_lookup_failure_does_not_restore_superseded_facts(setup):
    manager, _, _, scope, _ = setup
    def fail(*a, **kw): raise RuntimeError("backend unavailable")
    scope.query = fail
    ctx = manager._fetch_peer_context("assistant", search_query="Harness", target="owner")
    assert ctx["representation"] == ""
    assert ctx["card"] == ["Stable full card."]


def test_corrupt_owned_registry_fails_closed_for_automatic_representation(setup):
    manager, path, _, _, _ = setup
    path.write_text("{broken")
    ctx = manager._fetch_peer_context("assistant", search_query="Harness", target="owner")
    assert ctx["representation"] == ""
    assert ctx["card"] == ["Stable full card."]
