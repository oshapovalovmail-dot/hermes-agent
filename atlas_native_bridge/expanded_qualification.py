"""PROPOSED expanded verifier. Only an exact NEW parent permit can enable it.

Synthetic source policy is not production activation or an identity grant. Every
native source, turn generation, ACL, cancellation and SDK output guard remains.
"""
import hashlib,json,os,re
from pathlib import Path
from urllib.parse import urlsplit
from .protocol import Denied
IMAGE='sha256:5bd7249518e6776ce415a55c6a043e8773526569fa9fa2053d012a80c7c7f27a'
PUBLIC_READ_TOOLS=['integration_status','wiki_read','tracker_read','pr_read','trace_read','nirvana_read','yt_read','datalens_read','service_catalog','service_read']
ALLOWED_TOOLS=['qyp_role','qyp_code_read','qyp_exec','qyp_export',*['mcp__atlas_read__'+n for n in PUBLIC_READ_TOOLS]]
POLICY='244e6cb783242c9c6e24b04d3279000681c510e521954eeb14fbab34b2c53d57'
SCOPE='synthetic-expanded-native-model-SDK-Podman-read-fixture-only'
QUALIFICATION_ROOT=Path('/home/ovshapovalov/.local/share/hermes-atlas/qualification/native-final')
REUSED_PM_PYTHON='/home/ovshapovalov/.local/share/hermes-atlas/qualification/unified-native/home/installs/1e899db50145c308/environments/offline-native-telegram-mcp-v2/venv/bin/python'
RESOURCES={'memory_bytes':536870912,'cpus':1,'pids':32,'logical_uid_bytes':2147483648,'physical_transit_uid_bytes':2147483648,'export_bytes':2147483648,'script_seconds':86400,'outer_seconds':86520,'gateway_seconds':86580}

def contract(root,source,python):
    return {'source_root':str(source),'python':python,'code_root':str(root/'code-source'),'allowed_tools':list(ALLOWED_TOOLS),'resources':dict(RESOURCES),'engine':{'binary':'/usr/bin/podman','image':IMAGE,'network':'none','readonly_rootfs':True},'endpoints':{'model':'http://127.0.0.1:<fixture-port>/v1','staff':'in-process:StaffHTTPMock','sdk':'in-process:GuardedPTBMock','honcho':'in-process:HonchoReadMock'},'trace':'DENY_UNTIL_SEPARATELY_REVIEWED_SELECTED_READER'}

def validate_contract(cfg,c,root,home):
    def need(v,code):
        if not v:raise Denied(code)
    root=Path(root);home=Path(home)
    need(root==QUALIFICATION_ROOT/'fixture','exact_owned_expanded_root_required')
    source=root.parent/'source/candidate';python=c.get('python')
    need(python==REUSED_PM_PYTHON,'own_PM_python_required')
    need(c==contract(root,source,python),'closed_expanded_fixture_contract_required')
    need(home==root/'home' or home.is_relative_to(root/'home/profiles'),'exact_fixture_profile_required')
    model=cfg.get('model',{});u=urlsplit(model.get('base_url',''))
    need(model.get('provider')=='custom' and model.get('default')=='fake-model' and model.get('api_key')=='fixture-not-a-credential' and u.scheme=='http' and u.hostname=='127.0.0.1' and u.port is not None and not u.username and not u.password and u.path=='/v1' and not u.query and not u.fragment,'local_fake_model_only')
    need(cfg.get('agent',{}).get('allowed_tools')==ALLOWED_TOOLS and cfg['agent'].get('gateway_timeout')==86580,'exact_expanded_tool_ceiling_required')
    need(cfg.get('memory')=={'provider':'atlas_bridge_memory'},'native_memory_provider_required')
    gateway=cfg.get('gateway',{})
    need(gateway.get('required_policies')==['qyp_guard'] and gateway.get('home_channel_prompt')is False,'mandatory_fixture_policy_required')
    need(cfg.get('media_delivery')=={'required_policy':'qyp_guard'},'mandatory_fixture_media_policy_required')
    settings=cfg['plugins']['entries']['qyp_guard']['settings']
    need(settings.get('sandbox_backend')=='podman' and settings.get('podman_image')==IMAGE and settings.get('podman_metadata')==str(root/'podman-operations') and settings.get('root')==str(root/'broker') and settings.get('code_research_root')==str(root/'code-source') and settings.get('bridge_memory')=={'enabled':True},'exact_fixture_engine_input_roots_required')
    typed=settings.get('typed_work_read',{})
    need(type(typed)is dict and set(typed)=={'bundle_root','bundle_pins'} and typed['bundle_root']==str(source/'project/payload/services/atlas-read'),'exact_fixture_typed_bundle_required')
    servers=cfg.get('mcp_servers',{})
    need(set(servers)=={'atlas_read'},'only_published_atlas_read_allowed')
    server=servers['atlas_read']
    need(server.get('command')==python and server.get('args')==['-I','-B',str(source/'atlas_work_read/facade_entry.py'),'--config',str(home/'atlas-read-facade.json')] and server.get('cwd')==str(home) and server.get('env')=={} and server.get('sampling')=={'enabled':False} and server.get('tools')=={'include':PUBLIC_READ_TOOLS,'resources':False,'prompts':False},'exact_private_facade_required')
    return True

def canonical_config(cfg):
    copy=json.loads(json.dumps(cfg));settings=copy['plugins']['entries']['qyp_guard']['settings']
    settings.pop('qualification_permit',None);settings.pop('qualification_permit_sha256',None)
    copy['model']['base_url']='http://127.0.0.1:<fixture-port>/v1'
    return json.dumps(copy,sort_keys=True,separators=(',',':')).encode()

def load_context(ctx):
    path=Path(ctx.get_config('qualification_permit'));pin=ctx.get_config('qualification_permit_sha256')
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077:raise Denied('private_parent_fixture_permit_required')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=pin:raise Denied('parent_fixture_permit_hash_mismatch')
    permit=json.loads(raw)
    if (set(permit)!={'schema','issuer','scope','source_manifest_sha256','owned_root','homes','policy_sha256','config_sha256','contract','approved'} or permit.get('schema')!=2 or permit.get('issuer')!='parent_agent_explicit_qualification' or permit.get('scope')!=SCOPE or permit.get('approved')is not True or permit.get('policy_sha256')!=POLICY):raise Denied('new_expanded_parent_permit_required')
    root=Path(permit['owned_root']).resolve(strict=True)
    source=root.parent/'source/candidate'
    manifest=path.parent/'fixture-source-manifest.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=permit['source_manifest_sha256']:raise Denied('fixture_source_manifest_mismatch')
    for name,expected in json.loads(manifest.read_text()).items():
        p=Path(name)
        if not (p.is_relative_to(source) or p.is_relative_to(root)) or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise Denied('fixture_source_changed')
    from hermes_constants import get_hermes_home
    home=get_hermes_home().resolve(strict=True)
    if str(home)not in permit['homes'] or not home.is_relative_to(root):raise Denied('fixture_home_not_approved')
    if hashlib.sha256((home/'SOUL.md').read_bytes()).hexdigest()!=POLICY:raise Denied('fixture_policy_mismatch')
    from hermes_cli.config import read_user_config_raw
    cfg=read_user_config_raw(home/'config.yaml') or {}
    if hashlib.sha256(canonical_config(cfg)).hexdigest()!=permit['config_sha256'].get(str(home)):raise Denied('fixture_config_mismatch')
    validate_contract(cfg,permit['contract'],root,home)
    if os.environ.get('HERMES_RUNTIME_DIR')!='/home/ovshapovalov/.local/share/hermes-atlas/tools':raise Denied('exact_native_runtime_tools_required')
    return permit,cfg,root,home

def verify_input_root(ctx,value):
    permit,cfg,root,home=load_context(ctx)
    if value!=permit['contract']['code_root']:raise Denied('exact_private_synthetic_input_required')
    return True

def verify_service(service):
    permit,cfg,root,home=load_context(service.ctx)
    if any(k in os.environ for k in ('HERMES_PROFILE','HERMES_SESSION_PLATFORM','HERMES_SESSION_USER_ID','HERMES_SESSION_KEY','HERMES_SESSION_CHAT_TYPE')):raise Denied('ambient_identity_forbidden')
    from gateway.atlas_admission import installed_gate
    from .remote import RemoteAdmissionGate
    if not isinstance(installed_gate(),RemoteAdmissionGate):raise Denied('native_remote_gate_required')
    from atlas_work_read.bundle import Bundle
    typed=cfg['plugins']['entries']['qyp_guard']['settings']['typed_work_read'];Bundle(typed['bundle_root'],typed['bundle_pins'])
    return {'policy':'qyp_guard','ready':True,'qualification':'expanded_source_fixture_only','production_activation':False}
