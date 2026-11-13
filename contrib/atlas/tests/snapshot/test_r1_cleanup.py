"""R1 cleanup invariants. Pure store; no native initialization or upstream IO."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

SOURCE = Path(os.environ['ATLAS_FIX_SOURCE'])/'services/atlas-read/read_snapshot_store.py'


@pytest.fixture
def store(tmp_path):
    spec = importlib.util.spec_from_file_location('r1_store', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    s = module.SnapshotStore(tmp_path, clock=lambda: 100.0)
    # Deterministically drive cleanup without racing the daemon in these tests.
    s.stopped.set()
    s.worker.join(timeout=2)
    yield s
    s.close()
    assert not s.worker.is_alive()
    assert not list(tmp_path.rglob('spool-*'))


@pytest.mark.parametrize('value', [None, False, 0, '', [], {}])
def test_chunked_roundtrip_preserves_json_values(store, value):
    store.put('json', {'meta': 1}, [value], 10)
    assert store.get('json', 0) == ({'meta': 1}, value)


def test_ciphertext_rows_bound_even_large_native_part_and_metadata(store):
    # Tracker's retained arguments have no universal 8MB bound. Do not assume it.
    store.put('large', {'private': 'm'*2_000_000}, [{'private': 'v'*3_000_000}], 10)
    largest = store.db.execute('SELECT max(length(data)) FROM parts').fetchone()[0]
    assert largest <= 65536
    assert store.get('large', 0) == ({'private': 'm'*2_000_000}, {'private': 'v'*3_000_000})


def test_each_cleanup_transaction_deletes_one_bounded_row_and_eventually_reclaims(store):
    store.put('expired', {'private': 'm'*1_000_000}, [{'private': 'v'*3_000_000}], 10)
    store.put('live', {'live': True}, [{'keep': 1}], 1000)
    before = store.db.execute('PRAGMA page_count').fetchone()[0]
    tx_rows = [0]
    commits = []
    store.db.create_function('r1_deleted', 0, lambda: tx_rows.__setitem__(0, tx_rows[0]+1))
    store.db.execute('CREATE TEMP TRIGGER r1_deleted AFTER DELETE ON parts BEGIN SELECT r1_deleted(); END')
    def trace(statement):
        # Never retain SQL (it can contain ciphertext/identifiers).
        if statement == 'BEGIN ':
            tx_rows[0] = 0
        if statement == 'COMMIT':
            commits.append(tx_rows[0])
    store.db.set_trace_callback(trace)
    store.clock = lambda: 110.0
    try:
        assert store.get('expired', 0) is None
        assert commits and max(commits) == 1
        assert store.db.execute('SELECT count(*) FROM snapshots WHERE id="expired"').fetchone()[0] == 1
        for _ in range(8):
            store._prune()
        assert store.db.execute('SELECT count(*) FROM snapshots WHERE id="expired"').fetchone()[0] == 0
        assert max(commits) == 1
        assert not store.db.in_transaction
        assert store.db.execute('PRAGMA page_count').fetchone()[0] < before/2
        assert store.get('live', 0) == ({'live': True}, {'keep': 1})
    finally:
        store.db.set_trace_callback(None)


def test_interrupted_cleanup_rolls_back_only_current_chunk_and_expiry_stays_denied(store):
    store.put('expired', {'meta': 1}, [{'value': 'x'*3_000_000}], 10)
    store.put('live', {'meta': 2}, [{'keep': 2}], 1000)
    before = store.db.execute('SELECT count(*) FROM parts WHERE id="expired"').fetchone()[0]
    calls = [0]
    def fail_second():
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError('fixture cleanup fault')
    store.db.create_function('r1_fault', 0, fail_second)
    store.db.execute('CREATE TEMP TRIGGER r1_fault BEFORE DELETE ON parts BEGIN SELECT r1_fault(); END')
    store.clock = lambda: 110.0
    with pytest.raises(sqlite3.Error):
        store._prune()
    assert not store.db.in_transaction
    assert store.db.execute('SELECT count(*) FROM parts WHERE id="expired"').fetchone()[0] == before-1
    store.db.execute('DROP TRIGGER r1_fault')
    assert store.get('expired', 0) is None
    assert store.get('live', 0) == ({'meta': 2}, {'keep': 2})
    for _ in range(8):
        store._prune()
    assert store.db.execute('SELECT count(*) FROM snapshots WHERE id="expired"').fetchone()[0] == 0


def test_cleanup_overlaps_put_get_without_losing_unexpired_values(store):
    for i in range(10):
        store.put('old'+str(i), {}, [{'value': 'x'*300_000}], 10)
    store.put('keep', {}, [{'keep': True}], 1000)
    store.clock = lambda: 110.0
    def task(i):
        store.put('new'+str(i), {'n': i}, [{'n': i}], 1000)
        assert store.get('new'+str(i), 0) == ({'n': i}, {'n': i})
        assert store.get('keep', 0) == ({}, {'keep': True})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(task, range(40)))
    assert store.db.execute('SELECT count(*) FROM snapshots WHERE expires<=110').fetchone()[0] == 0
    assert store.db.execute('SELECT count(*) FROM snapshots').fetchone()[0] == 41


def test_worker_drains_multi_batch_snapshot_without_foreground_calls(tmp_path):
    spec = importlib.util.spec_from_file_location('r1_background_store', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.SnapshotStore(tmp_path, clock=lambda: 100.0)
    try:
        store.put('expired', {'private': 'm'*2_000_000}, [{'private': 'v'*2_000_000}], 10)
        before = store.db.execute('PRAGMA page_count').fetchone()[0]
        store.clock = lambda: 110.0
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            with store.lock:
                remaining = store.db.execute('SELECT count(*) FROM snapshots').fetchone()[0]
                after = store.db.execute('PRAGMA page_count').fetchone()[0]
            if remaining == 0:
                break
            time.sleep(.05)
        assert remaining == 0
        assert after < before/2
    finally:
        store.close()
    assert not store.worker.is_alive()
    assert not list(tmp_path.rglob('spool-*'))
