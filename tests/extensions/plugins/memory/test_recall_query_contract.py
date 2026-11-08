"""Automatic evidence contracts through native providers, manager and API sidecar."""
from types import SimpleNamespace as NS

import pytest

from agent.memory_manager import MemoryManager
from agent.turn_context import substitute_api_content
from tests.extensions.plugins.memory import test_review_r2_operators as base

rig = base.rig
isolated = base.isolated
http_fixture = base.http_fixture

PERMISSION_ONLY = [
    'Делай, разрешаю',
    'Делай, разрешаю только для текущей задачи',
    'Да, продолжай, я согласен',
    'Можешь продолжать, даю согласие',
    'Go ahead, you have my permission',
    'Proceed, I authorize it for this task only',
    'Yes, approved, continue',
    'Настоящим даю согласие продолжать только в рамках текущей задачи.',
    'I hereby authorize you to proceed for this task only.',
]
OPAQUE = 'memory-audit-no-such-run-7c39e2'
TOPICAL = [
    ('Какой результат у вымышленного запуска ' + OPAQUE + '?',
     'Memory audit run completed successfully.', OPAQUE + ' has no confirmed result.'),
    ('What result for export-run-AX29?', 'Export run AX29 completed.',
     'export-run-AX29 is pending.'),
    ('What result for d7440d05-6643-4f04-adec-83b3f3409b12?',
     'An unrelated result was successful.',
     'd7440d05-6643-4f04-adec-83b3f3409b12: task success 68.99%.'),
    ('Какое последнее расписание проверки результатов прокачек мы установили для Печкина 2 ноября?',
     'AllHands 2 ноября; проверки завершены.',
     'Для Печкина установлен запуск в 09:00.'),
    ('What schedule for Nebula checks on November 2?',
     'Zephyr checks completed on November 2.', 'Nebula uses the staging issuer.'),
    ('Делай, разрешаю восстановление Nebula',
     'Делай, разрешаю изменения для старой задачи.', 'Nebula restoration is task-local.'),
    ('Настоящим даю согласие продолжать восстановление Nebula только в рамках текущей задачи.',
     'Настоящим даю согласие на старую работу.', 'Nebula restoration is task-local.'),
    ('I hereby authorize you to proceed with Nebula recovery for this task only.',
     'I hereby authorize old work.', 'Nebula recovery requires a staging check.'),
]


def sidecar(home, query, block):
    with base.ovc.closing(base.ovc.SessionDB(home / 'state.db')) as db:
        db.create_session('saved', source='cli')
        db.append_message('saved', 'user', query,
                          api_content=base.ovc.compose_user_api_content(query, block, ''))
        saved = db.get_messages('saved')[0]
    assert saved['content'] == query
    wire = {'role': 'user', 'content': saved['content'], 'api_content': saved['api_content']}
    substitute_api_content(wire)
    return saved, wire['content']


@pytest.mark.parametrize('query', PERMISSION_ONLY)
def test_permission_only_openviking_has_no_historical_authorization(http_fixture, isolated, query):
    state, _ = http_fixture
    noise = query + '. This authorized a different historical task only.'
    item = base.ovc.leaf('old-authorization', noise)
    state['candidates'] = [item]
    state['bodies'] = {item['uri']: noise}
    manager, _ = base.ovc.make_manager(isolated)
    try:
        block = manager.prefetch_all(query, session_id='saved')
        saved, wire = sidecar(isolated, query, block)
        assert block == ''
        assert saved['api_content'] is None
        assert wire == query
        assert noise in manager.handle_tool_call('viking_search', {'query': query})
        assert noise in manager.handle_tool_call('viking_read', {'uri': item['uri'], 'level': 'content'})
    finally:
        manager.shutdown_all()


@pytest.mark.parametrize('query,noise,positive', TOPICAL)
def test_openviking_subject_and_identifier_cannot_be_replaced_by_scaffold(http_fixture, isolated, query, noise, positive):
    state, _ = http_fixture
    items = [base.ovc.leaf('noise', noise), base.ovc.leaf('positive', positive),
             base.ovc.leaf('misleading-summary', positive)]
    state['candidates'] = items
    state['bodies'] = {items[0]['uri']: noise, items[1]['uri']: positive + '\n\n' + noise,
                       items[2]['uri']: noise}
    manager, provider = base.ovc.make_manager(isolated)
    try:
        cfg = provider._recall_config()
        assert cfg['max_injected_chars'] == 4000
        assert cfg['full_read_limit'] == 2
        block = manager.prefetch_all(query, session_id='saved')
        assert positive in block
        assert noise not in block
        _, wire = sidecar(isolated, query, block)
        assert positive in wire and noise not in wire
        assert noise in manager.handle_tool_call('viking_search', {'query': query})
        assert noise in manager.handle_tool_call('viking_read', {'uri': items[0]['uri'], 'level': 'content'})
        assert not any(path.endswith(('/commit', '/messages', '/messages/batch'))
                       for _, path, _ in state['records'])
    finally:
        manager.shutdown_all()


@pytest.mark.parametrize('query', PERMISSION_ONLY)
@pytest.mark.parametrize('fallback', [False, True])
def test_permission_only_honcho_history_is_empty(rig, isolated, query, fallback):
    provider, mgr, session, _, peers = rig
    noise = '[2026-10-10] ' + query + '. This authorized a different historical task only.'
    def context(**kwargs):
        if fallback:
            raise RuntimeError('fixture offline')
        return NS(representation=noise, peer_card=[])
    for peer in peers.values():
        object.__setattr__(peer, 'context', context)
        object.__setattr__(peer, 'representation', lambda **kw: noise)
        object.__setattr__(peer, 'get_card', lambda **kw: [])
    result = mgr.get_prefetch_context(session.key, query)
    block = provider._format_first_turn_context(result)
    assert not result['representation'] and not result['ai_representation']
    _, wire = sidecar(isolated, query, block)
    assert wire == query


@pytest.mark.parametrize('query', PERMISSION_ONLY)
def test_permission_only_honcho_does_not_replay_ready_authorization(rig, isolated, query):
    provider, _, _, _, _ = rig
    noise = 'Historical authorization for a different task.'
    provider._prefetch_result = noise
    provider._prefetch_result_fired_at = provider._turn_count
    provider._base_context_cache = noise
    manager = MemoryManager()
    manager.add_provider(provider)
    block = manager.prefetch_all(query, session_id='saved')
    _, wire = sidecar(isolated, query, block)
    assert block == '' and wire == query


@pytest.mark.parametrize('fallback', [False, True])
@pytest.mark.parametrize('query,noise,positive', TOPICAL)
def test_honcho_provider_subject_and_identifier_reaches_api_sidecar(rig, isolated, fallback, query, noise, positive):
    provider, _, _, _, peers = rig
    text = '[2026-10-10] ' + noise + '\n[2026-10-09] ' + positive
    calls = []
    def context(**kwargs):
        calls.append(kwargs)
        if fallback:
            raise RuntimeError('fixture offline')
        return NS(representation=text, peer_card=[])
    for peer in peers.values():
        object.__setattr__(peer, 'context', context)
        object.__setattr__(peer, 'representation', lambda **kw: text)
        object.__setattr__(peer, 'get_card', lambda **kw: [])
        object.__setattr__(peer, 'chat', lambda *a, **kw: '')
    manager = MemoryManager()
    manager.add_provider(provider)
    block = manager.prefetch_all(query, session_id='saved')
    assert positive in block
    assert noise not in block
    assert all(call['search_query'] == query for call in calls)
    _, wire = sidecar(isolated, query, block)
    assert positive in wire and noise not in wire
