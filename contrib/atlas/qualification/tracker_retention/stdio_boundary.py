"""Real SDK STDIO qualification; only synthetic TEST-1 Unicode data.
The proxy measures actual newline-delimited JSON-RPC bytes, not result bodies.
"""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

SOURCE = Path(os.environ['ATLAS_TEST_SOURCE']).resolve()
OUT = Path(os.environ['ATLAS_TEST_OUTPUT']).resolve()

def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def load():
    spec = importlib.util.spec_from_file_location('qualified_sidecar', SOURCE / 'sidecar.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def make_input(s):
    from mcp import types
    best = None
    for n in range(2200, 2500):
        for suffix in ('', 'a'):
            data = [{'text': 'Ж' * n + suffix}]
            text, pagination = s.project_tracker(data, 'TEST-1', 'comments', False, 'synthetic-private-credential')
            value = s.result(True, 'ok', source='tracker:TEST-1:comments')
            value.update(text=text, returned_chars=len(text), pagination=pagination)
            body = types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(value, ensure_ascii=False))], structuredContent=value, isError=False)
            size = len(body.model_dump_json(by_alias=True, exclude_none=True).encode())
            if size <= 10000 and (best is None or size > best[0]):
                best = (size, n, suffix, data, text, pagination)
    assert best is not None and best[0] > 9950
    return best

class Response:
    status = 200
    def __init__(self, data):
        import io
        self.body = io.BytesIO(json.dumps(data, ensure_ascii=False).encode())
        self.headers = {'Link': ''}
    def read1(self, size): return self.body.read(size)
    def __enter__(self): return self
    def __exit__(self, *args): pass

class Transport:
    def __init__(self, data):
        self.data = data
        self.auth_calls = self.requests = 0
        self.emit()
    def emit(self): save('transport.json', {'auth_calls': self.auth_calls, 'requests': self.requests})
    def auth(self):
        self.auth_calls += 1
        self.emit()
        return 'synthetic-private-credential'
    def open(self, request, timeout):
        self.requests += 1
        self.emit()
        assert request.get_method() == 'GET'
        assert request.full_url == 'https://st-api.yandex-team.ru/v2/issues/TEST-1/comments?perPage=20'
        assert request.get_header('Authorization') == 'OAuth synthetic-private-credential'
        return Response(self.data)

def server():
    import socket
    from mcp.server.stdio import stdio_server
    def denied(*args, **kwargs):
        raise AssertionError('offline qualification forbids real network/native commands')
    socket.socket.connect = denied
    socket.create_connection = denied
    s = load()
    save('server-identity.json', {'source_sha256': hashlib.sha256((SOURCE / 'sidecar.py').read_bytes()).hexdigest(), 'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    s.run_cli = denied
    s.TrackerAPI._credential = staticmethod(denied)
    chosen = make_input(s)
    transport = Transport(chosen[3])
    sdk = s.build_server(s.ReadService(runner=denied, tracker_api=s.TrackerAPI(auth_reader=transport.auth, opener=transport)))
    async def run():
        async with stdio_server() as (read, write):
            await sdk.run(read, write, sdk.create_initialization_options())
    try:
        asyncio.run(run())
    finally:
        pager = s._pager()
        if pager._STORE is not None: pager._STORE.close()

def proxy():
    child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), 'server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, env=os.environ.copy())
    def feed():
        try:
            while line := sys.stdin.buffer.readline():
                child.stdin.write(line)
                child.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try: child.stdin.close()
            except BrokenPipeError: pass
    threading.Thread(target=feed, daemon=True).start()
    with (OUT / 'frames.jsonl').open('w') as out:
        while line := child.stdout.readline():
            message = json.loads(line)
            result = message.get('result', {})
            meta = {'id': message.get('id'), 'frame_bytes': len(line), 'json_without_lf_bytes': len(line.rstrip(b'\n')), 'sha256': hashlib.sha256(line).hexdigest(), 'tool_result': 'structuredContent' in result}
            if meta['tool_result']:
                meta['compact_result_bytes'] = len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode())
                meta['typed_page'] = 'format' in result['structuredContent'].get('pagination', {})
            out.write(json.dumps(meta) + '\n')
            out.flush()
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
    sys.exit(child.wait())

def rebuild(records):
    root = None
    for record in records:
        path, value = record['path'], record['value']
        if not path:
            root = value
            continue
        if root is None: root = [] if isinstance(path[0], int) else {}
        parent = root
        for i, part in enumerate(path):
            if isinstance(parent, list):
                while len(parent) <= part: parent.append(None)
            if i == len(path) - 1:
                if 'string_offset' in record:
                    previous = parent[part] if isinstance(parent, list) or part in parent else ''
                    previous = previous or ''
                    assert len(previous) == record['string_offset']
                    parent[part] = previous + value
                else: parent[part] = value
            else:
                if (isinstance(parent, dict) and part not in parent) or parent[part] is None:
                    parent[part] = [] if isinstance(path[i+1], int) else {}
                parent = parent[part]
    return root

async def exercise():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    s = load()
    chosen = make_input(s)
    env = {k: os.environ[k] for k in ('HOME', 'HERMES_HOME', 'TMPDIR', 'PATH', 'LANG', 'PYTHONDONTWRITEBYTECODE', 'ATLAS_TEST_SOURCE', 'ATLAS_TEST_OUTPUT')}
    params = StdioServerParameters(command=sys.executable, args=['-B', str(Path(__file__).resolve()), 'proxy'], env=env, cwd=os.environ['HERMES_HOME'])
    pages = []
    records = []
    with (OUT / 'stdio-stderr.log').open('w') as err:
        async with stdio_client(params, errlog=err) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool = next(t for t in tools.tools if t.name == 'tracker_read')
                save('stdio-discovery.json', tool.model_dump(mode='json', by_alias=True, exclude_none=True))
                args = {'key': 'TEST-1', 'view': 'comments', 'max_chars': 12000}
                while True:
                    reply = await session.call_tool('tracker_read', args)
                    page = reply.structured_content
                    assert page['ok'], page.get('code')
                    assert json.loads(reply.content[0].text) == page
                    assert len(page['text']) <= 12000
                    pagination = page.get('pagination', {})
                    typed = 'format' in pagination
                    pages.append({'typed': typed, 'returned_chars': page['returned_chars']})
                    if not typed:
                        reconstructed = json.loads(page['text'])
                        break
                    assert pagination['upstream'] == chosen[5]
                    assert pagination['capture_complete'] == (not pagination['has_more'])
                    assert pagination['complete'] == (not pagination['has_more'] and chosen[5]['complete'])
                    records.extend(json.loads(page['text'])['records'])
                    if not pagination['has_more']:
                        reconstructed = rebuild(records)
                        break
                    args['cursor'] = pagination['cursor']
                    assert len(pages) < 1000
    exact = json.dumps(reconstructed, ensure_ascii=False) == chosen[4]
    metrics = json.loads((OUT / 'transport.json').read_text())
    frames = [json.loads(line) for line in (OUT / 'frames.jsonl').read_text().splitlines()]
    tool_frames = [f for f in frames if f['tool_result']]
    within = bool(tool_frames) and all(f['frame_bytes'] <= 10000 for f in tool_frames)
    evidence = {'case': 'synthetic_TEST-1_unicode_near_threshold', 'chosen_body_bytes': chosen[0], 'unicode_count': chosen[1], 'ascii_suffix_chars': len(chosen[2]), 'pages': pages, 'safe_equality': exact, 'expected_safe_sha256': hashlib.sha256(chosen[4].encode()).hexdigest(), 'transport': metrics, 'tool_frame_sizes': [f['frame_bytes'] for f in tool_frames], 'all_tool_frames_within_10000': within, 'source_sha256': hashlib.sha256((SOURCE / 'sidecar.py').read_bytes()).hexdigest()}
    save('stdio-evidence.json', evidence)
    assert exact, 'safe projection not reconstructed byte-exactly'
    identity = json.loads((OUT / 'server-identity.json').read_text())
    assert identity['source_sha256'] == evidence['source_sha256'], 'child source binding changed'
    assert identity['harness_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'child harness binding changed'
    assert metrics == {'auth_calls': 1, 'requests': 1}, 'continuation reread/authenticated upstream'
    assert within, 'actual JSON-RPC stdout frame exceeds advertised 10000 bytes'
    print(json.dumps(evidence, indent=2))

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'test'
    {'server': server, 'proxy': proxy, 'test': lambda: asyncio.run(exercise())}[mode]()
