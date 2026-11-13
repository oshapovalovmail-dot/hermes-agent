"""Portable admission seams: operator identity, policy consent and native config."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from atlas_dist import install as installer
class PortableUsername(unittest.TestCase):
    def test_operator_parameter_not_creator_bypass(self):
        with tempfile.TemporaryDirectory(dir=PROJECT.parent/'receipts') as tmp:
            root=Path(tmp)/'fresh';installer.install(PROJECT,root,'87654321',{})
            code="import sys;sys.path.insert(0,"+repr(str(root/'home/plugins'))+");from qyp_guard.broker import OWNER,Principal,Broker;assert OWNER=='87654321',OWNER; b=Broker("+repr(str(root/'sandbox'))+");b.workspace(Principal(OWNER,'x','owner'));b.workspace(Principal('305016744','x','member'));\ntry:b.workspace(Principal('305016744','x','owner'))\nexcept PermissionError:pass\nelse:raise AssertionError('creator bypass')"
            p=subprocess.run([sys.executable,'-I','-B','-c',code],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
    def test_approved_policy_needs_explicit_consent(self):
        with tempfile.TemporaryDirectory(dir=PROJECT.parent/'receipts') as tmp:
            root=Path(tmp)/'fresh';installer.install(PROJECT,root,'87654321',{})
            with self.assertRaisesRegex(PermissionError,'policy_missing'):installer.policy_preflight(root)
            installer.approve_policy(PROJECT,root,approved=True,provenance='На проектный соул разрешаю')
            installer.policy_preflight(root)
            self.assertEqual((root/'home/SOUL.md').read_bytes(),(PROJECT/'templates/SOUL.md').read_bytes())
            self.assertEqual((root/'control/SOUL.md').read_bytes(),(PROJECT/'templates/SOUL.md').read_bytes())
            (root/'home/SOUL.md').write_text('tampered')
            with self.assertRaisesRegex(PermissionError,'policy'):installer.policy_preflight(root)
    def test_native_username_config_and_activation_barrier(self):
        with tempfile.TemporaryDirectory(dir=PROJECT.parent/'receipts') as tmp:
            root=Path(tmp)/'fresh';installer.install(PROJECT,root,'87654321',{})
            cfg=json.loads((root/'home/config.yaml').read_text())
            self.assertFalse(cfg['telegram']['enabled'])
            self.assertTrue(cfg['telegram']['extra']['atlas_admission'])
            self.assertEqual(cfg['telegram']['group_policy'],'open')
            self.assertEqual(cfg['plugins']['entries']['qyp_guard']['settings']['tasha_bot_id'],793835103)
            policy=json.loads((root/'control/authorization-policy.json').read_text())
            self.assertFalse(policy['activation_permitted'])
            self.assertEqual(policy['provider']['mode'],'telegram_username_exact')
if __name__=='__main__':unittest.main()
