"""Lossless arbitration of MCP's backwards-compatible JSON dual emission."""

import json


def _exact_json(text):
    # Keep number spellings, signs and types instead of rounding through float.
    # Tagged numbers cannot collide with JSON arrays, strings or booleans.
    return json.loads(
        text,
        parse_int=lambda value: ("int", value),
        parse_float=lambda value: ("float", value),
    )


def content_duplicates_structured(content, structured) -> bool:
    """Only suppress structured data when a complete text block carries the same JSON."""
    try:
        canonical = _exact_json(json.dumps(structured, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        return False
    for block in content or []:
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        # FastMCP wraps a scalar string return in a single-key structured object.
        if structured == {"result": text}:
            return True
        try:
            if _exact_json(text) == canonical:
                return True
        except (TypeError, ValueError, RecursionError):
            continue
    return False
