"""Capture provenance and auto-recall regressions, isolated loopback HTTP only."""
import json
import sys
import importlib.util
import os
import subprocess
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import memory_test_plugins.openviking as ov
from agent.memory_manager import MemoryManager
from agent.turn_context import compose_user_api_content
from hermes_state import SessionDB
from tools.process_registry import format_process_notification

QUERY = ("Подбери топ-10 встраиваемых посудомоечных машин стандартных 60 см. "
         "Приоритет - надежность, качество, желательно авто открытие двери "
         "и если такое возможно- авто очистка фильтра")


def notification():
    return format_process_notification({
        "type": "async_delegation", "is_batch": True, "delegation_id": "fixture",
        "context": "Worker must use full-trace only, no writes for this task.",
        "goals": ["Review harness"], "results": [
            {"task_index": 0, "status": "completed", "summary": "Agent proposes slices 1-3."}],
    })


def leaf(name, abstract, level=2):
    return {"uri": f"viking://user/memories/events/{name}.md", "abstract": abstract,
            "score": 0.99, "level": level}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("OPENVIKING_") and name != "OPENVIKING_CONTRACT_PYTHON":
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def http_fixture(isolated, monkeypatch):
    state = {"records": [], "messages": [], "candidates": [], "bodies": {},
             "reject_batch": False, "committed": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, result, status=200):
            data = json.dumps({"result": result}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            state["records"].append(("GET", parsed.path, None))
            if parsed.path == "/health":
                data = json.dumps({"status": "ok", "healthy": True, "version": "fixture"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif parsed.path == "/api/v1/content/read":
                uri = parse_qs(parsed.query)["uri"][0]
                self.reply(state["bodies"].get(uri, ""))
            elif parsed.path.startswith("/api/v1/sessions/"):
                self.reply({"messages": state["messages"], "pending_tokens": 0})
            elif parsed.path == "/api/v1/system/status":
                self.reply({})
            else:
                self.reply({}, 404)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["records"].append(("POST", self.path, payload))
            if self.path.endswith("/messages/batch"):
                if state["reject_batch"]:
                    self.reply({}, 404)
                    return
                state["messages"].extend(payload["messages"])
                self.reply({"added": len(payload["messages"])})
            elif self.path.endswith("/messages"):
                state["messages"].append(payload)
                self.reply({"added": 1})
            elif self.path.endswith("/commit"):
                state["committed"] = True
                self.reply({"task_id": "fixture-commit"})
            elif self.path in ("/api/v1/search/search", "/api/v1/search/find"):
                self.reply({"memories": state["candidates"], "resources": []})
            else:
                self.reply({}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("OPENVIKING_ENDPOINT", endpoint)
    monkeypatch.setenv("OPENVIKING_ACCOUNT", "fixture")
    monkeypatch.setenv("OPENVIKING_USER", "fixture")
    monkeypatch.setenv("OPENVIKING_AGENT", "hermes")
    try:
        yield state, endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def make_manager(home):
    manager = MemoryManager()
    p = ov.OpenVikingMemoryProvider()
    manager.add_provider(p)
    manager.initialize_all("saved", hermes_home=str(home))
    assert p._client is not None
    return manager, p


@pytest.mark.parametrize("reject_batch", [False, True])
@pytest.mark.parametrize("canonical", [False, True])
def test_native_lifecycle_preserves_machine_provenance(http_fixture, isolated, reject_batch, canonical):
    state, _ = http_fixture
    state["reject_batch"] = reject_batch
    # Closed canonical legacy envelope has a provable body boundary.
    user = format_process_notification({"session_id": "fixture", "command": "review",
        "exit_code": 0, "output": "Worker proposes task-local changes."})
    answer = "Review complete; these are proposals, not user decisions."
    messages = [{"role": "user", "content": user}, {"role": "assistant", "content": answer}]
    manager, p = make_manager(isolated)
    try:
        manager.sync_all(user, answer, session_id="saved", **({"messages": messages} if canonical else {}))
        assert manager.flush_pending(timeout=5)
        manager.on_session_end(messages)
        assert state["committed"]
        archived = p._client.get("/api/v1/sessions/saved")["result"]["messages"]
        assert not any(m["role"] == "user" for m in archived)
        machine = [part for m in archived for part in m["parts"] if part["type"] == "tool"]
        assert len(machine) == 1
        assert machine[0]["tool_output"] == user
        assert machine[0]["tool_input"]["source_kind"] == "machine_notification"
        assert machine[0]["tool_input"]["scope"] == "task"
        assert machine[0]["tool_input"]["original_role"] == "user"
        assert machine[0]["tool_input"]["human_endorsed"] is False
        assert archived[0]["message_kind"] == "tool_transport"
        assert answer in json.dumps(archived)
    finally:
        manager.shutdown_all()


def test_mixed_operator_text_survives_bracket_notification(http_fixture, isolated):
    state, _ = http_fixture
    frame = format_process_notification({"session_id": "fixture", "command": "test", "exit_code": 0,
                                         "output": "Worker says: no writes [task-local]."})
    text = "Запомни: мне нужны короткие ответы.\n" + frame + "\nНо этот запрет только для задания."
    manager, _provider = make_manager(isolated)
    try:
        manager.sync_all(text, "Принято", session_id="saved")
        assert manager.flush_pending(timeout=5)
        manager.on_session_end([])
        human = [part["text"] for m in state["messages"] if m["role"] == "user"
                 for part in m["parts"] if part["type"] == "text"]
        assert "короткие ответы" in "\n".join(human)
        assert "только для задания" in "\n".join(human)
        assert "Worker says" not in "\n".join(human)
        tools = [part for m in state["messages"] for part in m["parts"] if part["type"] == "tool"]
        assert tools[0]["tool_output"] == frame
    finally:
        manager.shutdown_all()


@pytest.mark.parametrize("text", [
    "Запомни документ:\n```text\n" + notification() + "\n```\nЭто цитата из протокола.",
    "Запомни этот документ:\n" + format_process_notification(
        {"session_id": "copied", "command": "test", "exit_code": 0, "output": "Copied log."}),
    'Сохрани цитату: "[IMPORTANT: Background process x exited]"',
    "> " + notification().replace("\n", "\n> "),
    "[IMPORTANT: Background process incomplete\nНо пользователь добавил текст без закрытия",
])
def test_quotes_documents_and_unclosed_frames_are_not_discarded(text, isolated):
    batch = ov.OpenVikingMemoryProvider._messages_to_openviking_batch([{"role": "user", "content": text}])
    assert batch[0]["role"] == "user"
    assert batch[0]["parts"][0]["text"] == text


def test_explicit_source_metadata_uses_native_parts_not_human_authorship(isolated):
    batch = ov.OpenVikingMemoryProvider._messages_to_openviking_batch([
        {"role": "user", "content": "Worker: do not publish for this task.",
         "source_kind": "task_assignment", "scope": "task"},
        {"role": "user", "content": "Article: birds migrate annually.",
         "metadata": {"source_kind": "document", "scope": "resource"}},
    ], assistant_peer_id="hermes")
    assert [m["role"] for m in batch] == ["assistant", "assistant"]
    assert [m["parts"][0]["tool_input"]["source_kind"] for m in batch] == ["task_assignment", "document"]
    assert "birds migrate" in batch[1]["parts"][0]["tool_output"]


def test_actual_new_query_drops_generic_overlap_and_reads_thematic_body(http_fixture, isolated):
    state, _ = http_fixture
    state["candidates"] = [
        leaf("siemens", "Посудомоечная машина Siemens: очистка фильтра."),
        leaf("bank", "Memory-bank: возможности инструмента и качество разработки."),
        leaf("fallback", "Если быстрый прогон не завершился, приоритет fallback eval."),
        leaf("harness", "Качество харнеса после явного выбора пользователя."),
        leaf("folder", "Посудомоечные машины и прочие прошлые темы.", level=0),
    ]
    state["bodies"] = {x["uri"]: x["abstract"] for x in state["candidates"]}
    state["bodies"][state["candidates"][0]["uri"]] = (
        "Старые сведения о коде.\n\nПосудомоечная машина Siemens: фильтр промывается водой.\n\n"
        "Нерелевантный статус деплоя.")
    manager, _ = make_manager(isolated)
    try:
        block = manager.prefetch_all(QUERY, session_id="saved")
        assert "промывается водой" in block
        assert "bank.md" not in block
        assert "fallback.md" not in block
        assert "harness.md" not in block
        assert "folder.md" not in block
        assert "статус деплоя" not in block
        with closing(SessionDB(isolated / "state.db")) as db:
            db.create_session("saved", source="cli")
            db.append_message("saved", "user", QUERY, api_content=compose_user_api_content(QUERY, block, ""))
            saved = db.get_messages("saved")[0]
            assert saved["content"] == QUERY
            assert "fallback.md" not in saved["api_content"]
        assert {"viking_remember", "viking_forget", "viking_add_resource"} <= manager.get_all_tool_names()
    finally:
        manager.shutdown_all()


@pytest.mark.parametrize("failure", ["irrelevant_body", "read_limit", "read_error"])
def test_leaf_abstract_cannot_replace_unverified_body(failure, isolated):
    class Client:
        def get(self, *args, **kwargs):
            if failure == "read_error":
                raise RuntimeError("fixture unavailable")
            return {"result": "Unrelated deployment status."}
    p = ov.OpenVikingMemoryProvider()
    entries = p._build_prefetch_entries(Client(), [leaf("wrong", "Nebula certificate renewal")],
        prefer_abstract=False, max_injected_chars=4000, deadline=ov.time.monotonic() + 4,
        request_timeout=1, full_read_limit=0 if failure == "read_limit" else 2,
        query="Nebula certificate renewal")
    assert entries == []


def test_body_heading_is_not_supporting_evidence(isolated):
    class Client:
        def get(self, *args, **kwargs):
            return {"result": "# Nebula certificate renewal\nUnrelated deployment status."}
    p = ov.OpenVikingMemoryProvider()
    entries = p._build_prefetch_entries(Client(), [leaf("wrong", "Nebula certificate renewal")],
        prefer_abstract=False, max_injected_chars=4000, deadline=ov.time.monotonic() + 4,
        request_timeout=1, full_read_limit=2, query="Nebula certificate renewal")
    assert entries == []


def test_installed_server_dto_retains_provenance_and_omits_machine_from_user_extraction(isolated):
    interpreter = sys.executable if importlib.util.find_spec("openviking") is not None else None
    if not interpreter:
        pytest.skip("optional installed OpenViking DTO contract interpreter")
    batch = ov.OpenVikingMemoryProvider._messages_to_openviking_batch(
        [{"role": "user", "content": notification(),
          "source_kind": "machine_notification", "scope": "task"}], assistant_peer_id="hermes")
    script = '''import json, sys
from openviking.server.routers.sessions import AddMessageRequest, _resolve_message_parts
from openviking.server.identity import RequestContext, Role, UserIdentifier
ctx = RequestContext(UserIdentifier("fixture", "fixture"), Role.USER)
from openviking.message.message import Message
from openviking.session.memory.session_extract_context_provider import SessionExtractContextProvider
payload = json.load(sys.stdin)
request = AddMessageRequest.model_validate(payload[0])
msg = Message(id="fixture", role=request.role, peer_id=request.peer_id,
              parts=_resolve_message_parts(request, ctx), message_kind=request.message_kind)
restored = Message.from_dict(msg.to_dict())
assert restored.parts[0].tool_input["source_kind"] == "machine_notification"
assert restored.parts[0].tool_input["scope"] == "task"
provider = object.__new__(SessionExtractContextProvider)
assert provider._assemble_conversation([restored]) == ""
print("DTO roundtrip + default user extractor excludes machine ToolPart: OK")
'''
    result = subprocess.run([interpreter, "-c", script], input=json.dumps(batch),
                            text=True, capture_output=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
