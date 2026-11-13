# Product-specific supplements to capacity requests

Use when the operator asks to calculate one product's resource contribution in the style of an existing quota ticket. This is a read-only reporting task unless publication or resource changes are explicitly requested.

## Reuse evidence without inheriting an old conclusion

1. Read the live ticket body and linked comment first. Record the current proposed total, reserve factor, compute window, units and separately granted resources. An older report may still propose a quota that has since been granted.
2. Recover retained evidence and scripts from the earlier calculation. Validate source hashes against its manifest when available; preserve those files and write the new calculation separately.
3. Filter the requested product by explicit cohort membership, keeping ambiguous/shared graphs separate. Recompute rather than relabelling the whole department result. Matching peak totals after filtering is a valid finding, not evidence that the broader cohort was already product-specific.
4. Restrict both intervals and evidence coverage to the ticket's exact half-open UTC window. Keep a longer inventory window separately labelled; adjacent monthly windows can differ by a full day.
5. Re-read the bounded set of live process configurations responsible for the decisive peak. Join resource options by block code, project only safe CPU/RAM/count/cluster/pool fields, and compare effective values with retained snapshots. This verifies configuration identity, not actual allocation.

## Reconcile quantities before adding them

Keep three distinct measurements:

- Scheduler allocation integral: integral of sampled allocated CPU.
- Busy CPU: terminal user/system job counters; state whether job_proxy is included.
- Configured-resource scenario: configured limits multiplied by modeled lifetimes, possibly including waiting.

The same CPU-hour unit does not make these interchangeable. A month can have readable nested-operation statistics while every nested service in the shorter comparison window is configuration-only. Recalculate counts after filtering by product, time window and operation kind; label that entire shorter-window row scenario if appropriate. Activity days are not monitoring coverage. Missing counters and inaccessible archives stay unknown.

For terminal operations, independently recompute retained totals from terminal job-state buckets. Exclude stale running-state buckets. Deduplicate by cluster and operation ID; distinguish outer Nirvana cubes from nested services. Apply the baseline pool-overlap exclusions before adding the nested contribution. An unresolved runtime pool remains a possible overlap, not proven separation.

## Same-hour sizing

Compute each resource separately:

`combined(h) = baseline(h) + product_scenario(h)`

`target = max_h(combined(h)) × (1 + reserve)`

Retain the peak hour, baseline value, product contribution and source process links for CPU, RAM and concurrency. Different resources can peak in different hours. Do not add a product's independent monthly maximum to the baseline's maximum on another day.

A baseline built from sums of per-pool hourly maxima is not measured simultaneous concurrency. It can exceed a finer-grained simultaneous peak in the ticket without contradicting it. Label the combined quantity a planning scenario, not a newly measured exact peak.

## Separate arithmetic from policy

Show these fields explicitly:

- Unrounded requirement after reserve.
- Minimum admissible value, including integer rounding for operations.
- Chosen proposed size and rounding convention.
- Delta from the current proposed order, not from an assumed existing allocation.
- Queue reserve policy: `total = running + queue reserve`.

A larger chosen CPU rounding is additional planning headroom, not an unavoidable mathematical requirement. Preserving a previous queue allowance is a policy decision unless queue demand was actually measured. Compute with full precision and round only the displayed result.

## Delivery contract

Return: proposed total and delta → cohort/window → compact usage/scenario table → same-hour formulas → direct source links → concise missing-data note. Attach a self-contained Markdown calculation when detail would overwhelm the chat. Preserve unrelated resources such as tablet bundles, result storage and inference budgets as separate items; refresh their status instead of carrying forward stale orders. Sending calculations to the current chat does not authorize editing the ticket.

## Verification

- Product-only cohort and exact comparison window recomputed.
- All rows labelled with their actual measurement semantics.
- Short-window coverage checked independently of month-level coverage.
- Peak composition reproduced from retained intervals and baseline series.
- Decisive live configurations checked without exporting secrets.
- Simultaneous concurrency distinguished from sums of hourly maxima.
- Arithmetic minimum, proposed rounding and queue reserve separated.
- Existing evidence preserved and no unrequested external writes.
