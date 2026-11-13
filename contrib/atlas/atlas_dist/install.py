"""Portable Atlas distribution installation; never starts a service."""
from pathlib import Path,PurePosixPath
import argparse,copy,hashlib,importlib.util,json,os,re,shutil,subprocess,sys
from urllib.parse import urlsplit
from .bundle import READ_FILES,TOOL_CONSTANTS,assignments,digest,portable_source,repin

CANONICAL_ID=re.compile(r'[1-9][0-9]{0,19}')

def safe_relative(value):
    if not isinstance(value,str) or not value or '\\' in value or '\x00' in value:raise ValueError('invalid_relative_path')
    parts=value.split('/')
    if value.startswith('/') or any(p in ('','.','..') for p in parts):raise ValueError('invalid_relative_path')
    return Path(*parts)

def verify_payload(project):
    project=Path(project);manifest=json.loads((project/'manifests/payload.json').read_text())
    actual={str(p.relative_to(project)) for p in (project/'payload').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if actual!=set(manifest['files']):raise ValueError('payload_file_set_mismatch')
    for rel,sha in manifest['files'].items():
        path=project/safe_relative(rel)
        if path.is_symlink() or digest(path)!=sha:raise ValueError('payload_hash_mismatch:'+rel)
    count=len(list((project/'payload/home/skills').rglob('SKILL.md')))
    if count!=manifest['skills']:raise ValueError('skills_count_mismatch')
    return {'files':len(actual),'skills':count}

def validate_trusted(trusted):
    allowed=set(TOOL_CONSTANTS.values())|{'docker','arc_cwd','arc_roots','github_repos','honcho_endpoint','code_root'}
    if not isinstance(trusted,dict) or set(trusted)-allowed:raise ValueError('unknown_trusted_parameter')
    out=copy.deepcopy(trusted)
    for key,value in out.items():
        if key=='code_root' and (type(value)is not str or hashlib.sha256(value.encode('utf-8','surrogatepass')).hexdigest() not in ('2ab3220bb5813a4186e6cf6607edf9ae95d383315f56e6c7ded43539ed8b6d85', 'fbff7b2e39ddd97249888e6a2b5095ca2428726485bede6b485f42e3c0af3c92', '067b1d8e58d9c132a81a511e079a5bca71d5f97da645a67f4e684613b8f6868f')):
            raise ValueError('approved_code_mount_root_required')
        if key in ('arc_roots','github_repos'):
            if not isinstance(value,list):raise ValueError('list_required')
            for item in value:
                if key=='arc_roots':safe_relative(item)
                elif not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',item):raise ValueError('invalid_repository')
        elif key=='honcho_endpoint':
            endpoint=urlsplit(value)
            if endpoint.scheme not in ('http','https') or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:raise ValueError('credential_free_honcho_endpoint_required')
        elif not isinstance(value,str) or not Path(value).is_absolute() or '..' in Path(value).parts or '\x00' in value:raise ValueError('absolute_trusted_path_required')
    return out

def _private_root(root):
    root=Path(root)
    if not root.is_absolute() or '..' in root.parts or str(root)=='/':raise ValueError('absolute_new_root_required')
    for part in [root,*root.parents]:
        if part.is_symlink():raise ValueError('symlink_root_component_forbidden')
    if root.exists():raise FileExistsError('root_must_not_exist')
    if not root.parent.is_dir():raise ValueError('existing_parent_required')
    root.mkdir(mode=0o700)
    return root

def _write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text)

def _config(root,owner,trusted,pins,home):
    reads={f'mcp__atlas_read__{name}':{'service':'atlas_read','method':name,'access':'read','reviewed':True} for name in ('integration_status','wiki_read','tracker_read','pr_read','trace_read','nirvana_read','yt_read','datalens_read','service_catalog','service_read')}
    python=str(Path(sys.executable).absolute())
    server={'command':python,'args':['-I','-B',str(root/'services/atlas-read/sidecar.py')],'cwd':str(home),'env':{},'sampling':{'enabled':False},'tools':{'include':[v['method'] for v in reads.values()],'resources':False,'prompts':False}}
    pin={k:copy.deepcopy(server[k]) for k in ('command','args','cwd')};pin['source_sha256']=pins['sidecar.py']
    settings={'root':str(root/'sandbox'),'admission_control':str(root/'control'),'admin_home':str(root/'home'),'admin_helper':str(root/'services/atlas-admin/native_profile_helper.py'),'sandbox_backend':'docker','docker_image':'sha256:'+'0'*64,'docker_host':'unix://'+str(root/'control/unconfigured-docker.sock'),'docker_bin':trusted.get('docker','/usr/bin/false'),'container_python':'/opt/atlas/bin/python3','container_node':'/usr/local/bin/node','media_policy_integrated':True,'reviewed_read_tools':reads,'required_read_tools':list(reads),'reviewed_mutation_tools':{},'reviewed_trace_tools':{},'reviewed_stdio_servers':{'atlas_read':pin},'reviewed_service_files':pins}
    config={'model':{'default':'gpt-6.1-terra','provider':'openai-codex'},'agent':{'reasoning_effort':'medium','allowed_tools':['qyp_exec','qyp_read','qyp_export','qyp_role','memory','skills_list','skill_view',*reads]},'plugins':{'enabled':['qyp_guard'],'isolation':'in_process','entries':{'qyp_guard':{'enabled':True,'allow_profile_admin':True,'settings':settings}}},'tools':{'tool_search':{'enabled':'off'}},'platform_toolsets':{'telegram':['qyp_guard','memory','skills','mcp-atlas_read']},'mcp_servers':{'atlas_read':server},'media_delivery':{'required_policy':'qyp_guard'},'unauthorized_dm_behavior':'ignore','telegram':{'enabled':False,'dm_policy':'allowlist','allow_from':[owner],'group_policy':'disabled','group_allow_from':[]},'gateway':{'multiplex_profiles':True,'required_policies':['qyp_guard'],'profile_routes':[]}}
    config['agent']['allowed_tools'].append('qyp_code_read')
    settings['code_research_root']=trusted.get('code_root')
    from .config_candidate import candidate_config
    return candidate_config(config,transport=False)

def install(project,root,owner,trusted):
    project=Path(project)
    if not isinstance(owner,str) or not CANONICAL_ID.fullmatch(owner):raise ValueError('canonical_owner_id_required')
    trusted=validate_trusted(trusted);payload=verify_payload(project);root=_private_root(root)
    try:
        for name in ('home','control','services','sandbox','bin'): (root/name).mkdir(mode=0o700)
        shutil.copytree(project/'payload',root,dirs_exist_ok=True)
        for p in root.rglob('*'):
            if p.is_dir():p.chmod(0o700)
            elif p.is_file():p.chmod(0o600)
        _write(root/'control/operator.json',{'owner_telegram_id':owner,'trusted':trusted})
        read=root/'services/atlas-read'
        for p in read.glob('*.py'):p.write_text(portable_source(p.read_text(),trusted))
        pins=repin(read)
        home=root/'home';profile=home/'profiles'/('tg-'+owner);profile.mkdir(parents=True,mode=0o700)
        template_home=root/'control/template-stdio';template_home.mkdir(mode=0o700)
        cfg=_config(root,owner,trusted,pins,home)
        cfg['gateway']['profile_routes']=[{'name':'atlas-tg-'+owner,'platform':'telegram','user_id':owner,'chat_id':owner,'profile':'tg-'+owner}]
        _write(home/'config.yaml',cfg)
        child=copy.deepcopy(cfg);child['gateway']['profile_routes']=[]
        child['mcp_servers']['atlas_read']['cwd']=str(profile)
        child['plugins']['entries']['qyp_guard']['settings']['reviewed_stdio_servers']['atlas_read']['cwd']=str(profile)
        _write(profile/'config.yaml',child)
        template=copy.deepcopy(child);template['mcp_servers']['atlas_read']['cwd']=str(template_home)
        template['plugins']['entries']['qyp_guard']['settings']['reviewed_stdio_servers']['atlas_read']['cwd']=str(template_home)
        _write(root/'control/profile-template.json',template)
        _write(root/'control/admissions.json',{'admitted':[owner],'pending':{}})
        _write(root/'control/authorization-policy.json',json.loads((project/'templates/authorization-policy.json').read_text()))
        for folder in ('skills','plugins'):(profile/folder).symlink_to(home/folder,target_is_directory=True)
        (profile/'memories').mkdir(mode=0o700)
        for name in ('MEMORY.md','USER.md'):_write(profile/'memories'/name,'')
        if 'honcho_endpoint' in trusted:
            _write(root/'control/honcho-profile-template.json',{'enabled':False,'baseUrl':trusted['honcho_endpoint'],'workspace':'atlas','credentialSetupRequired':True})
        # Copy source project for reproducible local checks, not another checkout.
        shutil.copytree(project/'atlas_dist',root/'distribution/atlas_dist',ignore=shutil.ignore_patterns('__pycache__'))
        _write(root/'distribution/check.py',"import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parent))\nfrom atlas_dist.install import check_install\nimport json\nprint(json.dumps(check_install(Path(__file__).resolve().parents[1]),indent=2))\n")
        receipt={'root':str(root),'owner_telegram_id':owner,'payload':payload,'activated':False,'credentials_copied':False,'native_core_installed':False,'sandbox_qualified':False,'read_bundle':pins,'installation_state':'source-fixture; native bootstrap/auth/docker qualification required'}
        _write(root/'control/install-receipt.json',receipt)
        return receipt
    except BaseException:
        # Keep partial tree for diagnosis, never remove operator-owned material.
        raise

def _load(name,path,package=False):
    spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(Path(path).parent)] if package else None)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod

def check_install(root):
    root=Path(root)
    if not (root/'runtime/hermes_constants.py').is_file():raise ValueError('pinned_core_source_required; run --prepare-core first')
    sys.path.insert(0,str(root/'runtime'))
    cfg=json.loads((root/'home/config.yaml').read_text());settings=cfg['plugins']['entries']['qyp_guard']['settings']
    for name,sha in settings['reviewed_service_files'].items():
        path=root/'services/atlas-read'/safe_relative(name)
        if path.is_symlink() or digest(path)!=sha:raise PermissionError('read_bundle_hash_mismatch')
    # Integrity refusal is pure and precedes native initialization consent.
    policy_preflight(root)
    # Import the actual copied guard, not a generated imitation or mocks.
    package='_atlas_check_'+hashlib.sha256(str(root).encode()).hexdigest()[:12]
    guard=_load(package,root/'home/plugins/qyp_guard/__init__.py',True)
    readiness=_load(package+'.readiness',root/'home/plugins/qyp_guard/readiness.py')
    # Explicit profile_home avoids loading unrelated Hermes configuration.
    readiness.verify_config(cfg,profile_home=root/'home')
    child_path=root/'home/profiles'/('tg-'+json.loads((root/'control/operator.json').read_text())['owner_telegram_id'])
    readiness.verify_config(json.loads((child_path/'config.yaml').read_text()),profile_home=child_path)
    sidecar=_load(package+'_sidecar',root/'services/atlas-read/sidecar.py')
    server=sidecar.build_server()
    # Exercise the real SDK over an isolated stdio child, not private handlers.
    import asyncio
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters,stdio_client
    async def schemas():
        params=StdioServerParameters(command=str(Path(sys.executable).absolute()),args=['-I','-B',str(root/'services/atlas-read/sidecar.py')],cwd=str(root/'home'),env={'HOME':str(root/'home'),'PATH':'/usr/bin:/bin','TMPDIR':str(root/'control')})
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                response=await session.list_tools()
                status=await session.call_tool('integration_status',{})
                if status.is_error or not status.structured_content['ok']:raise ValueError('stdio_status_failed')
                catalog=await session.call_tool('service_catalog',{'max_chars':4000})
                if catalog.is_error or not catalog.structured_content['ok']:raise ValueError('stdio_catalog_failed')
                catalog_header=json.loads(catalog.structured_content['text'])
                if catalog_header['operation_count']!=2121 or catalog_header['service_count']!=151:raise ValueError('reviewed_catalog_count_mismatch')
                denied=await session.call_tool('service_read',{'operation':'terminal.exec','arguments':{'code':'id'}})
                if not denied.is_error:raise ValueError('unreviewed_operation_allowed')
                return [tool.model_dump(mode='json',by_alias=True) for tool in response.tools]
    tools=asyncio.run(schemas())
    if len(tools)!=10:raise ValueError('expected_ten_read_tools')
    from jsonschema import Draft202012Validator
    for tool in tools:Draft202012Validator.check_schema(tool['inputSchema'])
    skill_root=root/'home/skills';skills=[]
    import yaml
    for path in sorted(skill_root.rglob('SKILL.md')):
        text=path.read_text()
        if not text.startswith('---\n'):raise ValueError('frontmatter_missing:'+str(path.relative_to(root)))
        front=yaml.safe_load(text.split('---',2)[1])
        if not isinstance(front,dict) or not front.get('name') or not front.get('description'):raise ValueError('skill_metadata_invalid')
        skills.append({'path':str(path.relative_to(skill_root)),'name':front['name'],'sha256':digest(path)})
    # Native catalog + progressive disclosure from the unpacked pinned core.
    # Use a closed environment; preprocess=False never executes inline recipes.
    code=('import sys,json; sys.path.insert(0,'+repr(str(root/'runtime'))+'); '
          'from tools.skills_tool import find_all_skills,skill_view; '
          'items=find_all_skills(); '
          'views=[json.loads(skill_view(s["name"],preprocess=False)) for s in items]; '
          'assert all(v.get("success") for v in views); '
          'print(json.dumps({"count":len(items),"names":[s["name"] for s in items]}))')
    env={'PATH':'/usr/bin:/bin','HOME':str(root/'home'),'HERMES_HOME':str(root/'home'),'HERMES_RUNTIME_DIR':str(root/'tools'),'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(root/'control')}
    proc=subprocess.run([sys.executable,'-I','-B','-c',code],env=env,capture_output=True,text=True,timeout=90)
    if proc.returncode:raise ValueError('native_skills_loader_failed:'+proc.stderr[-2000:])
    native_skills=json.loads(proc.stdout)
    if native_skills['count']!=len(skills):raise ValueError('native_skill_catalog_count_mismatch')
    # Guard negative controls: even owner cannot acquire host execution.
    from types import SimpleNamespace
    policy=sys.modules.get(package+'.policy') or _load(package+'.policy',root/'home/plugins/qyp_guard/policy.py')
    broker=sys.modules[package+'.broker'];owner=broker.Principal(broker.OWNER,'fixture','owner')
    ctx=SimpleNamespace(get_config=lambda key,default=None:settings.get(key,default))
    for name in ('terminal','browser_exec','computer_use','telegram_send','read_file'):
        if policy.allowed_tool(ctx,owner,name,{}):raise PermissionError('host_tool_was_allowed')
    return {'root':str(root),'guard_config_verified':True,'read_tool_count':len(tools),'reviewed_operation_count':2121,'reviewed_service_count':151,'native_fifo_guard':'SOURCE_NATIVE_QUALIFIED_INSTALLATION_NOT_ACTIVATED','native_actor_ready':False,'read_tool_names':[x['name'] for x in tools],'skill_count':len(skills),'skills':skills,'native_schema_validation':True,'host_tools_denied':True,'activated':False,'live_read_tested':False,'sandbox_execution_tested':False}

def approve_policy(project,root,*,approved=False,provenance=''):
    """Explicit operator action; copies only the project's approved exact bytes."""
    if approved is not True or not isinstance(provenance,str) or not provenance.strip():
        raise PermissionError('explicit_instruction_policy_consent_required')
    project=Path(project);root=Path(root)
    source=project/'templates/SOUL.md'
    if source.is_symlink() or not source.is_file():raise PermissionError('approved_project_policy_required')
    raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    store=_load('_atlas_bootstrap_instruction_consent',project/'payload/services/atlas-admin/instruction_consent.py')
    with store.consent_lock(root):
        homes=[root/'home',*sorted((root/'home/profiles').glob('*'))]
        targets=[*(h/'SOUL.md' for h in homes),root/'control/SOUL.md']
        approval=root/'control/instruction-policy-approval.json'
        if approval.exists() or approval.is_symlink() or any(t.exists() or t.is_symlink() for t in targets):
            raise PermissionError('policy_target_must_be_fresh')
        consent={'approved':True,'scope':'native-home-initialization','homes':[str(h) for h in homes],
                 'sha256':sha,'provenance':provenance,'source':'project/templates/SOUL.md'}
        store.atomic_consent_write(root,consent)
        for target in targets:_write(target,raw.decode())
    return consent

def policy_preflight(root):
    """Exact approved bytes plus recorded consent, before initializing imports."""
    root=Path(root);homes=[root/'home',*sorted((root/'home/profiles').glob('*'))]
    approval=root/'control/instruction-policy-approval.json'
    if not approval.is_file() or approval.is_symlink():
        raise PermissionError('policy_missing:explicit_native_initialization_consent_required')
    consent=json.loads(approval.read_text())
    if (consent.get('approved') is not True or consent.get('scope')!='native-home-initialization'
            or not consent.get('provenance') or not set(str(h) for h in homes)<=set(consent.get('homes',[]))):
        raise PermissionError('policy_missing:explicit_native_initialization_consent_required')
    for target in [*(h/'SOUL.md' for h in homes),root/'control/SOUL.md']:
        if target.is_symlink() or not target.is_file() or digest(target)!=consent.get('sha256'):
            raise PermissionError('policy_missing:approved_SOUL_hash_required')


def _bind_native_launcher(root,name):
    """Fail closed before native Python on absent/foreign home, runtime or profile.

    This is an installation-local POSIX guard around the native writer's output,
    not a change to the pinned core or to another instance's launcher.
    """
    import shlex
    root=Path(root)
    target=root/'bin'/name;native=root/'control/native-launchers'/name
    if target.is_symlink() or not target.is_file() or native.exists():raise ValueError('new_native_launcher_required')
    if not target.read_bytes().startswith(b'#!/bin/sh\n'):raise ValueError('native_POSIX_shell_launcher_required')
    body='#!/bin/sh\n'
    body+='if [ "${HERMES_HOME-}" != '+shlex.quote(str(root/'home'))+' ] || [ "${HERMES_RUNTIME_DIR-}" != '+shlex.quote(str(root/'tools'))+' ] || [ -n "${HERMES_PROFILE-}" ]; then\n'
    body+='  printf "%s\\n" "atlas_launcher_binding_required: explicit installation home/runtime; no ambient profile" >&2\n  exit 78\nfi\n'
    body+='for arg do\n  case "$arg" in -p|--profile|-p?*|--profile=*) printf "%s\\n" "atlas_launcher_binding_required: profile selectors forbidden" >&2; exit 78;; esac\ndone\n'
    body+='exec /bin/sh '+shlex.quote(str(native))+' "$@"\n'
    native.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    target.replace(native)
    native.chmod(0o600)  # Backing data, not an exposed unguarded bin entry point.
    _write(target,body);target.chmod(0o700)

def bind_native_launcher(root):
    root=Path(root)
    _bind_native_launcher(root,'hermes')
    for name in ('hermes-acp','hermes-agent'):
        if (root/'bin'/name).exists():_bind_native_launcher(root,name)


def native_commands(root,python):
    return [[str(python),'-S','-m','pm.cli','install','--tools-only','--without','chromium','--without','cua-driver'],[str(python),'-S','-m','pm.cli','install','--extra','telegram','--extra','mcp'],[str(python),'hermes_cli/_launchers.py',str(root/'bin')]]

def bootstrap_native(project,root,python):
    """Explicit operator opt-in. Pinned upstream + source patch, own root only."""
    project=Path(project);root=Path(root);core=root/'runtime'
    policy_preflight(root)  # Before Git, PM, native imports or any initializing call.
    pin=json.loads((project/'core/upstream.json').read_text())
    if core.exists():raise FileExistsError('runtime_must_not_exist')
    subprocess.run(['git','clone','--no-checkout',pin['url'],str(core)],check=True)
    subprocess.run(['git','-C',str(core),'checkout','--detach',pin['commit']],check=True)
    if subprocess.check_output(['git','-C',str(core),'rev-parse','HEAD']).decode().strip()!=pin['commit']:raise ValueError('upstream_commit_mismatch')
    patch=project/'core/atlas-core.patch'
    if digest(patch)!=pin['patch_sha256']:raise ValueError('core_patch_mismatch')
    subprocess.run(['git','-C',str(core),'apply','--check',str(patch)],check=True)
    subprocess.run(['git','-C',str(core),'apply',str(patch)],check=True)
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','LC_ALL','SYSTEMROOT','TMPDIR')}
    env.update(HERMES_HOME=str(root/'home'),HERMES_RUNTIME_DIR=str(root/'tools'),HERMES_GATEWAY_LAUNCHD_LABEL='ai.hermes.atlas-isolated',UV_CACHE_DIR=str(root/'cache/uv'))
    for cmd in native_commands(root,Path(python)):subprocess.run(cmd,cwd=core,env=env,check=True)
    bind_native_launcher(root)
    # PM owns the selected dependency generation; the stable store Python alone
    # does not contain MCP. Resolve the actual local venv with the native API.
    code="from pathlib import Path; from pm.environments import project_python; print(project_python(Path("+repr(str(core))+")))"
    proc=subprocess.run([str(python),'-I','-c','import sys; sys.path.insert(0,'+repr(str(core))+'); '+code],env=env,capture_output=True,text=True,check=True)
    selected=proc.stdout.strip()
    if not Path(selected).is_relative_to(root):raise ValueError('native_interpreter_outside_installation')
    for path in [root/'home/config.yaml',*list((root/'home/profiles').glob('*/config.yaml')),root/'control/profile-template.json']:
        cfg=json.loads(path.read_text());cfg['mcp_servers']['atlas_read']['command']=selected;cfg['plugins']['entries']['qyp_guard']['settings']['reviewed_stdio_servers']['atlas_read']['command']=selected
        path.write_text(json.dumps(cfg,indent=2)+'\n')
    for cmd in ([str(root/'bin/hermes'),'config','path'],[str(root/'bin/hermes'),'--version'],[str(root/'bin/hermes'),'gateway','run','--help']):subprocess.run(cmd,env=env,check=True)
    receipt=json.loads((root/'control/install-receipt.json').read_text());receipt['native_core_installed']=True;receipt['activated']=False;(root/'control/install-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path);parser.add_argument('--owner-telegram-id');parser.add_argument('--check',action='store_true');parser.add_argument('--native',action='store_true');parser.add_argument('--bootstrap-python',type=Path,default=Path(sys.executable));parser.add_argument('--trusted-paths',type=Path);parser.add_argument('--honcho-endpoint')
    for key in sorted(set(TOOL_CONSTANTS.values())|{'docker'}):parser.add_argument('--'+key+'-bin',dest=key)
    parser.add_argument('--approve-project-policy',action='store_true',help='Explicit consent to initialize native instruction files from the exact project SOUL');parser.add_argument('--policy-approval-provenance');parser.add_argument('--arc-cwd');parser.add_argument('--arc-root',action='append',default=[]);parser.add_argument('--github-repo',action='append',default=[])
    args=parser.parse_args();project=Path(__file__).resolve().parents[1]
    if args.check:print(json.dumps(check_install(args.root),ensure_ascii=False,indent=2));return
    trusted=json.loads(args.trusted_paths.read_text()) if args.trusted_paths else {}
    for key in set(TOOL_CONSTANTS.values())|{'docker'}:
        if getattr(args,key):trusted[key]=getattr(args,key)
    if args.honcho_endpoint:trusted['honcho_endpoint']=args.honcho_endpoint
    if args.arc_cwd:trusted['arc_cwd']=args.arc_cwd
    if args.arc_root:trusted['arc_roots']=args.arc_root
    if args.github_repo:trusted['github_repos']=args.github_repo
    receipt=install(project,args.root,args.owner_telegram_id,trusted)
    if args.approve_project_policy:approve_policy(project,args.root,approved=True,provenance=args.policy_approval_provenance or '')
    if args.native:receipt=bootstrap_native(project,args.root,args.bootstrap_python)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
