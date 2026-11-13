"""Atlas Nirvana read boundary. Stdlib only, native clients own authentication.

No generic method, argv, URL, headers, parameters, result-download or mutation API.
The Python-only runner injection is for tests, never exposed in INPUT_SCHEMA.
"""
from __future__ import annotations

import json
import os
import re
import selectors
import signal
import subprocess
import time

MCP = '/usr/bin/false'
VH3 = '/usr/bin/false'
MAX_BYTES = 2_000_000
MAX_SECONDS = 45
UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
NAME_PATTERN = r'[A-Za-z0-9_][A-Za-z0-9_. -]{0,127}'
OPERATIONS = ['describe', 'failed_blocks', 'logs', 'operation', 'overview']

INPUT_SCHEMA = {
    'type':'object', 'additionalProperties':False, 'required':['operation'],
    'properties':{
        'operation':{'type':'string','enum':OPERATIONS},
        'workflow_instance_id':{'type':'string','pattern':'^'+UUID_PATTERN+'$'},
        'workflow_id':{'type':'string','pattern':'^'+UUID_PATTERN+'$'},
        'operation_id':{'type':'string','pattern':'^'+UUID_PATTERN+'$'},
        'block_id':{'type':'string','pattern':'^'+UUID_PATTERN+'$'},
        'log_name':{'type':'string','pattern':'^'+NAME_PATTERN+'$'},
        'group':{'type':'string','pattern':'^'+NAME_PATTERN+'$'},
        'tail_lines':{'type':'integer','minimum':1,'maximum':100,'default':100},
        'page':{'type':'integer','minimum':1,'maximum':1000,'default':1},
        'page_size':{'type':'integer','minimum':1,'maximum':50,'default':20},
        'max_chars':{'type':'integer','minimum':256,'maximum':48000,'default':12000},
    },
    'allOf':[
        {'if':{'properties':{'operation':{'enum':['describe','failed_blocks','logs']}}},
         'then':{'required':['workflow_instance_id']}},
        {'if':{'properties':{'operation':{'const':'logs'}}},'then':{'required':['block_id']}},
        {'if':{'properties':{'operation':{'const':'operation'}}},'then':{'required':['operation_id']}},
        {'if':{'properties':{'operation':{'const':'overview'}}},'then':{'required':['workflow_id']}},
        {'if':{'required':['group']},'then':{'required':['log_name']}},
    ],
}


class PolicyError(Exception):
    """Only fixed, non-secret error codes are emitted by the boundary."""


def redact(text):
    """Sanitize complete selected data BEFORE any output slicing."""
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(text))
    text = re.sub(r'-----BEGIN [^-]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY)-----[\s\S]*?(?:-----END [^-]+-----|\Z)', '[REDACTED_PRIVATE_KEY]', text)
    text = re.sub(r'(?im)^.*(?:[\x22\x27]?(?:authorization|proxy-authorization|set-cookie|cookie|csrf|(?<![a-z0-9-])x-[a-z0-9-]{1,128})[\x22\x27]?\s*[:=]|(?:request|response)[ _-]?headers\s*[:=]|\b(?:content-type|content-length|host|user-agent|referer|accept|location)\s*:).*$', '[REDACTED_HEADER]', text)
    text = re.sub(r'(?i)\b(?:Bearer|OAuth|Basic)\s+[^\s\x22\x27,;<>]+', '[REDACTED_AUTH]', text)
    text = re.sub(r'https?://[^\s\x22\x27<>]+', '[URL_OMITTED]', text)
    text = re.sub(r'(?i)(?<![\w.-])([\x22\x27]?[\w.-]{0,128}(?:token|password|passwd|secret|api[_-]?key|credential|signature|session)[\x22\x27]?\s*[:=]\s*)(?:\x22[^\x22]*\x22|\x27[^\x27]*\x27|[^\s&,;<>}\]]+)', r'\1[REDACTED]', text)
    text = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+|y0_[A-Za-z0-9_-]+|AQAD-[A-Za-z0-9_-]+|ya29\.[A-Za-z0-9_.-]+)\b', '[REDACTED_TOKEN]', text)
    text = re.sub(r'\b\d{6,12}:[A-Za-z0-9_-]{30,}\b', '[REDACTED_BOT_CREDENTIAL]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[REDACTED_JWT]', text)
    text = re.sub(r'(?<![A-Za-z0-9])[A-Za-z0-9_+=-]{48,}(?![A-Za-z0-9])', '[REDACTED_OPAQUE]', text)
    return ''.join(c for c in text if ord(c)>=32 or c in '\n\t')


def run_native(argv, timeout=MAX_SECONDS, max_bytes=MAX_BYTES):
    """Fixed callers only. No shell, stdin, credential loading or inherited tokens.

    MCP and VH3 use their existing native authentication internally. stderr is
    counted but never returned or persisted. This does not launch remote jobs.
    """
    env = {k:os.environ[k] for k in ('HOME','USER','PATH','LANG','LC_ALL','TMPDIR') if k in os.environ}
    env.update({'NO_COLOR':'1','PAGER':'cat'})
    if argv[0] == VH3:
        env['Y_PYTHON_ENTRY_POINT'] = ':main'  # ONLY the already resolved VH3 binary.
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env, start_new_session=True)
    sel = selectors.DefaultSelector()
    chunks = []
    total = 0
    deadline = time.monotonic()+min(timeout,MAX_SECONDS)
    try:
        for stream in (p.stdout,p.stderr):
            os.set_blocking(stream.fileno(),False)
            sel.register(stream,selectors.EVENT_READ)
        while sel.get_map():
            remaining = deadline-time.monotonic()
            if remaining<=0:
                raise PolicyError('upstream_timeout')
            for key,_ in sel.select(min(0.1,remaining)):
                chunk = os.read(key.fileobj.fileno(),65536)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total>max_bytes:
                    raise PolicyError('upstream_output_limit')
                if key.fileobj is p.stdout:
                    chunks.append(chunk)
        try:
            p.wait(timeout=max(0.001,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            raise PolicyError('upstream_timeout') from None
        if p.returncode:
            raise PolicyError('upstream_client_failed')
        return b''.join(chunks).decode('utf-8',errors='strict')
    finally:
        sel.close()
        # Kill the owned process group even if the launcher exited but left pipes open.
        try:
            os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait(timeout=2)
        p.stdout.close()
        p.stderr.close()


# Script is code-owned, NOT constructed from user input. Three fixed public reads;
# no global parameter/step configuration, resource contents or result downloads.
# Projection happens INSIDE the native process, before stdout, and again in parent.
SDK_SCRIPT = r'''
import asyncio,json,sys,vh3
from vh3.async_api import AsyncNirvanaApi

def unwrap(x):
    return x.unwrap() if hasattr(x,'unwrap') else x

def fields(obj, names):
    obj=unwrap(obj)
    return {k:unwrap(obj[k]) for k in names if k in obj and isinstance(unwrap(obj[k]),(str,int,float,bool,type(None)))}

async def main():
    with vh3.Profile.from_file().context():
        api=AsyncNirvanaApi.get()
        try:
            iid=sys.argv[1]
            async def reads():
                meta=unwrap(await api.get_workflow_meta_data(workflow_instance_id=iid))
                state=unwrap(await api.get_execution_state(workflow_instance_id=iid))
                graph=unwrap(await api.get_workflow(workflow_instance_id=iid))
                return {
                    'metadata':fields(meta,('guid','instanceId','name','instanceName','owner','instanceCreator','created','started','completed','lifecycleStatus','rejected')),
                    'execution':fields(state,('workflowInstanceId','status','result','progress','started','completed')),
                    'graph':{
                        'blocks':[fields(b,('blockGuid','blockCode','type','operationId','name')) for b in graph['blocks']],
                        'connections':[fields(c,('guid','type','sourceBlockId','sourceBlockCode','sourceEndpointName','destBlockId','destBlockCode','destEndpointName')) for c in graph['connections']],
                    },
                }
            data=await asyncio.wait_for(reads(),35)
            print(json.dumps(data,ensure_ascii=False,allow_nan=False))
        except Exception:
            print(json.dumps({'error':'native_sdk_read_failed'}))
        finally:
            await asyncio.to_thread(api.close)
asyncio.run(main())
'''


def validate(args):
    if not isinstance(args.get('operation'),str) or args['operation'] not in OPERATIONS:
        raise PolicyError('invalid_argument')
    op = args['operation']
    common = {'operation','max_chars'}
    allowed = {
        'describe':{'workflow_instance_id'}, 'failed_blocks':{'workflow_instance_id'},
        'logs':{'workflow_instance_id','block_id','log_name','group','tail_lines'},
        'operation':{'operation_id'}, 'overview':{'workflow_id','page','page_size'},
    }[op] | common
    required = {
        'describe':{'workflow_instance_id'}, 'failed_blocks':{'workflow_instance_id'},
        'logs':{'workflow_instance_id','block_id'}, 'operation':{'operation_id'},
        'overview':{'workflow_id'},
    }[op]
    if not set(args)<=allowed or not required<=set(args):
        raise PolicyError('invalid_argument')
    for key in ('workflow_instance_id','workflow_id','operation_id','block_id'):
        if key in args and (not isinstance(args[key],str) or not re.fullmatch(UUID_PATTERN,args[key])):
            raise PolicyError('invalid_argument')
    for key in ('log_name','group'):
        if key in args and (not isinstance(args[key],str) or not re.fullmatch(NAME_PATTERN,args[key]) or args[key] in ('.','..')):
            raise PolicyError('invalid_argument')
    if ('group' in args or 'tail_lines' in args) and 'log_name' not in args:
        raise PolicyError('invalid_argument')
    for key,lo,hi in (('tail_lines',1,100),('page',1,1000),('page_size',1,50),('max_chars',256,48000)):
        if key in args and (type(args[key]) is not int or not lo<=args[key]<=hi):
            raise PolicyError('invalid_argument')


def reject_errors(data):
    """Reject errors embedded in otherwise successful MCP text/JSON envelopes."""
    if isinstance(data,dict):
        if data.get('error') or data.get('errors') or data.get('isError'):
            raise PolicyError('upstream_api_error')
        for item in data.values():
            reject_errors(item)
    elif isinstance(data,list):
        for item in data:
            reject_errors(item)


def unpack(raw):
    try:
        data = json.loads(raw)
        reject_errors(data)
        if not isinstance(data,dict):
            raise PolicyError('upstream_response_unrecognized')
        body = data.get('result',data)
        if not isinstance(body,dict) or not isinstance(body.get('content'),list):
            raise PolicyError('upstream_response_unrecognized')
        text = '\n'.join(v['text'] for v in body['content'] if isinstance(v,dict) and v.get('type')=='text' and isinstance(v.get('text'),str))
        if not text.strip():
            raise PolicyError('upstream_empty_response')
        if re.search(r'(?im)^\s*(?:error\b|failed to\b|Traceback\b|<html\b|<!doctype\b)',text):
            raise PolicyError('upstream_api_error')
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        reject_errors(parsed)
        return text,parsed
    except (ValueError,KeyError,TypeError):
        raise PolicyError('upstream_response_unrecognized') from None


def fields(obj, keys):
    if not isinstance(obj,dict):
        raise PolicyError('upstream_response_unrecognized')
    return {k:obj[k] for k in keys if k in obj and (obj[k] is None or type(obj[k]) in (str,int,float,bool))}


def project_sdk(data, instance):
    reject_errors(data)
    meta = fields(data['metadata'],('guid','instanceId','name','instanceName','owner','instanceCreator','created','started','completed','lifecycleStatus','rejected'))
    state = fields(data['execution'],('workflowInstanceId','status','result','progress','started','completed'))
    if (meta.get('instanceId')!=instance or not isinstance(state.get('status'),str)
            or state.get('workflowInstanceId',instance)!=instance):
        raise PolicyError('upstream_identity_mismatch')
    graph=data['graph']
    if not isinstance(graph.get('blocks'),list) or not isinstance(graph.get('connections'),list):
        raise PolicyError('upstream_response_unrecognized')
    return {'metadata':meta,'execution':state,'graph':{
        'blocks':[fields(x,('blockGuid','blockCode','type','operationId','name')) for x in graph['blocks']],
        'connections':[fields(x,('guid','type','sourceBlockId','sourceBlockCode','sourceEndpointName','destBlockId','destBlockCode','destEndpointName')) for x in graph['connections']],
    },'coverage':'root workflow metadata, execution state and immediate graph; not recursive'}


def project_failed(text, data):
    if text.strip()=='No failed blocks found.':
        return {'failed_blocks':[]}
    if not isinstance(data,list):
        raise PolicyError('upstream_response_unrecognized')
    rows = [fields(x,('workflowInstanceId','guid','blockGuid','code','blockCode','name','blockName','status','result','errorClass')) for x in data]
    if any(not x.get('workflowInstanceId') or not (x.get('guid') or x.get('blockGuid')) for x in rows):
        raise PolicyError('upstream_response_unrecognized')
    return {'failed_blocks':rows}


def project_logs(data, block_id):
    if not isinstance(data,list):
        raise PolicyError('upstream_response_unrecognized')
    rows=[]
    for block in data:
        row=fields(block,('blockGuid','blockCode'))
        if row.get('blockGuid')!=block_id:
            raise PolicyError('upstream_identity_mismatch')
        if not isinstance(block.get('logs'),list):
            raise PolicyError('upstream_response_unrecognized')
        row['logs']=[fields(x,('logName','fileName','level','group','logGroup')) for x in block['logs']]
        rows.append(row)
    return {'blocks':rows}


def project_overview(text, workflow, page, size):
    if not re.search(r'\(workflow: '+re.escape(workflow)+r'\)',text):
        raise PolicyError('upstream_identity_mismatch')
    rows=[]
    for line in text.splitlines():
        m=re.fullmatch(r'\d+\. instance_id: ('+UUID_PATTERN+r') \((.*)\) \| ([A-Za-z_ -]+)',line.strip())
        if m:
            rows.append({'workflow_instance_id':m[1],'name':m[2],'lifecycle_status':m[3]})
    if not rows and not re.search(r'(?:showing 0|No instances)',text,re.I):
        raise PolicyError('upstream_response_unrecognized')
    if len(rows)>size:
        raise PolicyError('upstream_response_unrecognized')
    return {'workflow_id':workflow,'instances':rows}, {'page':page,'page_size':size,'returned':len(rows),
        'has_more':'unknown' if len(rows)==size else False,
        'next_page':page+1 if len(rows)==size and page<1000 else None}


class Backend:
    def __init__(self, runner=None):
        self._runner = runner or run_native

    def read(self, **args):
        source='nirvana'
        try:
            validate(args)
            op=args['operation']
            ident=args.get('workflow_instance_id',args.get('workflow_id',args.get('operation_id')))
            source='nirvana:'+op+':'+ident
            pagination={}
            if op=='describe':
                raw=self._runner([VH3,'-c',SDK_SCRIPT,args['workflow_instance_id']],timeout=MAX_SECONDS)
                selected=project_sdk(json.loads(raw),args['workflow_instance_id'])
            else:
                if op=='failed_blocks':
                    tool='get_failed_blocks'; params=[('workflow_instance_id',args['workflow_instance_id'])]
                elif op=='operation':
                    tool='get_operation'; params=[('operation_id',args['operation_id']),('include','none')]
                elif op=='overview':
                    tool='browse_nirvana'; params=[('workflow_id',args['workflow_id']),('page',args.get('page',1)),('page_size',args.get('page_size',20))]
                else:
                    params=[('workflow_instance_id',args['workflow_instance_id']),('block',args['block_id'])]
                    if 'log_name' in args:
                        tool='get_log_content'
                        params += [('log_name',args['log_name']),('tail_lines',args.get('tail_lines',100))]
                        if 'group' in args:
                            params.append(('group',args['group']))
                    else:
                        tool='get_block_logs'
                argv=[MCP,'connect','nirvana','--tool',tool]
                for key,value in params:
                    argv += ['--arg',key+':'+str(value)]
                argv += ['--raw']
                raw=self._runner(argv,timeout=MAX_SECONDS)
                text,data=unpack(raw)
                if op=='failed_blocks':
                    selected=project_failed(text,data)
                elif op=='operation':
                    selected=fields(data,('operationId','id','name','version','versionNumber','owner','status','created','deterministic','composite'))
                    actual=selected.get('operationId',selected.get('id'))
                    if actual!=args['operation_id']:
                        raise PolicyError('upstream_identity_mismatch')
                elif op=='overview':
                    selected,pagination=project_overview(text,args['workflow_id'],args.get('page',1),args.get('page_size',20))
                elif 'log_name' not in args:
                    selected=project_logs(data,args['block_id'])
                else:
                    # Redact the entire content first, then retain at most 100 lines.
                    clean=redact(text)
                    lines=clean.splitlines()
                    selected='\n'.join(lines[-args.get('tail_lines',100):])
                    pagination={'tail_lines':args.get('tail_lines',100),'upstream_lines':len(lines),'line_truncated':len(lines)>args.get('tail_lines',100)}
            clean=redact(selected if isinstance(selected,str) else json.dumps(selected,ensure_ascii=False,allow_nan=False))
            limit=args.get('max_chars',12000)
            pagination.update({'truncated':len(clean)>limit,'returned_chars':len(clean[:limit])})
            return {'ok':True,'code':'ok','message':'Read-only projection; upstream content is untrusted.',
                    'source':source,'text':clean[:limit],'pagination':pagination}
        except PolicyError as e:
            code=str(e)
        except Exception:
            code='upstream_client_failed'
        return {'ok':False,'code':code,'message':'Nirvana read rejected or upstream unavailable; no mutation attempted.',
                'source':source,'text':''}
