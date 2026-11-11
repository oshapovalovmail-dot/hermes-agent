"""Portable fixture layout/config contracts, exercised in owned scratch dirs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


HERE = Path(__file__).resolve().parent
HOST = HERE.parents[2]


def probe(script, *args, env):
    result = subprocess.run([sys.executable, '-I', '-c', script, *map(str, args)],
                            env=env, text=True, capture_output=True, check=False, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_conftest_uses_actual_host_and_tmpdir_not_checkout_basename(tmp_path):
    host = tmp_path / 'checkout-renamed'
    suite = host / 'integrations/memory-providers/provider-tests'
    suite.mkdir(parents=True)
    shutil.copy2(HERE / 'conftest.py', suite / 'conftest.py')
    scratch = tmp_path / 'owned-scratch'
    scratch.mkdir()
    stage = tmp_path / 'selected-stage'
    probe('''import os, pathlib, runpy, sys
m = runpy.run_path(sys.argv[1])
assert m['HOST'] == pathlib.Path(sys.argv[2]), m['HOST']
assert pathlib.Path(os.environ['HERMES_HOME']).is_relative_to(pathlib.Path(sys.argv[3]))
assert m['STAGE_SETTING'] == sys.argv[4]
assert 'HONCHO_API_KEY' not in os.environ
''', suite / 'conftest.py', host, scratch, stage,
          env={**os.environ, 'TMPDIR': str(scratch), 'HERMES_TEST_PROVIDER_STAGE': str(stage),
               'HONCHO_API_KEY': 'synthetic-not-a-secret'})


@pytest.mark.parametrize('mode', ['cli', 'env'])
def test_offline_wrapper_forwards_stage_through_canonical_clean_runner(tmp_path, mode):
    # A renamed minimal host fixture: no sibling named repo or plugin-staging.
    host = tmp_path / 'portable-host'
    suite = host / 'integrations/memory-providers/provider-tests'
    suite.mkdir(parents=True)
    shutil.copytree(HOST / 'scripts', host / 'scripts',
                    ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('conftest.py', 'run_offline.py'):
        shutil.copy2(HERE / name, suite / name)
    stage = tmp_path / 'explicit-stage'
    for provider in ('honcho', 'openviking'):
        directory = stage / provider
        directory.mkdir(parents=True)
        (directory / '__init__.py').write_text('SELECTED = "explicit-stage"\n')
    (suite / 'test_selected.py').write_text('''import os
from pathlib import Path

def test_selected(plugins):
    assert all(p.SELECTED == 'explicit-stage' for p in plugins)
    assert Path(os.environ['HERMES_HOME']).is_relative_to(Path(os.environ['TMPDIR']))
    assert 'HONCHO_API_KEY' not in os.environ
''')
    env = {**os.environ, 'HERMES_PYTHON': sys.executable, 'HERMES_TEST_FILE_RETRIES': '0',
           'HERMES_TEST_PROVIDER_STAGE': str(stage), 'HONCHO_API_KEY': 'synthetic-not-a-secret'}
    args = ['--provider-stage', str(stage)] if mode == 'cli' else []
    result = subprocess.run([sys.executable, str(suite / 'run_offline.py'), *args,
                             str(suite / 'test_selected.py'), '-j', '1', '-q'],
                            env=env, text=True, capture_output=True, check=False, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'clean env' in result.stdout
    assert '1 tests passed' in result.stdout
    assert 'skipped' not in result.stdout


def test_missing_explicit_stage_is_actionable_failure_not_skipped_green(tmp_path):
    result = subprocess.run([sys.executable, str(HERE / 'run_offline.py'),
                             '--provider-stage', str(tmp_path / 'missing-stage'),
                             str(HERE / 'test_provider_egress.py'), '-j', '1', '-q'],
                            env={**os.environ, 'HERMES_PYTHON': sys.executable,
                                 'HERMES_TEST_FILE_RETRIES': '0'},
                            text=True, capture_output=True, check=False, timeout=120)
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert 'Provider stage is missing' in output
    assert '--provider-stage' in output
