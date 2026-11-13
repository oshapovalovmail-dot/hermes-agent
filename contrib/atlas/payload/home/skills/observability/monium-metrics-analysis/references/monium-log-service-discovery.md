# Monium log service discovery and coverage controls

## Scope and evidence boundary

Use for bounded read-only log investigations when the project is known but service labels are not. The reflection → autocomplete → search/control sequence below succeeded against the live API on 2026-10-13. It establishes API access and selector coverage, not recovery of a particular upstream auth trace. Do not turn an unresolved request-level investigation into a claimed RCA.

## 1. Inspect the authenticated contract

Endpoint: `query-prod.logs.yandex-team.ru:443`.

Read the already-authorized OAuth token inside the request process into a child environment variable. Pass a literal environment placeholder to grpcurl so the secret is not placed in argv:

```text
grpcurl -expand-headers -H 'Authorization: OAuth ${MONIUM_READ_TOKEN}' \
  query-prod.logs.yandex-team.ru:443 \
  describe monium.logs.query.v1.ValuesListRequest
```

Use the same auth for reflection and data requests. Successful reflection targets include:

- `monium.logs.query.v1.Autocomplete`
- `monium.logs.query.v1.ValuesListRequest`
- `monium.logs.query.v1.SearchLogsRequest`
- `monium.logs.query.v1.LogEntry`
- `vtail.api.query.Query`

Do not echo the child environment. Preserve return codes and redact the token from exception/error output. Use the network routing approved for the current environment rather than encoding a universal proxy bypass.

## 2. Discover service labels within the exact project

RPC: `monium.logs.query.v1.Autocomplete/Values`.

Verified request shape (replace project and timestamps for the task):

```json
{
  "fieldName": "service",
  "start": "2026-10-13T16:15:00Z",
  "end": "2026-10-13T16:45:00Z",
  "limit": 30,
  "selector": "{project=\"alice_grpc_proxy\"}"
}
```

Response values are in `value`, an array of strings. In this bounded example the values were `__awacs__` and `__monium-agent__`; these are an observation, not an evergreen catalog. Repeat discovery for the current window/project and increase the cap if the response reaches it.

Use discovered labels rather than guessed project aliases or wildcard project sweeps. This API's observed search contract required project and service selectors; the successful alternative was exact-project autocomplete followed by concrete service selection.

## 3. Search and run a minimal control

RPC: `vtail.api.query.Query/SearchLogs`.

```json
{
  "start": "2026-10-13T16:15:00Z",
  "end": "2026-10-13T16:45:00Z",
  "limit": 50,
  "queries": [
    "{project=\"alice_grpc_proxy\",service=\"__awacs__|__monium-agent__\",message=~\".*DownloadJeevesFileById.*\"}"
  ]
}
```

Substitute the incident method or safe non-secret identifier. Keep the selector/window fixed, remove only the incident predicate, and set `limit: 1` for the control.

Report separately:

- API return code and sanitized error;
- matched row count and continuation presence;
- control row presence;
- project/service/time and technical IDs only.

The verified example returned zero incident matches without continuation and a real control row. This proves a functioning read of those streams, not absence of the download or its auth failure elsewhere. Autocomplete visibility is not proof that every upstream component publishes request events to Monium.

For a complete nonempty extraction, follow continuation pagination from `references/privacy-safe-grpc-log-incidence.md`. A one-row control is intentionally not an exhaustive query.

## Output privacy

Allowlist `project`, `service`, `time`, `traceId`, `spanId`, and `logId` for discovery output. Do not dump `message`, `meta`, or `labels` merely to learn their schema. For auth diagnostics expose presence flags, status and error component, not Cookie/Authorization values. Do not persist raw responses when the task prohibits raw retention.

## Verdict contract

A useful conclusion distinguishes:

1. **Access verified:** reflection/autocomplete/control succeeded.
2. **Match coverage:** exact selector, UTC window, predicate, row count and continuation.
3. **Source fit:** whether the stream contains the upstream events needed for attribution.
4. **Unresolved boundary:** missing correlated event or explicit access denial, without inventing its cause.

A prose request to an operator is a handoff, not an executable query. Label query examples, executed queries and unexecuted follow-up templates separately. Source-code branches can define the evidence to seek but cannot prove which branch an individual request took.
