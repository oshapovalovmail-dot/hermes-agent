# Historical metric charts across runtime and cohort changes

Use when a trend must start at launch, history is incomplete, or legacy and native cohort metrics differ.

## Minimal extraction and publication gates

1. For an aggregate connector-error chart, query status groups and independent totals. Add connector×status queries only for a per-connector breakdown; skip tool-ID collection for an aggregate trend.
2. Treat coarse-probe availability or grouped/aggregate mismatches as extraction observations, not proof of a launch date, retention policy or zero traffic. Retry a separately requested supported resolution in bounded chunks and validate it independently; do not reweight sparse points from the earlier probe.
3. Trim each chunk to its half-open interval before merging, key by scope and label, and reject overlapping finite timestamps. For each plotted MSK day, check the exact aggregate timestamp set, status-slot coverage and status-to-total reconciliation. Preserve incomplete or unreconciled daily rates as null. Complete aggregates still do not prove lossless category telemetry.
4. Compute the ratio from unrounded non-ok and total completion integrals on the same grid, not from an unweighted average of interval percentages. Cross-check an overlapping known-good window before publishing recovered history.
5. Label legacy shared-service and native B2B history separately. Use different styles and disconnected segments, mark unavailable intervals and partial launch/end days, and decline growth comparisons across differing scopes. Put these distinctions inside the requested image.

## Archived-denominator gate

Read archived collectors and processors, not only the file named `source.json`. A processor can proportionally redistribute daily denominators to force an all-period total while leaving daily error numerators unchanged. Use original same-day status totals for a daily rate, not the redistributed denominator. If original timestamp grids were not retained, label the archive as an estimate with unverified completeness even when arithmetic passes.

Separate day→connector traffic totals and day→status totals cannot establish day→connector→error counts. Preserve missing joint cells as null; do not distribute aggregate errors by connector traffic share. A legacy service name does not establish B2B attribution.

## Single-image acceptance

- Title identifies an aggregate across connectors versus individual connector series.
- Formula and exact window are visible; percentage refers to completed statuses, not SDK sent calls.
- Cohort changes and gaps are visible without needing a prose attachment.
- The PNG is visually checked for clipped labels, legend/footer overlap and accidental interpolation across missing periods.
- A request for one picture returns one inline image, not a deck or a bundle.

## Verified evidence anchor

`~/out/jeeves-connector-history-20261105/` contains `probe.py`, `collect-fine.py`, `chart.py`, `fine-index.json`, `chart-data.json`, `archive/archive.json` and raw responses. The final explicit five-minute extraction produced 22 complete reconciled Go B2B days and matched all seven overlapping days in the earlier verified connector report. An hourly attempt with differing availability/reconciliation was not used for the final line. Legacy September daily snapshots remained separately labelled estimates because their original timestamp completeness could not be established. These facts validate the recovery gates, not permanent availability dates or a universal resolution guarantee.
