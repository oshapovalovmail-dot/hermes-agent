#!/usr/bin/env python3
"""Fresh source proof, pure metadata and units; native initialization requires consent.

Exit 2 means the mandatory native acceptance is BLOCKED, never a native PASS.
"""
from pathlib import Path
import argparse,io,json,os,re,shutil,subprocess,sys,tarfile
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--upstream-repo',required=True,type=Path,help='Read-only local Git source containing the pinned commit')
p.add_argument('--work',required=True,type=Path,help='New verification directory; must not already exist')
p.add_argument('--approve-project-policy',action='store_true',help='Explicit operator consent for approved project SOUL only')
args=p.parse_args();project=Path(__file__).resolve().parents[1]
work=args.work.absolute()
if work.exists() or work.is_symlink() or not work.parent.is_dir():raise SystemExit('new_work_directory_required')
work.mkdir(mode=0o700)
blocked={'SOUL.md','AGENTS.md','CLAUDE.md','.git','__pycache__','.venv'}
unpacked=work/'unpacked';shutil.copytree(project,unpacked,ignore=lambda path,names:[n for n in names if n in blocked and not (Path(path)==project/'templates' and n=='SOUL.md')])
(work/'receipts').mkdir()
sys.path.insert(0,str(unpacked))
from atlas_dist.install import install,check_install,approve_policy
from atlas_dist.bundle import digest
pin=json.loads((unpacked/'core/upstream.json').read_text());root=work/'installed'
receipt=install(unpacked,root,'123456789',{})
if args.approve_project_policy:approve_policy(unpacked,root,approved=True,provenance='Actual user: «На проектный соул разрешаю»; owned fresh source-fixture; deleg_4575a09d')
core=root/'runtime';core.mkdir()
archive=subprocess.check_output(['git','-C',str(args.upstream_repo),'archive',pin['commit']])
with tarfile.open(fileobj=io.BytesIO(archive)) as reader:
    members=[member for member in reader.getmembers() if Path(member.name).name not in blocked]
    reader.extractall(core,members=members,filter='data')
patch=unpacked/'core/atlas-core.patch'
if digest(patch)!=pin['patch_sha256']:raise SystemExit('patch_hash_mismatch')
subprocess.run(['git','apply','--check',str(patch)],cwd=core,check=True)
subprocess.run(['git','apply',str(patch)],cwd=core,check=True)
expected=json.loads((unpacked/'core/patched-files.json').read_text())
actual={name:digest(core/name) for name in expected}
if actual!=expected or set(actual)!=set(pin['changed_source_files']):raise SystemExit('patched_source_exact_bytes_mismatch')
# Pure file metadata, not the native skills loader or skill_view.
import yaml
metadata=[]
for path in sorted((root/'home/skills').rglob('SKILL.md')):
    text=path.read_text()
    if not text.startswith('---\n'):raise ValueError('frontmatter_missing')
    front=yaml.safe_load(text.split('---',2)[1])
    if not isinstance(front,dict) or not front.get('name') or not front.get('description'):raise ValueError('skill_metadata_invalid')
    metadata.append({'path':str(path.relative_to(root/'home/skills')),'name':front['name'],'sha256':digest(path)})
try:
    check={'state':'PASS','result':check_install(root)}
except PermissionError as error:
    if not str(error).startswith('policy_missing:'):raise
    check={'state':'BLOCKED','reason':str(error),'native_skills_executed':False,'native_SDK_check_executed':False}
for name in ('test-home','test-hermes-home','scratch'):(work/name).mkdir()
env={key:os.environ[key] for key in ('PATH','LANG','LC_ALL','SYSTEMROOT') if key in os.environ}
env.update(ATLAS_TEST_CORE=str(core),PYTHONDONTWRITEBYTECODE='1',HOME=str(work/'test-home'),HERMES_HOME=str(work/'test-hermes-home'),TMPDIR=str(work/'scratch'))
unit=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(unpacked/'tests'),'-v'],cwd=unpacked,env=env,capture_output=True,text=True)
log=unit.stdout+unit.stderr;(work/'unit-tests.txt').write_text(log)
match=re.search(r'Ran (\d+) tests? in ',log);count=int(match[1]) if match else 0
result={'interpreter':sys.executable,'python_version':sys.version,'inherited_parent_manifest_sha256':digest(project/'manifests/package.json'),'final_source_frozen':False,'native_fifo_guard':'SOURCE_NATIVE_QUALIFIED_INSTALLATION_NOT_ACTIVATED','native_actor_ready':False,'fresh_physical_unpack':True,'core_commit':pin['commit'],'core_patch_file_count':len(actual),'core_all_bytes_verified':True,'core_files':actual,'installed':receipt,'check':check,'skill_metadata':{'state':'PASS_METADATA_ONLY','count':len(metadata),'items':metadata},'unit_exit':unit.returncode,'unit_tests_executed':count,'publication':'not performed','activation':'not performed','live_auth_staff_tasha':'NOT_RUN live; concrete provider integrated and local native FIFO/model/MCP qualified separately','native_pm_install':'not exercised','sandbox_image_build':'not exercised','continuation_owner':'parent publication/auth-integration coordinator'}
(work/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'receipt':str(work/'verification.json'),'unit_exit':unit.returncode,'unit_tests':count,'native_check':check,'skill_metadata_count':len(metadata),'core_patch_files':len(actual),'activated':False},indent=2))
raise SystemExit(unit.returncode or (1 if not count else 2 if check['state']=='BLOCKED' else 0))
