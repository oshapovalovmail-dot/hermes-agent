"""Optional pinned-SDK contracts; fake HTTP is not live memory acceptance."""
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parents[2] / "integrations/memory-stack"


def test_adapter_import_is_lazy_and_offline(tmp_path):
    code = ("import socket,sys; from unittest.mock import patch; "
            "guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network')); "
            "guard.start(); import ov_exact; "
            "assert 'openviking' not in sys.modules and 'tokenizers' not in sys.modules")
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": str(HERE)},
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def native(tmp_path, monkeypatch):
    model = os.environ.get("MEMORY_STACK_TEST_TOKENIZER")
    if not model:
        pytest.skip("set MEMORY_STACK_TEST_TOKENIZER to the pinned FRIDA tokenizer.json")
    monkeypatch.syspath_prepend(str(HERE))
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    config = tmp_path / "ov.conf"
    config.write_text(json.dumps({"storage": {"workspace": str(tmp_path / "data")}}))
    monkeypatch.setenv("OPENVIKING_CONFIG_FILE", str(config))
    pytest.importorskip("openviking", exc_type=ImportError)
    tokenizers = pytest.importorskip("tokenizers")
    import httpx
    import openai
    from openviking.models.embedder.base import EmbedResult
    from openviking.models.embedder.openai_embedders import OpenAIDenseEmbedder
    hook = importlib.import_module("ov_exact")
    pins = json.loads((HERE / "pins.json").read_text())
    exact = hook.install(model, pins["assets"]["tokenizer.json"]["sha256"])
    tokenizer = tokenizers.Tokenizer.from_file(model)
    tokenizer.no_padding()
    tokenizer.no_truncation()
    calls = []
    vectors = {}

    def vector(text):
        raw = [float(n) - 127.5 for n in hashlib.sha256(text.encode()).digest()[:4]]
        norm = math.hypot(*raw)
        return [n / norm for n in raw] + [0.0] * 1532

    def count(text):
        return len(tokenizer.encode("search_document: " + text, add_special_tokens=True).ids)

    def reply(request):
        body = json.loads(request.content)
        text = body["input"]
        assert count(text) <= 512
        assert body == {"model": "frida", "input": text, "encoding_format": "float"}
        calls.append(text)
        response = {"object": "list", "model": "frida", "data": [
            {"object": "embedding", "index": 0, "embedding": vectors.get(text, vector(text))}]}
        return httpx.Response(200, content=json.dumps(response).encode(), headers={"Content-Type": "application/json"})

    def make(cls=exact):
        instance = cls(model_name="frida", api_base="http://fixture.invalid/v1", api_key="synthetic",
                       dimension=1536, encoding_format="float", config={"max_input_tokens": hook.EXACT_INPUT_SENTINEL,
                                                                      "max_concurrent": 1, "max_retries": 0})
        instance.client.close()
        instance.client = openai.OpenAI(api_key="synthetic", base_url="http://fixture.invalid/v1", max_retries=0,
                                       http_client=httpx.Client(transport=httpx.MockTransport(reply)))
        return instance

    instance = make()
    yield instance, calls, vectors, count, vector, make, OpenAIDenseEmbedder, EmbedResult
    instance.client.close()


def test_exact_boundary_and_unicode_preserve_every_character(native):
    instance, calls, _, count, *_ = native
    candidates = ["я " * n for n in range(1, 600)]
    boundary = next(text for text in candidates if count(text) == 512)
    instance.embed(boundary)
    assert calls == [boundary]
    for text in [next(text for text in candidates if count(text) == 513), "Жяъ😀e\u0301\x00\n" * 1500]:
        calls.clear()
        instance.embed(text)
        assert "".join(calls) == text
        assert all(count(part) <= 512 for part in calls)


def test_short_input_preserves_native_sdk_vector_and_dto(native):
    instance, _, vectors, _, _, make, stock, dto = native
    text = "Короткий текст 😀"
    vectors[text] = [0.3, 0.4] + [0.0] * 1534
    original = make(stock)
    try:
        for query in (False, True):
            result = instance.embed(text, is_query=query)
            assert isinstance(result, dto)
            assert result == original.embed(text, is_query=query)
    finally:
        original.client.close()


def test_long_input_matches_flat_original_character_weight_oracle(native):
    instance, calls, _, _, vector, *_ = native
    text = "".join(f"{n:04d} пример Жяъ😀 " for n in range(401))
    result = instance.embed(text)
    assert "".join(calls) == text and len(calls) > 1
    expected = [math.fsum(len(part) * vector(part)[i] for part in calls) for i in range(1536)]
    norm = math.hypot(*expected)
    assert max(abs(a - b / norm) for a, b in zip(result.dense_vector, expected)) < 1e-12


@pytest.mark.parametrize("bad", [[0.0] * 1536, [1.0] * 1535, [1.0] * 1537, [float("nan")] * 1536])
def test_invalid_native_sdk_vectors_fail_closed(native, bad):
    instance, _, vectors, *_ = native
    vectors["invalid"] = bad
    with pytest.raises(RuntimeError):
        instance.embed("invalid")
