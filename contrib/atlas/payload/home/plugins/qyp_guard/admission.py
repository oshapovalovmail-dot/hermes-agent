"""Trusted native admission provisioning, called only after provider proof."""
import asyncio
import json
import os
from pathlib import Path
import sys
from .staff_provider import build_staff_provider


def ensure_gate(ctx):
    from gateway.atlas_admission import installed_gate, install_gate, AdmissionGate
    current=installed_gate()
    bridge=ctx.get_config('bridge')
    if current is not None:
        if bridge is None:return current
        from atlas_native_bridge.factory import build_gate
        current=build_gate(bridge)
        if current.provision is not None:return current
    home=Path(ctx.get_config('admin_home'))
    control=Path(ctx.get_config('admission_control'))
    helper=Path(ctx.get_config('admin_helper'))
    locks={};provisioned=set()
    async def provision(binding):
        lock=locks.setdefault(binding.profile,asyncio.Lock())
        async with lock:
            if binding.profile in provisioned:return
            from .admin import load_json, control_lock
            # Helper and template are provisioner-owned paths, never model arguments.
            if not helper.is_absolute() or helper.is_symlink() or not helper.is_file():
                raise PermissionError('trusted_native_helper_required')
            template=control/'profile-template.json'
            selector=binding.profile if binding.chat_type=='group' else binding.user_id
            env={'PATH':'/usr/bin:/bin','HOME':os.environ.get('HOME','/nonexistent'),
                 'HERMES_HOME':str(home),'PYTHONDONTWRITEBYTECODE':'1',
                 'TMPDIR':os.environ.get('TMPDIR',str(control))}
            # Native PM activates dependencies in-process on a bare store Python;
            # sys.executable alone does not carry that selection into a child.
            # Resolve the committed environment, never a pinned generation or
            # ambient PYTHONPATH. Pre-PM developer interpreters retain their path.
            from pm.environments import committed_venv, project_python
            from pm.paths import repo_root
            runtime=repo_root()
            python=project_python(runtime) if committed_venv(runtime) is not None else Path(sys.executable)
            if not python.is_file():raise PermissionError('native_profile_interpreter_required')
            process=await asyncio.create_subprocess_exec(str(python),str(helper),str(home),selector,str(template),
                env=env,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            try:out,_=await asyncio.wait_for(process.communicate(),60)
            except BaseException:
                process.kill();await process.communicate();raise
            if process.returncode:raise PermissionError('native_profile_provision_failed')
            receipt=json.loads(out.decode().splitlines()[-1])
            if receipt.get('profile')!=binding.profile or receipt.get('home')!=str(home/'profiles'/binding.profile):
                raise PermissionError('native_profile_receipt_mismatch')
            def route():
                from hermes_cli.config import atomic_config_replace, read_user_config_raw
                with control_lock(control):
                    cfg=read_user_config_raw(home/'config.yaml') or {}
                    gateway=cfg.setdefault('gateway',{})
                    name='atlas-auto-'+binding.profile
                    entry={'name':name,'platform':'telegram','chat_id':binding.chat_id,'profile':binding.profile}
                    if binding.chat_type=='dm':entry['user_id']=binding.user_id
                    elif binding.thread_id is not None:entry['thread_id']=binding.thread_id
                    # Names are labels: native admission rejects equal-rank duplicates.
                    # Compare every other field; never merge distinct routing conditions.
                    body={k:v for k,v in entry.items() if k!='name'}
                    routes=[r for r in gateway.get('profile_routes',[]) if r.get('name')!=name
                            and {k:v for k,v in r.items() if k!='name'}!=body]
                    routes.append(entry);gateway['profile_routes']=routes
                    atomic_config_replace(home/'config.yaml',cfg)
            await asyncio.to_thread(route)
            native=await ctx.refresh_gateway_profiles()
            if binding.profile not in native.get('served_profiles',[]):
                raise PermissionError('native_profile_not_served')
            provisioned.add(binding.profile)
    if bridge is not None:
        from atlas_native_bridge.factory import build_gate
        return build_gate(bridge,provision=provision)
    gate=AdmissionGate(build_staff_provider(ctx),provision=provision)
    install_gate(gate)
    return gate
