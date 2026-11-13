# Atlas — restricted shared research bot

**Source integration qualified. Production activation is disabled by default.**

This project contains a reproducible pinned Hermes patch, restricted plugins, reviewed work-service reads, curated skills and sandbox sources. It is not an exported personal Hermes home: credentials, private memory/history, OAuth, bot tokens, launchd state and active services are excluded.

## Admission and isolation

- DM eligibility matches only real Telegram `Message.from_user.username` to Staff Telegram accounts of an active, nondeleted, nondismissed, nonrobot person. Typed login, display name and internal Staff login are not substitutes. This is **not** Staff-verified numeric Telegram binding; username reassignment remains a risk.
- Groups use an independent **OR** branch: genuine Tasha bot ID `793835103` must be an administrator. No additional per-sender employee or moderation-right requirement is imposed. Unavailable verification denies access.
- Numeric Telegram UID owns private files, memory and owner privileges. Owner comes from installation-owned `control/operator.json`; neither username nor the original creator UID grants that role.
- One gateway serves isolated DM/group/topic profiles and Honcho peers. Groups never import a sender's private DM memory. Stdio CWD, read cursors and artifact origin are bound to the admitted profile.
- The reviewed read bundle exposes **10 MCP tools / 2121 operations / 151 services**. This is reviewed coverage, not a claim that every upstream operation was live-tested. Entity mutations, mail/calendar, Telegram-user MCP, Computer Use and generic host execution are disabled. Trace access requires scoped background-only read wrappers.
- The complete patch applies to the exact fork/commit in `core/upstream.json`; all **28** changed/new runtime files are pinned in `core/patched-files.json`.

## Verified native behavior

The predecessor artifact (admission SHA-256 `cdfaf553a03b1b4c8388c5cdc1aa417130d5934400d6859e51ee43d4bc5f83a9`) passed 17 local native scenarios with real PTB, gateway, profile provisioning, durable FIFO, AIAgent, HTTP model protocol, MCP stdio and final Bot SDK serialization. Two different authenticated fixture senders completed model → `service_catalog` → model → SDK calls through distinct profile processes. External Staff, LLM and Telegram endpoints were explicitly synthetic fixtures, not live corporate/Telegram acceptance. Those 17 scenarios have not been rerun against the ingress and scoped-Principal deltas below.

The current admission source fixes two separately reproduced boundaries: the provision helper now uses native PM's selected interpreter rather than the parent's bare executable; route upsert removes differently named entries only when the complete mapping excluding `name` is identical. Non-equivalent routes remain unchanged, and genuinely ambiguous destinations still fail closed. `scripts/verify_ingress.py` executes 15 portable causal controls through the real provision callback, helper subprocess, native PM selection and native route resolver. It reproduces dependency loss on the old source and route conflict on the PM-only intermediate, then passes on the combined source. This is changed-boundary qualification, not full gateway/model E2E acceptance. The later parent-owned owner-private-chat delivery passed on the scoped-Principal delta below; multi-user and group acceptance remain open.

The additional two-file guard fix constructs the broker `Principal` inside its actual home-scoped plugin package instead of asking unchanged core to import a nonexistent global `qyp_guard.broker`. Issued-binding validity, fresh Staff/Tasha proof, native source/session and exact private profile checks remain enforced. The same construction is used for pre-LLM/tool policy, inbound attachment staging and pending media. Diagnostic telemetry is limited to fixed allowlisted codes and booleans, bounded once per code; exception text, prompts, kwargs and identifier values are not emitted.

`scripts/verify_scoped_principal.py` reproduces the old import failure through real native PluginManager discovery and profile multiplexing with **zero model requests**, without a plugin-directory `sys.path` shim or a global alias. The fixed bytes make **two main local HTTP model requests**, consume the actual `qyp_role` result, and produce the exact final Telegram SDK text. Loaded media hooks allow the own export and deny a foreign profile; loaded dispatch stages selected attachment bytes; Staff revocation adds zero model requests. Media hooks are boundary tests, not live attachment delivery. Nine additional explicit pure tests cover Principal mapping/revocation and bounded redacted telemetry. The 71 admission/provider tests (including nine role/media cases), 15 ingress controls and 22 FIFO/SQLite tests were rerun on the same guard source; these cohorts overlap and must not be summed. The local native regression uses a disabled sandbox and does not claim production startup/readiness, a new Docker qualification or the historical full 17-case pass. Real external model and DOCX/PPTX delivery are qualified separately by the parent receipt below. Exact inputs and path-free evidence are in `manifests/scoped-principal-evidence.json`.

Opaque authorization stays process-local and belongs to a specific durable admission. Only the first durable insert may register it. Exact redelivery, expiry, revocation or loss cannot mint a replacement. Missing authorization produces an unexecuted failed turn rather than empty completed generation. Commit-through-registration and claims share the tracked mutation boundary, including caller cancellation.

Concurrent profile consent writers share a private interprocess lock, re-read and validate current approval, merge homes and atomically replace/fsync JSON. Native creation follows outside the short control-plane lock. Both independently reported replay and consent findings are closed. See `manifests/qualification-summary.json` for exact source hashes, scopes and retained limitations.

## Optional home-channel notice

The generic core defaults to the existing notice behavior. Only explicit boolean `gateway.home_channel_prompt: false` suppresses the native no-home-channel notice; omitted, true and non-boolean values keep the legacy behavior. The check runs after the independent first-contact intro. No home target is assigned, and `/sethome`, scoped secret lookup and actual home delivery are unchanged.

The Atlas config generator sets this flag to false for the root, the private member config and the future profile template. `tests/test_home_prompt.py` executes the exact method AST with bounded config/secret/notice fixtures: two fresh empty-history calls produce no notice, while legacy values, existing homes, history/internal/local/webhook guards, the intro and Slack command remain covered. Run with `HOME_PROMPT_SOURCE="$PATCHED_CORE/gateway/run_turn_prepare.py" python -B tests/test_home_prompt.py`. This is fixture evidence, not real Telegram acceptance.

The complete 24-file patch was physically applied to fresh pinned upstream and all resulting hashes matched; the predecessor's 23 core files stayed byte-identical. The fresh distribution cohort passed 40 tests, including generated root/member/template flag assertions. Native initialization was deliberately not approved for this fresh source-only run, so its native readiness check remained blocked. Independent delta review passed. Working installation activation and two genuine fresh-thread request/reply observations are separate parent-owned gates. See `manifests/home-channel-prompt-evidence.json`.

## Snapshot reads, selected model and resource contract

The current composition retains the Home fix and integrates the independently accepted Snapshot R1 and resource-cancellation fixes. Historical 23/24-file receipts above remain historical. The 28-file patch additionally includes four native MCP files; the resource changes update two already-patched native files rather than replacing the predecessor patch.

Read admission has no artificial request-count, retained-snapshot-count or aggregate retained-byte allowance. Captures use process-private AES-GCM ciphertext in anonymous SQLite storage. Physical ciphertext fragments are at most 65536 bytes, with at most 32 immediately committed fragment-cleanup transactions per maintenance step. These are bounded maintenance units, not read quotas. Logical TTL remains 600 seconds, or 3600 seconds for Tracker; per-result, wire, row and time bounds remain unchanged. Expired cursors are unavailable even while physical reclamation continues.

Only `mcp_servers.atlas_read.circuit_breaker` is explicitly false. Other native MCP servers retain their normal default and malformed-value behavior. The new store is included in bundle collection, dependency-factory pins, sidecar pins and the exact readiness file set. `tests/test_snapshot_integration.py` checks repinning with a changed store and rejects missing or tampered stores. The generated root, served-owner profile and future-profile template select `gpt-6.1-terra` with `agent.reasoning_effort: medium` on `openai-codex`; configuration is not proof of the model actually used in a live turn.

The accepted execution contract is a default and maximum 86400-second script budget (24 hours), a 86520-second native tool budget and an 86580-second gateway watchdog. Container memory is 512 MiB. Per authenticated transport UID, logical user-data storage and the immutable-export maximum are 2 GiB. The source original plus one unchanged immutable export receive one-copy logical accounting credit: physical storage can therefore reach approximately twice the logical limit. This is not a 2 GiB physical filesystem quota. Existing per-file, file-count, input, output, batch, two-slot sandbox concurrency and security boundaries are unchanged. Both top-level and gateway session/chat admission caps are explicitly null, not a higher finite chat allowance.

Export cancellation is checked through the native worker-scoped interrupt bit during streaming and before the bounded registration commit. A pre-commit cancellation rolls back only that operation's snapshot/ledger; prior and foreign exports remain intact. A post-commit interrupt does not revoke an already issued artifact. Restricted document upload uses the native SDK's non-eager file-handle carrier. Real 24-hour execution, dense 2 GiB capacity and actual delivery remain separate from source tests and the earlier sparse-boundary proof.

Re-run the included immutable synthetic Snapshot/SDK fixtures against a prepared source installation, without credentials or business upstream calls:

```sh
python -B scripts/verify_snapshot.py --root "$PREPARED_INSTALL_ROOT" --work "$NEW_SNAPSHOT_FIXTURE_DIRECTORY"
```

The tests exercise more than the former retained-count limits, private cursor replay, foreign-profile rejection, four application errors followed by a healthy read, and R1 bounded cleanup. Native initialization, production lifecycle, the actual Terra/medium bot canary and real attachment delivery are separate acceptance layers. See `manifests/read-home-resource-integration.json` for source bindings and evidence scope. Public activation remains disabled; no QYP gateway, credentials or transport are activated by this source package.

## Explicit instruction-policy consent

Only approved `templates/SOUL.md` is supplied. Presence is not consent. The installer records explicit operator provenance and the exact SHA-256 before home initialization. Native profile creation receives those exact policy bytes; other Hermes homes and policies are not modified.

```sh
python -B -m atlas_dist.install \
  --root "$NEW_ABSOLUTE_INSTALL_ROOT" --owner-telegram-id "$OWNER_TELEGRAM_ID" \
  --trusted-paths "$OPERATOR_TRUSTED_PATHS" \
  --approve-project-policy --policy-approval-provenance "Explicit operator consent"
```

The new root must be fresh and free of symlink path components. Default executable/scope bindings deny access. Telegram and service activation stay disabled. The operator must supply and verify Docker executable, local Unix socket, immutable image, repository scopes, native auth and the corporate provider before permitting that installation's startup. Readiness guards remain mandatory; model tool arguments cannot authorize activation.

## Reproducible source checks

Use Python 3.12+ with the pinned project's native PM-built verification dependencies. Build tools before Telegram/MCP extras. A PM-built test environment is not a separately installed/activated runtime.

```sh
python -B scripts/verify_fresh_install.py \
  --upstream-repo "$READ_ONLY_PINNED_GIT_SOURCE" --work "$NEW_VERIFICATION_DIRECTORY" \
  --approve-project-policy
python -B scripts/verify_username_native.py \
  --root "$NEW_VERIFICATION_DIRECTORY/installed" --work "$NEW_USERNAME_FIXTURE_DIRECTORY"
python -B scripts/verify_portable_profiles.py --root "$NEW_VERIFICATION_DIRECTORY/installed"
python -B scripts/verify_ingress.py \
  --root "$NEW_VERIFICATION_DIRECTORY/installed" --work "$NEW_INGRESS_FIXTURE_DIRECTORY"
python -B scripts/verify_scoped_principal.py \
  --root "$NEW_VERIFICATION_DIRECTORY/installed" --work "$NEW_SCOPED_PRINCIPAL_FIXTURE_DIRECTORY"
ATLAS_GUARD_SOURCE="$NEW_VERIFICATION_DIRECTORY/installed/home/plugins/qyp_guard/__init__.py" \
  python -B tests/scoped/test_boundary.py
python -B scripts/verify_fifo.py \
  --core "$NEW_VERIFICATION_DIRECTORY/installed/runtime" --work "$NEW_FIFO_FIXTURE_DIRECTORY" \
  --approve-project-policy --policy-approval-provenance "Explicit regression-fixture consent"
```

The fresh verifier physically unpacks this source, archives the pinned upstream, applies the complete patch, checks every resulting hash and runs the distribution cohort. Username and profile checks use real native SDK/helper boundaries with explicitly synthetic external Staff HTTP. The FIFO verifier runs 22 exact-core proof/replay/SQLite/atomicity regressions. These commands qualify their stated scopes; they do not send live bot messages or claim live readiness.

`--native --bootstrap-python "$TRUSTED_PYTHON"` additionally performs native PM runtime installation and writes installation-bound launchers. Launchers reject foreign/absent home/runtime and profile selectors. No service is automatically activated. The recorded native positive gateway/MCP qualification used a genuine parent-issued permit confined to its owned fixture; public production policy remained disabled.

## Skills and sandbox

15 complete curated skill packages retain their helpers, templates and assets. Three filenames and four link files are adapted to Arc's filename rules; original filenames and unchanged binary hashes are recorded in `manifests/filename-adaptations.json`. The Docker source uses `COPY --chmod=0555 skills /opt/atlas/skills`, with no host skills mount. The previously qualified immutable image's template/hash and DOCX/PPTX/XLSX/PDF round-trips passed under both default UID and broker UID. The ingress and guard changes preserve every sandbox/image/skill input byte; that unchanged-input evidence is carried forward, not a new image build bound to the new global package hash. This does not assert LibreOffice rendering or a live attachment for this release.

## Parent-qualified owner live delivery

**OWNER_LIVE_DOCX_PPTX_PASS.** On 2026-11-12 the parent accepted one genuine owner private-chat request on the exact current two guard files and unchanged admission source. The real model consumed the catalog result: 2121 operations, 151 unique services, 4407 characters, no truncation. A restricted container generated DOCX and PPTX, immutable exports were sent by the bot, and both Telegram downloads were reopened and checked for the requested marker, catalog totals and tables. For each file, the original sandbox bytes, immutable export and recipient download have the same SHA-256. The DOCX is 37106 bytes; the one-slide PPTX is 29018 bytes. Binary hashes and source bindings are recorded in `manifests/owner-live-delivery.json`, without private paths, user IDs or raw history.

The parent observed network-disabled, read-only-root execution with dropped capabilities, no-new-privileges and only the owned work bind, followed by container removal. The source-publication worker made no live changes or additional canary requests. Separate parent visual rendering QA is not counted as an Atlas rendering capability. Second-human/group delivery, trace/CDP, shared Honcho automatic recall and usability of every catalog operation remain unqualified.

## Remaining live gates and provenance

Source review, unit/SDK/SQLite tests, local native generation, publication, disk installation, process activation and actual recipient delivery are separate receipts. This source release does not itself claim a live second-human/group pilot, live shared-Honcho E2E, all-service upstream coverage or native exhaustion auto-rotation. The latter has a canonical-owner unit control only. A supplementary all-thread startup tracing attempt was partial and is not counted as a second complete native pass.

`manifests/package.json` freezes the publishable source; `manifests/qualification-summary.json` records the completed bounded qualification. Raw local traces and private machine paths are not bundled. Rollback never auto-starts launchd. Licenses and asset restrictions remain in `NOTICE.md`, `LICENSE` and source provenance.
