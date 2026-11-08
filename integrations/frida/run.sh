#!/usr/bin/env bash
# Entrypoint for Klin FRIDA ONNX INT8 embedder used by Honcho.
# Stays in foreground so launchd can supervise it.
set -euo pipefail

cd "$(dirname "$0")"
export FRIDA_MODEL_PATH="${FRIDA_MODEL_PATH:-$PWD/model/frida-encoder-int8.onnx}"
export FRIDA_TOKENIZER_PATH="${FRIDA_TOKENIZER_PATH:-$PWD/model/tokenizer.json}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

exec ./venv/bin/uvicorn server:app \
  --host 127.0.0.1 \
  --port 8001 \
  --workers "${FRIDA_WORKERS:-1}" \
  --no-access-log
