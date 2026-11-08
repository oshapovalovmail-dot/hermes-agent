"""Minimal reminder state API, extracted from the local watcher; no collection automation."""
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def sanitize(text):
    return text.replace('MEDIA:', 'MEDIA：').replace('[[as_document]]', '(as_document)').replace('[[audio_as_voice]]', '(audio_as_voice)')


def link(chat, message_id):
    cid = str(chat['id'])
    if chat.get('source') == 'messenger':
        return 'https://messenger.360.yandex.ru/#/chats/' + quote(cid, safe='/_')
    if cid.startswith('-100'):
        return f'https://t.me/c/{cid[4:]}/{message_id}'
    if chat['id'] > 0:
        return f'tg://openmessage?user_id={cid}&message_id={message_id}'
    return f'tg://openmessage?chat_id={-chat["id"]}&message_id={message_id}'


class Store:
    def __init__(self, root, *, jobs=()):
        self.root = Path(root)
        self.jobs = frozenset(jobs)
        if self.root.is_symlink() or any(p.is_symlink() for p in self.root.parents):
            raise ValueError("Reminder state cannot traverse a symlink")
        if (self.root / 'watch.sqlite3').is_symlink():
            raise ValueError("Reminder database cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / 'watch.sqlite3', timeout=10)
        os.chmod(self.root / 'watch.sqlite3', 0o600)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.commit()

    def get(self, key):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, encode(value)))
