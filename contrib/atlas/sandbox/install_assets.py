import hashlib
import json
from pathlib import Path
import shutil
import tarfile

assets = json.loads(Path('/build/assets.json').read_text())
assert hashlib.sha256(Path('/build/node.tar.xz').read_bytes()).hexdigest() == assets['node']['sha256']
with tarfile.open('/build/node.tar.xz', 'r:xz') as archive:
    prefix = 'node-' + assets['node']['version'] + '-linux-x64/'
    for source, target in [('bin/node', '/usr/local/bin/node'), ('LICENSE', '/opt/atlas/licenses/Node-LICENSE')]:
        content = archive.extractfile(prefix + source).read()
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o555 if source == 'bin/node' else 0o444)
for entry in assets['fonts']:
    data = Path('/build', entry['filename']).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry['sha256']
    dest = Path('/usr/share/fonts/truetype/noto') if entry['filename'].endswith('.ttf') else Path('/opt/atlas/licenses')
    dest.mkdir(parents=True, exist_ok=True)
    (dest / entry['filename']).write_bytes(data)
for name in ['bootstrap.py', 'requirements.lock', 'assets.json']:
    shutil.copyfile('/build/' + name, '/opt/atlas/' + name)
Path('/opt/atlas/bin').mkdir(exist_ok=True)
shutil.copyfile('/build/atlas-python', '/opt/atlas/bin/python3')
Path('/opt/atlas/bin/python3').chmod(0o555)
for path in ['/root', '/home', '/usr/local/lib/python3.12/site-packages', '/usr/local/lib/python3.12/ensurepip']:
    shutil.rmtree(path, ignore_errors=True)
for path in Path('/usr/local/bin').glob('pip*'):
    path.unlink()
Path('/work').mkdir(exist_ok=True)
Path('/work').chmod(0o777)
Path('/opt/atlas/VERSION').write_text('atlas-document-sandbox/1\n')
shutil.rmtree('/build')
