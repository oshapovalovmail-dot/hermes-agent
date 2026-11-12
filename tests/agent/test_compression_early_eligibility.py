"""Native short packets must be rejected before expensive checkpoint/snapshot work."""

import copy
import json
import logging
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from agent.context_compressor import ContextCompressor, LEGACY_SUMMARY_PREFIX
from agent.conversation_compression import CompressionCommitFence, compress_context
from agent.memory_manager import MemoryManager
from agent.memory_provider import MemoryProvider, PRE_COMPRESS_CHECKPOINT_API_VERSION


class _CheckpointProvider(MemoryProvider):
    pre_compress_checkpoint_api_version = PRE_COMPRESS_CHECKPOINT_API_VERSION

    def __init__(self):
        self.calls = []

    @property
    def name(self):
        return "checkpoint-recorder"

    def is_available(self):
        return True

    def initialize(self, session_id, **kwargs):
        pass

    def get_tool_schemas(self):
        return []

    def on_pre_compress(self, messages, *, require_checkpoint=False):
        self.calls.append((copy.deepcopy(messages), require_checkpoint))
        return "Checkpoint id: early-eligibility-positive-control"


class _Agent:
    def __init__(self, compressor, manager):
        self.context_compressor = compressor
        self._memory_manager = manager
        self.compression_checkpoint_required = True
        self.compression_in_place = True
        self._compression_feasibility_checked = True
        self._session_db = None
        self._todo_store = SimpleNamespace(format_for_injection=lambda: "")
        self.session_id = "early-eligibility"
        self.platform = "cli"
        self.model = "test/model"
        self.provider = "test"
        self.log_prefix = ""
        self.tools = []
        self._cached_system_prompt = "stable system prompt"
        self._hard_interrupt_requested = threading.Event()

    def _emit_status(self, _message):
        pass

    def _emit_warning(self, _message):
        pass

    def _emit_diagnostic_status(self, _message):
        pass

    def _invalidate_system_prompt(self):
        self._cached_system_prompt = None

    def _build_system_prompt(self, system_message):
        return system_message

    def commit_memory_session(self, _messages):
        pass


@pytest.fixture
def runtime():
    compressor = ContextCompressor(
        model="test/model", provider="test", config_context_length=100_000,
        protect_first_n=3, quiet_mode=True,
    )
    provider = _CheckpointProvider()
    manager = MemoryManager()
    manager.add_provider(provider)
    return _Agent(compressor, manager), provider


def _packet(count) -> list[dict[str, Any]]:
    return [{"role": "system", "content": "stable system prompt"}] + [
        {"role": "user" if idx % 2 else "assistant", "content": f"payload-{idx}:" + "x" * 200_000}
        for idx in range(1, count)
    ]


def _attempts(caplog):
    prefix = "context compression attempt telemetry: "
    return [json.loads(record.getMessage().split(prefix, 1)[1])
            for record in caplog.records if prefix in record.getMessage()]


@pytest.mark.parametrize("count", range(3, 8))
def test_initial_giant_packet_skips_checkpoint_and_transcript_deepcopy(runtime, count, caplog, monkeypatch):
    agent, provider = runtime
    messages = _packet(count)
    original = copy.deepcopy(messages)
    original_rows = tuple(messages)
    copies = []
    deepcopy = copy.deepcopy

    def track_transcript_copy(value, *args, **kwargs):
        if value is messages:
            copies.append(value)
        return deepcopy(value, *args, **kwargs)

    metrics = []
    monkeypatch.setattr("hermes_cli.observability.shared_metrics_events.record_compression", lambda **kw: metrics.append(kw))
    with patch("agent.conversation_compression.copy.deepcopy", side_effect=track_transcript_copy):
        with patch("agent.context_compressor.call_llm") as summary:
            with caplog.at_level(logging.INFO, logger="agent.conversation_compression"):
                result, prompt = compress_context(agent, messages, "stable system prompt", approx_tokens=90_000, trigger="pre_api")

    assert provider.calls == [], "structurally impossible compaction must not checkpoint memory"
    assert copies == [], "the lossless early return must not deep-copy giant transcript payloads"
    summary.assert_not_called()
    assert result is messages
    assert messages == original
    assert all(row is original_rows[idx] for idx, row in enumerate(messages))
    assert prompt == "stable system prompt"
    compressor = agent.context_compressor
    assert compressor.compression_count == 0
    assert compressor._ineffective_compression_count == 0
    assert compressor._structural_no_op_backoff_until > 0
    assert compressor._structural_no_op_len == count
    telemetry = _attempts(caplog)
    assert len(telemetry) == 1
    assert telemetry[0]["failure_class"] == "insufficient_messages"
    assert telemetry[0]["commit_status"] == "aborted"
    assert telemetry[0]["trigger_source"] == "pre_api"
    assert telemetry[0]["attempt_id"] == compressor._last_compression_telemetry["attempt_id"]
    assert len(metrics) == 1
    assert metrics[0]["failure_class"] == "insufficient_messages"


def test_eligible_native_compaction_checkpoints_and_preserves_active_tool_round(runtime):
    agent, provider = runtime
    compressor = agent.context_compressor
    compressor.tail_token_budget = 10
    messages = _packet(15)
    messages.extend([
        {"role": "user", "content": "CURRENT ASK: inspect the result, then report"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "active-tool", "type": "function", "function": {"name": "terminal", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "active-tool", "content": "active result"},
    ])
    fence = CompressionCommitFence()
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="## Goal\nRetain the current task."))])
    with patch("agent.context_compressor.call_llm", return_value=response) as summary:
        compressed, _ = compress_context(agent, messages, "stable system prompt", approx_tokens=90_000, commit_fence=fence)

    assert len(provider.calls) == 1
    assert provider.calls[0][1] is True
    assert summary.called
    assert "Checkpoint id: early-eligibility-positive-control" in summary.call_args.kwargs["messages"][0]["content"]
    assert len(compressed) < len(messages)
    assert any("CURRENT ASK:" in str(row.get("content")) for row in compressed)
    tool_idx = next(idx for idx, row in enumerate(compressed) if row.get("tool_call_id") == "active-tool")
    assert compressed[tool_idx - 1]["tool_calls"][0]["id"] == "active-tool"
    assert compressor.compression_count == 1


@pytest.mark.parametrize("mode", ["forced", "focus", "plugin", "overridden-native"])
def test_explicit_or_custom_engines_keep_the_checkpoint_path(runtime, mode):
    agent, provider = runtime
    kwargs = {}
    calls = []
    if mode == "forced":
        kwargs["force"] = True
    elif mode == "focus":
        kwargs["focus_topic"] = "explicit focus"
    else:
        def compress(messages, **options):
            calls.append(options)
            return messages

        if mode == "plugin":
            agent.context_compressor = SimpleNamespace(compress=compress)
        else:
            agent.context_compressor.compress = compress
    with patch("agent.context_compressor.call_llm"):
        compress_context(agent, _packet(3), "stable system prompt", approx_tokens=90_000, **kwargs)
    assert len(provider.calls) == 1
    assert provider.calls[0][1] is True
    if mode in {"plugin", "overridden-native"}:
        assert len(calls) == 1
        assert "Checkpoint id:" in calls[0]["memory_context"]


def test_eligible_checkpoint_does_not_bypass_a_cancelled_commit_fence(runtime):
    agent, provider = runtime
    compressor = agent.context_compressor
    compressor.tail_token_budget = 10
    messages = _packet(15)
    original = copy.deepcopy(messages)
    fence = CompressionCommitFence()

    def finish_after_host_departure(**_kwargs):
        fence.cancel_before_commit()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="## Goal\nOld summary must not commit."))])

    with patch("agent.context_compressor.call_llm", side_effect=finish_after_host_departure):
        compressed, prompt = compress_context(agent, messages, "stable system prompt", approx_tokens=90_000, commit_fence=fence)

    assert len(provider.calls) == 1
    assert provider.calls[0][1] is True
    assert compressed is messages
    assert messages == original
    assert prompt == "stable system prompt"
    assert compressor.compression_count == 0
    assert getattr(compressor, "_compression_cancelled_check", None) is None


@pytest.mark.parametrize("decay", ["previous-compaction", "resumed-handoff"])
def test_native_decayed_head_is_not_mistaken_for_an_initial_packet(runtime, decay):
    agent, provider = runtime
    compressor = agent.context_compressor
    compressor.tail_token_budget = 10
    messages = _packet(7)
    if decay == "previous-compaction":
        compressor.compression_count = 1
    else:
        messages[1]["content"] = LEGACY_SUMMARY_PREFIX + "\nEarlier task state"
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="## Goal\nContinue the task."))])
    with patch("agent.context_compressor.call_llm", return_value=response) as summary:
        compress_context(agent, messages, "stable system prompt", approx_tokens=90_000)

    assert len(provider.calls) == 1
    assert provider.calls[0][1] is True
    assert summary.called


def test_structural_early_return_stops_heartbeat_before_releasing_lease(runtime, monkeypatch):
    from agent.conversation_compression import _CompressionActivityHeartbeat, _CompressionLease

    agent, provider = runtime
    events = []
    stop = _CompressionActivityHeartbeat.stop
    release = _CompressionLease.release

    def observe_stop(heartbeat, *args, **kwargs):
        events.append("heartbeat_stopped")
        return stop(heartbeat, *args, **kwargs)

    def observe_release(lease):
        events.append("lease_released")
        return release(lease)

    monkeypatch.setattr(_CompressionActivityHeartbeat, "stop", observe_stop)
    monkeypatch.setattr(_CompressionLease, "release", observe_release)
    compress_context(agent, _packet(3), "stable system prompt", approx_tokens=90_000)

    assert provider.calls == []
    assert events == ["heartbeat_stopped", "lease_released"]
