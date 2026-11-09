"""Behavioral boundaries for the optional fresh-root memory-stack controller."""
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parents[2] / "integrations" / "memory-stack"


@pytest.fixture
def paths(monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location("stack_paths", HERE / "stack_paths.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("provider,expected", [
    ("honcho", ["honcho"]), ("openviking", ["openviking"]),
    ("both", ["honcho", "openviking"]),
])
def test_explicit_provider_selection(paths, provider, expected):
    assert paths.provider_names(provider) == expected


def test_unknown_provider_is_not_silently_both(paths):
    with pytest.raises(ValueError):
        paths.provider_names("unknown")


def test_fresh_root_is_private_and_bound_to_absolute_location(paths, tmp_path):
    root = tmp_path / "new"
    state = paths.create_root(root, "honcho")
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert state["root"] == str(root)
    assert state["provider"] == "honcho"
    assert state["project"].startswith("hermes-memory-")
    assert paths.load_root(root)["project"] == state["project"]


def test_existing_root_is_never_merged(paths, tmp_path):
    keep = tmp_path / "keep"
    keep.write_text("unchanged")
    with pytest.raises(FileExistsError):
        paths.create_root(tmp_path, "both")
    assert keep.read_text() == "unchanged"


def test_dangling_symlink_root_is_rejected(paths, tmp_path):
    root = tmp_path / "link"
    root.symlink_to(tmp_path / "absent", target_is_directory=True)
    with pytest.raises((ValueError, FileExistsError)):
        paths.create_root(root, "honcho")
    assert not (tmp_path / "absent").exists()


def test_symlink_parent_is_rejected(paths, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    parent = tmp_path / "alias"
    parent.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        paths.create_root(parent / "new", "openviking")
    assert not (real / "new").exists()


def test_relative_root_requires_explicit_scope(paths):
    with pytest.raises(ValueError):
        paths.create_root(Path("relative"), "honcho")


def test_ownership_marker_cannot_be_moved_to_another_root(paths, tmp_path):
    source = tmp_path / "source"
    paths.create_root(source, "both")
    other = tmp_path / "other"
    source.rename(other)
    with pytest.raises(ValueError):
        paths.load_root(other)


def test_private_key_source_is_unchanged_and_not_logged(paths, tmp_path):
    key = tmp_path / "key"
    key.write_text("fixture-value\n")
    key.chmod(0o600)
    assert paths.read_key(key) == "fixture-value"
    assert key.read_text() == "fixture-value\n"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600


@pytest.mark.parametrize("kind", ["symlink", "public", "empty", "multiline"])
def test_invalid_key_file_fails_closed(paths, tmp_path, kind):
    key = tmp_path / "key"
    key.write_text("fixture-value")
    key.chmod(0o600)
    if kind == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(key)
        key = alias
    elif kind == "public":
        key.chmod(0o644)
    elif kind == "empty":
        key.write_text(" \n")
    else:
        key.write_text("first\nsecond")
    with pytest.raises(ValueError):
        paths.read_key(key)


@pytest.mark.parametrize("ports", [
    {"frida": 8001, "honcho": 8001}, {"frida": 0}, {"frida": 65536},
    {"frida": 80}, {"frida": True},
])
def test_ports_are_explicit_distinct_and_unprivileged(paths, ports):
    with pytest.raises(ValueError):
        paths.validate_ports(ports)


def test_dependency_lock_patch_is_a_complete_parseable_git_patch(tmp_path):
    result = subprocess.run(["git", "apply", "--numstat", str(HERE / "honcho-lock.patch")],
                            capture_output=True, text=True, timeout=15, cwd=tmp_path, check=False)
    assert result.returncode == 0, result.stderr
    assert "uv.lock" in result.stdout


def test_internal_source_symlinks_are_bound_without_following_outside_root(paths, tmp_path):
    spec = importlib.util.spec_from_file_location("stack_installer_case", HERE / "install.py")
    assert spec is not None and spec.loader is not None
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    (tmp_path / "build/honcho").mkdir(parents=True)
    (tmp_path / "build/honcho/CLAUDE.md").write_text("public upstream instructions")
    (tmp_path / "build/honcho/AGENTS.md").symlink_to("CLAUDE.md")
    (tmp_path / "compose.json").write_text("{}")
    result = installer.inventory(tmp_path)
    assert result["build/honcho/AGENTS.md"]["symlink"] == "CLAUDE.md"
    installer.verify_inventory(tmp_path, {"prepared": True, "inventory": result})
    (tmp_path / "build/honcho/AGENTS.md").unlink()
    (tmp_path / "build/honcho/AGENTS.md").symlink_to("../../../outside")
    with pytest.raises(ValueError):
        installer.inventory(tmp_path)


def test_root_cannot_be_created_inside_a_git_worktree(paths, tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").write_text("gitdir: /irrelevant/metadata\n")
    with pytest.raises(ValueError):
        paths.create_root(repository / "runtime", "both")
    assert not (repository / "runtime").exists()


@pytest.mark.parametrize("value,expected", [
    ([{"content": "Project probe-canary permanently prefers cobalt blue."}], True),
    ([{"content": "cobalt blue"}, {"content": "probe-canary"}], False),
    ([{"content": "likes red", "metadata": {"query": "cobalt probe-canary"}}], False),
    ([{"content": "unrelated", "uri": "viking://user/probe-canary/cobalt"}], False),
    ([{"content": "cobalt blue"}], False),
])
def test_derived_evidence_must_contain_fact_and_canary_not_request_metadata(paths, value, expected):
    checks = importlib.import_module("stack_checks")
    assert checks.semantic_match(value, "probe-canary") is expected


def test_model_assets_are_revalidated_after_preparation(paths, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("stack_installer_model_case", HERE / "install.py")
    assert spec is not None and spec.loader is not None
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    import hashlib
    model = tmp_path / "model"
    model.mkdir()
    artifact = model / "weights"
    artifact.write_bytes(b"before")
    monkeypatch.setattr(installer, "PINS", {"assets": {"weights": {
        "size": 6, "sha256": hashlib.sha256(b"before").hexdigest()}}})
    installer.verify_model_assets(tmp_path)
    artifact.write_bytes(b"change")
    with pytest.raises(ValueError):
        installer.verify_model_assets(tmp_path)


def test_marker_contains_no_credential(paths, tmp_path):
    root = tmp_path / "new"
    state = paths.create_root(root, "both")
    assert "api_key" not in state
    assert json.loads((root / "state.json").read_text())["root"] == str(root)
