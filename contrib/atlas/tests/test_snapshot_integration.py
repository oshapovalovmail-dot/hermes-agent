"""Distribution seams for the accepted unlimited snapshot implementation."""
import ast
import copy
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def literal(path, name):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


class SnapshotIntegrationTests(unittest.TestCase):
    def test_bundle_includes_store_and_repins_every_factory(self):
        from atlas_dist.bundle import READ_FILES, digest, repin
        self.assertIn('read_snapshot_store.py', READ_FILES)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'read'
            shutil.copytree(PROJECT / 'payload/services/atlas-read', root)
            store = root / 'read_snapshot_store.py'
            store.write_text(store.read_text() + '\n# Fixture-only digest change.\n')
            pins = repin(root)
            self.assertEqual(pins['read_snapshot_store.py'], digest(store))
            for filename in ('read_paging.py', 'tracker_wiki_backend.py', 'datalens_backend.py'):
                with self.subTest(filename=filename):
                    self.assertEqual(literal(root / filename, 'STORE_SHA256'), digest(store))
                    spec = importlib.util.spec_from_file_location('_repin_' + filename[:-3], root / filename)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    self.assertEqual(Path(module._store_module().__file__), store)
            self.assertEqual(literal(root / 'sidecar.py', 'PAGING_SHA256'), digest(root / 'read_paging.py'))
            extended = literal(root / 'sidecar.py', 'EXTENDED_BACKENDS')
            for value in extended.values():
                self.assertEqual(value['sha256'], digest(root / value['file']))

    def test_readiness_requires_and_verifies_snapshot_store(self):
        from atlas_dist.bundle import digest, repin
        path = PROJECT / 'payload/home/plugins/qyp_guard/readiness.py'
        tree = ast.parse(path.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'verify_read_bundle')
        namespace = {'Path': Path}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'read'
            shutil.copytree(PROJECT / 'payload/services/atlas-read', root)
            pins = repin(root)
            settings = {'reviewed_service_files': pins}
            namespace['verify_read_bundle'](root / 'sidecar.py', settings)
            without_store = dict(pins)
            without_store.pop('read_snapshot_store.py')
            with self.assertRaisesRegex(PermissionError, 'exact_read_bundle_required'):
                namespace['verify_read_bundle'](root / 'sidecar.py', {'reviewed_service_files': without_store})
            store = root / 'read_snapshot_store.py'
            store.write_text(store.read_text() + '\n# Fixture tamper.\n')
            self.assertNotEqual(digest(store), pins['read_snapshot_store.py'])
            with self.assertRaisesRegex(PermissionError, 'read_bundle_hash_mismatch'):
                namespace['verify_read_bundle'](root / 'sidecar.py', settings)

    def test_generator_selects_terra_medium_and_only_atlas_breaker_false(self):
        from atlas_dist.install import _config
        from atlas_dist.config_candidate import candidate_config
        cfg = _config(Path('/fixture/atlas'), '41', {}, {'sidecar.py': '0' * 64}, Path('/fixture/atlas/home'))
        self.assertEqual(cfg['model']['default'], 'gpt-6.1-terra')
        self.assertEqual(cfg['model']['provider'], 'openai-codex')
        self.assertEqual(cfg['agent']['reasoning_effort'], 'medium')
        self.assertEqual(cfg['agent']['gateway_timeout'], 86580)
        self.assertIsNone(cfg['max_concurrent_sessions'])
        self.assertIsNone(cfg['gateway']['max_concurrent_sessions'])
        self.assertIs(cfg['gateway']['home_channel_prompt'], False)
        self.assertIs(cfg['mcp_servers']['atlas_read']['circuit_breaker'], False)
        other = {'command': '/fixture/other', 'circuit_breaker': {'threshold': 7}}
        cfg['mcp_servers']['other'] = copy.deepcopy(other)
        cfg['mcp_servers']['atlas_read'].pop('circuit_breaker')
        changed = candidate_config(cfg, transport=False)
        self.assertEqual(changed['mcp_servers']['other'], other)
        self.assertIs(changed['mcp_servers']['atlas_read']['circuit_breaker'], False)
        self.assertNotIn('circuit_breaker', cfg['mcp_servers']['atlas_read'])


if __name__ == '__main__':
    unittest.main()
