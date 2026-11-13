#!/usr/bin/env python3
"""Prepare source-only sandbox context with checksum-admitted public assets.

Does not call Docker, change a daemon, or activate anything. Context is a NEW
operator-selected directory, never a live installation. Linux arm64 source pin.
"""
from pathlib import Path
import argparse,hashlib,json,shutil,urllib.request
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--context',required=True,type=Path);p.add_argument('--asset-cache',type=Path)
a=p.parse_args();project=Path(__file__).resolve().parents[1];dst=a.context.absolute()
if dst.exists() or dst.is_symlink() or not dst.parent.is_dir():raise SystemExit('new_context_required')
dst.mkdir(mode=0o700)
for name in ('Dockerfile','install_assets.py','bootstrap.py','atlas-python','assets.json','requirements.lock'):shutil.copyfile(project/'sandbox'/name,dst/name)
shutil.copytree(project/'payload/home/skills',dst/'skills',ignore=shutil.ignore_patterns('__pycache__'))
assets=json.loads((dst/'assets.json').read_text());rows=[]
for spec in [dict(assets['node'],target='node.tar.xz'),*[dict(x,target=x['filename']) for x in assets['fonts']]]:
    target=dst/spec['target'];cached=a.asset_cache/spec['target'] if a.asset_cache else None
    if cached and cached.is_file() and not cached.is_symlink():raw=cached.read_bytes()
    else:
        if not spec['url'].startswith('https://'):raise SystemExit('https_source_required')
        with urllib.request.urlopen(spec['url'],timeout=60) as response:raw=response.read(64*1024*1024+1)
    if len(raw)>64*1024*1024 or hashlib.sha256(raw).hexdigest()!=spec['sha256']:raise SystemExit('asset_integrity:'+spec['target'])
    target.write_bytes(raw);rows.append({'filename':spec['target'],'sha256':spec['sha256'],'bytes':len(raw)})
receipt={'context_prepared':True,'architecture':'linux/arm64','assets':rows,'skills':len(list((dst/'skills').rglob('SKILL.md'))),'image_built':False,'activated':False}
(dst/'context-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
