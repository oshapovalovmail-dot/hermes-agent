# Negative-outcome production investigations

Use this procedure when a dashboard claims that some percentage of production requests had no answer, timed out, failed, or otherwise ended badly.

## 1. Reproduce the percentage before explaining it

Freeze and record:

- dashboard/widget or original query;
- numerator and denominator selectors;
- event versus request versus turn semantics;
- label filters, cohorts, retries, and deduplication;
- timezone and half-open start/end timestamps;
- downsampling and RATE-to-count conversion.

Recompute absolute numerator and denominator counts from the primary API. A displayed `4.5%` is not evidence if the underlying series cannot be reproduced. If the original window is unknown, report that explicitly and compute complete recent windows such as 24 hours and 7 days without pretending they are the source window.

## 2. Attribute the live artifact

Record the production stage, package/resource identity, source commit, readiness, and snapshot timestamp. Keep these claims separate:

1. behavior exists in trunk;
2. behavior is included in the production artifact;
3. the relevant subsystem is live and ready.

A fallback or fix found in trunk does not explain or mitigate production until artifact inclusion is proven.

## 3. Build an exclusive cause taxonomy

Start broad, then add categories only when traces justify them. Typical classes:

- empty model response;
- tool-result-only turn;
- runtime or SDK error;
- timeout or cancellation;
- policy/safety refusal;
- auth, permission, or elicitation continuation;
- child-agent or tool failure;
- answer generated but lost downstream;
- client/UI classification mismatch;
- intentional no-op;
- `UNKNOWN`.

Categories must be mutually exclusive for percentage accounting. Preserve `UNKNOWN`; forcing every trace into a plausible story manufactures certainty.

## 4. Sample traces without fooling yourself

Use aggregate counts first, then draw a stratified sample of negative outcomes plus a control sample of successful requests. Stratify by time, deployment/model/experiment/cohort, and any dominant error labels. Track:

- eligible population and sample size;
- missing or unsampled traces;
- duplicate retries and multi-turn requests;
- coverage of the negative-outcome population;
- whether trace retention biases the sample.

Do not generalize from a handful of visually compelling traces.

## 5. Trace end to end

For each sampled request follow the full path:

`ingress -> runtime -> model/tools/children -> finalizers/guardrails -> outbound response -> client/UI semantics`

A transport failure is not automatically a functional-quality failure. Conversely, a server-side success may still be a user-visible no-answer if the final response is empty, dropped, or classified away downstream.

For each root-cause category retain bounded evidence: selector/query, timestamps, anonymized trace/request identifiers when allowed, source references, and production artifact attribution.

## 6. Find regressions without confusing correlation and cause

Plot the percentage and absolute counts over time. Compare breakpoints with releases, model changes, experiments, flags, and cohorts. Call a relationship causal only when a source/config diff and trace behavior support it; otherwise label it correlation.

## 7. Report decision-grade output

Required output:

- verdict on whether the claimed percentage is reproducible, with exact window and metric contract;
- root-cause table with count, percent of all requests, percent of negative outcomes, evidence strength, and owning layer;
- top causal chains;
- what is already mitigated in production versus only trunk/PR;
- fixes ordered by expected percentage-point reduction and risk;
- verification plan and remaining unknowns;
- evidence appendix with live queries and deployment identity.

Keep raw bounded API responses separate from the canonical summary. Never persist credentials.