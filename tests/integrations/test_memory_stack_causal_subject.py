"""Implicit subjects require an actual causal entity diff and matching file read."""
import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.parse

import pytest


IDENTITY = "probe-canary"
ARCHIVE = f"viking://user/{IDENTITY}/sessions/{IDENTITY}/history/archive_001"
URI = f"viking://user/{IDENTITY}/memories/preferences/{IDENTITY}/project color preference.md"
CONTENT = "- Permanently prefers cobalt blue as the project's color; this is a lasting project preference."
RED_CONTENT = "- Permanently prefers crimson red as the project's color; this is a lasting project preference."
FOREIGN_URI = URI.replace("/preferences/probe-canary/", "/preferences/other-project/")
OTHER_URI = URI.replace("project color preference.md", "other preference.md")
ENTRY = {"uri": URI, "memory_type": "preferences", "after": CONTENT}
OTHER_ENTRY = {"uri": OTHER_URI, "memory_type": "preferences", "after": RED_CONTENT}


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "integrations/memory-stack"))
    checks = importlib.import_module("stack_checks")
    monkeypatch.setattr(checks.uuid, "uuid4", lambda: SimpleNamespace(hex="canary"))
    data = {
        "task": {"status": "completed", "error": None, "resource_id": IDENTITY,
                 "result": {"session_id": IDENTITY, "archive_uri": ARCHIVE,
                            "memory_diff_uri": ARCHIVE + "/memory_diff.json"}},
        "diff": {"archive_uri": ARCHIVE, "operations": {"adds": [copy.deepcopy(ENTRY)], "updates": [], "deletes": []}},
        "rows": [{"uri": URI, "abstract": CONTENT}], "reads": {URI: CONTENT},
    }
    stored = ""

    def http(base, path, body=None, **kwargs):
        nonlocal stored
        if path == "/api/v1/sessions":
            return {"result": {"session_id": IDENTITY}}
        if path.endswith("/messages"):
            assert body is not None
            stored = body["content"]
            return {"result": {}}
        if path.endswith("/context"):
            return {"result": {"messages": [{"role": "user", "content": stored}]}}
        if path.endswith("/commit"):
            return {"result": {"task_id": "task-canary"}}
        if path == "/api/v1/tasks/task-canary":
            return {"result": data["task"]}
        if path == "/api/v1/search/find":
            return {"result": {"memories": data["rows"]}}
        if path.startswith("/api/v1/content/read?uri="):
            read_uri = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["uri"][0]
            value = json.dumps(data["diff"]) if read_uri == ARCHIVE + "/memory_diff.json" else data["reads"].get(read_uri, "")
            if isinstance(value, list):
                value = value.pop(0)
            return {"result": value}
        raise AssertionError(path)

    monkeypatch.setattr(checks, "request", http)
    return checks, data


@pytest.mark.parametrize("content", [CONTENT, "- Permanently prefers cobalt blue as a lasting project preference."])
def test_scoped_preference_requires_completed_causal_diff_and_independent_content_read(probe, content):
    checks, data = probe
    data["reads"][URI] = content
    data["diff"]["operations"]["adds"][0]["after"] = content
    assert checks.check_openviking("http://fixture.invalid", storage_only=False, timeout=1)["passed"]


@pytest.mark.parametrize("changes", [
    [(("task", "resource_id"), "foreign-session")],
    [(("task", "result", "archive_uri"), "viking://user/foreign/sessions/foreign/history/archive_001")],
    [(("diff", "archive_uri"), "viking://user/foreign/sessions/foreign/history/archive_001")],
    [(("diff", "operations", "adds"), [])],
    [(("diff", "operations", "adds", 0, "uri"), FOREIGN_URI),
     (("rows", 0, "uri"), FOREIGN_URI), (("reads", FOREIGN_URI), CONTENT)],
    [(("reads", URI), "")],
    [(("diff", "operations", "adds", 0, "after"), "A different content version.")],
    [(("reads", URI), "This is a project record."),
     (("diff", "operations", "adds", 0, "after"), "This is a project record.")],
    [(("reads", URI), CONTENT + " This preference was revoked."),
     (("diff", "operations", "adds", 0, "after"), CONTENT + " This preference was revoked.")],
    [(("diff", "operations", "adds"), [ENTRY, OTHER_ENTRY]),
     (("rows",), [{"uri": URI}, {"uri": OTHER_URI}]), (("reads", OTHER_URI), RED_CONTENT)],
    [(("reads", URI), "Another project permanently prefers cobalt blue."),
     (("diff", "operations", "adds", 0, "after"), "Another project permanently prefers cobalt blue.")],
], ids=["foreign-task", "foreign-archive", "foreign-diff", "missing-add", "foreign-entity", "empty-read",
        "after-mismatch", "metadata-only", "revoked", "contradiction", "wrong-subject"])
def test_scoped_preference_rejects_uncoupled_metadata_or_conflicting_content(probe, changes):
    checks, data = probe
    for path, value in changes:
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = copy.deepcopy(value)
    assert not checks.check_openviking("http://fixture.invalid", storage_only=False, timeout=1)["passed"]


@pytest.mark.parametrize("positive", [CONTENT, "Project probe-canary permanently prefers cobalt blue."])
@pytest.mark.parametrize("conflict", [
    "Project probe-canary no longer prefers cobalt blue.",
    "Project probe-canary has chosen crimson red.",
    "Has chosen crimson red.",
])
def test_causal_subset_cannot_discard_conflict_in_other_independent_read(probe, positive, conflict):
    checks, data = probe
    data["reads"][URI] = positive
    data["diff"]["operations"]["adds"][0]["after"] = positive
    data["rows"].append({"uri": OTHER_URI})
    data["reads"][OTHER_URI] = conflict
    assert not checks.check_openviking("http://fixture.invalid", storage_only=False, timeout=1)["passed"]


@pytest.mark.parametrize("predicate", ["Has chosen", "Permanently has chosen"])
def test_causal_bound_implicit_choice_cannot_contradict_preference(probe, predicate):
    checks, data = probe
    contradictory = CONTENT + "\n" + predicate + " crimson red."
    data["reads"][URI] = contradictory
    data["diff"]["operations"]["adds"][0]["after"] = contradictory
    assert not checks.check_openviking("http://fixture.invalid", storage_only=False, timeout=1)["passed"]


@pytest.mark.parametrize("positive", [CONTENT, "Project probe-canary permanently prefers cobalt blue."])
@pytest.mark.parametrize("conflict", ["Project probe-canary no longer prefers cobalt blue.", "Has chosen crimson red."])
@pytest.mark.parametrize("conflict_first", [True, False])
def test_repeated_uri_cannot_overwrite_independently_read_conflict(probe, positive, conflict, conflict_first):
    checks, data = probe
    data["rows"].append({"uri": URI})
    data["reads"][URI] = [conflict, positive] if conflict_first else [positive, conflict]
    data["diff"]["operations"]["adds"][0]["after"] = positive
    result = checks.check_openviking("http://fixture.invalid", storage_only=False, timeout=1)
    assert not result["passed"]
    assert result["error"] == "inconsistent-memory-content"


@pytest.mark.parametrize("positive", [CONTENT, "Project probe-canary permanently prefers cobalt blue."])
def test_identical_repeated_uri_is_not_a_content_conflict(probe, positive):
    checks, data = probe
    data["rows"].append({"uri": URI})
    data["reads"][URI] = [positive, positive]
    data["diff"]["operations"]["adds"][0]["after"] = positive
    assert checks.check_openviking("http://fixture.invalid", storage_only=False, timeout=1)["passed"]
