"""Producer-only wake origin scope across native API turn dispatch."""
from functools import wraps

from agent.capture_origin import runtime_capture_origin


def capture_runtime_turn(run):
    """Keep private origin out of both public request metadata and turn kwargs."""
    @wraps(run)
    async def bound(self, *args, **kwargs):
        payload = kwargs.pop("_runtime_payload", "")
        if not payload:
            return await run(self, *args, **kwargs)
        with runtime_capture_origin(payload):
            return await run(self, *args, **kwargs)
    return bound


def runtime_wake_kwargs(adapter, request, session_id, text, messages, stream):
    """Consume an exact one-use producer capability after ordinary API admission."""
    import json
    from aiohttp import web
    ticket = request.headers.get("X-Hermes-Runtime-Wake", "")
    if not ticket:
        return {}
    bound = getattr(adapter, "_runtime_wake_tickets", {}).pop(ticket, None)
    if (bound is None or bound != (session_id, text) or stream
            or len(messages) != 1 or messages[0].get("role") != "user"):
        raise web.HTTPForbidden(text=json.dumps({"error": {"message": "Invalid runtime wake capability",
                                                         "type": "invalid_request_error"}}),
                                content_type="application/json")
    return {"_runtime_payload": bound[1]}


def _prefix_names_served_profile(profile: str) -> bool:
    """True when a /p/<profile>/ prefix names the profile this gateway serves. Fail closed: a
    single-profile gateway answering /p/<x>/ served the owner's toolsets under another URL."""
    try:
        from hermes_cli.profiles import profile_matches_home
        return profile_matches_home(profile)
    except Exception:
        return False
