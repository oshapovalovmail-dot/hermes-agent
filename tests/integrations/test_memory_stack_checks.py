"""HTTP-boundary contract tests; these do not replace live backend acceptance."""
import importlib
import importlib.util
from pathlib import Path


import pytest


HERE = Path(__file__).resolve().parents[2] / "integrations/memory-stack"


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    return importlib.import_module("stack_checks")


def test_honcho_search_is_scoped_to_the_ingested_peer(checks, monkeypatch):
    identity = ""
    messages = []
    def http(base, path, data=None, **kwargs):
        nonlocal identity, messages
        if path == "/v3/workspaces":
            identity = data["id"]
        if path.endswith("/messages"):
            if data is not None:
                messages = data["messages"]
            return {"items": messages}
        if path.endswith("/messages/list"):
            return {"items": messages}
        if "/queue/status" in path:
            return {"completed_work_units": 1, "pending_work_units": 0, "in_progress_work_units": 0}
        if path.endswith("/conclusions/list"):
            return {"items": [{"id": "new-fact", "content": identity + " prefers cobalt blue."}]}
        if path.endswith("/conclusions/query"):
            assert data is not None
            assert data.get("filters") == {"observer": "synthetic-user", "observed": "synthetic-user",
                                            "session_id": identity}
            return [{"id": "new-fact", "content": identity + " prefers cobalt blue."}]
        return {}
    monkeypatch.setattr(checks, "request", http)
    assert checks.check_honcho("http://fixture.invalid", storage_only=False, timeout=1)["passed"]


@pytest.mark.parametrize("flag", ["honcho_port", "openviking_port"])
def test_explicit_zero_port_is_rejected_before_any_preparation(flag, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location("stack_port_case", HERE / "install.py")
    assert spec is not None and spec.loader is not None
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    from argparse import Namespace
    key = tmp_path / "private.key"
    key.write_text("synthetic-test-value")
    key.chmod(0o600)
    args = Namespace(provider="both", root=tmp_path / "stack", llm_base_url="https://fixture.invalid/v1", llm_model="fixture",
                     llm_api_key_file=key, frida_port=18501, honcho_port=None, openviking_port=None)
    setattr(args, flag, 0)
    def no_network(*args, **kwargs):
        raise AssertionError("port validation must happen before network or filesystem preparation")
    monkeypatch.setattr(installer, "require_free_ports", no_network)
    with pytest.raises(ValueError, match="ports must"):
        installer.prepare(args)


@pytest.mark.parametrize("kind, expected", [("derived", True), ("identifier_only", False), ("unrelated", False)])
def test_openviking_reads_content_not_search_metadata(checks, monkeypatch, kind, expected):
    identity = ""
    message = ""

    def http(base, path, data=None, *, headers=None, **_):
        nonlocal identity, message
        if path == "/api/v1/sessions":
            assert data is not None and headers is not None
            identity = data["session_id"]
            assert headers["X-OpenViking-User"] == identity
            return {"result": {"session_id": identity}}
        if path.endswith("/messages"):
            assert data is not None
            message = data["content"]
            return {"result": {}}
        if path.endswith("/commit"):
            return {"result": {"task_id": "causal-task"}}
        if path.startswith("/api/v1/tasks/"):
            return {"result": {"status": "completed", "error": None}}
        if path == "/api/v1/search/find":
            return {"result": {"memories": [{"uri": "viking://user/memories/fact.md", "abstract": identity + " prefers cobalt blue."}]}}
        if path.startswith("/api/v1/content/read?"):
            document = {"derived": identity + " has chosen cobalt blue.", "identifier_only": identity,
                        "unrelated": "An unrelated project has chosen cobalt blue."}[kind]
            return {"result": {"content": document}}
        return {"result": {"messages": [{"role": "user", "content": message}]}}

    monkeypatch.setattr(checks, "request", http)
    result = checks.check_openviking("http://fixture.invalid", storage_only=False, timeout=1)
    assert result["passed"] is expected
    assert result["task_id"] == "causal-task"


def test_openviking_nonlocal_bind_uses_own_api_key_without_leaking_it(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    render = importlib.import_module("stack_render")
    import json
    state = {"provider": "openviking", "project": "isolated-test", "ports": {"frida": 18501, "openviking": 18533}}
    render.profile(tmp_path, state)
    connection = json.loads((tmp_path / "hermes-home/ovcli.conf").read_text())
    key = (tmp_path / "openviking.key").read_text().strip()
    assert len(key) >= 32 and key != "local"
    assert connection["api_key"] == key
    assert (tmp_path / "openviking.key").stat().st_mode & 0o777 == 0o600
    template = render.ov_configuration(tmp_path, state["project"], "https://llm.invalid/v1", "fixture")
    assert template["server"]["auth_mode"] == "trusted"
    compose = render.compose_config(tmp_path, state, "https://llm.invalid/v1", "fixture", "unused")
    assert key not in json.dumps(compose) and key not in json.dumps(template)
    assert any(v["source"] == str(tmp_path / "openviking.key") and v["read_only"] for v in compose["services"]["openviking"]["volumes"])
