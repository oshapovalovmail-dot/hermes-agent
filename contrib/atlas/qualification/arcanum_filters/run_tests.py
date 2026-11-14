"""Run portable full-import regressions with isolated state; no native calls."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path,
                        default=Path(__file__).resolve().parents[2]/'payload/services/atlas-read')
    parser.add_argument('--output', type=Path, required=True,
                        help='Private receipt directory outside the source project; must be fresh')
    args = parser.parse_args()
    output = args.output.resolve()
    project = Path(__file__).resolve().parents[2]
    if output.is_relative_to(project):
        parser.error('--output must be outside the source project (raw receipts contain local paths)')
    output.mkdir(parents=True, exist_ok=False)
    isolated = output/'dispatch-isolated'
    for name in ('home', 'hermes', 'tmp'):
        (isolated/name).mkdir(parents=True)
    env = {'HOME': str(isolated/'home'), 'HERMES_HOME': str(isolated/'hermes'),
           'TMPDIR': str(isolated/'tmp'), 'PATH': '/usr/bin:/bin',
           'LANG': 'en_US.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    exits = {}
    for suite in ('full_dispatch', 'filter_only_dispatch'):
        command = [sys.executable, '-B', str(Path(__file__).with_name('test_'+suite+'.py')),
                   str(args.source.resolve()), str(output/(suite+'.json'))]
        result = subprocess.run(command, cwd=isolated, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=120)
        (output/(suite+'.log')).write_bytes(result.stdout)
        (output/(suite+'-command.json')).write_text(json.dumps(
            {'command': command, 'cwd': str(isolated), 'environment': env,
             'exit_code': result.returncode}, indent=2)+'\n')
        sys.stdout.write(result.stdout.decode('utf-8', errors='replace'))
        exits[suite] = result.returncode
    return int(any(exits.values()))


if __name__ == '__main__':
    sys.exit(main())
