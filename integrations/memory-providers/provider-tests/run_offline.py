"""Forward the manual pinned-provider cohort to the canonical clean runner.

Usage: python run_offline.py --provider-stage /path/to/stage [test paths] [runner/pytest args]
HERMES_TEST_PROVIDER_STAGE is captured by the shared conftest before sanitation.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    # Share the cohort's stage capture, env scrub and network block; do not add
    # another runtime setting or let the wrapper read a production home.
    from conftest import HOST, STAGE_SETTING

    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--provider-stage')
    options, args = parser.parse_known_args()
    stage = Path(options.provider_stage or STAGE_SETTING or HOST.parent / 'plugin-staging').resolve()
    for name in ('honcho', 'openviking'):
        if not (stage / name / '__init__.py').is_file():
            raise SystemExit(f'Provider stage is missing: {stage / name}; reconstruct the reviewed pinned '
                             'providers offline, then pass --provider-stage /path/to/stage '
                             'or HERMES_TEST_PROVIDER_STAGE.')
    with tempfile.TemporaryDirectory(prefix='provider-suite-') as home:
        os.environ.update(HOME=home, HERMES_HOME=home, HERMES_RUNTIME_DIR=str(Path(home) / 'tools'),
                          HERMES_PYTHON=sys.executable, HERMES_TEST_FILE_RETRIES='0',
                          HERMES_DISABLE_LAZY_INSTALLS='1')
        result = subprocess.run(['bash', str(HOST / 'scripts/run_tests.sh'),
                                 *(args or [str(Path(__file__).resolve().parent)]),
                                 '--', f'--provider-stage={stage}'], cwd=HOST, check=False, timeout=600)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
