"""Scope boundary is conveyed at the actual saved/API memory fence."""
from agent.memory_manager import build_memory_context_block
from tests.extensions.plugins.memory import test_recall_query_contract as base

isolated = base.isolated


def test_historical_scope_cannot_supply_current_authorization_at_api(isolated):
    query = 'Inspect Nebula recovery; do not change production.'
    old = 'Nebula recovery was authorized for an archived task only. NOT standing permission.'
    block = build_memory_context_block(old)
    saved, wire = base.sidecar(isolated, query, old)
    assert block in wire
    assert saved['content'] == query
    assert old in wire
    assert 'historical reference data' in wire
    assert 'not current authorization' in wire
    assert 'original task scope and negations' in wire
    assert 'authoritative reference data' not in wire
