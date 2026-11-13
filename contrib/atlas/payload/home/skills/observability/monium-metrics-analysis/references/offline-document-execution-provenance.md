# Offline document-execution provenance

Use for read-only verification of original document processing from retained Monium JSON. This procedure establishes evidence coverage and joins; it does not recover absent runtime payloads.

## 1. Establish scope and coverage

Honor local-only/no-write constraints: operate in memory on explicitly supplied files and permitted sibling directories. If a parent search is rejected because it may enter a protected mount, narrow to already authorized subdirectories; do not bypass the guard or traverse the mount. Avoid recursive inventories of virtual environments.

Inspect `response` before indexing: exports can contain an empty response rather than `response.logs`. Distinguish an empty export from proof of no events. Record row count, minimum/maximum `time`, and presence of a nonempty `response.continuationToken` (do not print its value). A capped newest-first page may contain completion bookkeeping while omitting earlier execution. Absence of continuation only describes that query's coverage, not the whole request's telemetry.

Normalize Go `meta` arrays of `{name,value}` for lookup, but retain each original index for citations. Bind evidence to exact request/task/context IDs and the request marker; a similarly named export may describe another turn.

## 2. Extract safe projections first

Start with row index, logId, timestamp, message category, metadata key names, field types and value lengths. Project only allowlisted technical values afterward. A prefix/suffix of `Push ToolTaskRequest` can still contain request/account information; length clipping or a URL regex is not sanitization. Do not print whole payloads, signed URL queries, credentials or document text.

Keyword searches locate candidate rows, not facts. Identify whether each hit is a user instruction, model proposal, dispatch header, actual tool-result envelope, model final text or UI record. Retain original JSON paths through any decoded nested string.

## 3. Keep the evidence layers separate

| Layer | Evidence needed | Does not prove |
|---|---|---|
| Attachment registration | `files`, `types`, `fetchable`, `known_locations` | Runtime read or byte identity |
| Dispatch/access | Tool ID, call ID, permission decision | Backend choice or successful execution |
| Runtime | Correlated result containing backend, runtimeVersion, exitCode | Correct input identity unless hashes are also observed |
| Input identity | Locally computed original SHA256 equals runtime-observed input SHA256 | Identity from filename, count or MIME type alone |
| Output generation | Actual result FileId/name pairs | Presentation or successful download |
| Model/final | Exact response body with output references | A `RunModelActivityHandler: response` bookkeeping line is not that body |
| UI presentation | Saved card/download provenance linked to output FileId | `card pushed` artifact IDs may be agent-steps, not document IDs |
| Download/content | Successful native download plus local binary validation | Generated attachments or visible cards are not downloaded documents |

Compute hashes from original bytes, not extracted text or previews. Multiple attachment entries may represent one original plus extracted text; classify by type rather than equating attachment count with original count. If runtime hashes are absent, report local hashes as a baseline and the comparison as unavailable.

Join output FileId/name pairs independently across tool result, model final and UI provenance. Do not fill missing IDs from expected names in the user prompt. A failed download is evidence of delivery failure at that boundary, not proof that generation failed. Context supplied by the parent/user must be labeled as such when the source JSON does not corroborate it.

## 4. Compact report contract

Lead with confirmed / not established. Include:
- Per-source coverage and continuation status.
- Decisive claims with file alias, zero-based `response.logs[i]` path, logId and exact metadata index/name.
- Original fixture basename, byte size, computed SHA256 and runtime comparison status.
- Backend/runtimeVersion/exitCode and output pairs, using unknown/null when absent.
- Separate counts for registered originals, generated outputs, displayed cards, downloaded binaries and content-validated binaries.
- Missing evidence needed to close each gap; state whether any files were modified.

## Validated boundary example

A retained audit had 500 ATS rows with continuation and only a short completion tail; a separate 35-row Go stage export ended before that tail. Stage metadata showed four binary and four text entries plus a sandbox access exemption. ATS contained four validate dispatches and four present dispatches, but no runtime backend/version/exit code, input hashes, output FileIds or final answer body. Local fixture hashes were computed successfully. The defensible result was a coverage gap, not successful execution. UI cards and a reported HTTP401 download were kept separate from downloaded-document verification. This is an example of sound offline evidence classification, not a claimed recovery method for missing logs.
