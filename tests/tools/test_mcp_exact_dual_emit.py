"""Dual-emitted MCP payloads may be removed only on lossless JSON equality."""
import json
from types import SimpleNamespace

import pytest

from tools.mcp_tool_handlers import _render_call_tool_result


@pytest.mark.parametrize(("text", "structured"), [
    ('{"value": 1}', {"value": True}),
    ('{"value": 1.0000000000000001}', {"value": 1.0}),
    ('{"value": -0.0}', {"value": 0.0}),
])
def test_distinct_json_values_preserve_structured_payload(text, structured):
    result = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                             structuredContent=structured, isError=False, meta=None)
    rendered = json.loads(_render_call_tool_result(result, "fixture"))
    assert rendered["structuredContent"] == structured
    assert rendered["result"] == text


@pytest.mark.parametrize(("text", "structured"), [
    ('{ "x": [1, "a"] }', {"x": [1, "a"]}),
    ('plain string', {"result": "plain string"}),
])
def test_exact_dual_emit_retains_all_text_blocks_without_duplicate(text, structured):
    result = SimpleNamespace(content=[SimpleNamespace(type="text", text="status"),
                                      SimpleNamespace(type="text", text=text)],
                             structuredContent=structured, isError=False, meta=None)
    rendered = json.loads(_render_call_tool_result(result, "fixture"))
    assert "structuredContent" not in rendered
    assert rendered["result"] == "status\n" + text
