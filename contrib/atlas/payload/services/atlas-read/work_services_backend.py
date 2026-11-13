"""Frozen typed work-service reads. Source-only candidate; no activation.

No arbitrary transport, URL, code, method, shell or argv. The reviewed manifest
is hash-pinned and every call revalidates its effective closed input schema.
Native tools alone own authentication; this module never loads credentials.
"""
from __future__ import annotations
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

MCP = '/usr/bin/false'
YT = '/usr/bin/false'
GH = '/usr/bin/false'
ARC = '/usr/bin/false'
ARCANUM = '/usr/bin/false'
ARC_CWD = '/nonexistent'
MAX_BYTES=2_000_000
MAX_SECONDS=45
MANIFEST_SHA256 = 'b26fb43e9648082a3f8f251def2a66878756ba18b07c0501d6a4a01d92ea475d'
YT_CONFIG=('{read_retries={enable=%false;create_transaction_and_take_snapshot_lock=%false;};'
           'read_parallel={enable=%false;};proxy={enable_proxy_discovery=%false;'
           'prefer_https=%true;request_timeout=10000;retries={count=1;};};}')
COLUMN=r'[A-Za-z_][A-Za-z0-9_]{0,127}'
BASE_PATH=r'//[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*'
PATH=re.compile('^'+BASE_PATH+'$')
RANGED_PATH=re.compile('^('+BASE_PATH+r')(?:\{('+COLUMN+r'(?:,'+COLUMN+r')*)\})?\[#([0-9]{1,12}):#([0-9]{1,12})\]$')
CREDENTIAL_NAME=re.compile(r'(?:^|[/_.-])(?:credentials?|passwords?|passwd|oauth|cookies?|csrf|secrets?|private[_-]?key|authorization|access[_-]?token|refresh[_-]?token)(?:$|[/_.-])',re.I)
CREDENTIAL_PATH=re.compile(r'(?:^|/)(?:\.env(?:\.[^/]*)?|\.netrc|\.npmrc|\.pypirc|\.tokens?|tokens?(?:\.[^/]*)?|credentials?(?:\.[^/]*)?|cookies?(?:\.[^/]*)?|(?:oauth|auth)(?:[._-][^/]*)?)(?:/|$)',re.I)

class ReadError(Exception):pass

class UpstreamReadError(ReadError):
    """Bounded allowlisted upstream diagnostics, never a raw exception string."""
    def __init__(self,value,provenance):
        super().__init__('UPSTREAM_ERROR')
        diagnostic={'provenance':provenance,'omissions':'Raw upstream messages and payload omitted for credential safety.'}
        if type(value)is dict:
            for key in ('httpStatus','isError','errorCode','code'):
                item=value.get(key)
                if type(item)is bool and key=='isError':diagnostic[key]=item
                elif type(item)is int:diagnostic[key]=item
                elif type(item)is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}',item):diagnostic[key]=redact(item)
            body=value.get('body')
            if type(body)is dict:
                item=body.get('code')
                if type(item)is int or (type(item)is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}',item)):diagnostic['bodyCode']=redact(item) if type(item)is str else item
        self.diagnostic={'upstream':diagnostic}

SELECT_PARSER_SHA256 = '0ef0ffd9b61f2b90ebc102ba37df1b6ee1e89f38726f087f9c0f41bc41b2b179'
TRUSTED_MANIFEST_MAX_BYTES=16_000_000

def _load_select_parser():
    path=Path(__file__).resolve().with_name('select_parser.py')
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:raise ReadError('PARSER_INTEGRITY')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=SELECT_PARSER_SHA256:raise ReadError('PARSER_INTEGRITY')
        namespace={'__name__':'_atlas_pinned_select_'+SELECT_PARSER_SHA256,'__file__':str(path)}
        exec(compile(raw,str(path),'exec',dont_inherit=True),namespace)
        return namespace
    except OSError:raise ReadError('PARSER_INTEGRITY') from None

_SELECT=_load_select_parser()
parse_select=_SELECT['parse_select']
SelectError=_SELECT['SelectError']


METRIC_NAMES={'input_tokens','output_tokens','total_tokens','prompt_tokens','completion_tokens','cached_tokens'}


def sensitive_name(value):
    # Treat token(s) as credentials unless it is an explicitly named business
    # metric. CamelCase, dotted attributes and underscore names share a guard.
    norm=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',str(value)).lower().replace('-','_')
    if norm in METRIC_NAMES:return False
    return bool(CREDENTIAL_NAME.search(norm) or re.search(r'(?:^|[/_.])(?:tokens?|api_?key|client_?secret|environment|env|headers|job_variables|processor_?ticket)(?:$|[/_.])',norm))


def safe_column(value):
    if type(value)is not str or not re.fullmatch(COLUMN,value) or sensitive_name(value):raise ReadError('FORBIDDEN_SOURCE')


def audit_schema(schema,depth=0):
    from jsonschema import Draft202012Validator
    try:Draft202012Validator.check_schema(schema)
    except Exception:raise ReadError('UNSUPPORTED_SCHEMA') from None


def admit_extra_routes(raw,expected_sha256,*,base=None):
    """Pure optional admission; caller semantically reviews exact hash-bound bytes.

    Never changes MANIFEST or dispatch. Schema validity is not read semantics.
    Caller must review operation defaults and supply appropriate semantic guards.
    """
    if type(raw)is not bytes or len(raw)>TRUSTED_MANIFEST_MAX_BYTES or type(expected_sha256)is not str or not re.fullmatch(r'[0-9a-f]{64}',expected_sha256) or hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ReadError('MANIFEST_INTEGRITY')
    try:extra=json.loads(raw)
    except (ValueError,UnicodeError):raise ReadError('MANIFEST_INTEGRITY') from None
    if type(extra)is not dict:raise ReadError('INVALID_MANIFEST')
    out=dict(MANIFEST if base is None else base)
    forbidden={'mail','mail_corp','calendar','telegram','computer','computer_use','devtools'}
    for op,spec in extra.items():
        if op in out or type(spec)is not dict or set(spec)!={'service','nativeTool','transport','inputSchema','defaults'}:raise ReadError('INVALID_MANIFEST')
        if type(op)is not str or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+',op) or spec['service'] in forbidden or op.split('.',1)[0]!=spec['service'] or spec['transport']!='mcp' or type(spec['nativeTool'])is not str or not re.fullmatch(r'[A-Za-z0-9_.-]+',spec['nativeTool']):raise ReadError('INVALID_MANIFEST')
        schema=spec['inputSchema'];audit_schema(schema)
        if type(schema)is not dict or schema.get('type')!='object' or schema.get('additionalProperties')is not False or type(spec['defaults'])is not dict:raise ReadError('INVALID_MANIFEST')
        public={**schema,'required':[k for k in schema.get('required',[]) if k in spec['defaults']]}
        validate(spec['defaults'],public)
        out[op]=spec
    return out


def load_manifest():
    path=Path(__file__).resolve().with_name('work_services_manifest.json')
    if path.is_symlink() or path.stat().st_size>TRUSTED_MANIFEST_MAX_BYTES:
        raise ReadError('MANIFEST_INTEGRITY')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA256:
        raise ReadError('MANIFEST_INTEGRITY')
    manifest=json.loads(raw)
    for spec in manifest.values():audit_schema(spec['inputSchema'])
    return manifest

MANIFEST=load_manifest()
PUBLIC_ARGUMENT_SCHEMAS={op:{**spec['inputSchema'],'required':[k for k in spec['inputSchema'].get('required',[]) if k not in spec['defaults']]} for op,spec in MANIFEST.items()}
def _embedded_schema(schema,prefix):
    if type(schema)is list:return [_embedded_schema(v,prefix) for v in schema]
    if type(schema)is not dict:return schema
    return {k:(prefix+v[1:] if k in ('$ref','$dynamicRef') and type(v)is str and v.startswith('#') else _embedded_schema(v,prefix)) for k,v in schema.items()}

INPUT_SCHEMA={'type':'object','additionalProperties':False,'required':['operation','arguments'],'properties':{'operation':{'type':'string','enum':sorted(MANIFEST)},'arguments':{'type':'object'},'max_chars':{'type':'integer','minimum':256,'maximum':48000},'text_offset':{'type':'integer','minimum':0,'maximum':MAX_BYTES},'expected_text_sha256':{'type':'string','pattern':r'^[0-9a-f]{64}$'}},'$defs':{},'oneOf':[]}
for index,(op,spec) in enumerate(sorted(MANIFEST.items())):
    key='op'+str(index)
    INPUT_SCHEMA['$defs'][key]=_embedded_schema(PUBLIC_ARGUMENT_SCHEMAS[op],'#/$defs/'+key)
    INPUT_SCHEMA['oneOf'].append({'type':'object','additionalProperties':False,'properties':{**INPUT_SCHEMA['properties'],'operation':{'const':op},'arguments':INPUT_SCHEMA['$defs'][key]},'required':['operation','arguments']})


def validate(value,schema,depth=0):
    """Draft 2020-12 assertions and local refs; no network reference retrieval."""
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry
    from referencing.exceptions import NoSuchResource
    def no_remote(uri):raise NoSuchResource(ref=uri)
    formats=FormatChecker()
    @formats.checks('int32')
    def int32(v):return type(v)not in(int,float) or (-2147483648<=v<=2147483647)
    try:
        audit_schema(schema)
        validator=Draft202012Validator(schema,registry=Registry(retrieve=no_remote),format_checker=formats)
        if not validator.is_valid(value):raise ReadError('INVALID_INPUT')
    except ReadError:raise
    except Exception:raise ReadError('INVALID_INPUT') from None


def sanitize_data(value,depth=0):
    """Remove credential containers before rendering normal work metadata.

    Processor tickets, environment/headers and secret payloads are not read
    capabilities. Ordinary numeric token metrics and pagination cursors are.
    """
    if depth>30:return '[OMITTED_DEPTH_LIMIT]'
    if type(value)is str:
        try:embedded=json.loads(value)
        except (ValueError,RecursionError):return redact(value)
        if type(embedded)in(dict,list):return json.dumps(sanitize_data(embedded,depth+1),ensure_ascii=False,allow_nan=False)
        return redact(value)
    if type(value)is list:return [sanitize_data(v,depth+1) for v in value]
    if type(value)is dict:
        result={}
        private_names={'auth','authentication','pass','pin','pin_code','unlock_pin','device_pin','service_ticket','user_ticket','tvm_ticket'}
        def private_name(k):
            norm=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',str(k)).lower().replace('-','_')
            return sensitive_name(k) or any(part in private_names for part in re.split(r'[/\.]',norm))
        named_secret=any(type(value.get(k))is str and private_name(value[k]) for k in ('name','code','key','parameter','parameterName','optionName','option_name'))
        for k,v in value.items():
            lower=str(k).lower().replace('-','_')
            cursor=lower in ('next_page_token','page_token','nextpagetoken','continuation_token','cursor','next_cursor') and (v is None or type(v)is str)
            numeric_metric=lower in ('input_tokens','output_tokens','total_tokens','prompt_tokens','completion_tokens','cached_tokens') and type(v)in(int,float)
            private=(named_secret and lower not in ('name','code','key','parameter','parametername','optionname','option_name','type','datatype','description','title')) or private_name(k) or lower in ('environment','env','headers','request_headers','response_headers','job_variables','processorticket')
            result[k]='[REDACTED]' if private and not cursor and not numeric_metric else sanitize_data(v,depth+1)
        return result
    return value


def redact(text):
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',str(text))
    text=re.sub(r'-----BEGIN [^-]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY)-----[\s\S]*?(?:-----END [^-]+-----|\Z)','[REDACTED_PRIVATE_KEY]',text)
    text=re.sub(r'(?im)^.*(?:authorization|proxy-authorization|set-cookie|cookie|csrf)\s*[:=].*$','[REDACTED_HEADER]',text)
    text=re.sub(r'(?im)^\s*(?:job[-_]variables|processor[-_]?ticket|environment)\s*[:=].*$','[REDACTED_PRIVATE_CONTAINER]',text)
    text=re.sub(r'(?i)\b(?:Bearer|OAuth|Basic)\s+[^\s\x22\x27,;<>]+','[REDACTED_AUTH]',text)
    text=re.sub(r'(?i)([\x22\x27]?[\w.-]*(?:token|password|passwd|secret|api[_-]?key|credential|cookie|csrf|signature)[\x22\x27]?\s*[:=]\s*)(?:\x22[^\x22]*\x22|\x27[^\x27]*\x27|[^\s&,;<>}\]]+)',r'\1[REDACTED]',text)
    text=re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+|y0_[A-Za-z0-9_-]+|AQAD-[A-Za-z0-9_-]+|ya29\.[A-Za-z0-9_.-]+)\b','[REDACTED_TOKEN]',text)
    text=re.sub(r'\b\d{6,12}:[A-Za-z0-9_-]{30,}\b','[REDACTED_BOT_CREDENTIAL]',text)
    text=re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b','[REDACTED_JWT]',text)
    # Remove credential-bearing URLs entirely; never emit download access tokens.
    text=re.sub(r'https?://[^\s\x22\x27<>]*(?:[?&](?:token|signature|credential|key|x-amz-[^=]*|x-goog-[^=]*)=)[^\s\x22\x27<>]*','[REDACTED_SIGNED_URL]',text,flags=re.I)
    return ''.join(c for c in text if ord(c)>=32 or c in '\n\t')


def run_native(argv,deadline):
    env={k:os.environ[k] for k in ('HOME','USER','PATH','LANG','LC_ALL','TMPDIR') if k in os.environ}
    env.update(NO_COLOR='1',GH_PROMPT_DISABLED='1',GH_PAGER='cat',PAGER='cat')
    p=None;chunks=[];total=0
    try:
        p=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,start_new_session=True,cwd=ARC_CWD if argv[0]==ARC else None)
        with selectors.DefaultSelector() as selector:
            for stream in (p.stdout,p.stderr):
                os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ)
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ReadError('TIMEOUT')
                for key,_ in selector.select(min(0.1,remaining)):
                    chunk=os.read(key.fd,65536)
                    if not chunk:selector.unregister(key.fileobj);continue
                    total+=len(chunk)
                    if total>MAX_BYTES:raise ReadError('OUTPUT_LIMIT')
                    if key.fileobj is p.stdout:chunks.append(chunk)
        try:p.wait(timeout=max(0.001,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:raise ReadError('TIMEOUT')from None
        permitted={0,8} if argv[:3]==[GH,'pr','checks'] else {0}
        if p.returncode not in permitted:raise ReadError('NATIVE_READ_FAILED')
        return b''.join(chunks).decode('utf-8')
    except OSError:raise ReadError('NATIVE_UNAVAILABLE')from None
    finally:
        if p is not None:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            p.wait();p.stdout.close();p.stderr.close()


def uncarrier(text):
    """Decode observed JSON/string/literal wrappers without eval or expressions."""
    value=text
    for _ in range(3):
        if type(value)is not str:break
        try:value=json.loads(value);continue
        except ValueError:pass
        if not value.lstrip().startswith(('{','[')):break
        try:
            tree=ast.parse(value,mode='eval')
            for node in ast.walk(tree):
                if isinstance(node,ast.Name):
                    if node.id not in ('true','false','null'):raise ValueError()
                    node.__class__=ast.Constant;node.value={'true':True,'false':False,'null':None}[node.id]
                elif type(node)not in (ast.Expression,ast.Dict,ast.List,ast.Tuple,ast.Constant,ast.UnaryOp,ast.USub,ast.UAdd,ast.Load):raise ValueError()
            value=ast.literal_eval(tree)
        except (ValueError,SyntaxError,TypeError,RecursionError):break
    return value


def unpack(raw,mcp):
    if not mcp:
        return uncarrier(raw)
    rpc=json.loads(raw)
    if type(rpc)is not dict:raise ReadError('INVALID_RESPONSE')
    if rpc.get('error'):raise UpstreamReadError(rpc['error'],'jsonrpc')
    result=rpc.get('result')
    if type(result)is not dict:raise ReadError('INVALID_RESPONSE')
    content=result.get('content')
    if type(content)is not list:raise ReadError('INVALID_RESPONSE')
    texts=[c['text'] for c in content if type(c)is dict and c.get('type')=='text' and type(c.get('text'))is str]
    if not texts:
        if result.get('isError')is True:raise UpstreamReadError(result,'mcp_result')
        raise ReadError('UNSUPPORTED_RESPONSE_CONTENT')
    text='\n'.join(texts)
    value=uncarrier(text)
    if type(value)is dict and (value.get('isError')is True or (type(value.get('httpStatus'))is int and 400<=value['httpStatus']<=599)):
        raise UpstreamReadError(value,'native_api')
    if result.get('isError')is True:raise UpstreamReadError(value,'mcp_result')
    if re.search(r'(?im)^\s*(?:error\b|failed to\b|Traceback\b|<html\b|<!doctype\b)',text):raise UpstreamReadError({},'native_text')
    if type(value)is dict and (value.get('error') or value.get('errors')) and not (value.get('state') or value.get('status')):raise UpstreamReadError(value,'native_api')
    return value


def safe_path(value,ranged=False):
    if type(value)is not str or len(value)>2048 or sensitive_name(value) or CREDENTIAL_PATH.search(value):raise ReadError('FORBIDDEN_SOURCE')
    if value=='//' and not ranged:return
    if ranged:
        match=RANGED_PATH.fullmatch(value)
        if not match or not 0<int(match[4])-int(match[3])<=100:raise ReadError('UNBOUNDED_READ')
        if any(x in ('.','..') for x in match[1][2:].split('/')):raise ReadError('INVALID_INPUT')
        if match[2]:
            for column in match[2].split(','):safe_column(column)
    elif not PATH.fullmatch(value) or any(x in ('.','..') for x in value[2:].split('/')):raise ReadError('INVALID_INPUT')


def semantic_checks(op,a):
    service,name=op.split('.',1)
    if service=='yt':
        for attr in a.get('attributes',[])+([a['property']] if 'property'in a else []):
            if sensitive_name(attr):raise ReadError('FORBIDDEN_SOURCE')
        if name=='qt_start_query' and a['engine']=='ql':
            try:parse_select(a['query'],safe_path,safe_column)
            except SelectError:raise ReadError('SQL_GRAMMAR_DENIED')from None
        elif name=='qt_start_query':
            # Complete accepted SQL grammar, not a substring denylist. No table
            # scans, UDFs, pragmas, multi-statements or external data loads.
            if not re.fullmatch(r'\s*SELECT\s+-?[0-9]{1,12}(?:\s+AS\s+[A-Za-z_][A-Za-z0-9_]{0,63})?(?:\s*,\s*-?[0-9]{1,12}(?:\s+AS\s+[A-Za-z_][A-Za-z0-9_]{0,63})?){0,19}\s*;?\s*',a['query'],re.I):raise ReadError('SQL_GRAMMAR_DENIED')
        for key in ('path','directory','root_path','table_path'):
            if key in a:safe_path(a[key])
        if 'paths'in a:
            if not 1<=len(a['paths'])<=100:raise ReadError('INVALID_INPUT')
            for p in a['paths']:safe_path(p)
        if 'table'in a:
            safe_path(a['table'],ranged=name in ('common_client_sample_static_table','common_client_infer_table_schema'))
        if name in ('get_attributes_account','get_attributes_account_limits_disk','get_attributes_bundle','get_attributes_pool'):
            key={'get_attributes_account':'account','get_attributes_account_limits_disk':'account','get_attributes_bundle':'bundle','get_attributes_pool':'pool'}[name]
            if not a.get(key):raise ReadError('SCOPE_REQUIRED')
        if name=='get_proxy' and a.get('proxy_type') not in ('http','rpc',None):raise ReadError('INVALID_INPUT')
    if service=='nirvana':
        if name=='upload_data':
            if bool(a.get('file_path'))==bool(a.get('url')):raise ReadError('SCOPE_REQUIRED')
            if a.get('file_path') and (CREDENTIAL_PATH.search(a['file_path']) or sensitive_name(a['file_path'])):raise ReadError('FORBIDDEN_SOURCE')
            if a.get('url'):
                from urllib.parse import urlsplit
                url=urlsplit(a['url'])
                if url.scheme!='https' or url.username or url.password or url.query or url.fragment:raise ReadError('FORBIDDEN_SOURCE')
        if name in ('describe_workflow','get_parameters','block_positions','block_cache','manage_external_endpoints','get_block_endpoints','upgrade_operations'):
            if not any(a.get(k) for k in ('workflow_instance_id','block_type_id','endpoint_guids')):raise ReadError('SCOPE_REQUIRED')
        if name=='get_parameters' and a['scope']=='block' and not a.get('block'):raise ReadError('SCOPE_REQUIRED')
        if name=='get_parameters' and not a['names_only'] and any(sensitive_name(p) for p in a.get('parameter_names') or []):raise ReadError('FORBIDDEN_SOURCE')
        if name=='find_workflow_instances' and not any(a.get(k) for k in ('ns_path','ns_id','author','pattern','quota_project_id')):raise ReadError('SCOPE_REQUIRED')
        if name=='browse_nirvana' and not any(a.get(k) for k in ('path','namespace_id','workflow_id')):raise ReadError('SCOPE_REQUIRED')
    if service=='sandbox':
        for key in ('file_path','dir_path'):
            if key in a and (a[key].startswith(('/','\\')) or any(x=='..' for x in re.split(r'[/\\]',a[key])) or any(c in a[key] for c in ('%','?','#','\\')) or CREDENTIAL_NAME.search(a[key]) or CREDENTIAL_PATH.search(a[key])):raise ReadError('FORBIDDEN_SOURCE')
        if 'range'in a:
            start,end=map(int,a['range'][6:].split('-'))
            if not 0<=end-start<65536:raise ReadError('UNBOUNDED_READ')
        if name in ('sandbox_list_resources','sandbox_count_resources') and not any(a.get(k) for k in ('task_id','owner','type','id','attrs')):raise ReadError('SCOPE_REQUIRED')
    if service=='docs' and 'url'in a:
        from urllib.parse import urlsplit
        url=urlsplit(a['url'])
        if url.scheme!='https' or url.username or url.password or not(url.hostname=='docs.yandex-team.ru' or (url.hostname or '').endswith('.yandex-team.ru')):raise ReadError('FORBIDDEN_SOURCE')
    if service=='monium_mcp' and name=='resolve_url':
        from urllib.parse import urlsplit
        url=urlsplit(a['url'])
        if url.scheme!='https' or url.username or url.password or url.port not in (None,443) or url.hostname not in ('nda.ya.ru','monium.yandex-team.ru','monitoring.yandex-team.ru','solomon.yandex-team.ru','setrace.yandex-team.ru'):raise ReadError('FORBIDDEN_SOURCE')
    if service=='intrasearch' and name=='list_filters':
        if a['vertical'] not in ('wiki','doc','tracker','arcanum','stackoverflow','nirvana','people'):raise ReadError('FORBIDDEN_SOURCE')
    if service=='intrasearch':
        if name=='search_pipeline':validate_search_pipeline(a['pipeline'])
        if name=='semantic_code_search' and re.search(r'\b(?:AND|OR|NOT)\b',a['query'],re.I):raise ReadError('INVALID_INPUT')
        if name=='search':
            if any(not k.startswith(a['vertical']+'.') for k in a.get('filters',{})):raise ReadError('FORBIDDEN_SOURCE')
        if name=='fetch':
            for url in a['urls']:indexed_source_url(url,a['source_layer'])
        if name=='evaluate_sources':
            for row in a['evaluations']:indexed_source_url(row['url'])
        if name=='list_filter_values' and not re.fullmatch(r'(wiki|doc|tracker|arcanum|stackoverflow|nirvana|people)\.[A-Za-z_][A-Za-z0-9_.-]{0,127}',a['filter']):raise ReadError('FORBIDDEN_SOURCE')
    if service=='staff_api_mcp' and name in ('person-full-info','group-info','group-memberships','department-staff') and not a.get('search_by'):raise ReadError('SCOPE_REQUIRED')
    if service=='yql' and name=='validate_query':
        if a['cluster'] in ('hahn','arnold'):raise ReadError('TARGET_UNAVAILABLE')
        # No implicit cluster switch or SQL-dialect substitution. VALIDATE is
        # nonexecuting, but a conflicting USE must not choose another target.
        uses=re.findall(r'(?im)^\s*USE\s+([A-Za-z_][A-Za-z0-9_-]*)\s*;',a['query'])
        if any(u!=a['cluster'] for u in uses):raise ReadError('TARGET_CONFLICT')
    if service=='yql' and name=='execute_query':
        if a['cluster'] in ('hahn','arnold'):raise ReadError('TARGET_UNAVAILABLE')
        try:parse_select(a['query'],safe_path,safe_column,dialect='yql')
        except SelectError:raise ReadError('SQL_GRAMMAR_DENIED')from None
    if service=='yql' and name=='fix_query':
        match=re.fullmatch(r'\s*USE\s+([A-Za-z_][A-Za-z0-9_-]*)\s*;\s*(.+)',a['query'],re.I|re.S)
        if not match or match[1] in ('hahn','arnold'):raise ReadError('TARGET_REQUIRED')
        try:parse_select(match[2],safe_path,safe_column,dialect='yql')
        except SelectError:raise ReadError('SQL_GRAMMAR_DENIED')from None
    if service=='ci':
        if name=='get_action_launch':
            triple=all(a.get(k) is not None for k in ('config_path','action_id','launch_number'))
            single=bool(a.get('flow_launch_id'))
            if triple==single or (single and any(k in a for k in ('config_path','action_id','launch_number'))):raise ReadError('INVALID_INPUT')


def yt_argv(name,a):
    base=[YT,'--proxy',a['cluster'],'--tx','0-0-0-0','--config',YT_CONFIG]
    if name=='dynamic_select':
        safe_path(a['path'])
        for col in a['columns']+[f['column'] for f in a['filters']]:
            safe_column(col)
        sql=','.join(a['columns'])+' FROM ['+a['path']+']'
        if a['filters']:
            sql+=' WHERE '+' AND '.join(f['column']+' '+f['operator']+' '+json.dumps(f['value'],ensure_ascii=False,allow_nan=False) for f in a['filters'])
        sql+=' LIMIT '+str(a['limit'])
        return base+['select-rows',sql,'--input-row-limit',str(a['input_row_limit']),'--output-row-limit',str(a['limit']),'--forbid-full-scan','--forbid-join-without-index','--format','json']
    if name=='native_attributes':
        argv=base+['get',a['path']+('@' if a['path']=='//' else '/@'),'--max-size','100','--format','json']
        for attr in a['attributes']:argv+=['--attribute',attr]
        return argv
    if name=='list_operations':
        argv=base+['list-operations','--user',a['user'],'--limit',str(a['limit']),'--no-include-counters','--format','json']
        for attr in ('id','state','type','start_time','finish_time'):argv+=['--attribute',attr]
        for key in ('state','cursor_time','cursor_direction'):
            if key in a:argv+=['--'+key.replace('_','-'),a[key]]
        return argv
    raise ReadError('ROUTE_UNAVAILABLE')


def dynamic_query(a):
    safe_path(a['path'])
    for col in a['columns']+[f['column'] for f in a['filters']]:
        safe_column(col)
    query=','.join(a['columns'])+' FROM ['+a['path']+']'
    if a['filters']:query+=' WHERE '+' AND '.join(f['column']+' '+f['operator']+' '+json.dumps(f['value'],ensure_ascii=False,allow_nan=False) for f in a['filters'])
    return query+' LIMIT '+str(a['limit'])


def argv_for(op,spec,a):
    name=spec['nativeTool'];transport=spec['transport']
    if transport in ('yt_cli','github_cli','arc_cli'):name=op.split('.',1)[1]
    if transport=='scoped_semantic_code':
        args={'query':a['query']+' s_project:"'+a['project_path']+'"','page_size':a['page_size']}
        return argv_for(op,{'nativeTool':'semantic_code_search','transport':'mcp','service':'intrasearch'},args)
    if transport=='qt_guarded_select':
        args={k:a[k] for k in ('cluster','engine','query','stage')}
        if a['engine']=='ql':
            try:query,limit=parse_select(a['query'],safe_path,safe_column)
            except SelectError:raise ReadError('SQL_GRAMMAR_DENIED')from None
            args['query']=query
            args['settings']={'cluster':a.get('target_cluster',a['cluster']),'input_row_limit':a['input_row_limit'],'output_row_limit':limit,'allow_full_scan':False,'allow_join_without_index':False,'fail_on_incomplete_result':True}
        return argv_for(op,{'nativeTool':'qt_start_query','transport':'mcp','service':'yt'},args)
    if transport=='qt_select_dynamic':
        settings={'cluster':a['cluster'],'input_row_limit':a['input_row_limit'],'output_row_limit':a['limit'],'allow_full_scan':False,'allow_join_without_index':False,'fail_on_incomplete_result':True}
        args={'cluster':a['query_tracker_cluster'],'engine':'ql','query':dynamic_query(a),'settings':settings,'stage':'production'}
        return argv_for('yt.qt_start_query',{'nativeTool':'qt_start_query','transport':'mcp','service':'yt'},args)
    if transport=='mcp':
        argv=[MCP,'connect',spec['service'],'--tool',name]
        for k,v in sorted(a.items()):
            if k=='setup_server_args':raise ReadError('INVALID_INPUT')
            argv+=['--arg',k+':'+(v if type(v)is str else json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False))]
        return argv+['--raw']
    if transport=='yt_cli':return yt_argv(name,a)
    if transport=='github_cli':
        number=str(a['number']);repo=a['repository']
        if name=='pr_diff':return [GH,'pr','diff',number,'--repo',repo,'--color','never']
        if name=='pr_checks':return [GH,'pr','checks',number,'--repo',repo,'--json','bucket,name,state,description,startedAt,completedAt,link,workflow']
        fields={'pr_status':'number,title,state,isDraft,url,author,baseRefName,headRefName,headRefOid,mergeStateStatus,mergeable,reviewDecision,statusCheckRollup,changedFiles,additions,deletions',
                'pr_comments':'number,url,comments','pr_reviews':'number,url,reviews,latestReviews,reviewRequests','pr_files':'number,url,changedFiles,files','pr_commits':'number,url,commits'}[name]
        return [GH,'pr','view',number,'--repo',repo,'--json',fields]
    if transport=='arc_cli':
        return [ARC,'pr',{'pr_status':'status','pr_diff':'changes','pr_commits':'history'}[name],str(a['number'])]+([] if name=='pr_diff' else ['--json'])
    raise ReadError('ROUTE_UNAVAILABLE')


def indexed_source_url(value,layer=None):
    from urllib.parse import urlsplit,unquote
    url=urlsplit(value)
    host_layers={'wiki.yandex-team.ru':'wiki','docs.yandex-team.ru':'doc','st.yandex-team.ru':'tracker','a.yandex-team.ru':'arcanum','nirvana.yandex-team.ru':'nirvana','staff.yandex-team.ru':'people','stackoverflow.yandex-team.ru':'stackoverflow'}
    actual=host_layers.get(url.hostname)
    if url.scheme!='https' or url.username or url.password or url.port not in (None,443) or actual is None or (layer and layer!=actual):raise ReadError('FORBIDDEN_SOURCE')
    path=unquote(url.path)
    if '%' in path or CREDENTIAL_PATH.search(path) or sensitive_name(path) or url.query or url.fragment:raise ReadError('FORBIDDEN_SOURCE')
    if actual=='arcanum' and not path.startswith('/review/'):
        # Fetching indexed source files must not expand filesystem/code search
        # authorization. Immutable roots mirror AGENTS.md, not caller options.
        roots=('neuroexpert','junk/ovshapovalov','frontend/browserweb/projects/neuro-expert','alice','agents/eval','agents/sdk-go','taxi/tplatform/ai_infra/ai_minion','zootopia/analytics/ml/stefania','portal/alice-cowork','browser')
        relative=path.removeprefix('/arcadia/')
        if not path.startswith('/arcadia/') or any(p in ('.','..') for p in relative.split('/')) or not any(relative==r or relative.startswith(r+'/') for r in roots):raise ReadError('FORBIDDEN_SOURCE')


def validate_search_pipeline(value):
    import shlex
    try:
        lexer=shlex.shlex(value,posix=True,punctuation_chars='|')
        lexer.whitespace_split=True;lexer.commenters=''
        tokens=list(lexer)
    except ValueError:raise ReadError('PIPELINE_GRAMMAR_DENIED')from None
    stages=[[]]
    for token in tokens:
        if token=='|':stages.append([])
        else:stages[-1].append(token)
    def deny():raise ReadError('PIPELINE_GRAMMAR_DENIED')
    if not 1<=len(stages)<=4 or any(not s for s in stages):deny()
    first=stages[0]
    if len(first)<6 or first[0]!='search' or first[1].startswith('-'):deny()
    args={};i=2
    while i<len(first):
        flag=first[i]
        if flag not in ('--vertical','--limit','--filters') or flag in args or i+1>=len(first):deny()
        args[flag]=first[i+1];i+=2
    if args.get('--vertical') not in ('wiki','doc','tracker','people') or not args.get('--limit','').isdigit() or not 1<=int(args['--limit'])<=50:deny()
    if '--filters'in args:
        try:filters=json.loads(args['--filters'])
        except ValueError:deny()
        schema=MANIFEST['intrasearch.search']['inputSchema']['properties']['filters']
        validate(filters,schema)
        if any(not k.startswith(args['--vertical']+'.') for k in filters):deny()
    tail=stages[1:]
    def head(stage):
        if stage==['head']:return
        if len(stage)!=3 or stage[:2]!=['head','-n'] or not stage[2].isdigit() or not 1<=int(stage[2])<=100:deny()
    if not tail:return
    if tail[0][0]=='head':
        if len(tail)!=1:deny()
        head(tail[0]);return
    if tail[0]!=['fetch'] or len(tail)<2 or tail[1][0]!='rg':deny()
    rg=tail[1];i=1
    while i<len(rg)-1:
        flag=rg[i]
        if flag in ('-i','-n','-o'):i+=1;continue
        if flag not in ('-A','-B','-C','-m') or i+1>=len(rg)-1 or not rg[i+1].isdigit() or not 0<=int(rg[i+1])<=(100 if flag=='-m' else 20):deny()
        i+=2
    if i!=len(rg)-1 or len(rg[-1])>512 or rg[-1].startswith('-'):deny()
    if len(tail)>2:head(tail[2])


GITHUB_ENDPOINTS={'pr_comments':'issues/{number}/comments','pr_reviews':'pulls/{number}/reviews','pr_files':'pulls/{number}/files','pr_commits':'pulls/{number}/commits','pr_review_comments':'pulls/{number}/comments','pr_review_comments_for_review':'pulls/{number}/reviews/{review_id}/comments'}


def github_page(op,a,invoke):
    from urllib.parse import urlsplit,parse_qs
    name=op.split('.',1)[1]
    path='repos/'+a['repository']+'/'+GITHUB_ENDPOINTS[name].format(**a)
    endpoint=path+'?per_page='+str(a['per_page'])+'&page='+str(a['page'])
    # Explicit GET is essential: gh defaults to POST when fields are present.
    raw=invoke([GH,'api',endpoint,'--hostname','github.com','--method','GET','--include'])
    match=re.match(r'^HTTP/[^\r\n]+[\r\n]+',raw)
    if not match:raise ReadError('INVALID_RESPONSE')
    split=re.split(r'\r?\n\r?\n',raw,maxsplit=1)
    if len(split)!=2:raise ReadError('INVALID_RESPONSE')
    header,body=split
    if not re.match(r'^HTTP/\S+\s+200\b',header):raise ReadError('UPSTREAM_ERROR')
    items=json.loads(body)
    if type(items)is not list or len(items)>a['per_page']:raise ReadError('INVALID_RESPONSE')
    next_page=None;invalid_link=False
    links=re.findall(r'(?im)^link:\s*(.+)$',header)
    for line in links:
        for target in re.findall(r'<([^>]+)>\s*;\s*rel="next"',line):
            url=urlsplit(target);params=parse_qs(url.query)
            # GitHub redirects canonical repo-name reads to numeric repository
            # URLs. Never follow that URL: extract only the next integer and
            # rebuild the original caller's fixed repo endpoint on the next call.
            suffix=GITHUB_ENDPOINTS[name].format(**a)
            same_path=url.path=='/'+path or bool(re.fullmatch('/repositories/[0-9]+/'+re.escape(suffix),url.path))
            if url.scheme=='https' and url.hostname=='api.github.com' and not url.username and not url.password and url.port in (None,443) and same_path and set(params)=={'page','per_page'} and params.get('per_page')==[str(a['per_page'])] and params.get('page')==[str(a['page']+1)]:next_page=a['page']+1
            else:invalid_link=True
    cap={'pr_files':3000,'pr_commits':250}.get(name)
    reached_cap=cap is not None and (a['page']-1)*a['per_page']+len(items)>=cap
    data={'items':items,'page':a['page'],'per_page':a['per_page'],'next_page':next_page,'has_more':None if invalid_link or reached_cap else next_page is not None,'snapshot_consistent':False,'coverage':'One independently paginated native REST collection; no snapshot consistency. Follow next_page with identical scope. Native collection caps remain authoritative.'}
    if cap is not None:data['native_collection_cap']=cap
    return data


def nirvana_parameters(a,spec,invoke):
    if a['names_only'] or a.get('parameter_names'):
        return unpack(invoke(argv_for('nirvana.get_parameters',spec,a)),True)
    # Enumerate metadata first so an unfiltered business-value read never
    # explicitly asks the native service for credential parameter values.
    names_args={**a,'names_only':True}
    names=unpack(invoke(argv_for('nirvana.get_parameters',spec,names_args)),True)
    if type(names)is not list or any(type(n)is not str for n in names):raise ReadError('INVALID_RESPONSE')
    safe=list(dict.fromkeys(n for n in names if not sensitive_name(n)))
    selected=safe[:100]
    values=unpack(invoke(argv_for('nirvana.get_parameters',spec,{**a,'parameter_names':selected})),True) if selected else {}
    return {'parameters':values,'selected_names':selected,'excluded_credential_names':[n for n in names if sensitive_name(n)],'has_more':len(safe)>100,'coverage':'Metadata discovery followed by explicit noncredential name selection, max 100 names. Use names_only=true and explicit parameter_names for remaining business settings.'}


def arcanum_read(op,a,invoke):
    name=op.split('.',1)[1]
    by_id={'pr_comments':['comment','list'],'pr_reviews':['pr','reviewers','list'],'pr_active_diff':['pr','active-diff'],'pr_diffs':['pr','diffs'],'pr_metadata':['pr','get']}
    by_diff={'pr_inline_comments':['comment','list-diff'],'pr_files':['pr','changelist'],'pr_checks':['checks']}
    if name in by_id:argv=[ARCANUM]+by_id[name]+['--id',str(a['number'])]
    elif name in by_diff:argv=[ARCANUM]+by_diff[name]+['--diff-id',a['diff_id']]
    else:raise ReadError('ROUTE_UNAVAILABLE')
    if a.get('include_deleted'):argv.append('--include-deleted')
    if a.get('ignore_whitespace'):argv.append('--ignorews')
    if name=='pr_checks':
        argv+=['--limit',str(a['limit'])]
        if 'cursor'in a:argv+=['--cursor',a['cursor']]
    def get(command):
        value=unpack(invoke(command+['--json']),False)
        # --json-schema publishes bare arrays/objects, not an MCP or invented
        # {ok,data} envelope. Validate that actual native payload contract.
        if type(value)not in (dict,list):raise ReadError('INVALID_RESPONSE')
        if type(value)is dict and (value.get('error') or value.get('errors') or value.get('ok')is False):raise ReadError('UPSTREAM_ERROR')
        return value
    first=get(argv)
    if name=='pr_reviews':return {'assigned_reviewers':first,'current_approvers':get([ARCANUM,'pr','get','--id',str(a['number']),'--fields','id,approvers(name,uid)']),'coverage':'Current reviewer assignment and approver status only; historical decision events not supplied by this native CLI.'}
    if name in ('pr_comments','pr_inline_comments','pr_files'):
        if type(first)is not list:raise ReadError('INVALID_RESPONSE')
        end=min(len(first),a['offset']+a['limit'])
        return {'items':first[a['offset']:end],'offset':a['offset'],'limit':a['limit'],'source_items_received':len(first),'next_offset':end if end<len(first) else None,'has_more':end<len(first),'snapshot_consistent':False,'coverage':'Local page of this bounded native array. Re-reads are not a snapshot; upstream completeness is not independently inferred.'}
    return first


def filtered_static(a,invoke):
    import operator
    safe_path(a['path'])
    projection=list(dict.fromkeys(a['columns']+[f['column'] for f in a['filters']]))
    for column in projection:safe_column(column)
    table=a['path']+'{'+','.join(projection)+'}[#'+str(a['row_start'])+':#'+str(a['row_start']+a['scan_rows'])+']'
    spec={'service':'yt','nativeTool':'common_client_sample_static_table','transport':'mcp'}
    rows=unpack(invoke(argv_for('yt.common_client_sample_static_table',spec,{'cluster':a['cluster'],'method':'read_table','table':table})),True)
    if type(rows)is not list or len(rows)>a['scan_rows']:raise ReadError('INVALID_RESPONSE')
    funcs={'=':operator.eq,'!=':operator.ne,'<':operator.lt,'<=':operator.le,'>':operator.gt,'>=':operator.ge}
    matched=[];scanned=0
    for row in rows:
        scanned+=1
        if type(row)is not dict or any(c not in row for c in projection):raise ReadError('INVALID_RESPONSE')
        try:keep=all(funcs[f['operator']](row[f['column']],f['value']) for f in a['filters'])
        except (TypeError,ValueError):keep=False
        if keep:matched.append({c:row[c] for c in a['columns']})
        if len(matched)>=a['limit']:break
    return {'rows':matched,'source_rows_received':len(rows),'source_rows_scanned':scanned,'next_row_start':a['row_start']+scanned if rows else None,'has_more':True if scanned<len(rows) else None,'snapshot_consistent':False,'coverage':'Bounded projected row slice; filtering is local, cursor counts scanned source rows, not matched rows.'}


def bounded_find(a,invoke):
    """Cypress BFS with <=100 visited nodes, <=5 levels, no link traversal.

    Native incomplete flags are preserved; no synthetic cursor or exhaustive
    coverage claim. A caller can continue with a narrower returned child root.
    """
    from collections import deque
    from fnmatch import fnmatchcase
    pending=deque([(a['root_path'],0)]);rows=[];visited=0;incomplete=False
    while pending and visited<a['limit']:
        directory,depth=pending.popleft()
        remaining=a['limit']-visited
        argv=[YT,'--proxy',a['cluster'],'--tx','0-0-0-0','--config',YT_CONFIG,'list',directory,'--max-size',str(remaining),'--format','json']
        for attr in list(dict.fromkeys(['type','owner','account']+a['attributes'])):argv+=['--attribute',attr]
        obj=json.loads(invoke(argv))
        incomplete=incomplete or (type(obj)is dict and bool(obj.get('$attributes',{}).get('incomplete')))
        nodes=obj.get('$value',obj) if type(obj)is dict else obj
        if type(nodes)is not list or len(nodes)>remaining:raise ReadError('INVALID_RESPONSE')
        for node in nodes:
            visited+=1
            if type(node)is not dict:raise ReadError('INVALID_RESPONSE')
            name=node.get('$value');attrs=node.get('$attributes',{})
            if type(name)is not str or type(attrs)is not dict or not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name in ('.','..'):raise ReadError('INVALID_RESPONSE')
            child=directory+('' if directory=='//' else '/')+name
            if sensitive_name(child):continue
            typ=attrs.get('type')
            if typ=='map_node':
                if depth+1<a['max_depth']:pending.append((child,depth+1))
                else:incomplete=True
            if typ in a['type'] and fnmatchcase(name,a.get('name','*')) and all(attrs.get(k)==v for k,v in a.get('attributes_to_match',{}).items()):
                rows.append({'path':child,'attributes':{k:attrs[k] for k in a['attributes'] if k in attrs}})
    return {'items':rows,'visited_nodes':visited,'has_more':bool(incomplete or pending),'next_cursor':None,'coverage':'Bounded subtree traversal only; use narrower root_path to continue. No snapshot consistency.'}


class Backend:
    def __init__(self,runner=None):self._runner=runner

    def read(self,operation=None,arguments=None,max_chars=12000,text_offset=0,expected_text_sha256=None,**unknown):
        return self._read(operation,arguments,max_chars,text_offset,expected_text_sha256,False,**unknown)

    def read_full(self,operation=None,arguments=None,max_chars=12000,*,native_capture=None):
        # Host callback only; raw cursors never enter the returned data or text.
        return self._read(operation,arguments,max_chars,0,None,True,_native_capture=native_capture)

    def _read(self,operation=None,arguments=None,max_chars=12000,text_offset=0,expected_text_sha256=None,full=False,_native_capture=None,**unknown):
        source={'system':'reviewed_work_services'}
        try:
            if unknown or type(operation)is not str or operation not in MANIFEST or type(arguments)is not dict or type(max_chars)is not int or not 256<=max_chars<=48000:raise ReadError('INVALID_INPUT')
            if type(text_offset)is not int or not 0<=text_offset<=MAX_BYTES or (expected_text_sha256 is not None and (type(expected_text_sha256)is not str or not re.fullmatch(r'[0-9a-f]{64}',expected_text_sha256))) or (text_offset and expected_text_sha256 is None):raise ReadError('INVALID_INPUT')
            _load_select_parser()
            spec=MANIFEST[operation]
            source.update(service=spec['service'],nativeTool=spec['nativeTool'],operation=operation)
            if len(json.dumps(arguments,ensure_ascii=False,allow_nan=False).encode())>65536:raise ReadError('INPUT_LIMIT')
            a=json.loads(json.dumps({**spec['defaults'],**arguments},ensure_ascii=False,allow_nan=False))
            validate(a,spec['inputSchema']);semantic_checks(operation,a)
            deadline=time.monotonic()+MAX_SECONDS
            byte_budget=MAX_BYTES
            def invoke(argv):
                nonlocal byte_budget
                if time.monotonic()>=deadline:raise ReadError('TIMEOUT')
                raw=self._runner(argv) if self._runner else run_native(argv,deadline)
                if type(raw)is bytes:raw=raw.decode('utf-8')
                if type(raw)is not str:raise ReadError('INVALID_RESPONSE')
                byte_budget-=len(raw.encode('utf-8'))
                if byte_budget<0:raise ReadError('OUTPUT_LIMIT')
                return raw
            if spec['transport']=='yt_find':data=bounded_find(a,invoke)
            elif spec['transport']=='filtered_static':data=filtered_static(a,invoke)
            elif spec['transport']=='github_rest_page':data=github_page(operation,a,invoke)
            elif spec['transport']=='arcanum_cli':data=arcanum_read(operation,a,invoke)
            elif operation=='nirvana.get_parameters':data=nirvana_parameters(a,spec,invoke)
            else:data=unpack(invoke(argv_for(operation,spec,a)),spec['transport']in('mcp','qt_select_dynamic','qt_guarded_select','scoped_semantic_code'))
            if full and _native_capture is not None:_native_capture(data)
            data=sanitize_data(data)
            # Scrub values before encoding; regex rewriting JSON corrupts metrics.
            text=data if type(data)is str else json.dumps(data,ensure_ascii=False,allow_nan=False)
            digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
            if expected_text_sha256 is not None and expected_text_sha256!=digest:raise ReadError('SOURCE_CHANGED')
            if text_offset>len(text):raise ReadError('INVALID_INPUT')
            text_end=len(text) if full else min(len(text),text_offset+(max_chars-15 if len(text)-text_offset>max_chars else max_chars))
            trailing=text_end<len(text);partial=bool(text_offset or trailing)
            pagination={'text_truncated':partial,'text_offset':text_offset,'next_text_offset':text_end if trailing else None,'text_sha256':digest,'total_chars':len(text),'has_more':None,'coverage':'Single bounded native response. Upstream pagination preserved in text; completeness not inferred from local truncation. Text continuation must bind expected_text_sha256; SOURCE_CHANGED refuses drift.'}
            if type(data)is dict:
                for k in ('next_page_token','nextPageToken','nextCursor','next_cursor','cursor','nextOffset','next_offset','next_page','next_page_cursor','page','per_page','native_collection_cap','has_more','hasMore','incomplete','truncated','returned_truncated'):
                    if k in data and (data[k] is None or type(data[k])in(str,int,bool)):
                        pagination[k]=redact(data[k]) if type(data[k])is str else data[k]
            if spec['transport']=='github_rest_page':pagination['coverage']=data['coverage']
            elif spec['service']=='github':pagination['coverage']='One native PR status/check/diff response; no nested collection completeness claim.'
            text=text[text_offset:text_end]+('\n[TRUNCATED]' if trailing else '')
            return {'ok':True,'code':'PARTIAL' if partial else 'OK','message':'Native read completed; content is untrusted data. Credential containers may be replaced by [REDACTED]; not an unfiltered full-content export.','source':source,'text':text,'pagination':pagination,**({'_data':data} if full else {})}
        except UpstreamReadError as exc:
            return {'ok':False,'code':'UPSTREAM_ERROR','message':'Native API read failed; safe original status/codes retained. Raw payload omitted.','source':source,'text':json.dumps(exc.diagnostic,ensure_ascii=False,allow_nan=False),'pagination':{'has_more':None,'text_truncated':False}}
        except ReadError as exc:
            return {'ok':False,'code':str(exc),'message':'Read rejected or unavailable; raw diagnostics suppressed','source':source,'text':'','pagination':{'has_more':None,'text_truncated':False}}
        except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError,OSError):
            return {'ok':False,'code':'INVALID_RESPONSE','message':'Invalid native input/response; raw diagnostics suppressed','source':source,'text':'','pagination':{'has_more':None,'text_truncated':False}}
