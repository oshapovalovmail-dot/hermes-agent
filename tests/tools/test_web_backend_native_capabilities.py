"""Native search selection must not leak into client search or extraction."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def native_web(monkeypatch, tmp_path, public_dns):
    from agent import web_search_registry as providers
    from hermes_cli.config import atomic_config_write
    from plugins.web import keyless_mcp
    from plugins.web.keenable.provider import KeenableWebSearchProvider
    from plugins.web.openai_native import provider as native
    from tools import web_tools
    from tools.registry import registry

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.config.get_env_value", lambda name: "")
    monkeypatch.setattr(native, "has_codex_credentials", lambda: True)
    monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: False)
    monkeypatch.setattr(web_tools, "_is_tool_gateway_ready", lambda: False)
    monkeypatch.setattr("tools.managed_tool_gateway.peek_nous_access_token", lambda: None)
    monkeypatch.setattr(keyless_mcp, "_ring_cursor", keyless_mcp._KEYLESS_RING.index("keenable"))

    marker = native.OpenAINativeWebSearchProvider()
    marker_search = Mock(wraps=marker.search)
    monkeypatch.setattr(marker, "search", marker_search)
    providers._reset_for_tests()

    def discover():
        providers.register_provider(marker)
        providers.register_provider(KeenableWebSearchProvider())

    monkeypatch.setattr(web_tools, "_ensure_web_plugins_loaded", discover)
    discover()
    requests = []
    url = "https://example.com/capability-fixture"
    body = "Capability fixture page body."

    def request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        assert "Authorization" not in kwargs["headers"]
        assert kwargs["headers"]["X-Keenable-Title"] == "hermes-agent"
        if endpoint.endswith("/v1/search/public"):
            data = {"results": [{"url": url, "title": "Fixture", "snippet": body}]}
        else:
            assert endpoint.endswith("/v1/fetch/public")
            assert kwargs["params"]["url"] == url
            data = {"url": url, "title": "Fixture", "content": body}
        return SimpleNamespace(status_code=200, json=lambda: data)

    monkeypatch.setattr("requests.post", lambda endpoint, **kw: request("post", endpoint, **kw))
    monkeypatch.setattr("requests.get", lambda endpoint, **kw: request("get", endpoint, **kw))

    def configure(**web):
        atomic_config_write(tmp_path / "config.yaml", {"web": {
            "cache_enabled": False,
            "provider_tier": {"exa": "paid", "parallel": "paid", "firecrawl": "paid"},
            **web,
        }})

    configure()
    yield SimpleNamespace(
        configure=configure, marker_search=marker_search, requests=requests,
        url=url, body=body, providers=providers, web_tools=web_tools,
        dispatch=lambda name, args: json.loads(registry.dispatch(name, args)),
    )
    providers._reset_for_tests()


def test_unpinned_extract_skips_native_oauth_marker(native_web):
    env = native_web
    assert env.web_tools._get_search_backend() == "openai-native"
    assert env.web_tools._get_extract_backend() == "keenable"
    result = env.dispatch("web_extract", {"urls": [env.url]})
    assert result["results"][0]["content"] == env.body
    assert result["results"][0]["url"] == env.url
    env.marker_search.assert_not_called()


def test_unpinned_python_search_does_not_attempt_native_then_rescue(native_web, caplog):
    env = native_web
    result = env.dispatch("web_search", {"query": "capability fixture"})
    assert result["success"] is True
    env.marker_search.assert_not_called()
    assert result["data"]["web"][0]["url"] == env.url
    assert "rescued_from" not in result["data"]
    assert "one-shot keyless rescue" not in caplog.text
    assert len(env.requests) == 1


@pytest.mark.parametrize("pin", ["backend", "search_backend"])
def test_explicit_native_search_pin_never_reroutes_client_search(native_web, pin):
    env = native_web
    env.configure(**{pin: "openai-native"})
    result = env.dispatch("web_search", {"query": "strict native pin"})
    assert result.get("success") is False, result
    assert "requires the Codex Responses transport" in result["error"]
    assert env.requests == []


@pytest.mark.parametrize("pin", ["backend", "extract_backend"])
def test_explicit_native_extract_pin_keeps_typed_error(native_web, pin):
    env = native_web
    env.configure(**{pin: "openai-native"})
    result = env.dispatch("web_extract", {"urls": [env.url]})
    assert result["success"] is False
    assert "search-only backend" in result["error"]
    assert "web.extract_backend" in result["error"]
    assert env.requests == []


@pytest.mark.parametrize("selection", [
    {"search_backend": "openai-native"},
    {"extract_backend": "keenable"},
    {"backend": "openai-native", "extract_backend": "keenable"},
])
def test_independent_extract_selection_does_not_disable_native_search(native_web, selection):
    env = native_web
    env.configure(**selection)
    assert env.web_tools._get_search_backend() == "openai-native"
    result = env.dispatch("web_extract", {"urls": [env.url]})
    assert result["results"][0]["content"] == env.body


@pytest.mark.parametrize("selection", [
    {"search_backend": "keenable", "extract_backend": "openai-native"},
    {"backend": "openai-native", "search_backend": "keenable"},
])
def test_client_search_pin_does_not_override_native_extract_pin(native_web, selection):
    env = native_web
    env.configure(**selection)
    assert env.web_tools._get_extract_backend() == "openai-native"
    search = env.dispatch("web_search", {"query": "independent pins"})
    assert search["success"] is True
    extraction = env.dispatch("web_extract", {"urls": [env.url]})
    assert "search-only backend" in extraction["error"]
    env.marker_search.assert_not_called()


@pytest.mark.parametrize("selection", [{}, {"backend": "openai-native"}, {"search_backend": "openai-native"}])
@pytest.mark.parametrize("is_codex", [True, False])
def test_real_responses_native_swap_is_preserved(native_web, selection, is_codex):
    from agent.transports.codex import ResponsesApiTransport

    env = native_web
    env.configure(**selection)
    tools = [{"type": "function", "function": schema} for schema in (
        env.web_tools.WEB_SEARCH_SCHEMA, env.web_tools.WEB_EXTRACT_SCHEMA,
    )]
    kwargs = ResponsesApiTransport().build_kwargs(
        model="gpt-5", messages=[{"role": "user", "content": "fixture"}],
        tools=tools, is_codex_backend=is_codex,
    )
    wire = kwargs["tools"]
    assert any(t.get("type") == "web_search" for t in wire) is is_codex
    assert any(t.get("type") == "function" and t.get("name") == "web_search" for t in wire) is not is_codex
    assert any(t.get("type") == "function" and t.get("name") == "web_extract" for t in wire)
    env.marker_search.assert_not_called()
    assert env.requests == []


@pytest.mark.parametrize("keys,expected", [
    ({"TAVILY_API_KEY", "EXA_API_KEY", "PARALLEL_API_KEY"}, "tavily"),
    ({"EXA_API_KEY", "PARALLEL_API_KEY"}, "exa"),
    ({"PARALLEL_API_KEY"}, "parallel"),
])
def test_paid_autodetect_preference_is_unchanged(native_web, monkeypatch, keys, expected):
    from plugins.web.exa.provider import ExaWebSearchProvider
    from plugins.web.parallel.provider import ParallelWebSearchProvider
    from plugins.web.tavily.provider import TavilyWebSearchProvider

    env = native_web
    monkeypatch.setattr("hermes_cli.config.get_env_value", lambda name: "fixture-key" if name in keys else "")
    for cls in (TavilyWebSearchProvider, ExaWebSearchProvider, ParallelWebSearchProvider):
        env.providers.register_provider(cls())
    assert env.web_tools._get_search_backend() == expected
    assert env.web_tools._get_extract_backend() == expected
    assert env.requests == []


def test_disabled_keyless_does_not_reroute_native_only_client(native_web):
    env = native_web
    env.configure(keyless_fallback=False)
    search = env.dispatch("web_search", {"query": "no anonymous route"})
    extraction = env.dispatch("web_extract", {"urls": [env.url]})
    assert search["success"] is False
    assert extraction["success"] is False
    assert env.web_tools._get_extract_backend() != "openai-native"
    env.marker_search.assert_not_called()
    assert env.requests == []
