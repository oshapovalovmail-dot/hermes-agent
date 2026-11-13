"""Explicit operator entrypoints. Never installed/started by the test runner."""
import asyncio,json,os
from pathlib import Path
from atlas_bridge.contract import Denied,digest
from atlas_native_bridge.protocol import Codec,load_key,decode
from .bundle import Bundle
from .backend import PrivateBackendPool,serve_worker
from .facade import serve

def bundle_config(cfg):
    if type(cfg)is not dict or set(cfg)!={'bundle_root','bundle_pins'}:raise Denied('closed_bundle_configuration')
    return Bundle(cfg['bundle_root'],cfg['bundle_pins'])

def build_mac_backend(cfg):
    if type(cfg)is not dict or not {'bundle_root','bundle_pins','python','worker_root'}<=set(cfg) or set(cfg)-{'bundle_root','bundle_pins','python','worker_root','peer_bundle_pins','trace_selection'}:raise Denied('closed_mac_read_configuration')
    bundle=bundle_config({k:cfg[k] for k in ('bundle_root','bundle_pins')})
    python=Path(cfg['python']);root=Path(cfg['worker_root'])
    if not python.is_absolute() or not python.is_file() or not os.access(python,os.X_OK) or not root.is_absolute():raise Denied('trusted_native_worker_paths_required')
    from atlas_native_bridge.protocol import directory
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=directory(root)
    try:
        info=os.fstat(fd)
        if info.st_uid!=os.getuid() or info.st_mode&0o777!=0o700:raise Denied('private_native_workers_required')
    finally:os.close(fd)
    config=root/'bundle.json'
    encoded=json.dumps({k:cfg[k] for k in ('bundle_root','bundle_pins')},sort_keys=True)
    if config.exists():
        if config.is_symlink() or config.read_text()!=encoded:raise Denied('native_worker_bundle_conflict')
    else:
        fd=os.open(config,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(encoded)
    def parameters(scope):
        from mcp import StdioServerParameters
        from .backend import identity
        private=root/digest(identity(scope));private.mkdir(mode=0o700,exist_ok=True)
        return StdioServerParameters(command=str(python),args=['-I','-B',str(Path(__file__).with_name('worker_entry.py')),'--config',str(config)],cwd=str(private),
            env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin','TMPDIR':os.environ.get('TMPDIR',str(private)),'LANG':'en_US.UTF-8'})
    return PrivateBackendPool(bundle,parameters)

def build_trace_adapter(cfg,edge,bundle):
    if cfg is None:return None
    if type(cfg)is not dict or not {'mode'}<=set(cfg) or set(cfg)-{'mode','endpoint'} or cfg['mode']!='background_owned':raise Denied('closed_trace_selection_configuration')
    from .selection import BackgroundTraceAdapter,DEFAULT_ENDPOINT
    return BackgroundTraceAdapter(edge,bundle,cfg.get('endpoint',DEFAULT_ENDPOINT))

def build_mac_connector(edge,cfg):
    from .rpc import MacReadConnector
    backend=build_mac_backend(cfg)
    trace=build_trace_adapter(cfg.get('trace_selection'),edge,backend.bundle)
    return MacReadConnector(edge,backend,trace=trace,peer_bundle_pins=cfg.get('peer_bundle_pins'))

def main(mode):
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--config',required=True,type=Path);a=p.parse_args()
    if a.config.is_symlink() or not a.config.is_file():raise Denied('trusted_operator_config_required')
    cfg=decode(a.config.read_bytes())
    if mode=='worker':asyncio.run(serve_worker(bundle_config(cfg)));return
    if set(cfg)!={'bundle_root','bundle_pins','profile_home','key_file','epoch','hub_socket'}:raise Denied('closed_qyp_read_configuration')
    bundle=bundle_config({k:cfg[k] for k in ('bundle_root','bundle_pins')})
    codec=Codec(load_key(cfg['key_file']),cfg['epoch'],'qyp')
    asyncio.run(serve(bundle,codec,cfg['profile_home'],cfg['hub_socket']))
