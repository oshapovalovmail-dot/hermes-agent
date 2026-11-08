"""Reusable prefix boundaries and real transport routing contracts."""
from types import SimpleNamespace

import pytest

from agent import system_prompt
from agent.transports.chat_completions import ChatCompletionsTransport
from agent.transports.codex import ResponsesApiTransport
from providers.base import ProviderProfile


def _agent():
    return SimpleNamespace(
        load_soul_identity=False, skip_context_files=True, valid_tool_names=set(),
        _task_completion_guidance=False, _tool_use_enforcement=False, _environment_probe=False,
        _bot_mode_protocol=False, _kanban_worker_guidance="", _memory_store=None,
        _memory_manager=None, model="gpt-5.6", provider="openai", platform="cli",
        pass_session_id=False, session_id="synthetic-session", _emit_diagnostic_status=lambda *a: None,
    )


def test_reusable_prefix_contains_catalog_and_project_context_not_runtime(monkeypatch):
    monkeypatch.setattr(system_prompt, "_skills_prompt", lambda a: "CATALOG_SENTINEL")
    monkeypatch.setattr(system_prompt, "_memory_parts", lambda a: ["MEMORY_SENTINEL"])
    monkeypatch.setattr(system_prompt, "_post_workspace_parts", lambda a: ["RUNTIME_SENTINEL"])
    monkeypatch.setattr(system_prompt, "_coding_parts", lambda a: (["BRIEF"], ["WORKSPACE"], ["TRAILING"]))
    agent = _agent()
    parts = system_prompt.build_system_prompt_parts(agent, "PROJECT_SENTINEL")
    assert "CATALOG_SENTINEL" in parts["stable"]
    assert "RUNTIME_SENTINEL" not in parts["stable"] + parts["context"]
    prompt = system_prompt.build_system_prompt(agent, "PROJECT_SENTINEL")
    assert agent._cached_system_prompt_static == "\n\n".join((parts["stable"], parts["context"]))
    assert prompt.startswith(agent._cached_system_prompt_static)
    assert "MEMORY_SENTINEL" not in agent._cached_system_prompt_static


@pytest.mark.parametrize("profile", [False, True])
def test_chat_transport_shares_family_across_sessions_and_volatile_tails(profile):
    transport = ChatCompletionsTransport()
    params = dict(stable_prompt_prefix="shared", cache_isolation_scope="piso_test", api_mode="chat_completions")
    if profile:
        params["provider_profile"] = ProviderProfile(name="synthetic-openai", supports_prompt_cache_key=True)
    results = [transport.build_kwargs(
        model="gpt-5.6", messages=[{"role": "system", "content": "shared\n\n" + tail}],
        session_id=sid, base_url="https://api.openai.com/v1", **params,
    ) for sid, tail in [("first", "memory A"), ("second", "memory B")]]
    assert results[0]["prompt_cache_key"] == results[1]["prompt_cache_key"]


def test_responses_uses_normalized_overridden_wire_model():
    transport = ResponsesApiTransport()
    params = dict(messages=[{"role": "system", "content": "shared"}], stable_prompt_prefix="shared",
                  cache_isolation_scope="piso_test", api_mode="codex_responses")
    first = transport.build_kwargs(model="gpt-5.6-sol-900k", **params)
    second = transport.build_kwargs(model="unrelated", request_overrides={"model": "gpt-5.6-sol-900k"}, **params)
    assert first["model"] == second["model"] == "gpt-5.6-sol"
    assert first["prompt_cache_key"] == second["prompt_cache_key"]


def test_unserializable_tools_fall_back_without_raising():
    result = ResponsesApiTransport().build_kwargs(
        model="gpt-5.6", messages=[{"role": "system", "content": "shared"}],
        tools=[{"type": "function", "function": {"name": "lookup", "parameters": {"bad": object()}}}],
        session_id="fallback-session", stable_prompt_prefix="shared",
        cache_isolation_scope="piso_test", api_mode="codex_responses",
    )
    assert result["prompt_cache_key"]


@pytest.mark.parametrize("platform,user_id,available", [
    ("telegram", None, False), ("", "alice", False), ("telegram", "alice", True), ("cli", None, True),
])
def test_family_scope_requires_gateway_principal(platform, user_id, available):
    from agent.prompt_cache_scope import resolve_prompt_cache_isolation_scope
    agent = SimpleNamespace(platform=platform, _user_id=user_id)
    assert bool(resolve_prompt_cache_isolation_scope(agent)) is available


def test_profile_scoped_catalog_and_family_switch_a_b_a(tmp_path):
    from agent.prompt_builder import build_skills_system_prompt
    from agent.prompt_cache_scope import resolve_prompt_cache_isolation_scope
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    prompts, scopes = [], []
    for label in ("a", "b"):
        home = tmp_path / label
        skill = home / "skills" / f"only-{label}"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: only-{label}\ndescription: Only {label}\n---\nbody\n")
        (home / "config.yaml").write_text("skills:\n  external_dirs: []\n")
    for label in ("a", "b", "a"):
        token = set_hermes_home_override(str(tmp_path / label))
        try:
            prompts.append(build_skills_system_prompt())
            scopes.append(resolve_prompt_cache_isolation_scope(SimpleNamespace(platform="cli")))
        finally:
            reset_hermes_home_override(token)
    assert prompts[0] == prompts[2] and prompts[0] != prompts[1]
    assert "only-b" not in prompts[0] and "only-a" not in prompts[1]
    assert scopes[0] == scopes[2] and scopes[0] != scopes[1]


@pytest.mark.parametrize("mode", ["codex_responses", "chat_completions"])
def test_request_helper_passes_family_identity_to_real_transport(monkeypatch, mode):
    from tests.agent.test_run_agent_codex_responses import _build_agent
    agent = _build_agent(monkeypatch)
    agent.platform = "cli"
    agent.api_mode = mode
    if mode == "chat_completions":
        agent.base_url = "https://api.openai.com/v1"
        agent.provider = "openai"
    agent._cached_system_prompt_static = "shared"
    keys = []
    for sid, tail in (("first", "memory A"), ("second", "memory B")):
        agent.session_id = sid
        keys.append(agent._build_api_kwargs([{"role": "system", "content": "shared\n\n" + tail}])["prompt_cache_key"])
    assert keys[0] == keys[1]


@pytest.mark.parametrize("transport,mode", [(ResponsesApiTransport, "codex_responses"),
                                           (ChatCompletionsTransport, "chat_completions")])
def test_explicit_key_wins_over_family(transport, mode):
    result = transport().build_kwargs(
        model="gpt-5.6-sol", messages=[{"role": "system", "content": "shared"}],
        base_url="https://api.openai.com/v1", stable_prompt_prefix="shared",
        cache_isolation_scope="piso_test", api_mode=mode,
        request_overrides={"prompt_cache_key": "explicit-key"},
    )
    assert result["prompt_cache_key"] == "explicit-key"


def test_responses_endpoint_optout_and_xai_routing_still_win(monkeypatch):
    params = dict(model="gpt-5.6-sol", messages=[{"role": "system", "content": "shared"}],
                  stable_prompt_prefix="shared", cache_isolation_scope="piso_test", api_mode="codex_responses")
    binding = ProviderProfile(name="synthetic-responses", responses_prompt_cache_key=False)
    monkeypatch.setattr("providers.profile_for_host", lambda url: binding if url == "https://responses.example.test" else None)
    opted_out = ResponsesApiTransport().build_kwargs(base_url="https://responses.example.test", **params)
    assert "prompt_cache_key" not in opted_out
    xai = ResponsesApiTransport().build_kwargs(base_url="https://api.x.ai/v1", is_xai_responses=True, **params)
    assert "prompt_cache_key" not in xai


def test_platform_and_trusted_tenant_are_isolation_axes(tmp_path):
    from agent.prompt_cache_scope import resolve_prompt_cache_isolation_scope
    def scope(platform, tenant):
        return resolve_prompt_cache_isolation_scope(SimpleNamespace(
            platform=platform, _user_id="alice", _tenant_id=tenant,
            _session_db=SimpleNamespace(db_path=tmp_path / "state.db")))
    assert scope("telegram", "tenant-a") != scope("discord", "tenant-a")
    assert scope("telegram", "tenant-a") != scope("telegram", "tenant-b")
