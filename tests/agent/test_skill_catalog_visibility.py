"""Behavioral tests for hierarchical skill-catalog visibility."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agent import skill_commands, skill_utils
from agent.prompt_builder import build_skills_system_prompt, clear_skills_system_prompt_cache
from tools import skills_tool


def _write_skill(
    root: Path,
    name: str,
    *,
    category: str = "general",
    visibility: str | None = None,
    profiles: list[str] | None = None,
    aliases: list[str] | None = None,
    platforms: list[str] | None = None,
) -> Path:
    skill_dir = root / "skills" / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    metadata: list[str] = []
    hermes: list[str] = []
    if visibility is not None:
        hermes.append(f"    visibility: {visibility}")
    if profiles is not None:
        hermes.append("    profiles: [" + ", ".join(profiles) + "]")
    if aliases is not None:
        hermes.append("    aliases: [" + ", ".join(aliases) + "]")
    if hermes:
        metadata = ["metadata:", "  hermes:", *hermes]
    platform_lines = [f"platforms: [{', '.join(platforms)}]"] if platforms else []
    content = "\n".join(
        [
            "---",
            f"name: {name}",
            f"description: Description for {name}",
            *platform_lines,
            *metadata,
            "---",
            f"# {name}",
            "",
            f"Body for {name}.",
            "",
        ]
    )
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


def _write_project_skill(
    repo: Path,
    name: str,
    *,
    description: str,
    metadata: str | None = None,
) -> Path:
    skill_dir = repo / ".hermes" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = ["---", f"name: {name}", f"description: {description}"]
    if metadata:
        frontmatter.append(metadata)
    frontmatter.extend(["---", f"# {name}", "", f"Project body for {name}.", ""])
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(frontmatter), encoding="utf-8")
    return path


def _prompt_rows(rendered: str, name: str) -> list[str]:
    return [line for line in rendered.splitlines() if line.lstrip().startswith(f"- {name}:")]


@pytest.fixture
def catalog_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / ".hermes"
    (home / "skills").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".hermes" / "skills").mkdir(parents=True)
    config = home / "config.yaml"
    config.write_text(
        "skills:\n"
        "  external_dirs: []\n"
        "  active_profiles: [work-profile]\n"
        f"  trusted_project_dirs: ['{repo}']\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.chdir(repo)
    skill_utils._external_dirs_cache_clear()
    skill_utils._PROJECT_QUARANTINE_CACHE.clear()
    clear_skills_system_prompt_cache(clear_snapshot=True)
    yield home, repo
    clear_skills_system_prompt_cache(clear_snapshot=True)
    skill_utils._external_dirs_cache_clear()
    skill_utils._PROJECT_QUARANTINE_CACHE.clear()


def test_missing_metadata_is_global_and_active_profile_leaf_is_visible(catalog_env):
    home, _repo = catalog_env
    _write_skill(home, "always", category="core")
    _write_skill(home, "work-leaf", category="work-leaf", visibility="profile", profiles=["work-profile"])
    _write_skill(home, "other", category="other", visibility="profile", profiles=["design-profile"])
    _write_skill(home, "deferred", category="long-tail", visibility="on_demand")

    rendered = build_skills_system_prompt()

    assert "always" in rendered
    assert "work-leaf" in rendered
    assert "other" not in rendered
    assert "deferred" not in rendered


def test_trusted_project_skill_is_visible_independent_of_active_profiles(catalog_env):
    home, repo = catalog_env
    _write_skill(home, "profile-leaf", category="other", visibility="profile", profiles=["design-profile"])
    project_dir = repo / ".hermes" / "skills" / "project-leaf"
    project_dir.mkdir(parents=True)
    (project_dir / "SKILL.md").write_text(
        "---\nname: project-leaf\ndescription: project capability\n"
        "metadata:\n  hermes:\n    visibility: profile\n    profiles: [design-profile]\n---\nbody\n",
        encoding="utf-8",
    )

    rendered = build_skills_system_prompt()

    assert "project-leaf" in rendered
    assert "profile-leaf" not in rendered


def test_on_demand_project_skill_shadows_local_canonical_prompt_row(catalog_env):
    home, repo = catalog_env
    _write_skill(home, "foo")
    _write_project_skill(
        repo,
        "foo",
        description="Deferred project foo",
        metadata="metadata:\n  hermes:\n    visibility: on_demand",
    )

    rendered = build_skills_system_prompt()
    loaded = json.loads(skills_tool.skill_view("foo", preprocess=False))

    assert _prompt_rows(rendered, "foo") == []
    assert loaded["success"] is True
    assert loaded["visibility"] == "on_demand"
    assert Path(loaded["skill_dir"]).resolve() == (repo / ".hermes" / "skills" / "foo").resolve()
    assert "Project body for foo" in loaded["content"]


def test_malformed_project_skill_shadows_local_canonical_prompt_row(catalog_env):
    home, repo = catalog_env
    _write_skill(home, "foo")
    _write_project_skill(repo, "foo", description="Malformed project foo", metadata="metadata: []")

    rendered = build_skills_system_prompt()
    loaded = json.loads(skills_tool.skill_view("foo", preprocess=False))

    assert _prompt_rows(rendered, "foo") == []
    assert loaded["success"] is True
    assert loaded["metadata_valid"] is False
    assert Path(loaded["skill_dir"]).resolve() == (repo / ".hermes" / "skills" / "foo").resolve()
    assert "Project body for foo" in loaded["content"]


def test_visible_project_override_is_the_only_canonical_prompt_row(catalog_env):
    home, repo = catalog_env
    _write_skill(home, "foo")
    _write_project_skill(repo, "foo", description="Visible project foo")

    rendered = build_skills_system_prompt()
    loaded = json.loads(skills_tool.skill_view("foo", preprocess=False))

    assert _prompt_rows(rendered, "foo") == ["  - foo: [project] Visible project foo"]
    assert loaded["success"] is True
    assert loaded["metadata_valid"] is True
    assert Path(loaded["skill_dir"]).resolve() == (repo / ".hermes" / "skills" / "foo").resolve()


def test_malformed_visibility_and_profiles_fail_closed_with_warning(catalog_env, caplog):
    home, _repo = catalog_env
    _write_skill(home, "bad-visibility", visibility="sometimes")
    _write_skill(home, "empty-profiles", visibility="profile", profiles=[])

    with caplog.at_level(logging.WARNING, logger="agent.skill_utils"):
        rendered = build_skills_system_prompt()

    assert "bad-visibility" not in rendered
    assert "empty-profiles" not in rendered
    assert any("visibility" in record.getMessage() or "profiles" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "metadata_yaml",
    [
        "metadata: []",
        "metadata:\n  hermes: []",
        "metadata:\n  hermes: malformed",
    ],
)
def test_malformed_catalog_containers_are_hidden_but_missing_metadata_stays_global(
    catalog_env, caplog, metadata_yaml,
):
    home, _repo = catalog_env
    skill_dir = home / "skills" / "malformed" / "broken-container"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken-container\ndescription: malformed container\n"
        f"{metadata_yaml}\n---\nbody\n",
        encoding="utf-8",
    )
    _write_skill(home, "legacy-without-metadata", category="core")
    skill_utils._CATALOG_METADATA_WARNINGS.clear()

    with caplog.at_level(logging.WARNING, logger="agent.skill_utils"):
        rendered = build_skills_system_prompt()

    assert "broken-container" not in rendered
    assert "legacy-without-metadata" in rendered
    assert any("metadata" in record.getMessage() for record in caplog.records)


def test_malformed_alias_declaration_is_hidden_and_warned(catalog_env, caplog):
    home, _repo = catalog_env
    skill_dir = home / "skills" / "malformed" / "bad-aliases"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: bad-aliases\ndescription: malformed aliases\n"
        "metadata:\n  hermes:\n    aliases: [bad-aliases, bad-aliases]\n"
        "---\nbody\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="agent.skill_utils"):
        rendered = build_skills_system_prompt()

    assert "bad-aliases" not in rendered
    assert any("aliases" in record.getMessage() for record in caplog.records)


def test_aliases_are_not_extra_prompt_rows_and_prompt_is_byte_stable(catalog_env):
    home, _repo = catalog_env
    _write_skill(home, "canonical", category="core", aliases=["legacy-canonical"])

    first = build_skills_system_prompt()
    second = build_skills_system_prompt()

    assert first == second
    assert first.count("- canonical:") == 1
    assert "legacy-canonical" not in first


def test_slash_scan_has_canonical_rows_but_explicit_alias_loading_still_works(catalog_env, monkeypatch):
    home, _repo = catalog_env
    _write_skill(home, "canonical", category="core", aliases=["legacy-canonical"])
    _write_skill(home, "deferred", category="core", visibility="on_demand")

    commands = skill_commands.scan_skill_commands()

    assert "/canonical" in commands
    assert "/legacy-canonical" not in commands
    assert "/deferred" not in commands
    loaded = skill_commands._load_skill_payload("legacy-canonical")
    assert loaded and loaded[0]["name"] == "canonical"


def test_get_skill_commands_rescans_when_active_profile_changes(catalog_env, monkeypatch):
    home, _repo = catalog_env
    _write_skill(home, "a-only", category="profiles", visibility="profile", profiles=["profile-a"])
    _write_skill(home, "b-only", category="profiles", visibility="profile", profiles=["profile-b"])
    config = home / "config.yaml"

    def set_active_profile(profile: str) -> None:
        config.write_text(
            "skills:\n"
            "  external_dirs: []\n"
            f"  active_profiles: [{profile}]\n",
            encoding="utf-8",
        )


    set_active_profile("profile-a")
    first = skill_commands.get_skill_commands()
    assert "/a-only" in first
    assert "/b-only" not in first

    set_active_profile("profile-b")
    second = skill_commands.get_skill_commands()

    assert "/a-only" not in second
    assert "/b-only" in second


def test_active_profiles_malformed_config_fails_closed(catalog_env):
    home, _repo = catalog_env
    config = home / "config.yaml"
    config.write_text("skills:\n  active_profiles: not-a-list\n", encoding="utf-8")
    skill_utils._external_dirs_cache_clear()

    assert skill_utils.get_active_skill_profiles() == frozenset()


def test_active_profile_change_invalidates_prompt_cache(catalog_env):
    home, _repo = catalog_env
    _write_skill(home, "work-leaf", category="work-leaf", visibility="profile", profiles=["work-profile"])
    _write_skill(home, "documents", category="documents", visibility="profile", profiles=["design-profile"])
    config = home / "config.yaml"

    first = build_skills_system_prompt()
    assert "work-leaf" in first
    assert "documents" not in first

    config.write_text("skills:\n  active_profiles: [design-profile]\n", encoding="utf-8")
    second = build_skills_system_prompt()

    assert "work-leaf" not in second
    assert "documents" in second
    assert first != second


def test_platform_selection_uses_frontmatter_without_changing_host_platform():
    import sys

    host_label = next(label for label, mapped in skill_utils.PLATFORM_MAP.items() if sys.platform.startswith(mapped))
    assert skill_utils.skill_matches_platform_list([host_label]) is True
    assert skill_utils.skill_matches_platform_list(["definitely-not-this-platform"]) is False