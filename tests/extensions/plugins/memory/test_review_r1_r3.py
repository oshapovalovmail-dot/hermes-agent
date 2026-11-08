"""Independent R1-R3 acceptance: native DTOs and isolated HTTP lifecycle."""
import importlib.util
import json
import sys
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS

import pytest


def load_sibling(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TESTS = Path(__file__).resolve().parents[2]
hc = load_sibling("honcho_capture_contract", TESTS / "honcho_plugin/test_capture_context_contract.py")
ovc = load_sibling("openviking_capture_contract", Path(__file__).with_name("test_openviking_capture_relevance_regression.py"))
rig = hc.rig
isolated = ovc.isolated
http_fixture = ovc.http_fixture


@pytest.mark.parametrize("batch", [True, False])
def test_honcho_async_human_suffix(rig, batch):
    text = hc.callback(batch) + "\nActually, I always prefer concise answers."
    rows = hc.capture(rig, text)
    assert rows[0].peer_id == "human"
    assert rows[0].content == text
    assert rows[0].metadata["source_kind"] == "human"
    rules = rows[0].configuration.model_dump()["reasoning"]["custom_instructions"]
    assert "explicit" in rules and "notification" in rules


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("query,positive,noise", [
    (ovc.QUERY, "Очистка фильтра посудомоечной машины выполняется водой.",
     "Если быстрый прогон не завершился, приоритет fallback eval."),
    ("Please choose a telescope, priority quality and reliability if possible",
     "A telescope with coated optics is installed.", "If possible, priority fallback eval quality checks."),
    ("Выбери микроскоп: желательно качество и надежность, если возможно",
     "Микроскоп установлен в лаборатории.", "Если возможно, желательно качество тестов харнеса."),
])
def test_honcho_full_query_filters_generic_overlap(rig, fallback, query, positive, noise):
    p, mgr, session, _, peers = rig
    representation = "[2026-10-10] " + noise + "\n[2026-10-09] " + positive
    assert hc.relevant_representation(noise, query) == ""
    def context(**kwargs):
        if fallback:
            raise RuntimeError("fixture offline")
        return NS(representation=representation, peer_card=[])
    for peer in peers.values():
        object.__setattr__(peer, "context", context)
        object.__setattr__(peer, "representation", lambda **kw: representation)
        object.__setattr__(peer, "get_card", lambda **kw: [])
    result = mgr.get_prefetch_context(session.key, query)
    assert positive in result["representation"]
    injected = p._truncate_to_budget(p._format_first_turn_context(result))
    assert positive in injected
    assert noise not in injected


@pytest.mark.parametrize("batch", [True, False])
@pytest.mark.parametrize("reject_batch", [False, True])
@pytest.mark.parametrize("canonical", [False, True])
def test_openviking_async_human_suffix_native_extractor(http_fixture, isolated, batch, reject_batch, canonical):
    state, _ = http_fixture
    state["reject_batch"] = reject_batch
    text = hc.callback(batch) + "\nActually, I always prefer concise answers."
    manager, p = ovc.make_manager(isolated)
    try:
        messages = [{"role": "user", "content": text}, {"role": "assistant", "content": "Noted."}]
        manager.sync_all(text, "Noted.", session_id="saved", **({"messages": messages} if canonical else {}))
        assert manager.flush_pending(timeout=5)
        manager.on_session_end(messages)
        archived = p._client.get("/api/v1/sessions/saved")["result"]["messages"]
        human = [part["text"] for m in archived if m["role"] == "user" for part in m["parts"] if part["type"] == "text"]
        assert text in human
        assert state["committed"]
        assert any("explicit human" in part.lower() and "task" in part.lower() for part in human)
        interpreter = sys.executable if importlib.util.find_spec("openviking") is not None else None
        assert interpreter, "native DTO/extractor acceptance requires installed interpreter"
        script = '''import json, sys
from openviking.server.routers.sessions import AddMessageRequest, _resolve_message_parts
from openviking.server.identity import RequestContext, Role, UserIdentifier
ctx = RequestContext(UserIdentifier("fixture", "fixture"), Role.USER)
from openviking.message.message import Message
from openviking.session.memory.session_extract_context_provider import SessionExtractContextProvider
restored=[]
for payload in json.load(sys.stdin):
    request=AddMessageRequest.model_validate(payload)
    msg=Message(id='fixture', role=request.role, peer_id=request.peer_id,
                parts=_resolve_message_parts(request, ctx), message_kind=request.message_kind)
    restored.append(Message.from_dict(msg.to_dict()))
provider=object.__new__(SessionExtractContextProvider)
text=provider._assemble_conversation(restored)
assert 'Actually, I always prefer concise answers.' in text
assert 'explicit human' in text.lower() and 'task' in text.lower()
print('Native DTO/extractor: human suffix and attribution guard retained')
'''
        result = subprocess.run([interpreter, "-c", script], input=json.dumps(archived), text=True, capture_output=True, timeout=45, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        manager.shutdown_all()


@pytest.mark.parametrize("unit", [
    "Replica recovery is authorized. This is task-local, not global policy.",
    "Replica recovery is authorized.\n  This is task-local, not global policy.",
    "- Replica recovery is authorized.\n  This is task-local, not global policy.",
    "Replica recovery is authorized " + "temporarily " * 130 + "but not global policy.",
])
def test_openviking_injected_scoped_evidence_is_atomic(http_fixture, isolated, unit):
    state, _ = http_fixture
    state["candidates"] = [ovc.leaf("replica", "Replica recovery authorization")]
    state["bodies"] = {state["candidates"][0]["uri"]: unit}
    manager, _ = ovc.make_manager(isolated)
    try:
        block = manager.prefetch_all("Replica recovery", session_id="saved")
        plain = "\n".join(line.removeprefix("  ") for line in block.splitlines())
        assert unit in plain or "Replica recovery is authorized" not in plain
        if len(unit) < 1000:
            assert unit in plain
        with ovc.closing(ovc.SessionDB(isolated / "state.db")) as db:
            db.create_session("saved", source="cli")
            db.append_message("saved", "user", "Replica recovery", api_content=ovc.compose_user_api_content("Replica recovery", block, ""))
            saved = db.get_messages("saved")[0]
            assert saved["content"] == "Replica recovery"
            api_text = saved["api_content"] or saved["content"]
            assert "global policy" in api_text or "Replica recovery is authorized" not in api_text
    finally:
        manager.shutdown_all()
