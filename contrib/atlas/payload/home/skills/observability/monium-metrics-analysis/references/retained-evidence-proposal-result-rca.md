# Retained-evidence proposal→result RCA

Use when an agent failure cohort has summaries or structural projections but raw traces or model-visible tool observations are incomplete. The verified method here is offline reconciliation and honest evidence reporting; live recovery may remain blocked.

## 1. Freeze identity and preserve evidence

- Record the original instance/revision, expected failed row IDs, model and official grading status. Join by exact row ID plus trace ID. Never use a later reduced cohort as proof about the original run.
- Inventory existing files with SHA-256 and sizes before collection. Preserve good projections even when newer reads fail.
- Write new attempts into a separate directory, using create-only names or attempt IDs. HTTP500/504, request-abort metadata and projection exceptions belong in failure artifacts, not successful projection filenames.
- Re-hash the initial inventory after completion and assert zero changes. Hash the actual evidence files used by the report too.

## 2. Audit the projection contract before interpretation

Separate five layers:
1. Shooter/request terminal status;
2. remote transport/activity failures;
3. logical MCP error envelopes;
4. model-output proposals;
5. model-input tool observations.

A boolean `isError:false` is not an error. A lexical occurrence of `isError` does not count errors. Zero transport errors does not exclude logical tool failures. Store both counts separately; do not force them to reconcile.

Inspect stored structure before trusting counters. One retained collector stored `output_stats.tool_proposals=0` while its `output_stats.types` contained hundreds of `tool_call` parts. Recompute counts from the actual type list and document the discrepancy. That reconstruction recovers proposal-part counts only, not names, arguments or call IDs.

A shape export containing `name`, `arguments`, `id` and `response` field types proves schema presence, not their values or successful pairing.

## 3. Reconstruct the observed remote/local trajectory

From ordered model and remote-tool timelines:

```python
last_remote_end = max(
    int(t['start_us']) + int(t['duration_us']) for t in remote_tools
)
tail = [m for m in model_runs if int(m['start_us']) > last_remote_end]
tail_proposal_parts = sum(
    m['output_stats']['types'].count('tool_call') for m in tail
)
```

For zero remote calls, report that fact and use the model timeline when available; do not call `max()` on an empty list.

Record the last remote span ID, name, argument hash, error flag and technical file-extension metadata; count later model calls and tool-call parts. A long tail after the last remote span localizes subsequent proposals to model/local work **in the observed telemetry**. It does not prove whether local calls executed, were rejected, lacked results, or made valid but unproductive progress. Absence of remote spans is not universal proof that no uninstrumented remote work occurred.

Track assistant text parts separately. A terminal tool_call/timeout does not prove no assistant text appeared earlier. An empty final model output also needs to be distinguished from repeated tool proposals.

## 4. Require direct observations for a causal local claim

When exact model observations are available, correlate output `tool_call` IDs with subsequent input `tool_result` IDs. Retain only sanitized technical metadata: tool names, argument keys/hashes, response keys/hashes, boolean error indicators, allowlisted error identifiers and bounded technical signatures. Never persist cookie/CSRF values, signed URLs, raw private documents or raw argument content.

Whole-input regex classes such as TypeError, unsupported extension, validation, cancellation or compaction may originate in retrieved content or earlier context. Record them as leads with their first model index/span, not as causal tool errors. Do not attribute a parser, whitelist, schema or compaction fix until the isolated response/exception supports it.

Use secondary investigator narratives as secondary evidence, especially when the original good projection was lost. Keep exact causes null if the narrative does not preserve the decisive exception. Remote per-tool summary counts can also disagree with original analytics; retain both and label the unresolved discrepancy rather than choosing a convenient total.

## 5. Bound collection without inventing recovery

Establish an explicit small request budget and deadlines; inspect retained evidence first. Use only schema/source/UI-verified filters. Save sanitized failed-attempt metadata separately. Stop when the budget is exhausted and complete the offline matrix with unknowns. Do not turn failed bundle/cache/filter experiments into a recommended recovery recipe or assert the service is permanently unusable.

## 6. Produce and independently verify the matrix

Each row should include identity, original terminal status, official grade/null, model calls, remote calls, transport and logical errors separately, evidence paths, observed boundary, direct-pair coverage, cause/null, hypotheses, missing fields and evidence-specific regression obligations.

Coverage dimensions must remain separate:
- prior HTTP200 summaries;
- retained structural projections;
- direct proposal/result pairs;
- exact causal tool errors;
- verified root causes.

An independent verifier should reopen files and assert:
- unique matrix IDs exactly equal the original failed cohort;
- original instance/revision and null grades are preserved;
- model/remote totals agree with the declared source, or discrepancies are explicit;
- reconstructed type and post-remote-tail counts agree with saved timelines;
- unavailable IDs, arguments and responses are null;
- source hashes verify and pre-existing evidence is unchanged.

A successful artifact verifier proves identity/count/preservation integrity, **not causal completeness**. Say both explicitly.

## Evidence-specific regression obligations

- For a retained same-argument logical-error loop: cite the argument hash, repetition count and boolean error count; require bounded exit even when transport/span status is non-error. Exact rejection-specific handling remains conditional on recovering the envelope.
- For a local/model tail after a completed remote read: cite its span/hash and tail counts; require replay of the first following proposal/response, ID correlation and bounded progress. Do not replace it with an invented remote retry test.
- For changing-query loops: test semantic no-progress, not only identical argument detection.
- For a secondary persistence exception: test terminal persistence separately from the loop that preceded it; do not treat a cleanup assertion as the origin of the loop.
- For an unretained compaction exception: preserve the candidate and exact missing proof; do not declare an existing max-token fix verified from keyword overlap alone.
