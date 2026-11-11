"""Curated migration and lifecycle preservation controls (offline only)."""
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from test_provider_egress import migration_fixture, wired_viking


def test_mixed_curated_file_drops_standalone_reasoning_not_quoted_examples(plugins,tmp_path):
    manager,uploads=migration_fixture(plugins,tmp_path)
    prose=('User studies type systems.\n\n<think>\nRAW_REASON\n</think>\n\n'
           'The user literally quotes <think> in documentation.\n'
           '```xml\n<think>quoted technical example</think>\n```\n'
           '> <think>quoted user example</think>\n')
    (tmp_path/'MEMORY.md').write_text(prose)
    assert manager.migrate_memory_files('fixture',str(tmp_path))
    text=uploads[0]['file'][1].decode()
    assert 'RAW_' not in text
    assert 'User studies type systems.' in text
    assert 'The user literally quotes <think> in documentation.' in text
    assert '```xml\n<think>quoted technical example</think>\n```' in text
    assert '> <think>quoted user example</think>' in text


@pytest.mark.parametrize('mode',['end','new','reset','resume','compression','shutdown'])
def test_machine_only_new_session_lifecycle_no_messages_or_commits(plugins,tmp_path,mode):
    p,sink,_=wired_viking(plugins,tmp_path)
    rows=[{'role':'user','content':'RAW_MACHINE','source_kind':'runtime_notification'},{'role':'assistant','content':'RAW_DERIVED'}]
    p.sync_turn('RAW_MACHINE','RAW_DERIVED',messages=rows)
    if mode=='end':p.on_session_end(rows)
    elif mode=='shutdown':p.shutdown()
    else:
        p.on_session_switch('fixture-new',reset=mode=='reset',reason='compression' if mode=='compression' else mode)
        p._drain_finalizers(2.0)
    assert sink.calls==[]
    assert p._turn_count==0


def test_egress_guards_load_with_stdlib_without_host_core(plugins):
    for plugin in plugins:
        path=Path(plugin.__file__).with_name('egress.py')
        script='''import importlib.util, sys
spec=importlib.util.spec_from_file_location("standalone_guard",sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.current_turn("raw", "raw", []) == []
assert m.project_messages([{"role":"user","source_kind":"task_assignment","content":"raw"},{"role":"assistant","content":"raw"}]) == []
assert m.current_turn("human", "<think>raw</think>final", None) == [{"role":"user","content":"human"},{"role":"assistant","content":"final"}]
assert not any(x.startswith("agent.") for x in sys.modules)
'''
        result=subprocess.run([sys.executable,'-I','-S','-c',script,str(path)],text=True,capture_output=True,check=False,timeout=30)
        assert result.returncode==0,result.stderr
