"""Run the portable offline regressions in a closed environment; retain receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('red', 'green'), required=True)
    parser.add_argument('--dependency-path', action='append', default=[],
                        help='Existing read-only site-packages directory; never installs dependencies')
    args = parser.parse_args()
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    if args.dependency_path:
        for path in args.dependency_path:
            if not Path(path).is_dir():
                parser.error('dependency path must be an existing directory')
        environment['PYTHONPATH'] = os.pathsep.join(args.dependency_path)
    receipts = []
    for name in ('test_identity.py', 'test_arcanum.py', 'test_payload_seam.py'):
        command = [sys.executable, '-B', str(ROOT/name)]
        result = subprocess.run(command, cwd=PROJECT, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = ROOT/(args.phase+'-'+name.removesuffix('.py')+'.log')
        log.write_text(result.stdout)
        counts = re.search(r'Ran (\d+) tests?', result.stdout)
        receipt = {'command': command, 'cwd': str(PROJECT), 'exit_code': result.returncode,
                   'tests': int(counts[1]) if counts else None, 'log': log.name,
                   'test_sha256': hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),
                   'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        receipts.append(receipt)
        print(json.dumps(receipt), flush=True)
        print(result.stdout[-1400:], flush=True)
    report = {'phase': args.phase, 'environment': environment, 'commands': receipts,
              'all_passed': all(r['exit_code'] == 0 for r in receipts)}
    (ROOT/(args.phase+'-receipt.json')).write_text(json.dumps(report, indent=2)+'\n')
    return 0 if report['all_passed'] else 1

if __name__ == '__main__':
    sys.exit(main())
