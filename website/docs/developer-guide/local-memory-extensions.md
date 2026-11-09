---
title: "Local memory extensions"
description: "Opt-in pinned Honcho and OpenViking patches carried by this fork"
---

# Local memory extensions

This fork keeps current upstream's external-provider architecture: no provider source is bundled in core or `extensions/`, and existing installations are not activated or migrated.

## Complete optional deployment

For a new installation of **Honcho, OpenViking, or both with the local FRIDA
embedder**, start with the [complete memory-stack guide](https://github.com/oshapovalovmail-dot/hermes-agent/blob/main/integrations/memory-stack/README.md)
and `integrations/memory-stack/install.py`. This opt-in controller prepares an
isolated profile and owned Docker Compose project; existing profiles and
backends are not reused or modified. It covers model/source pins, credentials,
startup, causal checks, shutdown and troubleshooting. The lower-level installer
below only reconstructs plugin source and intentionally does not deploy services.

## Provenance and trust

`integrations/memory-providers/manifest.json` pins the public catalog repositories:

- Honcho: `plastic-labs/honcho`, commit `7dd3702933d5cc1ce1f0a44bba6525cc61ee6e16`, subdirectory `hermes-plugin-honcho`.
- OpenViking: `volcengine/OpenViking`, commit `e855796c83f9eb575d9b0f3082926660730f6a63`, subdirectory `examples/hermes-plugin`.

Only exact unified patches are carried here, along with MIT license notices. The installer reads immutable Git objects (not cache working files), checks a canonical path/content SHA-256 inventory, checks the patch SHA-256, runs `git apply --unidiff-zero --check`, applies it, and verifies the complete resulting inventory. Reviewed repository commits are the trust anchor; hashes stored with mutable code alone are not an authenticity guarantee.

The changes cover provenance-aware capture, thematic recall, complete-unit context budgets, startup-context suppression, bounded asynchronous writers, scoped conclusion handling, and authentication-error propagation. `agent.recall_query` is an additive public plugin API for deterministic continuation detection and lexical corroboration, not retrieval or permission inference.

## Reconstruct, then explicitly install into an isolated home

Prepare the checkout using the upstream PM developer workflow. From the checkout root, choose **new** staging/cache locations:

```bash
python integrations/memory-providers/install.py honcho \
  --fetch --source-cache /absolute/disposable-source-cache \
  --destination /absolute/new-memory-stage/honcho
python integrations/memory-providers/install.py openviking \
  --fetch --source-cache /absolute/disposable-source-cache \
  --destination /absolute/new-memory-stage/openviking
```

Network access is opt-in (`--fetch`); omit it to reconstruct fully offline from an existing cache containing those commit objects. Each provider cache is a Git repository named `honcho` or `openviking`. The installer refuses an existing destination, never merges provider trees, never installs dependencies, imports provider code, writes configuration, or starts a backend. Keep the manifest and patches from the same reviewed fork revision.

Review the reconstructed README/dependency declarations before taking the separate deployment step:

```bash
export HERMES_HOME="$HOME/hermes-fork-test-data"
mkdir -p "$HERMES_HOME/plugins"
test ! -e "$HERMES_HOME/plugins/honcho"
test ! -e "$HERMES_HOME/plugins/openviking"
cp -R /absolute/new-memory-stage/honcho "$HERMES_HOME/plugins/honcho"
cp -R /absolute/new-memory-stage/openviking "$HERMES_HOME/plugins/openviking"
hermes plugins enable honcho
hermes plugins enable openviking
```

Use normal PM dependency consent/setup, and provide credentials locally. Do not copy production config, databases, transcripts or credentials. Importability does not prove backend availability. Catalog updates do not preserve these patches: reconstruct the pinned reviewed versions again into fresh staging when needed.

The singular `memory.provider` remains the fallback. Ordered multi-provider fan-out is explicitly opted into:

```yaml
memory:
  providers:
    - honcho
    - openviking
```

Duplicates are ignored; registration order determines colliding-tool ownership. An empty list disables external providers. No runtime defaults are changed.

## Verification

Populate the disposable Git cache using the commands above (or a local clone containing each pin). Then use the canonical runner with a disposable PM-built test interpreter containing the optional Honcho/OpenViking SDKs:

```bash
HERMES_PYTHON=/absolute/test-environment/bin/python \
  bash scripts/run_tests.sh tests/extensions tests/integrations \
  tests/agent/test_memory_multi_provider_port.py -j 2 --file-timeout 150
```

The default offline fixture cache is `.provider-sources/`; override it with `--memory-source-cache /absolute/disposable-source-cache`. Acceptance reconstructs the same hash-validated provider bytes into temporary homes and loads through native discovery/manifest gates without relaxing private-import policy. Fixtures exercise SDK DTOs, OpenViking extraction, loopback HTTP capture/readback, scoped recall, queue/shutdown and auth failures. Optional native server tests explicitly skip if the dependency is absent; use the SDK-equipped interpreter for full acceptance. No live memory service or private conversation is used.


## Current-query recall and capture origin

Automatic Honcho retrieval binds the exact query and runtime thread to a generation.
A query/thread pivot invalidates pending base and dialectic results, including an
A-to-B-to-A pivot; at most one real worker per layer remains in flight. Generic
startup synthesis cannot stand in for the next request. Historical paragraphs need
lexical corroboration, remain complete under budgets, and never renew permission.

Capture snapshots trusted machine spans before provider redaction/background
dispatch. The native gateway's admitted internal envelope owns its payload; public
text prefixes do not. API self-posts additionally use exact, one-use in-process
capabilities after ordinary authentication/session admission, with no redirects.
Human neighboring text and canonical history are retained; provider capture DTOs
carry separate origin/scope and machine derivation is disabled. Multi-author routing,
a2a session isolation, transport retries and native automation validation stay intact.

OpenViking reads return per-document completeness, offsets and source hashes.
Follow each single-document continuation and assemble matching-hash ranges through
`total_chars` before claiming a full read. A partial range can omit scope/negation.

The explicit tools remain available for uncorroborated discovery. Persistent
Telegram composer keyboards require explicit chat IDs and rows; topic/retry routing
is unchanged. This is configuration, not a personal keyboard preset.
