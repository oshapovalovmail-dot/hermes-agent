"""Independent offline dispatch acceptance; full pinned source imports, transport fixture only."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import unittest

SOURCE = Path(sys.argv.pop(1)).resolve()
REPORT = Path(sys.argv.pop(1)).resolve()
ROOT = REPORT.parent / 'dispatch-isolated'
OP = 'intrasearch.search'
LEGACY = 'intrasearch.arcanum_search'
FILES = ('sidecar.py', 'tracker_wiki_backend.py', 'tracker_wiki_catalog.json',
         'work_services_backend.py', 'work_services_manifest.json', 'read_paging.py',
         'read_snapshot_store.py', 'datalens_backend.py', 'nirvana_backend.py',
         'yt_backend.py', 'select_parser.py')
PINS = {name: hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in FILES}
assert not any(k.startswith('HERMES_SESSION_') for k in os.environ)
for key in ('HOME', 'HERMES_HOME', 'TMPDIR'):
    assert Path(os.environ[key]).is_relative_to(ROOT)

spec = importlib.util.spec_from_file_location('reviewed_sidecar', SOURCE/'sidecar.py')
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)
B = S.load_service_backend('work_services')
assert Path(B.__file__).resolve() == SOURCE/'work_services_backend.py'
assert B.SELECT_PARSER_SHA256 == PINS['select_parser.py']
SERVICE = S.ReadService(tracker_api=object())
PAYLOAD = {'results': [{'id': 'fixture-pr-1', 'title': 'Проверка dispatch'}], 'has_more': False}
WIRE = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'content': [
    {'type': 'text', 'text': json.dumps(PAYLOAD, ensure_ascii=False)}], 'isError': False}}, ensure_ascii=False)
CALLS = []
OBS = []

def fake_native(argv, deadline):
    assert deadline > time.monotonic()
    CALLS.append(copy.deepcopy(argv))
    return WIRE.encode('utf-8')

# The only substituted production callable is the native process transport.
B.run_native = fake_native

def dispatch(route, args, operation=OP):
    before = copy.deepcopy(args)
    CALLS.clear()
    if route == 'service':
        answer = SERVICE.service_read(operation=operation, arguments=args)
    else:
        answer = getattr(B.Backend(), route)(operation=operation, arguments=args)
    OBS.append({'route': route, 'operation': operation, 'arguments': before,
                'native_calls': len(CALLS), 'argv': copy.deepcopy(CALLS),
                'ok': answer.get('ok'), 'code': answer.get('code')})
    assert args == before, 'caller input mutated'
    return answer

class FullDispatch(unittest.TestCase):
    def assert_success(self, route, answer):
        self.assertTrue(answer['ok'], answer)
        self.assertEqual(answer['code'], 'ok' if route == 'service' else 'OK')
        value = json.loads(answer['text'])
        if route == 'service':
            self.assertEqual(value, {'records': [{'path': [], 'value': PAYLOAD}]})
            self.assertTrue(answer['pagination']['capture_complete'])
            self.assertFalse(answer['pagination']['has_more'])
            self.assertLessEqual(S.page_wire_bytes(answer), 10000)
        else:
            self.assertEqual(value, PAYLOAD)
            if route == 'read_full': self.assertEqual(answer['_data'], PAYLOAD)

    def test_explicit_blank_denied_before_transport(self):
        for query in ('', ' ', '\t\r\n', '\u00a0\u2003'):
            for vertical in ('arcanum', 'wiki', 'doc', 'tracker', 'stackoverflow', 'nirvana', 'people'):
                args = {'query': query, 'vertical': vertical}
                with self.subTest(boundary='service_input_valid', query=repr(query), vertical=vertical):
                    CALLS.clear()
                    valid = S.service_input_valid('service_read', {'operation': OP, 'arguments': args})
                    self.assertEqual(len(CALLS), 0)
                    self.assertFalse(valid)
                for route in ('read', 'read_full', 'service'):
                    with self.subTest(route=route, query=repr(query), vertical=vertical):
                        answer = dispatch(route, args)
                        self.assertEqual(len(CALLS), 0, 'blank reached transport')
                        self.assertFalse(answer['ok'])
                        self.assertEqual(answer['code'], 'invalid_argument' if route == 'service' else 'INVALID_INPUT')

    def test_valid_full_filters_exact_argv_and_serializer(self):
        filters = {'arcanum.author': ['vasermakov'], 'arcanum.reviewer': ['reviewer'],
                   'arcanum.created': {'from': '2026-11-09', 'to': '2026-11-15'},
                   'arcanum.updated': {'from': '2026-11-09', 'to': '2026-11-15'},
                   'arcanum.closed': {'from': '2026-11-09', 'to': '2026-11-15'}}
        args = {'query': ' \tтекст vasermakov\n', 'vertical': 'arcanum', 'filters': filters}
        expected = [B.MCP, 'connect', 'intrasearch', '--tool', 'search', '--arg',
                    'filters:'+json.dumps(filters, ensure_ascii=False, separators=(',', ':')),
                    '--arg', 'page_size:20', '--arg', 'query: \tтекст vasermakov\n',
                    '--arg', 'rag_search:0', '--arg', 'vertical:arcanum', '--raw']
        self.assertTrue(S.service_input_valid('service_read', {'operation': OP, 'arguments': args}))
        for route in ('read', 'read_full', 'service'):
            with self.subTest(route=route):
                answer = dispatch(route, args)
                self.assertEqual(CALLS, [expected])
                self.assertEqual([x.encode('utf-8') for x in CALLS[0]], [x.encode('utf-8') for x in expected])
                self.assert_success(route, answer)

    def test_legacy_empty_whitespace_and_documented_operator_unchanged(self):
        for query in ('', ' \t\n', 's_author:"vasermakov" s_updated:"\'20261109\'..\'20261115\'"'):
            args = {'query': query}
            self.assertTrue(S.service_input_valid('service_read', {'operation': LEGACY, 'arguments': args}))
            for route in ('read', 'read_full', 'service'):
                with self.subTest(route=route, query=repr(query)):
                    answer = dispatch(route, args, LEGACY)
                    self.assertEqual(CALLS, [[B.MCP, 'connect', 'intrasearch', '--tool', 'arcanum_search',
                                             '--arg', 'page_size:20', '--arg', 'query:'+query, '--raw']])
                    self.assert_success(route, answer)

    def test_foreign_namespace_and_unknown_fields_denied(self):
        for extra, code in [({'filters': {'wiki.author': 'someone'}}, 'FORBIDDEN_SOURCE'),
                            ({'unknown': 'value'}, 'INVALID_INPUT'),
                            ({'setup_server_args': 'value'}, 'INVALID_INPUT')]:
            args = {'query': 'text', 'vertical': 'arcanum', **extra}
            self.assertFalse(S.service_input_valid('service_read', {'operation': OP, 'arguments': args}))
            for route in ('read', 'read_full', 'service'):
                with self.subTest(route=route, extra=extra):
                    answer = dispatch(route, args)
                    self.assertEqual(CALLS, [])
                    self.assertFalse(answer['ok'])
                    self.assertEqual(answer['code'], 'invalid_argument' if route == 'service' else code)

    def test_missing_vertical_contract_remains_denied(self):
        for query in ('', 'text'):
            args = {'query': query}
            self.assertFalse(S.service_input_valid('service_read', {'operation': OP, 'arguments': args}))
            for route in ('read', 'read_full', 'service'):
                with self.subTest(route=route, query=query):
                    answer = dispatch(route, args)
                    self.assertEqual(CALLS, [])
                    self.assertFalse(answer['ok'])

    def test_guidance_in_real_manifest_and_catalog(self):
        CALLS.clear()
        entry = S.service_manifest()[OP]
        self.assertEqual(entry['inputSchema'], B.PUBLIC_ARGUMENT_SCHEMAS[OP])
        catalog = SERVICE.service_catalog(operation=OP, max_chars=48000)
        pages = []
        while True:
            self.assertTrue(catalog['ok'], catalog)
            pages.append(json.loads(catalog['text']))
            cursor = catalog['pagination']['cursor']
            if cursor is None: break
            catalog = SERVICE.service_catalog(operation=OP, cursor=cursor, max_chars=48000)
        rendered = json.dumps(pages, ensure_ascii=False)
        description = entry['inputSchema']['properties']['query']['description']
        for phrase in ('non-whitespace', 'intrasearch.arcanum_search', 'legacy operator',
                       'not explicit-search text substitutions', 'Do not invent query text',
                       's_author:', 's_reviewer:', 's_created:', 's_updated:', 's_closed:', 'YYYYMMDD'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, description)
                self.assertIn(phrase, rendered)
        self.assertEqual(CALLS, [])
        OBS.append({'catalog_pages': len(pages), 'catalog_ok': True, 'native_calls': 0})

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FullDispatch)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'source': str(SOURCE), 'source_hashes': PINS,
              'sidecar_module': S.__file__, 'backend_module': B.__file__,
              'test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'failure_ids': [t.id() for t, _ in result.failures],
              'error_details': [trace for _, trace in result.errors],
              'dispatch_count': sum('route' in o for o in OBS),
              'total_native_calls': sum(o.get('native_calls', 0) for o in OBS),
              'observations': OBS, 'success': result.wasSuccessful()}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
