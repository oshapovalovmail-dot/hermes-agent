"""Additional SDK/transport acceptance; no behavioral implementation in this file."""
import json

import pytest

from agent.memory_manager import MemoryManager
from tests.extensions.plugins.memory import test_recall_query_contract as contract

rig = contract.rig
isolated = contract.isolated


@pytest.mark.parametrize('query,noise,positive', contract.TOPICAL)
def test_real_honcho_sdk_context_parses_native_dto_before_api_injection(rig, isolated, monkeypatch, query, noise, positive):
    provider, mgr, _, _, peers = rig
    client = peers['human']._honcho
    # The fixture workspace is already provisioned; exercise reads only.
    client._workspace_ensured = True
    records = []
    def get(path, query=None, **kwargs):
        records.append((path, query))
        assert path.endswith('/context') and query is not None
        return {'peer_id': path.split('/')[-2], 'target_id': query['target'],
                'representation': '[2026-10-10] ' + noise + '\n[2026-10-09] ' + positive,
                'peer_card': ['Standing fixture identity.']}
    monkeypatch.setattr(client._http, 'get', get)
    for peer in peers.values():
        object.__setattr__(peer, 'chat', lambda *a, **kw: '')
    manager = MemoryManager()
    manager.add_provider(provider)
    block = manager.prefetch_all(query, session_id='saved')
    assert positive in block and noise not in block
    assert len(records) == 2
    assert all(kw['search_query'] == query for _, kw in records)
    _, wire = contract.sidecar(isolated, query, block)
    assert positive in wire and noise not in wire
    # Explicit discovery still returns the same noncorroborating historical row.
    mgr.honcho.search = lambda *a, **kw: [contract.NS(content=noise, peer_id='human',
                                                    session_id='old-fixture', metadata={})]
    assert noise in json.loads(manager.handle_tool_call('honcho_search', {'query': query}))['result']
