"""Independent-review counterexamples, using owned files and fake transport only."""
import importlib
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2] / "integrations/memory-stack"


@pytest.fixture
def installer(monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location("stack_review_regression", HERE / "install.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("documents, expected", [
    (["probe-canary prefers cobalt blue."], True),
    (["Project probe-canary permanently prefers cobalt blue."], True),
    (["probe-canary has chosen cobalt blue."], True),
    (["probe-canary does NOT prefer cobalt blue; prefers crimson red."], False),
    (["probe-canary never prefers cobalt blue."], False),
    (["probe-canary prefers crimson red, not cobalt blue."], False),
    (["probe-canary prefers crimson red.", "another-project prefers cobalt blue."], False),
    (["probe-canary", "I prefer cobalt blue."], False),
    (["A different project prefers cobalt blue; its neighbor is probe-canary."], False),
    (["probe-canary prefers cobalt blue.", "probe-canary does not prefer cobalt blue."], False),
    (["probe-canary prefers cobalt blue. This statement is false."], False),
    (["probe-canary prefers cobalt blue. This preference was revoked."], False),
    (["probe-canary prefers cobalt blue.", "probe-canary prefers crimson red."], False),
    (["probe-canary prefers cobalt blue. Project probe-canary has chosen crimson red instead."], False),
])
def test_fact_oracle_preserves_subject_polarity_and_document_boundary(installer, documents, expected):
    checks = importlib.import_module("stack_checks")
    assert checks.semantic_match(documents, "probe-canary") is expected


@pytest.mark.parametrize("area", ["build/frida", "hermes-home/plugins/openviking"])
def test_added_executable_inputs_are_not_admitted(installer, tmp_path, area):
    directory = tmp_path / area
    directory.mkdir(parents=True)
    (directory / "original.py").write_text("original")
    (tmp_path / "compose.json").write_text("{}")
    state = {"prepared": True, "inventory": installer.inventory(tmp_path)}
    (directory / "added.py").write_text("unreviewed")
    with pytest.raises(ValueError, match="inventory|snapshot"):
        installer.verify_inventory(tmp_path, state)


@pytest.mark.parametrize("provider, directory", [("openviking", "openviking"), ("honcho", "postgres"), ("honcho", "redis")])
def test_mutable_data_bind_cannot_be_redirected(installer, tmp_path, provider, directory):
    root = tmp_path / "owned"
    data = root / "data"
    data.mkdir(parents=True)
    for name in ("postgres", "redis", "openviking"):
        if name != directory:
            (data / name).mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (data / directory).symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        installer.verify_writable_binds(root, {"provider": provider})
    assert list(foreign.iterdir()) == []


def test_openviking_reads_message_context_not_session_metadata(installer, monkeypatch):
    checks = importlib.import_module("stack_checks")
    message = ""

    def http(base, path, data=None, **kwargs):
        nonlocal message
        if path == "/api/v1/sessions":
            assert data is not None
            return {"result": {"session_id": data["session_id"]}}
        if path.endswith("/messages"):
            assert data is not None
            message = data["content"]
            return {"result": {"accepted": True}}
        if path.endswith("/context"):
            return {"result": {"messages": [{"role": "user", "parts": [{"type": "text", "text": message}]}]}}
        return {"result": {"message_count": 1}}

    monkeypatch.setattr(checks, "request", http)
    assert checks.check_openviking("http://fixture.invalid", storage_only=True, timeout=1)["passed"]


def test_profile_links_exact_external_connection_and_identity(installer, tmp_path):
    import json
    import os
    render = importlib.import_module("stack_render")
    key = "synthetic-own-key"
    with os.fdopen(os.open(tmp_path / "openviking.key", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        stream.write(key)
    state = {"provider": "openviking", "project": "own-project", "ports": {"openviking": 19444}}
    render.profile(tmp_path, state)
    home = tmp_path / "hermes-home"
    settings = json.loads((home / "config.yaml").read_text())["memory"]["openviking"]
    assert settings["use_ovcli_config"] is True
    assert settings["deployment"] == "external-compose"
    assert settings["ovcli_config_path"] == str(home / "ovcli.conf")
    cli = json.loads((home / "ovcli.conf").read_text())
    assert cli["root_api_key"] == cli["api_key"] == key
    assert cli["actor_peer_id"] == state["project"]
    assert cli["user"] == state["project"]
    assert cli["account"] == "default"


@pytest.mark.parametrize("key", ["llm.key", "postgres.key", "openviking.key"])
def test_secret_binds_cannot_be_redirected_to_foreign_files(installer, tmp_path, key):
    import os
    root = tmp_path / "owned"
    for name in ("postgres", "redis", "openviking"):
        (root / "data" / name).mkdir(parents=True)
    foreign = tmp_path / "foreign.key"
    with os.fdopen(os.open(foreign, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        stream.write("synthetic-foreign-key")
    for name in ("llm.key", "postgres.key", "openviking.key"):
        if name == key:
            (root / name).symlink_to(foreign)
        else:
            with os.fdopen(os.open(root / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
                stream.write("synthetic-own-key")
    with pytest.raises(ValueError, match="symlink"):
        installer.verify_writable_binds(root, {"provider": "both"})
    assert foreign.read_text() == "synthetic-foreign-key"


@pytest.mark.parametrize("kind", ["metadata", "assistant", "part_metadata"])
def test_openviking_storage_requires_actual_user_message(installer, monkeypatch, kind):
    checks = importlib.import_module("stack_checks")
    text = ""

    def http(base, path, data=None, **kwargs):
        nonlocal text
        if path == "/api/v1/sessions":
            assert data is not None
            return {"result": {"session_id": data["session_id"]}}
        if path.endswith("/messages"):
            assert data is not None
            text = data["content"]
            return {"result": {}}
        contexts = {
            "metadata": {"messages": [], "metadata": {"last_request": text}},
            "assistant": {"messages": [{"role": "assistant", "parts": [{"type": "text", "text": text}]}]},
            "part_metadata": {"messages": [{"role": "user", "parts": [{"type": "image", "metadata": {"text": text}}]}]},
        }
        return {"result": contexts[kind]}

    monkeypatch.setattr(checks, "request", http)
    with pytest.raises(RuntimeError, match="readback"):
        checks.check_openviking("http://fixture.invalid", storage_only=True, timeout=1)
