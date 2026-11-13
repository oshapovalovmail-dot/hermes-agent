# Cohort-aware reporting with sparse historical metrics

Use for product presentations requiring calls, status rates, per-entity cuts, daily history, and week comparisons from a shared service.

## Bounded collection pattern

1. Freeze timezone and half-open complete-day boundaries. Prove credential access with a short current query.
2. Probe shared identity labels (`agent_id`, `env`) and inspect all retained labels in grouped results. A newly exposed native cohort label can be more informative than known shared identifiers. Probe its historical coverage before adopting it.
3. Keep distinct scopes: exact cohort selector, shared service, and each runtime. Never infer cohort from connector name, or assume separate runtime publications represent deduplicated product events.
4. Choose the smaller query axis. If there are many connectors but few statuses, discover statuses, then query each exact status grouped by connector. This yields connector × status rows without a high-cardinality tool cut or unsupported multi-label grouping. Independently collect totals, status groups, and connector groups for reconciliation.
5. Bound time ranges and concurrency. In the verified Solomon run, six-day chunks at one-minute resolution worked; exactly seven days failed the point limit. This is an observed API constraint, not a universal cap: revalidate when necessary. Use bounded retries for transient transport failures and reuse successful immutable responses.
6. Persist exact requests, response status, retrieval time, raw responses, and a SHA-256 manifest. Do not retain authentication headers or secrets.

## Coverage is a separate result

For a one-minute contract:

- Include only `from <= timestamp < to`.
- Partition every expected minute into finite, returned non-finite, or absent. Non-finite values can be strings such as `NaN`, not just JSON null.
- Inspect finite-point spacing and actual timestamps, even when the request says `gridMillis=60000`.
- Integrate finite RATE values using the declared contract, sum unrounded across days, and round only the final display value.
- If older samples are sparse, call this an **observed-sample integral**, not a complete traffic count. Do not silently impute zeroes or infer a different sample duration from timestamp distance.
- A separately requested coarser-resolution recovery must preserve its own query, resolution, and integration contract; do not mix it silently into the canonical one-minute series. An empty recovery probe establishes no recovery, not a known retention policy.
- Suppress publishable growth when one comparison window is sparse and the other dense. Store a machine-readable publication gate, not just a prose footnote beside an impressive ratio.

## Artifact contract

`summary.json` should contain separate scopes with exact selectors, requested windows, daily rows, per-entity statuses, and:

- `observed_calls_raw`, final rounded observed calls, observed successes/non-ok, and status taxonomy;
- `full_period_call_count=null` when coverage is incomplete;
- expected/finite/non-finite/absent slots, first/last finite timestamps, and explicit coverage semantics;
- independent aggregate reconciliation deltas;
- a comparison publication verdict and reason.

Chart nullable full-period totals rather than zero-valued observations from days without data. Category rounding can differ by a unit; reconcile raw integrals, or explicitly document an allocation rule if exact display-category sums are required.

Keep `source.json`, raw responses, manifest, label evidence, and `verification.json`. A local verifier should check status/connector/aggregate sums, unrounded daily-to-window sums, coverage partitions, cohort sums, null totals for incomplete windows, and raw hashes. Explain that passing arithmetic checks does not restore missing history or prove lossless instrumentation.

## Connector-error extraction on an explicit five-minute grid

Use this recipe when the requested contract is five-minute AVG, or when a separately requested five-minute recovery is being validated. Keep it separate from one-minute observed-sample integrals.

1. Read the reusable client before importing it. Redirect its output root and raw directory to the new evidence directory before calling any query; preserve old successful evidence. Read credentials inside the request process and retain no authentication headers.
2. Freeze the exact runtime/cohort selector and half-open UTC/MSK boundaries. For Go B2B system connectors, the validated selector is `{service="agents-sdk",cluster="jeeves-go-prod",host="cluster",space="b2b",sensor="skill_call_status",skill_kind="system"}`. Probe access, then discover the status union across every bounded chunk, not only the short probe.
3. Request explicit `gridMillis=300000, aggregation=AVG`; use chunks of at most four days for this recipe and bounded concurrency. Independently collect `series_sum(base)`, groups by `status`, and groups by `skill_name`.
4. For every exact discovered status, query groups by `skill_name` to build the matrix. For each non-`ok` status, separately query groups by exact `tool_id`. This bounds the grouping axis without unsupported multi-label grouping. Retain every returned tool ID and a bounded top list per status; rank positive integrals, not point peaks.
5. Integrate finite samples as `300 * math.fsum(values)` inside each half-open chunk. Reject duplicate finite timestamps for the same grouped key and chunk overlap. Ignore boundary samples outside the chunk and record how many were excluded. Grouping may return either RATE or DGAUGE; verify the metric's event-rate contract rather than treating the type label as a count.
6. Reconcile unrounded integrals for the entire window and each MSK day: status→total, connector→total, matrix→each independent connector/status total, and tools→each independent non-ok status total. Also compare finite grouped sums at matching reference timestamps; whole-window equality alone can hide compensating gaps or time shifts. Record tolerance, mismatched slot count and maximum absolute rate delta. The validated verifier used integral tolerances `rel_tol=1e-10, abs_tol=1e-7` and pointwise tolerances `rel_tol=1e-10, abs_tol=1e-10`.
7. Validate the exact expected aggregate timestamp set, not just its cardinality. For every aggregate/status/connector/tool row, retain finite, nonfinite and absent partitions separately. A complete aggregate can coexist with nonfinite category samples. Keep incomplete category `full_period_call_count` and absent matrix combinations null; finite-only observed integrals may still reconcile but do not prove missing category samples were zero.
8. Save exact selector/time/downsampling contracts, unrounded counts and rates, daily matrices, top tools and all tool IDs, per-series coverage, raw responses, SHA-256 manifest, and an offline verifier. Verify scope labels and time bounds on every request, HTTP status plus `errorsDetails`, and independently reread hashes after writing the manifest. Label displayed counts as rounded RATE-integral estimates; separately rounded categories/days can differ from the rounded overall total.

### Status taxonomy and reporting gate

Preserve source statuses verbatim. Authorization and forbidden/access outcomes belong in separate rows from business, transport and timeout outcomes. Do not rename all non-ok outcomes “MCP errors”; aggregate labels do not establish a remote-server cause or user-consent failure. A status not returned by discovery is not automatically a measured zero for that failure mechanism. Distinguish call success from task/user success.

For a JSON-only collection, deliver the data and verification paths plus a compact metric/coverage summary. Slide production is a separate requested deliverable, not a default follow-up.

### Verified five-minute case

The 29 October–4 November 2026 MSK Go B2B collection used UTC `[2026-10-28T21:00Z, 2026-11-04T21:00Z)`, four-day plus three-day chunks, and 29 raw responses. Its aggregate contained all 2,016 expected finite slots, while `authorization_error` had 14 nonfinite slots and `timeout` had 8. Independent daily/window and pointwise reconciliations passed. This demonstrates why aggregate completeness and category completeness need separate fields; do not generalize these coverage numbers to another window.

Evidence: `~/out/jeeves-tool-errors-20261105/connectors/` — `collect.py`, `summarize_verify.py`, `summary.json`, `verification.json`, `raw_manifest.json`, `series_coverage.json`, and `raw/`. Treat those scripts as a validated implementation to inspect and adapt, not a portable hardcoded destination.

## Verified case and evidence anchor

On 2026-10-29, Jeeves Go probes exposed `space=b2b|b2c` while `agent_id=jeeves-agent` and `env=production` remained shared. Exact B2B selection and B2B+B2C reconciliation worked. Kotlin did not expose the same cohort label in the observed results and was reported separately.

The 22–28 October Go window had all requested minute slots; 15–21 October had only 23.29% finite minute slots, often one finite sample per five minutes. Both sets reconciled arithmetically, illustrating why reconciliation alone cannot validate a growth claim. The full-month historical count was not recovered and was explicitly left null. Do not generalize these dates or percentages to future collections.

Evidence: `<approved-output>/connectors/` — `summary.json`, `verification.json`, `raw_manifest.json`, and collection/aggregation scripts. This anchors a verified reporting method, not a successful historical-data recovery procedure.
