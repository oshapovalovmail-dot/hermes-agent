# Optional FRIDA CPU embedding service

This is the operator-owned HTTP serving code used with the separately
published FRIDA ONNX INT8 model. It is not an installed Hermes plugin and is
never started automatically. Weights, model caches, private service settings,
launchd units, credentials and backfill data are deliberately absent.

The model must already contain masked mean pooling and L2 normalization.
The server adds `search_document: `, rejects inputs exceeding 512 total tokens,
and exposes the unchanged
`frida-850455b6-document-mean-l2-frida512-overlap20-v2` contract with 1536 dimensions.
`overlap20` is a downstream document-chunking policy, not an encoder operation.
There is no provider fallback and no paid API request.

## Standalone setup

Use Python 3.12 and a dedicated virtual environment, outside the Hermes runtime.
The dependency lock originated from the Linux CPU deployment; the actual server
contract is also exercised on macOS with ONNX Runtime 1.19.2.

```sh
uv venv --python 3.12 venv
uv pip install --python venv/bin/python -r requirements-runtime.lock
```

Supply the separately released `frida-encoder-int8.onnx`, its adjacent
`frida-encoder-int8.onnx.data`, and `tokenizer.json`. Verify their published
checksums before use. Set `FRIDA_MODEL_PATH` and `FRIDA_TOKENIZER_PATH` to the
verified files. No model is downloaded implicitly.

From this directory, on an unused local port:

```sh
FRIDA_MODEL_PATH="$MODEL_DIR/frida-encoder-int8.onnx" \
FRIDA_TOKENIZER_PATH="$MODEL_DIR/tokenizer.json" \
venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 18001 --workers 1
```

`MODEL_DIR` is the directory containing that verified model release.
`run.sh` preserves the original standalone launcher on port 8001; run it with
`bash run.sh` only on a host where that port is free. Neither command is a
Hermes gateway restart or a service installation. Do not expose this unauthenticated
endpoint outside loopback.

## Readiness and requests

`GET /health` reports `model_loaded`, the contract, dimensions, limit and the
load-error **type**. Check `model_loaded == true`, not merely HTTP status 200.
A failed model load returns 503 from `POST /v1/embeddings`; raw local model paths
are not included in the transport error. Oversized input is rejected with 400
before inference. Both OpenAI-compatible float and base64 float32 encodings are
supported. The accepted model aliases are `frida` and `ai-forever/FRIDA`; neither
selects a different model. The response model name is always `frida`.

## Tests

The standard Hermes runner preserves only the explicitly allowlisted,
non-secret `FRIDA_CONTRACT_MODEL_DIR` fixture location. With the optional test
dependencies installed through PM and the verified model directory supplied:

```sh
FRIDA_CONTRACT_MODEL_DIR="$MODEL_DIR" \
bash scripts/run_tests.sh tests/integrations/test_frida_service_contract.py -j 1
```

Run that command from the repository root. The suite executes real ONNX inference,
ASGI requests, normalization and binary-encoding checks, plus overflow-before-
inference and missing-model privacy failures. It creates its own in-process
application; it does not contact or modify an already running embedding service.
Without the optional dependencies/model fixture these hardware-dependent tests
are explicitly skipped, not counted as inference acceptance.

The source adaptation preserves the original serving behavior, with a typed
float32 conversion and formatting adjustments. Provenance hashes distinguish
the original local source from the adapted public files.
