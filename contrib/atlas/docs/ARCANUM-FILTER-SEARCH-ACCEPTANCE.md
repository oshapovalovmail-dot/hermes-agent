# Arcanum filtered-search repair — source acceptance

## Status and scope

- **Portable source tests: PASS.** The frozen public baseline was exercised RED, then the repaired public modules were exercised GREEN. The portable runner was also exercised independently GREEN.
- **Operator installation and process activation: PASS.** The parent installed the three reviewed assets on the approved Atlas two-host topology, read back both source sets and derived public pins, passed mandatory native readiness, and observed the primary ready and relay connected. Existing privilege, admission and project-policy assets were unchanged.
- **Live model execution and same-topic delivery: observed PASS.** A fresh authenticated owner request selected documented author/reviewer/date queries, completed six real service reads with no upstream error, and produced an exactly matched delivered response. Independent factual grading is separate and pending. These observations establish the repaired search path, not exhaustive historical activity coverage.
- Publication/commit/push/PR operations are not established by this source qualification.

Only `intrasearch.search.inputSchema` changes: explicit search requires a non-whitespace query and discovery explains the documented `intrasearch.arcanum_search` legacy operators for filter-only author/reviewer/date searches. It does not invent text, insert wildcards, or rewrite query/filters. The existing required `vertical` field remains required. The public manifest → backend → sidecar SHA-256 chain was recalculated from public bytes, not copied from operator-specific Python files.

All other public source bytes, deny-default operator bindings, defaults, ACLs, schema fields and dependency pins are retained. No product guard is patched for the tests.

## Reproduction

From the project root, with an existing Python interpreter providing `jsonschema`:

```sh
python -B qualification/arcanum_filters/run_tests.py --output /path/to/fresh-private-receipts
```

`--output` must name a new directory outside the project. Optional `--source /path/to/frozen-public-baseline` exercises another complete public source closure with the same tests. No installation, unpublished test tree, credentials, network access or native process is needed. The runner starts subprocesses with isolated HOME/HERMES_HOME/TMPDIR and a minimal environment; it does not inherit session state. The only substituted production callable is backend `run_native`, returning synthetic JSON-RPC bytes. Actual sidecar, pinned loaders, backend, schema validation, policy checks, paging and serialization execute unchanged.

Raw reports and command logs include resolved local paths and belong in private receipt storage, not publication. This document is a portable summary, not a projected or replacement execution log.

## Executed evidence

| Phase / suite | Exit | Test methods | Failed assertions (including subtests) | Errors | Real dispatches | Fake-native calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Public baseline / full dispatch | 1 | 6 | 123 | 0 | 111 | 96 |
| Public baseline / filter-only dispatch | 1 | 1 | 16 | 0 | 12 | 12 |
| Repaired public / full dispatch | 0 | 6 | 0 | 0 | 111 | 12 |
| Repaired public / filter-only dispatch | 0 | 1 | 0 | 0 | 12 | 0 |

Baseline failures are behavioral: blank explicit queries reach the transport and required guidance is absent. They are not import/setup failures. Both reviewed regression class ASTs, including all negative cases, remain unchanged; only the full-import fixture bindings were adapted to portable source/report locations. The filter-only test file remains byte-identical to its reviewed version.

GREEN covers 96 blank-query dispatch denials with no native calls, including filter-only inputs; 12 successful dispatches with exact argv and real serialization; legacy empty/whitespace/operator queries; foreign namespace and unknown-field rejection; missing-vertical rejection; and guidance in real manifest/catalog pages. Full filters and padded Unicode search text are byte-preserved. The separate portable-runner rerun passed the same seven methods; it is not counted as additional coverage.

## Public code hashes (SHA-256)

| File under `payload/services/atlas-read/` | SHA-256 |
| --- | --- |
| `work_services_manifest.json` | `051f83adb30280acbcef4ed3a68e0c922829afdf2976ab717974092a77fcf78e` |
| `work_services_backend.py` | `5800624d712c732b0beb967636623884ddbd75e91266624628ab4f01063ade62` |
| `sidecar.py` | `c8d747fb2c4e2db78d235bb0d84bd201778c972889f930071dc5966b934b46e1` |

The public backend hash differs from the operator candidate because portable deny-default bindings are preserved. The offline source qualification itself establishes neither actual native retrieval nor operator activation; the separately observed operator phase is described above. Original failed baseline evidence and private operator receipts remain untouched outside the project.
