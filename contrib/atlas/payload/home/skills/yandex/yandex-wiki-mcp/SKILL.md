---
name: yandex-wiki-mcp
description: Use for Yandex Wiki pages, grids, comments, and files.
metadata:
  hermes:
    visibility: global
    aliases:
    - stefania-wiki
---

# Yandex Wiki via MCP

Use native `mcp__wiki__*` tools in the `product` profile. From other profiles, call one operation on demand so the Wiki schemas stay out of the prompt.

## On-demand access

Inspect the live schema before using an unfamiliar operation:

```bash
~/arcadia/ya tool mcp connect wiki --list --tool GetPageDetails
```

Read a page:

```bash
~/arcadia/ya tool mcp connect wiki \
  --tool GetPageDetails \
  --arg slug:users/example/page \
  --raw
```

Create or replace a page:

```bash
~/arcadia/ya tool mcp connect wiki \
  --tool CreatePage \
  --arg slug:users/example/page \
  --arg 'title:Page title' \
  --arg 'content:# Page title' \
  --raw

~/arcadia/ya tool mcp connect wiki \
  --tool UpdatePageDetails \
  --arg slug:users/example/page \
  --arg 'content:# Updated title' \
  --raw
```

For precise edits, use `EditPageContent` with the live schema rather than overwriting the full page.

### Delta-backed Wiki notes

A Delta URL `https://delta.yandex-team.ru/wiki/page/<slug>` can expose the same note through Wiki MCP `GetPageDetails(slug=<slug>)`, including `page_type=wysiwyg`. Try this source-preserving API path before browser automation; do not assume every `/page/epad/` Delta URL has a Wiki slug.

For bounded ticket-link insertion, save the complete returned page locally, resolve and read actual Tracker candidates, then prepare exact unique paragraph replacements. Preserve the original text, priorities and existing links; label related/partial coverage instead of presenting it as an exact match. Re-read the page before mutation to detect intervening changes. The exercised `EditPageContent` schema accepts `page_id=<numeric id>` plus `replacements=[{old_text,new_text,replace_all:false}]`, and supports these WYSIWYG notes. Use the numeric id from the read, not a guessed id. After editing, `GetPageDetails` must match the complete intended content and unchanged title; reversing only the inserted additions should recover the pre-edit content. Keep the local before/after/diff as evidence, not as a substitute for the actual Delta note.

## Search and runtime surfaces

The local `ya tool mcp connect wiki` profile and Jeeves production Skills Registry are different evidence planes. Do not infer that a Jeeves production tool is absent merely because the local profile omits it.

For Jeeves production, inspect the current `yandex_wiki` Registry version and its declared tools. Production exposes `wiki__Search` for global discovery. Use it when only a topic is known:

1. Default to `filters.type=page`, a bounded `limit`, `highlight=false`, and relevancy ordering.
2. Treat search results as discovery only; read the selected page with `wiki__GetPageDetails` before answering from it.
3. Use `filters.type=file` only for an explicit file-search task. Do not automatically download or open a found file.
4. If results are empty or ambiguous, refine the query or namespace/cluster; do not invent a slug or silently switch sources.

For Hermes/local operations, inspect the live local schema first. If that profile lacks `Search`, report the local-profile limitation explicitly rather than claiming the production Jeeves skill lacks global search.

## Cached CLI fallback

If `ya tool mcp` fails before contacting Wiki while resolving the latest Sandbox resource, use an already downloaded `mcp` executable from `~/.ya/tools/v4/<resource-id>/mcp`. Discover only inside that tool-cache directory, pin the selected executable for the task, and inspect its live `connect wiki --list --tool <Name>` schema before use. Invoke `connect wiki --tool <Name> --raw` on the same executable. Do not force an update, change credentials, or infer that Wiki is unavailable from a tool-fetch timeout. Read-back verification still applies.

## Verification

After every mutation, call `GetPageDetails` and verify the title plus one expected content marker. A successful mutation response without read-back is incomplete.

For an uploaded source attachment, verify `ListPageAttachments` reports the expected ready filename/id and, when byte fidelity matters, download and compare bytes/hash. `DownloadAttachmentContent` can fail with storage `SignatureDoesNotMatch` because the shared HTTP client sends `Content-Type: application/json` to a signed GET. The verified fallback is `DownloadAttachment` to obtain the authenticated Wiki API URL, then an authenticated GET with redirects disabled; follow its HTTPS storage Location using a fresh credential-free GET without Content-Type. Validate the destination host against the expected Yandex storage domain. Never forward the Wiki Authorization header to storage, or print signed URLs/error bodies; report HTTP status and byte/hash equality only. This is a download workaround, not permission to change the shared client or credentials.

For search, verify both stages: `Search` returns a relevant `title`/`slug`/`url`, then `GetPageDetails` reads the selected page.

## Safety

- Read the existing page before editing it.
- Use partial replacement when preserving concurrent content matters.
- Require explicit user intent before delete operations.
- Keep large YFM content in a file or shell variable; do not fight nested quoting in a one-line command.
