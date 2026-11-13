"""Atlas candidate: closed typed native Tracker/Wiki READ surface.

No shell, arbitrary endpoint, manual auth, credential capture or activation.
Deploy this file and the exact hash-pinned read_catalog.json together. Returned
source text is always untrusted data. runner injection is host/test Python only,
never part of INPUT_SCHEMA; production uses the fixed official native client.
"""
from __future__ import annotations
import base64
import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import subprocess
import threading
import time
from urllib.parse import urlsplit
import zipfile
import xml.etree.ElementTree as ET

MCP_CLI = '/usr/bin/false'
CATALOG_SHA256 = 'b9917cb78fe780d9c0f4bcc49561c72d7b48054a0f799e471d888b971e5ac254'
MAX_CHARS=48000
MAX_BYTES=16*1024*1024
TIMEOUT=75
_raw=(Path(__file__).resolve().parent/'tracker_wiki_catalog.json').read_bytes()
if hashlib.sha256(_raw).hexdigest()!=CATALOG_SHA256:
    raise RuntimeError('read_catalog_integrity')
_catalog=json.loads(_raw)
OPERATIONS={r['action']:r for r in _catalog['operations'] if r['access']=='read'}
_bound={'type':'integer','minimum':256,'maximum':MAX_CHARS,'default':12000}
_HANDLE={'type':'string','pattern':r'^ac1-[0-9a-f]{24}$'}
_HANDLE_ARGS={'type':'object','properties':{'continuation':_HANDLE},'required':['continuation'],'additionalProperties':False}
def call_shape(native):
    # Either the native typed arguments OR one backend-issued continuation.
    return {'type':'object','properties':dict(native.get('properties',{}),continuation=_HANDLE),
            'additionalProperties':False,'oneOf':[native,_HANDLE_ARGS]}
INPUT_SCHEMA={'type':'object','properties':{'operation':{'type':'string','enum':sorted(OPERATIONS)},
              'arguments':{'type':'object'},'max_chars':_bound},'required':['operation','arguments'],
              'additionalProperties':False,'oneOf':[
    {'properties':{'operation':{'const':op},'arguments':call_shape(entry['readSchema'])},'required':['operation','arguments']}
    for op,entry in sorted(OPERATIONS.items())]}
# Opaque native cursors may contain encoded PII. Keep them private; the short
# random reference is not an upstream bearer credential or an impersonation API.
# One-hour process-local handles use private encrypted anonymous storage.
# No unexpired handle is evicted because of other reads. Re-run after restart/expiry.
_CONTINUATION_LOCK=threading.RLock()

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
    except Exception:raise ReadError('snapshot_storage_unavailable') from None

def _store():
    global _STORE
    if _STORE is None:
        try:_STORE=_store_module().SnapshotStore(_profile(), clock=lambda:time.monotonic())
        except Exception:raise ReadError('snapshot_storage_unavailable') from None
    if _STORE.profile!=_profile():raise ReadError('cursor_scope_denied')
    return _STORE


def _put(snapshot, values, ttl):
    meta={k:v for k,v in snapshot.items() if k not in ('pages','branches')}
    meta['part_count']=len(values)
    try:_store().put(snapshot['id'],meta,values,ttl)
    except _store_module().StoreError:raise ReadError('snapshot_storage_unavailable') from None


def _get(key,index):
    try:return _store().get(key,index)
    except _store_module().StoreError:raise ReadError('snapshot_storage_unavailable') from None



def continuation_for(operation,arguments):
    if scrub(arguments)==arguments:
        return {'operation':operation,'arguments':arguments}
    handle='ac1-'+secrets.token_hex(12)
    with _CONTINUATION_LOCK:
        _put({'id':handle,'profile':_profile(),'operation':operation},[arguments],3600)
    return {'operation':operation,'arguments':{'continuation':handle}}


def resolve_continuation(operation,arguments):
    if set(arguments)!={'continuation'}: return arguments
    handle=arguments['continuation']
    if not isinstance(handle,str) or not re.fullmatch(r'ac1-[0-9a-f]{24}',handle):raise ReadError('continuation_expired')
    with _CONTINUATION_LOCK:
        result=_get(handle,0)
        if result is None or result[0]['operation']!=operation:raise ReadError('continuation_expired')
        return result[1]


class ReadError(Exception):
    def __init__(self,code): self.code=code; super().__init__(code)

def validate(value,schema):
    """Validate the assertions used by the pinned primary draft-2020-12 schemas.

    Does not silently accept unsupported assertion keywords. Metadata is ignored.
    This backend has no dependency on a host jsonschema package.
    """
    supported={'$schema','title','description','default','examples','deprecated','readOnly','writeOnly',
               'type','const','enum','anyOf','oneOf','allOf','properties','required','additionalProperties',
               'propertyNames','items','minItems','maxItems','uniqueItems','minLength','maxLength','pattern',
               'format','minimum','maximum','exclusiveMinimum','exclusiveMaximum'}
    if set(schema)-supported: raise ReadError('schema_assertion_unsupported')
    if 'const' in schema and (type(value)!=type(schema['const']) or value!=schema['const']): return False
    if 'enum' in schema and not any(type(value)==type(v) and value==v for v in schema['enum']): return False
    for key in ('anyOf','oneOf','allOf'):
        if key in schema:
            n=sum(validate(value,s) for s in schema[key])
            if key=='anyOf' and n==0 or key=='oneOf' and n!=1 or key=='allOf' and n!=len(schema[key]): return False
    types=schema.get('type')
    if types:
        types=types if isinstance(types,list) else [types]
        matches={'object':type(value) is dict,'array':type(value) is list,'string':type(value) is str,
                 'integer':type(value) is int,'number':type(value) in (int,float) and math.isfinite(value),
                 'boolean':type(value) is bool,'null':value is None}
        if not any(matches.get(t,False) for t in types): return False
    if isinstance(value,dict):
        if not all(k in value for k in schema.get('required',[])): return False
        props=schema.get('properties',{}); extra=schema.get('additionalProperties',True)
        for key,item in value.items():
            if not isinstance(key,str): return False
            if 'propertyNames' in schema and not validate(key,schema['propertyNames']): return False
            if key in props:
                if not validate(item,props[key]): return False
            elif extra is False: return False
            elif isinstance(extra,dict) and not validate(item,extra): return False
    if isinstance(value,list):
        if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',10**9): return False
        if 'items' in schema and not all(validate(x,schema['items']) for x in value): return False
        if schema.get('uniqueItems') and len({json.dumps(x,sort_keys=True) for x in value})!=len(value): return False
    if isinstance(value,str):
        if len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',10**9): return False
        if 'pattern' in schema and not re.search(schema['pattern'],value): return False
        if schema.get('format')=='date-time':
            try:
                parsed=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
                if parsed.tzinfo is None: return False
            except ValueError: return False
        elif 'format' in schema: raise ReadError('schema_format_unsupported')
    if type(value) in (int,float):
        if not math.isfinite(value): return False
        if 'minimum' in schema and value<schema['minimum'] or 'maximum' in schema and value>schema['maximum']: return False
        if 'exclusiveMinimum' in schema and value<=schema['exclusiveMinimum'] or 'exclusiveMaximum' in schema and value>=schema['exclusiveMaximum']: return False
    return True

def redact(text):
    # Whole native string first, THEN serialization, THEN final truncation.
    text=re.sub(r'-----BEGIN [^-]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY)-----[\s\S]*?(?:-----END [^-]+-----|\Z)','[REDACTED_PRIVATE_KEY]',text)
    text=re.sub(r'(?im)^(?:[+\- ]?)(?:authorization|proxy-authorization|cookie|set-cookie)\s*:[^\r\n]*','[REDACTED_HEADER]',text)
    text=re.sub(r'(?i)\b(?:Bearer|OAuth)\s+[^\s\x22\x27,;<>]+','[REDACTED_AUTH]',text)
    text=re.sub(r'\b\d{6,12}:[A-Za-z0-9_-]{30,}\b','[REDACTED_BOT_CREDENTIAL]',text)
    text=re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+|y0_[A-Za-z0-9_-]+|AQAD-[A-Za-z0-9_-]+|ya29\.[A-Za-z0-9_.-]+)\b','[REDACTED_TOKEN]',text)
    text=re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b','[REDACTED_JWT]',text)
    text=re.sub(r'(?i)([\x22\x27]?(?:[\w.-]*(?:token|password|passwd|secret|api[_-]?key|credential|authorization|cookie)|session(?:id)?|csrf|signature)[\x22\x27]?\s*[:=]\s*)(?:[\x22][^\x22]*[\x22]|[\x27][^\x27]*[\x27]|[^\s&,;<>}\]]+)',r'\1[REDACTED]',text)
    # Bearer download links are capabilities, never normal source attribution.
    text=re.sub(r'https?://[^\s\x22\x27<>]*(?:\?|&)(?:[^\s\x22\x27<>]*)',lambda m: '[REDACTED_SIGNED_URL]' if re.search(r'(?i)(?:signature|sign=|token|credential|x-amz|x-goog|key-pair|expires=|auth=)',m[0]) else m[0],text)
    text=re.sub(r'(?i)[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}','[REDACTED_EMAIL]',text)
    text=re.sub(r'(?<!\w)\+\d[\d ()-]{8,}\d(?!\w)','[REDACTED_PHONE]',text)
    text=re.sub(r'(?<![A-Za-z0-9])[A-Za-z0-9_+=-]{48,}(?![A-Za-z0-9])','[REDACTED_OPAQUE]',text)
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)

SENSITIVE=re.compile(r'(?i)(?:password|passwd|secret|token|api[_-]?key|credential|authorization|cookie|sessionid|csrf|signature|identity|cloud_uid|passport|personal_?email|email|phone|birthday|birth_date|access_lists|access_policy)')
BASE64_KEYS={'content_base64','contentBase64','data_base64','dataBase64','base64','base64_content','file_base64'}

def project_binary(encoded):
    try: raw=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError): return {'content_status':'invalid_base64'}
    if len(raw)>MAX_BYTES: raise ReadError('upstream_output_limit')
    meta={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    try:
        text=raw.decode('utf-8')
        if '\x00' in text: raise UnicodeError
        return meta|{'content_status':'redacted_text','text':redact(text)}
    except UnicodeError: pass
    # Extract safe text from common zip-based Office formats in memory only.
    if raw.startswith(b'PK'):
        try:
            parts=[]; total=0
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for item in archive.infolist():
                    if item.filename.startswith(('word/','xl/','ppt/')) and item.filename.endswith('.xml'):
                        total+=item.file_size
                        if total>MAX_BYTES or item.compress_size==0 or item.file_size/item.compress_size>200:
                            raise ReadError('upstream_archive_limit')
                        node=ET.fromstring(archive.read(item))
                        parts.extend(n.text for n in node.iter() if n.text and n.tag.rsplit('}',1)[-1] in ('t','v'))
            if parts: return meta|{'content_status':'redacted_office_text','text':redact('\n'.join(parts)),'partial':True}
        except ReadError: raise
        except (zipfile.BadZipFile,ET.ParseError,ValueError): pass
    return meta|{'content_status':'binary_not_exported','message':'Raw binary/base64 is not safe model text; metadata retained, content projection unavailable.','partial':True}

def scrub(value):
    if isinstance(value,str): return redact(value)
    if isinstance(value,list): return [scrub(v) for v in value]
    if isinstance(value,dict):
        if value.get('restricted') is True:
            return {k:scrub(value[k]) for k in ('key','id','restricted','availability') if k in value}
        if value.get('availability') in ('restricted','unavailable'):
            return {k:scrub(value[k]) for k in ('key','id','availability') if k in value}
        out={}
        for key,item in value.items():
            if key in BASE64_KEYS:
                out['decoded_content']=project_binary(item)
            elif SENSITIVE.search(key): out[key]='[REDACTED]'
            elif re.search(r'(?i)(?:downloadurl|signedurl|presigned)',key): out[key]='[REDACTED_CAPABILITY_URL]'
            else: out[key]=scrub(item)
        return out
    return value

def result(ok,code,source='',text='',max_chars=12000,pagination=None):
    clean=redact(text); bounded=clean[:max_chars]
    out={'ok':ok,'code':code,'message':'','source':source,'text':bounded,'truncated':len(clean)>len(bounded),
         'returned_chars':len(bounded),'untrusted':True}
    if pagination is not None:
        if out['truncated']: pagination['complete']=False
        out['pagination']=pagination
    return out

def fixed_cli(argv):
    """No raw stderr, credential/environment dump, shell or tool passthrough."""
    env={k:os.environ[k] for k in ('HOME','USER','LANG','LC_ALL','TMPDIR','PATH') if k in os.environ}
    env.update({'NO_COLOR':'1','PAGER':'cat','GIT_TERMINAL_PROMPT':'0'})
    proc=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    selector=selectors.DefaultSelector(); deadline=time.monotonic()+TIMEOUT; parts=[]; size=0
    for stream in (proc.stdout,proc.stderr):
        os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ)
    try:
        while selector.get_map():
            if time.monotonic()>=deadline: raise ReadError('upstream_timeout')
            for item,_ in selector.select(min(.2,max(.01,deadline-time.monotonic()))):
                chunk=os.read(item.fileobj.fileno(),65536)
                if not chunk: selector.unregister(item.fileobj);continue
                size+=len(chunk)
                if size>MAX_BYTES: raise ReadError('upstream_output_limit')
                if item.fileobj is proc.stdout: parts.append(chunk)
        proc.wait(timeout=max(.01,deadline-time.monotonic()))
        if proc.returncode: raise ReadError('upstream_client_failed')
        return b''.join(parts).decode('utf-8')
    finally:
        selector.close()
        if proc.poll() is None:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            proc.wait(timeout=3)
        proc.stdout.close();proc.stderr.close()

def unpack(raw):
    if not isinstance(raw,str) or len(raw.encode('utf-8'))>MAX_BYTES: raise ReadError('upstream_output_limit')
    try: envelope=json.loads(raw)
    except (ValueError,UnicodeError): raise ReadError('upstream_response_unrecognized') from None
    if not isinstance(envelope,dict): raise ReadError('upstream_response_unrecognized')
    if envelope.get('error'): raise ReadError('upstream_rpc_error')
    native=envelope.get('result',envelope)
    if not isinstance(native,dict): raise ReadError('upstream_response_unrecognized')
    if native.get('isError'): raise ReadError('upstream_tool_error')
    if 'structuredContent' in native:
        return native['structuredContent']
    texts=[x['text'] for x in native.get('content',[]) if isinstance(x,dict) and x.get('type')=='text' and isinstance(x.get('text'),str)]
    parsed=[]
    for text in texts:
        try: parsed.append(json.loads(text))
        except ValueError: pass
    if parsed: return parsed[-1]
    if texts: return {'text':'\n'.join(texts),'response_structure':'text_only'}
    raise ReadError('upstream_empty_response')

def check_upstream(data):
    if not isinstance(data,dict): return
    code=data.get('code')
    error=data.get('error')
    if isinstance(error,dict): code=error.get('code',code)
    if data.get('error') or data.get('errors') or code in ('NOT_FOUND','FORBIDDEN','UNAUTHORIZED','PERMISSION_DENIED'):
        mapped={'NOT_FOUND':'upstream_not_found','FORBIDDEN':'upstream_acl_denied','UNAUTHORIZED':'upstream_unauthorized','PERMISSION_DENIED':'upstream_acl_denied'}
        raise ReadError(mapped.get(code,'upstream_service_error'))
    if (data.get('attributes') or {}).get('is_available_for_ai') is False:
        raise ReadError('upstream_ai_access_denied')

def pagination(operation,arguments,data):
    p={'scope':'one_native_response','has_more':None,'complete':False,'continuation':None}
    if not isinstance(data,dict): return p
    for key in ('total','totalIsExact','returned','perPage','page','hasMore','nextPage','nextFromId','nextCursor','cursor','next_cursor','nextCursor','stopReason','scannedEntries','mayBeTruncated','truncated','reachablePages','unavailableCount','restrictedCount'):
        if key in data: p[key]=scrub(data[key])
    partial=any(data.get(k) is True for k in ('mayBeTruncated','truncated','partial','commentsScanTruncated'))
    p['upstream_partial']=partial
    if type(data.get('hasMore')) is bool: p['has_more']=data['hasMore']
    if type(data.get('has_more')) is bool: p['has_more']=data['has_more']
    specs=OPERATIONS[operation]['readSchema'].get('properties',{})
    for native,target in [('nextPage','page'),('nextFromId','fromId'),('nextCursor','cursor'),('next_cursor','cursor'),('next','cursor'),('next_page_token','cursor')]:
        cursor=data.get(native)
        if cursor is not None and cursor!='' and target in specs:
            args=dict(arguments);args[target]=cursor
            if validate(args,OPERATIONS[operation]['readSchema']):
                p['has_more']=True;p['continuation']=continuation_for(operation,args)
                break
    if p['has_more'] is None and any(k in data for k in ('next_cursor','nextCursor','next_page_token')):
        p['has_more']=False
    # search_entities publishes authoritative pages instead of a nextPage field.
    if operation=='tracker.search_entities' and type(data.get('pages')) is int and type(data.get('page')) is int:
        page=data['page']; pages=data['pages']; reachable=data.get('reachablePages',pages)
        p['has_more']=page<pages
        if page<pages and type(reachable) is int and page<reachable:
            p['continuation']=continuation_for(operation,dict(arguments,page=page+1))
        elif page<pages: partial=True;p['upstream_partial']=True
    # hasMore=true,nextPage=null remains a dead end, never a manufactured cursor.
    p['complete']=p['has_more'] is False and not partial
    if p['has_more'] and p['continuation'] is None: p['continuation_unavailable']=True
    return p

def check_scope(operation,arguments):
    # Reject targeted excluded services, not legitimate Tracker discussions of integrations.
    for key in ('slug','source_slug','target_slug'):
        value=arguments.get(key)
        if isinstance(value,str):
            if any(part in ('..','.') for part in value.split('/')) or any(ord(c)<32 for c in value): raise ReadError('invalid_argument')
            if re.match(r'(?i)^(?:(?:mail|email|calendar|calendars)/personal|personal/(?:mail|email|calendar|calendars))(?:/|$)',value): raise ReadError('forbidden_scope')
    if operation=='wiki.ResolveSlugFromUrl':
        value=arguments['url']; url=urlsplit(value)
        if value.startswith('//') or url.query or url.fragment or url.username or url.password or url.port:
            raise ReadError('invalid_argument')
        if url.scheme and (url.scheme!='https' or url.hostname not in ('wiki.yandex-team.ru','wiki.yandex.ru')):
            raise ReadError('invalid_argument')
        if '\\' in value or any(ord(c)<32 for c in value): raise ReadError('invalid_argument')
        if any(s in ('.','..') for s in url.path.split('/')): raise ReadError('invalid_argument')

class Backend:
    def __init__(self,runner=None): self.runner=runner or fixed_cli
    def read(self,operation=None,arguments=None,max_chars=12000,**extra):
        return self._read(operation,arguments,max_chars,False,**extra)
    def read_full(self,operation=None,arguments=None,max_chars=12000):
        return self._read(operation,arguments,max_chars,True)
    def _read(self,operation=None,arguments=None,max_chars=12000,full=False,**extra):
        try:
            args={'operation':operation,'arguments':arguments,'max_chars':max_chars}
            if extra or not validate(args,INPUT_SCHEMA): raise ReadError('invalid_argument')
            arguments=resolve_continuation(operation,arguments)
            if not validate(arguments,OPERATIONS[operation]['readSchema']): raise ReadError('invalid_argument')
            # Resource bounds, not feature allowlists; no selected queue/repo/page restriction.
            if len(json.dumps(args,ensure_ascii=False,allow_nan=False))>256*1024: raise ReadError('argument_size_limit')
            check_scope(operation,arguments)
            spec=OPERATIONS[operation]
            argv=[MCP_CLI,'connect',spec['service'],'--tool',spec['nativeoperation'],'--raw','--no-browser']
            for key,value in arguments.items():
                encoded=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
                argv.extend(['--arg',key+':'+encoded])
            data=unpack(self.runner(argv));check_upstream(data)
            p=pagination(operation,arguments,data)
            cleaned=scrub(data)
            text=json.dumps(cleaned,ensure_ascii=False,allow_nan=False)
            return result(True,'ok',source=operation,text=text,max_chars=MAX_BYTES if full else max_chars,pagination=p)
        except ReadError as error:
            return result(False,error.code)
        except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError):
            return result(False,'invalid_argument' if not isinstance(operation,str) or operation not in OPERATIONS else 'upstream_response_unrecognized')
        except (OSError,subprocess.SubprocessError): return result(False,'upstream_client_unavailable')
        except Exception: return result(False,'upstream_unavailable')
