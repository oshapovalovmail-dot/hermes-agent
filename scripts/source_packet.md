# Lossless local-research source packets

`python scripts/source_packet.py` is a standalone CLI, not a new model tool. It
never discovers files, chooses relevance, invokes a model, or modifies the source
study. Use an explicit frozen manifest whose byte digest you retain separately.
Every listed file is mandatory. There is no `selected`, truncation, fallback to
summaries, or excluded-file inference.

## Freeze an explicit input

Prepare a private input directory using only the already-authorized list of
files. Preserve the full original user/study instruction as strict UTF-8 bytes;
do not rewrite it to make a packet smaller. Preserve exact source bytes too.
The manifest schema is deliberately small (substitute actual lowercase digests):

```json
{
  "version": 1,
  "revision": "optional-frozen-source-revision",
  "instruction": {"path": "instruction.txt", "sha256": "<64 lowercase hex>"},
  "files": [
    {"id": "S1", "path": "src/component.py", "sha256": "<64 lowercase hex>"}
  ]
}
```

All paths are canonical POSIX-relative paths confined below `--root`. Duplicate
IDs, paths, or JSON keys, traversal, controls, absolute paths, symlinks (even
in-root links), special files, invalid UTF-8 and digest drift fail closed. IDs
are literal `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`. Unknown manifest fields are
rejected rather than silently discarding an old `selected` contract. When
adapting a historical inventory, the owner must explicitly freeze the permitted
file list and the complete instruction; this CLI does not make that selection.
No recursive discovery is needed or performed. Directory-fd/no-follow support
is required; unsupported hosts fail closed.

`--manifest-sha256` pins the exact manifest file bytes, not a reserialized JSON
object. The CLI checks that pin and all source/instruction digests, and then
copies the admitted bytes into a new private bundle (`0700` directories, `0600`
files). Outputs must be outside the frozen root; existing outputs and symlinked
output-parent paths are refused. Use an owned, stable output parent, not a
shared directory another process can replace during creation. Do not place a
private bundle in a public repository.

## Consumer without tools (including `--toolsets ''`)

```bash
python scripts/source_packet.py build \
  --root /owned/frozen-input --manifest manifest.json \
  --manifest-sha256 "$MANIFEST_SHA256" --output /owned/inline-bundle \
  --mode inline --consumer-tools none --consumer-id research-reader \
  --max-packet-bytes 80000
python scripts/source_packet.py verify \
  --bundle /owned/inline-bundle --manifest-sha256 "$MANIFEST_SHA256"
```

Send **every** artifact listed in `coverage.json` → `packets`, in numbered
order, to the intended all-source analysis workflow. Each packet is complete
JSON usable as a query file, including the complete unchanged instruction and
the source-data safety policy. The byte cap includes instruction, JSON escaping,
source metadata, numbering, newline and source text. It is **not** a model token
estimate; choose a byte budget appropriate for the actual model and output
reserve. An instruction/index that cannot fit causes an error, never shrinking.

Source chunks contain `id`, original `path`, full-source `sha256`, zero-based
half-open `byte_start`/`byte_end`, inclusive original `line_start`/`line_end`,
and `lines`: `[original_line_number, exact_text]` pairs. Text includes original
line endings, BOM and final-newline state. Concatenating UTF-8-encoded text in
packet order reconstructs each source exactly. Empty files have an explicit
zero-byte, zero-line span. Files split at original line boundaries. If one line
alone exceeds the entire packet budget, it continues across disjoint UTF-8
byte ranges with the same original line number (never a made-up line number).

The coverage register maps each ID to every source range and packet; it records
packet digests, exact sizes, total input/covered bytes, and original source and
instruction identities. Source bytes are disjoint across the full inline packet
set. The instruction/policy intentionally repeat so safety constraints survive
separate continuations. Individual packets are subsets, not full-project proof.
Retain source IDs/ranges and coverage during synthesis and explicitly report
unread/failed packets; do not assert global absence from one packet. This CLI
builds and verifies delivery, not research orchestration or synthesis quality.

## Consumer with complete file reading

Indexed mode is allowed only after the caller checks the **actual future
consumer's** file-read tools and maps the entire bundle into its accessible
filesystem. A tool name alone is not proof of full reading: check paging beyond
preview limits. Create a readiness JSON file below the frozen root:

```json
{
  "version": 1,
  "consumer_id": "research-reader",
  "tools": "file-read",
  "manifest_sha256": "<exact frozen manifest digest>",
  "artifact_root": "/owned/indexed-bundle",
  "read_all_sources": true
}
```

`artifact_root` must equal the resolved, intended bundle path. `consumer_id`,
tools, manifest identity and the all-source obligation must match explicitly.
This is a caller attestation, **not** an automatic/live capability probe.

```bash
python scripts/source_packet.py build \
  --root /owned/frozen-input --manifest manifest.json \
  --manifest-sha256 "$MANIFEST_SHA256" --output /owned/indexed-bundle \
  --mode indexed --consumer-tools file-read --consumer-id research-reader \
  --readiness /owned/frozen-input/readiness.json --max-packet-bytes 80000
python scripts/source_packet.py verify \
  --bundle /owned/indexed-bundle --manifest-sha256 "$MANIFEST_SHA256"
```

The single `packets/00000001.json` is a stable compact source index with the
unchanged instruction, safety policy, every source ID/path/hash/byte and line
count, and relative artifact path. `sources/NNNNNNNN.txt` are complete exact
source bytes. Paths are relative to the delivered bundle, **not** the original
source tree. Consumer mounting/root binding remains the caller's responsibility.
Index bytes are stable for identical manifest/source/instruction bytes and do
not depend on output-directory names. An over-budget index fails closed; choose
an explicitly larger budget or inline packets, never trim the source list.

Never send the index to a tools-disabled consumer. Never give a consumer only
the index while omitting the actual artifacts. If readiness cannot be established,
use explicit inline mode, not a silent fallback or a smaller relevance sample.
Require consumer reading receipts before claiming all sources were analyzed.

## Verification and acceptance boundaries

`build` reads its written output back before printing `status: verified`.
`verify` needs only the copied bundle and the separately retained manifest pin;
it checks all admitted source/instruction bytes and deterministically rebuilds
all expected packet bytes and the coverage register. Packet corruption, missing
source bytes, altered ranges/IDs and changed coverage fail. Neither command
recursively enumerates unrelated inputs or bundle files. Unexpected extra bundle
files are not admitted evidence. The manifest pin is a caller trust boundary,
not a cryptographic signature or a model-reading attestation.

A successful build/verify establishes byte-identical delivery and packet bounds.
It does **not** establish model reading, answer factual sufficiency, improved
reasoning quality, end-to-end latency or production/live behavior. Test those
separately against frozen complete-input baselines. Preserve original user
constraints in all downstream continuations and keep corporate text/private
bundles outside public tests, commits and shared receipts.
