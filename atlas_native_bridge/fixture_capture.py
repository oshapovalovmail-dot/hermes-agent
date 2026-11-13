"""Lossless, fixture-only diagnostic projections; no native imports or I/O."""
import json

REASONING_MARKER = 'NEVER_DELIVER_SYNTHETIC_REASONING'


def sdk_snapshot(sdk):
    """Retain exactly the JSON parameters observed by the SDK, in call order.

    Never coerce values with str/default=str: a non-JSON payload is a capture
    error, not a plausible-looking substitute for the wire parameters.
    """
    calls = []
    for endpoint, parameters in (() if sdk is None else sdk.calls):
        copied = json.loads(json.dumps(parameters, ensure_ascii=False, allow_nan=False))
        calls.append({'endpoint': endpoint, 'parameters': copied,
                      'parameter_types': {k: type(v).__name__ for k, v in parameters.items()}})
    return {'initialized': sdk is not None, 'count': len(calls), 'calls': calls,
            'synthetic_reasoning_marker_present': any(
                REASONING_MARKER in json.dumps(c['parameters'], ensure_ascii=False)
                for c in calls)}


def model_snapshot(llm):
    """Capture loopback request bodies, never HTTP auth/headers or real providers."""
    if llm is None:
        return {'initialized': False, 'total_request_count': 0,
                'main_request_count': 0, 'main_requests': []}
    with llm._lock:
        records = json.loads(json.dumps([
            {k: v for k, v in r.items() if k in ('path', 'kind', 'body', 't', 'response')}
            for r in llm.requests], ensure_ascii=False, allow_nan=False))
    main = [r['body'] for r in records if r['kind'] == 'main']
    return {'initialized': True, 'total_request_count': len(records),
            'main_request_count': len(main), 'main_requests': main,
            'request_metadata': [{k: v for k, v in r.items() if k != 'body'} for r in records]}
