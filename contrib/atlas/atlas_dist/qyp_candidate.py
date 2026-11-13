"""Pure QYP supplier: no install, key loading, profile-history edits or activation.

Native PM-selected Python MUST be supplied by the operator's provisioning path.
Bridge authority/memory/CDP fields remain the independently composed A/C domain;
this function never fabricates the unanswered credential or readiness decision.
"""
from copy import deepcopy
from pathlib import Path
from .bundle import READ_FILES
from .install import _config
IMAGE='sha256:5bd7249518e6776ce415a55c6a043e8773526569fa9fa2053d012a80c7c7f27a'


def build_profiles(root,owner,pins,*,python):
    root=Path(root)
    if (not root.is_absolute() or '..' in root.parts or set(pins)!=set(READ_FILES)
            or not isinstance(python,str) or not Path(python).is_relative_to(root/'home/installs')
            or not python.endswith('/bin/python')):
        raise ValueError('exact_native_qyp_supplier_bindings_required')
    homes={'root':root/'home','profile':root/'home/profiles'/('tg-'+owner),'template':root/'control/template-stdio'}
    cfg=_config(root,owner,{'code_root':'/home/ovshapovalov/arcadia'},pins,homes['root'])
    settings=cfg['plugins']['entries']['qyp_guard']['settings']
    settings.update(sandbox_backend='podman',podman_image=IMAGE,podman_metadata=str(root/'control/podman-operations'))
    for name in ('docker_image','docker_host','docker_bin','container_python','container_node'):settings.pop(name,None)
    result={}
    for role,home in homes.items():
        current=deepcopy(cfg)
        current['mcp_servers']['atlas_read'].update(command=python,cwd=str(home))
        current['plugins']['entries']['qyp_guard']['settings']['reviewed_stdio_servers']['atlas_read'].update(command=python,cwd=str(home))
        result[role]=current
    return result
