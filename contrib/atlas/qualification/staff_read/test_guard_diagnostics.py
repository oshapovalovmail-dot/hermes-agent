"""Offline source-only guard regression; identity seam is a fixture, not admission proof."""
import ast
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import types
import unittest

import shutil
import tempfile
SOURCE = Path(__file__).resolve().parents[2]
ATLAS = Path(os.environ['ATLAS_TEST_INSTALLATION']).resolve()
ROOT = Path(tempfile.mkdtemp(prefix='atlas-staff-guard-', dir=os.environ['TMPDIR']))
for part in ('baseline/home/plugins/qyp_guard', 'overlay/home/plugins/qyp_guard', 'fixture/bundle'):
    (ROOT / part).mkdir(parents=True)
shutil.copyfile(SOURCE / 'qualification/staff_read/baseline_init.py', ROOT / 'baseline/home/plugins/qyp_guard/__init__.py')
shutil.copyfile(SOURCE / 'qualification/staff_read/baseline_policy.py', ROOT / 'baseline/home/plugins/qyp_guard/policy.py')
shutil.copyfile(SOURCE / 'payload/home/plugins/qyp_guard/__init__.py', ROOT / 'overlay/home/plugins/qyp_guard/__init__.py')
shutil.copyfile(SOURCE / 'qualification/staff_read/bundle-pins.json', ROOT / 'fixture/bundle-pins.json')
for name, pin in json.loads((ROOT / 'fixture/bundle-pins.json').read_text()).items():
    data = (ATLAS / 'services/atlas-read' / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == pin, 'approved immutable bundle required'
    (ROOT / 'fixture/bundle' / name).write_bytes(data)
os.environ.setdefault('GUARD_CANDIDATE', 'overlay')
# Only the native published Bundle/DTO dependencies are imported; no gateway startup.
sys.path.insert(0, str(ATLAS / 'runtime'))
DENIAL = 'Capability outside reviewed principal ceiling.'
LOCAL = ('Local preflight input/contract rejection before upstream. '
         'Re-read service_catalog and correct exact field names and values; '
         'this is not an upstream ACL denial.')
OP = 'staff_api_mcp.person-full-info'
READ = 'mcp__atlas_read__service_read'
CAT = 'mcp__atlas_read__service_catalog'
PINS = json.loads((ROOT / 'fixture/bundle-pins.json').read_text())


def offline_audit(event, args):
    if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.connect',
                 'socket.connect_ex', 'socket.bind', 'socket.getaddrinfo'):
        raise AssertionError('Offline fixture forbids native/network dispatch')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).absolute()
        if any(part.lower() in ('auth.json', 'credentials.json', 'config.yaml', 'config.yml', '.env', '.netrc') for part in path.parts):
            raise AssertionError('Fixture forbids credential/config reads')
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        if writing and not path.is_relative_to(ROOT):
            raise AssertionError('Fixture forbids writes outside owned root')


sys.addaudithook(offline_audit)


def load_guard(label, candidate=False):
    base = ROOT / ('overlay' if candidate else 'baseline') / 'home/plugins/qyp_guard'
    spec = importlib.util.spec_from_file_location('fixture_guard_' + label, base / '__init__.py',
        submodule_search_locations=[str(base), str(ROOT / 'baseline/home/plugins/qyp_guard'), str(ATLAS / 'home/plugins/qyp_guard')])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_guard('base')
CANDIDATE = load_guard('candidate', os.environ.get('GUARD_CANDIDATE') == 'overlay')
from atlas_work_read.bundle import Bundle


def entry(method, **changes):
    return dict(service='atlas_read', method=method, access='read', reviewed=True, **changes)


def configuration():
    return {'typed_work_read': {'bundle_root': str(ROOT / 'fixture/bundle'), 'bundle_pins': PINS.copy()},
            'reviewed_read_tools': {READ: entry('service_read'), CAT: entry('service_catalog')},
            'reviewed_mutation_tools': {}, 'reviewed_trace_tools': {}}


def args(fields='login,name,department_group'):
    return {'operation': OP, 'arguments': {'search_by': {'chief.login': 'ovshapovalov'},
            'fields_to_return': fields}, 'max_chars': 20000}


def service(module, config=None, role='owner', unauthorized=False):
    # Avoid Service.__init__: constructing a Broker/admission store is out of scope.
    # The only replaced behavior is the trusted identity result at this boundary.
    guard = module.Service.__new__(module.Service)
    settings = configuration() if config is None else config
    guard.ctx = types.SimpleNamespace(get_config=lambda key, default=None: settings.get(key, default))
    guard._trace_bindings = {}
    broker = sys.modules[module.__name__ + '.broker']
    who = broker.Principal(broker.OWNER if role == 'owner' else 'fixture-member',
        'fixture-session', role, 'fixture-profile', 'fixture-chat', '')
    def identity():
        if unauthorized:
            raise PermissionError('bound_native_admission_required')
        return who
    guard.authorized_principal = identity
    return guard


class GuardRegression(unittest.TestCase):
    def test_real_invalid_field_diagnostic(self):
        bad = args('login,name,department')
        original = copy.deepcopy(bad)
        bundle = Bundle(str(ROOT / 'fixture/bundle'), PINS)
        schema = bundle.operations()[OP]['inputSchema']['properties']['fields_to_return']
        from jsonschema import Draft202012Validator
        self.assertFalse(Draft202012Validator(schema).is_valid('login,name,department'))
        self.assertTrue(Draft202012Validator(schema).is_valid('login,name,department_group'))
        self.assertFalse(bundle.module.service_input_valid('service_read', bad))
        self.assertEqual(service(BASE).guard_tool(READ, bad), {'action': 'block', 'message': DENIAL})
        self.assertEqual(service(CANDIDATE).guard_tool(READ, bad), {'action': 'block', 'message': LOCAL})
        self.assertEqual(bad, original)

    def test_catalog_rejection_diagnostic(self):
        self.assertEqual(service(CANDIDATE).guard_tool(CAT, {'service': 'not-a-published-service'}),
                         {'action': 'block', 'message': LOCAL})

    def test_decision_matrix_identical(self):
        cases = [
            ('valid-chief-read', READ, args(), {}, False, True),
            ('valid-login-name', READ, args('login,name'), {}, False, True),
            ('valid-catalog', CAT, {'operation': OP}, {}, False, True),
            ('invalid-department', READ, args('login,name,department'), {}, False, False),
            ('invalid-case', READ, args('login,Name,department_group'), {}, False, False),
            ('invalid-whitespace', READ, args('login,name, department_group'), {}, False, False),
            ('missing-scope', READ, {'operation': OP, 'arguments': {'search_by': {}, 'fields_to_return': 'login'}}, {}, False, False),
            ('invalid-outer', READ, {**args(), 'unexpected': 'secret-sentinel'}, {}, False, False),
            ('invalid-catalog', CAT, {'operation': OP, 'service': 'wrong'}, {}, False, False),
            ('non-dict', READ, ['secret-sentinel'], {}, False, False),
            ('unauthorized', READ, args(), {}, True, False),
            ('unknown', 'mcp__atlas_read__unknown', args(), {}, False, False),
            ('mutating', 'mcp__tracker__update_issue', {'issue': 'FIXTURE-1'}, {}, False, False),
            ('shell', 'terminal', {'command': 'secret-sentinel'}, {}, False, False),
            ('unreviewed', READ, args(), {'unreviewed': True}, False, False),
            ('false-read-mutation', READ, args(), {'mutation_entry': True}, False, False),
            ('bad-pins', READ, args(), {'bad_pin': True}, False, False),
            ('missing-pins', READ, args(), {'missing_pin': True}, False, False),
            ('invalid-config', READ, args(), {'invalid_config': True}, False, False),
        ]
        receipts = []
        for role in ('owner', 'member'):
            for name, tool, value, variants, unauthorized, expected in cases:
                with self.subTest(role=role, case=name):
                    config = configuration()
                    if variants.get('unreviewed'): config['reviewed_read_tools'][READ]['reviewed'] = False
                    if variants.get('mutation_entry'): config['reviewed_read_tools'][READ]['access'] = 'mutation'
                    if variants.get('bad_pin'): config['typed_work_read']['bundle_pins']['sidecar.py'] = '0' * 64
                    if variants.get('missing_pin'): config['typed_work_read']['bundle_pins'].pop('select_parser.py')
                    if variants.get('invalid_config'): config['typed_work_read']['unexpected'] = True
                    before_args = copy.deepcopy(value)
                    old = service(BASE, config, role, unauthorized).guard_tool(tool, value)
                    new = service(CANDIDATE, config, role, unauthorized).guard_tool(tool, value)
                    self.assertEqual(old is None, expected)
                    self.assertEqual(new is None, expected)
                    self.assertEqual(old is None, new is None)
                    self.assertEqual(value, before_args)
                    if name in ('unauthorized', 'unknown', 'mutating', 'shell', 'unreviewed', 'false-read-mutation'):
                        self.assertEqual(old, new)
                    self.assertNotIn('secret-sentinel', json.dumps(new))
                    receipts.append({'role': role, 'case': name, 'before': old, 'after': new, 'allow': expected})
        (ROOT / ('green-matrix.json' if os.environ.get('GUARD_CANDIDATE') == 'overlay' else 'red-matrix.json')).write_text(json.dumps(receipts, indent=2) + '\n')

    def test_typed_contract_full_validation(self):
        bundle = Bundle(str(ROOT / 'fixture/bundle'), PINS)
        asyncio.run(bundle.validate('service_read', args()))
        from atlas_bridge.contract import Denied
        with self.assertRaises(Denied):
            asyncio.run(bundle.validate('service_read', args('login,name,department')))

    def test_invalid_pinned_schema_remains_blocked(self):
        # A corrupt but coherently repinned contract is NOT a valid-input read.
        root = ROOT / 'fixture/invalid-schema-bundle'
        root.mkdir(exist_ok=True)
        for name in PINS:
            (root / name).write_bytes((ROOT / 'fixture/bundle' / name).read_bytes())
        manifest = json.loads((root / 'work_services_manifest.json').read_text())
        manifest[OP]['inputSchema']['type'] = 'invalid-schema-sentinel'
        (root / 'work_services_manifest.json').write_text(json.dumps(manifest))
        manifest_sha = hashlib.sha256((root / 'work_services_manifest.json').read_bytes()).hexdigest()
        backend = (root / 'work_services_backend.py').read_text().replace(PINS['work_services_manifest.json'], manifest_sha)
        (root / 'work_services_backend.py').write_text(backend)
        backend_sha = hashlib.sha256((root / 'work_services_backend.py').read_bytes()).hexdigest()
        sidecar = (root / 'sidecar.py').read_text().replace(PINS['work_services_manifest.json'], manifest_sha).replace(PINS['work_services_backend.py'], backend_sha)
        (root / 'sidecar.py').write_text(sidecar)
        pins = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in PINS}
        config = configuration()
        config['typed_work_read'] = {'bundle_root': str(root), 'bundle_pins': pins}
        for module in (BASE, CANDIDATE):
            self.assertFalse(service(module, config).guard_tool(READ, args()) is None)
        from atlas_bridge.contract import Denied
        with self.assertRaises(Denied):
            asyncio.run(Bundle(str(root), pins).validate('service_read', args()))

    def test_guard_predicates_and_policy_unchanged(self):
        baseline = ast.parse((ROOT / 'baseline/home/plugins/qyp_guard/__init__.py').read_text())
        path = ROOT / 'overlay/home/plugins/qyp_guard/__init__.py'
        candidate = ast.parse(path.read_text() if path.exists() else (ROOT / 'baseline/home/plugins/qyp_guard/__init__.py').read_text())
        def guard(tree):
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Service')
            return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'guard_tool')
        old, new = guard(baseline), guard(candidate)
        # All original admission/allow/grant statements and exception handler remain.
        old_try, new_try = old.body[0], new.body[0]
        self.assertEqual(ast.dump(old_try.handlers[0]), ast.dump(new_try.handlers[0]))
        self.assertEqual(ast.dump(old.body[-1]), ast.dump(new.body[-1]))
        self.assertEqual([ast.dump(n) for n in old_try.body], [ast.dump(n) for n in new_try.body[:len(old_try.body)]])
        # No other plugin functions, registration, schemas or constants change.
        guard(baseline).body = []
        guard(candidate).body = []
        self.assertEqual(ast.dump(baseline), ast.dump(candidate))

    def test_upstream_acl_not_reclassified(self):
        # Guard has no upstream result channel. Do not synthesize a genuine ACL receipt.
        # Preserve actual backend/sidecar exception + serializer sources byte-for-byte.
        self.assertIsNone(service(CANDIDATE).guard_tool(READ, args()))
        for name, pin in PINS.items():
            self.assertEqual(hashlib.sha256((ROOT / 'fixture/bundle' / name).read_bytes()).hexdigest(), pin)
        old = ast.parse((ROOT / 'baseline/home/plugins/qyp_guard/policy.py').read_text())
        candidate_path = ROOT / 'overlay/home/plugins/qyp_guard/policy.py'
        new = ast.parse(candidate_path.read_text() if candidate_path.exists() else (ROOT / 'baseline/home/plugins/qyp_guard/policy.py').read_text())
        self.assertEqual(ast.dump(old), ast.dump(new))

    def test_diagnostic_no_argument_or_exception_echo(self):
        bad = args('login,name,department,credential-sentinel')
        for value in (bad, {'secret-sentinel': 'raw-credential-sentinel'}, ['secret-sentinel']):
            result = service(CANDIDATE).guard_tool(READ, value)
            self.assertEqual(result, {'action': 'block', 'message': LOCAL})


if __name__ == '__main__':
    unittest.main(verbosity=2)
