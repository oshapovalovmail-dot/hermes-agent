import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

class DistributionTests(unittest.TestCase):
    def test_installer_exists(self):
        self.assertTrue((PROJECT / 'atlas_dist' / 'install.py').is_file(), 'guarded installer missing')

    def test_payload_is_portable_and_closed(self):
        from atlas_dist.install import verify_payload
        result = verify_payload(PROJECT)
        self.assertGreater(result['skills'], 10)
        self.assertGreater(result['files'], 100)

    def test_refuse_existing_root(self):
        from atlas_dist.install import install
        with tempfile.TemporaryDirectory(dir=PROJECT.parent / 'receipts') as tmp:
            root=Path(tmp)/'occupied';root.mkdir();(root/'sentinel').write_text('retain')
            with self.assertRaises((ValueError,FileExistsError)):
                install(PROJECT,root,'12345',{})
            self.assertEqual((root/'sentinel').read_text(),'retain')

    def test_refuse_symlink_root(self):
        from atlas_dist.install import install
        with tempfile.TemporaryDirectory(dir=PROJECT.parent / 'receipts') as tmp:
            target=Path(tmp)/'target';target.mkdir();root=Path(tmp)/'alias';root.symlink_to(target)
            with self.assertRaises((ValueError,FileExistsError)):
                install(PROJECT,root,'12345',{})
            self.assertEqual(list(target.iterdir()),[])

    def test_owner_id_validation(self):
        from atlas_dist.install import install
        for bad in ('0','-1','a','123;id','1\n2','01'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                install(PROJECT,PROJECT.parent/'receipts'/'never-created',bad,{})

    def test_fresh_install_policy_blocked_before_native_skills(self):
        from atlas_dist.install import install, check_install
        from test_review_regressions import copy_core
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=PROJECT.parent / 'receipts') as tmp:
            root=Path(tmp)/'new-root'
            receipt=install(PROJECT,root,'12345',{})
            self.assertFalse(receipt['activated']);copy_core(root)
            # This is a consent-denial check, NOT native skills/SDK acceptance.
            with patch('atlas_dist.install._load',side_effect=AssertionError('native_import')) as native:
                with self.assertRaisesRegex(PermissionError,'policy_missing'):check_install(root)
                native.assert_not_called()
            self.assertFalse((root/'home/auth.json').exists())
            self.assertFalse((root/'home/.env').exists())
            cfg=json.loads((root/'home/config.yaml').read_text())
            self.assertFalse(cfg['telegram']['enabled'])
            self.assertEqual(cfg['telegram']['allow_from'],['*'])
            self.assertTrue(cfg['telegram']['extra']['atlas_admission'])
            for carrier in (root/'home/config.yaml', root/'home/profiles/tg-12345/config.yaml', root/'control/profile-template.json'):
                generated = json.loads(carrier.read_text())
                self.assertIs(generated['gateway']['home_channel_prompt'], False)
                self.assertNotIn('home_channel', generated['telegram'])
            for p in (root/'home/plugins/qyp_guard').glob('*.py'):
                self.assertNotRegex(p.read_text(),r"OWNER\s*=\s*['\"][0-9]")

    def test_tampered_bundle_denied(self):
        from atlas_dist.install import install, check_install
        with tempfile.TemporaryDirectory(dir=PROJECT.parent / 'receipts') as tmp:
            root=Path(tmp)/'tampered';install(PROJECT,root,'12345',{})
            from test_review_regressions import copy_core
            copy_core(root)  # Actual 15-file hash-verified pinned prerequisite.
            path=root/'services/atlas-read/read_paging.py';path.write_text(path.read_text()+'\n# tampered\n')
            with self.assertRaisesRegex(PermissionError,'^read_bundle_hash_mismatch$'):
                check_install(root)

    def test_trusted_paths_not_model_input(self):
        from atlas_dist.install import validate_trusted
        with self.assertRaises(ValueError):validate_trusted({'mcp':'relative/mcp'})
        with self.assertRaises(ValueError):validate_trusted({'unknown':'/bin/true'})

    def test_manifest_paths_cannot_escape(self):
        from atlas_dist.install import safe_relative
        for s in ('../x','/x','a/../../x','a\\b',''):
            with self.subTest(path=s),self.assertRaises(ValueError):safe_relative(s)

    def test_parent_acceptance_barrier_remains_closed(self):
        from jsonschema import validate
        policy=json.loads((PROJECT/'templates/authorization-policy.json').read_text())
        validate(policy,json.loads((PROJECT/'schema/authorization-policy.schema.json').read_text()))
        self.assertFalse(policy['activation_permitted'])
        self.assertEqual(policy['provider']['mode'],'telegram_username_exact')

    def test_pending_staff_tasha_policy_denies_native_start(self):
        from atlas_dist.install import install,_load
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory(dir=PROJECT.parent/'receipts') as tmp:
            root=Path(tmp)/'pending';install(PROJECT,root,'12345',{})
            package='_atlas_pending_auth_test'
            _load(package,root/'home/plugins/qyp_guard/__init__.py',True)
            readiness=_load(package+'.readiness',root/'home/plugins/qyp_guard/readiness.py')
            service=SimpleNamespace(ctx=SimpleNamespace(get_config=lambda key,default=None:str(root/'control') if key=='admission_control' else default))
            with self.assertRaisesRegex(PermissionError,'parent_verified_staff_tasha'):
                readiness.verify_service(service,probe_backend=False)

    def test_native_commands_tools_before_extras(self):
        from atlas_dist.install import native_commands
        cmds=native_commands(Path('/safe/root'),Path('/trusted/python'))
        self.assertIn('--tools-only',cmds[0])
        self.assertIn('--without',cmds[0])
        self.assertIn('--extra',cmds[1])
        self.assertTrue(any('_launchers.py' in x for x in cmds[2]))

if __name__ == '__main__':unittest.main()
