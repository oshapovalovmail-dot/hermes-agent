"""Private, process-lifetime encrypted disk snapshots, without count admission.

Only the broker loads this pinned module. No pathname or native argument crosses
its API. SQLite's pager bounds resident cache; AES-GCM keys exist only in RAM.
On POSIX the database is unlinked immediately after open, so process death also
reclaims disk space (no crash janitor, persisted key, or recoverable cursor).
"""
import atexit
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import threading
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# Physical ciphertext units, not result/request admission limits. This also
# bounds cleanup of native arguments that have no per-result size ceiling.
CHUNK_BYTES = 65_536
PRUNE_CHUNKS = 32


class StoreError(Exception):
    pass


class SnapshotStore:
    def __init__(self, profile, clock=time.monotonic):
        self.profile = str(Path(profile).resolve())
        self.clock = clock
        self.lock = threading.RLock()
        self.db = None
        self.cipher = AESGCM(AESGCM.generate_key(bit_length=256))
        self.stopped = threading.Event()
        parent = directory = fd = None
        name = 'spool-' + secrets.token_hex(16)
        created = False
        try:
            parent = os.open(self.profile, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.mkdir('.atlas-read-spool', 0o700, dir_fd=parent)
            except FileExistsError:
                pass
            directory = os.open('.atlas-read-spool', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            info = os.fstat(directory)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise StoreError('snapshot_storage_unavailable')
            fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            created = True
            path = Path(self.profile)/'.atlas-read-spool'/name
            # Recheck before and after SQLite opens; never follow a supplied symlink.
            if os.stat(path.parent, follow_symlinks=False).st_ino != info.st_ino:
                raise StoreError('snapshot_storage_unavailable')
            self.db = sqlite3.connect(str(path), check_same_thread=False)
            opened = os.stat(path, follow_symlinks=False)
            original = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (original.st_dev, original.st_ino):
                raise StoreError('snapshot_storage_unavailable')
            self.db.execute('PRAGMA journal_mode=MEMORY')
            self.db.execute('PRAGMA temp_store=MEMORY')
            self.db.execute('PRAGMA cache_size=-256')
            self.db.execute('PRAGMA mmap_size=0')
            self.db.execute('PRAGMA secure_delete=ON')
            # Reclaim expired bytes on commit, not just SQLite freelist slots.
            self.db.execute('PRAGMA auto_vacuum=FULL')
            self.db.execute('CREATE TABLE snapshots (id TEXT PRIMARY KEY, expires REAL)')
            self.db.execute('CREATE INDEX expiry ON snapshots(expires)')
            # Metadata (n=-1) and values share the same bounded physical units.
            # No plaintext or key is stored; chunks concatenate to one AEAD blob.
            self.db.execute('CREATE TABLE parts (id TEXT, n INTEGER, chunk INTEGER, '
                            'data BLOB CHECK(length(data)<=65536), '
                            'PRIMARY KEY(id,n,chunk)) WITHOUT ROWID')
            self.db.commit()
            os.unlink(name, dir_fd=directory)
            created = False
        except (OSError, sqlite3.Error, StoreError):
            if self.db is not None:
                self.db.close()
            self.db = None
            raise StoreError('snapshot_storage_unavailable') from None
        finally:
            if created:
                try:
                    os.unlink(name, dir_fd=directory)
                except OSError:
                    pass
            for handle in (fd, directory, parent):
                if handle is not None:
                    os.close(handle)
        # One cleanup worker per broker store, not per snapshot or request.
        self.worker = threading.Thread(target=self._maintain, name='atlas-snapshot-expiry', daemon=True)
        self.worker.start()
        atexit.register(self.close)

    def _seal(self, value, aad):
        nonce = secrets.token_bytes(12)
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        return nonce + self.cipher.encrypt(nonce, raw, aad)

    def _open(self, value, aad):
        return json.loads(self.cipher.decrypt(value[:12], value[12:], aad))

    def _write_part(self, key, index, value, aad):
        blob = self._seal(value, aad)
        self.db.executemany('INSERT INTO parts VALUES (?,?,?,?)',
            ((key, index, offset//CHUNK_BYTES, blob[offset:offset+CHUNK_BYTES])
             for offset in range(0, len(blob), CHUNK_BYTES)))

    def _read_part(self, key, index):
        rows = self.db.execute('SELECT data FROM parts WHERE id=? AND n=? ORDER BY chunk', (key, index))
        blob = b''.join(row[0] for row in rows)
        return blob or None

    def _prune(self):
        # Never nest cleanup in the caller's allocation transaction: MEMORY
        # rollback journals retain *all* touched preimages until COMMIT, and
        # cache_size cannot bound them. Each transaction removes <=64 KiB of
        # ciphertext plus bounded btree rebalance/auto-vacuum page moves. FULL
        # vacuum leaves no accumulated freelist for a later commit to process.
        # Index seeks avoid materializing the aggregate set of expired IDs.
        now = self.clock()
        for _ in range(PRUNE_CHUNKS):
            with self.db:
                row = self.db.execute('SELECT id FROM snapshots WHERE expires<=? '
                                      'ORDER BY expires LIMIT 1', (now,)).fetchone()
                if row is None:
                    return
                key = row[0]
                part = self.db.execute('SELECT n,chunk FROM parts WHERE id=? '
                                       'ORDER BY n,chunk LIMIT 1', (key,)).fetchone()
                if part is not None:
                    self.db.execute('DELETE FROM parts WHERE id=? AND n=? AND chunk=?', (key, *part))
                if self.db.execute('SELECT 1 FROM parts WHERE id=? LIMIT 1', (key,)).fetchone() is None:
                    self.db.execute('DELETE FROM snapshots WHERE id=?', (key,))

    def put(self, key, metadata, values, ttl):
        with self.lock:
            try:
                self._prune()
                with self.db:
                    self.db.execute('INSERT INTO snapshots VALUES (?,?)', (key, self.clock()+ttl))
                    self._write_part(key, -1, metadata, (key+':meta').encode())
                    for i, value in enumerate(values):
                        self._write_part(key, i, value, (key+':'+str(i)).encode())
            except (OSError, sqlite3.Error):
                raise StoreError('snapshot_storage_unavailable') from None

    def get(self, key, index):
        with self.lock:
            try:
                self._prune()
                # Logical TTL does not depend on physical cleanup reaching this
                # record. Partially reclaimed expired snapshots never decrypt.
                row = self.db.execute('SELECT 1 FROM snapshots WHERE id=? AND expires>?',
                                      (key, self.clock())).fetchone()
                if row is None:
                    return None
                meta = self._read_part(key, -1)
                part = self._read_part(key, index)
                if meta is None or part is None:
                    return None
                return (self._open(meta, (key+':meta').encode()),
                        self._open(part, (key+':'+str(index)).encode()))
            except Exception:
                # No exception details: they can carry private arguments or paths.
                raise StoreError('snapshot_storage_unavailable') from None

    def _maintain(self):
        while not self.stopped.wait(1):
            with self.lock:
                if self.db is None:
                    return
                try:
                    self._prune()
                except sqlite3.Error:
                    # Preserve existing cursors; next foreground operation returns
                    # the explicit storage error. Never evict a valid snapshot.
                    pass

    def close(self):
        self.stopped.set()
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None
            self.cipher = None
        if self.worker is not threading.current_thread():
            self.worker.join(timeout=2)
        atexit.unregister(self.close)


class StoredPages:
    """Constant-RAM view containing only the requested decrypted page."""
    def __init__(self, count, index, value):
        self.count, self.index, self.value = count, index, value

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if index != self.index:
            raise IndexError(index)
        return self.value
