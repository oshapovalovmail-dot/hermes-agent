# Product dashboard → runtime attribution

Use this when a product dashboard percentage is being interpreted as a service/runtime failure rate.

## Decompose the contract before traces

1. Read the product aggregate table and its request-grain source separately. A denominator can include cohorts that never contribute matching numerator fields. Record each component explicitly.
2. Split request rows by an explicit runtime-attribution field, then prove that attribution against runtime hosts for every candidate request before naming the slice after a runtime. Subtraction from a product total is useful for accounting, not host attribution.
3. Preserve both row count and unique request-id count. Retries and duplicate rows make them different grains.
4. Build mutually exclusive reason counts from source-native flags and reason fields, then inspect the canonical producer semantics. A flag name is not its meaning.
5. Reconcile product flags as runtime-attributed + non-runtime-attributed, and report both percentage within the runtime cohort and contribution to the product KPI in percentage points.

## Known semantic traps

- A visual/Rich UI answer can have empty textual `reply`. If `not_answered` tests only empty text and ignores visual payload presence, it is a deterministic metric false positive.
- A reason such as deferred-event loss proves an analytics/join gap, not necessarily a user-visible failure. Successful service traces still do not prove terminal UI delivery; keep that outcome `UNKNOWN` without downstream/client acknowledgement or state readback.
- User cancellation, policy outcomes, visual-only responses, backend degradation, and telemetry loss must not be summed into a metric named simply “service no-answer”.

For a small static mart, project only date, runtime-attribution, category flags, and reason fields with a bounded `read-table`, then aggregate locally. Persist structural counts rather than request/reply text when content is unnecessary.

## B2B v4 audience and request fallback

When authenticated DataLens cannot render, inspect the live mart metadata before reusing old v2 formulas. The verified v4 namespace is `kolmogorov://home/alice-dev/analytics/online/itangaev/ADA-6344/v4/`:

- `b2b_users_days` has `date`, `puid`, `company_id`, `chats_cnt`, `jeeves_cnt`, `knowledge_base_cnt`. Unlike v2, `chats_cnt` excludes Jeeves. Activity requires **chats_cnt + jeeves_cnt + knowledge_base_cnt > 0**. Omitting Jeeves substantially undercounts DAU.
- DAU is distinct nonempty `puid` per date; WAU deduplicates identities across the full week. Organization identity can differ between user-day and request marts; name the source and do not silently reconcile them.
- `b2b_requests` has `date`, `request_id`, `puid`, `request_type`, `generic_scenario`, `like_count`, `dislike_count`, file flags and product outcome flags. Verify schema live. `has_answer` was all false in an exercised recent cohort, so do not use it as a success KPI without a producer contract.
- Both tables were sorted by date. `yt.TablePath(..., columns=[...], lower_key=['YYYY-MM-DD'], upper_key=['next-day'])` permits bounded projected reads without whole-table scans. Keep identities in RAM, persist only aggregates, then independently cross-check recent DAU/WAU against request-grain identities.
- A stale v2 table and fresh v4 table can coexist. Read modification times and discover the version under the known analytics namespace.
- Local Python without YSON bindings needs `read_table(..., format=yt.JsonFormat())`. CHYT can redirect to an unresolvable heavy proxy even with discovery disabled; bounded native YT reads succeeded as an alternative. A retry recovering transport does not explain the network root cause.

## Mutable sources

A screenshot can become unreproducible when a daily mart is rewritten. Record table modification time and pipeline run identity. Preserve the screenshot and current reproduction separately; never infer an old numerator from rounded display values. Recommend immutable daily revisions and tooltip-level numerator/denominator/provenance.

## Deployment correlation

1. Capture the authenticated UI's actual history request/response through CDP Network events when a hand-written replay lacks UI-injected metadata.
2. Bucket request timestamps by exact deployment event seconds.
3. Compare source commit, artifact identity, environment/config diff, and rollout boundaries—not release names alone.
4. Check whether an explicit environment value merely repeats the exact artifact's built-in default; a semantic no-op is not a causal change.
5. Keep a breakpoint as correlation unless the source/config diff and trace behavior establish causality. Rolling restart, traffic shape, artifact rebuild, or log-join load can mimic a release regression.

## Jeeves-specific source semantics

For the validated Alice Business/Jeeves case:

- `b2b_user_day.total_request_count` includes `request_count + knowledge_base_requests_cnt`, while category numerators originate from request rows.
- `has_jeeves_call` is the product-side candidate attribution; confirm it with `jeeves-prod-*` logs for Kotlin.
- `reply_source=rich_ui_cards` means a valid visual answer even when text is empty.
- `reply_source=empty_because_of_deferred_loss` means the streaming main record exists but the deferred analytics record was not present/joined; user delivery remains unknown.
