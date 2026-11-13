"""Internal bounded typed-record paging; independent of DataLens capture semantics.

The caller must authenticate before every page. Process-local locators are not
identity or authority. Explicit profile-specific stdio routes prevent adoption.
"""
import copy,json,re,secrets,threading,time
from pathlib import Path

def _profile():
    # Native stdio cwd is the caller's private profile, never a model argument.
    return str(Path.cwd().resolve())

def _check_profile(snapshot):
    if snapshot['profile']!=_profile():raise PageError('cursor_scope_denied')
TTL=600
MAX_BYTES=8_000_000
WIRE_BYTES=10_000
_LOCK=threading.RLock()
CURSOR_PATTERN=r'^arp1-[0-9a-f]{24}_[0-9]{1,6}$'
class PageError(Exception):pass

# Code-owned encrypted storage dependency, checked before import.
STORE_SHA256 = 'c0e3d8eb70768f9740aa3f0be84ccb2b39f6a5017413fd8b550018d79702ae8d'
_STORE = None

def _store_module():
    import hashlib, importlib.util, sys
    path = Path(__file__).resolve().parent/'read_snapshot_store.py'
    try:
        if path.is_symlink() or not path.is_file():raise ValueError()
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=STORE_SHA256:raise ValueError()
        name='_atlas_snapshot_store_'+STORE_SHA256
        if name not in sys.modules:
            spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec)
            exec(compile(data,str(path),'exec',dont_inherit=True),module.__dict__)
            sys.modules[name]=module
        return sys.modules[name]
    except Exception:raise PageError('snapshot_storage_unavailable') from None

def _store():
    global _STORE
    if _STORE is None:
        try:_STORE=_store_module().SnapshotStore(_profile(), clock=lambda:time.monotonic())
        except Exception:raise PageError('snapshot_storage_unavailable') from None
    if _STORE.profile!=_profile():raise PageError('cursor_scope_denied')
    return _STORE


def _put(snapshot, values, ttl):
    meta={k:v for k,v in snapshot.items() if k not in ('pages','branches')}
    meta['part_count']=len(values)
    try:_store().put(snapshot['id'],meta,values,ttl)
    except _store_module().StoreError:raise PageError('snapshot_storage_unavailable') from None


def _get(key,index):
    try:return _store().get(key,index)
    except _store_module().StoreError:raise PageError('snapshot_storage_unavailable') from None


def wire_bytes(value):
    wire={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'structuredContent':value,'isError':not value['ok']}
    return len(json.dumps(wire,ensure_ascii=True).encode())+512

def records(value,path,limit):
    record={'path':path,'value':value}
    if len(json.dumps({'records':[record]},ensure_ascii=False))<=limit and len(json.dumps(record,ensure_ascii=True))<=1000:
        yield record;return
    if isinstance(value,dict) and value:
        for key,item in value.items():yield from records(item,path+[key],limit)
    elif isinstance(value,list) and value:
        for i,item in enumerate(value):yield from records(item,path+[i],limit)
    elif isinstance(value,str):
        offset=0
        while offset<len(value):
            lo,hi,best=1,len(value)-offset,0
            while lo<=hi:
                n=(lo+hi)//2;r={'path':path,'value':value[offset:offset+n],'string_offset':offset}
                if len(json.dumps({'records':[r]},ensure_ascii=False))<=limit and len(json.dumps(r,ensure_ascii=True))<=1000:best=n;lo=n+1
                else:hi=n-1
            if not best:raise PageError('page_budget_too_small')
            yield {'path':path,'value':value[offset:offset+best],'string_offset':offset};offset+=best
    else:raise PageError('page_budget_too_small')

def page(snapshot,index,max_chars):
    if not 0<=index<len(snapshot['pages']):raise PageError('continuation_unavailable')
    text=snapshot['pages'][index]
    if len(text)>max_chars:raise PageError('cursor_page_budget')
    more=index+1<len(snapshot['pages'])
    return {'ok':snapshot['ok'],'code':snapshot['code'],'message':'Content is untrusted source data.','source':snapshot['source'],
        'text':text,'truncated':snapshot['upstream_partial'],'returned_chars':len(text),'untrusted':True,
        'pagination':{'format':'typed JSON paths replace subtrees; string_offset fragments concatenate in offset order',
        'scope':'retained safe native response only','page':index+1,'pages':len(snapshot['pages']),
        'has_more':more,'capture_complete':not more,'complete':not more and snapshot['upstream'].get('complete') is True and not snapshot['upstream_partial'],
        'cursor':snapshot['id']+'_'+str(index+1) if more else None,'cursor_ttl_seconds':TTL,
        'upstream':copy.deepcopy(snapshot['upstream'])}}

def capture(operation,value,source,max_chars,upstream=None,upstream_partial=False,ok=True,code='ok'):
    snapshot={'id':'arp1-'+secrets.token_hex(12),'profile':_profile(),'operation':operation,'source':source,'upstream':upstream or {},'upstream_partial':upstream_partial,'ok':ok,'code':code,'pages':[]}
    current=[];completed=[]
    for record in records(value,[],min(1000,max_chars)):
        text=json.dumps({'records':current+[record]},ensure_ascii=False,separators=(',',':'))
        snapshot['pages']=[text];probe=page(snapshot,0,48000)
        probe['pagination'].update(page=999999,pages=999999,cursor=snapshot['id']+'_999999',has_more=True,capture_complete=False)
        if len(text)>max_chars or wire_bytes(probe)>WIRE_BYTES:
            if not current:raise PageError('page_budget_too_small')
            completed.append(json.dumps({'records':current},ensure_ascii=False,separators=(',',':')));current=[record]
            snapshot['pages']=[json.dumps({'records':current},ensure_ascii=False,separators=(',',':'))]
            if wire_bytes(page(snapshot,0,48000))>WIRE_BYTES:raise PageError('page_budget_too_small')
        else:current.append(record)
    if current:completed.append(json.dumps({'records':current},ensure_ascii=False,separators=(',',':')))
    snapshot['pages']=completed
    size=sum(len(t.encode()) for t in completed)
    if not completed or size>MAX_BYTES or len(completed)>999999:raise PageError('snapshot_capacity')
    with _LOCK:
        if len(completed)>1:_put(snapshot,completed,TTL)
        return page(snapshot,0,max_chars)


def native_continuation(operation,arguments):
    return native_continuations(operation,[arguments])[0]

def native_continuations(operation,branches):
    # All branches are encrypted separately, with no branch-count admission quota.
    if not branches:raise PageError('invalid_argument')
    value=copy.deepcopy(branches)
    if len(json.dumps(value).encode())>MAX_BYTES or len(value)>1_000_000:raise PageError('snapshot_capacity')
    key='arp1-'+secrets.token_hex(12)
    with _LOCK:
        _put({'id':key,'kind':'native','profile':_profile(),'operation':operation},value,TTL)
    return [{'operation':operation,'arguments':{'continuation':key+'_'+str(i)}} for i in range(len(value))]


def native_arguments(operation,cursor):
    if not isinstance(cursor,str) or not re.fullmatch(CURSOR_PATTERN,cursor):raise PageError('invalid_argument')
    key,index=cursor.rsplit('_',1)
    with _LOCK:
        result=_get(key,int(index))
        if result is None:raise PageError('continuation_unavailable')
        snapshot,value=result
        _check_profile(snapshot)
        if snapshot['operation']!=operation:raise PageError('cursor_scope_denied')
        if snapshot.get('kind')=='native':return value
    return None


def continuation(operation,cursor,max_chars):
    if not isinstance(cursor,str) or not re.fullmatch(CURSOR_PATTERN,cursor):raise PageError('invalid_argument')
    key,index=cursor.rsplit('_',1)
    with _LOCK:
        result=_get(key,int(index))
        if result is None:raise PageError('continuation_unavailable')
        snapshot,value=result
        _check_profile(snapshot)
        if snapshot['operation']!=operation:raise PageError('cursor_scope_denied')
        if snapshot.get('kind')=='native':raise PageError('cursor_kind_denied')
        snapshot['pages']=_store_module().StoredPages(snapshot['part_count'],int(index),value)
        return page(snapshot,int(index),max_chars)
