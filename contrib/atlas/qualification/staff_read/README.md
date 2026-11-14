# Staff read preflight regression

Use an already approved Atlas installation with the exact eleven-file read bundle pinned in `bundle-pins.json`, and its prepared native Python. This fixture imports only native source dependencies; it never starts a gateway, sends messages or invokes upstream tools.

```sh
ATLAS_TEST_INSTALLATION="$ATLAS_INSTALLATION" GUARD_CANDIDATE=overlay "$ATLAS_NATIVE_PYTHON" -B qualification/staff_read/test_guard_diagnostics.py
```

`TMPDIR` must name the operator-owned scratch directory. The harness creates its own isolated fixture there and keeps its decision matrix for inspection. Expected result: eight passing tests, including 38 unchanged owner/member allow/block decisions.

The causal baseline uses the same test class and exact prior plugin source:

```sh
ATLAS_TEST_INSTALLATION="$ATLAS_INSTALLATION" GUARD_CANDIDATE=baseline "$ATLAS_NATIVE_PYTHON" -B qualification/staff_read/test_guard_diagnostics.py
```

Expected baseline result: three diagnostic assertion failures, zero import/collection errors. Both versions continue to block the unsupported `fields_to_return` member `department`. The published exact field is `department_group`; the fix does not rewrite either value or widen permissions.

Identity is replaced only at the isolated admission-result seam. The tests do not prove genuine Staff admission or upstream ACL behavior; they prove that validation rejects locally, data/contract failures are not presented as upstream ACL denials, and unchanged native backends remain pinned. The separate deployment/live receipt records real Staff reads.
