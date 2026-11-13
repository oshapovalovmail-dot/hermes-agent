"""Real two-process native provisioning regression; explicit fixture bindings."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT = Path(os.environ.get('ATLAS_TEST_PROJECT', Path(__file__).resolve().parents[1])).resolve()
WORK = Path(os.environ.get('ATLAS_TEST_WORK', PROJECT.parent / 'receipts/consent-tests')).resolve()
CORE = Path(os.environ['ATLAS_TEST_CORE']).resolve()
sys.path.insert(0, str(PROJECT))
from atlas_dist import install as installer
APPROVED_SHA = '244e6cb783242c9c6e24b04d3279000681c510e521954eeb14fbab34b2c53d57'


def child(root, selector, barrier):
    helper = root / 'services/atlas-admin/native_profile_helper.py'
    sys.path.insert(0, str(helper.parent))
    spec = importlib.util.spec_from_file_location('native_helper', helper)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    approval = root / 'control/instruction-policy-approval.json'
    original_read = Path.read_text
    fault = os.environ.get('CONSENT_FAULT', '')
    once = False
    def scheduled_read(path, *args, **kwargs):
        nonlocal once
        text = original_read(path, *args, **kwargs)
        if path == approval and fault and not once:
            once = True
            current = json.loads(text)
            if fault == 'revoked': current['approved'] = False
            elif fault == 'hash-changed': current['sha256'] = '0' * 64
            elif fault == 'bad-homes': current['homes'] = ['foreign']
            elif fault == 'bad-provenance': current['provenance'] = []
            elif fault == 'merge': current['homes'].append(str(root / 'home/profiles/tg-77'))
            if fault in ('revoked', 'hash-changed', 'bad-homes', 'bad-provenance', 'merge'):
                path.write_text(json.dumps(current))
            elif fault == 'invalid-json': path.write_text('{')
            elif fault == 'approval-symlink':
                saved = path.with_name('saved.json')
                path.rename(saved)
                path.symlink_to(saved)
        if path == approval and barrier and not once:
            once = True
            (root / ('ready-' + selector)).write_text('ready')
            until = time.monotonic() + 20
            while len(list(root.glob('ready-*'))) < 2:
                if time.monotonic() > until:
                    raise TimeoutError('initial-read-only barrier')
                time.sleep(.005)
            if selector == '52':
                time.sleep(.2)
        return text
    Path.read_text = scheduled_read
    original_open = os.open
    truncations = []
    def observe_open(path, flags, *args, **kwargs):
        if Path(path) == approval and flags & os.O_TRUNC:
            truncations.append(str(path))
        return original_open(path, flags, *args, **kwargs)
    os.open = observe_open
    original_replace = os.replace
    if fault in ('replace-error', 'replace-crash', 'slow-replace'):
        def broken_replace(src, dst, *args, **kwargs):
            if Path(dst) == approval:
                if fault == 'replace-crash': os._exit(71)
                if fault == 'replace-error': raise OSError('injected pre-commit I/O error')
                time.sleep(.1)
            return original_replace(src, dst, *args, **kwargs)
        os.replace = broken_replace
    if fault == 'fsync-error':
        def broken_fsync(fd): raise OSError('injected file fsync error')
        os.fsync = broken_fsync
    template = json.loads((root / 'control/profile-template.json').read_text())
    template['_atlas_role_policy_soul'] = (root / 'control/SOUL.md').read_text()
    result = mod.provision(root / 'home', selector, template, {'enabled': False, 'workspace': 'fixture'})
    result.update(helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
                  helper_path=str(helper), approval_truncations=truncations)
    print(json.dumps(result))


class ConcurrentConsent(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='consent-', dir=WORK)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'installed'
        installer.install(PROJECT, self.root, '123456789', {})
        pins = json.loads((PROJECT / 'core/patched-files.json').read_text())
        for rel, sha in pins.items():
            self.assertEqual(hashlib.sha256((CORE / rel).read_bytes()).hexdigest(), sha, rel)
        (self.root / 'runtime').symlink_to(CORE, target_is_directory=True)
        raw = (PROJECT / 'templates/SOUL.md').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), APPROVED_SHA)
        installer.approve_policy(PROJECT, self.root, approved=True,
                                provenance='На проектный соул разрешаю; exact approved bytes; owned test only')
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root / 'home'),
                    'HERMES_HOME': str(self.root / 'home'), 'HERMES_RUNTIME_DIR': str(self.root / 'tools'),
                    'TMPDIR': str(WORK), 'PYTHONDONTWRITEBYTECODE': '1',
                    'ATLAS_TEST_PROJECT': str(PROJECT), 'ATLAS_TEST_WORK': str(WORK),
                    'ATLAS_TEST_CORE': str(CORE)}

    def spawn(self, uid, barrier=False):
        return subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--child',
                                 str(self.root), uid, str(int(barrier))], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_bootstrap_writer_uses_same_lock(self):
        import fcntl
        root = self.root.parent / 'bootstrap'
        installer.install(PROJECT, root, '123456789', {})
        lock = root / 'control/instruction-policy-approval.lock'
        with lock.open('w') as stream:
            lock.chmod(0o600)
            fcntl.flock(stream, fcntl.LOCK_EX)
            code = ('import sys; from pathlib import Path; sys.path.insert(0, ' + repr(str(PROJECT)) + '); '
                    'from atlas_dist.install import approve_policy; '
                    'Path(' + repr(str(root / 'ready')) + ').write_text("ready"); '
                    'approve_policy(Path(' + repr(str(PROJECT)) + '), Path(' + repr(str(root)) + '), '
                    'approved=True, provenance="На проектный соул разрешаю; owned fixture")')
            p = subprocess.Popen([sys.executable, '-B', '-c', code], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                until = time.monotonic() + 10
                while not (root / 'ready').exists():
                    if time.monotonic() > until: self.fail('bootstrap did not reach boundary')
                    time.sleep(.01)
                with self.assertRaises(subprocess.TimeoutExpired): p.wait(timeout=.4)
                self.assertFalse((root / 'control/instruction-policy-approval.json').exists())
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
                out, err = p.communicate(timeout=30)
            self.assertEqual(p.returncode, 0, err)
        installer.policy_preflight(root)

    def test_crash_before_replace_retains_valid_record_and_retry_merges_fresh(self):
        approval = self.root / 'control/instruction-policy-approval.json'
        before = approval.read_bytes()
        self.env['CONSENT_FAULT'] = 'replace-crash'
        p = self.spawn('61'); out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 71, (out, err))
        self.assertEqual(approval.read_bytes(), before)
        consent = json.loads(before); consent['homes'].append(str(self.root / 'home/profiles/tg-78'))
        approval.write_text(json.dumps(consent))
        self.env.pop('CONSENT_FAULT')
        p = self.spawn('61'); out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        self.assertIn(str(self.root / 'home/profiles/tg-78'), json.loads(approval.read_text())['homes'])
        installer.policy_preflight(self.root)

    def test_fsync_error_preserves_previous_record(self):
        approval = self.root / 'control/instruction-policy-approval.json'
        before = approval.read_bytes()
        self.env['CONSENT_FAULT'] = 'fsync-error'
        p = self.spawn('62'); out, err = p.communicate(timeout=30)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(approval.read_bytes(), before)
        self.assertFalse((self.root / 'home/profiles/tg-62').exists())
        self.assertEqual(list(approval.parent.glob('.instruction-policy-approval.*.tmp')), [])

    def test_lock_free_readers_see_only_complete_json(self):
        self.env['CONSENT_FAULT'] = 'slow-replace'
        processes = [self.spawn(str(uid)) for uid in (63, 64)]
        reads = 0
        until = time.monotonic() + 30
        try:
            while any(p.poll() is None for p in processes):
                json.loads((self.root / 'control/instruction-policy-approval.json').read_text())
                reads += 1
                if time.monotonic() > until: self.fail('reader/provisioners timed out')
                time.sleep(.001)
        finally:
            outcomes = [(p.communicate(timeout=30), p.returncode) for p in processes]
        self.assertGreater(reads, 10)
        self.assertEqual([x[1] for x in outcomes], [0, 0], outcomes)
        installer.policy_preflight(self.root)

    def test_existing_unrecorded_home_cannot_recover_by_inventing_consent(self):
        path = self.root / 'home/profiles/tg-65'; path.mkdir()
        p = self.spawn('65'); out, err = p.communicate(timeout=30)
        self.assertNotEqual(p.returncode, 0, (out, err))
        self.assertFalse((path / 'SOUL.md').exists())

    def test_fresh_merge_retains_other_writer(self):
        self.env['CONSENT_FAULT'] = 'merge'
        p = self.spawn('53'); out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        consent = json.loads((self.root / 'control/instruction-policy-approval.json').read_text())
        self.assertIn(str(self.root / 'home/profiles/tg-77'), consent['homes'])

    def test_concurrent_revocation_hash_or_record_change_denies_without_restoring_grant(self):
        approval = self.root / 'control/instruction-policy-approval.json'
        original = approval.read_bytes()
        for fault in ('revoked', 'hash-changed', 'bad-homes', 'bad-provenance', 'invalid-json', 'approval-symlink'):
            with self.subTest(fault=fault):
                if approval.is_symlink(): approval.unlink()
                approval.write_bytes(original)
                self.env['CONSENT_FAULT'] = fault
                p = self.spawn('54'); out, err = p.communicate(timeout=30)
                self.assertNotEqual(p.returncode, 0, (fault, out, err))
                self.assertFalse((self.root / 'home/profiles/tg-54').exists())
                if fault == 'revoked': self.assertFalse(json.loads(approval.read_text())['approved'])
                if fault == 'hash-changed': self.assertEqual(json.loads(approval.read_text())['sha256'], '0' * 64)

    def test_symlink_lock_denied_without_touching_target(self):
        sentinel = self.root / 'control/sentinel'; sentinel.write_text('untouched')
        lock = self.root / 'control/instruction-policy-approval.lock'
        if lock.exists(): lock.unlink()
        lock.symlink_to(sentinel)
        p = self.spawn('55'); out, err = p.communicate(timeout=30)
        self.assertNotEqual(p.returncode, 0, (out, err))
        self.assertEqual(sentinel.read_text(), 'untouched')
        self.assertFalse((self.root / 'home/profiles/tg-55').exists())

    def test_replace_error_preserves_previous_json_and_retry(self):
        approval = self.root / 'control/instruction-policy-approval.json'
        before = approval.read_bytes()
        self.env['CONSENT_FAULT'] = 'replace-error'
        p = self.spawn('56'); out, err = p.communicate(timeout=30)
        self.assertNotEqual(p.returncode, 0, (out, err))
        self.assertEqual(approval.read_bytes(), before)
        self.assertEqual(list(approval.parent.glob('.instruction-policy-approval.*.tmp')), [])
        self.env.pop('CONSENT_FAULT')
        p = self.spawn('56'); out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        installer.policy_preflight(self.root)

    def test_lock_held_by_other_process_blocks_only_consent_boundary(self):
        import fcntl
        lock = self.root / 'control/instruction-policy-approval.lock'
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            p = self.spawn('57')
            try:
                with self.assertRaises(subprocess.TimeoutExpired): p.wait(timeout=.4)
                self.assertFalse((self.root / 'home/profiles/tg-57').exists())
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                out, err = p.communicate(timeout=30)
            self.assertEqual(p.returncode, 0, err)
        finally: os.close(fd)

    def test_group_honcho_identity_and_private_memory_unchanged(self):
        p = self.spawn('tg-group-n10041-t7'); out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        home = Path(json.loads(out.splitlines()[-1])['home'])
        honcho = json.loads((home / 'honcho.json').read_text())
        self.assertEqual(honcho['peerName'], 'tg-group-n10041-t7')
        self.assertTrue(honcho['pinUserPeer']); self.assertTrue(honcho['pinPeerName'])
        self.assertEqual(honcho['userPeerAliases'], {})
        for name in ('MEMORY.md', 'USER.md'): self.assertEqual((home / 'memories' / name).read_bytes(), b'')
        installer.policy_preflight(self.root)

    def test_two_real_native_provisioners_retain_both_homes_and_preflight(self):
        ps = [(uid, self.spawn(uid, True)) for uid in ('51', '52')]
        outcomes = []
        for uid, p in ps:
            out, err = p.communicate(timeout=60)
            outcomes.append({'uid': uid, 'exit': p.returncode, 'stdout': out, 'stderr': err})
        approval = json.loads((self.root / 'control/instruction-policy-approval.json').read_text())
        missing = [str(self.root / 'home/profiles' / ('tg-' + uid)) for uid in ('51', '52')
                   if str(self.root / 'home/profiles' / ('tg-' + uid)) not in approval['homes']]
        try:
            installer.policy_preflight(self.root)
            preflight = 'PASS'
        except PermissionError as exc:
            preflight = str(exc)
        receipt = {'outcomes': outcomes, 'unrecorded_created_homes': missing,
                   'subsequent_policy_preflight': preflight,
                   'scheduling': 'initial approval read once per process, never lock/fresh reads',
                   'native_profiles_actual': True, 'core_pins': len(json.loads((PROJECT / 'core/patched-files.json').read_text()))}
        (WORK / 'concurrent-consent-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        self.assertEqual([x['exit'] for x in outcomes], [0, 0], outcomes)
        self.assertEqual(missing, [], receipt)
        self.assertEqual(preflight, 'PASS')
        for outcome in outcomes:
            result = json.loads(outcome['stdout'].splitlines()[-1])
            self.assertEqual(result['approval_truncations'], [])
            home = Path(result['home'])
            self.assertEqual((home / 'SOUL.md').read_bytes(), (PROJECT / 'templates/SOUL.md').read_bytes())
            for name in ('MEMORY.md', 'USER.md'):
                self.assertEqual((home / 'memories' / name).read_bytes(), b'')
            self.assertEqual(json.loads((home / 'honcho.json').read_text())['peerName'], result['profile'])
            from ruamel.yaml import YAML
            cfg = YAML(typ='safe').load((home / 'config.yaml').read_text())
            self.assertEqual(cfg['mcp_servers']['atlas_read']['cwd'], str(home))
            self.assertEqual(cfg['plugins']['entries']['qyp_guard']['settings']['reviewed_stdio_servers']['atlas_read']['cwd'], str(home))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(Path(sys.argv[2]), sys.argv[3], bool(int(sys.argv[4])))
    else:
        unittest.main()
