"""Durable per-numeric-UID physical transit reservations, not logical task credit.

One fixed 2GiB byte pool per UID and bridge host; no count/rate/global byte cap.
All profiles use the process's trusted HERMES_HOME, never the caller's profile.
"""
import fcntl,os,re,sqlite3,time
from pathlib import Path
from atlas_bridge.contract import PrivateStore
from .protocol import Denied,directory

LIMIT=2*1024**3

class StagingBudget(PrivateStore):
 def __init__(self,root):
  super().__init__(Path(root)/'staging.sqlite')
  self.db.execute('CREATE TABLE IF NOT EXISTS reservations(store TEXT NOT NULL,id TEXT NOT NULL,uid TEXT NOT NULL,size INTEGER NOT NULL,PRIMARY KEY(store,id))')
  self.reconcile()
 def reconcile(self):
  # No time-based expiry of valid work: only exclusively locked dead stores.
  for (raw,) in self.db.execute('SELECT DISTINCT store FROM reservations').fetchall():
   root=Path(raw)
   if not root.exists():
    self.db.execute('DELETE FROM reservations WHERE store=?',(raw,));continue
   dfd=directory(root)
   lock=os.open('stream.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=dfd)
   try:
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:continue
    db=sqlite3.connect(root/'stream.sqlite',isolation_level=None)
    try:
     complete={r[0] for r in db.execute('SELECT id FROM exports')}
     has_owners=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='owners'").fetchone()
     expired={r[0] for r in db.execute('SELECT id FROM owners WHERE expires<=?',(time.time(),))} if has_owners else set()
     obj=directory(root/'objects')
     try:
      for (eid,) in self.db.execute('SELECT id FROM reservations WHERE store=?',(raw,)).fetchall():
       if eid in complete and eid not in expired:continue
       if re.fullmatch('[0-9a-f]{32}',eid) is None:raise Denied('invalid_staging_ledger')
       for name in (eid,eid+'.partial'):
        try:os.unlink(name,dir_fd=obj)
        except FileNotFoundError:pass
       db.execute('BEGIN IMMEDIATE')
       try:
        db.execute('DELETE FROM exports WHERE id=?',(eid,))
        if has_owners:db.execute('DELETE FROM owners WHERE id=?',(eid,))
        db.execute('COMMIT')
       except BaseException:db.execute('ROLLBACK');raise
       self.release(raw,eid)
      os.fsync(obj)
     finally:os.close(obj)
    finally:db.close()
   finally:os.close(lock);os.close(dfd)
 def reserve(self,store,eid,scope,size):
  uid=scope.get('user_id')
  if type(uid) is not str or re.fullmatch('[1-9][0-9]{0,19}',uid) is None:raise Denied('numeric_staging_principal_required')
  if type(size) is not int or not 0<=size<=LIMIT:raise Denied('bounded_staging_reservation_required')
  with self.transaction():
   old=self.db.execute('SELECT uid,size FROM reservations WHERE store=? AND id=?',(str(store),eid)).fetchone()
   used=self.db.execute('SELECT COALESCE(SUM(size),0) FROM reservations WHERE uid=?',(uid,)).fetchone()[0]
   if old and old[0]!=uid:raise Denied('staging_owner_conflict')
   if used-(old[1] if old else 0)+size>LIMIT:raise Denied('staging_byte_quota')
   self.db.execute('INSERT OR REPLACE INTO reservations VALUES (?,?,?,?)',(str(store),eid,uid,size))
 def release(self,store,eid):self.db.execute('DELETE FROM reservations WHERE store=? AND id=?',(str(store),eid))
 def close(self):self.db.close()
