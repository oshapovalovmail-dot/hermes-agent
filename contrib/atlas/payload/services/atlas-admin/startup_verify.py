#!/usr/bin/env python3
"""Mandatory Atlas preflight entrypoint. --check does NOT start any service."""
import json
import os
from pathlib import Path
import sys

A=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(A/'runtime'))


def verify():
    policy=json.loads((A/'control/authorization-policy.json').read_text())
    if policy.get('activation_permitted') is not True or policy.get('state')!='parent_verified_provider_integrated':
        raise PermissionError('parent_verified_staff_tasha_authorization_required')
    from hermes_cli.config import load_config_readonly
    cfg=load_config_readonly() or {}
    if (cfg.get('gateway') or {}).get('required_policies')!=['qyp_guard']:
        raise PermissionError('required_gateway_policy_not_pinned')
    from gateway.required_policies import verify_required_gateway_policies
    verify_required_gateway_policies()
    return {'ready':True,'policy':'qyp_guard','native_guard_discovery':True,'docker_probe':True,'no_service_started':True}


if __name__=='__main__':
    try:
        receipt=verify()
        print(json.dumps(receipt),flush=True)
        if sys.argv[1:]==['--exec-gateway']:
            os.execv(str(A/'bin/hermes'),[str(A/'bin/hermes'),'gateway','run'])
        elif sys.argv[1:] not in ([],['--check']):raise ValueError('only --check or --exec-gateway')
    except (Exception,SystemExit) as error:
        print(json.dumps({'ready':False,'error':type(error).__name__}),file=sys.stderr)
        sys.exit(1)
