#!/usr/bin/env python3
"""Trusted fixed-argv native profile helper. No secret reads/copies or services."""
import json
import os
import shutil
import hashlib
from pathlib import Path
import sys

A=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(A/'runtime'))


def pin_profile_stdio(config,profile_home):
    """Trusted provisioner binds native adoption identity, not a model user_id.

    The exact resolved private profile directory must exist before launching.
    No generic host cwd selection is exposed to the assistant.
    """
    path=Path(profile_home)
    if path.is_symlink() or not path.is_absolute() or not path.is_dir():
        raise PermissionError('native_profile_cwd_required')
    path=path.resolve()
    server=(config.get('mcp_servers') or {}).get('atlas_read')
    if server is None:return
    pin=config['plugins']['entries']['qyp_guard']['settings']['reviewed_stdio_servers']['atlas_read']
    server['cwd']=str(path);pin['cwd']=str(path)


def _reused_config_equal(actual,expected):
    """Ignore only native one-time hint receipts; never behavioral settings."""
    if actual==expected:return True
    allowed={'busy_input_prompt','tool_progress_prompt','openclaw_residue_cleanup','profile_build_offered'}
    def without_seen(config):
        if not isinstance(config,dict):return None
        result=dict(config)
        if 'onboarding' not in result:return result
        section=result['onboarding']
        if not isinstance(section,dict):return None
        section=dict(section)
        if 'seen' in section:
            seen=section['seen']
            if (not isinstance(seen,dict) or set(seen)-allowed
                    or any(type(value)is not bool for value in seen.values())):return None
            section.pop('seen')
        if section:result['onboarding']=section
        else:result.pop('onboarding')
        return result
    left=without_seen(actual);right=without_seen(expected)
    return left is not None and right is not None and left==right


def provision(home, uid, template, honcho_template=None):
    template=json.loads(json.dumps(template))
    role_policy=template.pop('_atlas_role_policy_soul',None)
    if role_policy is not None and (not isinstance(role_policy,str) or not role_policy.strip() or '\x00' in role_policy or len(role_policy.encode())>16384):
        raise PermissionError('approved_role_policy_required')
    approval=home.parent/'control/instruction-policy-approval.json'
    if approval.is_symlink() or not approval.is_file():raise PermissionError('explicit_instruction_policy_consent_required')
    consent=json.loads(approval.read_text())
    if (consent.get('approved') is not True or consent.get('scope')!='native-home-initialization'
            or not consent.get('provenance') or role_policy is None
            or hashlib.sha256(role_policy.encode()).hexdigest()!=consent.get('sha256')):
        raise PermissionError('approved_role_policy_consent_required')
    from hermes_cli.profiles import create_profile, get_profile_dir
    from hermes_cli.config import atomic_config_replace
    import re
    group_profile=bool(re.fullmatch(r'tg-group-n[1-9][0-9]{0,19}-t(?:0|[1-9][0-9]{0,19})',uid))
    if not group_profile and not re.fullmatch(r'[1-9][0-9]{0,19}',uid):raise PermissionError('canonical_profile_selector_required')
    name=uid if group_profile else 'tg-'+uid
    path=get_profile_dir(name)
    if path != home/'profiles'/name:
        raise RuntimeError('native_profile_root_mismatch')
    if path.is_symlink():raise PermissionError('profile_symlink_forbidden')
    created=not path.exists()
    template['unauthorized_dm_behavior']='ignore'
    telegram=template.setdefault('telegram',{})
    telegram.update(enabled=False,dm_policy='open',allow_from=['*'],group_policy='open',group_allow_from=['*'])
    telegram.setdefault('extra',{})['atlas_admission']=True
    if isinstance(template.get('platforms'),dict) and 'telegram' in template['platforms']:
        template['platforms']['telegram'].update(enabled=False)
    settings=template['plugins']['entries']['qyp_guard']['settings']
    facade=None
    if settings.get('typed_work_read') is not None:
        # The installed distribution supplier is trusted source, not a configured
        # import-string callback. Its output is the existing closed facade schema.
        sys.path.insert(0,str(home.parent/'distribution'))
        from atlas_dist.unified_candidate import profile_facade_bindings
        template,facade=profile_facade_bindings(template,home.parent,path)
    else:
        # Preserve the earlier reviewed sidecar configuration contract.
        server=(template.get('mcp_servers') or {}).get('atlas_read')
        if server is not None:
            pin=settings['reviewed_stdio_servers']['atlas_read']
            server['cwd']=str(path);pin['cwd']=str(path)
    honcho=None
    if honcho_template is not None:
        def reject_secrets(value):
            if isinstance(value,dict):
                for key,child in value.items():
                    if key.lower().replace('_','').replace('-','') in {'token','accesstoken','refreshtoken','secret','apikey','password','authorization','credentials','auth','headers'}:
                        raise PermissionError('honcho_template_must_not_contain_credentials')
                    reject_secrets(child)
            elif isinstance(value,list):
                for child in value:reject_secrets(child)
        reject_secrets(honcho_template)
        peer=name
        identity={'aiPeer':'atlas-'+name,'peerName':peer,'pinUserPeer':False,'pinPeerName':False,'userPeerAliases':{uid:peer},'runtimePeerPrefix':'tg-'}
        if group_profile:
            identity={'aiPeer':'atlas-'+name,'peerName':name,'pinUserPeer':True,'pinPeerName':True,'userPeerAliases':{},'runtimePeerPrefix':name+'-'}
        honcho=json.loads(json.dumps(honcho_template));honcho.update(identity)
        for block in (honcho.get('hosts') or {}).values():
            if isinstance(block,dict):block.update(identity)
    # Never persist the initial snapshot: merge fresh consent under its existing
    # interprocess boundary. This is consent, not profile publication or registry.
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from instruction_consent import authorize_home
    authorize_home(home,path,role_policy,created=created)

    def initialize(stage,final):
        if final!=path:raise RuntimeError('native_initializer_home_mismatch')
        atomic_config_replace(stage/'config.yaml',template)
        if facade is not None:
            fd=os.open(stage/'atlas-read-facade.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump(facade,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        memory=stage/'memories';memory.mkdir(exist_ok=True)
        for filename in ('MEMORY.md','USER.md'):
            target=memory/filename
            if not target.exists():target.write_text('')
        for folder in ('plugins','skills'):
            target=stage/folder;source=home/folder
            if target.exists() and not target.is_symlink():
                if folder=='skills':shutil.rmtree(target)
                elif any(target.iterdir()):raise PermissionError('nonempty_profile_code_directory')
                else:target.rmdir()
            if not target.is_symlink() and source.is_dir():target.symlink_to(source,target_is_directory=True)
        if (stage/'auth.json').exists() or (stage/'auth.json').is_symlink():raise PermissionError('profile_credentials_forbidden')
        if honcho is not None:
            fd=os.open(stage/'honcho.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump(honcho,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        if (stage/'SOUL.md').read_bytes()!=role_policy.encode():raise PermissionError('approved_role_policy_required')

    if created:
        path=create_profile(name,no_skills=True,no_alias=True,soul=role_policy,_pre_publish_initializer=initialize)
    else:
        # Reuse is read-only. Do not repair an occupied or foreign profile in
        # place while the multiplexer may already be serving it.
        from hermes_cli.config import read_user_config_raw
        if (path/'config.yaml').is_symlink() or not _reused_config_equal(read_user_config_raw(path/'config.yaml'),template):
            raise PermissionError('existing_profile_config_conflict')
        if facade is not None:
            target=path/'atlas-read-facade.json'
            if target.is_symlink() or not target.is_file() or json.loads(target.read_text())!=facade:
                raise PermissionError('existing_profile_facade_conflict')
        if ((path/'SOUL.md').is_symlink() or (path/'SOUL.md').read_bytes()!=role_policy.encode()
                or (path/'auth.json').exists() or (path/'auth.json').is_symlink()
                or any((path/'memories'/n).is_symlink() or not (path/'memories'/n).is_file() for n in ('MEMORY.md','USER.md'))):
            raise PermissionError('existing_private_profile_conflict')
        if honcho is not None:
            target=path/'honcho.json'
            if target.is_symlink() or not target.is_file() or json.loads(target.read_text())!=honcho:
                raise PermissionError('existing_profile_memory_identity_conflict')
    return {'profile':name,'home':str(path),'native_profile':True,'memory_files':['memories/MEMORY.md','memories/USER.md'],
            'role_policy_installed':created and role_policy is not None,
            'role_policy_sha256':hashlib.sha256(role_policy.encode()).hexdigest() if role_policy is not None else None}

if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit('usage: native_profile_helper HOME USER_ID TEMPLATE')
    home=Path(sys.argv[1]);uid=sys.argv[2]
    import re
    if not re.fullmatch(r'(?:[1-9][0-9]{0,19}|tg-group-n[1-9][0-9]{0,19}-t(?:0|[1-9][0-9]{0,19}))',uid):raise SystemExit('invalid_id')
    if os.environ.get('HERMES_HOME')!=str(home):raise SystemExit('home_mismatch')
    template=Path(sys.argv[3]);honcho=template.with_name('honcho-profile-template.json')
    policy=template.with_name('SOUL.md')
    if not policy.is_file() or policy.is_symlink() or policy.stat().st_size>16384:
        raise SystemExit('approved_common_role_policy_missing')
    carrier=json.loads(template.read_text())
    carrier['_atlas_role_policy_soul']=policy.read_text()
    print(json.dumps(provision(home,uid,carrier,json.loads(honcho.read_text()) if honcho.exists() else None)))
