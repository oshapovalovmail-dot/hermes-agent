"""Owner-only profile admin. Admission is last on add, first on revoke."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from .broker import OWNER, _directory

HELPER=Path(__file__).resolve().parents[3]/'services/atlas-admin/native_profile_helper.py'


def canonical_id(uid):
    if not isinstance(uid,str) or not re.fullmatch(r'[1-9][0-9]{0,19}',uid):raise ValueError('canonical_id_required')
    return uid


def load_json(path, default):
    if not path.exists():return default
    if path.is_symlink():raise PermissionError('control_symlink_forbidden')
    return json.loads(path.read_text())


def save_json(path,data):
    temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()


@contextmanager
def control_lock(root):
    fd=_directory(root);os.close(fd)
    fd=os.open(root/'admin.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:os.close(fd)


class AccessAdmin:
    def __init__(self,home,control,*,helper=None):
        self.home=Path(home);self.control=Path(control)
        self.helper=Path(helper) if helper is not None else HELPER
        fd=_directory(self.control);os.close(fd)

    def apply(self,actor,action,uid):
        if actor!=OWNER:raise PermissionError('owner_required')
        canonical_id(uid)
        if uid==OWNER:raise PermissionError('owner_profile_is_operator_managed')
        if action not in ('add','revoke'):raise ValueError('add_or_revoke_required')
        with control_lock(self.control):
            admission=load_json(self.control/'admissions.json',{'admitted':[]})
            admitted=set(admission['admitted'])
            pending=admission.get('pending',{})
            if action=='revoke':
                admitted.discard(uid)
                pending.pop(uid,None)
                save_json(self.control/'admissions.json',{'admitted':sorted(admitted),'pending':pending})
                self._route(uid,remove=True)
                self._transport_admission(admitted)
                return {'profile':'tg-'+uid,'admitted':False,'memory_preserved':True}
            if len(admitted|set(pending))>=16 and uid not in admitted and uid not in pending:raise PermissionError('principal_limit')
            template_path=self.control/'profile-template.json'
            template=load_json(template_path,None)
            if not isinstance(template,dict):raise PermissionError('operator_profile_template_required')
            # No automatic credentials inheritance by file copy or symlink.
            env={'PATH':'/usr/bin:/bin','HOME':os.environ.get('HOME','/nonexistent'),
                 'HERMES_HOME':str(self.home),'HERMES_RUNTIME_DIR':str(Path(__file__).resolve().parents[3]/'tools'),
                 'TMPDIR':os.environ.get('TMPDIR',str(self.control)), 'PYTHONDONTWRITEBYTECODE':'1'}
            result=subprocess.run([sys.executable,str(self.helper),str(self.home),uid,str(template_path)],env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=60)
            if result.returncode:raise RuntimeError('native_profile_provision_failed:'+result.stderr[-1000:])
            receipt=json.loads(result.stdout.splitlines()[-1])
            if receipt.get('home')!=str(self.home/'profiles'/('tg-'+uid)):raise PermissionError('native_home_mismatch')
            self._route(uid)
            pending[uid]=uuid.uuid4().hex
            save_json(self.control/'admissions.json',{'admitted':sorted(admitted),'pending':pending})
            return receipt|{'admitted':uid in admitted,'activation_required':True,'generation':pending[uid]}

    def _route(self,uid,remove=False):
        from hermes_cli.config import atomic_config_replace, read_user_config_raw
        cfg=read_user_config_raw(self.home/'config.yaml') or {}
        gateway=cfg.setdefault('gateway',{})
        routes=gateway.get('profile_routes',[])
        routes=[r for r in routes if r.get('name')!='atlas-tg-'+uid]
        if not remove:routes.append({'name':'atlas-tg-'+uid,'platform':'telegram','user_id':uid,'chat_id':uid,'profile':'tg-'+uid})
        gateway['profile_routes']=routes
        atomic_config_replace(self.home/'config.yaml',cfg)

    def activate(self,uid,receipt,*,generation=None):
        canonical_id(uid)
        expected='tg-'+uid
        if expected not in receipt.get('served_profiles',[]):raise PermissionError('native_profile_not_served')
        routes=receipt.get('routes',[])
        if not any(r.get('platform')=='telegram' and r.get('user_id')==uid and r.get('profile')==expected for r in routes):raise PermissionError('native_exact_route_missing')
        with control_lock(self.control):
            data=load_json(self.control/'admissions.json',{'admitted':[]})
            pending=data.get('pending',{})
            if uid not in pending or (generation is not None and pending[uid]!=generation):
                raise PermissionError('stale_or_revoked_admission')
            pending.pop(uid)
            data['admitted']=sorted(set(data['admitted'])|{uid})
            save_json(self.control/'admissions.json',data)
            self._transport_admission(set(data['admitted']))
        return {'profile':expected,'admitted':True}

    def _transport_admission(self,admitted):
        from hermes_cli.config import atomic_config_replace,read_user_config_raw
        cfg=read_user_config_raw(self.home/'config.yaml') or {}
        ids=sorted(set(admitted)|{OWNER})
        cfg['unauthorized_dm_behavior']='ignore'
        blocks=[cfg.setdefault('telegram',{})]
        for parent in (cfg.get('platforms'),(cfg.get('gateway') or {}).get('platforms')):
            if isinstance(parent,dict) and isinstance(parent.get('telegram'),dict):blocks.append(parent['telegram'])
        for block in blocks:
            block.update(dm_policy='allowlist',allow_from=ids,group_policy='disabled',group_allow_from=[],unauthorized_dm_behavior='ignore')
            if isinstance(block.get('extra'),dict):block['extra'].update(allow_from=ids,dm_policy='allowlist',group_policy='disabled',group_allow_from=[])
        atomic_config_replace(self.home/'config.yaml',cfg)
