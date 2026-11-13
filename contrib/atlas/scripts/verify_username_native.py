#!/usr/bin/env python3
"""Run every merged admission/provider test against an exact fresh install."""
from pathlib import Path
import argparse,json,os,sys,unittest,hashlib
p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--work',required=True,type=Path);args=p.parse_args()
root=args.root.resolve();work=args.work.resolve();work.mkdir(mode=0o700)
(work/'fixtures').mkdir();(work/'runtime').symlink_to(root/'runtime',target_is_directory=True);(work/'plugins').symlink_to(root/'home/plugins',target_is_directory=True)
for k in ('HERMES_SESSION_PLATFORM','HERMES_SESSION_USER_ID','HERMES_SESSION_KEY','HERMES_SESSION_CHAT_TYPE'):os.environ.pop(k,None)
os.environ.update(ATLAS_TEST_CORE=str(root/'runtime'),ATLAS_USERNAME_FIXTURE_ROOT=str(work),ADMISSION_SOURCE_FILE=str(root/'runtime/gateway/atlas_admission.py'),PYTHONDONTWRITEBYTECODE='1')
project=Path(__file__).resolve().parents[1];sys.path.insert(0,str(project/'tests/username'));sys.path.insert(0,str(root/'home/plugins/qyp_guard'))
import test_native
suite=unittest.defaultTestLoader.discover(str(project/'tests/username'),pattern='test_*.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
modules={n:{'path':str(Path(m.__file__).resolve()),'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()} for n,m in list(sys.modules.items()) if n in ('gateway.atlas_admission','gateway.session','gateway.platforms.base','plugins.platforms.telegram.adapter','plugins.platforms.telegram.update_admission','provider','staff_provider')}
receipt={'interpreter':sys.executable,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'success':result.wasSuccessful() and result.testsRun>0 and not result.skipped,'modules':modules,'real_external_calls':False,'activation':False}
(work/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
sys.exit(0 if receipt['success'] else 1)
