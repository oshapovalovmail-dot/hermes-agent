"""Source-only config transformation. Import/call returns data, never writes files.

Apply with the frozen core+plugin+helper package only, after staff provider and
native end-to-end qualification. No BotFather/service/process changes here.
"""
from copy import deepcopy

def candidate_config(original,*,transport=True):
    cfg=deepcopy(original)
    cfg['unauthorized_dm_behavior']='ignore'
    gateway=cfg.setdefault('gateway',{})
    gateway['multiplex_profiles']=True
    # Native top-level key wins over gateway fallback: clear both explicitly.
    cfg['max_concurrent_sessions']=None
    gateway['max_concurrent_sessions']=None
    # Atlas-only turn watchdog includes the 24h script and management cleanup.
    cfg.setdefault('agent',{})['gateway_timeout']=86580
    # Restricted Atlas does not need the optional home-delivery onboarding notice.
    gateway['home_channel_prompt']=False
    atlas_read=cfg.get('mcp_servers',{}).get('atlas_read')
    if isinstance(atlas_read,dict):
        atlas_read['circuit_breaker']=False
    required=gateway.setdefault('required_policies',[])
    if 'qyp_guard' not in required:required.append('qyp_guard')
    cfg.setdefault('media_delivery',{})['required_policy']='qyp_guard'
    settings=cfg['plugins']['entries']['qyp_guard'].setdefault('settings',{})
    settings.update(admission_mode='verified_staff_or_official_tasha_administrator',tasha_bot_id=793835103)
    blocks=[cfg.setdefault('telegram',{})]
    for parent in (cfg.get('platforms'),gateway.get('platforms')):
        if isinstance(parent,dict) and isinstance(parent.get('telegram'),dict):blocks.append(parent['telegram'])
    for block in blocks:
        # Transport openness is only the lower layer. The mandatory native gate
        # authorizes actual SDK sender/group proof before any handler runs.
        block.update(dm_policy='open',allow_from=['*'],group_policy='open',group_allow_from=['*'],unauthorized_dm_behavior='ignore')
        extra=block.setdefault('extra',{})
        extra.update(atlas_admission=True,dm_policy='open',allow_from=['*'],group_policy='open',group_allow_from=['*'])
        # Keep BotFather privacy unchanged and normal @mention/reply trigger rules.
        # No free-response or guest-mode escalation; no unmentioned observation.
        block.update(require_mention=True,guest_mode=False,observe_unmentioned_group_messages=False)
        extra.update(require_mention=True,guest_mode=False,observe_unmentioned_group_messages=False)
        if not transport:block['enabled']=False
    return cfg
