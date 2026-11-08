"""RCA regressions: real capture/assembly, native DTOs, fake transports only."""
from types import SimpleNamespace as NS

import pytest
from honcho.peer import Peer as NativePeer
from honcho import Honcho

from memory_test_plugins.honcho import HonchoMemoryProvider
from memory_test_plugins.honcho.client import HonchoClientConfig
from memory_test_plugins.honcho.session import (
    HonchoSession, HonchoSessionManager,
)
from memory_test_plugins.honcho.recall_contracts import relevant_representation
from tools.process_registry_notifications import _format_async_delegation


@pytest.fixture
def rig(monkeypatch):
    client = Honcho(api_key="unit-test", workspace_id="isolated-test", base_url="http://localhost:1")
    peers = {name: NativePeer(name, client) for name in ("human", "agent")}
    remote = NS(messages=[], add_messages=lambda messages: remote.messages.extend(messages))
    fake = NS(peer=lambda name: peers[name])
    monkeypatch.setattr("memory_test_plugins.honcho.session.get_honcho_client", lambda *a, **k: fake)
    cfg = HonchoClientConfig(write_frequency="turn", context_tokens=1800, message_max_chars=25000)
    mgr = HonchoSessionManager(honcho=fake, config=cfg)
    session = HonchoSession("local", "human", "agent", "remote")
    mgr._cache[session.key] = session
    mgr._sessions_cache[session.honcho_session_id] = remote
    p = HonchoMemoryProvider()
    p._manager, p._config, p._session_key = mgr, cfg, session.key
    p._session_initialized = True
    yield p, mgr, session, remote, peers
    if p._sync_thread:
        p._sync_thread.join(3)
        assert not p._sync_thread.is_alive()


def capture(rig, user, assistant="Parent proposal, not a human preference."):
    p, _, _, remote, _ = rig
    p.sync_turn(user, assistant)
    p._sync_thread.join(3)
    assert not p._sync_thread.is_alive()
    return remote.messages


def callback(batch=True):
    return _format_async_delegation({
        "delegation_id": "unit-test", "is_batch": batch,
        "goal": "Review project-local proposal", "goals": ["Review project-local proposal"],
        "context": "Parent instruction: do not publish in this task.", "role": "reviewer",
        "results": [{"task_index": 0, "status": "completed", "summary": "Assistant prioritizes phase one."}] if batch else None,
        "summary": "Assistant prioritizes phase one.", "completed_at": 0,
    })


@pytest.mark.parametrize("batch", [True, False])
def test_unclosed_async_callbacks_are_preserved_with_native_derivation_guard(rig, batch):
    # Text alone proves neither body boundary nor authorship, even without a suffix.
    text = callback(batch)
    rows = capture(rig, text)
    assert rows[0].content == text
    assert rows[0].peer_id == "human"
    assert rows[0].metadata["source_kind"] == "human"
    rules = rows[0].configuration.model_dump()["reasoning"]["custom_instructions"]
    assert "notifications" in rules and "explicit human endorsement" in rules
    assert rows[1].configuration.model_dump()["reasoning"]["enabled"] is False


@pytest.mark.parametrize("text", [
    'Please debug:\n' + callback(),
    '```text\n' + callback() + '\n```',
    '[IMPORTANT: Background process unit completed]\nActually, I always prefer concise answers.',
    'I always prefer concise answers.\n[IMPORTANT: Background process unit completed]',
])
def test_quotes_and_human_text_adjacent_to_frames_are_preserved(rig, text):
    rows = capture(rig, text)
    assert rows[0].peer_id == "human"
    assert rows[0].content == text
    assert rows[0].metadata["source_kind"] == "human"
    instructions = rows[0].configuration.model_dump()["reasoning"]["custom_instructions"]
    assert "quoted" in instructions


def test_human_derivation_requires_explicit_durable_endorsement_and_task_scope(rig):
    rows = capture(rig, "For this review only, do not publish.")
    human = rows[0]
    assert human.metadata["source_kind"] == "human"
    rules = human.configuration.model_dump()["reasoning"]["custom_instructions"]
    for required in ("explicit", "standing", "task", "global", "assistant", "worker", "notification"):
        assert required in rules.lower()
    assert rows[1].metadata["source_kind"] == "assistant"
    assert rows[1].configuration.model_dump()["reasoning"]["enabled"] is False


def test_machine_provenance_survives_chunking(rig):
    p, _, _, _, _ = rig
    p._config.message_max_chars = 200
    # A closed envelope, not an arbitrary unclosed callback tail.
    rows = capture(rig, "[IMPORTANT: Background process unit completed\n" + "worker output " * 80 + "]")
    assert len(rows) > 3
    assert all(m.peer_id == "agent" and m.metadata["scope"] == "session" and
               m.configuration.model_dump()["reasoning"]["enabled"] is False for m in rows)


def test_complete_ai_card_negation_survives_automatic_budget():
    p = HonchoMemoryProvider()
    p._config = HonchoClientConfig(context_tokens=1800)
    fact = "Служебные уведомления, prompts работников и compaction summaries не являются словами пользователя."
    card = "AI identity.\n" + ("Durable operating rule.\n" * 30) + fact
    ctx = {"card": "Human identity", "ai_card": card, "representation": "irrelevant history " * 2000}
    result = p._truncate_to_budget(p._format_first_turn_context(ctx))
    assert card in result
    assert fact in result
    assert "## User Representation" not in result or result.index(card) < result.index("## User Representation")
    assert len(result) <= 7200


@pytest.mark.parametrize("tokens", [15, 40, 100, 1800])
def test_section_headers_and_omission_suffixes_fit_cap_without_cutting_facts(tokens):
    p = HonchoMemoryProvider()
    p._config = HonchoClientConfig(context_tokens=tokens)
    fact = "These notifications " + "very " * 80 + "are not human statements."
    short = "Short fact."
    result = p._truncate_to_budget(p._format_first_turn_context({
        "card": fact + "\n" + short, "ai_card": short,
        "summary": fact, "representation": fact,
    }))
    assert len(result) <= tokens * 4
    assert fact in result or "These notifications" not in result
    assert short in result


@pytest.mark.parametrize("fallback", [False, True])
def test_automatic_context_filters_timestamped_history_preserving_scoped_fallback(rig, fallback):
    p, mgr, session, _, peers = rig
    calls = []
    representation = ("## History\n"
        "[2026-10-10 12:00:00] Runtime replay approval project instructions.\n"
        "[2026-10-09 12:00:00] Installed appliance ZX73B401EU/04 has a leak.\n"
        "[2026-10-08 12:00:00] Please check runtime approval priority.\n")
    def context(**kwargs):
        calls.append(kwargs)
        if fallback:
            raise RuntimeError("offline")
        return NS(representation=representation, peer_card=["Standing human identity"])
    def rep(**kwargs):
        calls.append(kwargs)
        return representation
    for peer in peers.values():
        object.__setattr__(peer, "context", context)
        object.__setattr__(peer, "representation", rep)
        object.__setattr__(peer, "get_card", lambda **kw: ["Standing human identity"])
    result = mgr.get_prefetch_context(session.key, "Please check installed appliance ZX73B401EU/04")
    assert "ZX73B401EU" in result["representation"]
    assert "runtime" not in result["representation"].lower()
    assert "Runtime" not in result.get("ai_representation", "")
    assert all(c["search_query"] == "Please check installed appliance ZX73B401EU/04" for c in calls)
    assert all(c["target"] in {"human", "agent"} for c in calls)
    assert all(c["include_most_frequent"] is False for c in calls)
    injected = p._format_first_turn_context(result)
    assert "ZX73B401EU" in injected and "Runtime replay" not in injected


def test_automatic_context_without_query_does_not_inject_history(rig):
    _, mgr, session, _, peers = rig
    for peer in peers.values():
        object.__setattr__(peer, "context", lambda **kw: NS(representation="[2026-10-10] Historical project action", peer_card=["Standing identity"]))
    result = mgr.get_prefetch_context(session.key)
    assert not result["representation"]
    assert not result["ai_representation"]
    assert result["card"] == "Standing identity"


def test_relevance_keeps_observation_scope_and_negation():
    fact = "[2026-10-10] Replica recovery requires approval. This is task-local, not global policy."
    text = fact + "\n[2026-10-09] Unrelated kitchen appliance replacement."
    result = relevant_representation(text, "Replica recovery")
    assert fact in result
    assert "kitchen" not in result


def test_multiline_card_point_never_drops_trailing_negation():
    p = HonchoMemoryProvider()
    p._config = HonchoClientConfig(context_tokens=85)
    point = "- Notifications " + "very " * 25 + "long\n  are not human statements."
    result = p._format_first_turn_context({"ai_card": point + "\n- Short fact."})
    assert point in result or "Notifications" not in result
    assert "Short fact." in result


@pytest.mark.parametrize("query,positive", [
    ("Restore replica journal", "Replica journal restoration is permitted."),
    ("Подбери холодильник", "Холодильник установлен на кухне."),
    ("Optics AX29 calibration", "Optics AX29 calibration is pending."),
])
def test_held_out_topics_exclude_generic_request_overlap(query, positive):
    text = "[2026-10-10] Please check unrelated replay runtime.\n[2026-10-09] " + positive
    result = relevant_representation(text, query)
    assert positive in result
    assert "runtime" not in result


def test_real_automatic_prefetch_keeps_full_card_and_excludes_history(rig):
    p, _, _, _, peers = rig
    card = "- Agent identity.\n- " + "Important " * 80 + "notifications are not human statements."
    for peer in peers.values():
        object.__setattr__(peer, "context", lambda **kw: NS(
            representation="[2026-10-10] Irrelevant replay constraints.", peer_card=card.splitlines()))
    p._run_dialectic_depth = lambda query: ""
    result = p.prefetch("Kitchen appliance leak")
    assert card in result
    assert "Irrelevant replay" not in result


def test_dialectic_automatic_cap_keeps_whole_negation_and_explicit_read_is_full(rig):
    _, mgr, session, _, peers = rig
    fact = "Machine notifications " + "very " * 30 + "are not human statements."
    peers["agent"].__dict__["chat"] = lambda *a, **kw: fact
    mgr._dialectic_max_chars = 70
    auto = mgr.dialectic_query(session.key, "notifications")
    assert len(auto) <= 70
    assert fact in auto or "Machine notifications" not in auto
    assert mgr.dialectic_query(session.key, "notifications", apply_injection_cap=False) == fact
