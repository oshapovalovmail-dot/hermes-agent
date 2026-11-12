"""Opt-in owner-bound, loop-owned idle pause; legacy pause-for-update stays unchanged."""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from gateway import run_active_work_verb as work

IDENTITY_KEYS = ('hermes_home', 'pid', 'start_time', 'instance_id', 'authority_epoch', 'runtime_protocol')


def work_snapshot(runner) -> dict[str, Any]:
    """Same unscoped BOTH-zero sources as active-work; exceptions must refuse a pause."""
    import time
    units = list(runner._describe_active_work()) + work._delegation_units(time.time())
    count = runner._active_work_count()
    if type(count) is not int or count < 0:
        raise RuntimeError('invalid active work count')
    return {'active_agents': count, 'active_work': units}


def is_idle(snapshot: dict[str, Any]) -> bool:
    return snapshot['active_agents'] == 0 and snapshot['active_work'] == []


def compare_and_pause(runner, identify, params: dict[str, Any]) -> dict[str, Any]:
    """Compare under the native producer reservation barrier; restart commits it before mutation."""
    payload = identify()
    identity = {key: payload.get(key) for key in IDENTITY_KEYS}
    result = dict(pausing=False, idle_only=True, identity=identity, pid=identity['pid'])
    expected = params.get('expected_identity')
    if (set(params) != {'expected_identity'} or not isinstance(expected, dict)
            or set(expected) != set(IDENTITY_KEYS)
            or any(value is None or value == '' for value in identity.values())
            or any(type(expected[key]) is not type(identity[key]) or expected[key] != identity[key]
                   for key in IDENTITY_KEYS)):
        return dict(result, reason='identity_mismatch')
    if (payload.get('state') != 'ready' or runner._draining or runner._restart_requested
            or runner._restart_task_started or runner._stop_task is not None):
        return dict(result, reason='not_ready')
    from hermes_cli.backend_retirement import retirement
    permit = retirement.prepare()
    if not permit['ok']:
        return dict(result, reason='busy', **work_snapshot(runner))
    token = permit['token']
    try:
        snapshot = work_snapshot(runner)
        if not is_idle(snapshot):
            return dict(result, reason='busy', **snapshot)
        runner._idle_pause_retirement_token = token
        accepted = runner.request_restart(detached=False, via_service=True, idle_only=True)
        return dict(result, pausing=accepted, reason='accepted' if accepted else 'not_ready', **snapshot)
    finally:
        runner.__dict__.pop('_idle_pause_retirement_token', None)
        # Committed permits cannot be cancelled: producer admission stays closed through teardown.
        retirement.cancel(token)


def pause_if_idle_verb(runner, loop, identify):
    """Marshal the entire comparison/closure onto the runner's loop, never a socket-thread read."""
    def handler(params):
        future = concurrent.futures.Future()
        def request():
            if not future.set_running_or_notify_cancel():
                return
            try:
                future.set_result(compare_and_pause(runner, identify, params))
            except Exception as exc:
                logging.getLogger(__name__).exception("Idle pause comparison failed")
                future.set_exception(exc)
        loop.call_soon_threadsafe(request)
        try:
            return future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            future.cancel()  # a queued request cannot acquire a late side effect after timing out
            raise
    return handler


def commit_idle_pause(runner) -> bool:
    """Commit the comparison's permit before restart mutation; expired permits refuse without effects."""
    from hermes_cli.backend_retirement import retirement
    token = getattr(runner, '_idle_pause_retirement_token', None)
    return token is None or retirement.commit(token)['ok']


async def wait_idle_pause(runner) -> None:
    """No deadline: join reservations as well as registered work, then permanently close producers."""
    from hermes_cli.backend_retirement import retirement
    while True:
        permit = retirement.prepare()
        if permit['ok']:
            token = permit['token']
            try:
                if is_idle(work_snapshot(runner)) and retirement.commit(token)['ok']:
                    return
            finally:
                retirement.cancel(token)
        await asyncio.sleep(0.1)


async def run_requested_restart(runner, *, detached: bool, via_service: bool, idle_only: bool) -> None:
    from gateway.run_shutdown import _log_suppressed
    if not idle_only:
        await runner._await_active_work_before_restart()
    # Detached helper only AFTER the after-turn wait, or its deadline fires mid-turn.
    if detached:
        with _log_suppressed(logging.ERROR, 'Failed to launch detached gateway restart helper: %s'):
            await runner._launch_detached_restart_command()
    await asyncio.sleep(0.05)
    if idle_only:
        await wait_idle_pause(runner)
    await runner.stop(restart=True, detached_restart=detached, service_restart=via_service)
