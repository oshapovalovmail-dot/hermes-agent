"""Cancellation without assistant text must leave standalone ACP ready for the next prompt."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from acp.schema import TextContentBlock

from acp_adapter.server import HermesACPAgent
from acp_adapter.session import SessionManager


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("result_text", [{}, {"final_response": None}, {"final_response": ""}])
async def test_empty_interrupted_response_finishes_and_accepts_next_prompt(cancelled, result_text):
    manager = SessionManager(agent_factory=lambda: MagicMock(name="MockAIAgent"))
    server = HermesACPAgent(session_manager=manager)
    server._conn = MagicMock(session_update=AsyncMock())
    session = await server.new_session(cwd=".")
    state = manager.get_session(session.session_id)
    assert state is not None
    state.agent.model = "test-model"
    state.agent.provider = "openrouter"
    original_history = [{"role": "user", "content": "first request"}]

    def interrupted_turn(**kwargs):
        if cancelled:
            asyncio.run(server.cancel(session.session_id))
        return {**result_text, "interrupted": True, "messages": original_history}

    state.agent.run_conversation = interrupted_turn
    response = await server.prompt(
        prompt=[TextContentBlock(type="text", text="first request")],
        session_id=session.session_id,
    )

    assert response.stop_reason == ("cancelled" if cancelled else "end_turn")
    assert not state.is_running
    assert state.history == original_history
    next_turn = MagicMock(return_value={"final_response": "done", "messages": []})
    state.agent.run_conversation = next_turn
    response = await server.prompt(
        prompt=[TextContentBlock(type="text", text="second request")],
        session_id=session.session_id,
    )

    assert response.stop_reason == "end_turn"
    next_turn.assert_called_once()
    assert state.queued_prompts == []
    assert not state.is_running
