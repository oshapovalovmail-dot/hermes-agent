"""Bounded YT metadata + official server-side MCP static data reads.

The authenticated caller's root allowlist belongs in the parent pre-tool guard.
No caller-controlled argv/config/SQL/attribute selectors; no transactions/locks.
"""
import ast
import json
import math
import os
import re
import selectors
import signal
import subprocess
import time
from typing import Literal, TypedDict

YT_BINARY = '/usr/bin/false'
MCP_BINARY = '/usr/bin/false'
Scalar = str | int | float | bool | None
Row = dict[str, Scalar]


class ReadResult(TypedDict, total=False):
    ok: bool
    code: str
    message: str
    source: dict
    text: str
    data: list[Row] | None
    pagination: dict


MAX_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 45
# Snapshot transaction/lock is a separate switch from retry enable in this build.
# Standard front selection; server redirects may still require a supported TLS route.
CLI_CONFIG = ('{read_retries={enable=%false;create_transaction_and_take_snapshot_lock=%false;};'
              'read_parallel={enable=%false;};'
              'proxy={enable_proxy_discovery=%false;prefer_https=%true;request_timeout=15000;retries={count=1;};};}')
SAMPLE_PATH = '//sys/spark/examples/example_1'
CLUSTER_PATH = '//sys/@cluster_name'
KNOWN_CLUSTERS = frozenset({'hahn', 'arnold', 'vanga', 'markov', 'freud', 'kolmogorov'})
ATTRIBUTES = ('type', 'account', 'dynamic', 'row_count', 'chunk_count',
              'compressed_data_size', 'uncompressed_data_size', 'sorted',
              'creation_time', 'modification_time')
BLOCKED_NAME = re.compile(r'(token|oauth|credential|password|passwd|secret|cookie|csrf|mail|calendar|passport|personal|(?:^|[_/.-])(?:authorization|auth)(?:$|[_/.-]))', re.I)
NUMERIC_METRICS = frozenset({'input_tokens', 'output_tokens', 'total_tokens', 'prompt_tokens', 'completion_tokens', 'cached_tokens'})
COLUMN_PATTERN = r'[A-Za-z_][A-Za-z0-9_]{0,127}'
PATH_PATTERN = r'(?://[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*|//sys/@cluster_name)'
CLUSTER_PATTERN = r'(?:hahn|arnold|vanga|markov|freud|kolmogorov|[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\.yt\.yandex\.net)'
ENV_KEYS = ('HOME', 'USER', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR')
INTEGER_TYPES = frozenset({'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64', 'date', 'datetime', 'timestamp', 'interval'})
FLOAT_TYPES = frozenset({'float', 'double'})
STRING_TYPES = frozenset({'string', 'utf8'})
SCALAR_TYPES = INTEGER_TYPES | FLOAT_TYPES | STRING_TYPES | {'boolean', 'bool', 'null', 'void'}
INPUT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['operation', 'cluster', 'path'],
    'properties': {
        'operation': {'type': 'string', 'enum': ['exists', 'attributes', 'list', 'sample', 'schema']},
        'cluster': {'type': 'string', 'maxLength': 100, 'pattern': '^' + CLUSTER_PATTERN + '$',
                    'description': 'Known short proxy or canonical single-label *.yt.yandex.net; preserved verbatim.'},
        'path': {'type': 'string', 'pattern': '^' + PATH_PATTERN + '$', 'maxLength': 512,
                 'description': 'Normal nonsensitive Cypress path, without selectors/attributes (except //sys/@cluster_name). Parent authenticated guard enforces guest roots; native ACLs apply.'},
        'columns': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'uniqueItems': True,
                    'items': {'type': 'string', 'pattern': '^' + COLUMN_PATTERN + '$', 'maxLength': 128},
                    'description': 'Required for sample: explicit safe scalar columns, validated against native schema. Token-count metrics must be numeric; secret/mail/calendar columns forbidden.'},
        'row_start': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000, 'default': 0},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 20},
        'max_chars': {'type': 'integer', 'minimum': 256, 'maximum': 12000, 'default': 12000},
    },
}


class ReadError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def safe_environment():
    """Forward baseline OS/locale only, never private auth/proxy/entrypoint env."""
    return {key: os.environ[key] for key in ENV_KEYS if key in os.environ}


def _unwrap(value):
    return value['$value'] if isinstance(value, dict) and '$value' in value else value


def _json(raw):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ReadError('INVALID_RESPONSE') from None


def _safe_column_name(name):
    return (type(name) is str and re.fullmatch(COLUMN_PATTERN, name) is not None
            and (name in NUMERIC_METRICS or not BLOCKED_NAME.search(name)))


def _column_type(column):
    """Normalize only primitive/optional primitive native schema, not expressions."""
    typ = _unwrap(column.get('type_v3', column.get('type')))
    nullable = False if 'type_v3' in column else column.get('required') is not True
    if type(typ) is dict and typ.get('type_name') == 'optional':
        typ, nullable = _unwrap(typ.get('item')), True
    if type(typ) is not str or typ not in SCALAR_TYPES:
        typ = 'unsupported'
    if column.get('name') in NUMERIC_METRICS and typ not in INTEGER_TYPES | FLOAT_TYPES:
        raise ReadError('UNSAFE_COLUMN')
    return typ, nullable


def _valid_value(value, typ, nullable):
    if value is None:
        return nullable or typ in ('null', 'void')
    if typ in INTEGER_TYPES:
        return type(value) is int and (not typ.startswith('uint') or value >= 0)
    if typ in FLOAT_TYPES:
        return type(value) in (int, float) and math.isfinite(value)
    if typ in STRING_TYPES:
        return type(value) is str
    if typ in ('boolean', 'bool'):
        return type(value) is bool
    return False


def _parse_mcp_rows(raw: bytes) -> list[Row]:
    """Decode the observed native RPC -> JSON string -> literal-list carrier.

    No eval, object construction, arbitrary names, executable expressions or
    alternate guessed wrappers. Only true/false/null names are normalized.
    Returned keys/types are separately checked against the projected schema.
    """
    rpc = _json(raw)
    if type(rpc) is not dict:
        raise ReadError('INVALID_RESPONSE')
    if 'error' in rpc:
        raise ReadError('REMOTE_ERROR')
    result = rpc.get('result')
    if type(result) is not dict:
        raise ReadError('INVALID_RESPONSE')
    if result.get('isError') is True:
        raise ReadError('REMOTE_ERROR')
    content = result.get('content')
    if (result.get('isError') is not False or type(content) is not list or len(content) != 1
            or type(content[0]) is not dict or content[0].get('type') != 'text'
            or type(content[0].get('text')) is not str):
        raise ReadError('INVALID_RESPONSE')
    literal = _json(content[0]['text'])
    if type(literal) is not str:
        raise ReadError('INVALID_RESPONSE')
    try:
        tree = ast.parse(literal, mode='eval')
        nodes = list(ast.walk(tree))
        if len(nodes) > 5000:
            raise ReadError('INVALID_RESPONSE')
        for node in nodes:
            if isinstance(node, ast.Name):
                if node.id not in ('true', 'false', 'null'):
                    raise ReadError('INVALID_RESPONSE')
                node.__class__ = ast.Constant
                node.value = {'true': True, 'false': False, 'null': None}[node.id]
            elif type(node) not in (ast.Expression, ast.List, ast.Dict, ast.Constant,
                                   ast.Load, ast.UnaryOp, ast.USub, ast.UAdd):
                raise ReadError('INVALID_RESPONSE')
        rows = ast.literal_eval(tree)
    except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
        raise ReadError('INVALID_RESPONSE') from None
    if type(rows) is not list:
        raise ReadError('INVALID_RESPONSE')
    return rows


class Backend:
    def _run(self, argv, deadline, byte_budget=None):
        """Read <=2MiB combined stdout/stderr; no files or raw errors retained."""
        if time.monotonic() >= deadline:
            raise ReadError('TIMEOUT')
        proc = None
        chunks = []
        total = 0
        if byte_budget is None:
            byte_budget = [MAX_BYTES]
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True, env=safe_environment())
            with selectors.DefaultSelector() as selector:
                for stream in (proc.stdout, proc.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ReadError('TIMEOUT')
                    for key, _ in selector.select(min(remaining, 0.2)):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        byte_budget[0] -= len(chunk)
                        if total > MAX_BYTES or byte_budget[0] < 0:
                            raise ReadError('OUTPUT_LIMIT')
                        if key.fileobj is proc.stdout:
                            chunks.append(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReadError('TIMEOUT')
            try:
                code = proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise ReadError('TIMEOUT') from None
            if code:
                raise ReadError('NATIVE_ERROR')
            return b''.join(chunks)
        except OSError:
            raise ReadError('NATIVE_UNAVAILABLE') from None
        finally:
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                proc.stdout.close()
                proc.stderr.close()

    def read(self, operation: Literal['exists', 'attributes', 'list', 'sample', 'schema'],
             cluster: str, path: str, columns: list[str] | None = None,
             row_start: int = 0, limit: int = 20, max_chars: int = 12000,
             **unknown: object) -> ReadResult:
        source = {'system': 'yt'}
        try:
            if unknown or type(operation) is not str or operation not in INPUT_SCHEMA['properties']['operation']['enum']:
                raise ReadError('INVALID_INPUT')
            if type(cluster) is not str or len(cluster) > 100 or not re.fullmatch(CLUSTER_PATTERN, cluster):
                raise ReadError('INVALID_INPUT')
            if type(path) is not str or len(path) > 512 or not re.fullmatch(PATH_PATTERN, path) or BLOCKED_NAME.search(path):
                raise ReadError('INVALID_INPUT')
            for value, low, high in ((limit, 1, 20), (row_start, 0, 1000000000), (max_chars, 256, 12000)):
                if type(value) is not int or not low <= value <= high:
                    raise ReadError('INVALID_INPUT')
            if operation == 'sample':
                if (path == CLUSTER_PATH or type(columns) is not list or not 1 <= len(columns) <= 20
                        or not all(_safe_column_name(c) for c in columns) or len(set(columns)) != len(columns)):
                    raise ReadError('INVALID_INPUT')
            elif columns is not None or row_start != 0:
                raise ReadError('INVALID_INPUT')
            if path == CLUSTER_PATH and operation not in ('attributes', 'exists'):
                raise ReadError('INVALID_INPUT')
            source.update(cluster=cluster, path=path, operation=operation)
            if columns is not None:
                source['columns'] = columns.copy()
            deadline = time.monotonic() + TIMEOUT_SECONDS
            base = [YT_BINARY, '--proxy', cluster, '--tx', '0-0-0-0', '--config', CLI_CONFIG]
            used_bytes = 0
            byte_budget = [MAX_BYTES]

            def invoke(args):
                nonlocal used_bytes
                raw = self._run(base + args, deadline, byte_budget)
                used_bytes += len(raw)
                if used_bytes > MAX_BYTES:
                    raise ReadError('OUTPUT_LIMIT')
                return raw

            pagination = None
            if operation == 'exists':
                raw = invoke(['exists', path]).strip()
                if raw not in (b'true', b'false'):
                    raise ReadError('INVALID_RESPONSE')
                data = {'exists': raw == b'true'}
            elif operation == 'attributes':
                if path == CLUSTER_PATH:
                    value = _json(invoke(['get', path, '--format', 'json']))
                    if type(value) is not str or not re.fullmatch(r'[a-z0-9-]{1,64}', value):
                        raise ReadError('INVALID_RESPONSE')
                    data = {'cluster_name': value}
                else:
                    argv = ['get', path + '/@', '--format', 'json']
                    for attribute in ATTRIBUTES:
                        argv.extend(['--attribute', attribute])
                    attrs = _unwrap(_json(invoke(argv)))
                    if type(attrs) is not dict:
                        raise ReadError('INVALID_RESPONSE')
                    data = {k: _unwrap(v) for k, v in attrs.items() if k in ATTRIBUTES}
                    if any(type(v) not in (str, int, bool, type(None)) for v in data.values()):
                        raise ReadError('INVALID_RESPONSE')
            elif operation == 'list':
                obj = _json(invoke(['list', path, '--max-size', str(limit + 1), '--format', 'json']))
                incomplete = bool(obj.get('$attributes', {}).get('incomplete', False)) if isinstance(obj, dict) else False
                entries = _unwrap(obj)
                if type(entries) is not list or len(entries) > limit + 1:
                    raise ReadError('INVALID_RESPONSE')
                names = [_unwrap(x) for x in entries]
                if any(type(x) is not str for x in names):
                    raise ReadError('INVALID_RESPONSE')
                visible = [name for name in names if not BLOCKED_NAME.search(name)]
                data = visible[:limit]
                pagination = {'limit': limit, 'returned_count': len(data),
                              'source_entries_received': len(names), 'has_more': incomplete or len(visible) > limit,
                              'hidden_count_in_page': len(names) - len(visible),
                              'next_row_start': None, 'stable_order': False}
            else:
                argv = ['get', path + '/@', '--format', 'json']
                for attribute in ('type', 'dynamic', 'row_count', 'schema'):
                    argv.extend(['--attribute', attribute])
                meta = _unwrap(_json(invoke(argv)))
                if type(meta) is not dict or _unwrap(meta.get('type')) != 'table':
                    raise ReadError('UNSAFE_TABLE')
                dynamic = _unwrap(meta.get('dynamic'))
                if type(dynamic) is not bool:
                    raise ReadError('INVALID_RESPONSE')
                if operation == 'sample' and dynamic:
                    raise ReadError('DYNAMIC_TABLE_UNSUPPORTED')
                schema = _unwrap(meta.get('schema'))
                if type(schema) is not list:
                    raise ReadError('UNSAFE_TABLE')
                by_name = {}
                for entry in schema:
                    column = _unwrap(entry)
                    if type(column) is not dict or type(column.get('name')) is not str or column['name'] in by_name:
                        raise ReadError('INVALID_RESPONSE')
                    by_name[column['name']] = column
                if operation == 'schema':
                    visible = []
                    for name, column in by_name.items():
                        if not _safe_column_name(name):
                            continue
                        try:
                            typ, nullable = _column_type(column)
                        except ReadError:
                            continue
                        item = {'name': name, 'type': typ, 'nullable': nullable,
                                'sample_supported': typ in SCALAR_TYPES}
                        if column.get('sort_order') in ('ascending', 'descending'):
                            item['sort_order'] = column['sort_order']
                        visible.append(item)
                    data = {'dynamic': dynamic, 'columns': visible[:limit]}
                    pagination = {'limit': limit, 'returned_count': len(data['columns']),
                                  'source_column_count': len(schema), 'hidden_count': len(schema)-len(visible),
                                  'has_more': len(visible) > limit, 'next_row_start': None}
                else:
                    count = _unwrap(meta.get('row_count'))
                    if type(count) is not int or count < 0:
                        raise ReadError('INVALID_RESPONSE')
                    selected = {}
                    for name in columns:
                        if name not in by_name:
                            raise ReadError('UNKNOWN_COLUMN')
                        typ, nullable = _column_type(by_name[name])
                        if typ not in SCALAR_TYPES:
                            raise ReadError('UNSUPPORTED_COLUMN_TYPE')
                        selected[name] = (typ, nullable)
                    ypath = path + '{' + ','.join(columns) + '}[#' + str(row_start) + ':#' + str(row_start + limit) + ']'
                    source['data_transport'] = 'official_yt_mcp'
                    raw = self._run([MCP_BINARY, 'connect', 'yt', '--tool',
                        'common_client_sample_static_table', '--arg', 'cluster:' + cluster,
                        '--arg', 'method:read_table', '--arg', 'table:' + ypath, '--raw'],
                        deadline, byte_budget)
                    rows = _parse_mcp_rows(raw)
                    data = []
                    for row in rows:
                        if type(row) is not dict or set(row) != set(columns) or any(
                                not _valid_value(row[name], *selected[name]) for name in columns):
                            raise ReadError('INVALID_RESPONSE')
                        data.append(row)
                        if len(data) > limit:
                            raise ReadError('INVALID_RESPONSE')
                    next_row = row_start + len(data)
                    pagination = {'row_start': row_start, 'limit': limit, 'returned_count': len(data),
                                  'source_row_count': count, 'has_more': next_row < count,
                                  'next_row_start': next_row if data and next_row < count else None,
                                  'snapshot_consistent': False}
            text = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars - 14] + '\n[TRUNCATED]'
            if pagination is not None:
                pagination['text_truncated'] = truncated
            result = {'ok': True, 'code': 'OK', 'message': 'Read completed' + ('; text truncated' if truncated else ''),
                      'source': source, 'text': text}
            if pagination is not None:
                result['pagination'] = pagination
            if operation == 'sample':
                result['data'] = None if truncated else data
            return result
        except ReadError as exc:
            return {'ok': False, 'code': exc.code, 'message': 'YT read rejected or unavailable; raw diagnostics suppressed',
                    'source': source, 'text': ''}
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            return {'ok': False, 'code': 'INVALID_RESPONSE', 'message': 'Invalid native response; raw diagnostics suppressed',
                    'source': source, 'text': ''}
