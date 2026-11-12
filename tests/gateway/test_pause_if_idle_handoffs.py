"""SA-001: native admission reservations must fence idle-only lifecycle closure."""
import asyncio
import concurrent.futures
import os
import threading
from types import SimpleNamespace

import pytest

from tests.waiting import async_wait_until


@pytest.fixture(autouse=True)
def fence(monkeypatch):
    from hermes_cli import backend_retirement
    gate = backend_retirement.RetirementFence()
    monkeypatch.setattr(backend_retirement, 'retirement', gate)
    return gate


def identity(tmp_path):
    return dict(hermes_home=str(tmp_path.resolve()), pid=os.getpid(), start_time=1.0,
                instance_id='handoff-owner', authority_epoch='handoff-epoch', runtime_protocol=1)


def test_success_closes_producers_before_restart_mutates_runner(tmp_path, fence):
    from gateway.run_pause_idle import compare_and_pause
    runner = runner_fixture()
    expected = identity(tmp_path)

    def mark_shutdown():
        with fence.work() as admitted:
            assert not admitted, 'restart mutated state before permanently closing producer admission'

    runner._mark_api_runs_shutdown_requested = mark_shutdown

    async def stop(**kwargs):
        assert not fence.acquire()

    runner.stop = stop

    async def scenario():
        ack = compare_and_pause(runner, lambda: dict(expected, state='ready'),
                                {'expected_identity': expected})
        assert ack['pausing'] is True, ack
        await asyncio.wait_for(runner._restart_task, 5)

    asyncio.run(scenario())


def test_expired_comparison_permit_cannot_request_restart(tmp_path, fence):
    from gateway.run_pause_idle import compare_and_pause
    runner = runner_fixture()
    expected = identity(tmp_path)
    now = [1.0]
    fence._now = lambda: now[0]

    def describe():
        now[0] += 31
        return []

    runner._describe_active_work = describe

    async def scenario():
        ack = compare_and_pause(runner, lambda: dict(expected, state='ready'),
                                {'expected_identity': expected})
        assert ack['pausing'] is False, ack
        assert not runner._restart_requested and not runner._restart_task_started and not runner._draining
        with fence.work() as admitted:
            assert admitted

    asyncio.run(scenario())


def runner_fixture():
    from gateway.run import GatewayRunner
    runner = SimpleNamespace(
        _restart_task_started=False, _restart_requested=False, _draining=False,
        _external_drain_active=False, _stop_task=None, _running=True,
        _running_agents={}, session_runtime_descriptor={}, adapters={},
        _sessions_map=dict, _running_agent_count=lambda: 0,
        _active_api_run_count=lambda: 0, _active_deferred_agent_worker_count=lambda: 0,
        _mark_api_runs_shutdown_requested=lambda: None,
    )
    for name in ('_active_work_count', '_describe_active_work', '_active_cron_job_count',
                 'request_restart'):
        setattr(runner, name, getattr(GatewayRunner, name).__get__(runner))
    runner._running_cron_job_count = GatewayRunner._running_cron_job_count
    return runner


def test_pending_cron_handoff_refuses_pause_before_job_registration(monkeypatch, tmp_path, fence):
    from cron import scheduler as sched
    from cron import scheduler_tick as tick
    from gateway.run_pause_idle import compare_and_pause, work_snapshot

    runner = runner_fixture()
    expected = dict(hermes_home=str(tmp_path.resolve()), pid=os.getpid(), start_time=1.0,
                    instance_id='handoff-owner', authority_epoch='handoff-epoch', runtime_protocol=1)
    pending, release_tick = threading.Event(), threading.Event()
    started, release_job = threading.Event(), threading.Event()
    errors, results, stops = [], [], []
    job = dict(id='pending-handoff', name='fixture', schedule={'kind': 'interval', 'minutes': 5})
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def housekeeping(_sched, headless):
        assert not runner._draining
        pending.set()
        assert release_tick.wait(10)

    def process_job(*args):
        started.set()
        assert release_job.wait(10)
        return True

    monkeypatch.setattr(sched, '_get_hermes_home', lambda: tmp_path)
    monkeypatch.setattr(sched, '_should_yield_tick_to_fresh_gateway', lambda: None)
    monkeypatch.setattr(tick, '_acquire_tick_lock_or_degrade', lambda _: object())
    monkeypatch.setattr(sched, '_release_tick_lock', lambda fd: None)
    monkeypatch.setattr('agent.estop.check_paused', lambda *args: False)
    monkeypatch.setattr(tick, '_pre_dispatch_housekeeping', housekeeping)
    monkeypatch.setattr(sched, '_maybe_run_worktree_maintenance', lambda: None)
    monkeypatch.setattr(sched, 'get_due_jobs', lambda: [job])
    monkeypatch.setattr(sched, '_sweep_stale_inflight_for_tick', lambda jobs: None)
    monkeypatch.setattr(tick.store_health, 'dispatch_blocked', lambda jobs: False)
    monkeypatch.setattr(tick, '_advance_or_drop_recurring', lambda _, jobs: jobs)
    monkeypatch.setattr(sched, '_resolve_max_parallel_workers', lambda: 1)
    monkeypatch.setattr(sched, '_get_parallel_pool', lambda n: pool)
    monkeypatch.setattr(sched, 'create_execution', lambda *args, **kwargs: {'id': 'fixture'})
    monkeypatch.setattr(sched, 'note_cron_execution', lambda job: None)
    monkeypatch.setattr(sched, '_process_due_job', process_job)
    monkeypatch.setattr(sched, '_sweep_mcp_orphans_when_all_done', lambda fs: None)

    def producer():
        try:
            results.append(tick.tick(verbose=False, sync=False,
                                     can_dispatch=lambda: not runner._draining))
        except BaseException as exc:
            errors.append(repr(exc))

    thread = threading.Thread(target=producer)

    async def stop(**kwargs):
        stops.append(work_snapshot(runner))

    runner.stop = stop

    async def scenario():
        thread.start()
        assert await asyncio.to_thread(pending.wait, 5), errors
        assert fence.active_count() == 1
        assert work_snapshot(runner) == {'active_agents': 0, 'active_work': []}
        ack = compare_and_pause(runner, lambda: dict(expected, state='ready'),
                                {'expected_identity': expected})
        assert ack['pausing'] is False and ack['reason'] == 'busy', ack
        assert not runner._draining and not runner._restart_requested
        assert not runner._restart_task_started and not stops
        release_tick.set()
        assert await asyncio.to_thread(started.wait, 5), errors
        assert runner._active_work_count() == 1
        assert sched.get_running_job_details()[0]['job_id'] == job['id']

    try:
        asyncio.run(scenario())
    finally:
        release_tick.set()
        release_job.set()
        thread.join(10)
        pool.shutdown(wait=True)
        sched.release_running_job(job['id'], home=tmp_path)
    assert not thread.is_alive() and not errors, errors
    assert results == [1]
    assert fence.active_count() == 0


def test_teardown_waits_for_invisible_admission_then_closes_producer_gate(monkeypatch, fence):
    """Exercise the real idle restart even when called without the control-socket comparison."""
    from gateway.run_pause_idle import work_snapshot

    runner = runner_fixture()
    entered, release = threading.Event(), threading.Event()
    observed, errors = [], []

    def producer():
        try:
            with fence.work() as admitted:
                assert admitted
                entered.set()
                assert release.wait(10)
        except BaseException as exc:
            errors.append(repr(exc))

    thread = threading.Thread(target=producer)

    async def scenario():
        checks = 0
        stopped = asyncio.Event()

        def count():
            nonlocal checks
            checks += 1
            return 0

        runner._active_work_count = count
        prepare = fence.prepare

        def observe_prepare():
            nonlocal checks
            checks += 1
            return prepare()

        monkeypatch.setattr(fence, 'prepare', observe_prepare)

        async def stop(**kwargs):
            observed.append({'released': release.is_set(), 'reservations': fence.active_count()})
            with fence.work() as admitted:
                observed[-1]['new_admitted'] = admitted
            stopped.set()

        runner.stop = stop
        thread.start()
        assert await asyncio.to_thread(entered.wait, 5), errors
        assert work_snapshot(runner) == {'active_agents': 0, 'active_work': []}
        assert runner.request_restart(via_service=True, idle_only=True)
        try:
            await async_wait_until(lambda: checks >= 2 or stopped.is_set(), timeout=5,
                                   what='idle restart reaches the final admission check')
            assert not stopped.is_set(), observed
        finally:
            release.set()
            await asyncio.wait_for(runner._restart_task, 5)
        assert observed == [{'released': True, 'reservations': 0, 'new_admitted': False}]

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and not errors, errors
    assert fence.active_count() == 0
