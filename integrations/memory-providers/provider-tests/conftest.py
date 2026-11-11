"""Pinned staged plugins, scratch-owned host state, no real network/backend."""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import tempfile

import pytest

HOST = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HOST))
# Capture the explicit test-only setting BEFORE scrubbing HERMES/provider env.
# The wrapper transports it as --provider-stage through the canonical env -i.
STAGE_SETTING = os.environ.get('HERMES_TEST_PROVIDER_STAGE') or os.environ.get('PROVIDER_STAGE')
_HOME = tempfile.TemporaryDirectory(prefix='provider-fixture-')
TEST_HOME = Path(_HOME.name)
for key in list(os.environ):
    if key.startswith(('HONCHO_', 'OPENVIKING_', 'HERMES_')) or key.endswith(('_API_KEY', '_TOKEN', '_SECRET', '_PASSWORD')):
        os.environ.pop(key, None)
os.environ.update(HOME=str(TEST_HOME), HERMES_HOME=str(TEST_HOME), HERMES_TEST_ISOLATION=str(TEST_HOME), HERMES_DISABLE_LAZY_INSTALLS='1')


def blocked(*args, **kwargs):
    raise AssertionError('Real network prohibited in provider fixture')
socket.socket.connect = blocked
socket.create_connection = blocked


def pytest_addoption(parser):
    parser.addoption('--provider-stage', default=STAGE_SETTING,
                     help='Explicit offline directory containing pinned honcho/ and openviking/ stages')


def load(name, stage):
    root = stage / name
    if not (root / '__init__.py').is_file():
        raise pytest.UsageError(f'Provider stage is missing: {root}; reconstruct the reviewed pinned '
                                'providers offline and pass --provider-stage /path/to/stage '
                                '(or HERMES_TEST_PROVIDER_STAGE via run_offline.py).')
    spec = importlib.util.spec_from_file_location('egress_' + name, root / '__init__.py', submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='session')
def plugins(request):
    # Preserve the existing task command, without requiring a checkout named repo.
    stage = Path(request.config.getoption('--provider-stage') or HOST.parent / 'plugin-staging').resolve()
    return load('honcho', stage), load('openviking', stage)
