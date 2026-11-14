"""Issue-specific filter-only negative dispatch control using the same full imports."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

# The shared full-import fixture consumes source/report CLI bindings unchanged.
spec = importlib.util.spec_from_file_location('dispatch_fixture', Path(__file__).with_name('test_full_dispatch.py'))
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)

class FilterOnlyDispatch(unittest.TestCase):
    def test_filter_only_blank_denied_before_transport(self):
        for query in ('', ' ', '\t\r\n', '\u00a0\u2003'):
            args = {'query': query, 'vertical': 'arcanum',
                    'filters': {'arcanum.author': ['vasermakov'],
                                'arcanum.updated': {'from': '2026-11-09', 'to': '2026-11-15'}}}
            with self.subTest(boundary='service_input_valid', query=repr(query)):
                F.CALLS.clear()
                self.assertFalse(F.S.service_input_valid('service_read', {'operation': F.OP, 'arguments': args}))
                self.assertEqual(F.CALLS, [])
            for route in ('read', 'read_full', 'service'):
                with self.subTest(route=route, query=repr(query)):
                    answer = F.dispatch(route, args)
                    self.assertEqual(F.CALLS, [])
                    self.assertFalse(answer['ok'])
                    self.assertEqual(answer['code'], 'invalid_argument' if route == 'service' else 'INVALID_INPUT')

if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FilterOnlyDispatch))
    F.REPORT.write_text(json.dumps({'source': str(F.SOURCE), 'source_hashes': F.PINS,
        'test_sha256': F.hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'fixture_sha256': F.hashlib.sha256(Path(F.__file__).read_bytes()).hexdigest(),
        'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'dispatch_count': len(F.OBS), 'total_native_calls': sum(o['native_calls'] for o in F.OBS),
        'observations': F.OBS, 'success': result.wasSuccessful()}, ensure_ascii=False, indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
