#!/usr/bin/env python3
"""Run exact-core FIFO/replay regressions in an explicitly consented fixture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--core',type=Path,required=True)
p.add_argument('--work',type=Path,required=True)
p.add_argument('--approve-project-policy',action='store_true')
p.add_argument('--policy-approval-provenance',required=True)
a=p.parse_args()
project=Path(__file__).resolve().parents[1]
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
if not a.approve_project_policy or not a.policy_approval_provenance.strip():
    raise SystemExit('explicit_project_policy_consent_required')
core=a.core.resolve(strict=True)
for rel,pin in json.loads((project/'core/patched-files.json').read_text()).items():
    if sha(core/rel)!=pin:raise SystemExit('core_pin_mismatch:'+rel)
work=a.work.absolute()
if work.exists() or work.is_symlink() or not work.parent.is_dir():
    raise SystemExit('fresh_owned_work_directory_required')
work.mkdir(mode=0o700)
for name in ('home','os-home'):(work/name).mkdir(mode=0o700)
policy=project/'templates/SOUL.md'
if policy.is_symlink():raise SystemExit('approved_project_policy_required')
raw=policy.read_bytes()
(work/'home/SOUL.md').write_bytes(raw)
consent={'approved':True,'scope':'owned_FIFO_regression_fixture_only','homes':[str(work/'home')],
         'sha256':sha(policy),'provenance':a.policy_approval_provenance}
(work/'consent.json').write_text(json.dumps(consent,indent=2)+'\n')
scratch=os.environ.get('TMPDIR')
if not scratch or not Path(scratch).is_dir():raise SystemExit('controlled_TMPDIR_required')
env={'PATH':'/usr/bin:/bin','HOME':str(work/'os-home'),'HERMES_HOME':str(work/'home'),
     'TMPDIR':scratch,'PYTHONDONTWRITEBYTECODE':'1','HERMES_TELEMETRY_ENABLED':'0',
     'ATLAS_TEST_CORE':str(core),'ATLAS_TEST_DELTA':str(core)}
rows=[]
for name in ('test_inherited_proofs.py','test_independent.py','test_atomic.py','test_durable_disposition.py'):
    result=subprocess.run([sys.executable,'-B',str(project/'tests/fifo'/name)],
        cwd=project/'tests/fifo',env=env,capture_output=True,text=True,timeout=90)
    text=result.stdout+result.stderr
    (work/(name+'.log')).write_text(text)
    match=re.search(r'Ran (\d+) tests? in ',text)
    count=int(match[1]) if match else 0
    rows.append({'test':name,'exit':result.returncode,'executed':count})
    if result.returncode or not count:
        (work/'result.json').write_text(json.dumps({'passed':False,'tests':rows},indent=2)+'\n')
        raise SystemExit('FIFO_regression_failed:'+name)
receipt={'passed':True,'tests':rows,'total':sum(r['executed'] for r in rows),
         'interpreter':sys.executable,'core_patch_sha256':sha(project/'core/atlas-core.patch'),
         'policy_sha256':consent['sha256'],'scope':'source/regression only; no live activation'}
(work/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
