"""Behavioral tests for skills_list/search and deterministic alias resolution."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent import skill_utils
from tools import skills_tool


def _write_skill(
    root: Path,
    name: str,
    *,
    category: str = "general",
    description: str | None = None,
    visibility: str | None = None,
    profiles: list[str] | None = None,
    aliases: list[str] | None = None,
) -> Path:
    skill_dir = root / "skills" / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"name: {name}", f"description: {description or name + ' description'}"]
    hermes: list[str] = []
    if visibility is not None:
        hermes.append(f"    visibility: {visibility}")
    if profiles is not None:
        hermes.append("    profiles: [" + ", ".join(profiles) + "]")
    if aliases is not None:
        hermes.append("    aliases: [" + ", ".join(aliases) + "]")
    if hermes:
        lines.extend(["metadata:", "  hermes:", *hermes])
    lines.extend(["---", f"# {name}", "", f"Full body for {name}.", ""])
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    return skill_dir


@pytest.fixture
def tool_catalog_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / ".hermes"
    (home / "skills").mkdir(parents=True)
    (home / "config.yaml").write_text("skills:\n  external_dirs: []\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_PLATFORM", raising=False)
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.setattr(skills_tool, "_SKILLS_CACHE", {})
    skill_utils._external_dirs_cache_clear()
    yield home
    monkeypatch.setattr(skills_tool, "_SKILLS_CACHE", {})
    skill_utils._external_dirs_cache_clear()


def test_skills_list_query_and_category_compose_and_include_catalog_metadata(tool_catalog_env):
    home = tool_catalog_env
    _write_skill(
        home,
        "canonical-work",
        category="ops",
        description="Run the legacy work procedure",
        visibility="profile",
        profiles=["work-profile"],
        aliases=["legacy-work"],
    )
    _write_skill(home, "other-work", category="docs", description="Unrelated work")
    _write_skill(home, "deferred", category="ops", visibility="on_demand")

    from tools.registry import registry
    result = json.loads(registry.dispatch("skills_list", {"category": "ops", "query": "legacy"}))

    assert result["success"] is True
    assert [row["name"] for row in result["skills"]] == ["canonical-work"]
    row = result["skills"][0]
    assert row["visibility"] == "profile"
    assert row["profiles"] == ["work-profile"]
    assert row["aliases"] == ["legacy-work"]
    assert "legacy" in row["description"].lower()

    all_ops = json.loads(skills_tool.skills_list(category="ops"))
    assert {row["name"] for row in all_ops["skills"]} == {"canonical-work", "deferred"}


def test_skill_view_resolves_alias_to_canonical_and_preserves_hidden_leaf_access(tool_catalog_env):
    home = tool_catalog_env
    _write_skill(
        home,
        "canonical-work",
        category="ops",
        visibility="on_demand",
        aliases=["legacy-work"],
    )

    result = json.loads(skills_tool.skill_view("legacy-work", preprocess=False))

    assert result["success"] is True
    assert result["name"] == "canonical-work"
    assert result["visibility"] == "on_demand"
    assert result["aliases"] == ["legacy-work"]
    assert "Full body" in result["content"]


def test_alias_collision_with_canonical_name_fails_closed(tool_catalog_env):
    home = tool_catalog_env
    _write_skill(home, "canonical-one", category="ops", aliases=["shared-name"])
    _write_skill(home, "shared-name", category="ops")

    result = json.loads(skills_tool.skill_view("shared-name", preprocess=False))

    assert result["success"] is False
    assert "Ambiguous skill name" in result["error"]
    assert len(result["matches"]) == 2


@pytest.mark.parametrize(
    "metadata_yaml",
    [
        "metadata: []",
        "metadata:\n  hermes: []",
        "metadata:\n  hermes: malformed",
    ],
)
def test_malformed_catalog_container_remains_canonically_loadable_with_invalid_metadata(
    tool_catalog_env, metadata_yaml,
):
    home = tool_catalog_env
    skill_dir = home / "skills" / "malformed" / "broken-container"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken-container\ndescription: malformed container\n"
        f"{metadata_yaml}\n---\nFull body for broken-container.\n",
        encoding="utf-8",
    )

    listed = json.loads(skills_tool.skills_list(category="malformed"))
    row = next(row for row in listed["skills"] if row["name"] == "broken-container")
    assert row["metadata_valid"] is False

    loaded = json.loads(skills_tool.skill_view("broken-container", preprocess=False))
    assert loaded["success"] is True
    assert loaded["name"] == "broken-container"
    assert loaded["metadata_valid"] is False


@pytest.mark.parametrize(
    "aliases_yaml",
    [
        "aliases: not-a-list",
        "aliases: [bad-alias, bad-alias]",
        "aliases: [canonical-work]",
    ],
)
def test_malformed_aliases_keep_canonical_load_available_but_disable_alias_resolution(
    tool_catalog_env, aliases_yaml,
):
    home = tool_catalog_env
    skill_dir = home / "skills" / "malformed" / "canonical-work"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: canonical-work\ndescription: malformed aliases\n"
        "metadata:\n  hermes:\n    visibility: global\n    "
        f"{aliases_yaml}\n---\nFull body for canonical-work.\n",
        encoding="utf-8",
    )

    loaded = json.loads(skills_tool.skill_view("canonical-work", preprocess=False))
    assert loaded["success"] is True
    assert loaded["metadata_valid"] is False
    assert loaded["aliases"] == []

    alias_result = json.loads(skills_tool.skill_view("bad-alias", preprocess=False))
    assert alias_result["success"] is not True


def test_alias_alias_collision_fails_closed_without_traversal_order(tool_catalog_env):
    home = tool_catalog_env
    _write_skill(home, "first", category="ops", aliases=["shared-name"])
    _write_skill(home, "second", category="docs", aliases=["shared-name"])

    result = json.loads(skills_tool.skill_view("shared-name", preprocess=False))

    assert result["success"] is False
    assert "Ambiguous skill name" in result["error"]
    assert {Path(path).parent.name for path in result["matches"]} == {"first", "second"}

def test_alias_collision_catalog_rows_are_explicitly_loadable(tool_catalog_env):
    home = tool_catalog_env
    _write_skill(home, "canonical-one", category="ops", aliases=["shared-name"])
    _write_skill(home, "shared-name", category="docs")
    result = json.loads(skills_tool.skills_list())
    row = next(s for s in result["skills"] if s["name"].endswith("shared-name"))
    assert row["name"] == "docs/shared-name"
    assert json.loads(skills_tool.skill_view(row["name"], preprocess=False))["success"] is True
