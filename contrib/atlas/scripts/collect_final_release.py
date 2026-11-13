#!/usr/bin/env python3
"""Import a PARENT-REVIEWED source directory; never install or activate it."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from atlas_dist.bundle import collect,payload_manifest
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path);p.add_argument('--parent-validated',action='store_true',required=True);args=p.parse_args()
root=Path(__file__).resolve().parents[1]
receipt=collect(args.source,root/'payload/services/atlas-read')
(root/'manifests/read-source-import.json').write_text(json.dumps(receipt,indent=2)+'\n')
receipt['payload_files']=len(payload_manifest(root)['files'])
print(json.dumps(receipt,indent=2))
