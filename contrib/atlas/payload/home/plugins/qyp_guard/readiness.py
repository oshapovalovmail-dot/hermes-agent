"""Fail-closed startup contract. No model, auth refresh, or external MCP probes."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from .broker import Principal, OWNER, _IDENTITY
from .policy import READ_METHODS, MUTATION_METHODS, LOCAL, HONCHO, reviewed_read, reviewed_mutation

BASE_TOOLSETS=frozenset(('qyp_guard','memory','skills'))

def verify_code_root(root):
    import hashlib
    # Exact operator mount pins; no local usernames in the distributed source.
    # Pure binding check: an optional missing frontend subtree is ENOENT on its
    # own request, never a reason to block all other approved source reads.
    if type(root)is not str or hashlib.sha256(root.encode('utf-8','surrogatepass')).hexdigest() not in ('2ab3220bb5813a4186e6cf6607edf9ae95d383315f56e6c7ded43539ed8b6d85', 'fbff7b2e39ddd97249888e6a2b5095ca2428726485bede6b485f42e3c0af3c92', '067b1d8e58d9c132a81a511e079a5bca71d5f97da645a67f4e684613b8f6868f'):
        raise PermissionError('approved_operator_code_root_required')


def verify_required_read_tools(settings,names):
    required=settings.get('required_read_tools',[])
    if (not isinstance(required,list) or not all(isinstance(name,str) for name in required)
            or len(required)!=len(set(required)) or not set(required)<=set(names)):
        raise PermissionError('required_read_tools_missing_or_invalid')


def verify_read_bundle(sidecar,settings):
    import hashlib
    expected={'sidecar.py','tracker_wiki_backend.py','tracker_wiki_catalog.json','work_services_backend.py','work_services_manifest.json','read_paging.py','read_snapshot_store.py','datalens_backend.py','nirvana_backend.py','yt_backend.py','select_parser.py'}
    files=settings.get('reviewed_service_files')
    if not isinstance(files,dict) or set(files)!=expected:raise PermissionError('exact_read_bundle_required')
    for name,sha in files.items():
        path=Path(sidecar).parent/name
        limit=16_000_000 if name in ('work_services_manifest.json','tracker_wiki_catalog.json') else 2_000_000
        if path.is_symlink() or not path.is_file() or path.stat().st_size>limit or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise PermissionError('read_bundle_hash_mismatch')


def verify_profile_stdio(cfg,profile_home):
    """Only this trusted native profile directory can identify its stdio route."""
    home=Path(profile_home)
    server=(cfg.get('mcp_servers') or {}).get('atlas_read')
    if server is None:return
    pin=cfg['plugins']['entries']['qyp_guard']['settings']['reviewed_stdio_servers'].get('atlas_read') or {}
    if (home.is_symlink() or not home.is_absolute() or not home.is_dir()
            or server.get('cwd')!=str(home.resolve()) or pin.get('cwd')!=str(home.resolve())):
        raise PermissionError('exact_profile_stdio_cwd_required')


def verify_config(cfg,*,profile_home=None):
    def require(value,message):
        if not value:raise PermissionError(message)
    entry=((cfg.get('plugins') or {}).get('entries') or {}).get('qyp_guard') or {}
    settings=entry.get('settings') or {}
    require(settings.get('admission_mode')=='verified_staff_or_official_tasha_administrator','native_staff_tasha_admission_required')
    require(type(settings.get('tasha_bot_id')) is int and settings['tasha_bot_id']==793835103,'official_numeric_tasha_required')
    require(((cfg.get('telegram') or {}).get('extra') or {}).get('atlas_admission') is True,'native_telegram_intake_and_sdk_guard_required')
    require(entry.get('enabled') is True,'guard_required')
    require('qyp_guard' in (cfg.get('plugins') or {}).get('enabled',[]),'guard_native_discovery_enable_required')
    require((cfg.get('plugins') or {}).get('isolation','in_process')=='in_process','guard_must_run_in_process')
    require(settings.get('sandbox_backend') in ('docker','podman'),'verified_container_backend_required')
    verify_code_root(settings.get('code_research_root'))
    require(settings.get('media_policy_integrated') is True,'installed_media_policy_required')
    require((cfg.get('media_delivery') or {}).get('required_policy')=='qyp_guard','mandatory_media_policy_required')
    gateway=cfg.get('gateway') or {}
    require(gateway.get('multiplex_profiles') is True,'one_native_multiplexer_required')
    require(cfg.get('unauthorized_dm_behavior')=='ignore','native_unauthorized_prefilter_must_ignore')
    require('qyp_guard' in gateway.get('required_policies',[]),'mandatory_startup_policy_required')
    require(settings.get('admission_control') and settings.get('admin_home'),'native_admin_contract_required')
    reads=settings.get('reviewed_read_tools',{})
    require(isinstance(reads,dict) and all(reviewed_read(n,e) for n,e in reads.items()),'invalid_reviewed_read_table')
    verify_required_read_tools(settings,reads)
    mutations=settings.get('reviewed_mutation_tools',{})
    require(isinstance(mutations,dict) and all(reviewed_mutation(n,e) for n,e in mutations.items()),'invalid_reviewed_mutation_table')
    traces=settings.get('reviewed_trace_tools',{})
    require(isinstance(traces,dict),'invalid_trace_tools')
    require(all(n not in ('browser_exec','browser_cdp','terminal','computer_use') and
                e=={'kind':'trace_dom_read','broker':'trusted_trace_broker','background_only':True}
                for n,e in traces.items()),'trace_requires_background_only_read_broker')
    from . import TOOLS
    allowed_names=(cfg.get('agent') or {}).get('allowed_tools')
    require(isinstance(allowed_names,list),'native_exact_tool_ceiling_required')
    permitted=TOOLS|LOCAL|HONCHO|set(reads)|set(traces)|set(mutations)
    require(TOOLS|LOCAL<=set(allowed_names) and set(allowed_names)<=permitted,'native_tool_ceiling_not_exact')
    require(((cfg.get('tools') or {}).get('tool_search') or {}).get('enabled') in ('off',False),'deferred_tool_management_forbidden')
    servers=cfg.get('mcp_servers',{})
    require(isinstance(servers,dict),'invalid_mcp_servers')
    for name,server in servers.items():
        require(name in READ_METHODS and isinstance(server,dict),'unreviewed_or_telegram_mcp_forbidden')
        if name=='atlas_read':
            import hashlib
            pin=(settings.get('reviewed_stdio_servers') or {}).get(name) or {}
            args=server.get('args',[])
            require(server.get('command')==pin.get('command') and args==pin.get('args') and len(args)>=3 and args[:2]==['-I','-B'],'fixed_reviewed_stdio_required')
            require(server.get('env',{})=={} and (server.get('sampling') or {}).get('enabled') is False,'stdio_env_and_sampling_forbidden')
            require(Path(args[2]).is_absolute() and hashlib.sha256(Path(args[2]).read_bytes()).hexdigest()==pin.get('source_sha256'),'reviewed_sidecar_source_hash_mismatch')
            typed=settings.get('typed_work_read')
            if typed is None:
                verify_read_bundle(Path(args[2]),settings)
            else:
                from atlas_work_read.bundle import Bundle
                require(type(typed)is dict and set(typed)=={'bundle_root','bundle_pins'},'closed_typed_read_bundle_required')
                require(typed['bundle_pins']==settings.get('reviewed_service_files'),'identical_eleven_file_read_pins_required')
                Bundle(typed['bundle_root'],typed['bundle_pins'])
                verify_read_bundle(Path(typed['bundle_root'])/'sidecar.py',settings)
            from .policy import _approved_service_input
            from types import SimpleNamespace
            require(_approved_service_input(SimpleNamespace(get_config=lambda key,default=None:settings.get(key,default)),'service_catalog',{}),'closed_service_manifest_required')
            require((server.get('tools') or {}).get('resources') is False and (server.get('tools') or {}).get('prompts') is False,'stdio_utility_surface_forbidden')
        else:
            require('command' not in server and 'env' not in server,'mcp_host_execution_forbidden')
            endpoint=urlsplit(server.get('url',''))
            require(endpoint.scheme=='https' and bool(endpoint.hostname) and endpoint.hostname not in ('localhost','127.0.0.1','::1') and endpoint.port!=18724,'mcp_endpoint_not_reviewed')
        include=(server.get('tools') or {}).get('include')
        require(isinstance(include,list) and bool(include) and set(include)<=READ_METHODS[name]|MUTATION_METHODS[name],'mcp_exact_methods_required')
        require(all(any(e['service']==name and e['method']==method for e in list(reads.values())+list(mutations.values())) for method in include),'mcp_method_missing_dispatch_review')
    from hermes_constants import get_hermes_home
    verify_profile_stdio(cfg,Path(profile_home) if profile_home is not None else get_hermes_home())
    platforms=cfg.get('platform_toolsets') or {}
    require(isinstance(platforms,dict) and 'telegram' in platforms,'explicit_telegram_toolsets_required')
    allowed=BASE_TOOLSETS|{'mcp-'+s for s in servers}|set(settings.get('reviewed_toolsets',[]))
    # reviewed_toolsets is only for narrow native trace/integration wrappers; their
    # discovered TOOL NAMES still must pass the exact dispatcher ceiling below.
    for names in platforms.values():
        require(isinstance(names,list) and set(names)<=allowed,'host_or_deferred_toolset_forbidden')
    require(BASE_TOOLSETS<=set(platforms['telegram']),'native_memory_skills_sandbox_required')
    require(not cfg.get('quick_commands'),'host_quick_commands_forbidden')
    require(not cfg.get('mcp',{}).get('servers'),'legacy_mcp_forbidden')
    return settings


def verify_service(service,*,probe_backend=True):
    # Integration code is not authorization to activate this distribution.
    # A parent-issued exact-source qualification is scoped to owned synthetic
    # fixtures; it does not modify or substitute the production activation policy.
    if service.ctx.get_config('qualification_permit') is not None:
        from atlas_native_bridge.qualification import verify_fixture_service
        return verify_fixture_service(service)
    import json
    control=Path(service.ctx.get_config('admission_control'))
    policy_path=control/'authorization-policy.json'
    try:
        if policy_path.is_symlink():raise ValueError('symlink')
        authorization=json.loads(policy_path.read_text())
    except Exception:raise PermissionError('parent_verified_staff_tasha_authorization_required') from None
    if authorization.get('activation_permitted') is not True or authorization.get('state')!='parent_verified_provider_integrated':
        raise PermissionError('parent_verified_staff_tasha_authorization_required')
    from hermes_cli.config import load_config_readonly
    cfg=load_config_readonly() or {}
    settings=verify_config(cfg)
    from gateway.platforms.base import BasePlatformAdapter
    from gateway.session import SessionSource
    from plugins.platforms.telegram.update_admission import TelegramApplication
    if (not hasattr(BasePlatformAdapter,'_handle_admitted_message') or
            '_atlas_binding' not in SessionSource.__dataclass_fields__ or
            not hasattr(TelegramApplication,'_process_admitted_update')):
        raise PermissionError('native_admission_core_patch_required')
    if any(key in os.environ for key in _IDENTITY):raise PermissionError('ambient_identity_forbidden')
    if settings.get('required_read_tools'):
        # Native startup policy runs before the gateway's ordinary MCP stage.
        # Discover the reviewed local stdio server before requiring its names.
        from tools.mcp_tool_discovery import discover_mcp_tools
        discover_mcp_tools(allowed_mcp_names=['atlas_read'])
    from model_tools import get_tool_definitions
    definitions=get_tool_definitions(enabled_toolsets=cfg['platform_toolsets']['telegram'],quiet_mode=True)
    names={d['function']['name'] for d in definitions}
    verify_required_read_tools(settings,names)
    from . import TOOLS
    allowed=TOOLS|LOCAL|HONCHO|set(settings.get('reviewed_read_tools',{}))|set(settings.get('reviewed_trace_tools',{}))|set(settings.get('reviewed_mutation_tools',{}))
    if not TOOLS<=names or not names<=allowed:raise PermissionError('native_tool_surface_outside_ceiling:'+','.join(sorted(names-allowed)))
    from .admin import load_json
    control=Path(settings['admission_control'])
    admission=load_json(control/'admissions.json',None)
    template=load_json(control/'profile-template.json',None)
    if not isinstance(admission,dict) or not isinstance(template,dict):raise PermissionError('admin_files_required')
    verify_config(template,profile_home=Path(settings['admin_home']).parent/'control/template-stdio')
    if probe_backend:
        who=Principal(OWNER,'atlas-startup-selfcheck','owner')
        result=service.broker.execute(who,'python',"print('ATLAS_SANDBOX_READY')",timeout=10)
        if result.get('exit')!=0 or result.get('stdout','').strip()!='ATLAS_SANDBOX_READY' or result.get('container_removed') is not True:raise PermissionError('sandbox_selfcheck_failed')
    return {'policy':'qyp_guard','ready':True,'tools':sorted(names),'background_trace_only':True,'telegram_mcp':False}
