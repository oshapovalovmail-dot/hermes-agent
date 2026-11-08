"""Contract of the opt-in FRIDA HTTP service; no production service is used."""

import base64
import importlib.util
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def service():
    pytest.importorskip("onnxruntime")
    pytest.importorskip("fastapi")
    pytest.importorskip("tokenizers")
    model_dir = os.environ.get("FRIDA_CONTRACT_MODEL_DIR")
    if not model_dir:
        pytest.skip("set FRIDA_CONTRACT_MODEL_DIR to the verified offline artifact")
    root = Path(model_dir).resolve(strict=True)
    source = Path(__file__).resolve().parents[2] / "integrations/frida/server.py"
    spec = importlib.util.spec_from_file_location("frida_contract_service", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as modules:
        modules.setitem(sys.modules, spec.name, module)
        with pytest.MonkeyPatch.context() as settings:
            settings.setenv("FRIDA_MODEL_PATH", str(root / "frida-encoder-int8.onnx"))
            settings.setenv("FRIDA_TOKENIZER_PATH", str(root / "tokenizer.json"))
            spec.loader.exec_module(module)
            module.load_model()
        assert module.health()["model_loaded"] is True
        yield module


def test_http_embedding_is_normalized_and_base64_preserves_float_values(service):
    import numpy as np
    from fastapi.testclient import TestClient

    with TestClient(service.app) as client:
        plain = client.post(
            "/v1/embeddings", json={"input": "Как восстановить пароль?"}
        )
        encoded = client.post(
            "/v1/embeddings",
            json={
                "input": "Как восстановить пароль?",
                "encoding_format": "base64",
            },
        )
    assert plain.status_code == encoded.status_code == 200
    vector = np.asarray(plain.json()["data"][0]["embedding"], dtype=np.float32)
    decoded = np.frombuffer(
        base64.b64decode(encoded.json()["data"][0]["embedding"]), dtype="<f4"
    )
    assert vector.shape == (1536,)
    assert np.isfinite(vector).all()
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)
    np.testing.assert_array_equal(vector, decoded)


def test_http_overflow_is_rejected_before_inference(service, monkeypatch):
    from fastapi.testclient import TestClient

    def forbidden_inference(_texts):
        raise AssertionError("over-limit requests must not reach inference")

    monkeypatch.setattr(service, "embed", forbidden_inference)
    with TestClient(service.app) as client:
        response = client.post("/v1/embeddings", json={"input": "длинный текст " * 700})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "input_too_long"
    assert detail["actual_tokens"] > detail["max_tokens"] == 512


def test_health_reports_the_actual_mean_document_contract(service):
    from fastapi.testclient import TestClient

    with TestClient(service.app) as client:
        health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["dimensions"] == 1536
    assert health["input_prefix"] == "search_document: "
    assert health["truncation"] == "reject"
    assert (
        health["embedding_contract"]
        == "frida-850455b6-document-mean-l2-frida512-overlap20-v2"
    )


def test_load_failure_exposes_only_error_type_not_private_model_path(
    service, monkeypatch, tmp_path
):
    from fastapi.testclient import TestClient

    private_path = tmp_path / "private-model-path-that-must-not-be-returned"
    monkeypatch.setattr(service, "_session", None)
    monkeypatch.setattr(service, "_load_error", None)
    monkeypatch.setenv("FRIDA_TOKENIZER_PATH", str(private_path))
    with TestClient(service.app) as client:
        health = client.get("/health").json()
        response = client.post("/v1/embeddings", json={"input": "текст"})
    assert health["status"] == "error"
    assert health["model_loaded"] is False
    assert health["load_error"]
    assert str(private_path) not in str(health)
    assert response.status_code == 503
