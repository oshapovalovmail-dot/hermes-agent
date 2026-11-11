"""Failed-turn boundaries must not ask to resend an already received successor.

Run the real loop, durable closer, persistence and provider request assembly. Only the
model transport is scripted; it does not infer whether the material is a new task.
"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.turn_failure_copy import FAILED_TURN_DISPLAY_KIND, untyped_failed_turn_display_kind
from tools.registry import registry


PROBE = "successor_read_only_probe"
SCHEMA = {"type": "function", "function": {"name": PROBE, "description": "read-only fixture",
          "parameters": {"type": "object", "properties": {}}}}
registry.register(name=PROBE, toolset="utility", schema=SCHEMA["function"],
                  handler=lambda args, **kwargs: "probe complete", override=True)


def _mock_response(content=None, finish_reason="stop", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
                           model="fixture-model", usage=None)


INTRO = "Изучи и скажи, что думаешь; материал следующим сообщением."
MATERIALS = [
    "Вот текст: описание поведения сабагентов.",
    "https://example.invalid/document",
    "[Document attached: design.pdf]\nИзвлечённый текст документа.",
    [{"type": "text", "text": "Вот изображение"},
     {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
]


@pytest.fixture
def durable_agent(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    from run_agent import AIAgent

    monkeypatch.setattr("agent.title_generator.maybe_auto_title", lambda *a, **k: None)
    monkeypatch.setattr("hermes_cli.plugins.discover_plugins", lambda: None)
    db = SessionDB(tmp_path / "state.db")
    db.create_session("successor", "test", model="fixture-model")
    with (patch("model_tools.get_tool_definitions", return_value=[SCHEMA]),
          patch("model_tools.check_toolset_requirements", return_value={}),
          patch("agent.model_metadata.fetch_model_metadata", return_value={}),
          patch("agent.process_bootstrap.OpenAI")):
        agent = AIAgent(api_key="fixture-only", provider="custom", model="fixture-model",
                        base_url="http://127.0.0.1:1/v1", session_id="successor", session_db=db,
                        quiet_mode=True, skip_context_files=True, skip_memory=True,
                        save_trajectories=False)
    agent._session_db_created = True
    agent._disable_streaming = True
    agent._cached_system_prompt = "SYSTEM: fixture"
    agent._use_prompt_caching = False
    agent.compression_enabled = False
    agent._skip_mcp_refresh = True
    agent.tool_delay = 0
    monkeypatch.setattr(agent, "_model_supports_vision", lambda: True)
    try:
        yield agent, db
    finally:
        db.close()


def _assert_boundary_copy(boundary):
    assert boundary["display_kind"] == FAILED_TURN_DISPLAY_KIND
    text = boundary["content"]
    assert any("а" <= c.lower() <= "я" for c in text), text
    assert "not processed" not in text.lower(), text
    assert "send it again" not in text.lower(), text
    assert "повтор" not in text.lower(), text


@pytest.mark.parametrize("material", MATERIALS, ids=["text", "link", "document", "image"])
def test_cancelled_intro_then_successor_runs_once_without_resend_guidance(durable_agent, material):
    agent, db = durable_agent
    seen, displayed = [], []
    agent.stream_delta_callback = displayed.append

    def cancelled(request):
        seen.append(deepcopy(request["messages"]))
        # A busy successor can interrupt the first transport. The durable boundary
        # remains necessary; whether the gateway chose interrupt is not inferred here.
        agent.interrupt("следующее сообщение")
        raise InterruptedError("fixture successor interrupted the request")

    agent._interruptible_api_call = cancelled
    first = agent.run_conversation(INTRO, persist_user_platform_id="intro-1")
    assert first["interrupted"] is True and first["completed"] is False
    rows = db.get_messages_as_conversation("successor")
    assert [r["role"] for r in rows] == ["user", "assistant"]
    boundary = rows[-1]
    # The durable closer must be idempotent, not a second model answer or callback.
    from agent.conversation_loop import _close_durable_failed_turn
    _close_durable_failed_turn(agent, first)
    assert len(db.get_messages_as_conversation("successor")) == 2
    assert boundary["content"] not in displayed

    def complete(request):
        seen.append(deepcopy(request["messages"]))
        return _mock_response(content="Материал разобран.", finish_reason="stop")

    agent._interruptible_api_call = complete
    second = agent.run_conversation(material, conversation_history=rows,
                                    persist_user_platform_id="material-2")
    assert second["completed"] is True
    assert len(seen) == 2  # no extra inference or replay of the failed turn
    sent = [r for r in seen[-1] if r["role"] != "system"]
    assert [r["role"] for r in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"] == INTRO and sent[-1]["content"] == material
    assert seen[0][0] == seen[1][0]  # system prompt byte stability
    assert "display_kind" not in sent[1]  # UI provenance never leaks onto provider wire
    stored = db.get_messages_as_conversation("successor")
    assert [r["role"] for r in stored] == ["user", "assistant", "user", "assistant"]
    raw = [r for r in db.get_messages("successor") if r["role"] == "user"]
    assert [r["platform_message_id"] for r in raw] == ["intro-1", "material-2"]
    _assert_boundary_copy(boundary)


@pytest.mark.parametrize("action", ["steer", "redirect", "stop"])
def test_live_intervention_keeps_control_semantics(durable_agent, action):
    agent, db = durable_agent
    requests = []

    def call(request):
        requests.append(deepcopy(request["messages"]))
        if len(requests) == 1:
            if action == "stop":
                agent.interrupt(hard_cancel=True)
                assert agent.redirect("После явной отмены не продолжать.") is False
            elif action == "redirect":
                assert agent.redirect("Вместо этого проверь только документ.") is True
            else:
                assert agent.steer("Материал: https://example.invalid/document") is True
                tool = SimpleNamespace(id="p1", type="function",
                                       function=SimpleNamespace(name=PROBE, arguments="{}"))
                return _mock_response(finish_reason="tool_calls", tool_calls=[tool])
            raise InterruptedError("fixture intervention")
        return _mock_response(content="Готово.", finish_reason="stop")

    agent._interruptible_api_call = call
    result = agent.run_conversation(INTRO)
    if action == "stop":
        assert result["interrupted"] is True and result["completed"] is False
        assert len(requests) == 1
    else:
        assert result["completed"] is True and result["user_intervened"] is True
        assert not result.get("pending_steer")
        assert not [r for r in db.get_messages_as_conversation("successor")
                    if r.get("display_kind") == FAILED_TURN_DISPLAY_KIND]
        if action == "redirect":
            assert len(requests) == 2
            assert "Вместо этого проверь только документ." in str(requests[-1])


@pytest.mark.parametrize("legacy", [
    "Your request was not processed. Send it again if you still want me to carry it out.",
    "This turn did not complete. Some actions may already have run; verify their effects before resending.",
])
def test_legacy_exact_boundary_keeps_provenance_without_classifying_quotations(legacy):
    assert untyped_failed_turn_display_kind("assistant", legacy) == FAILED_TURN_DISPLAY_KIND
    assert untyped_failed_turn_display_kind("user", legacy) is None
    assert untyped_failed_turn_display_kind("assistant", "Цитата: " + legacy) is None


def test_tool_effects_still_require_verification(durable_agent):
    agent, db = durable_agent
    from agent.conversation_loop import _close_durable_failed_turn
    db.append_message("successor", "user", INTRO)
    calls = [{"id": "c1", "type": "function",
              "function": {"name": "terminal", "arguments": "{}"}}]
    db.append_message("successor", "assistant", "", tool_calls=calls)
    db.append_message("successor", "tool", "effect applied", tool_call_id="c1")
    rows = db.get_messages_as_conversation("successor")
    result = {"messages": rows, "completed": False, "failed": True,
              "failure_reason": "server_error", "current_turn_user_idx": 0}
    _close_durable_failed_turn(agent, result)
    boundary = db.get_messages_as_conversation("successor")[-1]
    _assert_boundary_copy(boundary)
    assert "проверь" in boundary["content"].lower()
    assert "действ" in boundary["content"].lower()
