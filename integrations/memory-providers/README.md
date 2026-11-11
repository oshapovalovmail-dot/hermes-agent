# Reviewed automatic-memory capture

This integration separates automatic long-term learning from the canonical
conversation transcript and checkpoint/context-engine evidence.

## Capture contract

- The core memory manager sends detached role/content projections: genuine human
  text, human steering, and eligible final assistant prose.
- Typed service notifications, synthetic task/compaction carriers, tool results,
  intermediate assistant messages, structured reasoning and unrelated metadata
  are excluded before automatic knowledge persistence.
- Trusted origin information survives native compression, historical replay and
  previous-message lookup. Text that merely resembles a service notification is
  not sufficient evidence to discard a genuine user's quotation.
- An explicitly empty capture remains empty; providers must not reconstruct it
  from raw scalar inputs, migration mirrors, retries or deferred flushes.
- Honcho and OpenViking add guards at their actual SDK/HTTP serialization and
  automatic file-import boundaries. Literal reasoning-tag examples in final code
  and Markdown fences remain intact, including across native message chunking.
- Canonical DTOs, SQLite history and version-2 checkpoint evidence are not
  rewritten by this feature. Legacy text without retained origin information is
  not retroactively assigned trusted provenance.

These are cooperative capture/preservation rules, not OS-level containment of
malicious code running inside the agent process. Explicit memory tools and
separate session-history exports are outside automatic capture.

## Reconstruct providers

`manifest.json` pins upstream commits, source-tree digests, patch digests and final
provider-tree digests. Upstream MIT licenses are retained in the reconstructed
packages. `install.py` only reconstructs into a **new staging directory**: it does
not import providers, install dependencies, change configuration or start a
service.

```sh
python integrations/memory-providers/install.py honcho \
  --source-cache /path/to/pinned-git-cache \
  --destination /path/to/new-stage/honcho
python integrations/memory-providers/install.py openviking \
  --source-cache /path/to/pinned-git-cache \
  --destination /path/to/new-stage/openviking
```

The cache contains one Git repository per provider, named `honcho` and
`openviking`. Sources are read from immutable commit objects, never an uncommitted
cache checkout. Add `--fetch` explicitly to fetch a missing pinned cache. Existing
cache repositories and destination directories are never overwritten.

Review the resulting code before deployment. Installation and gateway activation
are separate, instance-scoped operations; reconstruction is not activation.

## Native provider contracts

Prepare the repository's isolated test environment and the provider SDK
dependencies described in `provider-tests/README.md`. Then use the wrapper that
forwards to the canonical per-file clean test runner:

```sh
/path/to/prepared-python -B \
  integrations/memory-providers/provider-tests/run_offline.py \
  --provider-stage /path/to/new-stage \
  integrations/memory-providers/provider-tests -j 4 -q
```

The suite uses real provider and SDK serialization with offline recording
transports. It covers migration, empty captures, ordinary human/final positives,
reasoning negatives, failure/retry, chunking and literal preservation. It does
not establish that a running gateway has loaded the reviewed bytes or that live
backend writes satisfy the contract; verify those after an authorized deployment.
