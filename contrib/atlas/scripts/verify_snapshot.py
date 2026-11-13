#!/usr/bin/env python3
"""Re-run synthetic Snapshot/SDK regressions against an exact installed source root."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    work = args.work.absolute()
    if work.exists() or work.is_symlink() or not work.parent.is_dir():
        parser.error('fresh_owned_work_directory_required')
    project = Path(__file__).resolve().parents[1]
    tests = project / 'tests/snapshot'
    work.mkdir(mode=0o700)
    home = work / 'home'
    home.mkdir()
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'HERMES_HOME': str(home / 'native'),
           'TMPDIR': str(work), 'LANG': 'en_US.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
           'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'ATLAS_FIX_SOURCE': str(root)}
    selections = [str(tests / name) for name in ('test_capacity.py', 'test_safety.py', 'test_breaker.py',
                                               'test_sdk.py', 'test_tracker_sdk.py')]
    selections.append(str(tests / 'test_native_sdk.py') + '::test_native_handler_real_sdk_four_errors_then_valid')
    rows = []
    for label, selected in [('sdk', selections), ('r1', [str(tests / 'test_r1_cleanup.py')])]:
        command = [sys.executable, '-I', '-B', '-m', 'pytest', '-c', '/dev/null', '--noconftest',
                   '-p', 'no:cacheprovider', '--basetemp', str(work / label), '-q', '-s', '--tb=short', *selected]
        process = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, timeout=300)
        log = process.stdout + process.stderr
        (work / (label + '.log')).write_text(log, encoding='utf-8')
        count = re.search(r'(\d+) passed', log)
        rows.append({'cohort': label, 'command': command, 'exit': process.returncode,
                     'passed': int(count[1]) if count else 0})
    store = root / 'services/atlas-read/read_snapshot_store.py'
    result = {'root': str(root), 'python': sys.executable, 'store_sha256': hashlib.sha256(store.read_bytes()).hexdigest(),
              'rows': rows, 'synthetic_upstream': True, 'model_requests': 0, 'activation': False,
              'passed': all(row['exit'] == 0 and row['passed'] > 0 for row in rows)}
    (work / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
