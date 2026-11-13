#!/usr/bin/env python3
"""Causal native provision/PM/route regressions, without live ingress or services.

Run with a PM-built verification interpreter and a fresh installed source fixture.
The worker starts on that interpreter's bare base, then activates an owned native
PM selection. External eligibility proof is deliberately outside this boundary.
"""
from pathlib import Path
import argparse
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
import unittest


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(root, fixture):
    fixture.mkdir(mode=0o700)
    for name in ('home/profiles', 'control/admission', 'services/atlas-admin', 'os-home', 'scratch'):
        (fixture/name).mkdir(parents=True, exist_ok=True)
    policy = (root/'control/SOUL.md').read_bytes()
    consent = json.loads((root/'control/instruction-policy-approval.json').read_text())
    if (consent.get('approved') is not True or consent.get('scope') != 'native-home-initialization'
            or not consent.get('provenance') or hashlib.sha256(policy).hexdigest() != consent.get('sha256')):
        raise PermissionError('approved_fixture_policy_required')
    for name in ('home/SOUL.md', 'control/SOUL.md', 'control/admission/SOUL.md'):
        (fixture/name).write_bytes(policy)
    (fixture/'control/instruction-policy-approval.json').write_text(json.dumps({
        'approved': True, 'scope': 'native-home-initialization',
        'provenance': 'Explicit project-policy consent inherited for owned source regression only',
        'sha256': hashlib.sha256(policy).hexdigest(), 'homes': [str(fixture/'home')]}))
    (fixture/'control/admission/profile-template.json').write_text('{}')
    for name in ('native_profile_helper.py', 'instruction_consent.py'):
        shutil.copyfile(root/'services/atlas-admin'/name, fixture/'services/atlas-admin'/name)
    (fixture/'runtime').symlink_to(root/'runtime', target_is_directory=True)
    # Native PM validates that the selection is inside this home's generation tree.
    key = hashlib.sha256(str((root/'runtime').resolve()).encode()).hexdigest()[:16]
    state = fixture/'home/installs'/key
    venv = state/'environments/fixture/venv'
    (venv/'bin').mkdir(parents=True)
    (venv/'pyvenv.cfg').write_bytes((Path(sys.prefix)/'pyvenv.cfg').read_bytes())
    (venv/'bin/python').symlink_to(sys._base_executable)
    (venv/'lib').symlink_to(Path(sys.prefix)/'lib', target_is_directory=True)
    (state/'facts.json').write_text(json.dumps({'packages': {'venv': {'environment': str(venv)}}}))


def worker(args):
    root, fixture = args.root.resolve(), args.fixture.resolve()
    os.environ.update(HOME=str(fixture/'os-home'), HERMES_HOME=str(fixture/'home'), TMPDIR=str(fixture/'scratch'))
    sys.path.insert(0, str(root/'runtime'))
    if sys.prefix != sys.base_prefix:
        raise AssertionError('worker_must_start_on_bare_base')
    try:
        import ruamel.yaml  # noqa: F401
    except ImportError:
        pass
    else:
        raise AssertionError('bare_base_must_not_already_have_helper_dependencies')
    from pm.environments import activate_dependencies, runtime_facts_path, project_python
    activate_dependencies(root/'runtime')
    assert sys.prefix == sys.base_prefix
    package = types.ModuleType('qyp_guard')
    package.__path__ = [str(root/'home/plugins/qyp_guard')]
    sys.modules['qyp_guard'] = package
    source = args.source or root/'home/plugins/qyp_guard/admission.py'
    spec = importlib.util.spec_from_file_location('qyp_guard.admission', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build_staff_provider = lambda ctx: object()  # No eligibility claim in this cohort.
    from gateway import atlas_admission
    from gateway.profile_routing import ProfileRoute
    from gateway.session_ingress_context import _runtime_profile
    from hermes_state_runtime import RuntimeStoreError
    from hermes_cli.config import read_user_config_raw, atomic_config_replace

    class Context:
        def get_config(self, key, default=None):
            return {'admin_home': str(fixture/'home'), 'admission_control': str(fixture/'control/admission'),
                    'admin_helper': str(fixture/'services/atlas-admin/native_profile_helper.py')}.get(key, default)

        async def refresh_gateway_profiles(self):
            return {'served_profiles': ['tg-501', 'tg-group-n1009-t8']}

    entry = {'name': 'atlas-auto-tg-501', 'platform': 'telegram', 'chat_id': '501', 'profile': 'tg-501', 'user_id': '501'}
    initial = {**entry, 'name': 'atlas-tg-501'}
    binding = types.SimpleNamespace(profile='tg-501', chat_type='dm', user_id='501', chat_id='501', thread_id=None)

    def provision(routes, actor=binding):
        atomic_config_replace(fixture/'home/config.yaml', {'gateway': {'profile_routes': copy.deepcopy(routes)},
                                                          'unrelated': {'exact': ['kept', False, 71]}})
        atlas_admission._GATE = None
        asyncio.run(module.ensure_gate(Context()).provision(actor))
        config = read_user_config_raw(fixture/'home/config.yaml')
        assert config['unrelated'] == {'exact': ['kept', False, 71]}
        return config['gateway']['profile_routes']

    def resolve(routes):
        native = [ProfileRoute(**row) for row in routes]
        actor = types.SimpleNamespace(platform=types.SimpleNamespace(value='telegram'), scope_id=None,
                                      chat_id='501', thread_id=None, parent_chat_id=None, user_id='501', profile='tg-501')
        return _runtime_profile(types.SimpleNamespace(config=types.SimpleNamespace(profile_routes=native)),
                                actor, None, 'default', {}, False)

    class Routes(unittest.TestCase):
        def test_native_duplicate_is_the_cause(self):
            with self.assertRaises(RuntimeStoreError) as caught:
                resolve([initial, entry])
            self.assertEqual(str(caught.exception), 'admission_conflict')

        def test_initial_owner_becomes_unique_native_route(self):
            routes = provision([initial])
            self.assertEqual(resolve(routes), 'tg-501')
            self.assertEqual(routes, [entry])

        def test_existing_duplicate_pair_collapses(self):
            self.assertEqual(provision([initial, entry]), [entry])

        def test_three_equivalent_names_collapse(self):
            self.assertEqual(provision([initial, {**entry, 'name': 'third'}, entry]), [entry])

        def test_non_equivalent_fields_remain_exact(self):
            variants = [{'user_id': '502'}, {'chat_id': '502'}, {'thread_id': '8'}, {'guild_id': 'scope'},
                        {'profile': 'tg-502'}, {'bot_profile': 'other-bot'}, {'enabled': False}, {'enabled': True},
                        {'bot_profile': None}, {'user_id': 501}, {'condition': {'role': 'employee'}}, {'platform': 'discord'}]
            others = [{**initial, **value, 'name': 'keep-'+str(index)} for index, value in enumerate(variants)]
            self.assertEqual(provision([initial, *others, entry]), [*others, entry])

        def test_same_auto_name_upsert_is_retained(self):
            self.assertEqual(provision([{**entry, 'chat_id': 'stale'}]), [entry])

        def test_repeated_fresh_provision_is_idempotent(self):
            once = provision([initial, entry])
            twice = provision(once)
            self.assertEqual(once, twice)
            self.assertEqual(resolve(twice), 'tg-501')

        def test_other_target_tie_stays_fail_closed(self):
            routes = provision([initial, {**initial, 'name': 'other-target', 'profile': 'tg-502'}])
            with self.assertRaises(RuntimeStoreError):
                resolve(routes)

        def test_group_topic_preserves_other_scopes(self):
            actor = types.SimpleNamespace(profile='tg-group-n1009-t8', chat_type='group', chat_id='-1009', thread_id='8', user_id='501')
            group = {'name': 'atlas-auto-tg-group-n1009-t8', 'platform': 'telegram', 'chat_id': '-1009',
                     'profile': 'tg-group-n1009-t8', 'thread_id': '8'}
            other = {**group, 'name': 'other-topic', 'thread_id': '9'}
            self.assertEqual(provision([{**group, 'name': 'native-group'}, other], actor), [other, group])

        def test_control_template_remains_strict_json(self):
            provision([initial])
            self.assertEqual(json.loads((fixture/'control/admission/profile-template.json').read_text()), {})
            self.assertTrue(json.loads((fixture/'control/instruction-policy-approval.json').read_text())['approved'])

    class PMBoundary(unittest.TestCase):
        def test_actual_helper_boundary(self):
            expected = str(project_python(root/'runtime'))
            mode = args.worker
            if mode == 'bare-helper':
                proc = subprocess.run([sys.executable, '-B', str(fixture/'services/atlas-admin/native_profile_helper.py'),
                                       str(fixture/'home'), '501', str(fixture/'control/admission/profile-template.json')],
                                      env=closed_env(fixture), capture_output=True, text=True, timeout=60)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("No module named 'ruamel'", proc.stderr)
                return
            if mode == 'broken-selection':
                runtime_facts_path(root/'runtime').write_text('{')
            if mode == 'missing-interpreter':
                Path(expected).unlink()
            if mode == 'revoked-consent':
                path = fixture/'control/instruction-policy-approval.json'
                consent = json.loads(path.read_text())
                consent['approved'] = False
                path.write_text(json.dumps(consent))
            original = asyncio.create_subprocess_exec
            launches = []

            async def observed(*argv, **kwargs):
                self.assertEqual(set(kwargs['env']), {'PATH', 'HOME', 'HERMES_HOME', 'PYTHONDONTWRITEBYTECODE', 'TMPDIR'})
                self.assertEqual(tuple(argv[1:]), (str(fixture/'services/atlas-admin/native_profile_helper.py'),
                                                  str(fixture/'home'), '501', str(fixture/'control/admission/profile-template.json')))
                launches.append(argv[0])
                return await original(*argv, **kwargs)

            asyncio.create_subprocess_exec = observed
            try:
                if mode == 'positive':
                    provision([])
                    self.assertEqual(launches, [expected])
                    self.assertNotEqual(expected, sys.executable)
                    profile = fixture/'home/profiles/tg-501'
                    self.assertTrue((profile/'config.yaml').is_file())
                    self.assertEqual(digest(profile/'SOUL.md'), digest(fixture/'control/SOUL.md'))
                    consent = json.loads((fixture/'control/instruction-policy-approval.json').read_text())
                    self.assertIn(str(profile), consent['homes'])
                else:
                    with self.assertRaises((PermissionError, RuntimeError)):
                        provision([])
                    self.assertFalse((fixture/'home/profiles/tg-501').exists())
                    self.assertEqual(launches, [expected] if mode == 'revoked-consent' else [])
            finally:
                asyncio.create_subprocess_exec = original

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Routes if args.worker == 'routes' else PMBoundary)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'mode': args.worker, 'tests': result.testsRun, 'failures': len(result.failures),
                      'errors': len(result.errors), 'success': result.wasSuccessful(), 'source_sha256': digest(source),
                      'runtime': str(root/'runtime'), 'base_executable': sys.executable}))
    return 0 if result.wasSuccessful() and result.testsRun else 1


def closed_env(fixture):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(fixture/'os-home'), 'HERMES_HOME': str(fixture/'home'),
            'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(fixture/'scratch')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--source', type=Path, help='Test-only exact-source override for causal RED controls')
    parser.add_argument('--worker', choices=('routes', 'positive', 'broken-selection', 'missing-interpreter', 'revoked-consent', 'bare-helper'))
    parser.add_argument('--fixture', type=Path)
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    if not args.work or args.work.exists() or args.work.is_symlink():
        parser.error('new_work_directory_required')
    if not (Path(sys.prefix)/'pyvenv.cfg').is_file():
        parser.error('PM_built_verification_venv_required')
    work = args.work.absolute()
    work.mkdir(mode=0o700)
    rows = []
    for mode in ('routes', 'positive', 'broken-selection', 'missing-interpreter', 'revoked-consent', 'bare-helper'):
        fixture = work/mode
        prepare(args.root.resolve(), fixture)
        command = [sys._base_executable, '-B', str(Path(__file__).resolve()), '--root', str(args.root.resolve()),
                   '--worker', mode, '--fixture', str(fixture)]
        if args.source:
            command.extend(['--source', str(args.source.resolve())])
        proc = subprocess.run(command, env=closed_env(fixture), capture_output=True, text=True, timeout=180)
        (work/(mode+'.log')).write_text(proc.stdout+proc.stderr)
        try:
            row = json.loads(proc.stdout.splitlines()[-1])
        except (ValueError, IndexError):
            row = {'mode': mode, 'tests': 0, 'success': False, 'setup_failure': True}
        row['exit'] = proc.returncode
        rows.append(row)
    count = sum(row['tests'] for row in rows)
    receipt = {'interpreter': sys.executable, 'python_version': sys.version, 'rows': rows, 'tests': count,
               'success': count == 15 and all(row['success'] and row['exit'] == 0 for row in rows),
               'scope': 'Real provision callback, native PM helper selection, ProfileRoute and _runtime_profile only',
               'external_authentication': 'not exercised', 'live_acceptance': False, 'activation': False}
    (work/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))
    return 0 if receipt['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
