"""Application write-lock patience must not be hidden inside SQLite's busy wait."""
from contextlib import contextmanager
import sqlite3
import subprocess
import sys
import threading

import pytest

from hermes_state import SessionDB, StateDbCorruptError


_HOLDER = """
import sqlite3, sys, threading
conn = sqlite3.connect(sys.argv[1], isolation_level=None)
try:
    conn.execute('BEGIN IMMEDIATE')
    print('held', flush=True)
    threading.Event().wait(timeout=2)
    conn.execute('COMMIT')
finally:
    conn.close()
"""


@contextmanager
def _held_writer(path, kind):
    if kind == "process":
        with subprocess.Popen([sys.executable, "-c", _HOLDER, str(path)],
                              stdout=subprocess.PIPE, text=True) as holder:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "held"
            try:
                yield
            finally:
                assert holder.wait(timeout=10) == 0
        return
    acquired = threading.Event()
    errors = []
    def hold():
        conn = sqlite3.connect(path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            acquired.set()
            threading.Event().wait(timeout=2)  # health: allow HX013 -- finite lock lifetime must outlast the 0.2s patience
            conn.execute("COMMIT")
        except BaseException as exc:
            errors.append(exc)
            acquired.set()
        finally:
            conn.close()
    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert acquired.wait(timeout=5) and not errors
        yield
    finally:
        holder.join(timeout=10)
        assert not holder.is_alive() and not errors


@pytest.fixture
def db(tmp_path):
    database = SessionDB(db_path=tmp_path / "state.db")
    yield database
    database.close()


@pytest.mark.parametrize("holder_kind", ["thread", "process"])
def test_short_patience_rejects_before_sqlite_wait_can_admit_a_late_write(db, holder_kind):
    db._WRITE_PATIENCE_S = 0.2
    assert db._conn is not None
    db._conn.execute("PRAGMA busy_timeout=5000")
    with _held_writer(db.db_path, holder_kind):
        with pytest.raises(sqlite3.OperationalError, match="another Hermes process"):
            db.set_meta("deadline-probe", "must-not-land")
    assert db.get_meta("deadline-probe") is None
    assert db._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert not db._conn.in_transaction
    db.set_meta("after-release", "works")
    assert db.get_meta("after-release") == "works"


def test_timeout_restore_failure_rolls_back_before_callback(db, monkeypatch):
    conn = db._conn
    assert conn is not None
    conn.execute("PRAGMA busy_timeout=1000")
    callbacks = []
    denied_restores = []
    execute_write = db._execute_write

    def observe_write(fn, *args, **kwargs):
        def observed(connection):
            callbacks.append(connection)
            return fn(connection)
        return execute_write(observed, *args, **kwargs)

    def authorizer(operation, name, value, *_):
        if operation == sqlite3.SQLITE_PRAGMA and name == "busy_timeout" and value == "1000":
            denied_restores.append(value)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    monkeypatch.setattr(db, "_execute_write", observe_write)
    changes_before = conn.total_changes
    conn.set_authorizer(authorizer)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            db.set_meta("restore-failure", "must-not-land")
        assert denied_restores == ["1000"]
        assert callbacks == []
        assert conn.total_changes == changes_before
        assert db.get_meta("restore-failure") is None
        assert not conn.in_transaction
    finally:
        conn.set_authorizer(None)

    db.set_meta("after-restore-failure", "works")
    assert callbacks == [conn]
    assert db.get_meta("after-restore-failure") == "works"
    assert not conn.in_transaction


@pytest.mark.parametrize("restore_fails", [False, True])
def test_corrupt_begin_keeps_original_metadata_and_quarantine_on_restore_failure(db, restore_fails):
    conn = db._conn
    assert conn is not None
    conn.execute("PRAGMA busy_timeout=742")
    original = sqlite3.DatabaseError("database disk image is malformed")
    original.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
    original.sqlite_errorname = "SQLITE_CORRUPT"
    restore_error = sqlite3.OperationalError("interrupted")
    begins = []
    restores = []
    callbacks = []

    class BeginCorrupt:
        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                begins.append(sql)
                raise original
            if sql == "PRAGMA busy_timeout=742":
                restores.append(sql)
                if restore_fails:
                    raise restore_error
            return conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(conn, name)

    db._conn = BeginCorrupt()
    try:
        with pytest.raises(StateDbCorruptError) as excinfo:
            db._execute_write(lambda actual: callbacks.append(actual))
        assert db._db_corrupt
        assert excinfo.value.__cause__ is original
        assert excinfo.value.sqlite_errorcode == original.sqlite_errorcode == sqlite3.SQLITE_CORRUPT
        assert excinfo.value.sqlite_errorname == original.sqlite_errorname == "SQLITE_CORRUPT"
        assert begins == ["BEGIN IMMEDIATE"]
        assert restores == ["PRAGMA busy_timeout=742"]
        assert callbacks == []
        assert not conn.in_transaction
        if restore_fails:
            assert excinfo.value.__context__.restore_error is restore_error
            assert any("busy_timeout" in note and "interrupted" in note for note in original.__notes__)
        else:
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 742
        with pytest.raises(StateDbCorruptError):
            db._execute_write(lambda actual: callbacks.append(actual))
        assert begins == ["BEGIN IMMEDIATE"]
        assert callbacks == []
    finally:
        db._conn = conn
        conn.execute("PRAGMA busy_timeout=742")


@pytest.mark.parametrize("restore_message", ["interrupted", "database is locked"])
def test_busy_begin_with_restore_failure_stops_without_retry_or_callback(db, restore_message):
    conn = db._conn
    assert conn is not None
    conn.execute("PRAGMA busy_timeout=743")
    original = sqlite3.OperationalError("database is locked")
    original.sqlite_errorcode = sqlite3.SQLITE_BUSY
    original.sqlite_errorname = "SQLITE_BUSY"
    restore_error = sqlite3.OperationalError(restore_message)
    begins = []
    callbacks = []

    class BeginBusyOnce:
        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                begins.append(sql)
                if len(begins) == 1:
                    raise original
            if sql == "PRAGMA busy_timeout=743":
                raise restore_error
            return conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(conn, name)

    db._conn = BeginBusyOnce()
    try:
        with pytest.raises(sqlite3.Error) as excinfo:
            db._execute_write(lambda actual: callbacks.append(actual), patience_s=0.2)
        assert begins == ["BEGIN IMMEDIATE"]
        assert callbacks == []
        assert excinfo.value.begin_error is original
        assert excinfo.value.restore_error is restore_error
        assert not db._db_corrupt
        assert not conn.in_transaction
    finally:
        db._conn = conn
        conn.execute("PRAGMA busy_timeout=743")


@pytest.mark.parametrize("outcome", ["commit", "rollback"])
def test_write_keeps_connection_timeout_and_transaction_outcome(db, outcome):
    assert db._conn is not None
    db._conn.execute("PRAGMA busy_timeout=750")
    def write(conn):
        conn.execute("INSERT INTO state_meta(key, value) VALUES (?, ?)", ("transaction-probe", outcome))
        if outcome == "rollback":
            raise ValueError("callback failed")
        return "callback-result"
    if outcome == "rollback":
        with pytest.raises(ValueError, match="callback failed"):
            db._execute_write(write)
        assert db.get_meta("transaction-probe") is None
    else:
        assert db._execute_write(write) == "callback-result"
        assert db.get_meta("transaction-probe") == "commit"
    assert db._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 750
    assert not db._conn.in_transaction
