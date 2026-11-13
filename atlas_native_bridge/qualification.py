"""Parent-issued fixture-only readiness. Production activation remains separate.

This opt-in checks exact source/config/home policy, never changes authorization-
policy.json or grants Telegram/user authority. All native admission/source/tool
and output guards still run. Merely setting a JSON flag cannot satisfy it.
"""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from .protocol import Denied


def verify_fixture_service(service):
    permit_path=Path(service.ctx.get_config('qualification_permit'))
    expected=service.ctx.get_config('qualification_permit_sha256')
    if permit_path.is_symlink() or not permit_path.is_file() or permit_path.stat().st_mode&0o077:raise Denied('private_parent_fixture_permit_required')
    data=permit_path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected:raise Denied('parent_fixture_permit_hash_mismatch')
    permit=json.loads(data)
    if permit.get('schema')==2:
        from .expanded_qualification import verify_service
        return verify_service(service)
    if (set(permit)!={'schema','issuer','scope','source_manifest_sha256','owned_root','homes','policy_sha256','config_sha256','approved'}
            or permit['schema']!=1 or permit['issuer']!='parent_agent_explicit_qualification'
            or permit['scope']!='synthetic-native-model-SDK-fixture-only' or permit['approved'] is not True):raise Denied('parent_fixture_permit_required')
    root=Path(permit['owned_root']).resolve(strict=True)
    from hermes_constants import get_hermes_home
    home=get_hermes_home().resolve(strict=True)
    if str(home) not in permit['homes'] or not home.is_relative_to(root):raise Denied('fixture_home_not_approved')
    if hashlib.sha256((home/'SOUL.md').read_bytes()).hexdigest()!=permit['policy_sha256']:raise Denied('fixture_policy_mismatch')
    # Manifest itself is frozen outside the mutable fixture home and config hash
    # excludes only the parent-issued permit location/pin (no model-controlled data).
    manifest=permit_path.parent/'fixture-source-manifest.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=permit['source_manifest_sha256']:raise Denied('fixture_source_manifest_mismatch')
    pins=json.loads(manifest.read_text())
    for path,pin in pins.items():
        p=Path(path)
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=pin:raise Denied('fixture_source_changed')
    from hermes_cli.config import load_config_readonly,read_user_config_raw
    cfg=load_config_readonly() or {};copy=json.loads(json.dumps(read_user_config_raw(home/'config.yaml') or {}));settings=copy['plugins']['entries']['qyp_guard']['settings']
    settings.pop('qualification_permit',None);settings.pop('qualification_permit_sha256',None)
    copy['model']['base_url']='http://127.0.0.1:<fixture-port>/v1'
    canonical=json.dumps(copy,sort_keys=True,separators=(',',':')).encode()
    if hashlib.sha256(canonical).hexdigest()!=permit['config_sha256']:raise Denied('fixture_config_mismatch')
    model=cfg['model'];u=urlsplit(model['base_url'])
    if model.get('provider')!='custom' or u.hostname!='127.0.0.1' or u.scheme!='http' or cfg.get('mcp_servers'):raise Denied('local_synthetic_fixture_only')
    if cfg['agent']['allowed_tools']!=['qyp_role'] or service.ctx.get_config('sandbox_backend')!='disabled':raise Denied('fixture_role_only_no_execution')
    from gateway.atlas_admission import installed_gate
    from .remote import RemoteAdmissionGate
    if not isinstance(installed_gate(),RemoteAdmissionGate):raise Denied('native_remote_gate_required')
    if 'qyp_guard' not in cfg['gateway']['required_policies']:raise Denied('mandatory_policy_missing')
    if any(k in os.environ for k in ('HERMES_SESSION_PLATFORM','HERMES_SESSION_USER_ID','HERMES_SESSION_KEY','HERMES_SESSION_CHAT_TYPE')):raise Denied('ambient_identity_forbidden')
    return {'policy':'qyp_guard','ready':True,'qualification':'source_fixture_only','production_activation':False}
