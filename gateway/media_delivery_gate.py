"""Required plugin policy at MEDIA preflight and transport upload.

No cache/recency/remote fallback after a mandatory policy rejection.
Origins are transport-bound, never model arguments.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from hermes_cli.config import load_config_readonly
from hermes_cli.plugins import invoke_hook

_ORIGIN: ContextVar[dict | None] = ContextVar('plugin_media_delivery_origin', default=None)


@contextmanager
def media_delivery_origin(source, *, session_key=''):
    platform = getattr(source, 'platform', None)
    origin = None if source is None else {
        'platform': getattr(platform, 'value', platform),
        'user_id': getattr(source, 'user_id', None),
        'chat_id': getattr(source, 'chat_id', None),
        'chat_type': getattr(source, 'chat_type', None),
        'profile': getattr(source, 'profile', None),
        'thread_id': getattr(source, 'thread_id', None),
        '_atlas_binding': getattr(source, '_atlas_binding', None),
        'session_key': session_key,
    }
    token = _ORIGIN.set(origin)
    try:
        from gateway.atlas_admission import binding_scope
        with binding_scope(getattr(source,'_atlas_binding',None)):
            yield
    finally:
        _ORIGIN.reset(token)


def required_media_policy():
    """An unreadable configuration requires denial, never legacy fallback."""
    try:
        return ((load_config_readonly() or {}).get('media_delivery') or {}).get('required_policy')
    except (Exception, SystemExit):
        return True


def resolve_required_media_path(path, session_key=''):
    """Return (mandatory, approved absolute snapshot path or None)."""
    policy = required_media_policy()
    if policy in (None, ''):
        return False, None
    origin = _ORIGIN.get()
    if not isinstance(policy, str) or origin is None or not session_key:
        return True, None
    if origin.get('session_key') and origin['session_key'] != session_key:
        return True, None
    try:
        results = invoke_hook('resolve_media_delivery_path', path=path, session_key=session_key,
                              bound_source=dict(origin), policy=policy)
        if not isinstance(results, list) or len(results) != 1:
            return True, None
        decision = results[0]
        if not isinstance(decision, dict) or decision.get('policy') != policy:
            return True, None
        safe = decision.get('path')
        if not isinstance(safe, str) or not safe.startswith('/') or '\x00' in safe:
            return True, None
        return True, safe
    except (Exception, SystemExit):
        return True, None


def resolve_media_upload(path, chat_id):
    """Transport door: require the exact recipient and bound route."""
    if required_media_policy() in (None, ''):
        return False, None
    origin = _ORIGIN.get()
    if not origin or str(chat_id) != origin.get('chat_id'):
        return True, None
    return resolve_required_media_path(path, origin.get('session_key', ''))
