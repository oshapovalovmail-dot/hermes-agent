"""Closed source bundle importer and hierarchical code pin writer."""
from pathlib import Path, PurePosixPath
import ast
import hashlib
import json
import re

READ_FILES=('sidecar.py','tracker_wiki_backend.py','tracker_wiki_catalog.json','work_services_backend.py','work_services_manifest.json','read_paging.py','read_snapshot_store.py','datalens_backend.py','nirvana_backend.py','yt_backend.py','select_parser.py')
TOOL_CONSTANTS={'MCP_CLI':'mcp','MCP':'mcp','MCP_BINARY':'mcp','YT':'yt','YT_BINARY':'yt','GH':'gh','GH_CLI':'gh','ARC':'arc','ARC_CLI':'arc','ARCANUM':'arcanum','VH3':'vh3'}

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def assignments(text, values):
    """Replace only exact top-level literal assignment nodes, not arbitrary text."""
    lines=text.splitlines(keepends=True); edits=[]
    for node in ast.parse(text).body:
        if not isinstance(node,ast.Assign) or len(node.targets)!=1 or not isinstance(node.targets[0],ast.Name):continue
        name=node.targets[0].id
        if name not in values:continue
        replacement=name+' = '+repr(values[name])+'\n'
        edits.append((node.lineno-1,node.end_lineno,replacement))
    for start,end,value in sorted(edits,reverse=True):lines[start:end]=[value]
    return ''.join(lines)

def portable_source(text, trusted=None):
    trusted=trusted or {}
    values={key:trusted.get(tool,'/usr/bin/false') for key,tool in TOOL_CONSTANTS.items()}
    values.update(ARC_CWD=trusted.get('arc_cwd','/nonexistent'),ARC_ROOTS=tuple(trusted.get('arc_roots',())),GITHUB_REPOS=frozenset(trusted.get('github_repos',())))
    # Scrub only the reviewed binding nodes before checking collector residue.
    # Authorized values are inserted only after this check, not confused with it.
    residual=assignments(text,{key:None for key in values})
    if '/Users/' in residual or '/opt/homebrew/' in residual:raise ValueError('unreviewed_host_literal')
    return assignments(text,values)

def _literal(text,name):
    for node in ast.parse(text).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):return ast.literal_eval(node.value)
    raise ValueError('missing_pin:'+name)

def repin(directory):
    root=Path(directory)
    # Dependency -> backend -> public sidecar. The same catalog bytes are pinned
    # by both backend admission and sidecar integrity checks.
    for name,fields in {
        'tracker_wiki_backend.py':{'CATALOG_SHA256':digest(root/'tracker_wiki_catalog.json'),'STORE_SHA256':digest(root/'read_snapshot_store.py')},
        'read_paging.py':{'STORE_SHA256':digest(root/'read_snapshot_store.py')},
        'datalens_backend.py':{'STORE_SHA256':digest(root/'read_snapshot_store.py')},
        'work_services_backend.py':{'MANIFEST_SHA256':digest(root/'work_services_manifest.json'),'SELECT_PARSER_SHA256':digest(root/'select_parser.py')},
    }.items():
        path=root/name;path.write_text(assignments(path.read_text(),fields))
    path=root/'sidecar.py';text=path.read_text()
    extended=_literal(text,'EXTENDED_BACKENDS')
    for spec in extended.values():spec['sha256']=digest(root/spec['file'])
    service=_literal(text,'SERVICE_BACKENDS')
    for spec in service.values():
        spec['sha256']=digest(root/spec['file']);spec['catalog_sha256']=digest(root/spec['catalog'])
        for dep in spec.get('dependencies',{}):spec['dependencies'][dep]=digest(root/dep)
    text=assignments(text,{'EXTENDED_BACKENDS':extended,'SERVICE_BACKENDS':service,'PAGING_SHA256':digest(root/'read_paging.py')})
    path.write_text(text)
    return {name:digest(root/name) for name in READ_FILES}

def collect(source,target):
    source=Path(source);target=Path(target)
    if source.is_symlink() or not source.is_dir():raise ValueError('regular_validated_source_directory_required')
    rows={}
    # Validate the entire list before changing any target bytes.
    bodies={}
    for name in READ_FILES:
        path=source/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size>16_000_000:raise ValueError('source_regular_file_required:'+name)
        raw=path.read_bytes();rows[name]=hashlib.sha256(raw).hexdigest()
        if name.endswith('.py'):bodies[name]=portable_source(raw.decode()).encode()
        else:
            value=json.loads(raw)
            # Inventory provenance is descriptive, never an execution route.
            # Remove collector-machine executable paths, retain schemas verbatim.
            if isinstance(value,dict):
                for entry in value.get('sources',[]):
                    if isinstance(entry,dict) and isinstance(entry.get('command'),list) and entry['command'] and isinstance(entry['command'][0],str) and entry['command'][0].startswith('/Users/'):
                        entry['command'][0]='<operator-provided-native-mcp>'
            bodies[name]=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    target.mkdir(parents=True,exist_ok=True)
    for name,raw in bodies.items():(target/name).write_bytes(raw)
    return {'admitted_source_sha256':rows,'distributed_sha256':repin(target),'no_installation':True,'no_activation':True}

def payload_manifest(project):
    project=Path(project)
    files={str(p.relative_to(project)):digest(p) for p in sorted((project/'payload').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    result={'version':1,'files':files,'skills':len(list((project/'payload/home/skills').rglob('SKILL.md')))}
    path=project/'manifests/payload.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2)+'\n')
    return result
