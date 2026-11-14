"""Offline causal tests; only TrackerAPI auth/HTTP transport is synthetic.
Run through run_tests.py to bind an immutable source closure and closed HOME.
"""
import asyncio
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from urllib.error import HTTPError
from jsonschema import Draft202012Validator
from mcp import types

SOURCE = Path(os.environ['ATLAS_TEST_SOURCE'])
spec = importlib.util.spec_from_file_location('tested_sidecar', SOURCE/'sidecar.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

# Trusted fixture boundary: never consult native credentials or real network.
import socket
def denied(*args, **kwargs):
    raise AssertionError('offline fixture forbids network and native commands')
socket.socket.connect = denied
socket.create_connection = denied
s.run_cli = denied
s.TrackerAPI._credential = staticmethod(denied)

class Response:
    status = 200
    def __init__(self, data, link=''):
        self.body = io.BytesIO(json.dumps(data, ensure_ascii=False).encode())
        self.headers = {'Link': link}
    def read1(self, size): return self.body.read(size)
    def __enter__(self): return self
    def __exit__(self, *args): pass

class Transport:
    def __init__(self, data, link=''):
        self.data, self.link = data, link
        self.auth_calls = self.requests = 0
        self.fail = None
    def auth(self):
        self.auth_calls += 1
        return 'synthetic-private-credential'
    def open(self, request, timeout):
        self.requests += 1
        self.last_url = request.full_url
        self.last_request = request
        assert request.get_method() == 'GET'
        assert request.get_header('Authorization') == 'OAuth synthetic-private-credential'
        if self.fail: raise HTTPError(request.full_url, self.fail, 'synthetic', {}, io.BytesIO(b'private'))
        return Response(self.data, self.link)
    def service(self): return s.ReadService(tracker_api=s.TrackerAPI(auth_reader=self.auth, opener=self))

def unicode_text(n): return ('Обсуждение 🧪 e\u0301 "цитата" \\ строка\n' * n) + 'КОНЕЦ'

class TrackerRetention(unittest.TestCase):
    def setUp(self):
        self.old = Path.cwd()
        self.profile = Path(os.environ['HERMES_HOME']) / self._testMethodName
        self.profile.mkdir(parents=True, exist_ok=True)
        os.chdir(self.profile)
        self.pager = s._pager()
        self.pager._STORE = None
    def tearDown(self):
        if self.pager._STORE is not None: self.pager._STORE.close()
        self.pager._STORE = None
        os.chdir(self.old)
    def call(self, service, **args):
        # Actual registered SDK handler + serializer, not an imitation wire shape.
        server = s.build_server(service)
        wire = asyncio.run(server._request_handlers['tools/call'].handler(None, types.CallToolRequestParams(name='tracker_read', arguments=args)))
        encoded = wire.model_dump_json(by_alias=True, exclude_none=True).encode()
        self.assertLessEqual(len(encoded), 10000)
        self.assertEqual(json.loads(wire.content[0].text), wire.structured_content)
        return wire.structured_content
    def collect(self, transport, view='comments', bound=12000, key='TEST-1'):
        service = transport.service()
        page = self.call(service, key=key, view=view, max_chars=bound)
        self.assertTrue(page['ok'], page)
        # On the baseline, this assertion catches the observed causal clipping.
        self.assertIsInstance(json.loads(page['text']), (dict, list))
        expected_text, expected_upstream = s.project_tracker(transport.data, key, view, bool(transport.link), 'synthetic-private-credential')
        expected = json.loads(expected_text)
        if 'format' not in page.get('pagination', {}):
            self.assertEqual(json.loads(page['text']), expected)
            self.assertFalse(page['truncated'])
            return page, 1
        records = []
        count = 0
        while True:
            count += 1
            self.assertLess(count, 1000)
            records.extend(json.loads(page['text'])['records'])
            self.assertEqual(page['returned_chars'], len(page['text']))
            self.assertLessEqual(len(page['text']), bound)
            upstream = page['pagination']['upstream']
            self.assertEqual(upstream, expected_upstream or {'complete': True})
            more = page['pagination']['has_more']
            self.assertEqual(page['pagination']['capture_complete'], not more)
            self.assertEqual(page['pagination']['complete'], not more and upstream['complete'])
            if not more:
                self.assertIsNone(page['pagination']['cursor'])
                break
            before = transport.auth_calls, transport.requests
            page = self.call(service, key=key, view=view, max_chars=bound, cursor=page['pagination']['cursor'])
            self.assertTrue(page['ok'], page)
            self.assertEqual((transport.auth_calls, transport.requests), before, 'continuation must never reread/authenticate upstream')
        # Rebuild typed paths, including huge scalar fragments and empty containers.
        root = None
        for record in records:
            path, value = record['path'], record['value']
            if not path: root = value; continue
            if root is None: root = [] if isinstance(path[0], int) else {}
            parent = root
            for i, part in enumerate(path):
                last = i == len(path)-1
                if isinstance(parent, list):
                    while len(parent) <= part: parent.append(None)
                if last:
                    if 'string_offset' in record:
                        previous = parent[part] if (isinstance(parent, list) or part in parent) else None
                        if previous is None: previous = ''
                        self.assertEqual(len(previous), record['string_offset'])
                        parent[part] = previous + value
                    else: parent[part] = value
                else:
                    if (isinstance(parent, dict) and part not in parent) or parent[part] is None:
                        parent[part] = [] if isinstance(path[i+1], int) else {}
                    parent = parent[part]
        self.assertEqual(root, expected)
        self.assertEqual(json.dumps(root, ensure_ascii=False).encode(), expected_text.encode())
        self.assertEqual((transport.auth_calls, transport.requests), (1, 1))
        return page, count
    def test_direct_clipping_is_coherent_and_retained(self):
        service=Transport([{'text':unicode_text(700)}]).service()
        page=service.tracker_read('TEST-1',view='comments')
        self.assertTrue(page['ok'])
        try: json.loads(page['text'])
        except ValueError: self.fail('ReadService.tracker_read sliced safe JSON into invalid JSON')
        self.assertIsInstance(page.get('pagination',{}).get('cursor'),str)
    def test_minimum_budget_reassembles(self):
        self.collect(Transport([{'text':unicode_text(12)}]),bound=256)
    def test_own_cursor_retry_is_idempotent(self):
        t=Transport([{'text':unicode_text(300)}]);service=t.service()
        first=service.tracker_read('TEST-1',view='comments')
        cursor=first.get('pagination',{}).get('cursor')
        self.assertIsInstance(cursor,str)
        a=service.tracker_read('TEST-1',view='comments',cursor=cursor)
        b=service.tracker_read('TEST-1',view='comments',cursor=cursor)
        self.assertTrue(a['ok']);self.assertEqual(a,b)
        self.assertEqual((t.auth_calls,t.requests),(1,1))
    def test_incident_long_discussion_exact(self):
        t = Transport([{'id':str(i), 'text':unicode_text(100), 'createdBy':{'id':'u', 'display':'Автор'}, 'private':'omit'} for i in range(12)])
        _, count = self.collect(t)
        self.assertGreater(count, 1)
        self.assertTrue(t.last_url.endswith('/comments?perPage=20'))
    def test_single_huge_unicode_comment_exact(self):
        _, count = self.collect(Transport([{'id':'1', 'text':unicode_text(2400)}]), bound=24000)
        self.assertGreater(count, 1)
    def test_small_unicode_under_chars_but_over_wire_pages(self):
        _, count = self.collect(Transport([{'text':'🧪' * 1400}]), bound=48000)
        self.assertGreater(count, 1)
    def test_long_issue_and_links(self):
        for view, data in [('issue', {'key':'TEST-1','description':unicode_text(300)}), ('links', [{'id':'1','object':{'summary':unicode_text(300)}}])]:
            with self.subTest(view=view): self.collect(Transport(data), view)
    def test_native_upstream_next_still_visible_after_retention(self):
        page, _ = self.collect(Transport([{'text':unicode_text(300)}], '<https://untrusted.invalid/private>; rel="next"'))
        self.assertFalse(page['pagination']['complete'])
        self.assertTrue(page['pagination']['upstream']['has_more'])
        self.assertNotIn('untrusted.invalid', json.dumps(page))
    def test_twenty_comments_no_next_is_unknown(self):
        page, _ = self.collect(Transport([{'id':str(i), 'text':unicode_text(20)} for i in range(20)]))
        self.assertIsNone(page['pagination']['upstream']['has_more'])
        self.assertFalse(page['pagination']['complete'])
    def test_legacy_unicode_that_actual_sdk_wire_fits(self):
        t=Transport([{'text':'Ж' * 1100}])
        text,p=s.project_tracker(t.data,'TEST-1','comments',False,'synthetic-private-credential')
        expected=s.result(True,'ok',source='tracker:TEST-1:comments',text=text)
        expected['pagination']=p
        wire=types.CallToolResult(content=[types.TextContent(type='text',text=json.dumps(expected,ensure_ascii=False))],structuredContent=expected,isError=False)
        self.assertLessEqual(len(wire.model_dump_json(by_alias=True,exclude_none=True).encode()),10000)
        self.assertEqual(self.call(t.service(),key='TEST-1',view='comments'),expected)
    def test_legacy_short_shape(self):
        for view,data in [('issue',{'key':'TEST-1','summary':'Коротко'}), ('comments',[{'text':'Коротко'}]), ('links',[])]:
            t = Transport(data); text,p = s.project_tracker(data,'TEST-1',view,False,'synthetic-private-credential')
            expected = s.result(True,'ok',source='tracker:TEST-1:'+view,text=text)
            if p is not None: expected['pagination'] = p
            self.assertEqual(self.call(t.service(),key='TEST-1',view=view), expected)
    def test_no_serialized_json_reredaction(self):
        # Safe values containing words which look like JSON field names remain byte-exact.
        self.collect(Transport([{'text':'token: [REDACTED] "password": "[REDACTED]"\n' + unicode_text(300)}]))
    def test_validation_precedes_auth(self):
        t = Transport([]); service=t.service()
        for args in [dict(key='../TEST-1'),dict(key='TEST-1',view='search'),dict(key='TEST-1',max_chars=True),dict(key='TEST-1',max_chars=255),dict(key='TEST-1',max_chars=48001)]:
            self.assertEqual(service.tracker_read(**args)['code'], 'invalid_argument')
        self.assertEqual((t.auth_calls,t.requests),(0,0))
    def test_cursor_failclosed_no_native_auth_or_read(self):
        t = Transport([{'text':unicode_text(300)}]); service=t.service()
        page = service.tracker_read('TEST-1',view='comments')
        cursor = page.get('pagination',{}).get('cursor')
        self.assertIsInstance(cursor,str, 'must retain output and expose cursor')
        for kwargs in [dict(key='TEST-2',view='comments',cursor=cursor), dict(key='TEST-1',view='issue',cursor=cursor), dict(key='TEST-1',view='comments',cursor='arp1-'+'0'*24+'_1'),dict(key='TEST-1',view='comments',cursor='invalid'),dict(key='TEST-1',view='comments',cursor=''),dict(key='TEST-1',view='comments',cursor=17)]:
            with self.subTest(kwargs=kwargs): self.assertFalse(service.tracker_read(**kwargs)['ok'])
        self.assertEqual((t.auth_calls,t.requests),(1,1))
        # A same-profile deterministic replay is allowed, but foreign-profile replay is not.
        other=self.profile/'foreign';other.mkdir(exist_ok=True);os.chdir(other)
        self.assertFalse(service.tracker_read('TEST-1',view='comments',cursor=cursor)['ok'])
        os.chdir(self.profile)
        self.assertEqual((t.auth_calls,t.requests),(1,1))
        # Exact TTL expiry via the actual encrypted store clock, no sleep/mocked pager.
        store=self.pager._STORE
        store.clock=lambda: float('inf')
        self.assertFalse(service.tracker_read('TEST-1',view='comments',cursor=cursor)['ok'])
        self.assertEqual((t.auth_calls,t.requests),(1,1))
    def test_schema_discovery_and_rpc_reject_malformed_cursor(self):
        t=Transport([]);server=s.build_server(t.service())
        tools=asyncio.run(server._request_handlers['tools/list'].handler(None,None)).tools
        tool=next(v for v in tools if v.name=='tracker_read')
        shape=tool.input_schema
        self.assertIn('cursor',shape['properties'])
        validator=Draft202012Validator(shape)
        self.assertTrue(validator.is_valid({'key':'TEST-1','cursor':'arp1-'+'a'*24+'_1'}))
        for bad in ['', 'arp1-x_1', 1, None, 'arp1-'+'a'*24+'_1234567']:
            self.assertFalse(validator.is_valid({'key':'TEST-1','cursor':bad}))
            self.assertEqual(self.call(t.service(),key='TEST-1',cursor=bad)['code'],'invalid_argument')
        for word in ['cursor','key','view','has_more','retained','upstream','string_offset']:
            self.assertIn(word,tool.description)
        self.assertEqual((t.auth_calls,t.requests),(0,0))
        (Path(os.environ['ATLAS_TEST_OUTPUT'])/'tracker_tool_schema.json').write_text(tool.model_dump_json(indent=2))
    def test_http_auth_acl_redirect_gates_and_projection(self):
        for status,code in [(401,'tracker_unauthorized'),(403,'tracker_acl_denied'),(404,'tracker_not_found'),(302,'tracker_redirect_denied')]:
            t=Transport([]);t.fail=status
            self.assertEqual(t.service().tracker_read('TEST-1')['code'],code)
            self.assertIsNone(t.last_request.get_header('Authorization'))
        t=Transport([{'text':'OAuth secret-value\nsynthetic-private-credential', 'private':'do not export'}])
        page=self.call(t.service(),key='TEST-1',view='comments')
        self.assertNotIn('secret-value',page['text']);self.assertNotIn('synthetic-private-credential',page['text']);self.assertNotIn('private',page['text'])
    def test_first_twenty_admission_unchanged(self):
        t=Transport([{'text':'x'}]*21)
        self.assertEqual(t.service().tracker_read('TEST-1',view='comments')['code'],'tracker_response_unrecognized')
    def test_full_pinned_closure_imports(self):
        for name in s.EXTENDED_BACKENDS: self.assertIsNotNone(s.load_extension(name))
        for name in s.SERVICE_BACKENDS: self.assertIsNotNone(s.load_service_backend(name))
        self.assertEqual(s.MAX_CHARS,48000)
        self.assertEqual(s.MAX_BYTES,2_000_000)

if __name__ == '__main__':
    print('SOURCE', SOURCE, hashlib.sha256((SOURCE/'sidecar.py').read_bytes()).hexdigest(), flush=True)
    unittest.main(verbosity=2)
