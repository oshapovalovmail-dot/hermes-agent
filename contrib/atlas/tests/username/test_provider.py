"""Synthetic unit fixtures only; no gateway bootstrap, auth or live requests."""
import asyncio
import copy
from dataclasses import dataclass
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    import provider as p
    import staff_provider as bridge
except ModuleNotFoundError:
    p = bridge = None

@dataclass(frozen=True)
class Proof:
    telegram_id: int
    employee_id: str
    active: bool
    verified: bool
    robot: bool
    username: str | None = None


def person():
    return {'id': 123, 'login': 'not_the_telegram_name', 'is_deleted': False,
            'official': {'is_dismissed': False, 'is_robot': False},
            'telegram_accounts': [{'id': 888, 'value': 'User_One', 'value_lower': 'user_one'}]}


def body():
    return {'result': [person()], 'has_more': False, 'links': {}, 'next_page_token': None}


class Lookup:
    def __init__(self, data=None, error=None):
        self.data = body() if data is None else data
        self.error = error
        self.calls = []
    def lookup(self, username):
        self.calls.append(username)
        if self.error:
            raise self.error
        return copy.deepcopy(self.data)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(p, 'username Staff provider is not implemented')
    async def verify(self, data=None, username='User_One', uid=42, error=None):
        lookup = Lookup(data, error)
        result = await p.StaffUsernameProvider(lookup, proof_type=Proof).verify(uid, username)
        return result, lookup
    async def test_consistent_case_returns_scoped_username_proof(self):
        proof, lookup = await self.verify()
        self.assertEqual(proof, Proof(42, '123', True, True, False, 'user_one'))
        self.assertEqual(lookup.calls, ['user_one'])
    async def test_uid_is_authenticated_scope_not_staff_numeric_binding(self):
        first, _ = await self.verify(uid=42)
        second, _ = await self.verify(uid=43)
        self.assertEqual(first.employee_id, second.employee_id)
        self.assertEqual(second.telegram_id, 43)
    async def test_missing_malformed_non_native_username_never_looks_up(self):
        for name in (None, '', 123, True, '@User_One', ' User_One', 'User_One ', 'User\nOne',
                     'user\x00one', 'юзер', 'ｕser', 'user-one', 'a'*33):
            with self.subTest(name=repr(name)):
                proof, lookup = await self.verify(username=name)
                self.assertIsNone(proof)
                self.assertEqual(lookup.calls, [])
    async def test_short_native_name_accepted(self):
        data = body()
        data['result'][0]['telegram_accounts'] = [{'value': 'X', 'value_lower': 'x'}]
        proof, _ = await self.verify(data, username='X')
        self.assertEqual(proof.username, 'x')
    async def test_invalid_uid_never_looks_up(self):
        for uid in (True, 0, -1, '42', None, 2**52):
            with self.subTest(uid=uid):
                proof, lookup = await self.verify(uid=uid)
                self.assertIsNone(proof)
                self.assertEqual(lookup.calls, [])
    async def test_changed_or_missing_account_does_not_use_login(self):
        for accounts in ([], [{'value': 'other', 'value_lower': 'other'}], None):
            data = body(); data['result'][0]['login'] = 'user_one'
            data['result'][0]['telegram_accounts'] = accounts
            self.assertIsNone((await self.verify(data))[0])
    async def test_absent_returns_none(self):
        data = body(); data['result'] = []
        self.assertIsNone((await self.verify(data))[0])
    async def test_status_missing_wrong_type_or_not_active_denies(self):
        for path in [('is_deleted',), ('official', 'is_dismissed'), ('official', 'is_robot')]:
            for value in (True, None, 0, 'false', 'MISSING'):
                with self.subTest(path=path, value=value):
                    data = body(); obj = data['result'][0]
                    for key in path[:-1]: obj = obj[key]
                    if value == 'MISSING': obj.pop(path[-1])
                    else: obj[path[-1]] = value
                    self.assertIsNone((await self.verify(data))[0])
    async def test_invalid_staff_id_denies(self):
        for value in (None, True, 0, -1, '123', 'not-id'):
            data = body(); data['result'][0]['id'] = value
            self.assertIsNone((await self.verify(data))[0])
    async def test_multiple_people_or_duplicate_records_denies(self):
        data = body(); data['result'].append(person())
        self.assertIsNone((await self.verify(data))[0])
    async def test_duplicate_or_conflicting_accounts_denies(self):
        for accounts in ([{'value': 'User_One', 'value_lower': 'another'}],
                         [{'value': 'another', 'value_lower': 'user_one'}],
                         [{'value': 'User_One', 'value_lower': 'user_one'}]*2,
                         [{'value_lower': 'user_one'}],
                         [{'value': '@User_One', 'value_lower': 'user_one'}]):
            data = body(); data['result'][0]['telegram_accounts'] = accounts
            self.assertIsNone((await self.verify(data))[0])
    async def test_value_without_optional_lower_accepted(self):
        data = body(); data['result'][0]['telegram_accounts'][0].pop('value_lower')
        self.assertIsNotNone((await self.verify(data))[0])
    async def test_pagination_ambiguous_or_missing_denies(self):
        for key, value in [('has_more', True), ('has_more', 0), ('has_more', None),
                           ('next_page_token', 'more'), ('links', {'next': '/page2'})]:
            data = body(); data[key] = value
            self.assertIsNone((await self.verify(data))[0])
        for key in ('has_more', 'links', 'next_page_token'):
            data = body(); data.pop(key)
            self.assertIsNone((await self.verify(data))[0])
    async def test_schema_and_upstream_errors_deny(self):
        for data in ([], {}, {'error': 'denied', **body()}, {'errors': [], **body()},
                     {'result': 'bad', 'has_more': False}, {'result': [None], **{k:v for k,v in body().items() if k!='result'}}):
            self.assertIsNone((await self.verify(data))[0])
        for error in (TimeoutError('synthetic'), OSError('synthetic'), ValueError('synthetic')):
            self.assertIsNone((await self.verify(error=error))[0])
    async def test_async_deadline_returns_none(self):
        import time
        from unittest.mock import patch
        class Slow:
            def lookup(self, username):
                time.sleep(0.04)
                return body()
        with patch.object(p, 'VERIFY_TIMEOUT', 0.005):
            self.assertIsNone(await p.StaffUsernameProvider(Slow(), proof_type=Proof).verify(42, 'user_one'))
    async def test_task_cancellation_propagates(self):
        import time
        class Slow:
            def lookup(self, username):
                time.sleep(0.04)
                return body()
        task = asyncio.create_task(p.StaffUsernameProvider(Slow(), proof_type=Proof).verify(42, 'user_one'))
        await asyncio.sleep(0.005)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
    async def test_default_gateway_contract_import_without_home_initialization(self):
        from unittest.mock import patch
        module = types.ModuleType('gateway.atlas_admission'); module.StaffProof = Proof
        with patch.dict(sys.modules, {'gateway.atlas_admission': module}):
            proof = await p.StaffUsernameProvider(Lookup()).verify(42, 'User_One')
        self.assertEqual(proof, Proof(42, '123', True, True, False, 'user_one'))
    async def test_no_positive_cache_for_changed_or_dismissed_employee(self):
        lookup = Lookup()
        provider = p.StaffUsernameProvider(lookup, proof_type=Proof)
        self.assertIsNotNone(await provider.verify(42, 'User_One'))
        lookup.data['result'][0]['official']['is_dismissed'] = True
        self.assertIsNone(await provider.verify(42, 'User_One'))
        self.assertEqual(len(lookup.calls), 2)


class Response(io.BytesIO):
    status = 200
    def read1(self, n=-1): return self.read(n)

class Opener:
    def __init__(self, raw=None, status=200, error=None):
        self.raw = json.dumps(body()).encode() if raw is None else raw
        self.status = status; self.error = error; self.calls = []
    def open(self, request, timeout):
        self.calls.append((request, timeout, request.get_header('Authorization')))
        if self.error: raise self.error
        response = Response(self.raw); response.status = self.status
        return response

class TransportTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(p, 'username HTTP transport is not implemented')
    def test_fixed_exact_read_and_opaque_auth_cleaned(self):
        opener = Opener(); transport = p.StaffPersonHTTP(lambda: 'synthetic-fixture-token', opener)
        self.assertEqual(transport.lookup('User_One'), body())
        request, timeout, header = opener.calls[0]
        self.assertEqual(header, 'OAuth synthetic-fixture-token')
        self.assertIsNone(request.get_header('Authorization'))
        self.assertEqual(request.get_method(), 'GET')
        url = urlsplit(request.full_url)
        self.assertEqual((url.scheme, url.netloc, url.path), ('https', 'staff-api.yandex-team.ru', '/v4/person'))
        self.assertEqual(parse_qs(url.query), {'telegram_accounts.value_lower':['user_one'],
            '_fields':['id,login,is_deleted,official.is_dismissed,official.is_robot,telegram_accounts'],
            '_limit':['2'], '_one':['0'], '_doc':['0']})
        self.assertLessEqual(timeout, 3)
    def test_invalid_input_precedes_credential_access(self):
        def forbidden(): self.fail('credential accessed for invalid input')
        with self.assertRaises(p.StaffLookupUnavailable): p.StaffPersonHTTP(forbidden, Opener()).lookup('@User_One')
    def test_http_failure_timeout_schema_size_duplicate_keys_fail_closed(self):
        for opener in (Opener(status=403), Opener(status=302), Opener(error=TimeoutError()),
                       Opener(error=HTTPError('https://fixed',403,'synthetic',{},None)),
                       Opener(raw=b'not-json'), Opener(raw=b'x'*65537),
                       Opener(raw=b'{"result":[],"has_more":false,"has_more":true}')):
            with self.subTest(opener=opener):
                with self.assertRaises(p.StaffLookupUnavailable):
                    p.StaffPersonHTTP(lambda:'synthetic-fixture-token', opener).lookup('user_one')
                self.assertIsNone(opener.calls[0][0].get_header('Authorization'))


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bridge, 'reviewed provider factory is not implemented')
        self.fixture = tempfile.TemporaryDirectory(prefix='fixture-', dir=ROOT)
        self.addCleanup(self.fixture.cleanup)
        self.root = Path(self.fixture.name)
        (self.root/'home').mkdir()
        self.folder = self.root/'services'/'atlas-read'; self.folder.mkdir(parents=True)
        self.path = self.folder/'sidecar.py'
        self.source = b'class Opener:\n def open(self, *args, **kwargs): raise RuntimeError("synthetic fixture only")\nclass TrackerAPI:\n def __init__(self):\n  self._auth_reader=lambda: "synthetic-fixture-token"\n  self._opener=Opener()\n'
        self.path.write_bytes(self.source)
        self.settings = {'admin_home':str(self.root/'home'), 'reviewed_service_files':{'sidecar.py':hashlib.sha256(self.source).hexdigest()}}
        self.ctx = types.SimpleNamespace(get_config=lambda k,d=None:self.settings.get(k,d))
    def test_portable_concrete_factory_without_home_bootstrap(self):
        instance = bridge.build_staff_provider(self.ctx)
        self.assertIsInstance(instance, p.StaffUsernameProvider)
    def test_missing_or_wrong_pin_never_executes(self):
        for pins in ({}, {'sidecar.py':'0'*64}, {'sidecar.py':'../bad'}):
            self.settings['reviewed_service_files'] = pins
            with self.assertRaises(PermissionError): bridge.build_staff_provider(self.ctx)
    def test_symlink_file_or_directory_denied(self):
        target = self.folder/'copy.py'; target.write_bytes(self.source)
        self.path.unlink(); self.path.symlink_to(target)
        with self.assertRaises(PermissionError): bridge.build_staff_provider(self.ctx)
        self.path.unlink(); self.path.write_bytes(self.source)
        real = self.root/'moved'; self.folder.rename(real); self.folder.symlink_to(real, target_is_directory=True)
        with self.assertRaises(PermissionError): bridge.build_staff_provider(self.ctx)
    def test_admitted_buffer_not_reopened_after_path_mutation(self):
        from unittest.mock import patch
        original = bridge._admitted_sidecar
        def mutate_after_read(ctx):
            admitted = original(ctx)
            self.path.write_bytes(b'raise RuntimeError("must never execute changed bytes")\n')
            return admitted
        with patch.object(bridge, '_admitted_sidecar', side_effect=mutate_after_read):
            self.assertIsInstance(bridge.build_staff_provider(self.ctx), p.StaffUsernameProvider)
    def test_absolute_admin_home_contract_required(self):
        for home in ('relative/home', str(self.root/'other'), None):
            self.settings['admin_home'] = home
            with self.assertRaises(PermissionError): bridge.build_staff_provider(self.ctx)

if __name__ == '__main__': unittest.main(verbosity=2)
