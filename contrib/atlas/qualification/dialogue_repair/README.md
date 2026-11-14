# Portable dialogue repair qualification

Run from project root using an existing interpreter with python-telegram-bot and
jsonschema. No installations, credentials, gateway startup or native CLI calls:

```sh
"$PYTHON" -B qualification/dialogue_repair/run_qualification.py --phase green
```

Optional `--dependency-path "$EXISTING_SITE_PACKAGES"` exposes an already installed,
ABI-compatible dependency directory read-only to child imports. The runner strips
ambient session/auth variables and uses `-B`; no environment is installed/modified.

`test_identity.py`: original 23 reviewed methods, actual public plugin and services,
frozen native admission/session source fixture, synthetic Staff/bot. Only four
plugin imports and two fixture modules are copied to an owned temporary directory;
public services are imported in place. Synthetic operator.json is fixture-only.
`test_arcanum.py`: original seven reviewed methods, actual public sidecar; a narrow
synthetic ACL is bound only in memory, never persisted to the public payload.
`test_payload_seam.py`: five public pin-chain/bindings/SOUL/fixture checks.

Red/green receipts include actual exits, executed method counts and hashes.
`validation-env-*` and `production-env-*` retain the unsuccessful dependency probes;
they are not causal RED evidence. Canonical RED is `red-receipt.json`.
`public-baseline.json` captures only this change seam and fixture provenance, not
an overall distribution freeze. Full acceptance scope and gaps are documented in
`docs/DIALOGUE-REPAIR-ACCEPTANCE.md`.
