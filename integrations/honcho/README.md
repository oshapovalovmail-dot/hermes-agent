# Honcho exact-tokenizer / bounded-batch patch

This directory is a separate AGPL-3.0 integration artifact, not Hermes core code.
The patch and its modifications are provided under the included Honcho `LICENSE`
(GNU Affero General Public License version 3). Upstream project:
<https://github.com/plastic-labs/honcho>. Copyright notices in the upstream source
remain in effect. This export was prepared/modified on 2026-11-08. Distribution
or running a modified network service may impose corresponding-source duties;
read the included license before deployment.

## Provenance

- Actual immutable source base: `2ad56a4d715b015d744ea86f05a287069d264898`.
- Patch is the exact staged/index diff against that base for these four files:
  `pyproject.toml`, `src/config.py`, `src/embedding_client.py`,
  `tests/llm/test_embedding_client.py`.
- SHA-256 of `exact-tokenizer.patch`:
  `0d79b7ab0597d24d7c50e8218484b557c75dba8607c8f64f2ddd841586e8dde8`.
- No service source dump, `.env`, service configuration, state, DB, logs, recovery
  scripts, model weights/tokenizer assets or personal paths are included.
- The separate staged `uv.lock` is deliberately not exported. Before any later
  deployment, regenerate/verify the dependency lock in a disposable Honcho checkout;
  do not pretend this four-file patch is a frozen full deployment environment.

The service-side changes add exact Hugging Face tokenizer accounting with an
operator-supplied tokenizer file, optional input-prefix accounting, source-preserving
chunking with configurable overlap, and bounded batch concurrency. The prefix is
for **accounting** for a provider that prepends it; this patch does not itself
prepend that prefix to outgoing strings. Defaults retain tiktoken behavior.
Nothing downloads a tokenizer or starts an embedding service.

## Verification without service access

`verify_patch.py` requires an explicit local Git source containing the base object
and a separate test interpreter. It reads only Git blobs, exports source into an
automatically removed temporary directory, applies/checks the exported patch, and
runs the actual patched embedding test module. It never imports the live checkout,
changes its index/worktree, starts Postgres/Redis/Honcho, or inherits API credentials.
Honcho's app/database conftests are intentionally excluded from this unit-only test.
Socket connections are denied in the test process.

Build a fresh PM-owned requirements environment containing pytest, pytest-asyncio,
tiktoken, tokenizers, nanoid, openai, google-genai, python-dotenv and pydantic-settings.
Seed only the public `cl100k_base` tiktoken encoding into a disposable cache during
setup, before enabling the test network fence. No HF weights are involved. Then:

```sh
TIKTOKEN_CACHE_DIR=/absolute/path/to/disposable/token-cache \
  python integrations/honcho/verify_patch.py \
    --source /absolute/path/to/read-only-honcho-git-checkout \
    --python /absolute/path/to/disposable-testenv/bin/python
```

Observed preparation run: **51 passed** on Python 3.14.9. This is mocked-provider
unit coverage plus real tokenizer operations, not a running-service acceptance test.
No production/GitHub/HF/QYP actions were taken.
