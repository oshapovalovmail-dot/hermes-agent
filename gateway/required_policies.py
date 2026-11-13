"""Mandatory operator policies, verified before warmup or transport connection."""
from pathlib import Path


def require_policy_results(required, results):
    if not isinstance(required,list) or any(not isinstance(p,str) or not p for p in required):
        raise RuntimeError('invalid_required_gateway_policies')
    for policy in required:
        matches=[r for r in results if isinstance(r,dict) and r.get('policy')==policy]
        if len(matches)!=1 or matches[0].get('ready') is not True:
            raise RuntimeError('required_gateway_policy_unready:'+policy)


def verify_required_gateway_policies():
    """Apply the launch home's requirements to every native served profile."""
    from hermes_constants import get_routing_process_hermes_home
    from hermes_cli.config_effective import load_user_config_effective
    from hermes_cli.profiles import profiles_to_serve
    from hermes_cli.plugins import discover_plugins,invoke_hook
    from gateway.run import _profile_runtime_scope
    home=get_routing_process_hermes_home()
    cfg=load_user_config_effective(home/'config.yaml') or {}
    required=(cfg.get('gateway') or {}).get('required_policies',[])
    if not required:return
    homes={Path(home)}|{Path(h) for _,h in profiles_to_serve(multiplex=True)}
    for target in sorted(homes):
        with _profile_runtime_scope(target):
            discover_plugins()
            results=invoke_hook('required_gateway_policy',required=required)
            require_policy_results(required,results)


def required_source_authorized(source):
    """Preprocessing gate: before native downloads/sticker auxiliary inference.

    A transport allow-all cannot bypass an operator-required plugin policy.
    Missing, failed or ambiguous source-policy callbacks deny intake.
    """
    from hermes_cli.config import load_config_readonly
    from hermes_cli.plugins import invoke_hook
    try:
        required=((load_config_readonly() or {}).get('gateway') or {}).get('required_policies',[])
        if not required:return True
        results=invoke_hook('required_gateway_source',source=source)
        ready=[{'policy':r.get('policy'),'ready':r.get('allow') is True} for r in results if isinstance(r,dict)]
        require_policy_results(required,ready)
        return True
    except (Exception,SystemExit):
        return False
