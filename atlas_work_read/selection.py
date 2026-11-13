"""Host-only background trace selection, separate from the read-only reader.

The only production selection mode creates one owned target at the exact URL
from the actual admitted SDK message. No tab listing, navigation, focus, generic
JS, credential inspection, model-selected target or arbitrary network endpoint.
The pinned sidecar supplies metadata-only CDP connection setup and DOM script.
"""
import asyncio
from dataclasses import dataclass, field
import json
import re
import threading
import time

from atlas_bridge.contract import Denied, canonical
from .rpc import validate_body
from .trace import SelectedTraceReader

DEFAULT_ENDPOINT = 'http://127.0.0.1:9222'
MAX_FRAME = 262144
ID = re.compile(r'[A-Za-z0-9_-]{1,128}')


def identifier(value):
    if type(value) is not str or ID.fullmatch(value) is None:
        raise Denied('trace_protocol_identity_invalid')
    return value


@dataclass(eq=False)
class OriginalSource:
    edge: object
    scope: dict
    message: object
    binding: object
    urls: frozenset
    revoked: threading.Event = field(default_factory=threading.Event)

    def check(self):
        try:
            if (self.revoked.is_set() or self.edge._binding(self.scope) is not self.binding
                    or self.edge.gate.message_binding(self.message) is not self.binding):
                raise Denied('original_trace_source_revoked')
        except BaseException:
            self.revoked.set()
            raise


class ReadLease:
    def __init__(self, source, body, loop):
        self.source = source
        # A complete immutable-by-ownership call binding: UID/profile/chat/topic,
        # origin/source hash/session + signed canonical turn and exact arguments.
        self.body = json.loads(canonical(body))
        self.loop = loop
        self.deadline = time.monotonic() + 45

    def check(self):
        # Thread-safe lifetime bit only; SDK/journal objects belong to the loop.
        if self.source.revoked.is_set():
            raise Denied('original_trace_source_revoked')
        if time.monotonic() > self.deadline:
            self.source.revoked.set()
            raise Denied('trace_deadline_exceeded')

    async def fresh(self):
        self.check()
        try:
            self.source.check()
            binding = await self.source.edge.recheck(self.source.scope)
            self.check()
            self.source.check()
            if binding is not self.source.binding:
                raise Denied('original_trace_binding_changed')
        except BaseException:
            self.source.revoked.set()
            raise

    def fresh_sync(self):
        self.check()
        future = asyncio.run_coroutine_threadsafe(self.fresh(), self.loop)
        try:
            future.result(timeout=6)
            self.check()
        except BaseException:
            self.source.revoked.set()
            future.cancel()
            raise Denied('trace_source_fresh_check_denied') from None


class BackgroundTargetAPI:
    """Private bounded transport; reader receives only ReadOnlyDriver below."""
    def __init__(self, bundle, endpoint, lease):
        self.bundle = bundle
        self.lease = lease
        self.target = None
        self.creation_pending = False
        self.session = None
        self.transport = None
        self.counter = 0
        lease.fresh_sync()
        bundle.verify()
        # Reuse the ACTUAL pinned constructor: GET /json/version only, strict
        # same-loopback browser WS, no redirects, no proxies, no browser startup.
        self.transport = bundle.module.CDPDriver(endpoint)
        try:
            lease.fresh_sync()
        except BaseException:
            self.transport.close()
            raise

    def _wire(self, method, params, session=None):
        allowed = {'Target.createTarget', 'Target.getTargetInfo', 'Target.attachToTarget',
                   'Runtime.evaluate', 'Target.detachFromTarget', 'Target.closeTarget'}
        if method not in allowed:
            raise Denied('trace_method_denied')
        self.counter += 1
        payload = {'id': self.counter, 'method': method, 'params': params}
        if session is not None:
            payload['sessionId'] = session
        raw = json.dumps(payload)
        if len(raw.encode()) > MAX_FRAME:
            raise Denied('trace_payload_limit')
        self.transport.ws.send(raw)
        deadline = time.monotonic() + 8
        for _ in range(64):
            raw = self.transport.ws.recv(timeout=max(.01, deadline - time.monotonic()))
            if not isinstance(raw, str) or len(raw.encode()) > MAX_FRAME:
                raise Denied('trace_payload_limit')
            msg = json.loads(raw)
            if type(msg) is not dict:
                raise Denied('trace_protocol_invalid')
            if msg.get('id') == self.counter:
                if 'error' in msg or type(msg.get('result')) is not dict:
                    raise Denied('trace_protocol_error')
                return msg['result']
            if time.monotonic() > deadline:
                break
        raise Denied('trace_protocol_timeout')

    def info(self):
        self.lease.fresh_sync()
        out = self._wire('Target.getTargetInfo', {'targetId': self.target})
        self.lease.fresh_sync()
        info = out.get('targetInfo', {})
        if (info.get('targetId') != self.target or info.get('type') != 'page'
                or info.get('url') != self.lease.body['arguments']['url']):
            self.lease.source.revoked.set()
            raise Denied('selected_native_tab_changed')
        return out

    def create(self):
        if self.target is not None:
            raise Denied('trace_target_already_owned')
        self.lease.fresh_sync()
        self.creation_pending = True
        out = self._wire('Target.createTarget', {
            'url': self.lease.body['arguments']['url'], 'background': True})
        # Record the task-owned receipt BEFORE the post-await source check.
        self.target = identifier(out.get('targetId'))
        self.creation_pending = False
        self.lease.fresh_sync()
        self.info()

    def reader_call(self, method, params, session=None):
        if method == 'Target.detachFromTarget':
            if params != {'sessionId': self.session} or self.session is None or session is not None:
                raise Denied('trace_owned_session_required')
            # Cleanup remains legal after revoke/cancel, but never produces a
            # successful capture: a fresh check follows the cleanup receipt.
            out = self._wire(method, params)
            self.session = None
            self.lease.fresh_sync()
            self.info()
            return out
        self.lease.fresh_sync()
        if method == 'Target.getTargetInfo':
            if params != {'targetId': self.target} or session is not None:
                raise Denied('trace_exact_target_required')
            return self.info()
        if method == 'Target.attachToTarget':
            if (params != {'targetId': self.target, 'flatten': True}
                    or self.session is not None or session is not None):
                raise Denied('trace_exact_target_required')
            self.info()
            out = self._wire(method, params)
            self.session = identifier(out.get('sessionId'))
        elif method == 'Runtime.evaluate':
            if (self.session is None or session != self.session or params != {
                    'expression': self.bundle.module.TRACE_SCRIPT,
                    'returnByValue': True, 'timeout': 2000}):
                raise Denied('trace_fixed_script_required')
            self.bundle.verify()
            self.info()
            out = self._wire(method, params, session)
        else:
            raise Denied('trace_reader_method_denied')
        self.lease.fresh_sync()
        self.info()
        return out

    def cleanup(self):
        # Lost creation receipt: never enumerate to guess ownership or retry.
        # Latch the adapter and require operator reconciliation instead.
        failed = self.creation_pending
        try:
            if self.session is not None:
                try:
                    self._wire('Target.detachFromTarget', {'sessionId': self.session})
                    self.session = None
                except Exception:
                    failed = True
            if self.target is not None:
                try:
                    out = self._wire('Target.closeTarget', {'targetId': self.target})
                    if out.get('success') is not True:
                        raise Denied('trace_cleanup_failed')
                    self.target = None
                except Exception:
                    failed = True
        finally:
            if self.transport is not None:
                self.transport.close()
        if failed:
            raise Denied('trace_cleanup_failed')


class ReadOnlyDriver:
    def __init__(self, api):
        self.api = api

    def __call__(self, method, params, session=None):
        return self.api.reader_call(method, params, session)


class BackgroundTraceAdapter:
    def __init__(self, edge, bundle, endpoint=DEFAULT_ENDPOINT):
        self.edge = edge
        self.bundle = bundle
        try:self.endpoint = bundle.module.validate_endpoint(endpoint)
        except (ValueError,bundle.module.PolicyError):raise Denied('trace_endpoint_invalid') from None
        self.sources = {}
        self.active = set()
        self.closed = False
        self.cleanup_failures = []

    def remember_human(self, scope, message):
        from telegram import Message
        from .rpc import original_human_urls
        if (self.closed or not isinstance(message, Message) or message.from_user is None
                or message.from_user.is_bot or str(message.from_user.id) != scope['user_id']
                or str(message.chat.id) != scope['chat_id']):
            raise Denied('original_sdk_human_required')
        binding = self.edge._binding(scope)
        if self.edge.gate.message_binding(message) is not binding:
            raise Denied('original_native_message_binding_required')
        self.bundle.verify()
        urls = set()
        for url in original_human_urls(message.text or message.caption or '')[:8]:
            try:
                self.bundle.module.validate_trace(url)
                urls.add(url)
            except (ValueError, self.bundle.module.PolicyError):
                pass
        old = self.sources.get(scope['origin'])
        if old is not None:
            old.check()
            if old.scope != scope or old.urls != frozenset(urls) or old.binding is not binding:
                raise Denied('original_trace_source_conflict')
            # A redelivered DTO never replaces the original source or revives it.
            return
        # Follow the existing native message registry's lifetime, not a new
        # read-request quota. Eviction revokes any in-flight lease as well.
        for origin, record in list(self.sources.items()):
            if self.edge.gate.message_binding(record.message) is not record.binding:
                record.revoked.set()
                self.sources.pop(origin)
        if not urls:
            return
        self.sources[scope['origin']] = OriginalSource(
            self.edge, json.loads(canonical(scope)), message, binding, frozenset(urls))

    async def read_call(self, body):
        validate_body(body)
        source = self.sources.get(body['scope']['origin'])
        if (self.closed or self.cleanup_failures or source is None or source.scope != body['scope']
                or body['method'] != 'trace_read'
                or set(body['arguments']) - {'url', 'max_chars'}
                or body['arguments'].get('url') not in source.urls):
            raise Denied('original_human_selected_trace_required')
        lease = ReadLease(source, body, asyncio.get_running_loop())
        await lease.fresh()
        task = asyncio.create_task(asyncio.to_thread(self._read, lease))
        self.active.add(task)
        try:
            value = await asyncio.shield(task)
            await lease.fresh()
            return value
        except asyncio.CancelledError:
            source.revoked.set()
            # to_thread cancellation is NOT thread termination. Do not ACK until
            # the actual bounded worker has detached/closed its own target.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if task.done() and not task.cancelled():
                task.exception()
            raise
        finally:
            self.active.discard(task)

    def _read(self, lease):
        api = None
        try:
            api = BackgroundTargetAPI(self.bundle, self.endpoint, lease)
            api.create()
            def selected(scope, url):
                lease.fresh_sync()
                if scope != lease.body['scope'] or url != lease.body['arguments']['url']:
                    raise Denied('exact_trace_call_required')
                return api.target
            reader = SelectedTraceReader(ReadOnlyDriver(api), selected, self.bundle)
            for attempt in range(8):
                value = reader.read(lease.body['scope'], lease.body['arguments']['url'],
                                    lease.body['arguments'].get('max_chars', 12000))
                if value.get('code') != 'trace_not_ready' or attempt == 7:
                    return value
                lease.fresh_sync()
                time.sleep(.25)
                lease.fresh_sync()
                api.info()
        except (PermissionError, InterruptedError):
            raise
        except Exception:
            raise Denied('trace_cdp_unavailable') from None
        finally:
            if api is not None:
                try:
                    api.cleanup()
                except Exception:
                    self.cleanup_failures.append(lease.body['call_sha256'])
                    raise Denied('trace_cleanup_failed') from None

    async def close(self):
        self.closed = True
        for source in self.sources.values():
            source.revoked.set()
        if self.active:
            await asyncio.gather(*list(self.active), return_exceptions=True)
        if self.cleanup_failures:
            raise Denied('trace_cleanup_failed')
