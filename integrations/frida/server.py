from __future__ import annotations

import base64
import math
import os
import struct
import threading
from typing import Literal

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict
from tokenizers import Tokenizer

MODEL_ID = "ai-forever/FRIDA"
DIMENSIONS = 1536
PROMPT = "search_document: "
MAX_LENGTH = 512
CONTRACT_ID = "frida-850455b6-document-mean-l2-frida512-overlap20-v2"

app = FastAPI(title="klin-frida", docs_url=None, redoc_url=None)
_load_lock = threading.Lock()
_tokenizer: Tokenizer | None = None
_validation_tokenizer: Tokenizer | None = None
_session: ort.InferenceSession | None = None
_load_error: str | None = None


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str | list[str]
    model: Literal["ai-forever/FRIDA", "frida"] = "frida"
    encoding_format: Literal["float", "base64"] | None = None
    dimensions: int | None = None


def load_model() -> None:
    global _tokenizer, _validation_tokenizer, _session, _load_error
    if _session is not None or _load_error is not None:
        return
    with _load_lock:
        if _session is not None or _load_error is not None:
            return
        try:
            model_path = os.environ.get(
                "FRIDA_MODEL_PATH", "/opt/frida/frida-encoder-int8.onnx"
            )
            tokenizer_path = os.environ.get(
                "FRIDA_TOKENIZER_PATH", "/opt/frida/tokenizer.json"
            )
            validation_tokenizer = Tokenizer.from_file(tokenizer_path)
            tokenizer = Tokenizer.from_file(tokenizer_path)
            tokenizer.enable_truncation(max_length=MAX_LENGTH)
            tokenizer.enable_padding(pad_id=0, pad_token="<pad>")
            session = ort.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"],
            )
            _tokenizer = tokenizer
            _validation_tokenizer = validation_tokenizer
            _session = session
        except Exception as exc:  # health: allow BLE001 -- readiness and 503 expose error type without private model paths
            _load_error = type(exc).__name__


def embed(texts: list[str]) -> list[list[float]]:
    if _tokenizer is None or _session is None:
        raise RuntimeError("FRIDA model is not loaded")
    encodings = _tokenizer.encode_batch([PROMPT + text for text in texts])
    input_ids = np.asarray([encoding.ids for encoding in encodings], dtype=np.int64)
    attention_mask = np.asarray(
        [encoding.attention_mask for encoding in encodings], dtype=np.int64
    )
    vectors = _session.run(
        ["embedding"],
        {"input_ids": input_ids, "attention_mask": attention_mask},
    )[0]
    return np.asarray(vectors, dtype=np.float32).tolist()


def validate_input_lengths(texts: list[str]) -> list[int]:
    if _validation_tokenizer is None:
        raise RuntimeError("FRIDA validation tokenizer is not loaded")
    token_counts = [
        len(encoding.ids)
        for encoding in _validation_tokenizer.encode_batch(
            [PROMPT + text for text in texts]
        )
    ]
    for index, token_count in enumerate(token_counts):
        if token_count > MAX_LENGTH:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "input_too_long",
                    "input_index": index,
                    "actual_tokens": token_count,
                    "max_tokens": MAX_LENGTH,
                },
            )
    return token_counts


@app.on_event("startup")
def startup() -> None:
    load_model()


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok" if _session is not None else "error",
        "model": MODEL_ID,
        "backend": "onnxruntime-int8-cpu",
        "dimensions": DIMENSIONS,
        "embedding_contract": CONTRACT_ID,
        "max_input_tokens": MAX_LENGTH,
        "input_prefix": PROMPT,
        "truncation": "reject",
        "model_loaded": _session is not None,
        "load_error": _load_error,
    }


@app.get("/v1/models")
def models() -> dict[str, object]:
    return {
        "object": "list",
        "data": [{"id": "frida", "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingRequest) -> dict[str, object]:
    load_model()
    if _session is None:
        raise HTTPException(status_code=503, detail="FRIDA model unavailable")
    texts = [request.input] if isinstance(request.input, str) else request.input
    if not texts or any(not isinstance(text, str) or not text for text in texts):
        raise HTTPException(
            status_code=400, detail="input must contain non-empty strings"
        )
    if request.dimensions is not None and request.dimensions != DIMENSIONS:
        raise HTTPException(
            status_code=400, detail=f"dimensions must equal {DIMENSIONS}"
        )
    validate_input_lengths(texts)
    vectors = embed(texts)
    if any(
        len(vector) != DIMENSIONS
        or not any(value != 0.0 for value in vector)
        or not all(math.isfinite(value) for value in vector)
        for vector in vectors
    ):
        raise HTTPException(status_code=500, detail="invalid FRIDA embedding")
    encoding_format = request.encoding_format or "float"
    encoded_vectors: list[list[float]] | list[str] = vectors
    if encoding_format == "base64":
        encoded_vectors = [
            base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")
            for vector in vectors
        ]
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(encoded_vectors)
        ],
        "model": "frida",
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }
