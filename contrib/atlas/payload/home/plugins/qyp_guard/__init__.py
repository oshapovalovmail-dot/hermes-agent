"""Atlas deny-default guard. Only published ctx/session APIs; no monkey patches."""
import asyncio
import json
import os
import re
import uuid
import time
from pathlib import Path
from .broker import OWNER, Principal, Broker, DockerSandbox, DisabledSandbox, bound_principal, MAX_EXECUTION_SECONDS, ExportCancelled
from .code_research import SCOPES

TOOLS=frozenset(('qyp_exec','qyp_read','qyp_export','qyp_role','qyp_code_read'))


def principal():
    from gateway.session_context import get_session_env
    return bound_principal(get_session_env,os.environ)


def principal_for_binding(admission,binding,session_key):
    # Native directory plugins are home-scoped packages, not `qyp_guard` aliases.
    # Keep authority in the gate and materialize only this plugin's broker DTO.
    if not admission.valid(binding):raise PermissionError('bound_native_admission_required')
    return Principal(binding.user_id,session_key,'owner' if binding.user_id==OWNER else 'member',
        binding.profile,binding.chat_id,binding.thread_id or '')


def schema(name,description,properties,required):
    return {'name':name,'description':description,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}


SCHEMAS={
    'qyp_code_read':schema('qyp_code_read','Read UTF-8 source lines, list or literal-search within ONE explicitly selected approved Arcadia subtree. Read returns a hash-bound immutable /inputs copy for auxiliary scripts. No project writes, shell, credentials, mount-root discovery or symlinks. Search/list continuations are not a live-source snapshot.',{'operation':{'type':'string','enum':['read','list','search']},'scope':{'type':'string','enum':list(SCOPES)},'path':{'type':'string'},'start_line':{'type':'integer','minimum':1},'line_count':{'type':'integer','minimum':1,'maximum':200},'query':{'type':'string','minLength':1,'maxLength':256},'limit':{'type':'integer','minimum':1,'maximum':200},'after_path':{'type':'string'},'after_line':{'type':'integer','minimum':0}},['operation','scope','path']),
    'qyp_exec':schema('qyp_exec','Auxiliary Python/JS scripts only, in a no-network container. Review code/diffs and generate reports/documents; never apply project fixes, edit host source, commit, deploy or use Computer Use.',{'language':{'type':'string','enum':['python','javascript']},'code':{'type':'string','maxLength':65536},'timeout':{'type':'number','minimum':1,'maximum':MAX_EXECUTION_SECONDS,'default':MAX_EXECUTION_SECONDS}},['language','code']),
    'qyp_read':schema('qyp_read','Read a bounded UTF-8 sandbox result, never host projects, credentials or another user.',{'path':{'type':'string'}},['path']),
    'qyp_export':schema('qyp_export','Issue a private immutable report/document for this exact principal and chat.',{'path':{'type':'string'}},['path']),
    'qyp_role':schema('qyp_role','Bound Telegram role; owner has the same no-host/no-CU/no-Telegram-MCP ceiling.',{},[]),
}


class Service:
    def __init__(self,ctx):
        self.ctx=ctx
        root=ctx.get_config('root')
        if not isinstance(root,str) or not root:raise ValueError('operator_private_root_required')
        selected=ctx.get_config('sandbox_backend','disabled')
        backend=DisabledSandbox()
        if selected=='docker':
            backend=DockerSandbox(ctx.get_config('docker_image'),ctx.get_config('docker_host'),Path(root)/'control/docker-client',docker=ctx.get_config('docker_bin','/opt/homebrew/bin/docker'),python=ctx.get_config('container_python','/usr/local/bin/python3'),node=ctx.get_config('container_node'))
        elif selected=='podman':
            from .podman_backend import PodmanSandbox
            backend=PodmanSandbox(ctx.get_config('podman_image'),root,ctx.get_config('podman_metadata'))
        elif selected!='disabled':raise ValueError('unsupported_sandbox_backend')
        self.broker=Broker(root,backend=backend)
        from .code_research import CodeReader
        source_root=ctx.get_config('code_research_root')
        if source_root:
            from .readiness import verify_code_root
            if ctx.get_config('qualification_permit') is not None:
                from atlas_native_bridge.expanded_qualification import verify_input_root
                verify_input_root(ctx,source_root)
            else:verify_code_root(source_root)
        self.code_reader=CodeReader(source_root) if source_root else None
        self.media_integrated=ctx.get_config('media_policy_integrated',False) is True
        self._trace_bindings={}
        from .admission import ensure_gate
        self.admission=ensure_gate(ctx)

    def admitted_ids(self):
        control=self.ctx.get_config('admission_control')
        if control:
            from .admin import load_json
            return load_json(Path(control)/'admissions.json',{'admitted':[]})['admitted']
        return self.ctx.get_config('admitted_user_ids',[])

    def authorized_principal(self):
        binding=self.admission.check_current_sync()
        if self.ctx.profile_name!=binding.profile:raise PermissionError('exact_native_profile_required')
        from gateway.session_context import bound_session_key
        return principal_for_binding(self.admission,binding,bound_session_key())

    def guard_dispatch(self,event,session_key='',**kwargs):
        source=getattr(event,'source',None);platform=getattr(source,'platform',None);uid=getattr(source,'user_id',None)
        try:
            valid=self.admission.source_authorized(source)
        except Exception:valid=False
        if not valid:return {'action':'skip','reason':'atlas_identity_admission_or_exact_profile'}
        text=(getattr(event,'text','') or '').lstrip()
        getter=getattr(event,'get_command',None)
        command=getter() if callable(getter) else (text.split(None,1)[0][1:].split('@',1)[0] if text.startswith('/') else None)
        if command:
            command=command.lower().replace('_','-')
            allowed={'help','whoami','new','stop','status'}
            if uid==OWNER:allowed.add('atlas-access')
            if command not in allowed:return {'action':'skip','reason':'atlas_slash_ceiling'}
        if session_key and not command:
            from .policy import human_trace_urls
            urls=human_trace_urls(event,uid)
            if urls is not None:
                if len(self._trace_bindings)>=64:self._trace_bindings.pop(next(iter(self._trace_bindings)))
                self._trace_bindings[(uid,session_key)]=(time.monotonic()+900,tuple(urls))
        media=getattr(event,'media_urls',[]) or []
        snapshots=getattr(event,'inbound_attachment_snapshots',())
        if media:
            streamed=getattr(event,'_atlas_streamed_snapshots',None)
            if streamed is not None:
                try:
                    from atlas_native_bridge.attachments import BoundSnapshot
                    if (not session_key or self.ctx.profile_name!=source.profile
                            or len(streamed)!=len(media) or not self.admission.fresh_source_authorized(source)
                            or any(type(item) is not BoundSnapshot for item in streamed)):
                        raise PermissionError('issued_stream_snapshot_required')
                    who=principal_for_binding(self.admission,source._atlas_binding,session_key)
                    notes=[item.stage(self.broker,who,self.admission,source._atlas_binding) for item in streamed]
                    event.text+='\n[Selected read-only sandbox attachments: '+', '.join(notes)+']'
                    event.media_urls=[];event.media_types=[];event.media_filenames=[]
                    return None
                except (Exception,SystemExit):return {'action':'skip','reason':'attachment_stream_refused'}
            if not session_key or not snapshots or len(media)!=len(snapshots) or len(snapshots)>4:
                return {'action':'skip','reason':'bounded_transport_attachment_bytes_required'}
            try:
                who=principal_for_binding(self.admission,source._atlas_binding,session_key)
                notes=[]
                for index,(filename,content) in enumerate(snapshots):
                    suffix=Path(filename).suffix
                    if not re.fullmatch(r'\.[A-Za-z0-9]{1,10}',suffix):suffix='.bin'
                    name='attachment-'+uuid.uuid4().hex+suffix
                    self.broker.stage_input(who,name,content)
                    event.text=event.text.replace(media[index],'/inputs/'+name)
                    notes.append('/inputs/'+name)
                event.text+='\n[Selected read-only sandbox attachments: '+', '.join(notes)+']'
                event.media_urls=[];event.media_types=[]
            except Exception:return {'action':'skip','reason':'attachment_snapshot_refused'}
        return None

    def guard_tool(self,tool_name,args=None,**kwargs):
        try:
            who=self.authorized_principal()
            from .policy import allowed_tool,consume_mutation_grant,reviewed_mutation
            binding=self._trace_bindings.get((who.user_id,who.session_key))
            private=[{'user_id':who.user_id,'session_key':who.session_key,'url':url} for url in binding[1]] if binding and binding[0]>=time.monotonic() else []
            if tool_name in TOOLS or allowed_tool(self.ctx,who,tool_name,args or {},trace_bindings=private):return None
            control=self.ctx.get_config('admission_control')
            mutations=self.ctx.get_config('reviewed_mutation_tools',{})
            if control and isinstance(mutations,dict) and reviewed_mutation(tool_name,mutations.get(tool_name)) and consume_mutation_grant(Path(control),who,tool_name,args or {},kwargs.get('turn_id')):return None
            # Admission and every allow/grant predicate above are unchanged.
            # A reviewed service read reaching this point failed local preflight,
            # including unavailable/invalid pinned contracts; no upstream ran.
            from .policy import reviewed_read
            entries=self.ctx.get_config('reviewed_read_tools',{})
            entry=entries.get(tool_name) if isinstance(entries,dict) else None
            if reviewed_read(tool_name,entry) and entry['service']=='atlas_read' and entry['method'] in ('service_read','service_catalog'):
                return {'action':'block','message':'Local preflight input/contract rejection before upstream. Re-read service_catalog and correct exact field names and values; this is not an upstream ACL denial.'}
        except Exception:
            return {'action':'block','message':'Bound admitted private Telegram profile and valid policy required.'}
        return {'action':'block','message':'Capability outside reviewed principal ceiling.'}

    def guard_source(self,source,**kwargs):
        from types import SimpleNamespace
        try:allowed=self.admission.fresh_source_authorized(source)
        except Exception:allowed=False
        return {'policy':'qyp_guard','allow':allowed}

    def readiness(self,**kwargs):
        from .readiness import verify_service
        try:return verify_service(self)
        except (Exception,SystemExit):return {'policy':'qyp_guard','ready':False}

    def _guard_diagnostic(self,error):
        # Fixed public codes and booleans only. Never format exceptions/kwargs.
        import logging
        codes=frozenset(('ambient_identity_forbidden','bound_native_admission_required',
            'sync_recheck_on_gateway_loop_forbidden','verification_loop_unavailable',
            'fresh_verification_required','exact_native_profile_required'))
        code=error.args[0] if type(error) is PermissionError and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in codes else 'unclassified_guard_denial'
        seen=getattr(self,'_guard_diagnostic_seen',None)
        if seen is None:seen=self._guard_diagnostic_seen=set()
        if code in seen:return
        seen.add(code)
        snapshot={'binding_present':False,'binding_valid':False,'profile_equal':False,'session_key_present':False}
        try:
            from gateway.atlas_admission import current_binding
            from gateway.session_context import bound_session_key
            b=current_binding()
            snapshot.update(binding_present=b is not None,binding_valid=bool(self.admission.valid(b)),
                profile_equal=bool(b is not None and self.ctx.profile_name==b.profile),session_key_present=bool(bound_session_key()))
        except Exception:pass
        for name in ('PLATFORM','USER_ID','KEY','CHAT_TYPE'):
            snapshot['ambient_'+name.lower()]=('HERMES_SESSION_'+name) in os.environ
        logging.getLogger('atlas.guard').warning('ATLAS_GUARD_V1 %s %s',code,json.dumps(snapshot,sort_keys=True))

    def guard_llm(self,**kwargs):
        try:self.authorized_principal()
        except Exception as error:
            try:self._guard_diagnostic(error)
            except Exception:pass  # Telemetry must never replace the explicit veto.
            return {'action':'block','message':'Bound admitted private Telegram profile required.'}
        return None

    async def access(self,raw_args,**kwargs):
        # Staff admission replaces the former manual allowlist. This retired
        # owner-only command cannot grant a bypass or modify transport policy.
        return json.dumps({'ok':False,'error':'manual_admission_retired_use_verified_staff'})
    async def _retired_access(self,raw_args,**kwargs):
        try:
            who=self.authorized_principal()
            if who.user_id!=OWNER:raise PermissionError('owner_required')
            parts=raw_args.split(' ')
            if len(parts)!=2 or parts[0] not in ('add','revoke'):return 'Usage: /atlas_access add|revoke TELEGRAM_ID'
            from .admin import AccessAdmin
            home=self.ctx.get_config('admin_home');control=self.ctx.get_config('admission_control')
            if not home or not control:raise PermissionError('operator_admin_contract_required')
            admin=AccessAdmin(home,control,helper=self.ctx.get_config('admin_helper'))
            receipt=await asyncio.to_thread(admin.apply,who.user_id,parts[0],parts[1])
            native=await self.ctx.refresh_gateway_profiles()
            if parts[0]=='add':
                receipt=admin.activate(parts[1],native,generation=receipt['generation'])
                await self.ctx.refresh_gateway_profiles()
            return json.dumps(receipt)
        except Exception as error:return json.dumps({'ok':False,'error':type(error).__name__})

    def code_read(self,args,*,cancel_check=None):
        import io
        who=self.authorized_principal()
        if self.code_reader is None:raise PermissionError('operator_source_root_required')
        if cancel_check is not None and cancel_check():raise PermissionError('code_read_cancelled')
        result,data=self.code_reader.query(args)
        if self.authorized_principal()!=who:raise PermissionError('code_read_principal_changed')
        if cancel_check is not None and cancel_check():raise PermissionError('code_read_cancelled')
        if data is not None:
            name='code-'+result['sha256']+'.txt'
            self.broker.stage_input_stream(who,name,io.BytesIO(data),size=len(data),sha256=result['sha256'],cancel_check=cancel_check)
            result['sandbox_input']='/inputs/'+name
        if self.authorized_principal()!=who:raise PermissionError('code_read_principal_changed')
        return result

    def handler(self,name):
        def handle(args,**kwargs):
            try:
                who=self.authorized_principal();shape=SCHEMAS[name]['parameters']
                if not isinstance(args,dict) or set(args)-set(shape['properties']) or set(shape['required'])-set(args):return json.dumps({'ok':False,'error':'invalid_arguments'})
                if name=='qyp_role':result={'user_id':who.user_id,'role':who.role,'ceiling':'isolated_auxiliary_only'}
                elif name=='qyp_exec':
                    from tools.interrupt import is_interrupted
                    result=self.broker.execute(who,args['language'],args['code'],args.get('timeout',MAX_EXECUTION_SECONDS),cancel_check=is_interrupted)
                elif name=='qyp_read':result={'text':self.broker.read(who,args['path']).decode('utf-8','replace')}
                elif name=='qyp_code_read':
                    from tools.interrupt import is_interrupted
                    result=self.code_read(args,cancel_check=is_interrupted)
                else:
                    if not self.media_integrated:return json.dumps({'ok':False,'error':'media_policy_not_integrated'})
                    from tools.interrupt import is_interrupted, run_if_not_interrupted
                    result=self.broker.export(who,args['path'],cancel_check=is_interrupted,
                        commit_if_not_cancelled=run_if_not_interrupted)
                return json.dumps({'ok':True,**result})
            except FileNotFoundError:return json.dumps({'ok':False,'error':'source_not_found','errno':'ENOENT'})
            except ExportCancelled:return json.dumps({'ok':False,'error':'cancelled'})
            except Exception as error:return json.dumps({'ok':False,'error':type(error).__name__})
        return handle


def register(ctx):
    from atlas_work_read.native import configure
    configure(ctx)
    from atlas_native_bridge.factory import configure_memory
    configure_memory(ctx)
    service=Service(ctx)
    for name in sorted(TOOLS):
        options={'execution_timeout':MAX_EXECUTION_SECONDS+120} if name=='qyp_exec' else {}
        ctx.register_tool(name=name,toolset='qyp_guard',schema=SCHEMAS[name],handler=service.handler(name),**options)
    ctx.register_hook('pre_tool_call',service.guard_tool)
    ctx.register_hook('pre_llm_call',service.guard_llm)
    ctx.register_hook('pre_gateway_dispatch',service.guard_dispatch)
    ctx.register_hook('required_gateway_policy',service.readiness)
    ctx.register_hook('required_gateway_source',service.guard_source)
    ctx.register_command('atlas-access',service.access,description='Owner-only exact native profile admission',args_hint='add|revoke TELEGRAM_ID')
    if service.media_integrated:
        from .pending_media import register_pending
        register_pending(ctx,service)
