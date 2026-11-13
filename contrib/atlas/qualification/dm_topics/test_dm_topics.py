"""Offline sparse-seam regression. No production imports with side effects."""
import ast
import asyncio
import copy
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from typing import Any, Optional
import unittest

W = Path(__file__).resolve().parent
R = Path(os.environ['ATLAS_TEST_RUNTIME'])
MODE = sys.argv.pop(1) if len(sys.argv) > 1 and sys.argv[1] in ('baseline', 'overlay') else 'overlay'
PINS = json.loads((W / 'pins.json').read_text())
for relative, expected in PINS.items():
    assert hashlib.sha256((R / relative).read_bytes()).hexdigest() == expected, relative

# Deny network and all writes outside this artifact, including import bytecode.
sys.dont_write_bytecode = True

def audit(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
        raise RuntimeError('offline_test_forbids_' + event)
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        p = Path(os.fsdecode(args[0])).absolute()
        mode, flags = args[1:3]
        write = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        if write and not p.is_relative_to(W):
            raise RuntimeError('write_outside_artifact')
        atlas_home = R.parent / 'home'
        if p.is_relative_to(atlas_home) and not p.is_relative_to(atlas_home / 'installs'):
            raise RuntimeError('production_state_read_forbidden')
sys.addaudithook(audit)

for name in ('gateway', 'atlas_bridge', 'atlas_native_bridge'):
    package = types.ModuleType(name)
    package.__path__ = []
    sys.modules[name] = package


def module(name, path, selected=None, namespace=None):
    m = types.ModuleType(name)
    m.__file__ = str(path)
    sys.modules[name] = m
    if namespace:
        m.__dict__.update(namespace)
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    if selected is not None:
        nodes = [n for n in tree.body if getattr(n, 'name', None) in selected]
        assert {n.name for n in nodes} == set(selected)
        tree = ast.Module(body=nodes, type_ignores=[])
    exec(compile(tree, str(path), 'exec'), m.__dict__)
    return m


# Execute exact pinned AST nodes, not replacements, to avoid unrelated config,
# secret-provider, relay and session-store imports. These seams are unchanged.
config = module('gateway.config', R / 'gateway/config.py', ['Platform'], {'Enum': Enum})
detached = module('gateway.session_detached', R / 'gateway/session_detached.py', ['detached_route_of'])
session = module('gateway.session', R / 'gateway/session.py',
                 ['SessionSource', '_session_key_namespace', '_canonical_participant', 'build_session_key'],
                 dict(dataclass=dataclass, field=field, Any=Any, Optional=Optional,
                      Platform=config.Platform, detached_route_of=detached.detached_route_of))
contract_path = W / MODE / 'atlas_bridge/contract.py'
contract = module('atlas_bridge.contract', contract_path)
gate_module = module('gateway.atlas_admission', R / 'gateway/atlas_admission.py')
protocol = module('atlas_native_bridge.protocol', R / 'atlas_native_bridge/protocol.py')
remote = module('atlas_native_bridge.remote', R / 'atlas_native_bridge/remote.py', ['scope_for'],
                dict(origin_id=contract.origin_id, input_fingerprint=contract.input_fingerprint))
edge_module = module('atlas_native_bridge.edge', R / 'atlas_native_bridge/edge.py')

from telegram import Bot, Update
from telegram.request import BaseRequest

UID = 1234500


class Staff:
    def __init__(self):
        self.allowed = True

    async def verify(self, uid, username):
        if not self.allowed or username != 'fixtureemployee':
            return None
        return gate_module.StaffProof(uid, 'isolated-fixture', True, True, False, username)


class OfflineRequest(BaseRequest):
    """PTB transport sink: captures real serialization, never opens a socket."""
    def __init__(self):
        self.calls = []

    @property
    def read_timeout(self):
        return 1

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit('/', 1)[-1]
        data = request_data.parameters if request_data else {}
        self.calls.append((endpoint, copy.deepcopy(data)))
        if endpoint == 'getMe':
            result = {'id': 9229862070, 'is_bot': True, 'first_name': 'Fixture', 'username': 'fixture_bot'}
        elif endpoint == 'sendMessage':
            result = {'message_id': 9000 + len(self.calls), 'date': 1800000000,
                      'chat': {'id': int(data['chat_id']), 'type': 'private'}, 'text': data['text']}
            if 'message_thread_id' in data:
                result.update(message_thread_id=int(data['message_thread_id']), is_topic_message=True)
        else:
            raise AssertionError('unreviewed_fixture_endpoint')
        return 200, json.dumps({'ok': True, 'result': result}).encode()


def update(topic=None, *, number=945395668, uid=UID, chat=None, username='FixtureEmployee', kind='private', is_bot=False):
    message = {'message_id': number - 944965756, 'date': 1800000000,
               'from': {'id': uid, 'is_bot': is_bot, 'first_name': 'Fixture'},
               'chat': {'id': uid if chat is None else chat, 'type': kind},
               'text': 'Isolated private-topic regression fixture'}
    if username is not None:
        message['from']['username'] = username
    if topic is not None:
        message.update(is_topic_message=True, message_thread_id=topic)
    return Update.de_json({'update_id': number, 'message': message}, None)


class Topics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        (W / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=W / 'tmp')
        self.staff = Staff()
        self.gate = gate_module.AdmissionGate(self.staff)
        self.sink = OfflineRequest()
        self.bot = Bot('123456:OFFLINE_SYNTHETIC_NOT_A_CREDENTIAL',
                       request=gate_module.GuardedRequest(self.sink, self.gate), get_updates_request=OfflineRequest())
        await self.bot.initialize()
        self.edge = edge_module.MacEdge(protocol.Codec(b'x' * 32, 'fixture_epoch', 'mac'), self.gate, self.temp.name, bot=self.bot)
        self.peer = protocol.Codec(b'x' * 32, 'fixture_epoch', 'qyp')

    async def asyncTearDown(self):
        self.edge.close()
        await self.bot.shutdown()
        self.temp.cleanup()

    async def raw(self, topic=None, **kwargs):
        frame = await self.edge.ingress(update(topic, **kwargs))
        return self.peer.verify(frame)['body']['input']

    async def test_actual_sdk_private_topic_ingress(self):
        dto = update(429911)
        self.assertIs(type(dto), Update)
        self.assertEqual(dto.message.message_thread_id, 429911)
        b = await self.gate.admit_message(dto.message, self.bot)
        self.assertTrue(self.gate.valid(b))
        self.assertEqual((b.chat_type, b.user_id, b.chat_id, b.thread_id, b.profile),
                         ('dm', str(UID), str(UID), '429911', 'tg-' + str(UID)))
        frame = await self.edge.ingress(dto)
        raw = self.peer.verify(frame)['body']['input']
        self.assertEqual(contract.validate(raw)['thread_id'], '429911')

    async def test_two_topics_native_session_real_sdk_egress(self):
        keys = []
        for index, topic in enumerate((429911, 429913)):
            raw = await self.raw(topic, number=945395670 + index)
            event = contract.native_event(raw)
            self.assertEqual(event['source']['thread_id'], str(topic))
            scope = self.edge.scope(raw)
            expected = 'agent:tg-1234500:telegram:dm:1234500:' + str(topic)
            self.assertEqual(scope['session_key'], expected)
            keys.append(scope['session_key'])
            receipt = await self.edge.deliver({'scope': scope, 'obligation': str(index + 1) * 64,
                                             'action': {'op': 'send', 'content': 'Offline fixture reply'}})
            self.assertTrue(receipt['success'])
            endpoint, data = self.sink.calls[-1]
            self.assertEqual(endpoint, 'sendMessage')
            self.assertEqual(str(data['chat_id']), str(UID))
            self.assertEqual(str(data['message_thread_id']), str(topic))
            self.assertEqual(receipt['thread_id'], str(topic))
            self.assertEqual(self.edge.journal.sdk(scope['origin'])[0]['message']['message_thread_id'], topic)
        self.assertNotEqual(*keys)

    async def test_ordinary_dm_compatibility(self):
        raw = await self.raw()
        self.assertIsNone(raw['thread_id'])
        scope = self.edge.scope(raw)
        self.assertEqual(scope['session_key'], 'agent:tg-1234500:telegram:dm:1234500')
        receipt = await self.edge.deliver({'scope': scope, 'obligation': 'a' * 64,
                                         'action': {'op': 'send', 'content': 'Offline ordinary reply'}})
        self.assertTrue(receipt['success'])
        self.assertNotIn('message_thread_id', self.sink.calls[-1][1])

    async def test_service_topic_create_does_not_replace_following_text(self):
        payload = update(429911, number=945395680).to_dict()
        payload['message'].pop('text')
        payload['message']['forum_topic_created'] = {'name': 'Fixture topic', 'icon_color': 7322096}
        service = Update.de_json(payload, None)
        self.assertIsNotNone(service.message.forum_topic_created)
        self.assertIsNone(service.message.text)
        before = len(self.sink.calls)
        service_body = self.peer.verify(await self.edge.ingress(service))['body']
        human_body = self.peer.verify(await self.edge.ingress(update(429911, number=945395681)))['body']
        self.assertEqual(len(self.sink.calls), before)
        self.assertEqual(service_body['input']['text'], '')
        self.assertEqual(human_body['input']['text'], 'Isolated private-topic regression fixture')
        self.assertNotEqual(service_body['input']['update_id'], human_body['input']['update_id'])
        self.assertNotEqual(service_body['input']['message_id'], human_body['input']['message_id'])
        self.assertEqual(service_body['session_key'], human_body['session_key'])
        self.assertEqual(contract.native_event(human_body['input'])['text'], human_body['input']['text'])
        human_scope = self.edge.scope(human_body['input'])
        self.assertEqual(human_scope['message_id'], human_body['input']['message_id'])
        self.assertNotEqual(human_scope['origin'], contract.origin_id(service_body['input']))
        receipt = await self.edge.deliver({'scope': human_scope, 'obligation': 'b' * 64,
                                         'action': {'op': 'send', 'content': 'Offline human-origin reply'}})
        self.assertTrue(receipt['success'])
        self.assertEqual(len(self.sink.calls), before + 1)
        self.assertEqual(str(self.sink.calls[-1][1]['message_thread_id']), '429911')

    async def test_group_contract_controls_unchanged(self):
        raw = await self.raw()
        group = {**raw, 'chat_type': 'group', 'chat_id': '-100123', 'thread_id': '7',
                 'profile': 'tg-group-n100123-t7', 'username': None,
                 'eligibility': {'kind': 'tasha_admin', 'bot_id': '793835103', 'is_bot': True, 'status': 'administrator'}}
        self.assertIs(contract.validate(group), group)
        for key, value in (('chat_id', str(UID)), ('thread_id', '07'), ('thread_id', 7),
                           ('profile', 'tg-' + str(UID)), ('username', 'fixtureemployee'),
                           ('eligibility', raw['eligibility'])):
            with self.subTest(key=key, value=value):
                with self.assertRaises(contract.Denied):
                    contract.validate({**group, key: value})

    async def test_contract_negative_controls(self):
        raw = await self.raw()
        controls = [('thread_id', x) for x in ('', '0', '-1', '01', ' 1', '1 ', '1.0', '1e2', '١', '1' * 21, 1, True, 1.0, [], {})]
        controls += [('chat_id', '305016745'), ('user_id', '305016745'), ('profile', 'tg-305016745'),
                     ('profile', 'tg-1234500-t429911'), ('username', 'FixtureEmployee'), ('username', '@fixtureemployee'),
                     ('username', None), ('is_bot', True), ('chat_type', 'private'), ('chat_type', 'group'),
                     ('eligibility', {'kind': 'staff_username', 'active': False, 'verified': True, 'robot': False})]
        for key, value in controls:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(raw)
                changed[key] = value
                with self.assertRaises(contract.Denied):
                    contract.validate(changed)

    async def test_native_gate_negative_controls(self):
        cases = [dict(topic=x) for x in (0, -1, True, '429911', 1.5)]
        cases += [dict(chat=UID + 1), dict(username=None), dict(username='@fixtureemployee'),
                  dict(username='unverified'), dict(is_bot=True), dict(kind='group', chat=UID)]
        for index, kwargs in enumerate(cases):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(PermissionError):
                    await self.edge.ingress(update(number=945395700 + index, **kwargs))
        self.staff.allowed = False
        with self.assertRaises(PermissionError):
            await self.edge.ingress(update(429911))

    async def test_real_guard_denies_foreign_and_omitted_topic(self):
        raw = await self.raw(429911)
        b = self.edge._binding(self.edge.scope(raw))
        for kwargs in ({'chat_id': UID, 'message_thread_id': 429913}, {'chat_id': UID},
                       {'chat_id': UID + 1, 'message_thread_id': 429911}):
            before = len(self.sink.calls)
            with gate_module.binding_scope(b):
                with self.assertRaises(gate_module.AdmissionDenied):
                    await self.bot.send_message(text='Must never dispatch', **kwargs)
            self.assertEqual(len(self.sink.calls), before)
        scope = self.edge.scope(raw)
        for key, value in (('user_id', str(UID + 1)), ('profile', 'tg-foreign'), ('thread_id', '429913'), ('username', 'foreign')):
            altered = {**scope, key: value}
            with self.assertRaises(PermissionError):
                self.edge._binding(altered)

    async def test_signatures_freshness_and_nonce_preserved(self):
        raw = await self.raw(429911)
        now = raw['issued_at']
        codec = contract.EnvelopeCodec(b'y' * 32, raw['epoch'])
        signed = codec.sign(raw, now=now)
        self.assertEqual(codec.verify(signed, now=now), raw)
        tampered = copy.deepcopy(signed)
        tampered['payload']['thread_id'] = '429913'
        with self.assertRaisesRegex(contract.Denied, 'invalid_transport_signature'):
            codec.verify(tampered, now=now)
        with self.assertRaisesRegex(contract.Denied, 'stale_or_foreign_transport_proof'):
            codec.verify(signed, now=raw['expires_at'])
        ledger = contract.IngressLedger(Path(self.temp.name) / 'nonce.sqlite')
        try:
            self.assertEqual(ledger.admit(raw), 'new')
            changed = {**raw, 'update_id': str(int(raw['update_id']) + 1)}
            with self.assertRaisesRegex(contract.Denied, 'nonce_scope_conflict'):
                ledger.admit(changed)
        finally:
            ledger.db.close()
        frame = self.edge.codec.sign('input', {'input': raw})
        bad = copy.deepcopy(frame)
        bad['body']['input']['thread_id'] = '429913'
        with self.assertRaisesRegex(contract.Denied, 'invalid_signature'):
            self.peer.verify(bad)
        with self.assertRaisesRegex(contract.Denied, 'stale_frame'):
            self.peer.verify(frame, now=frame['exp'])
        self.edge.journal.seen(frame['nonce'])
        with self.assertRaisesRegex(contract.Denied, 'replayed_application_frame'):
            self.edge.journal.seen(frame['nonce'])


if __name__ == '__main__':
    import telegram
    print(json.dumps({'mode': MODE, 'contract_path': str(contract_path),
                      'contract_sha256': hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                      'python': sys.version, 'ptb': telegram.__version__,
                      'isolation': 'exact pinned AST session/config/scope seams; full real gate/edge/contract/protocol; fake Staff and offline PTB transport only'}, sort_keys=True), flush=True)
    unittest.main(verbosity=2)
