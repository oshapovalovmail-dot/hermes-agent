"""Review dispatch must bind request inputs and billing to the originating turn."""
from types import SimpleNamespace
from unittest.mock import patch

from agent import background_review as br
from hermes_state import SessionDB
from tests.agent.test_background_review_cache_parity import _make_agent_stub, _make_recorder_class


def test_dispatch_captures_inputs_before_parent_advances():
    import run_agent
    parent = _make_agent_stub(run_agent.AIAgent)
    parent.tools = [{"type": "function", "function": {"name": "skills_list", "parameters": {}}}]
    history = [{"role": "user", "content": "original"}]
    captured = {}
    recorder = _make_recorder_class(captured, ("_cached_system_prompt", "tools", "session_id"))
    task_cfg = {"max_input_tokens": 1000}
    original_run = recorder.run_conversation

    def run(self, **kw):
        captured["history"] = kw["conversation_history"]
        return original_run(self, **kw)

    with patch.object(run_agent, "AIAgent", recorder), patch.object(recorder, "run_conversation", run):
        target, _ = br.spawn_background_review_thread(parent, history, review_skills=True, task_cfg=task_cfg)
        parent._cached_system_prompt = "changed"
        parent.session_id = "next-session"
        parent.tools[0]["function"]["name"] = "terminal"
        parent.reasoning_config["effort"] = "low"
        history[0]["content"] = "changed"
        target()
    assert captured["_cached_system_prompt"].startswith("PARENT-SYSTEM")
    assert captured["session_id"] == "sess-123"
    assert captured["tools"][0]["function"]["name"] == "skills_list"
    assert captured["init_kwargs"]["reasoning_config"]["effort"] == "medium"
    assert captured["history"][0]["content"] == "original"


def test_review_usage_preserves_provider_reported_cost(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        db.create_session("parent", source="cli")
        fork = SimpleNamespace(model="test", provider="test", base_url=None,
                               session_api_calls=2, session_input_tokens=100,
                               session_actual_cost_usd=0.12, session_cost_status="reported",
                               session_cost_source="provider")
        br._record_review_usage_to_parent(SimpleNamespace(_session_db=db, session_id="parent"),
                                         br._snapshot_review_usage(fork))
        row = db._conn.execute("SELECT * FROM session_model_usage WHERE session_id='parent'").fetchone()
        assert row["actual_cost_usd"] == 0.12
        assert row["cost_status"] == "reported"
        assert row["api_call_count"] == 2
    finally:
        db.close()


def test_dispatch_bills_original_session_after_parent_advances(tmp_path):
    import run_agent
    parent = _make_agent_stub(run_agent.AIAgent)
    db = SessionDB(tmp_path / "state.db")
    try:
        db.create_session("sess-123", source="cli")
        db.create_session("next-session", source="cli")
        parent._session_db = db
        captured = {}
        recorder = _make_recorder_class(captured, ())
        original_run = recorder.run_conversation

        def run(self, **kwargs):
            self.session_api_calls = 2
            self.session_input_tokens = 100
            self.session_actual_cost_usd = 0.12
            self.session_cost_status = "reported"
            self.session_cost_source = "provider"
            return original_run(self, **kwargs)

        with patch.object(run_agent, "AIAgent", recorder), patch.object(recorder, "run_conversation", run):
            target, _ = br.spawn_background_review_thread(
                parent, [{"role": "user", "content": "fixture"}], review_skills=True)
            parent.session_id = "next-session"
            target()
        rows = db._read_all("SELECT * FROM session_model_usage")
        assert len(rows) == 1
        assert rows[0]["session_id"] == "sess-123"
        assert rows[0]["api_call_count"] == 2
        assert rows[0]["actual_cost_usd"] == 0.12
        assert rows[0]["cost_source"] == "provider"
    finally:
        db.close()
