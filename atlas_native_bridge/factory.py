"""Narrow native factory seam. Inactive unless operator opts in explicitly."""
from urllib.parse import urlsplit
from gateway.atlas_admission import installed_gate, install_gate
from .protocol import Codec, Denied, load_key
from .remote import RemoteAdmissionGate, AtlasWebSocketRelayTransport
from .hub import upgrade_secret


def configure_memory(ctx):
    """Operator-only factory choice; no peers, credentials or backend IO here."""
    setting=ctx.get_config('bridge_memory')
    if setting is None:return
    if setting!={'enabled':True}:raise Denied('explicit_native_bridge_memory_required')
    from .memory_provider import register
    register(ctx)


def build_gate(settings,*,provision=None):
    if (type(settings) is not dict or set(settings)!={'enabled','key_file','epoch','gateway_id'} or
            settings['enabled'] is not True):raise Denied('explicit_remote_admission_configuration_required')
    key=load_key(settings['key_file']);current=installed_gate()
    if current is not None:
        if not isinstance(current,RemoteAdmissionGate) or current.codec.epoch!=settings['epoch'] or current.codec._key!=key:raise Denied('conflicting_native_authority')
        if provision is not None and current.provision is None:current.provision=provision
        return current
    gate=RemoteAdmissionGate(Codec(key,settings['epoch'],'qyp'),provision=provision)
    install_gate(gate);return gate


def build_transport(settings,url):
    parsed=urlsplit(url)
    if (parsed.scheme!='ws' or parsed.hostname!='127.0.0.1' or parsed.port is None
            or parsed.path not in ('','/relay') or parsed.username or parsed.password or parsed.query or parsed.fragment):raise Denied('QYP_loopback_hub_only')
    gate=build_gate(settings)
    return AtlasWebSocketRelayTransport(url,'telegram','9229862070',gate=gate,
        identities=[('telegram','9229862070')],gateway_id=settings['gateway_id'],
        upgrade_secret=upgrade_secret(gate.codec._key),reconnect=True)
