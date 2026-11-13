"""Fixed read-only DataLens reader; existing background CDP session only.

No credential/header/request extraction, arbitrary evaluation, URL or method API.
Only native dashboard read responses are projected; bounded view-only scrolling.
"""
from __future__ import annotations
from typing import Literal
import json
import math
import re
import threading
import uuid
from datetime import datetime, timezone
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

MAX_BYTES = 2_000_000
MAX_CHARS = 48000
ENDPOINT = 'http://127.0.0.1:9222'
INPUT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['url'],
    'properties': {
        'url': {'type': 'string', 'maxLength': 2048, 'description': 'Exact HTTPS DataLens dashboard URL; optional tab/state only.'},
        'view': {'type': 'string', 'enum': ['summary', 'data'], 'default': 'summary'},
        'max_chars': {'type': 'integer', 'minimum': 256, 'maximum': MAX_CHARS, 'default': 12000},
        'cursor': {'type': 'string', 'pattern': r'^[a-f0-9]{32}_[0-9]{1,6}$', 'maxLength': 39,
                   'description': 'Continue this process/profile capture with the same url and view. Expires after 600 seconds; no browser re-read. Omit for a fresh capture.'},
    },
}

class PolicyError(Exception): pass


def validate_url(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url) or any(c in url for c in ('\\', '%', '#')):
        raise PolicyError('url_denied')
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'datalens.yandex-team.ru' or not re.fullmatch(r'/[a-z0-9]{13}(?:-[A-Za-z0-9_-]{1,180})?/?', p.path):
        raise PolicyError('url_denied')
    fields = parse_qsl(p.query, keep_blank_values=True, max_num_fields=3)
    if len({k for k, _ in fields}) != len(fields): raise PolicyError('url_denied')
    for k, v in fields:
        if k not in ('tab', 'state') or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', v): raise PolicyError('url_denied')
    if p.query and '&'.join(k+'='+v for k,v in fields) != p.query: raise PolicyError('url_denied')
    return url


def redact(text):
    text = re.sub(r'\b\d{6,12}:[A-Za-z0-9_-]{30,}\b', '[REDACTED_BOT_CREDENTIAL]', str(text))
    text = re.sub(r'(?im)^(?:authorization|proxy-authorization|cookie|set-cookie)\s*:[^\r\n]*', '[REDACTED_HEADER]', str(text))
    text = re.sub(r'(?i)\b(?:Bearer|OAuth)\s+[^\s\x22\x27,;<>]+', '[REDACTED_AUTH]', text)
    text = re.sub(r'\b(?:gh[pousr]_|github_pat_|sk-|y0_|AQAD-|ya29\.)[A-Za-z0-9_.-]+\b', '[REDACTED_TOKEN]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[REDACTED_JWT]', text)
    text = re.sub(r'(?i)(?<![\w.-])([\x22\x27]?(?:[\w.-]*(?:token|password|passwd|secret|api[_-]?key|credential|authorization|cookie)|session(?:id)?|csrf|signature)[\x22\x27]?\s*[:=]\s*)(?:\x22[^\x22]*\x22|\x27[^\x27]*\x27|[^\s&,;<>}\]]+)', r'\1[REDACTED]', text)
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]+-----|\Z)', '[REDACTED_PRIVATE_KEY]', text)
    text = re.sub(r'(?<![A-Za-z0-9])[A-Za-z0-9_+=-]{48,}(?![A-Za-z0-9])', '[REDACTED_OPAQUE]', text)
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)


def clean_values(value):
    """Redact scalar strings before JSON encoding, never edit serialized JSON."""
    if isinstance(value, str): return redact(value)
    if isinstance(value, list): return [clean_values(v) for v in value]
    if isinstance(value, dict): return {k:clean_values(v) for k,v in value.items()}
    return value


def make_result(ok, code, source='', text='', max_chars=12000):
    max_chars = max(256, min(MAX_CHARS, max_chars)) if type(max_chars) is int else 12000
    try: obj=json.loads(text)
    except (ValueError,TypeError): obj=None
    clean=json.dumps(clean_values(obj),ensure_ascii=False) if obj is not None else redact(text)
    truncated=len(clean)>max_chars
    if truncated and obj is not None:
        # Errors retain bounded cause codes, not an unterminated JSON string.
        codes=re.findall(r'"code"\s*:\s*"([A-Za-z0-9_.-]{1,80})"',clean)[:2]
        clean=json.dumps({'omitted':True,'codes':codes},ensure_ascii=False)
        if len(clean)>max_chars:clean='{"omitted":true}'
    elif truncated: clean=clean[:max_chars]
    answer={'ok': ok, 'code': code, 'message': '', 'source': redact(source),
            'text': clean, 'truncated': truncated,
            'returned_chars': len(clean), 'untrusted': True}
    if wire_bytes(answer)>PAGE_WIRE_BYTES:
        codes=re.findall(r'"code"\s*:\s*"([A-Za-z0-9_.-]{1,80})"',clean)[:2]
        clean=json.dumps({'omitted':True,'codes':codes},ensure_ascii=False)
        answer.update(text=clean,returned_chars=len(clean),truncated=True)
    return answer


# Private encrypted process-lifetime spool; no host-file capability or upstream re-read.
# A cursor is a locator, never authorization; the parent guard must check EVERY call.
PAGE_WIRE_BYTES = 10_000
SNAPSHOT_TTL = 600
SNAPSHOT_MAX_BYTES = 8_000_000
_SNAPSHOT_LOCK = threading.RLock()


def _profile():
    return str(Path.cwd().resolve())

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
    except Exception:raise PolicyError('snapshot_storage_unavailable') from None

def _store():
    global _STORE
    if _STORE is None:
        try:_STORE=_store_module().SnapshotStore(_profile(), clock=lambda:time.monotonic())
        except Exception:raise PolicyError('snapshot_storage_unavailable') from None
    if _STORE.profile!=_profile():raise PolicyError('cursor_scope_denied')
    return _STORE


def _put(snapshot, values, ttl):
    meta={k:v for k,v in snapshot.items() if k not in ('pages','branches')}
    meta['part_count']=len(values)
    try:_store().put(snapshot['id'],meta,values,ttl)
    except _store_module().StoreError:raise PolicyError('snapshot_storage_unavailable') from None


def _get(key,index):
    try:return _store().get(key,index)
    except _store_module().StoreError:raise PolicyError('snapshot_storage_unavailable') from None


def wire_bytes(value):
    """Conservative SDK dual-emit envelope INCLUDING nested JSON escaping.

    ASCII escaping overestimates UTF-8 MCP serialization. Reserve 512 more bytes
    for SDK optional fields and the native result wrapper, without changing its cap.
    """
    text=json.dumps(value,ensure_ascii=False)
    wire={'content':[{'type':'text','text':text}],
          'structuredContent':value,'isError':not value['ok']}
    return len(json.dumps(wire,ensure_ascii=True).encode('utf-8'))+512


def page_records(value, path, limit):
    """Lossless typed paths: whole subtrees when small, leaves when necessary.

    Each record replaces exactly its path. Long strings use string_offset and
    concatenate in offset order; no raw JSON fragment is ever returned.
    Chart provenance/data precede dashboard metadata, including in large captures.
    """
    record={'path':path,'value':value}
    if len(json.dumps({'records':[record]},ensure_ascii=False))<=limit and len(json.dumps(record,ensure_ascii=True))<=1000:
        yield record; return
    if isinstance(value,dict) and value:
        keys=list(value)
        priority={'charts':0,'provenance':1,'indicators':2,'series':3,'tables':4,'metadata':9}
        for key in sorted(keys,key=lambda k:priority.get(k,5)):
            yield from page_records(value[key],path+[key],limit)
    elif isinstance(value,list) and value:
        for index,item in enumerate(value):
            yield from page_records(item,path+[index],limit)
    elif isinstance(value,str):
        offset=0
        while offset<len(value):
            # Pick the largest coherent string record that fits, including escapes.
            low=1; high=len(value)-offset; best=0
            while low<=high:
                n=(low+high)//2
                r={'path':path,'value':value[offset:offset+n],'string_offset':offset}
                if len(json.dumps({'records':[r]},ensure_ascii=False))<=limit and len(json.dumps(r,ensure_ascii=True))<=1000:best=n;low=n+1
                else:high=n-1
            if not best:raise PolicyError('page_budget_too_small')
            yield {'path':path,'value':value[offset:offset+best],'string_offset':offset}
            offset+=best
    else: raise PolicyError('page_budget_too_small')


def snapshot_page(snapshot, index, max_chars):
    pages=snapshot['pages']
    if not 0<=index<len(pages):raise PolicyError('cursor_unavailable')
    text=pages[index]
    if len(text)>max_chars:raise PolicyError('cursor_page_budget')
    more=index+1<len(pages)
    answer=make_result(True,'ok',snapshot['url'])
    answer.update(text=text,returned_chars=len(text),truncated=snapshot['capture_truncated'])
    answer['pagination']={**snapshot['coverage'],'page':index+1,'pages':len(pages),
        'has_more':more,'cursor':snapshot['id']+'_'+str(index+1) if more else None,
        'capture_complete':not more,'complete':False,
        'cursor_ttl_seconds':SNAPSHOT_TTL,
        'format':'records replace typed JSON paths; string_offset fragments concatenate; charts before metadata'}
    return answer


def capture_pages(out, url, view, max_chars):
    """Freeze a bounded projected capture only AFTER owned-target cleanup."""
    out=clean_values(out)
    charts=out.get('charts',[])
    series=[s for c in charts for s in c.get('series',[])]
    snapshot={'id':uuid.uuid4().hex,'profile':_profile(),'url':url,'view':view,'pages':[],
        'capture_truncated':out.get('truncated',False),
        'coverage':{'scope':'captured native reads in requested tab; other tabs/lazy charts not guaranteed',
            'captured_at':datetime.now(timezone.utc).isoformat(),
            'captured_metadata':len(out.get('metadata',[])),'captured_charts':len(charts),
            'captured_series':len(series),
            'captured_numeric_points':sum(numeric(p.get('y',p.get('value'))) is not None if isinstance(p,dict) else any(numeric(v) is not None for v in p[1:]) if isinstance(p,list) else numeric(p) is not None for s in series for p in s.get('data',[])),
            'captured_indicators':sum(len(c.get('indicators',[])) for c in charts),
            'capture_truncated':out.get('truncated',False)}}
    # Small records ensure they fit the fully escaped wire budget. A tiny user
    # max_chars may split further, but NEVER slices a JSON string or omits data.
    records=list(page_records(out,[],min(1000,max_chars)))
    current=[]; completed=[]
    for record in records:
        candidate=json.dumps({'records':current+[record]},ensure_ascii=False,separators=(',',':'))
        snapshot['pages']=[candidate]
        # Reserve the longest possible page counter, and an actual next cursor.
        probe=snapshot_page(snapshot,0,MAX_CHARS)
        probe['pagination'].update(page=999999,pages=999999,has_more=True,cursor=snapshot['id']+'_999999',capture_complete=False)
        if len(candidate)>max_chars or wire_bytes(probe)>PAGE_WIRE_BYTES:
            if not current:raise PolicyError('page_budget_too_small')
            yield_text=json.dumps({'records':current},ensure_ascii=False,separators=(',',':'))
            # Keep pages outside the temporary sizing snapshot.
            completed.append(yield_text)
            current=[record]
        else:current.append(record)
    if current:completed.append(json.dumps({'records':current},ensure_ascii=False,separators=(',',':')))
    snapshot['pages']=completed
    size=sum(len(t.encode('utf-8')) for t in completed)
    if len(completed)>999999 or size>SNAPSHOT_MAX_BYTES:raise PolicyError('snapshot_capacity')
    with _SNAPSHOT_LOCK:
        if len(completed)>1:_put(snapshot,completed,SNAPSHOT_TTL)
        return snapshot_page(snapshot,0,max_chars)


def continue_page(cursor, url, view, max_chars):
    if not isinstance(cursor,str) or not re.fullmatch(r'[a-f0-9]{32}_[0-9]{1,6}',cursor):raise PolicyError('invalid_argument')
    key,index=cursor.split('_')
    with _SNAPSHOT_LOCK:
        result=_get(key,int(index))
        if result is None:raise PolicyError('cursor_unavailable')
        snapshot,value=result
        if snapshot['profile']!=_profile() or snapshot['url']!=url or snapshot['view']!=view:raise PolicyError('cursor_scope_denied')
        snapshot['pages']=_store_module().StoredPages(snapshot['part_count'],int(index),value)
        return snapshot_page(snapshot,int(index),max_chars)


def scalar(value):
    if isinstance(value, str): return redact(value)[:1024]
    if value is None or type(value) in (int, bool): return value
    if type(value) is float and math.isfinite(value): return value
    return None


def numeric(value):
    """Finite native metric value, not a placeholder or boolean."""
    if type(value) in (int, float):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str) or len(value)>128: return None
    text=re.sub(r'[\s\u00a0\u202f]', '', value)
    text=re.sub(r'^[$€₽]', '', text)
    text=re.sub(r'%$', '', text)
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', text): return None
    number=float(text)
    return number if math.isfinite(number) else None


def provenance(payload):
    """Known business filters and source identity only; no rows/config/URLs."""
    out={'params':{},'sources':[]}
    cid=payload.get('id')
    if isinstance(cid,str) and re.fullmatch(r'[a-z0-9]{13}',cid): out['chart_id']=cid
    params=payload.get('params',{})
    if isinstance(params,dict):
        for key,value in list(params.items())[:128]:
            if not re.fullmatch(r'(?:jeeves_metric|jeeves_staff|event_date_[a-z0-9]+|platform_[a-z0-9]+|app_name_[a-z0-9]+)',key): continue
            values=value if isinstance(value,list) else [value]
            if len(values)>16 or any(type(v) not in (str,int,float,bool,type(None)) for v in values): continue
            out['params'][key]=[scalar(v) for v in values]
    sources=payload.get('sources',{})
    if isinstance(sources,dict):
        for source in list(sources.values())[:30]:
            if not isinstance(source,dict): continue
            did=source.get('datasetId'); status=source.get('status')
            if isinstance(did,str) and re.fullmatch(r'[a-z0-9]{13}',did) and type(status) is int:
                safe={'dataset_id':did,'status':status}
                if safe not in out['sources']:out['sources'].append(safe)
    return out


def project_error(payload, status):
    """Read only bounded error causes; case-insensitive/JSON-string nesting."""
    root=payload.get('error',payload) if isinstance(payload,dict) else {}
    out={'status':status}; queue=[(root,0)]; nested=[]; visited=0; sources=[]
    # Native errors may place causes beside `error`, not only below it.
    if isinstance(payload,dict) and 'error' in payload:
        siblings={k:v for k,v in list(payload.items())[:64] if k.lower() in
                  ('details','detail','cause','errors','innererror','originalerror','sources')}
        if siblings: queue.append((siblings,0))
    while queue and visited<64 and len(nested)<8:
        node,depth=queue.pop(0);visited+=1
        if depth>8:continue
        if isinstance(node,str):
            if len(node)<=16000:
                try:node=json.loads(node)
                except ValueError:node={'message':node}
        if isinstance(node,list):
            queue.extend((v,depth+1) for v in node[:8]);continue
        if not isinstance(node,dict):continue
        safe={}
        for key,value in list(node.items())[:64]:
            low=key.lower()
            if low in ('code','message','reason','description') and type(value) in (str,int):
                text=re.sub(r'https?://[^\s<>\x22\x27]+','[REDACTED_URL]',redact(str(value)))
                text=re.sub(r'(?is)\b(?:select|insert|update|delete)\s+.*','[QUERY_DETAIL_OMITTED]',text)
                safe[low]=text[:512]
            elif low in ('error','errors','details','detail','cause','innererror','originalerror','body'):
                queue.append((value,depth+1))
            elif low=='sources' and isinstance(value,dict):
                # Actual /api/run DTO: details.sources.<source_id>.body.
                # Never descend into the sibling source data/request/config.
                for source_id,source in list(value.items())[:8]:
                    if len(sources)>=8: break
                    if not isinstance(source_id,str) or not re.fullmatch(r'[a-z0-9]{13}(?:_[A-Za-z0-9_-]{1,48})?',source_id) or not isinstance(source,dict): continue
                    item={'source_id':source_id}
                    if type(source.get('status')) is int:item['status']=source['status']
                    sources.append(item)
                    queue.append((source.get('body',{}),depth+1))
        if visited==1:out.update(safe)
        elif safe:nested.append(safe)
        queue=queue[:64]
    if nested:out['nested_errors']=nested
    if sources:out['sources']=sources
    return out


def project(kind, payload):
    """Allowlisted chart/table scalars; never SQL, sources, configs or access lists."""
    if not isinstance(payload, dict): return {}
    if kind != 'run':
        obj = payload
        for _ in range(5):
            child = next((obj[k] for k in ('entry', 'result', 'dashboard') if isinstance(obj.get(k), dict)), None)
            if child is None: break
            obj = child
        data = obj.get('data', obj)
        if isinstance(data, str):
            try: data = json.loads(data)
            except ValueError: return {}
        if not isinstance(data, dict): return {}
        tabs = data.get('tabs')
        if not isinstance(tabs, list): return {}
        out = {'title': scalar(obj.get('name', obj.get('title'))), 'tabs': [], 'truncated': len(tabs)>30}
        for tab in tabs[:30]:
            if not isinstance(tab, dict): continue
            t = {'id': scalar(tab.get('id')), 'title': scalar(tab.get('title')), 'charts': []}
            items = tab.get('items', [])
            if not isinstance(items, list): continue
            if len(items)>200: out['truncated']=True
            for item in items[:200]:
                if not isinstance(item, dict) or not isinstance(item.get('data'), dict): continue
                d=item['data']; charts=d.get('tabs', [d])
                if not isinstance(charts, list): continue
                for c in charts[:30]:
                    if isinstance(c,dict) and c.get('chartId'):
                        t['charts'].append({'id':scalar(c['chartId']), 'title':scalar(c.get('title',d.get('title')))})
            out['tabs'].append(t)
        return out
    if payload.get('error'): return {}
    native_sources=payload.get('sources',{})
    if isinstance(native_sources,dict) and any(isinstance(s,dict) and type(s.get('status')) is int and s['status']>=400 for s in native_sources.values()): return {}
    data=payload.get('data')
    if isinstance(data,list) and payload.get('type')=='metric_wizard_node':
        indicators=[]; prov=provenance(payload)
        names=prov['params'].get('jeeves_metric',[])
        for item in data[:30]:
            if not isinstance(item,dict): continue
            current=item.get('content',{}).get('current',{}) if isinstance(item.get('content'),dict) else {}
            if not isinstance(current,dict): continue
            value=current.get('value'); number=numeric(value)
            if number is not None:
                indicators.append({'name':scalar(item.get('title') or (names[0] if names else '')), 'value':scalar(value), 'numeric_value':number})
        return {'indicators':indicators,'series':[],'tables':[],'provenance':prov,'truncated':len(data)>30} if indicators else {}
    if not isinstance(data,dict): return {}
    out={'series':[], 'tables':[], 'truncated':False}
    series=data.get('series',data.get('graphs',{}))
    series=series.get('data',[]) if isinstance(series,dict) else series
    if isinstance(series,list):
        if len(series)>30: out['truncated']=True
        for s in series[:30]:
            if not isinstance(s,dict): continue
            points=s.get('data',[])
            if not isinstance(points,list): continue
            if len(points)>500: out['truncated']=True
            if not s.get('name') and not any(isinstance(p,(dict,list)) for p in points): continue
            ps=[]
            for p in points[:500]:
                if isinstance(p,dict): ps.append({k:scalar(p[k]) for k in ('x','y','value','name','category') if k in p and not isinstance(p[k],(dict,list))})
                elif isinstance(p,list): ps.append([scalar(x) for x in p[:16]])
                else: ps.append(scalar(p))
            has_value=any(numeric(p.get('y',p.get('value'))) is not None if isinstance(p,dict) else (any(numeric(x) is not None for x in p[1:]) if isinstance(p,list) else numeric(p) is not None) for p in ps)
            if ps and has_value: out['series'].append({'name':scalar(s.get('name')), 'data':ps})
    table=data.get('table',data)
    if isinstance(table,dict) and isinstance(table.get('rows'),list):
        rows=table['rows']; safe=[]
        if len(rows)>200: out['truncated']=True
        for row in rows[:200]:
            cells=row.get('cells') if isinstance(row,dict) else row
            if isinstance(cells,list):
                if len(cells)>30: out['truncated']=True
                projected=[scalar(c.get('value',c.get('text'))) if isinstance(c,dict) else scalar(c) for c in cells[:30]]
                if any(x is not None and x!='' for x in projected):safe.append(projected)
        if safe: out['tables'].append({'rows':safe})
    if not out['series'] and not out['tables']:return {}
    out['provenance']=provenance(payload)
    return out


def chart_reads(payload, url):
    """Up to four distinct chart IDs from native requested-tab metadata.

    Never fabricate state/filter overrides; short state URLs use native capture only.
    All selector defaults, global parameters, widget parameters and aliases merge.
    """
    validate_url(url)
    query=dict(parse_qsl(urlsplit(url).query))
    if 'state' in query: return []
    try:
        entry=payload['entry']; data=entry['data']
        if isinstance(data,str): data=json.loads(data)
        tabs=data['tabs']
        tab=next((t for t in tabs if t.get('id')==query.get('tab')),None) if 'tab' in query else tabs[0]
        if not tab: return []
        params=dict(data.get('settings',{}).get('globalParams',{}))
        items=tab.get('items',[])
        for item in items:
            d=item.get('data',{})
            if item.get('type')=='control': params.update(d.get('defaults',{}))
            elif item.get('type')=='group_control':
                for control in d.get('group',[]): params.update(control.get('defaults',{}))
        aliases=tab.get('aliases',{}).get('default',[])
        reads=[]; seen=set()
        for item in items:
            if item.get('type')!='widget': continue
            for c in item.get('data',{}).get('tabs',[])[:1]:
                cid=c.get('chartId')
                if not isinstance(cid,str) or not re.fullmatch(r'[a-z0-9]{13}',cid) or cid in seen: continue
                merged={**params,**c.get('params',{})}
                for key,value in list(merged.items()):
                    if value:
                        for group in aliases:
                            if key in group:
                                for alias in group:
                                    if not merged.get(alias): merged[alias]=value
                if len(merged)>128: continue
                valid=True
                for key,value in merged.items():
                    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',key) or re.search(r'token|secret|password|cookie|csrf|credential|authorization|url|redirect',key,re.I): valid=False; break
                    values=value if isinstance(value,list) else [value]
                    if len(values)>64 or any(type(v) not in (str,int,float,bool,type(None)) or (isinstance(v,str) and (len(v)>1024 or re.search(r'https?://|javascript:',v,re.I))) for v in values): valid=False; break
                if not valid: continue
                reads.append({'id':cid,'params':merged}); seen.add(cid)
                if len(reads)>=4: return reads
        return reads
    except (KeyError,TypeError,ValueError,AttributeError,IndexError): return []


# Only location is touched on an unexpected page. No storage/cookies/headers.
READ_SCRIPT = r'''((expected) => {
 if (location.href !== expected) return {matches:false,pending:location.href==='about:blank'};
 return {matches:true, ready:document.readyState==='complete',
 title:(document.title||'').slice(0,512)};
})'''

# View-only, fixed bounded scroll of the owned dashboard document and its
# existing scroll containers. Never focus, click, fake visibility or dispatch fetch.
SCROLL_SCRIPT = r'''((expected, step) => {
 if (location.href !== expected) return {matches:false,pending:location.href==='about:blank'};
 const roots=[document.scrollingElement, ...Array.from(document.querySelectorAll('main,section,div')).slice(0,2000)
  .filter(e => e.clientHeight >= 200 && e.scrollHeight > e.clientHeight + 100
   && /auto|scroll/.test(getComputedStyle(e).overflowY))];
 const unique=[...new Set(roots.filter(Boolean))].slice(0,4);
 for (const e of unique) e.scrollTo({top:Math.min(step*Math.max(200,e.clientHeight*0.75),e.scrollHeight-e.clientHeight),behavior:'instant'});
 return {matches:true,scrolled:true};
})'''

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

class CDP:
    def __init__(self):
        from websockets.sync.client import connect
        self.deadline=time.monotonic()+38
        self.owned=None; self.session=None; self.counter=0
        self.pending={}; self.finished=[]; self.bytes=0; self.network_limited=False
        self.response_shapes=[]; self.closed_verified=False
        self.native_responses=[]; self.native_errors=[]; self.scroll_steps=0
        opener=build_opener(ProxyHandler({}),NoRedirect())
        with opener.open(ENDPOINT+'/json/version',timeout=3) as response: blob=response.read(16385)
        if len(blob)>16384: raise PolicyError('metadata_limit')
        ws=json.loads(blob).get('webSocketDebuggerUrl','')
        if not re.fullmatch(r'ws://127\.0\.0\.1:9222/devtools/browser/[A-Za-z0-9-]+',ws): raise PolicyError('metadata_invalid')
        self.ws=connect(ws,open_timeout=3,close_timeout=1,max_size=MAX_BYTES,proxy=None)

    def _ingest(self,msg):
        if msg.get('sessionId') != self.session: return
        method=msg.get('method'); p=msg.get('params',{})
        if method=='Network.responseReceived':
            r=p.get('response',{}); u=urlsplit(r.get('url',''))
            kind=None
            if u.scheme=='https' and u.netloc=='datalens.yandex-team.ru':
                kind={'/gateway/root/mix/getDashboardV2':'getDashboardV2','/gateway/root/us/getEntryByKey':'getEntryByKey','/api/run':'run'}.get(u.path)
            status=r.get('status')
            if kind and (status==200 or kind=='run' and type(status) in (int,float) and 400<=status<=599):
                if len(self.native_responses)>=120 or len(self.pending)>=120:
                    self.network_limited=True; return
                # No URL query, headers, cookies, initiator or request payload retained.
                self.native_responses.append({'kind':kind,'path':u.path,'status':int(status),'request_id':p['requestId']})
                self.pending[p['requestId']]=kind
        elif method=='Network.loadingFinished' and p.get('requestId') in self.pending:
            rid=p['requestId']; kind=self.pending.pop(rid)
            if len(self.finished)<120: self.finished.append((rid,kind,p.get('encodedDataLength',0)))
            else: self.network_limited=True
        elif method=='Network.loadingFailed': self.pending.pop(p.get('requestId'),None)

    def _rpc(self, method, params, session=None, cleanup=False):
        if method not in {'Target.createTarget','Target.attachToTarget','Target.closeTarget','Target.getTargetInfo','Network.enable','Network.getResponseBody','Page.navigate','Runtime.evaluate'}:
            raise PolicyError('method_denied')
        self.counter+=1; n=self.counter
        payload={'id':n,'method':method,'params':params}
        if session: payload['sessionId']=session
        self.ws.send(json.dumps(payload))
        rpc_timeout=8 if method=='Runtime.evaluate' and params.get('awaitPromise') else 4
        end=min(self.deadline,time.monotonic()+rpc_timeout) if not cleanup else time.monotonic()+1
        while time.monotonic()<end:
            msg=json.loads(self.ws.recv(timeout=max(.01,end-time.monotonic())))
            if msg.get('id')==n:
                if 'error' in msg:
                    error=msg['error']
                    self.last_protocol_error={'method':method,'code':error.get('code')}
                    if method=='Runtime.evaluate' and error.get('code')==-32000 and any(s in error.get('message','').lower() for s in ('execution context was destroyed','cannot find context','cannot find default execution context')):
                        raise PolicyError('navigation_context_pending')
                    if cleanup and method=='Target.getTargetInfo' and error.get('code')==-32602 and 'target' in error.get('message','').lower() and any(s in error.get('message','').lower() for s in ('not found','no target','invalid target')):
                        return {'absent':True}
                    raise PolicyError('protocol_error')
                return msg.get('result',{})
            self._ingest(msg)
        raise PolicyError('timeout')

    def create(self):
        result=self._rpc('Target.createTarget',{'url':'about:blank','background':True})
        self.owned=result['targetId']; return self.owned

    def attach(self,target):
        if target!=self.owned: raise PolicyError('target_denied')
        self.session=self._rpc('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
        return self.session

    def enable(self,session):
        self._rpc('Network.enable',{'maxTotalBufferSize':MAX_BYTES,'maxResourceBufferSize':MAX_BYTES},session)

    def navigate(self,url,session):
        validate_url(url)
        result=self._rpc('Page.navigate',{'url':url},session)
        if result.get('errorText') or result.get('isDownload'): raise PolicyError('navigation_failed')

    def _check(self,url,session):
        try:
            value=self._rpc('Runtime.evaluate',{'expression':READ_SCRIPT+'('+json.dumps(url)+')','returnByValue':True,'timeout':1000},session).get('result',{}).get('value',{})
        except PolicyError as error:
            if str(error)=='navigation_context_pending': return {'pending':True}
            raise
        if value.get('pending'): return value
        if not value.get('matches'): raise PolicyError('redirect_or_auth_required')
        return value

    def capture(self,url,view,session):
        out={'metadata':[], 'charts':[], 'truncated':False}
        seen=set(); last=time.monotonic(); last_scroll=last-2
        while time.monotonic()<self.deadline-2:
            page=self._check(url,session)
            if page.get('pending'): time.sleep(.1); continue
            if page.get('title'): out['title']=redact(page['title'])
            while self.finished:
                rid,kind,size=self.finished.pop(0)
                if size>MAX_BYTES-self.bytes: out['truncated']=True; continue
                if view=='summary' and kind=='run': continue
                event=next((r for r in self.native_responses if r['request_id']==rid),{})
                status=event.get('status',200)
                body=self._rpc('Network.getResponseBody',{'requestId':rid},session)
                raw=body.get('body','')
                if body.get('base64Encoded'): out['truncated']=True; continue
                length=len(raw.encode('utf-8')); self.bytes+=length
                if self.bytes>MAX_BYTES: out['truncated']=True; break
                try: obj=json.loads(raw)
                except ValueError: continue
                self.response_shapes.append({'kind':kind,'keys':sorted(obj)[:20] if isinstance(obj,dict) else []})
                if status!=200:
                    # Case-insensitive cause/detail fields projected in memory only.
                    self.native_errors.append(project_error(obj,status))
                    last=time.monotonic()
                    continue
                projected=project(kind,obj)
                if projected:
                    signature=json.dumps(projected,ensure_ascii=False,sort_keys=True)
                    if signature not in seen:
                        seen.add(signature); out['charts' if kind=='run' else 'metadata'].append(projected)
                        out['truncated']|=projected.get('truncated',False); last=time.monotonic()
                if self.bytes>=MAX_BYTES: break
            if view=='data' and out['metadata'] and not out['charts'] and self.scroll_steps<8 and time.monotonic()-last_scroll>=2:
                self.scroll_steps+=1; last_scroll=time.monotonic()
                expression=SCROLL_SCRIPT+'('+json.dumps(url)+','+str(self.scroll_steps)+')'
                value=self._rpc('Runtime.evaluate',{'expression':expression,'returnByValue':True,'timeout':1000},session).get('result',{}).get('value',{})
                if not value.get('matches'): raise PolicyError('redirect_or_auth_required')
            # A failed selector/widget does not cancel independent native reads.
            # Exhaust the existing deadline; no retries or new requests are made.
            if out['metadata'] and (view=='summary' or out['charts']) and time.monotonic()-last>3: break
            if self.bytes>=MAX_BYTES: break
            time.sleep(.15)
        out['truncated']|=self.network_limited
        out['native_scroll_steps']=self.scroll_steps
        if not out['metadata']: raise PolicyError('dashboard_metadata_unavailable')
        if view=='data' and not out['charts']:
            if self.native_errors: raise PolicyError('native_chart_http_'+str(self.native_errors[0]['status']))
            raise PolicyError('chart_data_unavailable')
        if self.native_errors: out['native_errors']=self.native_errors[:8]
        return out

    def cleanup(self,target):
        if target!=self.owned: raise PolicyError('target_denied')
        stop=time.monotonic()+4
        self._rpc('Target.closeTarget',{'targetId':target},cleanup=True)
        while time.monotonic()<stop:
            result=self._rpc('Target.getTargetInfo',{'targetId':target},cleanup=True)
            if result.get('absent'):
                self.closed_verified=True; return
            time.sleep(.05)
        raise PolicyError('cleanup_unverified')

    def close(self): self.ws.close()

class Backend:
    def read(self, url: str, view: Literal['summary','data']='summary', max_chars: int=12000, cursor: str|None=None) -> dict:
        driver=None; target=None; answer=None; source=''; out=None
        try:
            validate_url(url); source=url
            if view not in ('summary','data') or type(max_chars) is not int: raise PolicyError('invalid_argument')
            max_chars=max(256,min(MAX_CHARS,max_chars))
            if cursor is not None:return continue_page(cursor,url,view,max_chars)
            driver=CDP(); target=driver.create(); session=driver.attach(target)
            driver.enable(session); driver.navigate(url,session)
            out=driver.capture(url,view,session)
            answer=make_result(True,'ok',url)
        except PolicyError as error:
            answer=make_result(False,str(error),source)
            if str(error).startswith('native_chart_http_'):
                answer=make_result(False,str(error),source,json.dumps({'native_errors':driver.native_errors[:8]},ensure_ascii=False),max_chars)
                answer['message']='An automatically authenticated native UI chart read was rejected. No manual fetch, credentials or security headers were extracted or replayed.'
        except TimeoutError: answer=make_result(False,'timeout',source)
        except Exception: answer=make_result(False,'cdp_unavailable',source)
        finally:
            if driver:
                try:
                    if target: driver.cleanup(target)
                except Exception:
                    answer=make_result(False,'cleanup_unverified',source)
                    answer['message']='Owned target closure could not be verified. No user targets were enumerated or controlled.'
                finally:
                    try: driver.close()
                    except Exception: pass
        if answer['ok'] and out is not None:
            try:return capture_pages(out,url,view,max_chars)
            except PolicyError as error:return make_result(False,str(error),source)
        return answer
