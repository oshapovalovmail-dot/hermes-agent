"""Source-only review controls; never initialize a native Hermes home."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from atlas_dist import install as installer
from atlas_dist.bundle import portable_source

BLOCKED={'SOUL.md','AGENTS.md','CLAUDE.md','.git','__pycache__'}
def copy_core(root):
    core=Path(os.environ['ATLAS_TEST_CORE'])
    shutil.copytree(core,root/'runtime',ignore=lambda p,n:[x for x in n if x in BLOCKED])
    pins=json.loads((PROJECT/'core/patched-files.json').read_text())
    from atlas_dist.bundle import digest
    assert {n:digest(root/'runtime'/n) for n in pins}==pins

class ReviewRegressions(unittest.TestCase):
    def test_authorized_mac_paths_survive(self):
        trusted=installer.validate_trusted({'mcp':'/opt/homebrew/bin/mcp','arc_cwd':'/Users/'+'tester/checkout/alice','arc_roots':['alice']})
        text=portable_source("MCP = '/usr/bin/false'\nARC_CWD = '/nonexistent'\nARC_ROOTS = ()\n",trusted)
        self.assertIn(repr(trusted['mcp']),text)
        self.assertIn(repr(trusted['arc_cwd']),text)
        self.assertIn("('alice',)",text)

    def test_foreign_literals_still_denied(self):
        for text in ("OTHER = '"+'/Users/'+'collector/private'+"'\n", "# /opt/homebrew/collector\nMCP = '/usr/bin/false'\n"):
            with self.assertRaisesRegex(ValueError,'unreviewed_host_literal'):
                portable_source(text,{'mcp':'/opt/homebrew/bin/mcp'})

    def test_missing_policy_stops_before_initializing_import_or_call(self):
        with tempfile.TemporaryDirectory(dir=PROJECT.parent/'receipts') as tmp:
            root=Path(tmp)/'new';installer.install(PROJECT,root,'12345',{});copy_core(root)
            # The spy prevents any dynamic native import or subprocess. No policy file is created.
            with patch.object(installer,'_load',side_effect=AssertionError('initializing_import')) as load,patch.object(installer.subprocess,'run',side_effect=AssertionError('native_call')) as run:
                with self.assertRaisesRegex(PermissionError,'policy_missing'):
                    installer.check_install(root)
                load.assert_not_called();run.assert_not_called()
                with self.assertRaisesRegex(PermissionError,'policy_missing'):
                    installer.bootstrap_native(PROJECT,root,sys.executable)
                run.assert_not_called()

    def test_tamper_specific_with_real_core_before_policy(self):
        with tempfile.TemporaryDirectory(dir=PROJECT.parent/'receipts') as tmp:
            root=Path(tmp)/'new';installer.install(PROJECT,root,'12345',{});copy_core(root)
            target=root/'services/atlas-read/read_paging.py';target.write_text(target.read_text()+'\n# tampered\n')
            with patch.object(installer,'_load',side_effect=AssertionError('initializing_import')) as load:
                with self.assertRaisesRegex(PermissionError,'^read_bundle_hash_mismatch$'):installer.check_install(root)
                load.assert_not_called()

    def test_bound_later_launcher_fails_closed_before_actual_native_code(self):
        with tempfile.TemporaryDirectory(dir=PROJECT.parent/'receipts',prefix="quoted '$ root ") as tmp:
            root=Path(tmp)/'atlas';(root/'bin').mkdir(parents=True);copy_core(root)
            # Generate the exact pinned native launcher without executing its bootstrap.
            code='import sys;sys.path.insert(0,'+repr(str(root/'runtime'))+');from pathlib import Path;from hermes_cli._launchers import _launcher_script;print(_launcher_script("hermes",Path('+repr(str(root/'runtime'))+'),None))'
            env={'PATH':'/usr/bin:/bin','HOME':str(root),'TMPDIR':str(PROJECT.parent/'receipts'),'PYTHONDONTWRITEBYTECODE':'1'}
            proc=subprocess.run([sys.executable,'-I','-B','-c',code],env=env,capture_output=True,text=True,check=True)
            import shlex
            native=root/'bin/hermes';native.write_text('#!/bin/sh\nexec '+shlex.join([sys.executable,'-I','-B','-c',proc.stdout])+' "$@"\n');native.chmod(0o700)
            # ACP dispatch sentinel only: an unguarded launch cannot initialize Hermes.
            acp=root/'bin/hermes-acp';acp.write_text('#!/bin/sh\nexit 99\n');acp.chmod(0o700)
            installer.bind_native_launcher(root)
            acp_result=subprocess.run([str(acp),'--help'],env=env,capture_output=True,text=True)
            self.assertEqual(acp_result.returncode,78,'every exposed native launcher must fail closed')
            self.assertFalse((root/'bin/hermes-native').exists(),'unguarded native launcher must not be exposed in bin')
            for home in (None,str(root/'foreign')):
                trial=dict(env,HERMES_RUNTIME_DIR=str(root/'tools'))
                if home is not None:trial['HERMES_HOME']=home
                child=subprocess.run([str(native),'--version'],env=trial,capture_output=True,text=True)
                self.assertEqual(child.returncode,78,child.stderr)
                self.assertIn('atlas_launcher_binding_required',child.stderr)
                self.assertNotIn('Traceback',child.stderr)
            # Wrong runtime and profile selectors are also refused, before any native program.
            for extra in ({'HERMES_RUNTIME_DIR':str(root/'foreign')},{'HERMES_PROFILE':'foreign'}):
                trial=dict(env,HERMES_HOME=str(root/'home'),HERMES_RUNTIME_DIR=str(root/'tools'));trial.update(extra)
                child=subprocess.run([str(native),'--version'],env=trial,capture_output=True,text=True)
                self.assertEqual(child.returncode,78,child.stderr)
            for selector in ('--profile=foreign','-pforeign','--profile','-p'):
                trial=dict(env,HERMES_HOME=str(root/'home'),HERMES_RUNTIME_DIR=str(root/'tools'))
                child=subprocess.run([str(native),selector,'foreign','--version'],env=trial,capture_output=True,text=True)
                self.assertEqual(child.returncode,78,child.stderr)
            # Positive control is dispatch recording only, NOT native boot acceptance.
            backing=root/'control/native-launchers/hermes'
            recorder='import json,os,sys;print(json.dumps({"home":os.environ["HERMES_HOME"],"runtime":os.environ["HERMES_RUNTIME_DIR"],"args":sys.argv[1:]}))'
            backing.write_text('#!/bin/sh\nexec '+shlex.join([sys.executable,'-I','-B','-c',recorder])+' "$@"\n')
            trial=dict(env,HERMES_HOME=str(root/'home'),HERMES_RUNTIME_DIR=str(root/'tools'))
            literal='$(not-a-command); literal argument'
            child=subprocess.run([str(native),literal],env=trial,capture_output=True,text=True)
            self.assertEqual(child.returncode,0,child.stderr)
            self.assertEqual(json.loads(child.stdout),{'home':str(root/'home'),'runtime':str(root/'tools'),'args':[literal]})

    def test_declared_helpers_help(self):
        skill=PROJECT/'payload/home/skills/productivity/powerpoint'
        for name in ('thumbnail.py','office/unpack.py','office/soffice.py','office/pack.py'):
            with self.subTest(script=name):
                proc=subprocess.run([sys.executable,'-B',str(skill/'scripts'/name),'--help'],capture_output=True,text=True)
                self.assertEqual(proc.returncode,0,proc.stderr)

    def test_design_root_resolves_packaged_asset(self):
        skill=PROJECT/'payload/home/skills/creative/psiii-design'
        recipe=(skill/'references/pptx-local-build-and-visual-qa.md').read_text()
        self.assertIn("const ds = '/opt/atlas/skills/creative/psiii-design';",recipe)
        docker=(PROJECT/'sandbox/Dockerfile').read_text()
        self.assertIn('COPY --chmod=0555 skills /opt/atlas/skills',docker)
        self.assertTrue((skill/'templates/business-pptx/source.pptx').is_file())

if __name__=='__main__':unittest.main()
