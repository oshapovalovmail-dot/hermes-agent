# Dashboard-backed interactive reports

Use for an interactive metric report whose source must be a real dashboard, especially compact Telegram-native output. Read the parent skill's source, coverage and counting gates first.

## Source-first sequence

1. Resolve the intended dashboard through a bounded known-project search or prior source link. Old reports locate the source; they do not supply current measurements. Do not spend the task designing hypothetical incidents or reviewing unrelated eval histories.
2. Read the live dashboard definition through the authenticated UI's `monitoringInternal/getDashboard`. Preserve its identity/title, widget title, query programs, parameter definitions/defaults, aggregation and host scope. Capture only necessary request/response bodies, not cookies, authorization headers or browser credentials. Use the already authenticated browser and an owned background tab; do not disturb unrelated tabs.
3. Select the actual widget and resolve its template parameters explicitly. Freeze an offset-bearing, half-open window. If the user gave no period, state a bounded default such as seven completed local calendar days; do not pretend it was user-selected.
4. Prove a small authorized read, then collect the live programs or documented equivalent component queries through the read-only Data API. Keep raw replies, exact queries, source metadata, hashes and canonical unrounded summaries separate.
5. Independently reconcile total, statuses, entities and tools, including matching timestamp slots and daily sums. Verify coverage for each series, not only the aggregate. Preserve null full-period counts for incomplete categories.
6. Only after the evidence qualifies, build the interaction and send the requested transport. An unavailable dashboard is a blocker, not permission to use synthetic examples or archived test runs.

## Jeeves live-definition discovery: historical example, revalidate

On 2026-11-07, the authenticated page
`https://monitoring.yandex-team.ru/projects/jeeves-agent/dashboards/jeeves_go_alive/view`
returned title `Все ли хорошо у Jeeves?` and a `Skill Calls` group. Its live definition differed materially from a local manifest and earlier collectors:

- cluster control defaulted to three Go production clusters: `jeeves-go-prod|jeeves-go-prod-mow|jeeves-go-prod-nrg`;
- metric queries summed the DC host aggregates `Klg|Mow|Nrg|Sas|Vla`, not `host="cluster"`;
- queries used `skill_kind="*"`, not only `system`;
- product attribution used the native `space` parameter: resolve it to `b2b` rather than leaving the B2B+B2C default;
- tool/skill non-ok shares used `skill_call_status`, `integral(...)`, and a zero baseline from `flatten(failed_raw, total_raw * 0)`;
- top-20-by-share widgets were distinct from non-ok counts by skill.

These are discovery hints, not permanent selectors. Copy current defaults/programs and exclude other cohorts explicitly. Do not add raw hosts, DC aggregates and a cluster aggregate together. Do not call this metric all SDK tools, failed user requests, or pure remote MCP errors: preserve the widget's actual boundary and keep access/application statuses separate.

## Reproducing native percentages

Collect both component RATE series and the resolved native percentage program when possible. Compare the native final value with the locally derived ratio by exact entity ID. Record matched entities and maximum difference in percentage points. Display-precision agreement is not an exact match; small differences must remain in verification output, not be erased by rounding or a silently weakened assertion. Inspect native zero-fill, integration and missing-category behavior before assigning a cause.

Use `observed` and nullable `full_period_count` separately. Mark incomplete entity/status rows in the UI and explain the marker. A complete aggregate and arithmetically reconciling category integrals do not prove complete category histories.

## Compact interaction model

Useful views are summary/statuses, skills/connectors, exact tools and days, plus source/method details. Every value must come from the canonical summary. State dates, timezone, cohort, approximate RATE-derived units and the difference between non-ok attempts and failed tasks in the artifact itself.

For a size-bounded widget, precompute the union of the top N by error count and the top N by error share. Switching between those two rankings can then produce the true top N without embedding the full catalog. Preserve a deterministic tie rule. Do not add arbitrary filters or alternative rankings to a truncated union and imply they cover the full catalog; recompute those selections from the complete source first. Retain counts alongside high percentages on small volumes.

## Native Telegram verification boundary

Recheck current Telegram widget-format/profile documentation before building. The profile-1 implementation exercised here used `TelegramWidget.ready()`, not `Telegram.Widget.ready()`, with inline JS and no backend requests. Observed profile limits were 32,768 raw UTF-8 bytes and 4,096 bytes after zlib level 9; treat them as versioned contracts, not timeless platform limits.

Validate the exact generated HTML in the upstream widget sandbox/shim/validator, not merely an ordinary browser. Check:

- no runtime errors or profile diagnostics;
- tab switches, sorting, page boundaries and source/method disclosure;
- every relevant page and ranking at the narrowest supported width, plus representative wider layouts;
- text wrapping and actual layout height within the supported frame;
- no unintended network requests or storage writes;
- compressed size of the final content, after the last edit.

Use the requested native sender only after those gates pass. Keep stable send identity and an unknown-outcome fence; do not blindly resend an ambiguous accepted request. Never put bot credentials in HTML, logs or reports. Record API acceptance/message identity, then independently verify message presence. Client rendering and client clicks need their own evidence. A local file or passing sandbox is not delivery.

## Evidence anchor and limit

The exercised collection and canonical verification are under `~/out/jeeves-widget-dashboard-20261107/` (`dashboard.json`, `source.json`, `raw/`, `raw_manifest.json`, `summary.json`, `verification.json`). The authored HTML and test are in the separate local interactive-cards workspace as `examples/jeeves-dashboard-report.html` and `tests/jeeves-dashboard-report.mts`.

That session verified collection, reconciliations, ten interaction states and first-page layouts for five views at widths 200/320/430. It did **not** complete native delivery or prove all pagination layouts/client interactions. Do not promote those unfinished gates to a validated end-to-end workflow, reuse its numbers as current statistics, or transfer unrelated sandbox test totals to this report.
