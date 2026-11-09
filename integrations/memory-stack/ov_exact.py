"""Installer-owned OpenViking 0.4.15 FRIDA hook. Import performs no I/O.

Only install in the dedicated image, before server imports/worker startup.
Use max_input_tokens=EXACT_INPUT_SENTINEL in that image's embedding config.
Long-input pooling weights are original Python character lengths, not tree weights.
"""
import hashlib
import importlib.metadata
import math
import os
import sys
from pathlib import Path

EXACT_INPUT_SENTINEL = 2147483647
PREFIX = "search_document: "
LIMIT = 512
DIMENSION = 1536
_installed = None


def install(tokenizer_path, expected_sha256):
    """Register once in this process; no global package files are edited."""
    global _installed
    data = Path(tokenizer_path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise ValueError("FRIDA tokenizer SHA256 mismatch")
    if importlib.metadata.version("openviking") != "0.4.15":
        raise RuntimeError("Exact FRIDA hook requires OpenViking 0.4.15")
    if _installed:
        if _installed[0] != digest:
            raise RuntimeError("Different FRIDA tokenizer already installed")
        return _installed[1]
    # LiteLLM otherwise attempts a public model-cost-map fetch during OV import.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    from tokenizers import Tokenizer
    import openviking.models.embedder as registry
    from openviking.models.embedder.openai_embedders import OpenAIDenseEmbedder
    from openviking.models.embedder.base import EmbedResult
    import openviking.utils.embedding_input as input_guard

    tokenizer = Tokenizer.from_str(data.decode("utf-8"))
    tokenizer.no_truncation()
    tokenizer.no_padding()

    class ExactFridaEmbedder(OpenAIDenseEmbedder):
        """Preserve native SDK calls, retries, telemetry, limiter and DTOs."""

        def __init__(self, *args, **kwargs):
            model = kwargs.get("model_name", args[0] if args else None)
            if model != "frida" or kwargs.get("dimension") != DIMENSION:
                raise ValueError("Dedicated adapter requires frida, dimension=1536")
            if kwargs.get("query_param") or kwargs.get("document_param") or kwargs.get("extra_body"):
                raise ValueError("FRIDA prefix/body belongs to server, not caller parameters")
            if kwargs.get("encoding_format") != "float":
                raise ValueError("FRIDA requires explicit float encoding")
            if kwargs.get("provider", "openai") != "openai":
                raise ValueError("Dedicated adapter requires provider=openai")
            if (kwargs.get("config") or {}).get("max_input_tokens") != EXACT_INPUT_SENTINEL:
                raise ValueError("Use exact guard sentinel to prevent upstream truncation")
            super().__init__(*args, **kwargs)
            self.max_input_tokens = None

        @staticmethod
        def count_input(text):
            # Prefix is included only for accounting: server adds it exactly once.
            return len(tokenizer.encode(PREFIX + text, add_special_tokens=True).ids)

        def split_input(self, text):
            if not isinstance(text, str):
                raise TypeError("FRIDA embedding input must be text")
            stack, leaves = [text], []
            while stack:
                part = stack.pop()
                if self.count_input(part) <= LIMIT:
                    leaves.append(part)
                elif len(part) <= 1:
                    raise ValueError("Single Unicode character exceeds FRIDA input limit")
                else:
                    middle = len(part) // 2
                    # Slice original code points, never decode/re-encode token fragments.
                    stack.extend((part[middle:], part[:middle]))
            return leaves

        def _truncate_vector(self, vector):
            # Native OV silently truncates overlong dimensions; FRIDA must fail closed.
            if len(vector) != DIMENSION or any(not math.isfinite(x) for x in vector):
                raise ValueError("Invalid FRIDA embedding dimension or nonfinite value")
            if math.hypot(*vector) == 0:
                raise ValueError("Zero FRIDA embedding")
            return vector

        @staticmethod
        def _pool(parts, results):
            if len(results) == 1:
                return results[0]  # Preserve short-input vector and native DTO exactly.
            weighted = [math.fsum(len(p) * r.dense_vector[i]
                                  for p, r in zip(parts, results))
                        for i in range(DIMENSION)]
            norm = math.hypot(*weighted)
            if not math.isfinite(norm) or norm == 0:
                raise ValueError("Invalid or cancelling FRIDA weighted root sum")
            return EmbedResult(dense_vector=[v / norm for v in weighted])

        def embed(self, text, is_query=False):
            parts = self.split_input(text)
            # No outer retry/permit: only individual HTTP calls own retries/permits.
            results = [super(ExactFridaEmbedder, self).embed(p, is_query=is_query)
                       for p in parts]
            return self._pool(parts, results)

        async def embed_async(self, text, is_query=False):
            parts = self.split_input(text)
            results = []
            for part in parts:
                results.append(await super().embed_async(part, is_query=is_query))
            return self._pool(parts, results)

    # Bypass the heuristic ONLY for our explicit sentinel. Patch captured aliases
    # if already loaded; future import-from bindings get the replacement naturally.
    original = input_guard.truncate_embedding_input

    def preserve_exact_input(text, max_tokens, *args, **kwargs):
        if max_tokens == EXACT_INPUT_SENTINEL:
            return text
        return original(text, max_tokens, *args, **kwargs)

    for name in ("openviking.utils.embedding_input", "openviking.models.embedder.base",
                 "openviking.utils.embedding_utils", "openviking.service.reindex_executor"):
        module = sys.modules.get(name)
        if module is not None:
            module.truncate_embedding_input = preserve_exact_input
    # The real 0.4.15 factory imports this registry attribute at call time.
    registry.OpenAIDenseEmbedder = ExactFridaEmbedder
    _installed = (digest, ExactFridaEmbedder)
    return ExactFridaEmbedder
