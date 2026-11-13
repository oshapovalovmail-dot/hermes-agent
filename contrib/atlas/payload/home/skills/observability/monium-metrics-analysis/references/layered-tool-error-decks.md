# Layered tool-error decks

Use when a report covers both agent SDK tool calls and connector execution outcomes. The method was exercised with Jeeves Go B2B metrics and editable PPTX plus a native PowerPoint PDF; it is not an incident-RCA method.

## 1. Freeze two measurement contracts

Reuse the source selectors and safe Data API access from `references/jeeves-skill-call-status.md`. Record exact half-open dates, timezone, cohort, runtime and resolution before collecting.

| Layer | Numerator | Denominator | Publishable label |
|---|---|---|---|
| SDK outside connector executors | `tool_call_error`: responses with populated protocol error | `tool_call`: sent calls | Errors per 100 sent calls |
| System connectors | Non-ok `skill_call_status` completions | All `skill_call_status` completions | Percentage of completed attempts with non-ok status |

For Jeeves SDK, exclude both `mcp-executor-tool` and `alice-apps-tool` from the first layer's numerator and denominator. Describe the remainder as **outside those executors**, not necessarily a closed inventory of built-in tools. Preserve missing-tool-ID events as unattributed.

Sent calls and error responses cross different event boundaries. Their ratio remains an incidence ratio even when numerically below 100%; it is not the fraction of completed calls that failed. Connector and SDK counts also overlap across abstraction layers. Present separate panels rather than a sum of failed tasks.

## 2. Discover live categories before composing slides

1. Query all observed statuses over the full frozen window.
2. Compare live labels with the local code definition; retain every live label even when the checkout lacks it. Source inspection explains a definition but does not identify the deployed historical revision.
3. Keep access/authorization outcomes separate from transport, timeout and business outcomes. A displayed access group can be derived from exact `forbidden_error` and `authorization_error` values, with the formula retained in notes/source data.
4. Describe `business_error` as an instrumented application error/refusal, not proof of a server defect. A timeout label alone does not distinguish deadline expiry from cancellation. Absent consent-specific telemetry means unknown consent incidence, not zero.
5. Build connector × status and exact-tool-ID × status cuts. Rank tools after merging all retained per-status rows, not after truncating each status to a top-N list. Persist the dominant status alongside each tool total; do not infer causes from operation names.

## 3. Reconcile values and coverage independently

Use bounded chunks and one explicit integration contract. At an explicitly verified 300-second AVG grid, integrate finite RATE values × 300 and round only the final display values.

Check:

- Exact expected timestamps for each independent aggregate, excluding the upper boundary.
- Grouped versus independent sums, daily versus whole-window sums, and matching timestamp slots.
- Coverage separately for aggregate, status, connector and tool series; complete aggregate coverage does not repair a sparse category.
- Nullable full-period counts for incomplete categories and nullable absent matrix combinations.
- Raw-response hashes, exact selectors, retrieval metadata and no retained authentication headers.

Display sparse-category numbers as observed integrals and place the coverage caveat near their chart. Do not turn fractional RATE integrals into claims of exact event-log counts. For a positive ratio that would round to `0.00`, show a threshold such as `< 0.01` instead of a false-looking zero. High ratios on small volumes should retain both counts.

## 4. Six-slide content contract

Adapt the number of slides to the request; this is a reusable compact shape:

1. **Summary:** separate SDK and connector KPI panels; dominant contributor within each layer; no cross-layer total.
2. **Daily dynamics:** two independent charts, each with its own unit and denominator; identify a measured peak without inventing its cause.
3. **Outside executors:** concentration bar and tool table with calls, protocol errors and errors per 100 sent calls. Include a remainder row.
4. **Connectors:** observed status mix and connector table with completions, non-ok counts and completion-based fraction. Access/authorization remains distinct; show category gaps.
5. **Operations:** exact tool IDs ranked by non-ok count, count bars and dominant observed status. Attribute to a connector only when the source supports that association.
6. **Method:** event boundaries, retries, cohort exclusions, coverage and the difference between an error attempt and unsuccessful user outcome.

Keep charts and tables editable. Put source links in slide footers and exact selectors, exclusion lists, formulas and UTC boundaries in speaker notes. Preserve canonical JSON and full technical method alongside the generated files. Deliver the requested PPTX/PDF attachments rather than only local paths.

## 5. Verify the exact delivered artifacts

Load `powerpoint` for native export and visual checks. A successful application command is not proof of export: require the actual PDF file, page count and expected text.

- Reopen the final PPTX and compare its required figures with canonical unrounded data and declared rounding.
- Open, close and reopen the exact final PPTX in native PowerPoint when claiming native acceptance; export the final PDF from that deck.
- Render that PDF and inspect every slide at full resolution, including an independent visual review. Distinguish this from factual/numerical review.
- For compact alternating-row tables, vertically center cell text within the same rectangle as the row background. Inspect baseline placement, not just text-box bounds; a valid box can still put text against the lower edge.
- PDF text extraction can reorder a separately emitted arrow glyph. When a string comparison fails, inspect the rendered page and glyph positions before declaring content missing. If normalization is warranted, keep it narrow and separately verify the glyph; do not weaken all missing-text checks.
- After a targeted layout fix, re-render affected slides. Pixel-compare unaffected slides against the reviewed render; differences confined to source-link/footer styling are not evidence of a content change.
- Record final PPTX/PDF hashes after the last change, not from the previous render.

## Evidence anchor

The validated example is retained at `~/out/jeeves-tool-errors-20261105/`: separate `sdk/` and `connectors/` source data, `raw-manifest.json`, `build.py`, `verify.py`, `native-qa.applescript`, final artifacts and PNG QA. Use it to inspect the workflow, not as current production statistics or a source of today's status taxonomy.
