"""Small fixed app contract; NOT native admission or a production launcher.

No HTTP/Shell dispatch, credentials, arbitrary metadata or host paths. Input body
is user content; a schema cannot infer whether a user pasted a secret into text.
Attestations never enter native_event(), durable inputs or the Mac journal.
"""
from contextlib import contextmanager
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock

BOT_ID = '9229862070'
TASHA_ID = '793835103'
DOMAIN = b'atlas-telegram-transport-v1\x00'
FIELDS = frozenset(('version', 'kind', 'bot_id', 'epoch', 'nonce', 'issued_at', 'expires_at',
                    'update_id', 'message_id', 'user_id', 'username', 'is_bot', 'chat_id',
                    'chat_type', 'thread_id', 'profile', 'text', 'eligibility'))
ACTION_FIELDS = frozenset(('origin', 'op', 'user_id', 'chat_id', 'thread_id', 'profile', 'content'))


class Denied(PermissionError):
    """A bounded denial code, never raw input/credentials."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def positive_id(value):
    return type(value) is str and re.fullmatch(r'[1-9][0-9]{0,19}', value) is not None


def validate(raw):
    if type(raw) is not dict or set(raw) != FIELDS:
        raise Denied('closed_input_schema')
    if type(raw['version']) is not int or raw['version'] != 1 or raw['kind'] != 'telegram_input' or raw['bot_id'] != BOT_ID:
        raise Denied('wrong_transport_identity')
    if (type(raw['epoch']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', raw['epoch'])
            or type(raw['nonce']) is not str or not re.fullmatch(r'[0-9a-f]{32}', raw['nonce'])):
        raise Denied('invalid_epoch_nonce')
    if (type(raw['issued_at']) is not int or type(raw['expires_at']) is not int
            or raw['issued_at'] < 0 or not 0 < raw['expires_at'] - raw['issued_at'] <= 30):
        raise Denied('invalid_freshness_window')
    if not all(positive_id(raw[key]) for key in ('user_id', 'update_id', 'message_id')) or raw['is_bot'] is not False:
        raise Denied('canonical_human_identity_required')
    if type(raw['text']) is not str or len(raw['text'].encode()) > 65536:
        raise Denied('bounded_text_required')
    if type(raw['eligibility']) is not dict:
        raise Denied('eligibility_required')
    proof = raw['eligibility']
    if raw['chat_type'] == 'dm':
        if raw['chat_id'] != raw['user_id'] or raw['thread_id'] is not None or raw['profile'] != 'tg-' + raw['user_id']:
            raise Denied('exact_dm_scope_required')
        if (type(raw['username']) is not str or not re.fullmatch(r'[a-z0-9_]{1,32}', raw['username'])
                or proof != {'kind': 'staff_username', 'active': True, 'verified': True, 'robot': False}
                or any(type(proof.get(k)) is not bool for k in ('active', 'verified', 'robot'))):
            raise Denied('active_human_username_required')
    elif raw['chat_type'] == 'group':
        chat = raw['chat_id']; topic = raw['thread_id']
        if type(chat) is not str or not re.fullmatch(r'-[1-9][0-9]{0,19}', chat):
            raise Denied('canonical_group_required')
        if topic is not None and not positive_id(topic):
            raise Denied('canonical_topic_required')
        if raw['profile'] != 'tg-group-n' + chat[1:] + '-t' + (topic or '0') or raw['username'] is not None:
            raise Denied('separate_group_profile_required')
        if (proof != {'kind': 'tasha_admin', 'bot_id': TASHA_ID, 'is_bot': True, 'status': 'administrator'}
                or proof.get('is_bot') is not True):
            raise Denied('official_tasha_admin_required')
    else:
        raise Denied('unsupported_chat_type')
    return raw


class EnvelopeCodec:
    def __init__(self, key, epoch):
        if type(key) is not bytes or len(key) < 32:
            raise Denied('strong_transport_key_required')
        self._key, self.epoch = key, epoch

    def sign(self, payload, *, now):
        body = copy.deepcopy(validate(payload))
        self._fresh(body, now)
        signature = hmac.new(self._key, DOMAIN + canonical(body), hashlib.sha256).hexdigest()
        return {'payload': body, 'signature': signature}

    def _fresh(self, payload, now):
        if (type(now) is not int or payload['epoch'] != self.epoch
                or not payload['issued_at'] <= now < payload['expires_at']):
            raise Denied('stale_or_foreign_transport_proof')

    def verify(self, envelope, *, now):
        if type(envelope) is not dict or set(envelope) != {'payload', 'signature'}:
            raise Denied('signed_envelope_required')
        body = copy.deepcopy(validate(envelope['payload']))
        signature = envelope['signature']
        if type(signature) is not str or not re.fullmatch(r'[0-9a-f]{64}', signature):
            raise Denied('invalid_transport_signature')
        expected = hmac.new(self._key, DOMAIN + canonical(body), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise Denied('invalid_transport_signature')
        self._fresh(body, now)
        return body


def origin_id(raw):
    return raw['bot_id'] + ':' + raw['update_id']


def input_fingerprint(raw):
    return digest({k: v for k, v in raw.items() if k not in {'epoch', 'nonce', 'issued_at', 'expires_at', 'eligibility'}})


def native_event(raw):
    """Closed normalized native DTO. This does not mint an Atlas Binding."""
    validate(raw)
    return {'text': raw['text'], 'message_type': 'command' if raw['text'].startswith('/') else 'text',
            'message_id': raw['message_id'],
            'source': {'platform': 'telegram', 'chat_id': raw['chat_id'], 'chat_type': raw['chat_type'],
                       'user_id': raw['user_id'], 'thread_id': raw['thread_id'],
                       'profile': raw['profile'], 'message_id': raw['message_id']}}


def _store_serialized(method):
    def call(self, *args, **kwargs):
        with self._store_lock:
            return method(self, *args, **kwargs)
    return call


class _StoreCursor(sqlite3.Cursor):
    def __init__(self, connection):
        self._store_lock = connection._store_lock
        super().__init__(connection)

    execute = _store_serialized(sqlite3.Cursor.execute)
    executemany = _store_serialized(sqlite3.Cursor.executemany)
    executescript = _store_serialized(sqlite3.Cursor.executescript)
    fetchone = _store_serialized(sqlite3.Cursor.fetchone)
    fetchmany = _store_serialized(sqlite3.Cursor.fetchmany)
    fetchall = _store_serialized(sqlite3.Cursor.fetchall)
    __next__ = _store_serialized(sqlite3.Cursor.__next__)
    close = _store_serialized(sqlite3.Cursor.close)


class _StoreConnection(sqlite3.Connection):
    """One connection, serialized across bootstrap, reader and tool workers.

    Cursor stepping and close share the transaction lock: serializing execute
    alone would expose another thread's uncommitted rows on this connection.
    """
    def __init__(self, *args, **kwargs):
        self._store_lock = RLock()
        super().__init__(*args, **kwargs)

    @_store_serialized
    def cursor(self):
        return super().cursor(factory=_StoreCursor)

    @_store_serialized
    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)

    @_store_serialized
    def executemany(self, *args, **kwargs):
        return self.cursor().executemany(*args, **kwargs)

    @_store_serialized
    def executescript(self, *args, **kwargs):
        return self.cursor().executescript(*args, **kwargs)

    commit = _store_serialized(sqlite3.Connection.commit)
    rollback = _store_serialized(sqlite3.Connection.rollback)
    close = _store_serialized(sqlite3.Connection.close)


class PrivateStore:
    def __init__(self, path):
        if sqlite3.threadsafety == 0:
            raise Denied('threadsafe_sqlite_required')
        path = Path(path).absolute()
        for candidate in (path, *path.parents):
            if candidate.is_symlink():
                raise Denied('symlink_store_forbidden')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.fchmod(fd, 0o600); os.close(fd)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False,
                                  factory=_StoreConnection)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA busy_timeout=5000')

    @contextmanager
    def transaction(self):
        with self.db._store_lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()


class IngressLedger(PrivateStore):
    def __init__(self, path):
        super().__init__(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS inputs(origin TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS nonces(nonce TEXT PRIMARY KEY, origin TEXT NOT NULL)')

    def admit(self, raw):
        validate(raw)
        origin, fingerprint = origin_id(raw), input_fingerprint(raw)
        with self.transaction():
            old_nonce = self.db.execute('SELECT origin FROM nonces WHERE nonce=?', (raw['nonce'],)).fetchone()
            if old_nonce and old_nonce[0] != origin:
                raise Denied('nonce_scope_conflict')
            old = self.db.execute('SELECT fingerprint FROM inputs WHERE origin=?', (origin,)).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise Denied('input_identity_conflict')
                self.db.execute('INSERT OR IGNORE INTO nonces VALUES (?,?)', (raw['nonce'], origin))
                return 'replay'  # never recreates ephemeral native authorization
            self.db.execute('INSERT INTO inputs VALUES (?,?)', (origin, fingerprint))
            self.db.execute('INSERT INTO nonces VALUES (?,?)', (raw['nonce'], origin))
            return 'new'


class DeliveryJournal(PrivateStore):
    """Metadata-only Mac journal. Caller must perform live admission recheck.

    reserved->acked; a repeated reserved intent returns ambiguous and NEVER
    authorizes another send. No recovery can manufacture a Telegram ACK.
    """
    def __init__(self, path):
        super().__init__(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS origins(origin TEXT PRIMARY KEY, fingerprint TEXT, uid TEXT, chat TEXT, topic TEXT, profile TEXT, revoked INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS sends(operation TEXT PRIMARY KEY, origin TEXT, fingerprint TEXT, status TEXT, message TEXT)')

    def register_origin(self, raw):
        validate(raw)
        origin, fingerprint = origin_id(raw), input_fingerprint(raw)
        with self.transaction():
            old = self.db.execute('SELECT fingerprint FROM origins WHERE origin=?', (origin,)).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise Denied('input_identity_conflict')
                return  # no replacing a revoked receipt
            self.db.execute('INSERT INTO origins VALUES (?,?,?,?,?,?,0)',
                            (origin, fingerprint, raw['user_id'], raw['chat_id'], raw['thread_id'], raw['profile']))

    def reserve(self, operation, action):
        if type(operation) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', operation):
            raise Denied('stable_operation_id_required')
        if type(action) is not dict or set(action) != ACTION_FIELDS or action['op'] != 'send':
            raise Denied('closed_reply_schema')
        if type(action['content']) is not str or len(action['content'].encode('utf-16-le')) // 2 > 4096:
            raise Denied('bounded_reply_required')
        fingerprint = digest(action)
        with self.transaction():
            scope = self.db.execute('SELECT uid,chat,topic,profile,revoked FROM origins WHERE origin=?', (action['origin'],)).fetchone()
            if (not scope or scope[4] or tuple(action[k] for k in ('user_id', 'chat_id', 'thread_id', 'profile')) != scope[:4]):
                raise Denied('exact_unrevoked_recipient_required')
            old = self.db.execute('SELECT fingerprint,status,message FROM sends WHERE operation=?', (operation,)).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise Denied('operation_identity_conflict')
                return {'status': 'acked', 'message_id': old[2]} if old[1] == 'acked' else {'status': 'ambiguous'}
            self.db.execute('INSERT INTO sends VALUES (?,?,?,?,NULL)', (operation, action['origin'], fingerprint, 'reserved'))
            return {'status': 'reserved'}

    def ack(self, operation, *, chat_id, message_id):
        if not positive_id(message_id):
            raise Denied('real_message_id_required')
        with self.transaction():
            old = self.db.execute('SELECT sends.status,origins.chat,sends.message FROM sends JOIN origins USING(origin) WHERE operation=?', (operation,)).fetchone()
            if not old or old[1] != chat_id or (old[0] == 'acked' and old[2] != message_id):
                raise Denied('exact_recipient_ack_required')
            self.db.execute("UPDATE sends SET status='acked',message=? WHERE operation=?", (message_id, operation))

    def revoke(self, origin):
        with self.transaction():
            self.db.execute('UPDATE origins SET revoked=1 WHERE origin=?', (origin,))
