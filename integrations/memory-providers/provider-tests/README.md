# Manual pinned-provider offline contracts

This is an **opt-in contract cohort**, not part of the default root `tests/`
discovery or a claim about production/backend acceptance. It imports explicitly
staged Honcho/OpenViking plugins and exercises real provider queues, Honcho SDK
serialization and OpenViking HTTP serialization. Only transports are recorded;
`conftest.py` blocks real socket connections and removes provider/credential env.
No third-party provider sources are vendored in this checkout.

## Interpreter and stage

Use an isolated interpreter containing this checkout's host dependencies,
`pytest`, `httpx` and **`honcho-ai==2.9.0`**. Set `PY` to that interpreter.
The stage must contain `honcho/__init__.py` and `openviking/__init__.py` plus their
respective plugin files. Missing stages fail explicitly; they never skip green.

Once the provider packaging has been separately reviewed and approved, a clean
checkout can reconstruct the pinned sources and approved patches **offline** from
an existing source cache. Choose new, task-owned destinations outside production
homes (these commands are documentation, not automatic test setup):

```sh
STAGE=/absolute/task-owned/new-provider-stage
CACHE=/absolute/task-owned/provider-source-cache
"$PY" integrations/memory-providers/install.py honcho \
  --source-cache "$CACHE" --destination "$STAGE/honcho"
"$PY" integrations/memory-providers/install.py openviking \
  --source-cache "$CACHE" --destination "$STAGE/openviking"
```

**Candidate v3 note:** packaging/manifest rebuilding is still approval-pending.
The current package patches do not represent the v3 staged source hashes. Until
that separate approval/rebuild, select the reviewed task-owned v3 stage directly;
do not treat the old reconstructed package as v3. Tests never reconstruct, install,
activate, fetch providers or change an installed runtime.

## Canonical execution

From the actual checkout root (its basename need not be `repo`):

```sh
HERMES_PYTHON="$PY" HERMES_HOME="$TEST_HOME" \
HERMES_RUNTIME_DIR="$TEST_TOOL_STORE" HERMES_TEST_FILE_RETRIES=0 \
  scripts/run_tests.sh integrations/memory-providers/provider-tests -j 4 -q \
  -- --provider-stage="$STAGE"
```

The explicit `--` is required for the custom pytest option. The canonical runner
cleans its environment, so exporting `PROVIDER_STAGE` or a new test variable alone
cannot forward it. The cohort-local wrapper captures the test-only stage setting
**before** shared conftest sanitation and transports it as the explicit pytest
argument through the unmodified canonical runner:

```sh
HERMES_TEST_PROVIDER_STAGE="$STAGE" "$PY" \
  integrations/memory-providers/provider-tests/run_offline.py \
  integrations/memory-providers/provider-tests -j 4 -q
# Or pass --provider-stage "$STAGE" to run_offline.py directly.
```

The wrapper sets its interpreter explicitly, isolates HOME/runtime directories in
owned temporary scratch, disables file retries and delegates to
`scripts/run_tests.sh`; it does **not** run bare pytest. Both fixtures respect
`TMPDIR` (the canonical runner gives each file its own scratch root). They resolve
the host as `Path(__file__).resolve().parents[3]`, never `TASK / 'repo'`.

For the existing task layout only, the default remains
`<actual checkout parent>/plugin-staging`, so the original native task command
continues to work without a selector. A fresh checkout should always pass the
explicit stage argument or use the wrapper variable above.

## v2 evidence

`test_provider_review_v2.py` reproduces the three independent review blockers and
the conditional author field shape using native SDK/HTTP serialization.
`test_fixture_portability.py` uses a renamed minimal host and explicit external
stage marker modules to prove fixture selection/env transport, independently of
the native-provider contract cases. Positive controls retain genuine human prose,
inline/multiline backticks, fenced XML, blockquotes and literal reasoning words.
The guards are public in-process filtering, **not adversarial containment** or
semantic classification of arbitrary untyped summaries.

## v3 preservation evidence

`test_provider_review_v3.py` targets only the two remaining preservation defects:
Honcho chunk rechecks losing the original fence/multiline-code-span context, and
both guards accepting an info-suffixed code line as a closing fence. Fixtures are
explicit bounded literals, never evaluated expressions from a review report.

The native Honcho cases cover the unchanged 25000-character default and a small
64-character cap, tags before/at/after the first and second chunk boundaries,
queued high-level turns, failed native sends and retries. They assert exact human
and final bytes, per-message wire caps and resolved peers. A private immutable
slice carries the complete safe logical assistant text; every lower recheck
parses that whole text again and requires exact slice equality. It is not a
caller-controlled `_capture_final` skip flag. Direct/legacy rows and altered
builder rows retain raw-envelope exclusion.

Both native serializers additionally preserve fence-like content with info
suffixes, then exclude closed and unclosed raw reasoning after a genuine
whitespace-only closing delimiter. No transport, package or runtime is activated.
