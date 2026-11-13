"""Pure source supplier, never writes operator homes or reads credentials."""
from copy import deepcopy
from pathlib import Path
import re
from .qyp_candidate import build_profiles as base_profiles
from .bundle import READ_FILES
PUBLIC_READ_TOOLS=['integration_status','wiki_read','tracker_read','pr_read','trace_read','nirvana_read','yt_read','datalens_read','service_catalog','service_read']

def build_profiles(root,owner,pins,*,python,bridge,facade_sha256,served_profiles=()):
    root=Path(root)
    if (type(bridge)is not dict or set(bridge)!={'enabled','key_file','epoch','gateway_id'} or bridge['enabled'] is not True
        or not all(type(bridge[k])is str and bridge[k] for k in ('key_file','epoch','gateway_id'))
        or not Path(bridge['key_file']).is_relative_to(root/'control') or '..' in Path(bridge['key_file']).parts
        or type(facade_sha256)is not str or re.fullmatch('[0-9a-f]{64}',facade_sha256)is None
        or not re.fullmatch('[1-9][0-9]{0,19}',owner)):
        raise ValueError('explicit_operator_unified_bindings_required')
    result=base_profiles(root,owner,pins,python=python)
    homes={'root':root/'home','profile':root/'home/profiles'/('tg-'+owner),'template':root/'control/template-stdio'}
    if len(set(served_profiles))!=len(served_profiles):raise ValueError('duplicate_profile')
    for profile in served_profiles:
        if not isinstance(profile,str) or not re.fullmatch(r'tg-(?:[1-9][0-9]{0,19}|group-n[1-9][0-9]{0,19}-t(?:0|[1-9][0-9]{0,19}))',profile) or profile=='tg-'+owner:
            raise ValueError('canonical_private_profile_required')
        result[profile]=deepcopy(result['profile']);homes[profile]=root/'home/profiles'/profile
    for role,cfg in result.items():
        home=homes[role];settings=cfg['plugins']['entries']['qyp_guard']['settings']
        settings.update(bridge=deepcopy(bridge),bridge_memory={'enabled':True},typed_work_read={'bundle_root':str(root/'services/atlas-read'),'bundle_pins':dict(pins)})
        server=cfg['mcp_servers']['atlas_read']
        server.update(command=python,args=['-I','-B',str(root/'runtime/atlas_work_read/facade_entry.py'),'--config',str(home/'atlas-read-facade.json')],cwd=str(home))
        server['tools']['include']=list(PUBLIC_READ_TOOLS)
        settings['reviewed_stdio_servers']['atlas_read']={k:deepcopy(server[k]) for k in ('command','args','cwd')}
        settings['reviewed_stdio_servers']['atlas_read']['source_sha256']=facade_sha256
        cfg['memory']={'provider':'atlas_bridge_memory'}
        cfg['thread_sessions_per_user']=True
    return result

def application_plan(root,mac_root,*,qyp_python,mac_python,bundle_pins,honcho):
    """Explicit paths/config only. Actual owner peer labels must be supplied by
    the operator from Atlas's non-secret config; never infer/import histories.
    The trace proposal remains absent from the active Mac work_read map.
    """
    root=Path(root);mac_root=Path(mac_root)
    for base,python in ((root,qyp_python),(mac_root,mac_python)):
        if not base.is_absolute() or '..' in base.parts or not Path(python).is_relative_to(base/'home/installs') or '..' in Path(python).parts or not python.endswith('/bin/python'):raise ValueError('exact_native_home_and_PM_python_required')
    if set(bundle_pins)!=set(READ_FILES) or any(not re.fullmatch('[0-9a-f]{64}',v) for v in bundle_pins.values()):raise ValueError('exact_bundle11_required')
    if (type(honcho)is not dict or set(honcho)-{'workspace_id','mapping','api_key_file'} or not isinstance(honcho.get('workspace_id'),str) or not honcho['workspace_id'] or type(honcho.get('mapping'))is not dict or set(honcho['mapping'])!={'owner_user_peer','owner_assistant_peer','namespace'} or any(type(v)is not str or not v or len(v)>256 for v in honcho['mapping'].values())):raise ValueError('explicit_existing_Atlas_owner_mapping_required')
    common={'enabled':True,'key_file':str(root/'control/application.key'),'epoch':'OPERATOR_MUST_SUPPLY_DEPLOYMENT_EPOCH','gateway_id':'atlas','port':18770}
    qyp_hub={**common,'role':'qyp','root':str(root/'control/bridge'),'work_read':{'enabled':True}}
    mac_bridge={**common,'key_file':str(mac_root/'control/application.key'),'role':'mac','root':str(mac_root/'control/bridge'),'ssh_host':'qyp-dev','remote_python':qyp_python,'remote_entry':str(root/'runtime/atlas_native_bridge/hub_entry.py'),'remote_config':str(root/'control/bridge.json'),'bot_token_file':str(mac_root/'control/bot-token'),'staff_admin_home':str(mac_root/'home'),'staff_reviewed_service_files':dict(bundle_pins),'thread_sessions_per_user':True,'honcho':deepcopy(honcho),'work_read':{'bundle_root':str(mac_root/'services/atlas-read'),'bundle_pins':dict(bundle_pins),'python':mac_python,'worker_root':str(mac_root/'control/private-read-workers')}}
    def env(base):return {'PATH':'/usr/bin:/bin','HOME':str(base/'home'),'HERMES_HOME':str(base/'home'),'HERMES_RUNTIME_DIR':str(base/'tools')}
    return {'qyp_hub':qyp_hub,'mac_bridge':mac_bridge,'qyp_launcher':{'argv':[str(root/'bin/hermes'),'gateway','run'],'env':env(root)},'mac_launcher':{'argv':[mac_python,'-I','-B',str(mac_root/'runtime/atlas_native_bridge/edge_entry.py'),'--config',str(mac_root/'control/bridge.json')],'env':env(mac_root)},'mac_only_trace_selection_proposal':{'mode':'background_owned','endpoint':'http://127.0.0.1:9222'},'activation':False,'operator_epoch_required':True}


def profile_facade_bindings(config,root,profile_home):
    """Bind only the known unified template fields; never rewrite arbitrary text.

    Returned config and closed JSON use the FINAL semantic home even when the
    trusted native initializer writes them into an unpublished staging tree.
    """
    import hashlib
    root=Path(root);home=Path(profile_home);template=root/'control/template-stdio'
    if (not root.is_absolute() or '..' in root.parts or home.parent!=root/'home/profiles'
            or not re.fullmatch(r'tg-(?:[1-9][0-9]{0,19}|group-n[1-9][0-9]{0,19}-t(?:0|[1-9][0-9]{0,19}))',home.name)):
        raise ValueError('canonical_private_profile_required')
    cfg=deepcopy(config);settings=cfg['plugins']['entries']['qyp_guard']['settings']
    typed=settings['typed_work_read'];bridge=settings['bridge'];server=cfg['mcp_servers']['atlas_read']
    pin=settings['reviewed_stdio_servers']['atlas_read'];entry=root/'runtime/atlas_work_read/facade_entry.py'
    expected=['-I','-B',str(entry),'--config',str(template/'atlas-read-facade.json')]
    if (type(typed)is not dict or set(typed)!={'bundle_root','bundle_pins'}
            or typed['bundle_root']!=str(root/'services/atlas-read')
            or set(typed['bundle_pins'])!=set(READ_FILES)
            or typed['bundle_pins']!=settings['reviewed_service_files']
            or any(not isinstance(v,str) or re.fullmatch('[0-9a-f]{64}',v)is None for v in typed['bundle_pins'].values())
            or server.get('args')!=expected or server.get('cwd')!=str(template)
            or any(server.get(k)!=pin.get(k) for k in ('command','args','cwd'))
            or hashlib.sha256(entry.read_bytes()).hexdigest()!=pin.get('source_sha256')
            or type(bridge)is not dict or set(bridge)!={'enabled','key_file','epoch','gateway_id'}
            or bridge.get('enabled') is not True
            or not all(isinstance(bridge[k],str) and bridge[k] for k in ('key_file','epoch','gateway_id'))
            or not Path(bridge['key_file']).is_relative_to(root/'control') or '..' in Path(bridge['key_file']).parts):
        raise ValueError('exact_unified_facade_template_required')
    server['args']=['-I','-B',str(entry),'--config',str(home/'atlas-read-facade.json')]
    server['cwd']=str(home)
    for key in ('command','args','cwd'):pin[key]=deepcopy(server[key])
    return cfg,facade_config(root,home,typed['bundle_pins'],bridge)


def facade_config(root,home,pins,bridge):
    root=Path(root);home=Path(home)
    if home!=root/'home' and home!=root/'control/template-stdio' and not home.is_relative_to(root/'home/profiles'):raise ValueError('owned_private_home_required')
    return {'bundle_root':str(root/'services/atlas-read'),'bundle_pins':dict(pins),'profile_home':str(home),'key_file':bridge['key_file'],'epoch':bridge['epoch'],'hub_socket':str(root/'control/bridge/work-read.sock')}
