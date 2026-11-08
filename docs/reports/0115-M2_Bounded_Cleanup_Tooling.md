# Epic 0115 M2: bounded cleanup tooling

## Frozen implementation scope

This milestone adds [`cleanup_0115.py`](../../scripts/cleanup_0115.py), a local CLI for planning
and applying exact file removals from one explicit root. The `plan` command is dry-run. Apply binds
to the frozen source-manifest digest, source revision, root, candidate paths, candidate hashes and
sizes, protected dependency identities, and a per-plan receipt. It rejects symlink paths,
unresolved references, changed identities, and open files under the selected root. The receipt is
atomic and records per-file progress before mutation so an interrupted apply can resume safely.

The only production manifest input is
[`cleanup-plan.json`](0115-M1_Recovery_and_Cleanup_Plan.artifacts/cleanup-plan.json), frozen at
`docs/reports/0115-M1_Recovery_and_Cleanup_Plan.artifacts/cleanup-plan.json`. The only selected
root is `data/operations-recovery/0108-m10-20261105/recording-videos`; the exact set is its 51
listed recovery-video files. The retained recovery subtree and every path outside that root are
excluded. The M1 manifest says deletion is not authorized and contains unresolved references, so
the tool must refuse apply against it. M2 performs no operation on retained user data.

Temporary fixtures cover default dry-run, protected dependencies and unknown references, stale
manifest/file identity, symlink escape, open-file writer detection, interrupted apply, repeated
apply, and proof that planning writes remain inside the fixture root. No real data deletion ran.

Frozen commands:

```sh
mise exec -- uv run --project operations pytest operations/tests/test_cleanup_0115.py
mise exec -- uv run --project operations ruff check scripts/cleanup_0115.py operations/tests/test_cleanup_0115.py
mise exec -- uv run --project operations ruff format --check scripts/cleanup_0115.py operations/tests/test_cleanup_0115.py
```

Commit boundary: the CLI, its focused fixture tests, this report, and the 0115 epic/board/handoff
update in one commit. This milestone implements tooling only. M3 owns reference audit, recovery
drill, and any decision to authorize a real-data removal.

## Result

The focused fixture suite passed all 10 tests. It includes receipt replacement after preflight,
concurrent apply rejection, and receipts that claim a present file was removed, contain an extra
candidate, or omit the observation for a missing file. These fail before mutation or completion.
Ruff check and format check passed, as did `git diff --check`. The M1 manifest cannot authorize
apply: it has no explicit deletion approval,
does not declare a complete reference audit, and retains unresolved references. Its selected
production root is absent from this checkout, so the only writes were temporary test-fixture plans
and receipts. No real retained data changed.

The tool refuses apply if `lsof` is unavailable or reports any open file below the selected root.
It also refuses hard-linked candidates. It writes plans and receipts below the selected root and
fsyncs progress before and after each removal. Before resuming or returning a completed result, it
checks receipt metadata, the exact candidate list and planned identities, and whether each file is
present or absent as its recorded status requires. A file marked removed that is still present and
any extra receipt candidate both fail closed. A file missing after a durable `deleting` status is
treated as an interrupted removal and can be reconciled on the next apply. Apply acquires an
exclusive lock for the cleanup root, reloads and validates the receipt under that lock, then uses
that validated receipt in memory. This serializes cleanup applies and prevents stale preflight state
from authorizing a second apply. M3 must complete the reference audit and recovery drill before it
can create an authorized manifest for the M1 candidates.
