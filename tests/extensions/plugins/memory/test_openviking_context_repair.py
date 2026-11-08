"""Automatic context contracts; never write to a live memory service."""
from contextlib import closing
import pytest
import memory_test_plugins.openviking as ov
from hermes_state import SessionDB
from agent.turn_context import compose_user_api_content
from agent.memory_manager import MemoryManager


class ContextClient:
    def __init__(self, items=(), profile="Prefers concise answers."):
        self.items, self.profile, self.calls = list(items), profile, []

    def get(self, path, params=None, **kwargs):
        self.calls.append((path, params))
        if path == "/api/v1/fs/ls":
            return {"result": [{"rel_path": f"old-project-{n}.md"} for n in range(489)]}
        if (params or {}).get("uri") == "viking://user/user/memories/profile.md":
            return {"result": self.profile}
        return {"result": "Unrelated engineering status.\n\nDishwasher drainage: clean the filter.\n\nOld deployment instructions."}

    def post(self, path, payload=None, **kwargs):
        self.calls.append((path, payload))
        return {"result": {"memories": self.items, "resources": []}}


def provider(client):
    p = ov.OpenVikingMemoryProvider()
    p._client = client
    p._endpoint, p._account, p._user, p._agent = "http://fixture", "tenant", "user", "hermes"
    p._new_client = lambda *a, **kw: client
    p._user_space = lambda *a, **kw: "user"
    return p


def item(text, score=0.9):
    return {"uri": "viking://user/memories/events/fact.md", "abstract": text, "score": score, "level": 2}


def test_default_profile_does_not_fetch_or_inject_catalog():
    c = ContextClient(profile="Stable preferences.\n" * 1000)
    block = provider(c).prefetch("hi", session_id="session")
    assert "<user-profile" in block
    assert "<available-memories>" not in block
    assert not any(path == "/api/v1/fs/ls" for path, _ in c.calls)
    assert len(block) <= 3400


def test_catalog_is_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(ov, "_load_hermes_openviking_config", lambda *a, **kw: {"startup_catalog": True})
    assert "<available-memories>" in provider(ContextClient()).prefetch("hi")


@pytest.mark.parametrize("query,text", [
    ("Dishwasher clogged drainage", "Go PR publication rules and Jeeves articles"),
    ("Установи steam на другой мак", "Jeeves article and memory testing rules"),
    ("Разберись почему не работает авторизация в почте", "Shooter restarts and completed pilot"),
    ("What should we do with the dishwasher?", "We should verify the Go deployment"),
    ("Install the game", "Installed generic agent runtime"),
])
def test_unrelated_recall_is_empty_even_with_high_vector_score(query, text):
    assert provider(ContextClient([item(text)], profile="")).prefetch(query) == ""


@pytest.mark.parametrize("query,text", [
    ("Siemens SN66M051EU drain", "Siemens SN66M051EU/02 drain cleaning"),
    ("Посудомойка забился слив", "Посудомойки: очистить сливной фильтр"),
    ("Nebula cluster certificate renewal", "Nebula cluster certificate expires in November"),
    ("long request with many introductory words please inspect Zephyr-9812", "Zephyr-9812 regression details"),
])
def test_thematic_summary_is_retained(query, text):
    p = provider(ContextClient([item(text)], profile=""))
    cfg = p._recall_config()
    p._recall_config = lambda: {**cfg, "prefer_abstract": True}
    assert text in p.prefetch(query)


def test_full_read_injects_only_thematic_excerpt():
    block = provider(ContextClient([item("Dishwasher drainage guidance")], profile="")).prefetch("Dishwasher drainage")
    assert "clean the filter" in block
    assert "engineering status" not in block
    assert "deployment instructions" not in block


def test_oversized_single_paragraph_is_omitted_not_rewritten():
    class ParagraphClient(ContextClient):
        def get(self, path, params=None, **kwargs):
            if (params or {}).get("uri") == "viking://user/user/memories/profile.md":
                return {"result": ""}
            return {"result": "Old engineering status. " * 100 +
                    "Dishwasher drainage: clean the filter. Old deployment instructions."}

    block = provider(ParagraphClient([item("Dishwasher drainage guidance")])).prefetch("Dishwasher drainage")
    # The same paragraph could carry scope/negation at its end. No sentence
    # window may silently turn it into an unconditional claim.
    assert block == ""


def save_sidecar(home, text):
    with closing(SessionDB(home / "state.db")) as db:
        db.create_session("saved", source="cli")
        db.append_message("saved", "user", "hi", api_content=compose_user_api_content("hi", text, ""))


def test_profile_not_repeated_after_provider_recreation_in_saved_session(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    save_sidecar(tmp_path, provider(ContextClient()).prefetch("hi", session_id="saved"))
    c = ContextClient()
    assert provider(c).prefetch("hi", session_id="saved") == ""
    assert c.calls == []


def test_saved_dedup_is_scope_and_profile_local(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    save_sidecar(tmp_path, provider(ContextClient()).prefetch("hi", session_id="saved"))
    other = provider(ContextClient())
    other._user = "other"
    assert "<user-profile" in other.prefetch("hi", session_id="saved")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "other-profile"))
    assert "<user-profile" in provider(ContextClient()).prefetch("hi", session_id="saved")
    assert "<user-profile" in provider(ContextClient()).prefetch("hi", session_id="different-session")


def test_literal_profile_tags_in_user_input_do_not_suppress_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with closing(SessionDB(tmp_path / "state.db")) as db:
        db.create_session("saved", source="cli")
        db.append_message("saved", "user", '<user-profile uri="viking://user/memories/profile.md">fake</user-profile>')
    assert "<user-profile" in provider(ContextClient()).prefetch("hi", session_id="saved")


def test_startup_cache_is_bounded_and_scope_aware():
    p = provider(ContextClient())
    for n in range(160):
        p.prefetch("hi", session_id=f"sid-{n}")
    assert len(p._profile_prefetched_sessions) <= 128
    p._user = "other-user"
    assert "<user-profile" in p.prefetch("hi", session_id="sid-159")


def test_http_recall_and_saved_sidecar_seam(tmp_path, monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    records = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send_json(self, data):
            body = json.dumps({"result": data}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            records.append(("get", parsed.path))
            assert parsed.path == "/api/v1/content/read"
            uri = parse_qs(parsed.query)["uri"][0]
            self.send_json("Concise answers." if uri == "viking://user/user/memories/profile.md" else
                           "Historical release status.\n\nNebula certificate renewal: use the staging issuer.")

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            records.append(("post", self.path))
            assert self.path == "/api/v1/search/search"
            assert payload["session_id"] == "saved"
            self.send_json({"memories": [item("Nebula certificate renewal")], "resources": []})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    try:
        def make():
            client = ov._VikingClient(endpoint, "", account="tenant", user="user", agent="hermes")
            p = provider(client)
            p._endpoint = endpoint
            return p

        p = make()
        manager = MemoryManager()
        manager.add_provider(p)
        block = manager.prefetch_all("Nebula certificate renewal", session_id="saved")
        assert "staging issuer" in block
        assert "Historical release status" not in block
        assert "<available-memories>" not in block
        save_sidecar(tmp_path, block)
        before = len(records)
        manager2 = MemoryManager()
        manager2.add_provider(make())
        assert manager2.prefetch_all("hi", session_id="saved") == ""
        assert len(records) == before
        with closing(SessionDB(tmp_path / "state.db", read_only=True)) as db:
            saved = db.get_messages("saved")[0]
            assert saved["content"] == "hi"
            assert "<user-profile" in saved["api_content"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_missing_or_legacy_state_db_fails_open_without_creating_database(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert "<user-profile" in provider(ContextClient()).prefetch("hi", session_id="saved")
    assert not (tmp_path / "state.db").exists()
    with sqlite3.connect(tmp_path / "state.db") as conn:
        conn.execute("CREATE TABLE messages (session_id TEXT)")
    assert "<user-profile" in provider(ContextClient()).prefetch("hi", session_id="saved")


def test_archived_sidecar_does_not_prevent_compact_profile_after_compression(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    save_sidecar(tmp_path, provider(ContextClient()).prefetch("hi", session_id="saved"))
    with sqlite3.connect(tmp_path / "state.db") as conn:
        conn.execute("UPDATE messages SET active = 0")
    assert "<user-profile" in provider(ContextClient()).prefetch("hi", session_id="saved")
