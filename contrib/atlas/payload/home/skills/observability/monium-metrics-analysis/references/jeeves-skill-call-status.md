# Jeeves `skill_call_status` production reporting

This reference records a verified read-only recipe for connector-call reports in project `jeeves-agent`.

## Source contract

Endpoint:

```text
POST https://solomon.yandex.net/api/v2/projects/jeeves-agent/sensors/data
Authorization: OAuth <token>
Content-Type: application/json
```

A working local token location was `~/.tokens/monium` with permissions `0600`. Treat the path as environment-specific; verify it exists and is accepted without printing the token.

Base selector labels:

```text
service="jeeves"
cluster="jeeves-prod"
host="cluster"
sensor="skill_call_status"
skill_kind="system"
```

Observed dimensions:

```text
agent_id, cluster, env, host, project, sensor, service,
skill_kind, skill_name, status, tool_id
```

Live 2026-10-29 Go probes additionally exposed a native `space` label (`b2b`, `b2c`). Always probe current and historical label coverage before product-specific reporting: `agent_id=jeeves-agent` and `env=production` are shared and cannot establish B2B attribution. `space="b2b"` proves only the tagged subset; do not assume older/unlabeled series or Kotlin are B2B. Preserve separate shared-service and B2B-tagged scopes, missing-history coverage, and exact selectors.

## Go runtime selector and migration checks

Verified live on 2026-10-09: Go production `skill_call_status` is published under `service="agents-sdk", cluster="jeeves-go-prod", host="cluster", skill_kind="system"` in project `jeeves-agent`. `service="jeeves-go"` returned no series for this sensor; the old Kotlin selector `service="jeeves", cluster="jeeves-prod"` returned only zeros over the same window. Do not interpret the old selector's zero as zero product traffic: inspect the current Go dashboard manifest and probe its SDK selector. When covering both runtimes, query each separately over one frozen window and reconcile within each metric boundary before adding disjoint runtime totals.

Check timestamps of null samples, not just their count: a collection ending with fresh finite samples may still have internal missing buckets. Exclude nulls from RATE integration and disclose incomplete coverage; do not assume ingestion lag removes historical gaps or coerce missing minutes to zero.

## Live Data API payload

Verified one-minute AVG downsampling:

```json
{
  "from": "<ISO-8601 UTC>",
  "to": "<ISO-8601 UTC>",
  "program": "<expression>",
  "downsampling": {
    "gridMillis": 60000,
    "aggregation": "AVG"
  }
}
```

The live endpoint returned HTTP 400 for the generated-OpenAPI spelling `gridInterval` with `GRID_AGGREGATION_AVG`. It returned HTTP 200 for `gridMillis` with `AVG`. Revalidate after API migrations, but do not loop on the rejected shape.

For this RATE metric and 60-second buckets:

```text
calls = round(sum(finite values) * 60)
```

Use a minute-aligned end timestamp.

## Expressions

Status split for one connector:

```text
group_by_labels(
  {service="jeeves", cluster="jeeves-prod", host="cluster",
   sensor="skill_call_status", skill_kind="system",
   skill_name="<connector>", status="*"},
  "status", v -> series_sum(v)
)
```

Tool split for one connector:

```text
group_by_labels(
  {service="jeeves", cluster="jeeves-prod", host="cluster",
   sensor="skill_call_status", skill_kind="system",
   skill_name="<connector>", status="*", tool_id="*"},
  "tool_id", v -> series_sum(v)
)
```

Independent total:

```text
series_sum(<same exact connector selector>)
```

A grouping attempt that passed both `"skill_name"` and `"status"` to `group_by_labels` returned HTTP 400. The robust fallback is one exact connector per request, followed by local merging.

## Long windows and transport resilience

The Data API can reject a single query covering slightly more than seven days with HTTP 400, and large tool-level responses can terminate with `IncompleteRead`. For release-to-now reports:

- split the exact half-open window into bounded one-day chunks (or at most six days when request count matters); a live 2026-10-29 request for exactly seven days at 60000ms failed with HTTP 400 `too many points: 10080, please increase gridMillis`;
- treat an empty historical vector as missing evidence, not zero calls; probe an alternate resolution once if needed, but never silently mix it into the requested one-minute integration;
- inspect timestamp intervals as well as nulls: historical responses can have 300000ms timestamp jumps even with a requested 60000ms grid; retain the requested integration contract and disclose absent minute slots rather than silently imputing or reweighting;
- run the same expression for every chunk;
- merge series by the requested grouping label;
- sum unrounded RATE-derived values across chunks and round only after the full-window sum;
- allocate integer categories against the independently rounded connector total;
- retry transient read/connection failures with bounded exponential backoff;
- deduplicate discovered connector names before per-connector queries.

Do not sum independently rounded daily counts. That introduces avoidable drift and can break status/tool reconciliation.

## Read/write cut

There is no read/write label in `skill_call_status`. Derive it from exact tool operations and persist the allowlist.

Examples of writes observed across system connectors:

- Bitrix24: `create_deal`, `create_contact`, `update_deal`.
- Mail: `create_draft`, `update_draft`.
- Calendar: `create_event`, `patch_event`, `delete_event`, participant mutations.
- Disk: `move_resource`, `delete_resource`, folder/resource creation, upload operations, copy/publication operations.
- Tracker: create/update/transition/bulk/comment/trigger mutations.
- Wiki: create/edit/update page/grid operations and row/column additions.

Treat get/search/list/download/status calls as read unless the connector contract says they mutate state. Explicitly record special choices:

- `get_upload_link` is read because it obtains a link; the later upload call is write.
- query-like operations need contract review rather than blind prefix classification.

## Evidence artifact

Persist a JSON document containing:

- exact Moscow and UTC windows;
- metric and downsampling;
- per-connector status counts;
- per-tool counts;
- exact write-operation allowlist;
- per-connector read/write totals;
- reconciliation results.

This lets reviewers challenge a classification without rerunning the production query.

## Errors outside connectors

For a Go B2B non-connector error slide, use native `space="b2b"` on `service="agents-sdk",cluster="jeeves-go-prod",host="cluster"`. `tool_call` and `tool_call_error` are grouped by `tool_id`; exclude **both** `mcp-executor-tool` and `alice-apps-tool` from numerator and denominator. Current SDK `metrics/agentstream.go` counts a tool error only when the protocol `ToolResponseData.error` is populated. Logical error text inside a successful result is not covered. `model_error/model_call` is a separate model-call ratio. Do not add it to tool errors as failed user requests, and do not call `agent_run_error` connector-free without attribution.

Preserve label-less error events as unattributed. A negative label selector can exclude absent-label rows, while a group-by query retains them; summing all grouped rows can therefore differ from the filtered independent total. Reconcile a known-ID allowlist and export the omitted count separately. Empty series may have `values: []` and no `timestamps`; record that shape rather than crashing or claiming full coverage.

If the requested minute grid has sparse older buckets, retry explicitly at a supported five-minute AVG grid. Only integrate at 300 seconds after proving the returned finite timestamps equal the exact expected five-minute grid. This is a new verified extraction, not retroactive reweighting of sparse minute samples. Reconcile grouped and independent totals on that same grid and disclose the resolution.

## Slide QA lesson

For a two-slide report:

- Slide 1: overall success, total calls/errors, two group totals, error concentration.
- Slide 2: one row per connector with total, read/write ratio bar, read/write counts, success, and errors.

After any text edit, rerender both slides. Two defects appeared during iteration despite structurally valid PPTX files:

1. A right-side callout wrapped onto two lines and overlapped its supporting caption.
2. A group label collided with the table column header.

Fix these with shorter wording and explicit vertical space, then inspect the final PNG at full resolution. Keep the caveat that counts are calls, not unique users.
