# Tracker retained-output qualification

## Scope

Only `ReadService.tracker_read`, its input schema and its tool description change in the public sidecar. All other bytes, deny-default public operator bindings and backend pins are preserved. The reviewed method retains a 512-byte transport reserve when the installed SDK serializer is used for the Unicode legacy-output fallback.

Public sidecar SHA-256: `077ffb3cf2d20ef90f8e7d848b1982b3e32bc8882b203f46f3c77ad0e4768a34`.

Long safe projections use the existing encrypted retained-output pager rather than slicing serialized JSON. Continue with the same key/view and issued cursor. Typed-path records reconstruct the safe projection; concatenate `string_offset` fragments in offset order. Retained-output completion does not imply native upstream completeness. No upstream next-page fetch is added.

## Portable execution

Run from the project directory with an existing Python environment containing `mcp`, `jsonschema` and `cryptography`; the runner installs nothing:

```sh
python -B qualification/tracker_retention/run.py --output "$RUN_OUTPUT"
```

`RUN_OUTPUT` must name a fresh, nonexistent directory outside the project. Source defaults to `payload/services/atlas-read` resolved relative to the published runner, not the shell working directory. An explicit `--source` can select an alternate complete public closure for baseline or negative-control qualification. `--only regressions` and `--only stdio` select individual gates.

The runner stages the eleven public closure files and published harness, verifies unchanged companion hashes against `baseline-pins.json`, and records the actual sidecar hash. This baseline file is historical qualification input, not a new deployment/overall manifest. Workers run in fresh HOME/profile/tmp directories with an explicit closed environment. Synthetic auth/GET transport replaces only the trusted Tracker boundary; native commands and actual socket connections are denied. No private fixture, business record, host-specific path, credentials, live API, service configuration or operator installation is needed.

Outputs include exact argv/environment/exit codes and source/harness/dependency/log hashes in `receipt.json`; regression counts, discovery schemas, actual STDIO frame metadata, parent/child source identity, synthetic transport counters and framing evidence are stored beneath the output directory. Discovery frames are recorded but are not covered by the tool-result 10000-byte gate.

## Executed source/test evidence

Existing dependency versions used: MCP 2.3.0, jsonschema 4.26.0, cryptography 50.0.2. Results are specific to this installed SDK; rerun when changing dependencies.

| Gate | Frozen public baseline | Promoted public source |
|---|---|---|
| Original regression class, AST unchanged | 18 executed; 12 failure entries (including subtests), 1 error; exit 1 | 18 executed; zero failures/errors; exit 0 |
| Real SDK client → STDIO proxy → real SDK server | 10011-byte tool-result frame; exit 1 | Five frames: 3718, 3722, 3726, 3728, 3546 bytes; exit 0 |

The STDIO case is entirely synthetic: `TEST-1`, a Unicode comment of 2325 `Ж` characters. The installed SDK result body is exactly 10000 bytes, but the actual newline-delimited JSON-RPC frame is 10011 bytes on the old path. The proxy measures raw stdout bytes before forwarding them unchanged; serializing `CallToolResult` alone is **not** treated as framing qualification.

A separate causal negative control removes only `+512` from the promoted method's SDK size calculation in an external disposable closure: the real frame returns to 10011 bytes and the STDIO gate fails with exit 1. The normal published source is never mutated for this control. With the reserve present, all five typed pages reconstruct the safe JSON byte-exactly, using one synthetic authentication and one synthetic GET total; continuation performs neither again. The expected safe UTF-8 SHA-256 is `4a7a0ffc384e44d02ebf2d8d99ecd8d6d445e23106c7606aabc757517894d4f7`.

The eighteen regressions cover direct JSON coherence, minimum budgets, lossless Unicode/large scalar reconstruction, legacy compatibility, upstream-completeness preservation, cursor replay/scope/expiry, schema validation, pre-auth rejection, redaction/projection, HTTP policy gates and pinned closure imports. Their existing result-body assertions remain result-body tests; only the separate STDIO test establishes actual transport framing.

## Acceptance boundaries

| Receipt category | Status |
|---|---|
| Public source and portable tests | Executed and passing; byte/AST guards verified |
| Repository publication | Files prepared locally only; no commit, push or review comment performed |
| Operator disk installation | Separate parent-owned receipt; not established by these tests |
| Operator process activation | Separate parent-owned receipt; no process/config changes made here |
| Operator live behavior | Separate parent-owned receipt; no live API/business-record qualification claimed here |
| Final delivery | Scoped public artifacts and external execution receipts delivered to parent |

Private genuine-data qualification and operator-live receipts are intentionally excluded from the public harness and documentation dependencies. Synthetic transport tests do not establish current service ACLs, operator deployment, live upstream availability or full upstream pagination. The 512-byte reserve is qualified by the recorded real SDK frames, not a proof for arbitrary future SDK/envelope changes.
