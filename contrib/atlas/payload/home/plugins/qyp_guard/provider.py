"""Host-only Staff username proof. Not a numeric Telegram/Staff binding.

Only trusted Telegram intake may supply username and telegram_id. No model tool,
login fallback, guest fallback, owner exception, persistent identity cache or URL
parameter is exposed. A negative/unavailable/ambiguous lookup returns None.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

STAFF_PERSON = 'https://staff-api.yandex-team.ru/v4/person'
FIELDS = 'id,login,is_deleted,official.is_dismissed,official.is_robot,telegram_accounts'
MAX_BYTES = 65536
HTTP_TIMEOUT = 3.0
VERIFY_TIMEOUT = 4.0
_USERNAME = re.compile(r'[A-Za-z0-9_]{1,32}', re.ASCII)


class StaffLookupUnavailable(Exception):
    """Sanitized internal failure. Never include upstream content or credentials."""


def canonical_username(value):
    # Do not strip whitespace, '@', controls or Unicode lookalikes into identity.
    # Basic Telegram names have a minimum length; collectible names can be short.
    if type(value) is not str or _USERNAME.fullmatch(value) is None:
        return None
    return value.lower()


def _unique_object(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError('duplicate_json_key')
        output[key] = value
    return output


class StaffPersonHTTP:
    """Fixed GET only; callbacks come from reviewed host-side TrackerAPI code.

    Injection is trusted Python construction, never model/schema input. The
    reviewed opener disables proxies and redirects and validates HTTPS normally.
    Each read is byte/deadline bounded. No response/header/body/auth is logged.
    """
    def __init__(self, auth_reader, opener):
        self._auth_reader = auth_reader
        self._opener = opener

    def lookup(self, username):
        name = canonical_username(username)
        if name is None:
            raise StaffLookupUnavailable('invalid_username')
        request = None
        deadline = time.monotonic() + HTTP_TIMEOUT
        try:
            credential = self._auth_reader()
            if (type(credential) is not str or not credential or len(credential) > 16384
                    or any(ord(c) < 33 or ord(c) > 126 for c in credential)):
                raise StaffLookupUnavailable('auth_unavailable')
            params = {'telegram_accounts.value_lower': name, '_fields': FIELDS,
                      '_limit': '2', '_one': '0', '_doc': '0'}
            request = Request(STAFF_PERSON + '?' + urlencode(params), method='GET',
                              headers={'Authorization': 'OAuth ' + credential,
                                       'Accept': 'application/json'})
            del credential
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StaffLookupUnavailable('timeout')
            with self._opener.open(request, timeout=remaining) as response:
                if type(response.status) is not int or response.status != 200:
                    raise StaffLookupUnavailable('http_error')
                chunks = []; total = 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise StaffLookupUnavailable('timeout')
                    sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    # read1 prevents a slow trickle from resetting a whole-body timeout.
                    chunk = response.read1(min(8192, MAX_BYTES + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise StaffLookupUnavailable('response_limit')
                    chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise StaffLookupUnavailable('timeout')
                return json.loads(b''.join(chunks).decode('utf-8'),
                                  object_pairs_hook=_unique_object,
                                  parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite_json')))
        except HTTPError as error:
            error.close()
            raise StaffLookupUnavailable('http_error') from None
        except StaffLookupUnavailable:
            raise
        except Exception:
            raise StaffLookupUnavailable('lookup_unavailable') from None
        finally:
            if request is not None:
                request.remove_header('Authorization')


def _employee_id(data, username):
    if (type(data) is not dict or 'error' in data or 'errors' in data
            or data.get('has_more') is not False or data.get('links') != {}
            or 'next_page_token' not in data or data['next_page_token'] is not None):
        return None
    people = data.get('result')
    if type(people) is not list or len(people) != 1:
        return None
    person = people[0]
    if type(person) is not dict or person.get('is_deleted') is not False:
        return None
    employee_id = person.get('id')
    official = person.get('official')
    if (type(employee_id) is not int or employee_id <= 0
            or type(official) is not dict or official.get('is_dismissed') is not False
            or official.get('is_robot') is not False):
        return None
    accounts = person.get('telegram_accounts')
    if type(accounts) is not list or not accounts or len(accounts) > 128:
        return None
    names = set()
    for account in accounts:
        if type(account) is not dict:
            return None
        value = canonical_username(account.get('value'))
        if value is None or value in names:
            return None
        # If lower is provided, it must itself be canonical and agree with value.
        if 'value_lower' in account and (type(account['value_lower']) is not str
                or account['value_lower'] != value):
            return None
        names.add(value)
    return str(employee_id) if username in names else None


class StaffUsernameProvider:
    def __init__(self, transport, *, proof_type=None):
        self._transport = transport
        self._proof_type = proof_type

    async def verify(self, telegram_id: int, username: str):
        name = canonical_username(username)
        # Telegram identifiers have at most 52 significant bits. bool is not int.
        if name is None or type(telegram_id) is not int or not 0 < telegram_id < 2**52:
            return None
        try:
            data = await asyncio.wait_for(asyncio.to_thread(self._transport.lookup, name), VERIFY_TIMEOUT)
            employee_id = _employee_id(data, name)
            if employee_id is None:
                return None
            proof_type = self._proof_type
            if proof_type is None:
                from gateway.atlas_admission import StaffProof
                proof_type = StaffProof
            return proof_type(telegram_id, employee_id, True, True, False, username=name)
        except Exception:
            # asyncio cancellation is BaseException and propagates to the caller.
            return None
