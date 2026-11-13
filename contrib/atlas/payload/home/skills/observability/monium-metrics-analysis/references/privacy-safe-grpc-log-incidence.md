# Privacy-safe paginated ERROR-log incidence

Use for bounded Monium runtime investigations that prohibit retaining user text. The extraction is read-only; production configuration and code remain unchanged.

## Proven grpc request shape

Validated in a Jeeves Kotlin production audit on 2026-09-29:

- Endpoint: `query-prod.logs.yandex-team.ru:443`
- Method: `monium.logs.query.v1.Query/SearchLogs`
- Selector: `{project="jeeves-agent",service="agents",cluster="production",host="jeeves-prod-*",level="ERROR"}`
- Body: `{"queries":[SELECTOR],"start":START_ISO,"end":END_ISO,"limit":1000,"SortDir":"ASC"}`.
- Response: `logs`, optional `continuationToken`, optional `notices`.
- Rows include `time`, `host`, `logId`, `traceId`, `message`, and `meta`/`labels` arrays of `{name,value}`. Request IDs were in `meta.request_id`; trace IDs can be in metadata or top-level `traceId`.

First issue a limit-3 probe, printing only exit status, response field names, row count, and continuation presence. Confirm the current schema rather than assuming historical scripts are safe.

## Keep credentials out of argv

Read the user-approved token file in Python; check nonempty content and mode 0600 without displaying it. Pass a copied subprocess environment containing `RO_MONIUM_TOKEN`. Invoke grpcurl without a shell:

```python
args = [grpcurl_path, '-max-time', '45', '-expand-headers',
        '-H', 'authorization: OAuth ${RO_MONIUM_TOKEN}',
        '-d', json.dumps(body),
        'query-prod.logs.yandex-team.ru:443',
        'monium.logs.query.v1.Query/SearchLogs']
r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=55)
```

The header in argv is a literal placeholder; grpcurl expands it from the child environment. Do not interpolate the token into argv, shell commands, exceptions, debug output, or saved responses. Keep failed-call diagnostics to exit codes and allowlisted technical classifications when response text may contain private data.

## Pagination and coverage contract

1. Freeze a half-open UTC interval and exact runtime selector. Keep Go/trunk outside a Kotlin cohort at collection time.
2. Follow `continuationToken` until absent. Track repeated tokens in memory. A page cap is a safety bound, not evidence of completeness.
3. Save a sanitized page manifest: page number, row count, earliest/latest time, continuation-present boolean, notice count. Never save the token itself.
4. Filter by host and exact time boundaries, count exclusions, and deduplicate by `logId`. Report missing log IDs separately.
5. Report complete/incomplete status, stop reason, configured cap, pages consumed, duplicate IDs, missing request IDs, notices, and observed event bounds. An absent final continuation proves only exhaustion of this API query—not upstream logging completeness.
6. Use parsed timestamps or precision-normalized UTC values for local bounds. Mixed RFC3339 fractional precision is unsafe for naive lexical comparison at an exact boundary.

Create directories with mode 0700 and files with mode 0600 from the start (umask 077). Sanitize every row in memory before persistence; do not first dump a raw page and redact it afterward.

## Sanitization and signatures

Retain only needed correlation IDs, timestamp, host, logger scope, fixed template label, reviewed exception-class tokens, known error codes, and parsed technical tool ID/code. Do not retain arbitrary metadata, message excerpts, stack traces, notices, or user/script text. A syntactically plausible token is not automatically privacy-safe: constrain extraction to known technical fields/templates.

Useful fixed prefixes include `Calling tool ... failed:`, `Model call error for call_id=`, `Calling agent ... failed:`, and `Reasoning length recovery returned ...`. Parse the fixed tool code as its own dimension: aggregating every sandbox failure into `tool_call_failed` loses the dominant actionable signatures.

Produce three distinct kinds of evidence:

- **Template/code signatures:** e.g. tool ID plus `SANDBOX_ARTIFACT_METADATA_ERROR`, `SANDBOX_INPUT_MISSING`, `SANDBOX_STAGING_ERROR`, or `INTERNAL_SERVER_ERROR`.
- **Logger-scope attribution:** e.g. `ru.yandex.logbroker.agent.internal.SessionImpl`; if message meaning is not decoded, say so instead of inventing a cause.
- **Overlapping lexical tags:** timeout, empty response, length/context limit, maximum turns, cancellation. Restrict component-specific tags to relevant templates/scopes; a word found inside a tool message does not prove a model or Logbroker failure.

Split timeout incidence by model versus tool. Distinguish reasoning-recovery-empty from a final empty answer. Keep generic `mcp-executor-tool` separate from identified connectors. Count unique request IDs per signature/tool/tag, plus raw log counts and missing-ID counts. Preserve overlaps rather than summing these populations.

## Verification and reporting

- Recompute summary counts from sanitized records.
- Assert the exclusive template/scope categories sum to the deduplicated logs.
- Assert cohort membership, final pagination state, and file permissions.
- Publish detailed `(tool_id, tool_error_code)` counts and template/exception/code counts—not just top-level tool names.
- Say `zero matching ERROR signatures` rather than `no failures` when a tag is absent; the event may be logged at another level.
- Use the explicit caveat: **ERROR incidence is not terminal no-answer or failure rate.** A rate requires an eligible-request denominator; terminal failure requires retry/final-delivery evidence. Prior-day absolute counts require traffic normalization before trend claims.

## Validation anchor, not a reusable baseline

The 2026-09-28 UTC audit exhausted 8 pages: 7,499 distinct logs, 3,936 request IDs, no missing IDs or notices. Tool-call failures comprised 5,402 logs / 3,008 requests; the artifact-metadata tool code alone comprised 2,676 / 2,324. Logbroker scope-only errors comprised 1,794 / 918. These historical figures demonstrate why tool-code granularity and scope-only uncertainty matter; re-query for new dates rather than reusing them.
