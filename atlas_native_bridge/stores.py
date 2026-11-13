"""Private durable inbox and replay metadata. No global message/rate allowance."""
import json
import os
from pathlib import Path
import sqlite3
from atlas_bridge.contract import PrivateStore, Denied, canonical, digest


class PendingInbox(PrivateStore):
    """Payload retained until native durable-ledger receipt; fingerprints survive ACK."""
    def __init__(self,path):
        super().__init__(path)
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('CREATE TABLE IF NOT EXISTS inbox(origin TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,payload TEXT,receipt TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS nonces(nonce TEXT PRIMARY KEY,fingerprint TEXT NOT NULL)')
    def close(self):self.db.close()
    def nonce(self,nonce,frame):
        fingerprint=digest(frame)
        with self.transaction():
            old=self.db.execute('SELECT fingerprint FROM nonces WHERE nonce=?',(nonce,)).fetchone()
            if old:
                if old[0]!=fingerprint:raise Denied('nonce_conflict')
                return False
            self.db.execute('INSERT INTO nonces VALUES (?,?)',(nonce,fingerprint));return True
    def put(self,origin,body,*,fingerprint=None):
        fingerprint=digest(body) if fingerprint is None else fingerprint
        with self.transaction():
            old=self.db.execute('SELECT fingerprint,receipt FROM inbox WHERE origin=?',(origin,)).fetchone()
            if old:
                if old[0]!=fingerprint:raise Denied('input_identity_conflict')
                return 'acked' if old[1] is not None else 'pending'
            self.db.execute('INSERT INTO inbox VALUES (?,?,?,NULL)',(origin,fingerprint,canonical(body).decode()))
            return 'new'
    def pending(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM inbox WHERE receipt IS NULL ORDER BY rowid')]
    def ack(self,origin,receipt):
        if (type(receipt) is not dict or set(receipt)!={'status','admission_id'} or
                receipt['status'] not in ('queued','started','terminal','unknown','refused','command') or
                type(receipt['admission_id']) is not str or not receipt['admission_id']):raise Denied('native_ledger_receipt_required')
        with self.transaction():
            row=self.db.execute('SELECT receipt FROM inbox WHERE origin=?',(origin,)).fetchone()
            if row is None:raise Denied('unknown_pending_input')
            if row[0] is not None:
                if json.loads(row[0])!=receipt:raise Denied('receipt_conflict')
                return
            self.db.execute('UPDATE inbox SET payload=NULL,receipt=? WHERE origin=?',(canonical(receipt).decode(),origin))
    def receipt(self,origin):
        row=self.db.execute('SELECT receipt FROM inbox WHERE origin=?',(origin,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None
