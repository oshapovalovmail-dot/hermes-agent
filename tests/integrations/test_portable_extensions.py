"""Portable extension contracts; all state/identities are synthetic and disposable."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2] / "integrations" / "local-plugins"


def load(name):
    path = ROOT / name / "__init__.py"
    spec = importlib.util.spec_from_file_location("portable_" + name.replace("-", "_"), path,
                                                  submodule_search_locations=[str(path.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Context:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.calls = []

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def __getattr__(self, name):
        if name.startswith("register_"):
            return lambda *args, **kw: self.calls.append((name, args, kw))
        raise AttributeError(name)


@pytest.mark.parametrize("name", ["meeting-context", "project-memory-bank", "reminder-actions", "qyp-delegate", "web-yandex"])
def test_disabled_plugins_do_not_register_or_write(name, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    before = set(tmp_path.rglob("*"))
    plugin = load(name)
    ctx = Context()
    plugin.register(ctx)
    assert ctx.calls == []
    assert set(tmp_path.rglob("*")) == before


def test_bank_initialize_bind_checkpoint_and_agreement(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    plugin = load("project-memory-bank")
    project = tmp_path / "project"
    project.mkdir()
    bank = plugin.bank.initialize(str(project))
    assert plugin.bank.bound("session") is None
    plugin.bank.bind("session", str(project))
    assert plugin.bank.bound("session") == bank
    (bank / "progress.md").write_text("# Progress\n\n### Synthetic checkpoint\nBuilt a sample.\n")
    handoff = plugin.bank.handoff(bank, "session")
    assert "Synthetic checkpoint" in handoff.read_text()
    assert plugin.bank.agree(bank, "Use bounded tests", "operator-confirmed", None)
    assert "Use bounded tests" in (bank / "agreements.md").read_text()
    assert not (project / ".memory-bank").exists()


def test_bank_rejects_roots_and_symlink_state(tmp_path, monkeypatch):
    plugin = load("project-memory-bank")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile"))
    for root in ["/", str(tmp_path)]:
        with pytest.raises(ValueError):
            plugin.bank.initialize(root)
    home = tmp_path / "profile"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / "project-memory").symlink_to(outside, target_is_directory=True)
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError):
        plugin.bank.initialize(str(project))
    assert not list(outside.iterdir())


def test_bank_rejects_symlink_ancestor_and_report_without_evidence(tmp_path, monkeypatch):
    plugin = load("project-memory-bank")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile"))
    project = tmp_path / "project"
    project.mkdir()
    bank = plugin.bank.initialize(str(project))
    outside = tmp_path / "outside"
    outside.mkdir()
    (bank / "notes").rmdir()
    (bank / "notes").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        plugin.bank.write(bank / "notes" / "leak.md", "no", bank)
    assert not plugin.bank.verify_report({"checks": [{"id": "x", "result": "pass"}]})["passed"]


def test_meeting_explicit_binding_and_path_boundary(tmp_path, monkeypatch):
    plugin = load("meeting-context")
    root = tmp_path / "transcripts"
    root.mkdir()
    transcript = root / "synthetic.md"
    transcript.write_text("synthetic meeting data")
    mapping = tmp_path / "topics.json"
    mapping.write_text(json.dumps({"threads": {"sample-topic": {"meeting_id": "synthetic", "transcript_path": str(transcript)}}}))
    plugin.register(Context({"enabled": True, "transcripts_root": str(root), "bindings_path": str(mapping)}))
    monkeypatch.setattr(plugin, "_session_row", lambda _: {"source": "telegram", "thread_id": "sample-topic"})
    request = {"messages": [{"role": "system", "content": "base"}, {"role": "user", "content": "decision?"}]}
    result = plugin.inject_meeting_context(request=request, session_id="sample")
    assert str(transcript) in result["request"]["messages"][1]["content"]
    assert request["messages"][1]["content"] == "decision?"
    assert plugin._safe_transcript_path(str(tmp_path / "escape.md")) is None
    (root / "escape.md").symlink_to(tmp_path / "outside.md")
    assert plugin._safe_transcript_path(str(root / "escape.md")) is None


def test_real_discovery_from_fresh_home(tmp_path, monkeypatch):
    import hermes_yaml as yaml
    from hermes_cli import plugins as api
    home = tmp_path / "profile"
    plugins = home / "plugins"
    plugins.mkdir(parents=True)
    for name in ["meeting-context", "project-memory-bank", "reminder-actions", "qyp-delegate", "web-yandex"]:
        shutil.copytree(ROOT / name, plugins / name, ignore=shutil.ignore_patterns("__pycache__"))
    entries = {
        "project-memory-bank": {"settings": {"enabled": True}},
        "meeting-context": {"settings": {"enabled": True, "bindings_path": str(tmp_path / "topics.json"), "transcripts_root": str(tmp_path / "transcripts")}},
        "reminder-actions": {"settings": {"enabled": True, "state_root": str(tmp_path / "reminders"), "route": {"owner_id": "owner", "chat_id": "inbox", "thread_id": "topic"}, "job_ids": ["synthetic-job"]}},
        "qyp-delegate": {"settings": {"enabled": True, "host": "worker.example.invalid", "remote_home": "/srv/worker", "remote_hermes_home": "/srv/worker/profile", "remote_hermes": "/srv/worker/bin/hermes", "default_workdir": "/srv/worker/project", "allowed_roots": ["/srv/worker/project"]}},
        "web-yandex": {"settings": {"enabled": True}},
    }
    (home / "config.yaml").write_text(yaml.safe_dump({"plugins": {"enabled": list(entries), "entries": entries}}))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    empty = tmp_path / "bundled"
    empty.mkdir()
    monkeypatch.setattr(api, "get_bundled_plugins_dir", lambda: empty)
    manager = api.PluginManager()
    manager.discover_and_load()
    for name in [p.name for p in plugins.iterdir()]:
        state = manager._plugins[name]
        assert state.enabled, (name, state.error)
        assert state.error is None, (name, state.error)
    hints = manager.invoke_hook("pre_llm_call", session_id="synthetic-session")
    assert any("bind only an explicit project" in str(hint) for hint in hints)
    assert manager.has_middleware("llm_request")
    assert manager.invoke_middleware("llm_request", request={"messages": []}, session_id="unbound") == []
    assert not (home / "project-memory").exists()
    assert not (tmp_path / "reminders").exists()
    for name in list(manager._plugins):
        manager.unload(name)


def test_qyp_disabled_refuses_before_any_process(tmp_path, monkeypatch):
    plugin = load("qyp-delegate")
    monkeypatch.setattr(plugin.qyp_delegate.subprocess, "run", Mock(side_effect=AssertionError("no process")))
    result = json.loads(plugin.qyp_delegate.handle_delegate_qyp({"goal": "not executed"}, jobs_root=tmp_path / "jobs"))
    assert not result["success"]
    assert not (tmp_path / "jobs").exists()


def test_qyp_configuration_and_workdir_restrictions(tmp_path, monkeypatch):
    plugin = load("qyp-delegate")
    settings = {"enabled": True, "host": "worker.example.invalid", "remote_home": "/srv/worker", "remote_hermes_home": "/srv/worker/profile", "remote_hermes": "/srv/worker/bin/hermes", "default_workdir": "/srv/worker/project", "allowed_roots": ["/srv/worker/project"]}
    monkeypatch.setattr(plugin.qyp_delegate, "_settings", lambda: settings)
    assert plugin.qyp_delegate.validate_workdir("/srv/worker/project/src") == "/srv/worker/project/src"
    for raw in ["/", "/srv/worker", "/srv/worker/other", "/srv/worker/project/../other", "relative"]:
        with pytest.raises(ValueError):
            plugin.qyp_delegate.validate_workdir(raw)
    assert plugin.qyp_delegate._ssh_prefix()[-1] == "worker.example.invalid"


def test_reminder_store_rejects_symlink_root_and_database(tmp_path):
    plugin = load("reminder-actions")
    from importlib import import_module
    store_module = import_module(plugin.__name__ + ".watch_state")
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        store_module.Store(linked)
    root = tmp_path / "store"
    root.mkdir()
    (root / "watch.sqlite3").symlink_to(outside / "db")
    with pytest.raises(ValueError):
        store_module.Store(root)
    assert not list(outside.iterdir())


def test_reminder_controls_identity_replay_and_draft_admission(tmp_path):
    plugin = load("reminder-actions")
    from importlib import import_module
    state = import_module(plugin.__name__ + ".watch_state")
    controls = plugin.controls
    store = state.Store(tmp_path / "store", jobs=["synthetic-job"])
    try:
        route = {"owner_id": "owner", "chat_id": "inbox", "thread_id": "topic"}
        item = {"key": "synthetic-question", "source": "telegram", "chat": {"id": 1, "name": "Synthetic"},
                "message_id": 1, "reason": "Sample question", "action": "Draft only", "status": "open"}
        with store.db:
            store.put("buttons_enabled", route)
            store.put("followups", {item["key"]: item})
            content = controls.publish(store, "Synthetic reminder", [item["key"]], "synthetic-job")
        with pytest.raises(ValueError):
            controls.lookup(store, content, "wrong-job", "inbox", "topic")
        with pytest.raises(ValueError):
            controls.lookup(store, content, "synthetic-job", "elsewhere", "topic")
        delivery = controls.lookup(store, content, "synthetic-job", "inbox", "topic")
        token = delivery["cards"][0]["token"]
        controls.mark_sent(store, token, [1], "bot")
        identity = dict(actor_id="owner", chat_id="inbox", thread_id="topic", message_id=1, bot_id="bot")
        for field in identity:
            wrong = identity | {field: "not-authorized"}
            with pytest.raises(ValueError):
                controls.operate(store, "d", token, **wrong)
        assert controls.operate(store, "d", token, **identity)["status"] == "draft"
        assert controls.operate(store, "d", token, **identity)["status"] == "already_requested"
        controls.draft_admitted(store, item["key"], False)
        assert controls.operate(store, "d", token, **identity)["status"] == "draft"
        controls.draft_admitted(store, item["key"], True)
        assert controls.operate(store, "c", token, **identity)["status"] == "closed"
        assert controls.operate(store, "c", token, **identity)["status"] == "already_closed"
        assert controls.lookup(store, content, "synthetic-job", "inbox", "topic")["cards"] == []
    finally:
        store.db.close()


def test_reminder_registers_native_adapter_only_with_explicit_config(tmp_path):
    from gateway.config import PlatformConfig
    plugin = load("reminder-actions")
    with pytest.raises(ValueError):
        plugin.register(Context({"enabled": True}))
    ctx = Context({"enabled": True, "state_root": str(tmp_path / "store"),
                   "route": {"owner_id": "owner", "chat_id": "inbox", "thread_id": "topic"},
                   "job_ids": ["synthetic-job"]})
    plugin.register(ctx)
    entry = next(kw for method, _, kw in ctx.calls if method == "register_platform")
    assert entry["name"] == "telegram"
    assert not entry.get("trusted_inbound")
    adapter = entry["adapter_factory"](PlatformConfig())
    assert adapter.reminder_route["chat_id"] == "inbox"
    assert not (tmp_path / "store").exists()


def test_qyp_physical_symlink_escape_rejected_without_ssh(tmp_path, monkeypatch):
    import subprocess
    plugin = load("qyp-delegate")
    allowed = tmp_path / "project"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (allowed / "escape").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(plugin.qyp_delegate, "_settings", lambda: {"allowed_roots": [str(allowed)]})
    for path, expected in [(allowed, 0), (allowed / "escape", 1)]:
        result = subprocess.run(["bash", "-c", plugin.qyp_delegate._remote_cd(str(path))], capture_output=True, check=False, timeout=3)
        assert result.returncode == expected


def test_bank_tampered_runtime_fails_before_script_execution(tmp_path, monkeypatch):
    plugin = load("project-memory-bank")
    runtime = tmp_path / "runtime"
    shutil.copytree(plugin.bank.UPSTREAM, runtime, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(plugin.bank, "UPSTREAM", runtime)
    (runtime / "scripts" / "mb-handoff.sh").write_text("exit 99")
    monkeypatch.setattr(plugin.bank.subprocess, "run", Mock(side_effect=AssertionError("must not execute")))
    with pytest.raises(ValueError, match="integrity mismatch"):
        plugin.bank.handoff(tmp_path / "not-opened")


def test_qyp_symlink_job_store_is_refused(tmp_path):
    plugin = load("qyp-delegate")
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "jobs"
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        plugin.qyp_delegate._write_json_atomic(root / "sample.json", {"sample": True})
    assert not list(outside.iterdir())


def test_qyp_background_spec_never_serializes_inherited_private_environment(tmp_path, monkeypatch):
    from types import SimpleNamespace
    plugin = load("qyp-delegate")
    settings = {"enabled": True, "host": "worker.example.invalid", "remote_home": "/srv/worker", "remote_hermes_home": "/srv/worker/profile", "remote_hermes": "/srv/worker/bin/hermes", "default_workdir": "/srv/worker/project", "allowed_roots": ["/srv/worker/project"]}
    monkeypatch.setattr(plugin.qyp_delegate, "_settings", lambda: settings)
    monkeypatch.setenv("SYNTHETIC_PRIVATE_SETTING", "not-for-job-artifacts")
    spawn = Mock(return_value=SimpleNamespace(pid=1))
    monkeypatch.setattr(plugin.qyp_delegate.subprocess, "Popen", spawn)
    result = json.loads(plugin.qyp_delegate.handle_delegate_qyp({"goal": "Synthetic dry run", "wait": False}, jobs_root=tmp_path / "jobs"))
    assert result["success"]
    spec = json.loads((tmp_path / "jobs" / result["job_id"] / "spec.json").read_text())
    assert "SYNTHETIC_PRIVATE_SETTING" not in spec["env"]
    assert "not-for-job-artifacts" not in json.dumps(spec)
    spawn.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["connect", "send"])
async def test_reminder_profile_resolution_does_not_block_loop(tmp_path, monkeypatch, operation):
    import threading
    from gateway.config import PlatformConfig
    from importlib import import_module

    plugin = load("reminder-actions")
    module = import_module(plugin.__name__ + ".adapter")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "original"))
    adapter = module.ReminderAdapter(PlatformConfig(), root=tmp_path / "store", route={}, jobs=[])
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "other"))
    resolve = Path.resolve
    loop_thread = threading.get_ident()

    def nonblocking_resolve(path, *args, **kwargs):
        assert threading.get_ident() != loop_thread, "filesystem resolution must run off-loop"
        return resolve(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", nonblocking_resolve)
        if operation == "connect":
            assert await adapter.connect() is False
        else:
            result = await adapter.send("inbox", "synthetic")
            assert not result.success
            assert result.error == "reminder_profile_mismatch"
