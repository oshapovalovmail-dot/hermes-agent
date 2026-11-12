"""Idle-only pause is a loop-owned compare-and-close, not a stale client snapshot."""
import asyncio
import copy
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gateway.control_socket import query_gateway_control
from gateway.run_bootstrap import _start_gateway_start_control_socket


@pytest.fixture
def owner(monkeypatch, tmp_path):
    identity = dict(hermes_home=str(tmp_path.resolve()), pid=os.getpid(), start_time=12.5,
                    instance_id='owned-instance', authority_epoch='owned-epoch', runtime_protocol=1)
    monkeypatch.setattr('gateway.control_socket.build_identify_payload', lambda: dict(identity))
    runner = SimpleNamespace(
        session_runtime_descriptor=dict(identity, state='ready', capabilities=[]),
        session_ticket_store=None, _draining=False, _restart_requested=False,
        _restart_task_started=False, _stop_task=None, _running=True,
        _active_work_count=lambda: 0, _describe_active_work=list,
        request_restart=Mock(return_value=True))
    monkeypatch.setattr('gateway.run_active_work_verb._delegation_units', lambda now: [])
    return runner, identity


def exchange(owner, params, before=None):
    runner, _ = owner

    async def scenario():
        server = await _start_gateway_start_control_socket(runner)
        assert server is not None
        try:
            if before:
                before()
            return await asyncio.to_thread(query_gateway_control, server._home,
                                           'pause-if-idle', params=params, timeout=8)
        finally:
            await server.stop()
    return asyncio.run(scenario())


@pytest.mark.parametrize('agents,work', [(1, []), (0, [{'kind': 'delegation'}]),
                                         (1, [{'kind': 'chat'}])])
def test_busy_never_enters_a_deadline_drain(owner, agents, work):
    runner, identity = owner
    runner._active_work_count = lambda: agents
    runner._describe_active_work = lambda: work
    result = exchange(owner, {'expected_identity': identity})
    assert result is not None, 'native idle-only admission is unsupported'
    assert result['pausing'] is False and result['reason'] == 'busy'
    runner.request_restart.assert_not_called()
    assert runner._draining is False


@pytest.mark.parametrize('key', ['pid', 'start_time', 'instance_id', 'authority_epoch',
                                 'runtime_protocol', 'hermes_home'])
def test_owner_mismatch_is_nonmutating(owner, key):
    runner, identity = owner
    expected = dict(identity, **{key: 'foreign'})
    result = exchange(owner, {'expected_identity': expected})
    assert result is not None, 'native idle-only admission is unsupported'
    assert result['pausing'] is False and result['reason'] == 'identity_mismatch'
    runner.request_restart.assert_not_called()


@pytest.mark.parametrize('params', [{}, {'expected_identity': {}},
                                    {'expected_identity': None},
                                    {'expected_identity': {'pid': True}}])
def test_missing_identity_fails_closed(owner, params):
    runner, _ = owner
    result = exchange(owner, params)
    assert result is not None, 'native idle-only admission is unsupported'
    assert result['pausing'] is False
    runner.request_restart.assert_not_called()


def test_inbound_arrives_after_zero_readback_before_pause(owner):
    runner, identity = owner
    assert runner._active_work_count() == 0 and runner._describe_active_work() == []
    def inbound():
        runner._active_work_count = lambda: 1
        runner._describe_active_work = lambda: [{'kind': 'chat'}]
    result = exchange(owner, {'expected_identity': identity}, inbound)
    assert result is not None, 'native idle-only admission is unsupported'
    assert result['pausing'] is False and result['reason'] == 'busy'
    runner.request_restart.assert_not_called()


def test_idle_closes_in_the_same_loop_callback(owner):
    runner, identity = owner
    def close(**kwargs):
        assert asyncio.get_running_loop().is_running()
        assert runner._active_work_count() == 0 and runner._describe_active_work() == []
        runner._draining = True
        return True
    runner.request_restart.side_effect = close
    result = exchange(owner, {'expected_identity': copy.deepcopy(identity)})
    assert result is not None, 'native idle-only admission is unsupported'
    assert result['pausing'] is True and result['idle_only'] is True
    assert result['identity'] == identity
    assert result['active_agents'] == 0 and result['active_work'] == []
    runner.request_restart.assert_called_once_with(detached=False, via_service=True, idle_only=True)
    assert runner._draining is True


@pytest.mark.parametrize('count', [0, 1])
def test_safe_restart_never_uses_legacy_deadline_wait(monkeypatch, count):
    from gateway.run import GatewayRunner
    async def scenario():
        busy = asyncio.Event()
        release = asyncio.Event()
        stopped = asyncio.Event()
        runner = SimpleNamespace(_restart_task_started=False, _draining=False,
                                 session_runtime_descriptor={},
                                 _active_work_count=lambda: count if not release.is_set() else 0,
                                 _describe_active_work=lambda: [] if release.is_set() else [{'kind': 'cron'}],
                                 _mark_api_runs_shutdown_requested=lambda: None)
        async def legacy_wait():
            pytest.fail('safe pause entered the finite legacy restart wait')
        async def stop(**kwargs):
            assert release.is_set()
            stopped.set()
        async def tick(delay):
            if delay == 0.1 and not release.is_set():
                busy.set()
                await release.wait()
        runner._await_active_work_before_restart = legacy_wait
        runner.stop = stop
        monkeypatch.setattr(asyncio, 'sleep', tick)
        assert GatewayRunner.request_restart(runner, via_service=True, idle_only=True)
        assert runner._draining is True
        await asyncio.wait_for(busy.wait(), 5)
        assert not stopped.is_set()
        release.set()
        await asyncio.wait_for(runner._restart_task, 5)
        assert stopped.is_set()
    asyncio.run(scenario())


def test_identify_advertises_idle_pause_contract(owner):
    runner, _ = owner
    async def scenario():
        server = await _start_gateway_start_control_socket(runner)
        assert server
        try:
            result = await asyncio.to_thread(query_gateway_control, server._home, 'identify')
            assert result and result.get('idle_pause_protocol') == 1
        finally:
            await server.stop()
    asyncio.run(scenario())


def test_legacy_pause_still_uses_original_restart_contract(owner):
    runner, _ = owner
    async def scenario():
        server = await _start_gateway_start_control_socket(runner)
        assert server
        try:
            result = await asyncio.to_thread(query_gateway_control, server._home,
                                            'pause-for-update', timeout=8)
            assert result['pausing'] is True
            runner.request_restart.assert_called_once_with(detached=False, via_service=True)
        finally:
            await server.stop()
    asyncio.run(scenario())
