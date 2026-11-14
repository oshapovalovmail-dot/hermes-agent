"""Public hash chain, deny-default bindings and unchanged sidecar seam."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
READ = PROJECT/'payload/services/atlas-read'
BASE = json.loads((ROOT/'public-baseline.json').read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def assignment(source, name):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)

def outside_changed_seam(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SERVICE_BACKENDS' for t in node.targets):
            node.value = ast.Constant(None)
        if isinstance(node, ast.FunctionDef) and node.name == 'parse_pr':
            node.body = [ast.Pass()]
        if isinstance(node, ast.ClassDef) and node.name == 'ReadService':
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name == 'pr_read':
                    method.body = [ast.Pass()]
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()

class PublicPayloadTests(unittest.TestCase):
    def test_public_backend_manifest_pin(self):
        source = (READ/'work_services_backend.py').read_text()
        self.assertEqual(assignment(source, 'MANIFEST_SHA256'), digest(READ/'work_services_manifest.json'))
        for name in ('MCP', 'YT', 'GH', 'ARC', 'ARCANUM'):
            self.assertEqual(assignment(source, name), '/usr/bin/false')
        self.assertEqual(assignment(source, 'ARC_CWD'), '/nonexistent')

    def test_actual_public_service_and_extension_pin_chain(self):
        spec = importlib.util.spec_from_file_location('public_seam_sidecar', READ/'sidecar.py')
        sidecar = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sidecar)
        for name, pin in sidecar.SERVICE_BACKENDS.items():
            self.assertEqual(pin['sha256'], digest(READ/pin['file']))
            self.assertEqual(pin['catalog_sha256'], digest(READ/pin['catalog']))
            for dependency, expected in pin.get('dependencies', {}).items():
                self.assertEqual(expected, digest(READ/dependency))
            sidecar.load_service_backend(name)
        for pin in sidecar.EXTENDED_BACKENDS.values():
            self.assertEqual(pin['sha256'], digest(READ/pin['file']))
        self.assertEqual(sidecar.PAGING_SHA256, digest(READ/'read_paging.py'))

    def test_existing_sidecar_acl_bindings_other_pins_unchanged(self):
        source = (READ/'sidecar.py').read_text()
        self.assertEqual(outside_changed_seam(source), BASE['sidecar_outside_changed_seam_ast_sha256'])
        for name, value in BASE['sidecar_constants'].items():
            if name == 'SERVICE_BACKENDS':
                current = assignment(source, name)
                self.assertEqual(current['tracker_wiki'], value['tracker_wiki'])
                self.assertEqual(current['work_services']['dependencies'], value['work_services']['dependencies'])
            else:
                actual = assignment(source, name)
                self.assertEqual(list(actual) if isinstance(actual, tuple) else actual, value)

    def test_canonical_soul_exact_reviewed_bytes(self):
        self.assertEqual(digest(PROJECT/'templates/SOUL.md'), BASE['expected_soul_sha256'])

    def test_native_fixture_integrity(self):
        for name, expected in BASE['native_fixture'].items():
            self.assertEqual(digest(ROOT/'native_fixture'/name), expected)

if __name__ == '__main__':
    unittest.main(verbosity=2)
