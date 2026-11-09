# Optional local extensions

This directory is an explicit, source-only export for this fork. Nothing here is
in the bundled `plugins/` discovery path; nothing activates on checkout. It adds
no core patches, credentials, personal configuration, skills, model weights,
meeting records, project banks, watcher database, or implicit service deployment.
The upstream built-in skills are untouched.

## Complete memory-stack installer

[`memory-stack/README.md`](memory-stack/README.md) is the end-to-end guide for a
**new, isolated** deployment: choose `honcho`, `openviking`, or `both`, serve the
pinned FRIDA ONNX INT8 release locally, and configure the selected native Hermes
plugins. `memory-stack/install.py` provides the explicit prepare/up/check/down
lifecycle. It never runs on checkout, overwrites an existing profile, installs a
watcher, or synchronizes this fork automatically. Read the guide's verification
levels: backend health or accepted writes alone are not proof of derived memory.

The native plugin API was checked against the pinned fork base
`21ae0e1238fdf466fa52a85a6ebf75d6899e49da`, especially
`hermes_cli/plugins_context.py` and `website/docs/developer-guide/plugins/index.md`.
The live docs URL could not be retrieved in the preparation environment; the
checked-out current-main docs and actual registration/discovery tests are the
compatibility evidence, not an assumed legacy API.

## Coverage and exclusions

Source paths below are relative to the local profile's `plugins/`, except where
explicitly identified otherwise. All are code-only, reviewed adaptations, not a
copy of an active profile.

| Source files | Export | Changes / intentionally excluded material |
| --- | --- | --- |
| `reminder-actions/{__init__.py,plugin.yaml}` | `local-plugins/reminder-actions/{__init__.py,adapter.py,plugin.yaml}` | Explicit settings replace watcher path, owner/chat/topic and scheduler IDs. Telegram SDK is lazy. Native authorization remains intact. |
| Local watcher `watch_buttons.py` | `local-plugins/reminder-actions/watch_buttons.py` | Relative imports; scheduler IDs come from each Store instance, not a global operator list. |
| Local watcher `watch_state.py` | `local-plugins/reminder-actions/watch_state.py` | Only `encode`, `link`, and Store constructor/get/put retained. Reject symlink roots/DB; no global umask mutation. |
| Local watcher `watch_followups.py` | `sanitize` in exported `watch_state.py` | Only the rendering sanitizer. Collectors, folder policies, follow-up scanning and scheduler automation are out of scope. |
| `project-memory-bank/{bank.py,__init__.py,plugin.yaml}` | Same files under `local-plugins/project-memory-bank/` | Profile-aware Hermes home, explicit hook opt-in, self-contained pinned helper runtime. No personal bank or skill content. |
| MIT `skill-memory-bank` runtime at `bde42c698f9e20ea196ce2add463c10910b98e64` | `project-memory-bank/runtime/` | Exactly `LICENSE`, `scripts/{_lib.sh,mb-handoff.sh,mb-agree.sh}`, `memory_bank_skill/{__init__.py,handoff_capsule.py,private.py}`. Immutable Git blobs; hashes in `SHA256SUMS.json`. No skill, rules, prompts, agent definitions, installer, registry or project memory files. |
| `meeting-context/{__init__.py,test_plugin.py,plugin.yaml}` | Same files under `local-plugins/meeting-context/` | Bindings/transcript paths must be configured. Removed personal domain/skill instructions. Only synthetic test transcripts/topics. |
| `qyp-delegate/{qyp_delegate.py,__init__.py,plugin.yaml,README.md}` | Code/manifests under `local-plugins/qyp-delegate/`; generic replacement README | Removed operator host/home/workdir/allowlist; strict opt-in settings and physical cwd check. No remote commands were run. No inherited secret environment is persisted in job specs. |
| `web/yandex/{provider.py,__init__.py,plugin.yaml,README.md,tests/test_provider.py}` | `local-plugins/web-yandex/`; tests in `tests/integrations/test_yandex_provider.py`; replacement README | Public direct search URL retained; private workflow origin/ID removed. Optional context endpoint requires explicit HTTPS URL. No credentials/cookies/browser session. |
| Profile `agent-hooks/restrict-arcadia-search.py`, `agent-hooks/role-write-policy.py` | **Excluded** | Live policy authorities contain operator-specific scope. Not copied, modified, weakened, disabled, installed, or replaced by generic templates. Provision a separately reviewed policy before using restricted environments. |
| Honcho staged `pyproject.toml`, `src/config.py`, `src/embedding_client.py`, `tests/llm/test_embedding_client.py` | `honcho/exact-tokenizer.patch` | Exact index-only patch against documented immutable base, with AGPL license and offline unit verifier. |
| Honcho staged `uv.lock`, untracked tests/recovery backups | **Excluded** | Outside the assigned four-file patch. Regenerate the lock in a disposable Honcho checkout if deploying later. |

All profile configuration, `.env`, secrets, state/logs, caches/bytecode, databases,
user transcripts/topics, local skills and weight files are excluded. Watcher
`test_watch.py` tests an entire personal automation and was not copied; focused
synthetic reminder authorization/replay tests replace only the extracted helper
coverage. The two original plugin READMEs contained local operator assumptions;
they were replaced, not published verbatim.

## Installing intentionally (not performed on an active profile)

Use a reviewed Git snapshot of this fork. Copy just the selected plugin directory
from `integrations/local-plugins/` to the intended profile's `plugins/<name>/`.
Use a new/nonexistent destination; do not merge over unknown files or follow
symlinked destinations. `web-yandex` is deliberately flattened from the original
nested `web/yandex` layout. Do not copy this entire repository into a profile.

Use the current Hermes CLI for dependency provisioning/validation and enablement:

```sh
hermes plugins validate /absolute/path/to/copied-plugin --install-deps
hermes plugins enable <name>
```

Then configure the selected profile's `plugins.entries.<name>.settings`.
Every extension requires its own `enabled: true`; simply enabling the manifest
is not permission to read local meeting/project state or execute remote work.
No example below contains an actual operator identity or endpoint:

| Plugin | Required settings beyond `enabled: true` |
| --- | --- |
| `meeting-context` | `bindings_path`, `transcripts_root`: explicit local paths. Mapping format: `{"threads":{"<topic>":{"meeting_id":"<label>","transcript_path":"<absolute .md path within transcripts_root>"}}}`. Topic bindings are trusted operator configuration, not an ingestion endpoint. |
| `project-memory-bank` | None. `bank.initialize(project)` and `bank.bind(session_id, project)` must be called explicitly by the operator; no auto-initialization. |
| `reminder-actions` | `state_root`, `route: {owner_id: <owner>, chat_id: <chat>, thread_id: <topic-or-null>}`, `job_ids: [<approved scheduler ID>]`. Store must be the one your separately configured producer uses. Producer calls `watch_buttons.publish` with the same configured `Store(..., jobs=...)`. |
| `qyp-delegate` | `host`, `remote_home`, `remote_hermes_home`, `remote_hermes`, `default_workdir`, `allowed_roots` (nonempty list of concrete subtrees of remote_home). Values belong to your own approved SSH installation, never this source tree. |
| `web-yandex` | None for direct search. Optional `context_endpoint` must be an explicit HTTPS URL with no userinfo. Set `web.search_backend` to `yandex` or `yandex-context` only after provider registration. |

Settings are non-secret configuration, not new environment variables. Configure
credentials through the platform/provider's normal secret mechanism; never put
credentials in these sources. The pinned MIT bank helper runtime is included
already and needs no fetch, skill installation or package install. Its hash file
checks accidental changes; authenticity comes from the reviewed fork commit,
not a self-signed manifest. Runtime helper upgrades require a new source review.

`reminder-actions` wraps current bundled Telegram adapter internals and therefore
requires revalidation on core upgrades. It is in-process only; never switch off
an operator's plugin isolation policy to make it load. The project-bank runtime
requires Bash and POSIX `fcntl`; Windows has not been validated. Installing it
does not install a skill or give the agent a new project-memory tool.

## Verification scope

`tests/integrations/test_portable_extensions.py` exercises fresh-HOME real plugin
discovery/registration, default-disabled imports, explicit project initialization,
binding, actual vendored handoff/agreement scripts, root/symlink refusals,
reminder owner/chat/topic/message/bot authorization, replay and draft retry,
native adapter construction, QYP disabled-before-spawn and local physical cwd
checks. The existing meeting and web tests use synthetic data and mocked HTTP.
No SSH/QYP, Telegram, search-provider, Honcho server, production, GitHub or HF
operations are exercised. Dependencies were provisioned into separate disposable
PM-built test environments, not an active runtime.

Run through the canonical fork runner with isolated HOME/HERMES_HOME,
HERMES_RUNTIME_DIR and HERMES_PYTHON (include the Telegram extra in a dedicated
PM-built test interpreter):

```sh
bash scripts/run_tests.sh tests/integrations/test_portable_extensions.py \
  tests/integrations/test_yandex_provider.py \
  integrations/local-plugins/meeting-context/test_plugin.py -j 2 --file-timeout 150
```

See `honcho/README.md` for its separately licensed patch and test procedure.
