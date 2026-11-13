"""Operator-reviewed capability table, not MCP annotations or model claims."""
import hashlib
import json
import re
import time
from .broker import OWNER

LOCAL = frozenset(('memory','skills_list','skill_view'))
HONCHO = frozenset(('honcho_profile','honcho_search','honcho_context','honcho_reasoning','honcho_conclude'))
READ_METHODS = {
    'atlas_read': frozenset(('integration_status','wiki_read','tracker_read','pr_read','trace_read','nirvana_read','yt_read','datalens_read','service_catalog','service_read')),
    'tracker': frozenset(('get_issue','search_issues','get_comments','get_transitions','get_issue_changelog','get_queue','list_queues','get_user','get_worklogs')),
    'wiki': frozenset(('get_page','get_page_content','search_pages','get_grid','get_grid_rows','get_comments','get_attachments')),
    'github': frozenset(('get_pull_request','get_pull_request_diff','get_pull_request_files','get_pull_request_comments','get_pull_request_reviews','get_file_contents','search_code','get_issue','list_commits')),
}
# Mutations can only target external reviewed integrations, never host, CU, MCP
# management, Telegram, deployment or repository writes. PR comments need an
# external control-plane proof; no author name supplied by a model is evidence.
MUTATION_METHODS = {'atlas_read': frozenset(), 'tracker': frozenset(('update_issue','add_comment')),
                    'wiki': frozenset(('update_page','add_comment')),
                    'github': frozenset(('add_pull_request_comment',))}


def reviewed_read(name, entry):
    return (isinstance(entry,dict) and set(entry)=={'service','method','access','reviewed'}
            and entry['reviewed'] is True and entry['access']=='read'
            and entry['method'] in READ_METHODS.get(entry['service'],())
            and name in (f"mcp__{entry['service']}__{entry['method']}",f"mcp_{entry['service']}_{entry['method']}",f"connectors__{entry['service']}__{entry['method']}",f"{entry['service']}_{entry['method']}")
            and re.fullmatch(r'[A-Za-z0-9_-]+',name) is not None
            and not re.search(r'telegram|userbot|messaging|localhost|18724',name,re.I))


_SERVICE_MODULES={}

def _approved_service_input(ctx,method,args):
    """Compile the pinned admitted bytes, then enforce its actual backend schema.

    Only trusted configuration supplies the path/pin, never model arguments.
    Every call rechecks source plus its code-owned adjacent catalogs/backends.
    """
    import importlib.util
    from pathlib import Path
    import sys,threading
    try:
        typed=ctx.get_config('typed_work_read')
        if typed is not None:
            from atlas_work_read.bundle import Bundle
            if type(typed)is not dict or set(typed)!={'bundle_root','bundle_pins'}:return False
            bundle=Bundle(typed['bundle_root'],typed['bundle_pins'])
            return bundle.module.service_input_valid(method,args)
        pin=(ctx.get_config('reviewed_stdio_servers',{}) or {})['atlas_read']
        argv=pin['args']
        if len(argv)<3 or argv[:2]!=['-I','-B']:return False
        path=Path(argv[2]);sha=pin['source_sha256']
        if not path.is_absolute() or path.is_symlink() or path.stat().st_size>262144:return False
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=sha:return False
        key=(str(path),sha)
        if key not in _SERVICE_MODULES:
            spec=importlib.util.spec_from_file_location('_atlas_guard_schema_'+sha,path)
            module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
            exec(compile(data,str(path),'exec',dont_inherit=True),module.__dict__)
            _SERVICE_MODULES[key]=module
        return _SERVICE_MODULES[key].service_input_valid(method,args)
    except Exception:return False


def allowed_tool(ctx, who, name, args, *, trace_bindings=()):
    if not isinstance(args,dict):return False
    if name in LOCAL:return True
    if name in HONCHO:
        expected=who.profile or 'tg-'+who.user_id
        for key in ('currentprofile','current_profile','profile','profile_id','user_id'):
            if key in args and args[key] not in (None,'',expected):return False
        return args.get('peer') in (None,'user','ai') and args.get('peer_id') in (None,'user','ai')
    traces=ctx.get_config('reviewed_trace_tools',{})
    if isinstance(traces,dict) and name in traces:
        entry=traces[name]
        bindings=list(ctx.get_config('trace_read_bindings',[]))+list(trace_bindings)
        return (entry=={'kind':'trace_dom_read','broker':'trusted_trace_broker','background_only':True}
                and set(args)<= {'url','tab_id','view'} and {'url','tab_id'}<=set(args)
                and args.get('view','dom') in ('dom','trace') and isinstance(bindings,list)
                and any(isinstance(b,dict) and b.get('user_id')==who.user_id
                        and b.get('session_key')==who.session_key and b.get('url')==args['url']
                        and b.get('tab_id')==args['tab_id'] for b in bindings))
    entries=ctx.get_config('reviewed_read_tools',{})
    entry=entries.get(name) if isinstance(entries,dict) else None
    if isinstance(entry,dict) and entry.get('service')=='atlas_read':
        if entry.get('method')=='datalens_read' and args.get('view','summary') not in ('summary','data'):return False
        if entry.get('method') in ('service_catalog','service_read'):
            if not _approved_service_input(ctx,entry['method'],args):return False
        if entry.get('method')=='yt_read':
            # Ordinary service native ACL, identical for owner/member. Filesystem
            # Arcadia ceilings remain separate and unchanged.
            if args.get('operation') not in ('exists','attributes','list','schema','sample'):return False
    if name=='mcp__atlas_read__trace_read':
        if ctx.get_config('typed_work_read') is not None:
            from atlas_work_read.native import allow_original_trace
            return reviewed_read(name,entries.get(name)) and allow_original_trace(args)
        bindings=list(ctx.get_config('trace_read_bindings',[]))+list(trace_bindings)
        if (set(args)-{'url','max_chars'} or not isinstance(bindings,list) or
                not any(isinstance(b,dict) and b.get('user_id')==who.user_id and b.get('session_key')==who.session_key and b.get('url')==args.get('url') for b in bindings)):
            return False
    return isinstance(entries,dict) and reviewed_read(name,entries.get(name))


def human_trace_urls(event,uid):
    """Original authenticated Telegram text/caption, never model args or document content."""
    from urllib.parse import urlsplit,parse_qsl
    raw=getattr(event,'raw_message',None)
    sender=getattr(raw,'from_user',None);chat=getattr(raw,'chat',None)
    if (raw is None or str(getattr(sender,'id',''))!=uid or getattr(sender,'is_bot',True)
            or str(getattr(chat,'id',''))!=uid or getattr(chat,'type',None)!='private'):
        return None
    text=getattr(raw,'text',None) or getattr(raw,'caption',None) or ''
    urls=[]
    from atlas_work_read.rpc import original_human_urls
    for url in original_human_urls(text)[:8]:
        try:
            p=urlsplit(url)
            if len(url)>4096 or '\\' in url or '%' in p.path or p.scheme!='https' or p.netloc not in ('monium.yandex-team.ru','setrace.yandex-team.ru') or p.fragment or '..' in p.path.split('/'):continue
            if p.hostname=='setrace.yandex-team.ru':
                if not re.fullmatch(r'/(?:t/alice/[A-Za-z0-9_-]+|alice/trace/[A-Za-z0-9_-]+/[0-9]+)/?',p.path):continue
            elif not re.search(r'/(?:traces?|trace-explorer)(?:/|$)',p.path):continue
            fields=parse_qsl(p.query,keep_blank_values=True,max_num_fields=32)
            if any(re.search(r'token|password|secret|key|cookie|auth|credential|signature|next|redirect|url|target|script',k,re.I) or len(v)>2048 or re.search(r'https?[:]|javascript[:]|file[:]',v,re.I) for k,v in fields):continue
            urls.append(url)
        except ValueError:continue
    return urls


def args_digest(args):
    return hashlib.sha256(json.dumps(args,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def reviewed_mutation(name, entry):
    return (isinstance(entry,dict) and set(entry)=={'service','method','access','reviewed'}
            and entry['reviewed'] is True and entry['access']=='mutation'
            and entry['method'] in MUTATION_METHODS.get(entry['service'],())
            and name in (f"mcp__{entry['service']}__{entry['method']}",f"mcp_{entry['service']}_{entry['method']}",f"connectors__{entry['service']}__{entry['method']}",f"{entry['service']}_{entry['method']}"))


def consume_mutation_grant(control, who, name, args, turn_id):
    """One-use exact-operation grant from trusted control plane, never the LLM.

    The owner identity/PR-author proof must be verified by the external issuer.
    No grant can authorize a host tool or Telegram. A missing real turn ID denies.
    """
    from .admin import control_lock, load_json, save_json
    if not isinstance(turn_id,str) or not turn_id:return False
    with control_lock(control):
        data=load_json(control/'mutation-grants.json',{'grants':[]})
        for grant in data.get('grants',[]):
            if not isinstance(grant,dict) or grant.get('consumed'):continue
            if (grant.get('user_id')!=who.user_id or grant.get('session_key')!=who.session_key
                    or grant.get('turn_id')!=turn_id or grant.get('tool')!=name
                    or grant.get('args_sha256')!=args_digest(args)
                    or not isinstance(grant.get('expires'),(int,float)) or grant['expires']<time.time()):continue
            service=grant.get('service');method=grant.get('method')
            if method not in MUTATION_METHODS.get(service,()):continue
            if name not in (f'mcp__{service}__{method}',f'mcp_{service}_{method}',f'connectors__{service}__{method}',f'{service}_{method}'):continue
            auth=grant.get('authorization',{})
            owner=auth.get('kind')=='owner_exact_operation' and auth.get('verified_actor_id')==OWNER
            author=(service=='github' and method=='add_pull_request_comment'
                    and auth.get('kind')=='verified_pr_author_exact_operation'
                    and auth.get('verified_actor_id')==who.user_id
                    and isinstance(auth.get('proof_receipt'),str) and bool(auth['proof_receipt'])
                    and auth.get('repository')==args.get('repository')
                    and auth.get('pull_number')==args.get('pull_number'))
            if author:
                proof_id=auth['proof_receipt']
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',proof_id):continue
                proof=load_json(control/'proofs'/(proof_id+'.json'),{})
                author=(proof.get('source')=='trusted_pr_identity_verifier'
                        and proof.get('verified_actor_id')==who.user_id
                        and proof.get('repository')==args.get('repository')
                        and proof.get('pull_number')==args.get('pull_number')
                        and proof.get('session_key')==who.session_key
                        and proof.get('turn_id')==turn_id
                        and proof.get('args_sha256')==args_digest(args))
            if not (owner or author):continue
            grant['consumed']=True;save_json(control/'mutation-grants.json',data);return True
    return False
