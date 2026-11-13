"""Explicit parent-selected existing local memory; never silently replace/disable."""
import os
from pathlib import Path
import httpx
from .protocol import Denied,load_key
from .memory import LocalHonchoAdapter


def local_honcho(cfg,root):
    if (type(cfg) is not dict or set(cfg)-{'workspace_id','mapping','api_key_file'}
            or type(cfg.get('workspace_id')) is not str or not cfg['workspace_id'] or type(cfg.get('mapping')) is not dict):raise Denied('parent_existing_shared_Honcho_mapping_required')
    key=None
    if cfg.get('api_key_file') is not None:key=load_key(cfg['api_key_file']).decode('utf-8').strip()
    elif 'HONCHO_API_KEY' in os.environ:raise Denied('ambient_memory_credentials_forbidden')
    from honcho import Honcho
    http=httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,follow_redirects=False,timeout=10)
    try:
        client=Honcho(api_key=key,workspace_id=cfg['workspace_id'],base_url='http://127.0.0.1:8000',max_retries=0,http_client=http)
        adapter=LocalHonchoAdapter(client,cfg['mapping'],journal=Path(root)/'memory.sqlite')
        return adapter,http
    except BaseException:http.close();raise
