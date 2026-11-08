"""Explicitly configured reminder controls; disabled by default."""
from pathlib import Path
from . import watch_buttons as controls

def register(ctx):
    if not ctx.get_config("enabled", False):
        return
    root = ctx.get_config("state_root")
    route = ctx.get_config("route")
    jobs = ctx.get_config("job_ids")
    if not root or not isinstance(route, dict) or not all(route.get(k) for k in ("owner_id", "chat_id")) or not jobs:
        raise ValueError("Configure state_root, route owner/chat/thread, and job_ids explicitly")
    from .adapter import ReminderAdapter, native
    from hermes_constants import get_hermes_home
    owner_home = Path(get_hermes_home()).resolve()

    def build(config):
        if Path(get_hermes_home()).resolve() != owner_home:
            raise ValueError("reminder_profile_mismatch")
        adapter = ReminderAdapter(config, root=root, route=route, jobs=jobs)
        adapter._notifications_mode = native._resolve_notifications_mode()
        return adapter

    async def standalone(pconfig, chat_id, message, **kwargs):
        if controls.MARKER.search(message):
            raise RuntimeError("reminder_controls_need_live_gateway")
        return await native._standalone_send(pconfig, chat_id, message, **kwargs)

    class Registration:
        def register_platform(self, **kwargs):
            # User plugins must not waive native allowlists/pairing.
            kwargs.pop("trusted_inbound", None)
            return ctx.register_platform(**(kwargs | {"adapter_factory": build,
                                                       "standalone_sender_fn": standalone}))
    native.register(Registration())
