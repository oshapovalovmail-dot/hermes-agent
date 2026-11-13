"""Fixture-only QYP-role native relay listener + fixed app stdio input.

NOT an activatable Atlas transport: all native output is refused until reviewed
QYP native-issued binding integration exists. No model, Bot API or work access.
"""
import argparse
import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time

import websockets
from atlas_bridge.contract import BOT_ID, Denied, EnvelopeCodec, IngressLedger, canonical, native_event

KEY = b'synthetic-fixture-key-at-least-32-bytes'
EPOCH = 'synthetic-epoch'
GATEWAY_ID = 'synthetic-atlas-qyp'
UPGRADE_SECRET = 'synthetic-native-upgrade-secret'
DESCRIPTOR = {'contract_version': 1, 'platform': 'telegram', 'label': 'Atlas fixture only',
              'max_message_length': 4096, 'supports_draft_streaming': False,
              'supports_edit': False, 'supports_threads': False, 'markdown_dialect': 'plain',
              'len_unit': 'utf16', 'supported_ops': ['send']}
MAX_FRAME = 131072


def output(frame):
    sys.stdout.write(canonical(frame).decode() + '\n'); sys.stdout.flush()


def decode(raw):
    if type(raw) is bytes:
        raw = raw.decode('utf-8')
    if type(raw) is not str or len(raw.encode()) > MAX_FRAME:
        raise Denied('bounded_frame_required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Denied('duplicate_field')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise Denied('invalid_json') from None
    if type(value) is not dict:
        raise Denied('object_required')
    return value


def authenticated(headers):
    try:
        values = headers.get_all('Authorization')
        if len(values) != 1 or not values[0].startswith('Bearer '):
            return False
        token = values[0][7:]
        decoded = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4)).decode()
        subject, exp, signature = decoded.rsplit(':', 2)
        signed = subject + ':' + exp
        expected = hmac.new(UPGRADE_SECRET.encode(), signed.encode(), hashlib.sha256).hexdigest()
        return subject == GATEWAY_ID and int(time.time()) < int(exp) <= int(time.time()) + 300 and hmac.compare_digest(expected, signature)
    except (ValueError, UnicodeError, KeyError):
        return False


class Hub:
    def __init__(self, root):
        self.root = root
        self.codec = EnvelopeCodec(KEY, EPOCH)
        self.ledger = IngressLedger(root / 'input.sqlite')
        self.native = None
        self.hello = False

    async def relay(self, ws):
        if ws.request.path != '/relay' or not authenticated(ws.request.headers):
            await ws.close(code=4401, reason='unauthorized'); return
        if self.native is not None:
            await ws.close(code=4409, reason='single_gateway_only'); return
        self.native = ws
        try:
            async for raw in ws:
                # Native contract uses newline-delimited JSON inside WebSocket text.
                for line in raw.splitlines():
                    frame = decode(line)
                    kind = frame.get('type')
                    if kind == 'hello' and frame == {'type': 'hello', 'platform': 'telegram', 'botId': BOT_ID}:
                        self.hello = True
                        await ws.send(canonical({'type': 'descriptor', 'descriptor': DESCRIPTOR}).decode() + '\n')
                    elif kind == 'inbound_ack' and set(frame) == {'type', 'bufferId'} and type(frame['bufferId']) is str:
                        # This is an observed native ACK, not a claim of model execution.
                        output({'kind': 'native_ingress_ack', 'origin': frame['bufferId']})
                    elif kind == 'outbound' and type(frame.get('requestId')) is str:
                        # No production native binding exists. Model metadata is not authority.
                        result = {'success': False, 'error': 'native_issued_binding_required',
                                  'error_code': 'native_issued_binding_required'}
                        await ws.send(canonical({'type': 'outbound_result', 'requestId': frame['requestId'], 'result': result}).decode() + '\n')
                    elif kind == 'going_idle' and set(frame) == {'type'}:
                        await ws.send('{"type":"going_idle_ack"}\n')
                    else:
                        await ws.close(code=4400, reason='unreviewed_native_frame'); return
        except (Denied, ValueError, UnicodeError):
            await ws.close(code=4400, reason='invalid_native_frame')
        finally:
            if self.native is ws:
                self.native = None; self.hello = False

    async def application(self):
        while True:
            raw = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_FRAME + 1)
            if not raw:
                return
            try:
                frame = decode(raw)
                if frame == {'kind': 'close'}:
                    return
                if set(frame) != {'kind', 'envelope'} or frame['kind'] != 'input':
                    raise Denied('unreviewed_application_kind')
                if self.native is None or not self.hello:
                    raise Denied('native_transport_unavailable')
                body = self.codec.verify(frame['envelope'], now=int(time.time()))
                disposition = self.ledger.admit(body)
                if disposition == 'new':
                    # QYP-only durable fingerprint, not a native FIFO claim or grant.
                    event = native_event(body)
                    await self.native.send(canonical({'type': 'inbound', 'bufferId': body['bot_id'] + ':' + body['update_id'], 'event': event}).decode() + '\n')
                output({'kind': 'input_disposition', 'disposition': disposition})
            except Denied as error:
                output({'kind': 'denied', 'code': str(error)})
            except (ValueError, UnicodeError):
                output({'kind': 'denied', 'code': 'invalid_application_frame'})


async def run(root):
    hub = Hub(root)
    try:
        async with websockets.serve(hub.relay, '127.0.0.1', 0, max_size=MAX_FRAME) as server:
            output({'kind': 'fixture_ready', 'port': server.sockets[0].getsockname()[1],
                    'production_ready': False})
            await hub.application()
    finally:
        hub.ledger.db.close()


def main():
    parser = argparse.ArgumentParser(description='NOT a production bridge; synthetic transport fixture only')
    parser.add_argument('--fixture-only', action='store_true', required=True)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    expected = Path(__file__).resolve().parents[1] / 'receipts'
    root = args.root.absolute()
    if not root.is_relative_to(expected) or any(p.is_symlink() for p in (root, *root.parents)):
        parser.error('owned receipts subdirectory required')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    asyncio.run(run(root))


if __name__ == '__main__':
    main()
