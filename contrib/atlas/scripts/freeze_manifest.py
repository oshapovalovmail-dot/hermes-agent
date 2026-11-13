#!/usr/bin/env python3
"""Freeze package hashes and scan the publishable source tree, never private state."""
from pathlib import Path
import hashlib,json,re,sys,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from atlas_dist.bundle import digest,payload_manifest
P=Path(__file__).resolve().parents[1]
payload=payload_manifest(P)
provenance=P/'manifests/source-provenance.json';source=json.loads(provenance.read_text())
for row in source['files']:
    path=P/row['target']
    if path.is_file() and row.get('carrier')!='unified diff':
        row['distributed_sha256']=digest(path);row['modified']=row['distributed_sha256']!=row['source_sha256']
source['distribution_adjustments']=['trusted operator root/tool/scope binding; no collector-host defaults','owner ID from installation-owned control/operator.json','profile-specific skill visibility made shared/global','neutral personal operational read procedures','source-qualified staff/Tasha provider integration; explicit per-installation activation barrier remains','read bundle dependency/backend/sidecar hierarchical repinning','sandbox curated skills copied into immutable image, no host mount']
provenance.write_text(json.dumps(source,ensure_ascii=False,indent=2)+'\n')
patterns={'host_username':re.compile(r'/Users/[A-Za-z0-9_.-]+|(?<!/)/home/[a-z][a-z0-9_.-]+/(?:\.tokens|\.hermes|\.config)'),
          'owner_literal':re.compile(r"OWNER\s*=\s*['\"][0-9]+"),
          'secret_value':re.compile(r'sk-[A-Za-z0-9]{20,}|[0-9]{8,12}:[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')}
findings=[];scanned=0;archive_members=0
allowed={}
for path in sorted(P.rglob('*')):
    if path.is_symlink():findings.append({'file':str(path.relative_to(P)),'kind':'symlink','accepted':False});continue
    if not path.is_file() or '__pycache__' in path.parts:continue
    rel=str(path.relative_to(P))
    if path.name in ('package.json','package.sha256','security-scan.json') and path.parent==P/'manifests':continue
    if any(part in ('.git','.venv','node_modules','__pycache__') for part in path.relative_to(P).parts) or path.name in ('.env','auth.json','state.db','history.db'):
        findings.append({'file':rel,'kind':'forbidden_state','accepted':False})
    content=[]
    try:content.append(('',path.read_text()))
    except UnicodeError:pass
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.filename.startswith('docProps/') and info.file_size<100000:
                    content.append((info.filename,archive.read(info).decode('utf-8','replace')));archive_members+=1
    scanned+=1
    for member,text in content:
        for kind,pattern in patterns.items():
            if pattern.search(text):findings.append({'file':rel,'member':member or None,'kind':kind,'accepted':(rel,kind) in allowed,'reason':allowed.get((rel,kind))})
scan={'files_scanned':scanned,'embedded_office_property_parts_scanned':archive_members,'findings':findings,'pass':all(x['accepted'] for x in findings),'scope':'publishable source only; no private input stores scanned','not_a_guarantee':'Pattern scan and bounded Office metadata review do not establish absence of all possible sensitive text.'}
(P/'manifests/security-scan.json').write_text(json.dumps(scan,indent=2)+'\n')
files={str(p.relative_to(P)):digest(p) for p in sorted(P.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p not in (P/'manifests/package.json',P/'manifests/package.sha256')}
package={'files':files,'file_count':len(files),'bytes':sum((P/name).stat().st_size for name in files),'skill_count':payload['skills'],'payload_file_count':len(payload['files']),'state':'source-qualified; native FIFO/model/MCP validated locally; production activation is installation-specific and disabled by default'}
(P/'manifests/package.json').write_text(json.dumps(package,indent=2)+'\n')
(P/'manifests/package.sha256').write_text(digest(P/'manifests/package.json')+'  manifests/package.json\n')
print(json.dumps({'package_files':len(files),'bytes':package['bytes'],'skills':payload['skills'],'security_scan_pass':scan['pass'],'findings':findings,'package_manifest_sha256':digest(P/'manifests/package.json')},indent=2))
if not scan['pass']:raise SystemExit(1)
