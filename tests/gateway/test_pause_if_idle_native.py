"""Owned loopback daemon: stale-idle pause refuses a real managed turn, then exits idle."""
import asyncio
from contextlib import closing
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import threading

from tests.gateway.fixtures.local_recovery_probe import Model, child_env, daemon, rpc, websocket
from tests.gateway.test_normal_runtime_boot import control
from tests.waiting import async_wait_until


KEYS = ('hermes_home', 'pid', 'start_time', 'instance_id', 'authority_epoch', 'runtime_protocol')


def test_native_stale_zero_refuses_then_completed_turn_allows_idle_exit(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home, user = tmp_path / 'state', tmp_path / 'user'
    home.mkdir(mode=0o700)
    user.mkdir()
    peer = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    peer.requests = []
    peer.blocked, peer.release = threading.Event(), threading.Event()
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{peer.server_port}/v1'
    (home / 'config.yaml').write_text(json.dumps({
        'gateway': {'managed_workers': True, 'multiplex_profiles': False},
        'agent': {'restart_after_turn_timeout': 0, 'restart_drain_timeout': 0},
        'model': {'provider': 'custom', 'default': 'idle-fixture', 'base_url': url},
        'platform_toolsets': {'cli': []}, 'auxiliary': {'title_generation': {'enabled': False}}}))
    env = child_env()
    env.update(HOME=str(user), USERPROFILE=str(user), HERMES_HOME=str(home), PYTHONPATH=str(root),
               OPENAI_API_KEY='loopback-only', OPENAI_BASE_URL=url)
    admission = None

    async def exercise(process, descriptor):
        nonlocal admission
        expected = {key:descriptor[key] for key in KEYS}
        initial = await asyncio.to_thread(control, home, 'active-work')
        assert initial['active_agents'] == 0 and initial['active_work'] == []
        async with websocket(home, descriptor) as ws:
            created = await rpc(ws, 'session.create', request_id='idle-session', source='cli', cwd=str(home),
                                model='idle-fixture', provider='custom', base_url=url,
                                api_key='loopback-only', toolsets=[], ignore_rules=True)
            assert 'result' in created, created
            sid = created['result']['session_id']
            submitted = await rpc(ws, 'prompt.submit', session_id=sid, input_id='idle-input',
                                  text='BLOCK_STARTED', finite=True)
            assert 'result' in submitted, submitted
            admission = submitted['result']['admission_id']
            assert await asyncio.to_thread(peer.blocked.wait, 30)
            refused = await asyncio.to_thread(control, home, 'pause-if-idle', {'expected_identity': expected})
            assert refused['pausing'] is False and refused['reason'] == 'busy', refused
            assert process.poll() is None
            assert (await asyncio.to_thread(control, home, 'identify'))['state'] == 'ready'
            peer.release.set()
            def terminal():
                with closing(sqlite3.connect(home / 'state.db')) as db:
                    row = db.execute('SELECT status,outcome FROM session_admissions WHERE admission_id=?', (admission,)).fetchone()
                    workers = db.execute('SELECT status FROM worker_executions').fetchall()
                    return row == ('terminal', 'completed') and workers and all(row[0] == 'terminal' for row in workers)
            await async_wait_until(terminal, timeout=40, what='durable completed admission and settled worker')
            def idle():
                value = control(home, 'active-work')
                return value['active_agents'] == 0 and value['active_work'] == []
            await async_wait_until(idle, timeout=40, what='managed turn naturally finishes')
            # Closing the client can admit a managed detach after the idle readback.
            # Keep the observer attached until the native closure; never retry a refused pause.
            accepted = await asyncio.to_thread(control, home, 'pause-if-idle', {'expected_identity': expected})
            assert accepted['pausing'] is True and accepted['idle_only'] is True, json.dumps(accepted)
            assert accepted['identity'] == expected
            assert accepted['active_agents'] == 0 and accepted['active_work'] == []
            await asyncio.to_thread(process.wait, 40)
            # No external supervisor is installed in this fixture; native service handoff exits.
            assert process.returncode == 75

    try:
        with daemon(root, home, env, barrier=False) as (process, descriptor):
            asyncio.run(exercise(process, descriptor))
        with closing(sqlite3.connect(home / 'state.db')) as db:
            row = db.execute('SELECT status,outcome FROM session_admissions WHERE admission_id=?', (admission,)).fetchone()
            assert row == ('terminal', 'completed'), row
            assert db.execute('SELECT status FROM worker_executions').fetchone()[0] == 'terminal'
        assert len(peer.requests) == 1
    finally:
        peer.release.set()
        peer.shutdown()
        peer.server_close()
        thread.join(timeout=5)
