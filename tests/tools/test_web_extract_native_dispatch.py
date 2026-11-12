"""Executable extraction and native Responses search must resolve independently.

Use the real tool/provider registries and provider methods. Only vendor I/O and
DNS are replaced; credentials and config are synthetic files in a temporary home.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def native_install(monkeypatch, tmp_path):
    from agent import web_search_registry as providers
    from plugins.web.exa import provider as exa_module
    from plugins.web.exa.provider import ExaWebSearchProvider
    from plugins.web.openai_native.provider import OpenAINativeWebSearchProvider
    from tools import web_tools

    home = tmp_path / "native-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "auth.json").write_text(json.dumps({
        "providers": {"openai-codex": {"tokens": {"access_token": "fixture-native-token"}}},
    }))
    web_config = {"keyless_fallback": True}

    def configure(**values):
        web_config.clear()
        web_config.update({"keyless_fallback": True, **values})
        (home / "config.yaml").write_text("web: " + json.dumps(web_config) + "\n")

    configure()
    # Exercise real config reads, selection helpers, registry resolution and handlers.
    providers._reset_for_tests()
    native = OpenAINativeWebSearchProvider()
    exa = ExaWebSearchProvider()
    providers.register_provider(native)
    providers.register_provider(exa)
    monkeypatch.setattr(web_tools, "_ensure_web_plugins_loaded", lambda: None)
    monkeypatch.setattr(web_tools, "_ddgs_package_importable", lambda: False)
    monkeypatch.setattr(web_tools, "_is_tool_gateway_ready", lambda: False)
    monkeypatch.setattr(providers, "_keyless_preference", lambda: ("exa",))

    # Public DNS fixture: still run the production URL and website-policy gates.
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("93.184.216.34", 443)),
    ])
    native_search = Mock(wraps=native.search)
    native_extract = Mock(wraps=native.extract)
    monkeypatch.setattr(native, "search", native_search)
    monkeypatch.setattr(native, "extract", native_extract)
    vendor_calls = []

    def keyless_extract(display, name, urls, logger):
        vendor_calls.append(("keyless", name, urls))
        return [{"url": url, "title": "Fixture page", "content": "keyless extracted body"}
                for url in urls]

    monkeypatch.setattr(exa_module, "keyless_extract", keyless_extract)

    def get_contents(urls, **kwargs):
        vendor_calls.append(("paid", "exa", urls))
        return SimpleNamespace(results=[
            SimpleNamespace(url=url, title="Fixture page", text="paid extracted body")
            for url in urls
        ])

    monkeypatch.setattr(exa_module, "_get_exa_client", lambda: SimpleNamespace(get_contents=get_contents))
    yield SimpleNamespace(
        configure=configure, native=native, exa=exa, calls=vendor_calls,
        native_search=native_search, native_extract=native_extract, web_tools=web_tools,
        providers=providers,
    )
    native_search.assert_not_called()
    native_extract.assert_not_called()
    providers._reset_for_tests()


def extract():
    from tools.registry import registry
    return json.loads(registry.dispatch("web_extract", {"urls": ["https://example.com/article"]}))


def assert_native_swap():
    from agent.transports.codex import _alias_wire_tools
    from tools.registry import registry
    tools = [{"type": "function", **registry.get_schema(name)}
             for name in ("web_search", "web_extract")]
    wire, aliases = _alias_wire_tools(tools, {}, False, is_codex_backend=True)
    assert aliases == {}
    assert wire == [tools[1], {"type": "web_search"}]
    assert tools[0]["type"] == "function"  # request-local, no schema mutation


@pytest.mark.parametrize("zero_arg_backend_seam", [False, True])
def test_native_search_kept_while_registry_extract_executes_keyless(native_install, monkeypatch,
                                                                  zero_arg_backend_seam):
    install = native_install
    assert install.native.is_available()
    assert install.providers.get_active_search_provider() is install.native
    assert_native_swap()
    if zero_arg_backend_seam:
        original = install.web_tools._get_backend
        monkeypatch.setattr(install.web_tools, "_get_backend", lambda: original())
    result = extract()
    assert result.get("results", [{}])[0].get("content") == "keyless extracted body", result
    assert install.calls == [("keyless", "exa", ["https://example.com/article"])]
    assert_native_swap()


@pytest.mark.parametrize("search_pin", [None, "openai-native", "missing-search"])
def test_native_only_keyless_disabled_reports_no_extract_provider(native_install, search_pin):
    values = {"keyless_fallback": False}
    if search_pin:
        values["search_backend"] = search_pin
    native_install.configure(**values)
    assert native_install.providers.get_active_extract_provider() is None
    result = extract()
    assert "No web extract provider configured" in result.get("error", ""), result
    assert native_install.calls == []


@pytest.mark.parametrize("extract_pin", ["openai-native", "missing-extract"])
def test_explicit_extract_pin_is_strict_despite_healthy_keyless(native_install, extract_pin):
    native_install.configure(search_backend="openai-native", extract_backend=extract_pin)
    result = extract()
    assert "error" in result
    assert ("search-only" if extract_pin == "openai-native" else "no registered") in result["error"]
    assert native_install.calls == []
    assert_native_swap()


@pytest.mark.parametrize("shared", [{"backend": "openai-native"}, {"backend": "missing-shared"},
                                    {"use_gateway": True}])
def test_shared_selection_remains_strict_for_extract(native_install, shared):
    native_install.configure(**shared)
    result = extract()
    assert "error" in result, result
    assert native_install.calls == []


@pytest.mark.parametrize("search_pin", [None, "openai-native", "missing-search"])
def test_paid_extract_preferred_independently_of_search_pin(native_install, monkeypatch, search_pin):
    if search_pin:
        native_install.configure(search_backend=search_pin)
    monkeypatch.setenv("EXA_API_KEY", "fixture-paid-key")
    result = extract()
    assert result.get("results", [{}])[0].get("content") == "paid extracted body", result
    assert native_install.calls == [("paid", "exa", ["https://example.com/article"])]


def test_explicit_extract_pin_does_not_override_native_search(native_install):
    native_install.configure(extract_backend="exa")
    assert_native_swap()
    result = extract()
    assert result.get("results", [{}])[0].get("content") == "keyless extracted body", result


def test_extract_override_wins_over_search_only_shared_pin(native_install):
    native_install.configure(backend="openai-native", extract_backend="exa")
    assert_native_swap()
    result = extract()
    assert result.get("results", [{}])[0].get("content") == "keyless extracted body", result
