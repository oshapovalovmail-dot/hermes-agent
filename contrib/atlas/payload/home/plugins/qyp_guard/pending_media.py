"""Issued immutable snapshots: exact native source/profile/chat/topic/session."""
def register_pending(ctx,service):
    def resolve(path,session_key,bound_source,policy,**kwargs):
        deny={'policy':'qyp_guard','path':None}
        if policy!='qyp_guard' or not isinstance(bound_source,dict):return deny
        from types import SimpleNamespace
        source=SimpleNamespace(**bound_source)
        gate=service.admission
        if not gate.source_authorized(source) or ctx.profile_name!=source.profile:return deny
        try:
            from . import principal_for_binding
            who=principal_for_binding(gate,source._atlas_binding,session_key)
            safe=service.broker.resolve_export(who,path,session_key)
        except (Exception,SystemExit):return deny
        return {'policy':'qyp_guard','path':safe}
    ctx.register_hook('resolve_media_delivery_path',resolve)
