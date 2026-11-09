# Epic 0118 M4: lifecycle closure

Date: 2026-11-09

## Result

No lifecycle contract from M1–M3 authorizes expiry or removal. M4 adds no cleanup code and
removes no data. Close the selected scope with every affected log, recovery copy, training view,
review root, and recovery root preserved.

## Decisions

- **Managed-job logs:** M1 found the configured `jobs` root absent in this checkout. The current
  writer retains at most 1,000 entries, but it has no per-entry byte limit or independent restore
  source. The M1 concurrent append/read and restart test passed again. Do not add expiry or change
  the existing writer behavior.
- **Accepted-loss recovery copy:** M2's current verification still matches snapshot
  `c8979c9a53956abd749e638466e1f88009f2e0ce8e725d674bf26ff0335ed430`. It validates 2,086
  resources and 34,414 manifest file records, including 150 retained human-work records. The
  recovery package and active node store share a volume. There is no independent recovery source,
  declared recovery window, or expiry condition. Preserve the package.
- **0070 M5 training view and review dependencies:** the 0071 materializer still consumes the
  view. The fresh M3 audit verified 1,328 restored files and 537 rows. All 24 immutable revision
  manifests and content match. Only 7/24 expected mutable states and 0/24 drafts match across the
  bounded recovery candidates. The other 17 exact states and all 24 exact drafts remain unavailable.
  Do not infer their content or remove the view or any known review/recovery root.

Unknown references fail closed: no manifest, pin, or reference analysis can authorize removal
while the relevant owner, exact recovery source, historical state, or draft remains unresolved.
No removal manifest or durable removal receipt is applicable because no removal was authorized.

## Storage effects

- Logical removal: 0 bytes.
- Relocation: 0 bytes.
- Path allocation change: not measured; no files were moved or changed.
- Physical space reclaimed: not measured; no reclamation claim is made.

The M2 report's logical bytes, path allocation, and summed allocated blocks are different
measurements. They do not establish unique APFS allocation or space that a removal would reclaim.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_job_recovery.py` — passed,
  13 tests. Covers active and terminal logs, concurrent append/read, and restart in a disposable
  root.
- `mise exec -- uv run --project backend python scripts/verify_0115_recovery.py --data-root /Users/niklas.sparfeld/Developer/doko_detector/data --runtime-root /Users/niklas.sparfeld/Developer/doko_detector/.runtime --output /tmp/0118-m4-current-verification.json` — passed. Snapshot and plan digests match M2; 2,086 resources, 34,414 manifest files, and 441 exact retained files passed.
- `mise exec -- uv run --project operations python docs/reports/0118-M3_0070_Synthetic_Training_View.artifacts/audit_0118_m3.py --repository /Users/niklas.sparfeld/Developer/doko_detector --restored-view /tmp/0118-m4-campaign-view --evidence /tmp/0118-m4-reference-dependency-audit.json` — passed. It checked all manifests, 447 M1 source/review files, 537 M2 scene receipts and images, 789 materialization files, 24 source videos, both model bundles, and the restored view. It reproduced the 24/24 immutable-manifest/content, 7/24 state, and 0/24 draft results.
- `git diff --check` and changed Markdown-link validation — passed after documentation updates.

No authoritative data changed. Checks establish preservation and current evidence only; they do
not establish full historical review recovery, off-volume recovery, exact regeneration, or physical
space recovery.
