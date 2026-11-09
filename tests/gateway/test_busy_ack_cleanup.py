"""Transient busy replies use the real final-delivery lifecycle, not handler completion."""
import asyncio
from types import SimpleNamespace

import pytest

from gateway.config import Platform
from gateway.platforms.base import SendResult
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run_turn_runner import TurnRunner
from gateway.session import SessionSource
from gateway.turn_context import TurnContext
from tests.gateway.test_run_cleanup_progress import CleanupCaptureAdapter, _make_runner


class DeliveryAdapter(CleanupCaptureAdapter):
    def __init__(self):
        super().__init__()
        self.config.typing_indicator = False
        self.final_started = asyncio.Event()
        self.final_release = asyncio.Event()
        self.ack_started = asyncio.Event()
        self.ack_release = asyncio.Event()
        self.delay_ack = False
        self.final_ok = True
        self.ack_ok = True
        self.delete_raises = False

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        if content.endswith("final answer"):
            self.final_started.set()
            await self.final_release.wait()
            if not self.final_ok:
                return SendResult(success=False, error="transport failed")
        elif content.endswith("busy receipt"):
            self.ack_started.set()
            if self.delay_ack:
                await self.ack_release.wait()
            if not self.ack_ok:
                return SendResult(success=False, error="ack failed")
        return await super().send(chat_id, content, reply_to, metadata)

    async def delete_message(self, chat_id, message_id):
        if self.delete_raises:
            raise RuntimeError("delete forbidden")
        return await super().delete_message(chat_id, message_id)


def setup_turn(monkeypatch, *, enabled=True, generation=1, thread_id="topic-a"):
    import gateway.run as gateway_run

    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {
        "display": {"platforms": {"telegram": {"cleanup_progress": enabled}}},
    })
    adapter = DeliveryAdapter()
    runner = _make_runner(adapter)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="chat", chat_type="group",
                           user_id="human", thread_id=thread_id)
    key = runner._session_key_for_source(source)
    ctx = TurnContext(source=source, session_key=key, run_generation=generation,
                      _cleanup_progress=enabled)
    state = runner._session_state(key)
    state.persistent.run_generation = generation
    state.turn.ctx = ctx
    event = MessageEvent(text="continue", message_type=MessageType.TEXT, source=source,
                         message_id="user-command")
    turn = TurnRunner(runner, ctx)
    return runner, adapter, ctx, turn, event, key


async def deliver(runner, adapter, ctx, event, key, *, failed=False, response="final answer"):
    async def handler(_event):
        runner._run_agent_schedule_bubble_cleanup({"failed": failed}, adapter, ctx)
        adapter._active_sessions[key]._hermes_run_generation = ctx.run_generation
        return response

    adapter._message_handler = handler
    await adapter._process_message_background(event, key)
    # Flush thread-safe scheduling callbacks and their spawned cleanup coroutines.
    for _ in range(3):
        barrier = asyncio.Event()
        asyncio.get_running_loop().call_soon(barrier.set)
        await barrier.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["redirected", "steered", "queued"])
async def test_busy_and_working_deleted_only_after_actual_final(monkeypatch, message):
    runner, adapter, ctx, turn, event, key = setup_turn(monkeypatch)
    working = await adapter.send("chat", "Working")
    turn._track_progress_result(working)
    await runner._send_busy_ack_reply(event, adapter, message)
    approval = await adapter.send("chat", "approval request")
    await runner._send_busy_reply(event, adapter, "real command result")
    transient_ids = {working.message_id, adapter.sent[1]["message_id"]}
    task = asyncio.create_task(deliver(runner, adapter, ctx, event, key))
    await asyncio.wait_for(adapter.final_started.wait(), 5)
    assert adapter.deleted == []
    adapter.final_release.set()
    await asyncio.wait_for(task, 5)
    assert {d["message_id"] for d in adapter.deleted} == transient_ids
    assert approval.message_id not in transient_ids
    assert adapter.sent[-1]["content"] == "final answer"
    assert len(adapter.sent) == 5  # no extra bot notices from cleanup


@pytest.mark.asyncio
@pytest.mark.parametrize("final_ok,enabled,failed,response", [
    (False, True, False, "final answer"),
    (True, False, False, "final answer"),
    (True, True, True, "final answer"),
    (True, True, False, None),
])
async def test_failed_disabled_or_absent_final_keeps_transients(
    monkeypatch, final_ok, enabled, failed, response,
):
    runner, adapter, ctx, turn, event, key = setup_turn(monkeypatch, enabled=enabled)
    turn._track_progress_result(await adapter.send("chat", "Working"))
    await runner._send_busy_ack_reply(event, adapter, "busy receipt")
    other_callbacks = []
    adapter.register_post_delivery_callback(key, lambda: other_callbacks.append(True), generation=1)
    adapter.final_ok = final_ok
    adapter.final_release.set()
    await deliver(runner, adapter, ctx, event, key, failed=failed, response=response)
    assert adapter.deleted == []
    assert other_callbacks == [True]  # failure must not suppress unrelated hooks


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt_after_final", [False, True])
async def test_late_ack_receipt_is_collected_even_after_final(monkeypatch, receipt_after_final):
    runner, adapter, ctx, _turn, event, key = setup_turn(monkeypatch)
    adapter.delay_ack = True
    ack = asyncio.create_task(runner._send_busy_ack_reply(event, adapter, "busy receipt"))
    await asyncio.wait_for(adapter.ack_started.wait(), 5)
    task = asyncio.create_task(deliver(runner, adapter, ctx, event, key))
    await asyncio.wait_for(adapter.final_started.wait(), 5)
    if not receipt_after_final:
        adapter.ack_release.set()
        await asyncio.wait_for(ack, 5)
        assert adapter.deleted == []
    adapter.final_release.set()
    await asyncio.wait_for(task, 5)
    if receipt_after_final:
        # A new generation must never receive the old send's late id.
        successor = TurnContext(source=event.source, session_key=key, run_generation=2,
                                _cleanup_progress=True)
        runner._session_state(key).persistent.run_generation = 2
        runner._session_state(key).turn.ctx = successor
        adapter.ack_release.set()
        await asyncio.wait_for(ack, 5)
        assert successor._cleanup_msg_ids == []
    ack_id = next(s["message_id"] for s in adapter.sent if s["content"] == "busy receipt")
    assert adapter.deleted == [{"chat_id": "chat", "message_id": ack_id}]


@pytest.mark.asyncio
async def test_topic_and_generation_do_not_cross_cleanup(monkeypatch):
    runner, adapter, ctx, _turn, event, key = setup_turn(monkeypatch)
    other_source = SessionSource(platform=Platform.TELEGRAM, chat_id="chat", chat_type="group",
                                 user_id="human", thread_id="topic-b")
    other_key = runner._session_key_for_source(other_source)
    other_ctx = TurnContext(source=other_source, session_key=other_key, run_generation=1,
                            _cleanup_progress=True)
    runner._session_state(other_key).persistent.run_generation = 1
    runner._session_state(other_key).turn.ctx = other_ctx
    other_event = MessageEvent(text="other", message_type=MessageType.TEXT, source=other_source)
    await runner._send_busy_ack_reply(other_event, adapter, "other topic")
    await runner._send_busy_ack_reply(event, adapter, "this topic")
    this_id = adapter.sent[-1]["message_id"]
    adapter.final_release.set()
    await deliver(runner, adapter, ctx, event, key)
    assert adapter.deleted == [{"chat_id": "chat", "message_id": this_id}]
    assert not adapter.pop_post_delivery_callback(other_key, generation=2)


@pytest.mark.asyncio
async def test_bot_and_failed_ack_are_not_cleanup_candidates(monkeypatch):
    runner, adapter, ctx, _turn, event, key = setup_turn(monkeypatch)
    event.source.is_bot = True
    await runner._send_busy_ack_reply(event, adapter, "busy receipt")
    assert adapter.sent == []
    event.source.is_bot = False
    adapter.ack_ok = False
    await runner._send_busy_ack_reply(event, adapter, "busy receipt")
    adapter.final_release.set()
    await deliver(runner, adapter, ctx, event, key)
    assert adapter.deleted == []


@pytest.mark.asyncio
async def test_cleanup_delete_failure_is_silent(monkeypatch):
    runner, adapter, ctx, _turn, event, key = setup_turn(monkeypatch)
    await runner._send_busy_ack_reply(event, adapter, "busy receipt")
    adapter.delete_raises = True
    adapter.final_release.set()
    await deliver(runner, adapter, ctx, event, key)
    assert [s["content"] for s in adapter.sent] == ["busy receipt", "final answer"]


@pytest.mark.asyncio
async def test_late_working_receipt_after_final_is_deleted_once(monkeypatch):
    from tests.waiting import async_wait_until

    runner, adapter, ctx, turn, event, key = setup_turn(monkeypatch)
    adapter.final_release.set()
    await deliver(runner, adapter, ctx, event, key)
    receipt = await adapter.send("chat", "Working")
    turn._track_progress_result(receipt)
    turn._track_progress_result(receipt)  # an edited heartbeat may repeat an id
    assert await async_wait_until(lambda: bool(adapter.deleted), timeout=5)
    assert adapter.deleted == [{"chat_id": "chat", "message_id": receipt.message_id}]


@pytest.mark.asyncio
async def test_ack_before_agent_context_is_bound_joins_same_generation(monkeypatch):
    runner, adapter, _ctx, _turn, event, key = setup_turn(monkeypatch)
    runner._session_state(key).turn.ctx = None  # native pending-agent startup window
    await runner._send_busy_ack_reply(event, adapter, "busy receipt")
    ack_id = adapter.sent[-1]["message_id"]
    disp = runner._run_agent_display_settings(event.source)
    bound, _, cleanup_adapter = runner._run_agent_build_turn_context(
        disp, object, message="hello", source=event.source, session_key=key, run_generation=1,
    )
    assert cleanup_adapter is adapter
    adapter.final_release.set()
    await deliver(runner, adapter, bound, event, key)
    assert adapter.deleted == [{"chat_id": "chat", "message_id": ack_id}]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_ok", [True, False])
async def test_stream_final_receipt_not_preview_controls_cleanup(monkeypatch, stream_ok):
    runner, adapter, ctx, turn, event, key = setup_turn(monkeypatch)
    turn._track_progress_result(await adapter.send("chat", "Working"))
    ctx.stream_consumer_holder[0] = SimpleNamespace(
        final_response_sent=stream_ok, final_content_delivered=stream_ok,
        delivered_final_matches=lambda text: stream_ok, stream_deltas_enabled=False,
    )

    async def handler(_event):
        response = {"final_response": "final answer"}
        await runner._run_agent_mark_streamed_delivery(response, ctx)
        runner._run_agent_schedule_bubble_cleanup(response, adapter, ctx)
        adapter._active_sessions[key]._hermes_run_generation = 1
        # Native handler suppresses the normal send after streaming.

    adapter._message_handler = handler
    await adapter._process_message_background(event, key)
    assert bool(adapter.deleted) is stream_ok


@pytest.mark.asyncio
@pytest.mark.parametrize("send_ok", [True, False])
async def test_authority_owned_final_has_the_same_delivery_fence(monkeypatch, send_ok):
    from gateway.session_ingress import deliver_settled, fire_post_delivery, _take_post_delivery

    runner, adapter, ctx, _turn, event, key = setup_turn(monkeypatch)
    await runner._send_busy_ack_reply(event, adapter, "busy receipt")
    runner._run_agent_schedule_bubble_cleanup({"final_response": "final answer"}, adapter, ctx)
    authority = SimpleNamespace(runner=runner, profile_id="test-owner", native_waiters=set(),
                                pending_deliveries={"admission": (adapter, event, key, "final answer", None)})
    _take_post_delivery(authority, "admission", event.source, key)
    adapter.final_ok = send_ok
    adapter.final_release.set()
    await deliver_settled(authority, "admission")
    await fire_post_delivery(authority, "admission")
    assert bool(adapter.deleted) is send_ok


@pytest.mark.asyncio
async def test_cleanup_lookup_failure_does_not_suppress_native_ack(monkeypatch):
    import gateway.run as gateway_run

    runner, adapter, _ctx, _turn, event, key = setup_turn(monkeypatch)
    runner._session_state(key).turn.ctx = None

    def unavailable_config():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(gateway_run, "_load_gateway_config", unavailable_config)
    await runner._send_busy_ack_reply(event, adapter, "busy receipt")
    assert [s["content"] for s in adapter.sent] == ["busy receipt"]


@pytest.mark.asyncio
async def test_cleanup_registration_failure_is_best_effort(monkeypatch):
    runner, adapter, ctx, _turn, _event, _key = setup_turn(monkeypatch)

    def unavailable_registration(*args, **kwargs):
        raise RuntimeError("adapter unavailable")

    monkeypatch.setattr(adapter, "register_post_delivery_callback", unavailable_registration)
    runner._run_agent_schedule_bubble_cleanup({"final_response": "done"}, adapter, ctx)
    assert adapter.deleted == []


@pytest.mark.asyncio
@pytest.mark.parametrize("send_ok,failed,streamed", [
    (True, False, False), (False, False, False), (True, True, False), (True, False, True),
])
async def test_queued_first_final_cleans_its_own_messages_before_followup(
    monkeypatch, send_ok, failed, streamed,
):
    from gateway.transient_cleanup import bind_turn_cleanup

    runner, adapter, ctx, turn, event, key = setup_turn(monkeypatch)
    bind_turn_cleanup(runner, ctx, adapter)
    working = await adapter.send("chat", "Working")
    turn._track_progress_result(working)
    await runner._send_busy_ack_reply(event, adapter, "busy receipt")
    transient_ids = {working.message_id, adapter.sent[-1]["message_id"]}
    if streamed:
        ctx.stream_consumer_holder[0] = SimpleNamespace(
            final_response_sent=True, final_content_delivered=True,
            delivered_final_matches=lambda text: True,
        )
    adapter.final_ok = send_ok
    adapter.final_release.set()
    response = {"final_response": "final answer", "failed": failed}
    await runner._run_agent_deliver_first_response(ctx, adapter, response, response, None)
    assert {d["message_id"] for d in adapter.deleted} == (transient_ids if send_ok and not failed else set())

    # Recursive queued turns retain the run generation, but must get a fresh receipt owner.
    disp = runner._run_agent_display_settings(event.source)
    successor, next_turn, _adapter = runner._run_agent_build_turn_context(
        disp, object, message="followup", source=event.source, session_key=key, run_generation=1,
    )
    next_working = await adapter.send("chat", "Working followup")
    next_turn._track_progress_result(next_working)
    assert successor._cleanup_msg_ids == [next_working.message_id]
    assert next_working.message_id not in {d["message_id"] for d in adapter.deleted}
