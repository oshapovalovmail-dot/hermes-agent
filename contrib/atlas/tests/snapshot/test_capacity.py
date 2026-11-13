"""Synthetic private fixtures only; RED/GREEN against exact selected source."""
import importlib.util
import os
from pathlib import Path
import json
import sys
from concurrent.futures import ThreadPoolExecutor
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('ATLAS_FIX_SOURCE', ROOT/'candidate'))
LOADED=[]

@pytest.fixture(autouse=True)
def close_stores():
    yield
    for module in LOADED:
        store=getattr(module,'_STORE',None)
        if store is not None:store.close()
    LOADED.clear()

def load(name):
    path = SOURCE/'services/atlas-read'/name
    spec = importlib.util.spec_from_file_location(name.replace('.', '_')+os.urandom(4).hex(), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    LOADED.append(module)
    return module

@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def consume(pager, first, op):
    records = []
    answer = first
    while True:
        assert pager.wire_bytes(answer) <= 10000
        records += json.loads(answer['text'])['records']
        cursor = answer['pagination']['cursor']
        if cursor is None:
            break
        answer = pager.continuation(op, cursor, 1200)
    return records


def test_more_than_eight_active_mixed_cursors(profile):
    p = load('read_paging.py')
    held=[]
    for i in range(120):
        op=['staff.schema', 'search', 'tracker.get'][i%3]
        if i%2:
            arg={'page':i, 'opaque_cursor':'synthetic-private-upstream-'+str(i)}
            cursor=p.native_continuation(op,arg)['arguments']['continuation']
            held.append(('native',op,cursor,arg))
        else:
            value={'items':[{'id':j, 'text':'row '+str(j)} for j in range(100)]}
            first=p.capture(op,value,'fixture',1200,upstream={'complete':True})
            held.append(('pages',op,first,value))
    for kind,op,cursor,value in held:
        if kind=='native':
            assert p.native_arguments(op,cursor)==value
            assert p.native_arguments(op,cursor)==value
        else:
            assert consume(p,cursor,op)
            assert consume(p,cursor,op)==consume(p,cursor,op)


def test_prior_total_bytes_do_not_reject_small_reads(profile):
    p=load('read_paging.py')
    # Native opaque argument bytes bypass record splitting; exceeds the old aggregate cap.
    held=[]
    for i in range(12):
        arg={'page':i, 'opaque':'fixture.'*100000}
        held.append((p.native_continuation('search',arg)['arguments']['continuation'],arg))
    small=p.capture('staff.schema',{'ok':'small'},'fixture',1200)
    assert small['ok']
    for cursor,arg in held:
        assert p.native_arguments('search',cursor)==arg


def test_datalens_more_than_four_and_small_under_load(profile):
    d=load('datalens_backend.py')
    url='https://datalens.yandex-team.ru/abcdefghijklm'
    held=[]
    for i in range(20):
        value={'charts':[{'series':[{'data':[[j,j+i] for j in range(300)]}]}], 'metadata':[]}
        first=d.capture_pages(value,url,'data',1200)
        held.append(first)
    assert d.capture_pages({'charts':[]},url,'data',1200)['ok']
    for first in held:
        cursor=first['pagination']['cursor']
        pages=1
        while cursor:
            answer=d.continue_page(cursor,url,'data',1200)
            assert d.wire_bytes(answer)<=10000
            pages+=1;cursor=answer['pagination']['cursor']
        assert pages==first['pagination']['pages']


def test_more_than_fifty_one_native_branches(profile):
    p=load('read_paging.py'); args=[{'page':i} for i in range(100)]
    cursors=p.native_continuations('search',args)
    assert [p.native_arguments('search',r['arguments']['continuation']) for r in cursors]==args


def test_scope_expiry_replay(profile,monkeypatch,tmp_path):
    p=load('read_paging.py')
    now=[1000.0];monkeypatch.setattr(p.time,'monotonic',lambda:now[0])
    cursor=p.native_continuation('search',{'x':1})['arguments']['continuation']
    with pytest.raises(p.PageError,match='cursor_scope_denied'):p.native_arguments('staff.schema',cursor)
    foreign=tmp_path/'foreign';foreign.mkdir();monkeypatch.chdir(foreign)
    with pytest.raises(p.PageError,match='cursor_scope_denied|continuation_unavailable'):p.native_arguments('search',cursor)
    monkeypatch.chdir(profile);now[0]=1599.9
    assert p.native_arguments('search',cursor)=={'x':1}
    now[0]=1600.0
    with pytest.raises(p.PageError,match='continuation_unavailable'):p.native_arguments('search',cursor)


def test_concurrent_captures_keep_all_cursors(profile):
    p=load('read_paging.py')
    def task(i):
        arg={'n':i}; c=p.native_continuation('tracker',arg)['arguments']['continuation']
        return c,arg
    with ThreadPoolExecutor(max_workers=12) as pool:held=list(pool.map(task,range(160)))
    assert all(p.native_arguments('tracker',c)==arg for c,arg in held)
