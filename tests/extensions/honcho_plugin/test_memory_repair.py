"""Regression contracts; real provider/manager with in-memory transport, no writes to live Honcho."""
from types import SimpleNamespace as NS
import threading
from memory_test_plugins.honcho import HonchoMemoryProvider
from memory_test_plugins.honcho.client import HonchoClientConfig
from memory_test_plugins.honcho.session import HonchoSession, HonchoSessionManager

class Peer:
    def __init__(self, name):
        self.id = name
        self.metadata = {"unrelated": "keep"}
        self.context_calls = []
        self.fail_context = False
    def context(self, **kw):
        self.context_calls.append(kw)
        if self.fail_context:
            raise RuntimeError("offline")
        return NS(representation="[2026-07-01 12:00:00] Old event\n[2026-10-05 12:00:00] New event", peer_card=[])
    def representation(self, **kw):
        self.context_calls.append(kw)
        return "[2026-07-01 12:00:00] Old event\n[2026-10-05 12:00:00] New event"
    def get_card(self, **kw):
        return ["Compact standing preference"] if not kw else []
    def message(self, content, **kw):
        return NS(content=content, peer_id=self.id, **kw)
    def get_metadata(self):
        return dict(self.metadata)
    def set_metadata(self, metadata):
        self.metadata = dict(metadata)

class Remote:
    def __init__(self):
        self.uploads, self.messages = [], []
        self.fail_upload = False
    def upload_file(self, **kw):
        if self.fail_upload:
            raise RuntimeError("upload failed")
        self.uploads.append(kw)
    def add_messages(self, messages):
        self.messages.extend(messages)

class Client:
    def __init__(self):
        self.peers = {n: Peer(n) for n in ("user-a", "ai-a")}
        self.remote = Remote()
        self.search_calls, self.results = [], []
    def peer(self, name):
        return self.peers[name]
    def search(self, query, **kw):
        self.search_calls.append((query, kw))
        return self.results(query) if callable(self.results) else self.results

def setup_manager(monkeypatch, client=None):
    c = client or Client()
    monkeypatch.setattr("memory_test_plugins.honcho.session.get_honcho_client", lambda *a, **kw: c)
    cfg = HonchoClientConfig(enabled=True, peer_name="user-a", base_url="http://localhost:1", context_tokens=1800, write_frequency="turn")
    mgr = HonchoSessionManager(honcho=c, config=cfg, context_tokens=1800)
    s = HonchoSession("local", "user-a", "ai-a", "remote")
    mgr._cache[s.key], mgr._sessions_cache[s.honcho_session_id] = s, c.remote
    return mgr, s, c, cfg

def provider(mgr, s, cfg):
    p = HonchoMemoryProvider()
    p._manager, p._session_key, p._config = mgr, s.key, cfg
    p._session_initialized = True
    return p

def wait_sync(p):
    if p._sync_thread:
        p._sync_thread.join(3)
        assert not p._sync_thread.is_alive()

def message(content, identity="m1", author="user-a"):
    return NS(content=content, id=identity, peer_id=author, session_id="past", created_at=None, metadata={})

def test_card_survives_large_history_and_summary():
    p = HonchoMemoryProvider()
    p._config = HonchoClientConfig(context_tokens=1800)
    text = p._truncate_to_budget(p._format_first_turn_context({"summary": "session history " * 2000, "representation": "[2026-07-01] old observations " * 2000, "card": "Compact standing preference", "ai_card": "AI identity"}))
    assert text.startswith("## User Peer Card")
    assert "Compact standing preference" in text
    assert "AI identity" in text
    assert len(text) <= 7200

def test_query_context_excludes_frequency_feed_and_bounds_candidates(monkeypatch):
    mgr, s, c, _ = setup_manager(monkeypatch)
    mgr._fetch_peer_context(s.assistant_peer_id, search_query="routing priority", target=s.user_peer_id)
    kw = c.peers["ai-a"].context_calls[0]
    assert kw["include_most_frequent"] is False
    assert 1 <= kw["search_top_k"] < kw["max_conclusions"] <= 20

def test_fallback_representation_keeps_query_and_bounds(monkeypatch):
    mgr, s, c, _ = setup_manager(monkeypatch)
    c.peers["ai-a"].fail_context = True
    mgr._fetch_peer_context(s.assistant_peer_id, search_query="routing", target=s.user_peer_id)
    kw = c.peers["ai-a"].context_calls[-1]
    assert kw.get("search_query") == "routing"
    assert kw.get("include_most_frequent") is False
    assert kw.get("max_conclusions", 100) <= 20

def test_prefetch_card_uses_same_target_fallback_as_profile(monkeypatch):
    mgr, s, _, _ = setup_manager(monkeypatch)
    ctx = mgr.get_prefetch_context(s.key, "routing")
    assert ctx["card"] == "\n".join(mgr.get_peer_card(s.key))
    assert "Compact standing preference" in ctx["card"]

def test_observations_present_newest_first(monkeypatch):
    mgr, s, _, _ = setup_manager(monkeypatch)
    ctx = mgr._fetch_peer_context(s.assistant_peer_id, target=s.user_peer_id)
    assert ctx["representation"].index("New event") < ctx["representation"].index("Old event")

def test_long_query_recovers_generic_identifier_with_scoped_fallback(monkeypatch):
    mgr, s, c, _ = setup_manager(monkeypatch)
    hit = message("Device ZX73B401EU is installed", "hit")
    c.results = lambda q: [hit] if q == "ZX73B401EU" else [message("unrelated archive", "noise")]
    text = mgr.search_context(s.key, "Which device model is installed ZX73B401EU/04 at home")
    assert "ZX73B401EU" in text
    assert len(c.search_calls) <= 5
    assert all(kw["filters"] == {"peer_perspective": s.user_peer_id} for _, kw in c.search_calls)

def test_raw_ranking_and_excerpt_center_on_matches(monkeypatch):
    mgr, s, c, _ = setup_manager(monkeypatch)
    c.results = [message("unrelated archive", "noise"), message("boilerplate " * 500 + "alpha umask 0077 private baseline", "hit")]
    text = mgr.search_context(s.key, "alpha umask 0077 private baseline", max_tokens=350)
    assert "0077" in text
    assert "private baseline" in text
    assert "unrelated archive" not in text.split("\n\n")[0]
    assert text.count("0077") == 1
    assert len(text) <= 1400

def test_notifications_kept_without_user_authorship_or_derivation(monkeypatch):
    mgr, s, c, cfg = setup_manager(monkeypatch)
    p = provider(mgr, s, cfg)
    p.sync_turn("[IMPORTANT: Background process proc_123 completed normally (exit code 0).\nOutput:\ndone]", "Tests finished")
    wait_sync(p)
    assert len(c.remote.messages) == 2
    for msg in c.remote.messages:
        assert msg.peer_id == s.assistant_peer_id
        assert msg.metadata["source"] == "runtime_notification"
        assert msg.configuration["reasoning"]["enabled"] is False

def test_real_user_text_containing_notification_is_not_filtered(monkeypatch):
    mgr, s, c, cfg = setup_manager(monkeypatch)
    p = provider(mgr, s, cfg)
    text = "Please debug this: [IMPORTANT: Background process proc_123 completed]"
    p.sync_turn(text, "Will investigate")
    wait_sync(p)
    assert c.remote.messages[0].peer_id == s.user_peer_id
    assert c.remote.messages[0].content == text
    assert c.remote.messages[0].metadata["source"] == "user_turn"

def test_turn_arriving_during_initialization_replays_once(monkeypatch):
    mgr, s, c, cfg = setup_manager(monkeypatch)
    p = provider(mgr, s, cfg)
    gate = threading.Event()
    p._session_initialized = False
    p._init_thread = threading.Thread(target=lambda: gate.wait(3))
    p._init_thread.start()
    p.sync_turn("First real user instruction", "First answer")
    gate.set()
    p._init_thread.join(3)
    p._session_initialized = True
    p.sync_turn("Second real user instruction", "Second answer")
    wait_sync(p)
    assert [m.content for m in c.remote.messages] == ["First real user instruction", "First answer", "Second real user instruction", "Second answer"]
    p.sync_turn("Third instruction", "Third answer")
    wait_sync(p)
    assert sum(m.content == "First real user instruction" for m in c.remote.messages) == 1

def test_memory_seed_dedup_survives_manager_recreation(monkeypatch, tmp_path):
    mgr, s, c, _ = setup_manager(monkeypatch)
    (tmp_path / "USER.md").write_text("A real durable preference")
    assert mgr.migrate_memory_files(s.key, str(tmp_path))
    mgr2, s2, _, _ = setup_manager(monkeypatch, c)
    assert not mgr2.migrate_memory_files(s2.key, str(tmp_path))
    assert len(c.remote.uploads) == 1
    assert c.peers[s.user_peer_id].metadata["unrelated"] == "keep"
    meta = c.remote.uploads[0]["metadata"]
    assert meta["origin"] == "agent_memory_import"
    assert meta["author"] != "user"
    assert len(meta["sha256"]) == 64
    (tmp_path / "USER.md").write_text("A corrected durable preference")
    assert mgr2.migrate_memory_files(s2.key, str(tmp_path))
    assert len(c.remote.uploads) == 2

def test_failed_seed_remains_retryable(monkeypatch, tmp_path):
    mgr, s, c, _ = setup_manager(monkeypatch)
    (tmp_path / "USER.md").write_text("Durable preference")
    c.remote.fail_upload = True
    assert not mgr.migrate_memory_files(s.key, str(tmp_path))
    c.remote.fail_upload = False
    assert mgr.migrate_memory_files(s.key, str(tmp_path))
    assert not mgr.migrate_memory_files(s.key, str(tmp_path))
    assert len(c.remote.uploads) == 1

def test_ai_seed_attributed_and_not_repeated(monkeypatch):
    mgr, s, c, _ = setup_manager(monkeypatch)
    assert mgr.seed_ai_identity(s.key, "Helpful persona", source="soul_md")
    assert not mgr.seed_ai_identity(s.key, "Helpful persona", source="soul_md")
    assert len(c.remote.messages) == 1
    assert c.remote.messages[0].metadata["source"] == "ai_identity_seed"

def test_legacy_matching_seed_is_not_imported_again(monkeypatch, tmp_path):
    mgr, s, c, _ = setup_manager(monkeypatch)
    (tmp_path / "USER.md").write_text("Durable preference")
    c.results = [message("<prior_memory_file>\n<context>Legacy foundation</context>\n\nDurable preference\n</prior_memory_file>")]
    c.results[0].metadata = {"source": "local_memory", "original_file": "USER.md", "target_peer": "user"}
    assert not mgr.migrate_memory_files(s.key, str(tmp_path))
    assert not c.remote.uploads
