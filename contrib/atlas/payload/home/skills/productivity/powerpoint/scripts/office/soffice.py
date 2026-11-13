"""Run an installed LibreOffice with a fresh private profile; never install or shim it."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def run_soffice(args,**kwargs):
    executable=shutil.which('soffice')
    if not executable:
        raise RuntimeError('LibreOffice prerequisite missing: soffice is not installed')
    with tempfile.TemporaryDirectory(prefix='atlas-lo-') as profile:
        env=dict(os.environ,SAL_USE_VCLPLUGIN='svp')
        return subprocess.run([executable,'-env:UserInstallation='+Path(profile).as_uri(),*list(args)],env=env,**kwargs)


def main():
    if sys.argv[1:]==['--help']:
        print(__doc__+'\nUsage: soffice.py --headless --convert-to pdf input.pptx [LibreOffice arguments]')
        return 0
    try:return run_soffice(sys.argv[1:]).returncode
    except RuntimeError as error:
        print(str(error),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
