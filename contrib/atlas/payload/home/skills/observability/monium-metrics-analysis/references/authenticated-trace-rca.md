# Authenticated Monium trace RCA through a logged-in browser

Use this when a direct/headless Monium or Temporal URL redirects to Passport but the user has explicitly authorized inspection through an already authenticated desktop browser.

## Recover the trace URL from a failed Nirvana Shooter job

When `yt get-job-stderr` exposes only Job Launcher output, a killed `diagnostics_daemon`, `COMMAND/RETURN_CODE`, or the final generic fail counter, use the operator-authorized Nirvana UI before guessing at infrastructure:

1. Open the exact failed Shooter result and its **Logs** tab in the already authenticated browser.
2. Search the logs for `Fatal ATS error` to recover the exact ATS request ID.
3. Search for that request ID to recover the row ID and Temporal URL.
4. Search for `trace` to recover the exact Monium URL emitted by the client.
5. Open that Monium trace and continue the error-span/LLM-turn procedure below.

The Nirvana log selector may show only a subset such as `2/11`; a substring search is more reliable than scrolling the currently virtualized tail. Keep Job Launcher death, Shooter `FailCounterExceeded`, ATS `Fatal ATS error`, and the inner Pi/model exception as separate layers. Never classify `diagnostics_daemon` death as causal merely because it appears in YT stderr.

## Procedure

1. Open the exact trace URL in the user's authenticated browser profile. Do not type credentials or interact with password/2FA dialogs.
2. If the browser was intentionally launched with a local Chrome DevTools Protocol port, enumerate `http://127.0.0.1:<port>/json/list` and bind to the exact page by URL/title. Do not attach to unrelated personal tabs.
3. Read `document.body.innerText` through `Runtime.evaluate` to confirm the trace ID and loaded content. Prefer the trace UI's error-span filter (`span.status = "error"`) rather than guessing from the root span.
4. Open each error span and record:
   - operation/span name and span ID;
   - exact status description/exception;
   - last successful parent or sibling boundary;
   - downstream wrapper errors separately from the causal error.
5. For agent/model failures, switch to the LLM trace and reconstruct the ordered sequence: model turns, tool calls/results, final stop reason, terminal assistant content, and artifact publication. Distinguish model behavior from harness conversion and ATS/Shooter wrappers.
6. Redact credentials, tokens, signed URLs, raw private payloads, and file bytes. Preserve IDs and bounded error strings needed for causal attribution.
7. Classify only after the inner exception is visible. Generic wrappers such as `Fatal ATS error`, `request processing failed`, and `FailCounterExceeded` are effects, not root causes.
8. Feed the exact evidence into the active planner/developer/reviewer chain before rerunning. Never spend a canary on a blind retry when the trace proves a deterministic harness defect.

## Verification standard

A complete RCA states: exact failing component, model/runtime identity, causal exception, trigger trajectory, last successful boundary, downstream propagation, and whether the failure is code, model behavior, or infrastructure. If any of these remains unknown, label the RCA incomplete.

## Validated pattern

A successful investigation used the logged-in Yandex Browser plus its explicitly enabled local CDP endpoint to reveal a Pi runtime `ProtocolError` hidden behind ATS and Shooter wrappers. The LLM trace showed a successful tool result followed by repetitive reasoning until `stopReason=length`, no terminal assistant text, and then harness conversion into transport failure. The durable lesson is the layered attribution method, not the session's IDs or error string.
