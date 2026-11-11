"""Fresh source-drift contracts exercised through reconstructed native providers."""
import json
import threading
from types import SimpleNamespace

from agent.capture_origin import capture_messages, runtime_capture_origin
from memory_test_plugins.honcho import HonchoMemoryProvider
from memory_test_plugins.honcho.capture import build_capture_turn
from memory_test_plugins.honcho.automatic_context import select_history, bound_units
from memory_test_plugins.openviking import OpenVikingMemoryProvider


def test_native_capture_preserves_human_suffix_without_machine_projection():
    from copy import deepcopy

    machine = "[ASYNC DELEGATION COMPLETE — worker] PRIVATE_MACHINE_SENTINEL"
    human_text = "\nHuman correction remains local."
    user = machine + human_text
    final = "The final answer preserves technical discussion of [ASYNC DELEGATION COMPLETE]."
    canonical = [{"role": "user", "content": user}, {"role": "assistant", "content": final}]
    saved = deepcopy(canonical)
    with runtime_capture_origin(machine):
        messages = capture_messages(user, final, canonical)
    snapshot = deepcopy(messages)
    rows = build_capture_turn(user, final, messages=messages, max_chars=13)
    human = [r for r in rows if r["metadata"]["source_kind"] == "human"]
    assistant = [r for r in rows if r["metadata"]["source_kind"] == "assistant"]
    assert "".join(r["content"] for r in human) == human_text
    assert "".join(r["content"] for r in assistant) == final
    assert not [r for r in rows if r["metadata"]["source_kind"] == "machine_notification"]
    assert "PRIVATE_MACHINE_SENTINEL" not in "".join(r["content"] for r in rows)
    assert all("custom_instructions" in r["configuration"]["reasoning"] for r in human)
    assert all(r["configuration"]["reasoning"]["enabled"] is False for r in assistant)
    assert canonical == saved
    assert messages == snapshot


def test_generation_rejects_completed_base_after_query_pivot():
    provider = HonchoMemoryProvider()
    started, release = threading.Event(), threading.Event()
    def fetch(*args):
        started.set()
        assert release.wait(5)
        return {"representation": "Old telescope evidence"}
    provider._manager = SimpleNamespace(get_prefetch_context=fetch)
    provider._session_key = "backend-session"
    generation = provider._activate_recall("telescope", "thread-a")
    worker = provider._start_base_refresh("telescope", generation)
    try:
        assert started.wait(5)
        provider._activate_recall("microscope", "thread-b")
        assert provider._start_base_refresh("microscope", provider._recall_generation) is worker
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert provider._base_context_data == {}
    assert provider._activate_recall("telescope", "thread-a") != generation


def test_automatic_history_cannot_borrow_topic_across_paragraphs():
    assert select_history("Telescope is a project.\n\nAn unrelated procedure is allowed.", "telescope") == "Telescope is a project."
    scoped = "Telescope changes were allowed only in a test. Not production."
    assert select_history(scoped, "telescope") == scoped
    assert scoped not in bound_units(scoped, 50)


def test_openviking_ranges_are_hash_bound_and_reconstruct_whole_source():
    text = "Telescope evidence. " * 1000 + "Not authorized in production."
    provider = OpenVikingMemoryProvider()
    provider._client = SimpleNamespace(get=lambda *a, **kw: {"result": text})
    args = {"uri": "viking://fixture/document.md", "level": "full"}
    first = json.loads(provider._tool_read(args))
    assert first["truncated"] and not first["complete"]
    parts = [first["content"]]
    page = first
    while "continuation" in page:
        page = json.loads(provider._tool_read(page["continuation"]))
        assert page["source_sha256"] == first["source_sha256"]
        parts.append(page["content"])
    assert "".join(parts) == text
    provider._client = SimpleNamespace(get=lambda *a, **kw: {"result": "changed"})
    error = json.loads(provider._tool_read(first["continuation"]))
    assert "Source changed" in str(error)


def test_marked_current_spans_do_not_lose_first_human_or_machine_segment():
    messages = [{"role": "user", "content": "old"},
                {"role": "user", "content": "machine", "capture_current_turn": True, "source_kind": "machine_notification"},
                {"role": "user", "content": "human", "capture_current_turn": True, "source_kind": "human"},
                {"role": "assistant", "content": "answer"}]
    result = OpenVikingMemoryProvider._extract_current_turn_messages(messages, "machinehuman", "answer")
    assert [r["content"] for r in result] == ["machine", "human", "answer"]
