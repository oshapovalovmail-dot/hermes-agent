# Alert ratios: event boundaries and live configuration

## Read-only investigation recipe

1. Recover the alert URL/ID and notification time. If pasted text lost the hyperlinks, list alerts in the known project and match the full name, including contour. Do not require the contour to appear in the ID.
2. Read the deployed alert, preserving version, updatedAt, expression, grouping, window, delay, downsampling, thresholds and overrides. Compare with source only afterward: local source can predate the active configuration.
3. Extract numerator and denominator selectors. Compare sensor names, event boundaries, labels, statuses, aggregation and timestamp coverage.
4. Trace producer increments: start, attempt, completion, retry or logical request. Verify completion deduplication separately rather than assuming a ratio above 100% proves duplicate counting.
5. For exact incident attribution, fetch the input series at the notification evaluation time with its actual delay and aggregation. Reproduce the ratio before declaring the specific cause. Inspect other mismatches in the same scope (label coverage, retries, gaps, resets and alignment).
6. Report the verified formula and mechanism, then the incident-evidence limit. A configuration read does not establish the cause of underlying transport failures. Make no monitoring changes for an explanation request.

## Verified Solomon API route

These GET routes returned usable JSON in the 2026-10-31 investigation:

```text
https://solomon.yandex.net/api/v2/projects/{project}/alerts?pageSize=1000
https://solomon.yandex.net/api/v2/projects/{project}/alerts/{alert_id}
```

Use OAuth credentials read inside the request process, never printed or inserted into command arguments. Filter list results before emitting them: retain matching IDs, names and versions, plus pagination metadata. Follow returned pagination if present. Detail exposes `type.expression.program`, `groupByLabels`, `windowSecs`, `delaySecs`/`delaySeconds`, `downsampling` and `version`.

## Observed Jeeves example — historical, re-fetch before use

The B2C alert was named with «контур b2c» but had ID `skill-error-rate_jeeves` in project `jeeves-agent`; filtering only IDs for `b2c` missed it.

The live expression used:

- denominator: `skill_call_count`;
- numerator: `skill_call_status`, excluding `ok|authorization_error|forbidden_error`;
- transport component: `skill_call_status` with `transport_error|timeout`;
- common scope: `space=b2c`, `skill_kind=system|unknown`, cluster host;
- per-series five-minute AVG followed by series sum;
- ratio multiplied by 100;
- Disk threshold override of 101, default threshold 10;
- evaluation window of one hour and delay of 60 seconds, distinct from five-minute grouping.

The local template differed: it used `skill_call_status` for both numerator and denominator, demonstrating why source alone could not explain the live alert.

Producer evidence in `alice/agents/jeeves/go/internal/skills/engine/skillmetrics/skillmetrics.go`:

- `Metrics.Start` increments `CountSensor` and initializes a zero OK status series;
- `Metrics.finish` increments `StatusSensor`;
- `attempt.record` uses atomic compare-and-swap so an attempt records only its first finish.

This establishes a start/completion boundary mismatch capable of producing percentages above 100%. It does not establish exact event counts for the pasted notification or prove which producer revision was deployed. The calculated `14 / 13 × 100 = 107.69%` was an illustration only; a rounded percentage does not uniquely identify counts.

## Correct metric contract

For failure fraction among completed calls, use:

```text
erroneous completions / all completions × 100
```

Use the same completion metric, scope, grid and aggregation on both sides, with errors as a subset of denominator outcomes. Explicitly decide how authorization/forbidden outcomes affect the numerator; retaining them in the denominator means they are treated as non-alerting outcomes, not removed from the cohort.

Completion fractions do not detect hung calls that never finish. Monitor outstanding calls, age or completion lag separately. A start-based cohort success measure needs request-level cohort attribution, not a same-window ratio of starts and finishes.

Thresholds above 100% are not a reliable disabling mechanism for an unconstrained ratio. Do not infer intent from the number, clamp percentages, or raise the threshold as a substitute for fixing the metric contract. Any correction or explicit muting requires separate authorization and normal configuration publication gates.
