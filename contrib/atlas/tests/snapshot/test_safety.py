import json
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
import pytest
from test_capacity import load, profile, consume


def reconstruct(records):
    root=None
    for r in records:
        path=r['path'];value=r['value']
        if not path:
            if 'string_offset' in r:
                root=(root or '')+value
            else:root=value
            continue
        if root is None:root=[] if isinstance(path[0],int) else {}
        current=root
        for i,key in enumerate(path):
            if isinstance(current,list):
                while len(current)<=key:current.append(None)
            if i==len(path)-1:
                if 'string_offset' in r:
                    old=current[key] if isinstance(current,list) else current.get(key)
                    assert len(old or '')==r['string_offset']
                    value=(old or '')+value
                current[key]=value
            else:
                nextkey=path[i+1]
                child=current[key] if isinstance(current,list) else current.get(key)
                if child is None:
                    child=[] if isinstance(nextkey,int) else {};current[key]=child
                current=child
    return root


def test_lossless_escaped_unicode_empty_and_replay(profile):
    p=load('read_paging.py')
    value={'unicode':'Привет\\\"\n😀 '*500,'nested':[{},[],None,False,17,{'x':list(range(100))}],'empty':''}
    first=p.capture('search',value,'fixture',1200,upstream={'complete':True})
    assert reconstruct(consume(p,first,'search'))==value
    assert reconstruct(consume(p,first,'search'))==value
    cursor=first['pagination']['cursor']
    with pytest.raises(p.PageError,match='cursor_scope_denied'):p.continuation('different',cursor,1200)
    with pytest.raises(p.PageError,match='cursor_page_budget'):p.continuation('search',cursor,1)
    assert reconstruct(consume(p,first,'search'))==value


def test_private_encrypted_anonymous_inode_permissions_cleanup(profile,monkeypatch):
    p=load('read_paging.py');module=p._store_module()
    original=module.os.open;captured=[]
    def observe(path,flags,*args,**kw):
        fd=original(path,flags,*args,**kw)
        if str(path).startswith('spool-') and flags & os.O_CREAT:captured.append(os.dup(fd))
        return fd
    monkeypatch.setattr(module.os,'open',observe)
    sentinel='fixture-sensitive-native-cursor-DO-NOT-PERSIST'
    cursor=p.native_continuation('search',{'cursor':sentinel})['arguments']['continuation']
    store=p._STORE
    try:
        fd=captured[0];info=os.fstat(fd)
        assert stat.S_IMODE(info.st_mode)==0o600 and info.st_uid==os.getuid() and info.st_nlink==0
        data=os.pread(fd,info.st_size,0)
        assert data.startswith(b'SQLite format 3')
        assert sentinel.encode() not in data and b'search' not in data and str(profile).encode() not in data
        assert stat.S_IMODE((profile/'.atlas-read-spool').stat().st_mode)==0o700
        assert list((profile/'.atlas-read-spool').iterdir())==[]
        assert p.native_arguments('search',cursor)=={'cursor':sentinel}
        assert store.db.execute('PRAGMA cache_size').fetchone()[0]==-256
        assert store.db.execute('PRAGMA mmap_size').fetchone()[0]==0
    finally:
        store.close()
        for fd in captured:os.close(fd)
    assert not store.worker.is_alive() and store.cipher is None


@pytest.mark.parametrize('kind',['symlink','world-readable'])
def test_storage_directory_fail_closed_without_following(profile,kind,tmp_path):
    p=load('read_paging.py');directory=profile/'.atlas-read-spool';outside=profile/'outside';outside.mkdir()
    if kind=='symlink':directory.symlink_to(outside,target_is_directory=True)
    else:
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)  # Defeat the runner's private umask for this negative fixture.
    with pytest.raises(p.PageError,match='snapshot_storage_unavailable'):
        p.native_continuation('search',{'fixture':1})
    assert list(outside.iterdir())==[]
    # A valid single-page result needs no storage admission.
    assert p.capture('staff.schema',{'x':1},'fixture',1200)['ok']


def test_disk_full_real_sqlite_failure_preserves_prior_cursor(profile):
    p=load('read_paging.py')
    first=p.native_continuation('search',{'fixture':'original'})['arguments']['continuation']
    db=p._STORE.db
    db.execute('PRAGMA max_page_count='+str(db.execute('PRAGMA page_count').fetchone()[0]))
    with pytest.raises(p.PageError,match='snapshot_storage_unavailable'):
        p.native_continuation('search',{'fixture':'large.'*100000})
    assert p.native_arguments('search',first)=={'fixture':'original'}
    assert p.capture('staff.schema',{'x':1},'fixture',1200)['ok']


def test_ttl_cleanup_without_any_new_call(profile):
    p=load('read_paging.py');cursor=p.native_continuation('search',{'x':1})['arguments']['continuation']
    store=p._STORE;store.clock=lambda:float('inf')
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        with store.lock:
            count=store.db.execute('SELECT count(*) FROM snapshots').fetchone()[0]
        if count==0:break
        time.sleep(.05)
    assert count==0
    with store.lock:assert store.db.execute('SELECT count(*) FROM parts').fetchone()[0]==0
    with pytest.raises(p.PageError,match='continuation_unavailable'):p.native_arguments('search',cursor)


def test_wrong_process_key_and_tamper_fail_closed(profile):
    p=load('read_paging.py');cursor=p.native_continuation('search',{'x':1})['arguments']['continuation']
    store=p._STORE;key=cursor.rsplit('_',1)[0]
    with store.db:store.db.execute('UPDATE parts SET data=? WHERE id=?',(b'bad-ciphertext',key))
    with pytest.raises(p.PageError,match='snapshot_storage_unavailable'):p.native_arguments('search',cursor)


def test_datalens_profile_url_view_and_expiry(profile,monkeypatch):
    d=load('datalens_backend.py');url='https://datalens.yandex-team.ru/abcdefghijklm'
    value={'charts':[{'series':[{'data':[[i,i+1] for i in range(300)]}]}],'metadata':[]}
    first=d.capture_pages(value,url,'data',1200);cursor=first['pagination']['cursor']
    for u,v in [(url+'?tab=x','data'),(url,'summary')]:
        with pytest.raises(d.PolicyError,match='cursor_scope_denied'):d.continue_page(cursor,u,v,1200)
    records=json.loads(first['text'])['records'];answer=first
    while answer['pagination']['cursor']:
        answer=d.continue_page(answer['pagination']['cursor'],url,'data',1200)
        records+=json.loads(answer['text'])['records']
    assert reconstruct(records)==value
    foreign=profile/'foreign';foreign.mkdir();monkeypatch.chdir(foreign)
    with pytest.raises(d.PolicyError,match='cursor_scope_denied'):d.continue_page(cursor,url,'data',1200)
    monkeypatch.chdir(profile);d._STORE.clock=lambda:float('inf')
    with pytest.raises(d.PolicyError,match='cursor_unavailable'):d.continue_page(cursor,url,'data',1200)
