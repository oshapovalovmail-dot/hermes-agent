---
name: monium-metrics-analysis
description: Use when extracting and reporting Monium/Solomon metrics.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags:
    - monium
    - solomon
    - metrics
    - observability
    - rate
    - reporting
    visibility: global
    aliases: []
---

# Monium Metrics Analysis

Use this skill for read-only extraction, reconciliation, and presentation of Monium/Solomon metrics through the Data API. It covers token-safe API access, RATE-to-count conversion, label-level breakdowns, derived dimensions, and evidence-backed slide/report production.

## Scope

Use when the task asks for:

- production metric counts over an exact time window;
- breakdowns by labels such as service, connector, status, or tool;
- conversion of a RATE series into event counts;
- success/error percentages with reconciled totals;
- read/write or other derived classifications not present as native labels;
- a stakeholder slide backed by the extracted metric data.

Do not edit dashboards, alerts, or monitoring objects when the request is read-only.

For production percentages such as no-answer, timeout, or failure rates that require trace-level root-cause decomposition, follow `references/negative-outcome-root-cause-investigations.md`. It adds metric-contract reproduction, live-artifact attribution, stratified trace sampling, mutually exclusive cause accounting, and downstream/UI verification.

For bounded Nirvana Shooter audits, follow `references/shooter-trace-tool-result-audit.md` to reconcile YT rows, Monium spans, nested tool results, and Grader coverage. When direct trace URLs hit Passport and scoped API authorization is unavailable but the user has authorized an already authenticated desktop browser, follow `references/authenticated-trace-rca.md` for CDP-based extraction.

## Workflow

### 1. Freeze source and window

Record:

- project and endpoint;
- exact selector labels;
- metric kind;
- timezone and fixed start/end timestamps;
- downsampling interval and aggregation;
- requested groups and connector names.

For reports ending “at the current minute”, truncate the end timestamp to the minute boundary. A partial last bucket multiplied as a full bucket corrupts counts.

When the source is a screenshot, `nda.ya.ru/t/...` share link, or DataLens product dashboard, recover the exact dashboard identity and frozen window before querying. A Passport redirect can still expose the real Monitoring URL in its decoded `retpath`; preserve epoch-millisecond `from`/`to`, then verify the page through authenticated browser/CDP. Treat tooltip `Сумма` as a composite formula, never as a synonym for one component: recover and reproduce every component numerator and denominator separately. If the user limits the incident to one runtime or cluster, exclude other runtimes from collection, denominators, causal attribution, and fixes—not just from the summary. For the Jeeves-specific validated workflow, screenshot/share-link window mismatch, DataLens `getDashboardV2` extraction, and Kotlin-only scope handling, see `references/jeeves-health-share-links-and-composite-percentages.md`.

### Impossible percentages and counter boundaries

For error rates above 100%, inspect the **live alert expression first**, then trace when each counter increments. Started calls and completed outcomes in the same time window are different populations: delayed completions can make errors/starts exceed 100% without duplicate errors. For a completion-based failure fraction, use erroneous completions divided by all completions with identical labels, window and aggregation. Keep incomplete/hung calls as a separate signal. Do not clamp the ratio or raise thresholds to hide the mismatch.

Separate a proven mechanism from attribution of a specific notification: the latter needs its evaluation timestamp and raw series. Label illustrative counts explicitly; do not infer them from a rounded percentage. Treat a threshold above 100% as observed configuration, not proof of the author's intent. A local checkout may differ from the deployed alert; do not substitute it for live evidence.

See `references/alert-ratio-event-boundaries.md` for the verified read-only API route and the Jeeves counter example.

### 2. Protect credentials

- Prefer an explicitly named environment variable or a mode-`0600` token file.
- Check presence, non-empty content, and file mode without printing the secret.
- Read the token inside the request process.
- Never put token values in command arguments, logs, result JSON, slides, or memory.
- Prove access with a small HTTP 200 read request before the full extraction.

### 3. Validate the live API shape

Generated OpenAPI contracts can drift from the live endpoint. Start with a minimal known-good request. If a documented enum/field returns a payload-deserialization HTTP 400, compare with a live proven request shape rather than repeating the same malformed payload.

Capture status code and a bounded error body separately. Do not pipe away the status.

For Monium log discovery without known service labels, use authenticated gRPC reflection and project-scoped `Autocomplete/Values` before constructing the search selector; see `references/monium-log-service-discovery.md` for verified request shapes. Pair an empty incident query with a one-row control over the same project, services, and time window. This distinguishes a working query against the wrong telemetry stream from an authentication failure; neither result proves the absence of upstream request events.

### 4. Query bounded dimensions

Prefer exact per-entity queries when the user provides a connector/service list. This avoids unrelated series and cardinality limits.

- Aggregate statuses per entity.
- Aggregate tool IDs per entity when needed.
- Merge locally after each query succeeds.
- Persist raw API responses and a compact canonical summary separately.

### Privacy-safe ERROR-log incidence

For bounded runtime ERROR-log audits, use `references/privacy-safe-grpc-log-incidence.md`: environment-expanded grpc authentication, full continuation pagination, allowlisted technical metadata, and request-grain signature counts. When raw text retention is prohibited, sanitize in memory before writing; the raw-response persistence step above does not apply. Separate exact template/code signatures from logger-scope attribution and overlapping lexical tags. An exhausted ERROR query proves API coverage, not terminal failure or complete upstream telemetry.

### 5. Convert and reconcile

For RATE metrics, use the conversion specified by the user or metric contract. Ignore null/non-finite values. Keep unrounded values until the final event-count conversion.

Required checks:

- each entity total equals its status sum;
- each entity total equals its tool sum when a tool cut is used;
- independent aggregate queries match the detailed sums;
- group totals equal the overall total;
- success percentages use the declared success status and denominator.

Do not report unique users unless the source has a user identity dimension and a deduplication contract. Event counts are calls.

### Coverage and comparison gate

Validate the returned timestamp grid, not just the requested downsampling. For each half-open day/window, partition expected slots into finite, returned non-finite, and absent; record first/last finite timestamps. Older data can have only one finite point per five requested minute slots. A RATE integral using the requested bucket multiplier is then an observed-sample integral, not a complete period count. Do not silently multiply sparse historical points by larger inferred durations or assume a retention policy without evidence.

Keep `observed_calls_raw` separate from a nullable `full_period_call_count`; missing history is not zero traffic. Mark growth comparisons non-publishable when sampling coverage differs materially. An arithmetic reconciliation can pass even when both inputs omit the same history. Aggregate finite-slot completeness does not prove lossless reporting by every underlying producer.

For product/cohort reports, probe labels before full collection; shared agent/environment labels are insufficient. Keep explicitly tagged cohorts separate from service-wide and runtime-specific totals, and reconcile cohort sums against an independent aggregate. For bounded query planning, sparse-history evidence, and the reusable artifact contract, see `references/cohort-aware-sparse-metric-reporting.md`.

For connector-error reports, discover statuses over the full window, collect connector groups and exact tool IDs separately for each non-ok status, and reconcile both integrals and matching timestamp slots. Track coverage independently for aggregate, status, connector and tool series: a complete aggregate does not make sparse category counts complete. Keep absent matrix combinations and incomplete category full-period counts nullable. Preserve authorization/access outcomes separately; status labels alone do not establish remote MCP or consent RCA. The five-minute recipe and its validated coverage edge case are in `references/cohort-aware-sparse-metric-reporting.md`.

Match the latest requested deliverable. For JSON-only/read-only collection, return canonical files, compact metrics, coverage caveats and verifiable paths; create slides only when requested. For «один график картинкой только по коннекторам», deliver one PNG inline, with the connector-only denominator and essential source/gap caveats inside the image; omit SDK panels, extra attachments and a prose report. Preserve an earlier explicit time range such as «с запуска». For an aggregate trend, collect status groups and independent totals, not a full tool-ID matrix. Distinguish an overall connector rate from a per-connector breakdown in the title. See the historical-chart and archived-denominator gates in `references/historical-metric-charts.md`.

### 6. Derive dimensions honestly

Before producing any chart, diagram, or report split by a requested dimension, prove that the source contains either:

- a native bounded label for that dimension; or
- a request-level field plus an auditable join key that preserves exact attribution.

If neither exists, stop at the evidence verdict: the split is not supported by the data. Do **not** draw a speculative split, substitute anonymous categories, or turn the missing telemetry into a target-architecture diagram unless the user explicitly asks for a proposed instrumentation design.

When a requested split is absent from source labels but can be derived exactly:

- call it derived;
- use an explicit, auditable mapping or allowlist;
- persist the mapping with the evidence;
- document ambiguous operations;
- do not present the split as source-native telemetry.

For read/write, classify side-effecting operations by exact tool ID rather than a loose substring heuristic. Review names such as `get_upload_link`, `run_query`, `transition`, and `patch` individually.

### Capacity-request supplements

For a product-specific calculation in the style of an existing quota ticket, use `references/capacity-request-supplements.md`. Recompute the named cohort in the ticket's exact window; check coverage again after filtering. Keep scheduler allocation, busy CPU and configured-resource scenarios separate. Report proposed total and delta with same-hour formulas and source links, distinguishing the arithmetic minimum from chosen rounding and queue reserve. Return the calculation in the requested chat; publication is separate.

### 7. Produce the artifact

#### Interactive dashboard reports

For the operator, an interactive report means inspectable metrics: summary, source-native statuses, entity/tool rankings, daily dynamics, sorting, pagination and source/method details. It does **not** mean a game, quiz, points, invented incidents or a training exercise.

When the requested source is a dashboard, inspect its **live definition first** and collect its underlying data for an explicit window and cohort. Archived eval runs, saved incident reviews and source-code examples are not substitutes. Prior reports and skills are discovery aids only. A source correction must replace the dataset and dependent claims before further UI work; do not merely relabel an already-built artifact. Ask for the dashboard link only after bounded discovery cannot identify the intended source.

Keep output and delivery contracts separate. A requested native Telegram widget is not fulfilled by an HTML attachment, browser link or local file. Bind the interactive artifact to a canonical verified summary; exercise filters, ranking changes, pagination and narrow layouts before sending. Local sandbox success, API acceptance, message-history presence, client rendering and client clicks are separate verification levels. If sending has not happened, say so rather than claiming completion.

See `references/dashboard-backed-interactive-reports.md` for live Jeeves dashboard extraction, cohort/host-scope drift, bounded ranking payloads and native-widget verification.

A compact two-slide pattern works well:

1. Overall result, group totals, total errors, and the dominant error source.
2. One row per entity with total, normalized derived-dimension bar, counts, success percentage, and errors.

For a comparative four-slide report, repeat that pair for two explicitly frozen windows rather than mixing denominators on shared slides. Use a half-open complete-day window (`00:00` to next-day `00:00`) for “yesterday”; use the declared launch/release timestamp through a minute-aligned current endpoint for “all time”. Label the latter as “since release” when telemetry did not exist before launch. Keep KPI cards clear by shortening scope labels before reducing table legibility.

Include the fixed window, source, downsampling method, and calls-not-users caveat. Keep full method detail in a source JSON or appendix. See `references/paired-window-connector-decks.md` for the verified four-slide recipe.

For tool-error decks spanning SDK and connector telemetry, keep the two layers in separate panels: error responses divided by sent SDK calls means **errors per 100 sent calls**, not a completion failure fraction; connector non-ok statuses divided by all completed statuses is a completion-based fraction. Preserve each layer's denominator in summaries and daily charts, and do not add the layers as failed tasks. Follow `references/layered-tool-error-decks.md` for the slide contract, live-status discovery and final-artifact checks.

### 8. Verify rendered output

- Reopen the PPTX programmatically and assert slide count and required figures.
- Export through a real renderer to PDF and PNG.
- Inspect every slide at full resolution.
- Re-render after every copy or spacing change. Short callouts can wrap and overlap after an apparently harmless wording edit.
- Check group labels separately from column headers; dense table layouts often collide there.
- Require totals in the slide to match the canonical summary.

## Retained-evidence agent RCA

For offline document-execution audits, use `references/offline-document-execution-provenance.md`. Report a compact verdict with exact source file, zero-based JSON path and logId for every decisive observation. Separate registered attachments, runtime byte-hash identity, execution result, final/model output, UI cards and successful downloads; none substitutes for another. Inspect coverage before interpreting missing fields, and project allowlisted technical fields before printing log content rather than dumping request payloads.

For proposal→result investigations, read retained evidence before requesting traces and preserve every good projection. Hash existing artifacts before collection; write new projections and failed reads to separate, create-only files. Verify the original row identity set and hashes after reporting. Never substitute a smaller later run for the original failed cohort.

Report coverage in separate dimensions: row summaries, structural timelines, call-ID/result-ID pairs, exact tool-error observations, and verified causal explanations. A complete matrix can still have incomplete RCA; use null for missing fields, not guessed causes. Regression obligations must cite observed boundaries, repetition hashes, counts or exact error envelopes, and remain conditional when the necessary observation is absent.

Distinguish model tool proposals, local execution/results, remote MCP dispatch, transport errors, and logical error envelopes. Hundreds of model calls with few or zero remote calls do not establish remote MCP timeouts. Regex hits anywhere in model input are investigative leads, not isolated tool-result proof. Cross-check summary counters against stored part types before trusting them.

See `references/retained-evidence-proposal-result-rca.md` for the verified preservation, timeline-reconstruction and independent-coverage method. This is a retained-evidence workflow, not a claim that blocked trace recovery was solved.

## Pitfalls

- Treating a RATE value as an event count without multiplying by the bucket duration.
- Multiplying a partial final bucket as if it covered the full interval.
- Guessing read/write from prefixes without recording exact tool mappings.
- Calling calls “users”.
- Trusting a dashboard screenshot when the task asks for exact totals.
- In a bounded Shooter trace audit, treating `UNSET_STATUS` or zero Monium error spans as proof the tools worked. Decode the exported tool-result envelope (`content[0].text.text` can itself be JSON with a `result` string), correlate with `execute_tool` spans, and distinguish a returned “skill could not be resolved” result from transport failure. A final answer after repeated unresolved `skill_view` calls does not prove access to the requested domain connector. If the Grader stores null scores with `score_status=error`, report `task_success=N/A`, not zero.
- Trusting PPTX structure without checking rendered pixels.
- Updating dashboards or alerts during a read-only statistics task.

## Platform references

- Jeeves `skill_call_status`, Solomon Data API quirks, connector/status/tool breakdowns, and derived read/write reporting: `references/jeeves-skill-call-status.md`.
