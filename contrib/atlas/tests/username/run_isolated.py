"""Bounded source/SDK suite; no gateway, native HOME bootstrap or model calls."""
from pathlib import Path
import hashlib
import json
import os
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
assert not any(k in os.environ for k in ('HERMES_SESSION_PLATFORM','HERMES_SESSION_USER_ID','HERMES_SESSION_KEY','HERMES_SESSION_CHAT_TYPE'))
os.environ['ADMISSION_SOURCE_FILE']=str(ROOT/'runtime/gateway/atlas_admission.py')
sys.path.insert(0,str(ROOT/'tests'))
# Bind native packages before discovery. No module may fall back to old Atlas
# admission code simply because another SDK test was imported first.
import test_native
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
def flatten(node):
    for child in node:
        if isinstance(child,unittest.TestSuite):yield from flatten(child)
        else:yield child
ids=[t.id() for t in flatten(suite)]
assert len(ids)==len(set(ids)), 'duplicate test IDs'
modules={}
for name in ('gateway.atlas_admission','gateway.session','gateway.platforms.base','gateway.media_delivery_gate','plugins.platforms.telegram.adapter','plugins.platforms.telegram.update_admission'):
    module=__import__(name,fromlist=['_'])
    path=Path(module.__file__).resolve()
    assert path.is_relative_to(ROOT/'runtime'),(name,str(path))
    modules[name]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
result=unittest.TextTestRunner(verbosity=2).run(suite)
protected=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and p.name in ('SOUL.md','AGENTS.md','CLAUDE.md')]
assert not protected,protected
receipt={'interpreter':sys.executable,'tests_run':result.testsRun,'unique_test_ids':ids,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'success':result.wasSuccessful(),'modules':modules,'hermes_load_config':'hard preflight sentinel; initializer forbidden','instruction_files':protected,'model_requests':0,'full_gateway_model_fifo':'NOT_RUN'}
(ROOT/'test-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k not in ('unique_test_ids','modules')}))
sys.exit(0 if result.wasSuccessful() and result.testsRun>0 and not result.skipped else 1)
