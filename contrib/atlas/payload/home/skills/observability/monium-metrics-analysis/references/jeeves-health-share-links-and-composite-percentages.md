# Jeeves health share links and composite percentage triage

Use this when an incident starts from a `https://nda.ya.ru/t/...` Monitoring share link or a screenshot tooltip rather than a metric query.

## Resolve the source without losing the frozen window

1. Send a bounded unauthenticated `HEAD` request to the short link.
2. A redirect to Passport is not a dead end: inspect the decoded `retpath`. It can contain the real `monitoring.yandex-team.ru/projects/<project>/dashboards/<id>/view` URL, including exact `from`/`to` epoch-millisecond timestamps.
3. Convert `from` and `to` to UTC explicitly and preserve the original values. Do not silently replace a frozen window with `now-1d`.
4. Open the resolved URL in an authenticated browser/CDP session and verify title, final URL, and dashboard identity.
5. Prefer dashboard/widget backend JSON for selectors and formulas. DOM text is useful only to verify the page and visible headline values.

## Treat tooltip totals as formulas, not labels

A tooltip can show several mutually distinct series plus a synthetic `Сумма`. Never rename the sum after one component.

Verified Jeeves example shape:

- `Пустые ответы`: 2.91%
- `Неответы`: 1.58%
- `Деградации`: 0.02%
- `Сумма`: 4.50% after display rounding

The valid investigation is therefore three separate numerator contracts and one explicit composite formula. Required checks:

- recover each widget series query and denominator;
- reproduce each component independently for the screenshot date/window;
- recompute the total from unrounded values, then compare with displayed rounding;
- keep Kotlin `jeeves-prod` and Go `jeeves-go-prod` clusters separate;
- do not infer a screenshot's exact window from a different share link, even when both point to the same dashboard;
- trace and classify each component separately before aggregating root causes.

## DataLens product-analytics source

The product-quality chart may live in DataLens rather than the operational Monium dashboard. For the Alice Business dashboard, the relevant chart is on the first visible tab, `Основная`, lower on the page under `Неответы, деградации и пустые ответы`; do not drift into the separate `Jeeves` tab merely because the incident concerns Jeeves.

Validated extraction rules:

1. Open the exact shared URL including opaque `tab=` and `state=` values in an authenticated CDP session.
2. Verify `document.title`, the visible active-tab title, and the target chart heading. Opaque tab IDs do not explain the visible tab semantically.
3. Capture the backend actually used by the current UI. The observed dashboard endpoint is `gateway/root/mix/getDashboardV2`, not the older `getDashboardV1`; chart execution uses `/api/run`.
4. Map the target heading to its widget/chart ID through the dashboard response, then persist the matching `/api/run` request and response.
5. Extract dataset/source, formulas, filters, timezone, grain, numerator, and denominator before using Monium logs or traces for causal decomposition.
6. Treat the DataLens product classification and the Monium runtime event taxonomy as separate contracts until lineage proves how they join.

## Feature Limiter versus product request counts

Before reconciling `LF_JEEVES_DAYS` with Alice Business headline requests:

1. Recover the actual B2B chart SQL. A headline on `Основная` may sum `b2b_user_day.total_request_count`, which includes all B2B scenarios plus knowledge-base requests, rather than Jeeves-only requests. Trace its YQL lineage and query `request_count`, `jeeves_request_count`, `knowledge_base_requests_cnt`, and `total_request_count` separately.
2. A Jeeves B2C headline can use `uniqExact(request_id)` while B2B user-day aggregates use row counts. Reconcile row/unique counts before adding cohorts; distinguish `has_jeeves_call` analytics classification from a limiter decision.
3. Inspect the actual Monium selector: dashboard cluster/model controls do not scope a hard-coded `features_limiter` query unless referenced in its formula. Raw `CAN_PASS_POST.self.decision` with `D_ALLOW` is a decision event count, not unique product requests.
4. Query bounded raw limiter series to verify sensor, request_type, client_type, user_class, and quota flags; do not infer B2B/B2C from user_class alone. Compare the integral at two supported grid resolutions to bound display/downsampling effects.
5. A `Z` suffix in DataLens date-selector state is not proof of UTC-day bucketing. Inspect generated SQL (Date versus timestamp) and actual request timestamp bounds to verify the upstream day timezone.
6. Do not attribute the residual to retries, logging loss, or runtime failure without a request-level limiter-to-product join. Aggregate metrics prove incompatible contracts, not an exact causal decomposition.

## Scope discipline

Keep Kotlin `jeeves-prod` and Go `jeeves-go-prod` separate. If the operator scopes the incident to Kotlin production, exclude Go collection and Go-derived explanations entirely rather than presenting a comparison the user did not request. A scope correction must propagate to denominators, samples, root-cause tables, deployment attribution, and recommended fixes—not merely to the prose summary.

## Reporting contract

State these independently:

1. dashboard identity and frozen window;
2. source-native component names and values;
3. composite formula;
4. reproduced backend values;
5. unresolved mismatch between screenshot and share-link windows;
6. whether counts represent requests, turns, responses, or events.

This avoids the standard observability failure mode: turning a decorative tooltip sum into a confidently wrong incident metric.