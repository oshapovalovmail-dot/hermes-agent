"""R2: request operators cannot certify automatic history; real injection paths."""
from types import SimpleNamespace as NS

import pytest

from tests.extensions.plugins.memory.test_review_r1_r3 import hc, ovc

rig = hc.rig
isolated = ovc.isolated
http_fixture = ovc.http_fixture

# Recommendation/selection paraphrases, not a subject/brand allowlist.
REQUESTS = [
    "Recommend", "Suggest", "Advise", "Pick", "Shortlist",
    "Give recommendations for", "Offer a recommendation for",
    "Make a suggestion for", "Selection of", "Prioritize", "Prioritise",
    "Порекомендуй", "Рекомендуй", "Посоветуй", "Предложи",
    "Выбрать", "Выбирать", "Подобрать", "Сравнить", "Выбор", "Рекомендации",
]
CASES = [(op + " binoculars for birdwatching. Prioritize weather sealing and comfortable eye relief.",
          op + " Docker Compose for local fallback evaluation services.",
          "Binoculars with comfortable eye relief are useful for birdwatching.")
         for op in REQUESTS]
# Ordinary request framing cannot establish a topic through a pronoun/auxiliary.
FRAMINGS = [
    "Could you recommend", "I would like recommendations for",
    "Would you kindly recommend", "I am looking for recommendations for",
    "We would appreciate recommendations for", "Can you recommend",
    "Please recommend to me", "May I please ask for recommendations for",
    "Рекомендуй пожалуйста для нас", "Мне хотелось бы подобрать",
    "Show me", "Tell me about", "We want recommendations for",
    "I need recommendations for", "Please explain", "Please inspect",
    "Доделывай", "Продолжай", "Continue", "Proceed",
]
CASES += [(framing + " binoculars for birdwatching. Prioritize weather sealing and comfortable eye relief.",
           framing + " Docker Compose for local fallback evaluation services.",
           "Binoculars with comfortable eye relief are useful for birdwatching.")
          for framing in FRAMINGS]
# Single genuine lexical anchors remain sufficient; not a multi-match threshold.
CASES += [
    ("Suggest compressor", "Suggest Docker Compose services.", "Compressor operates quietly."),
    ("Посоветуй ферментация", "Посоветуй Docker Compose services.", "Ферментация требует времени."),
    ("Pick AX29", "Pick Docker Compose services.", "AX29 calibration is pending."),
]


def test_generic_framing_vocabulary_stays_aligned():
    from memory_test_plugins.honcho.recall_contracts import _RECALL_STOPWORDS
    from memory_test_plugins.openviking import OpenVikingMemoryProvider
    for word in _RECALL_STOPWORDS:
        assert OpenVikingMemoryProvider._query_tokens(word) == [], word


@pytest.mark.parametrize("fallback", [False, True], ids=["context", "representation-fallback"])
@pytest.mark.parametrize("query,noise,positive", CASES)
def test_honcho_operator_only_overlap_never_reaches_injection(rig, fallback, query, noise, positive):
    p, mgr, session, _, peers = rig
    text = "[2026-10-10] " + noise + "\n[2026-10-09] " + positive
    calls = []
    def context(**kwargs):
        calls.append(("context", kwargs))
        if fallback:
            raise RuntimeError("fixture offline")
        return NS(representation=text, peer_card=[])
    def representation(**kwargs):
        calls.append(("representation", kwargs))
        return text
    for peer in peers.values():
        object.__setattr__(peer, "context", context)
        object.__setattr__(peer, "representation", representation)
        object.__setattr__(peer, "get_card", lambda **kw: [])
    result = mgr.get_prefetch_context(session.key, query)
    injected = p._truncate_to_budget(p._format_first_turn_context(result))
    assert positive in injected
    assert noise not in injected
    assert positive in result["representation"]
    assert noise not in result["representation"]
    assert noise not in result["ai_representation"]
    assert {name for name, _ in calls} == ({"context", "representation"} if fallback else {"context"})
    assert all(kw["search_query"] == query for _, kw in calls)
    # Explicit dialectic reads are intentionally not this automatic lexical gate.
    for peer in peers.values():
        object.__setattr__(peer, "chat", lambda *a, **kw: text)
    assert noise in mgr.dialectic_query(session.key, query, apply_injection_cap=False)


@pytest.mark.parametrize("query,noise,positive", CASES)
def test_openviking_operator_overlap_filtered_at_candidate_and_body_api_boundaries(http_fixture, isolated, monkeypatch, query, noise, positive):
    state, _ = http_fixture
    candidates = [ovc.leaf("operator-noise", noise),
                  ovc.leaf("topical", positive),
                  ovc.leaf("body-only-noise", positive)]
    state["candidates"] = candidates
    state["bodies"] = {candidates[0]["uri"]: noise,
                       candidates[1]["uri"]: positive + "\n\n" + noise,
                       candidates[2]["uri"]: noise}
    manager, p = ovc.make_manager(isolated)
    reads = []
    get = p._client.get
    def tracked_get(path, *args, **kwargs):
        if path == "/api/v1/content/read":
            reads.append(kwargs["params"]["uri"])
        return get(path, *args, **kwargs)
    monkeypatch.setattr(p._client, "get", tracked_get)
    try:
        block = manager.prefetch_all(query, session_id="saved")
        assert positive in block
        assert noise not in block
        assert "operator-noise.md" not in block
        assert "body-only-noise.md" not in block
        candidate_uris = {item["uri"] for item in candidates}
        assert set(reads) & candidate_uris == {candidates[1]["uri"], candidates[2]["uri"]}
        with ovc.closing(ovc.SessionDB(isolated / "state.db")) as db:
            db.create_session("saved", source="cli")
            api = ovc.compose_user_api_content(query, block, "")
            db.append_message("saved", "user", query, api_content=api)
            saved = db.get_messages("saved")[0]
            assert saved["content"] == query
            assert positive in saved["api_content"]
            assert noise not in saved["api_content"]
        # Explicit search/read still expose full history through the real HTTP client.
        assert noise in manager.handle_tool_call("viking_search", {"query": query})
        assert noise in manager.handle_tool_call("viking_read", {"uri": candidates[0]["uri"], "level": "content"})
        assert not any(path.endswith(("/commit", "/messages", "/messages/batch"))
                       for _, path, _ in state["records"])
    finally:
        manager.shutdown_all()
