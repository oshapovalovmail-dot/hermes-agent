"""Narrow operator-config route refresh for profile-admin plugins."""
from dataclasses import asdict
from pathlib import Path


async def refresh_gateway_profiles(home: Path) -> dict:
    """Reconcile native homes before replacing routes, on the gateway loop.

    Reads only operator configuration. Never accepts routes or sender identities
    supplied by plugin/model arguments. Callers gate the ctx capability.
    """
    from gateway.run import _gateway_runner_ref
    from gateway.profile_routing import parse_profile_routes
    from hermes_cli.config_effective import load_user_config_effective
    runner = _gateway_runner_ref()
    if runner is None:
        raise RuntimeError('gateway_not_running')
    cfg = load_user_config_effective(home / 'config.yaml') or {}
    routes = parse_profile_routes((cfg.get('gateway') or {}).get('profile_routes', []))
    result = await runner.reconcile_served_profiles(reason='plugin-profile-admin')
    if result.get('pending'):
        raise RuntimeError('profile_reconcile_pending')
    served = set(result.get('served_profiles', []))
    if any(route.profile not in served and route.profile != 'default' for route in routes):
        raise RuntimeError('route_profile_not_served')
    import asyncio
    from gateway.required_policies import verify_required_gateway_policies
    await asyncio.to_thread(verify_required_gateway_policies)
    runner.config.profile_routes = routes
    from gateway.config import load_gateway_config
    from gateway.run import _profile_runtime_scope
    with _profile_runtime_scope(home):
        authored = load_gateway_config()
    auth_keys = ('dm_policy','allow_from','allow_admin_from','group_policy','group_allow_from','group_allow_admin_from','unauthorized_dm_behavior')
    runner.config.unauthorized_dm_behavior = authored.unauthorized_dm_behavior
    for platform, configured in authored.platforms.items():
        targets = []
        current = runner.config.platforms.get(platform)
        if current is not None:targets.append(current)
        adapter = getattr(runner, 'adapters', {}).get(platform)
        if adapter is not None:targets.append(adapter.config)
        for target in targets:
            for key in auth_keys:
                if key in configured.extra:target.extra[key] = configured.extra[key]
                else:target.extra.pop(key,None)
    return {'served_profiles': sorted(served), 'routes': [asdict(route) for route in routes]}
