"""Portable offline runner. Existing mcp, jsonschema and cryptography required.
No installs, private fixtures, operator bindings, network or repository discovery.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, value): path.write_text(json.dumps(value, indent=2) + '\n')

def worker():
    import importlib.util
    import unittest
    test = HERE / 'test_tracker_retention.py'
    spec = importlib.util.spec_from_file_location('tracker_retention_tests', test)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.TrackerRetention)
    assert suite.countTestCases() == 18
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    save(Path(os.environ['ATLAS_TEST_OUTPUT']) / 'regressions-result.json', {'tests_run': result.testsRun, 'failures': [{'test': str(t), 'traceback': tb} for t, tb in result.failures], 'errors': [{'test': str(t), 'traceback': tb} for t, tb in result.errors], 'successful': result.wasSuccessful()})
    return 0 if result.wasSuccessful() else 1

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=PROJECT / 'payload/services/atlas-read', help='explicit alternate complete public source closure for RED/control')
    parser.add_argument('--output', required=True, type=Path, help='fresh nonexistent directory outside project')
    parser.add_argument('--only', choices=('all', 'regressions', 'stdio'), default='all')
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output == PROJECT or PROJECT in output.parents:
        parser.error('--output must be outside the project')
    if output.exists(): parser.error('--output must be fresh/nonexistent')
    versions = {name: importlib.metadata.version(name) for name in ('mcp', 'jsonschema', 'cryptography')}
    pins = json.loads((HERE / 'baseline-pins.json').read_text())
    assert len(pins) == 11
    for name, expected in pins.items():
        path = source / name
        assert path.is_file() and not path.is_symlink(), name
        if name != 'sidecar.py': assert sha(path) == expected, name
    output.mkdir(parents=True)
    staged = output / 'source'
    harness = output / 'harness'
    staged.mkdir()
    harness.mkdir()
    for name in pins: shutil.copyfile(source / name, staged / name)
    for name in ('run.py', 'test_tracker_retention.py', 'stdio_boundary.py', 'baseline-pins.json'):
        shutil.copyfile(HERE / name, harness / name)
    receipts = []
    for mode in (('regressions', 'stdio') if args.only == 'all' else (args.only,)):
        root = output / mode
        root.mkdir()
        for name in ('home', 'profile', 'tmp'): (root / name).mkdir()
        env = {'HOME': str(root / 'home'), 'HERMES_HOME': str(root / 'profile'), 'TMPDIR': str(root / 'tmp'), 'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'ATLAS_TEST_SOURCE': str(staged), 'ATLAS_TEST_OUTPUT': str(root)}
        command = [sys.executable, '-B', str(harness / ('run.py' if mode == 'regressions' else 'stdio_boundary.py')), 'worker' if mode == 'regressions' else 'test']
        proc = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=240)
        (root / 'stdout.log').write_text(proc.stdout)
        (root / 'stderr.log').write_text(proc.stderr)
        receipts.append({'mode': mode, 'command': command, 'cwd': str(root), 'environment': env, 'exit_code': proc.returncode, 'stdout_sha256': sha(root / 'stdout.log'), 'stderr_sha256': sha(root / 'stderr.log')})
        print(mode, 'exit', proc.returncode)
        print(proc.stdout)
        print(proc.stderr)
    receipt = {'invocation': [sys.executable, *sys.argv], 'source_directory': str(source), 'source_sha256': sha(staged / 'sidecar.py'), 'closure': {name: sha(staged / name) for name in pins}, 'harness': {name: sha(harness / name) for name in ('run.py', 'test_tracker_retention.py', 'stdio_boundary.py', 'baseline-pins.json')}, 'dependencies': versions, 'runs': receipts, 'successful': all(r['exit_code'] == 0 for r in receipts)}
    save(output / 'receipt.json', receipt)
    return 0 if receipt['successful'] else 1

if __name__ == '__main__':
    sys.exit(worker() if sys.argv[1:] == ['worker'] else main())
