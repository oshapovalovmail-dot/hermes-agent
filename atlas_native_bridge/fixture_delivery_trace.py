"""Fixture-only observation of native delivery; never restores authority."""
from functools import wraps
from types import MethodType
from gateway.atlas_admission import current_binding


def trace_delivery(adapter, transport, gate, rows):
    def state(bound=None):
        ambient = current_binding()
        return {'ambient_present': ambient is not None, 'ambient_valid': gate.valid(ambient),
                'event_binding_present': bound is not None, 'event_binding_valid': gate.valid(bound),
                'ambient_is_event_binding': bound is not None and ambient is bound}

    def instrument(target, name, label):
        original = getattr(target, name)

        @wraps(original)
        async def observed(_self, *args, **kwargs):
            event = args[0] if name == 'send_final_ledgered' and args else None
            source = getattr(event, 'source', None)
            bound = getattr(source, '_atlas_binding', None)
            action = args[0] if name in ('send_outbound', 'outbound') and args else {}
            row = {'boundary': label, 'phase': 'enter', **state(bound)}
            if source is not None:
                row.update(event_profile=source.profile, event_chat=source.chat_id,
                           event_binding_source_authorized=gate.source_authorized(source),
                           relay_source=source.delivered_via_upstream_relay)
            if isinstance(action, dict):
                row.update(op=action.get('op'), final_text=action.get('content') == 'NATIVE_BRIDGE_MODEL_OK')
            rows.append(row)
            try:
                result = await original(*args, **kwargs)
            except BaseException as error:
                rows.append({'boundary': label, 'phase': 'raise', 'type': type(error).__name__,
                             'denial': str(error) if isinstance(error, PermissionError) else None})
                raise
            else:
                reply = result[0] if isinstance(result, tuple) else result
                rows.append({'boundary': label, 'phase': 'return',
                             'success': reply.get('success') if isinstance(reply, dict) else getattr(reply, 'success', None),
                             'code': reply.get('code') if isinstance(reply, dict) else None})
                return result
        setattr(target, name, MethodType(observed, target))

    for name in ('send_final_ledgered', 'send', 'send_for_platform'):
        instrument(adapter, name, 'native_adapter.' + name)
    instrument(transport, 'send_outbound', 'bridge_transport.send_outbound')
    instrument(gate, 'outbound', 'remote_gate.outbound')
