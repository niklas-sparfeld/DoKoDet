# Epic 0115 M3: recovery-tree retirement

## Frozen scope before apply

M3 will retire only the 51 duplicate recording-video files under
`data/operations-recovery/0108-m10-20261105/recording-videos`. The frozen candidate set is
[`recording-video-candidates.json`](0115-M3_Recovery_Tree_Retirement.artifacts/recording-video-candidates.json)
(SHA-256 `8de6e1b4ee5eb867027ccffa5cdd28bc13cab30a039ada500ec8459b2b917ae9`). The
[preflight audit](0115-M3_Recovery_Tree_Retirement.artifacts/preflight-audit.json) freezes the
candidate identities and retained-tree digest before apply. Each file must match the declared byte length
and SHA-256 of its protected `data/intake` original. M10 migration manifests must reference only
these intake paths for the `recording_videos` source family. The frozen source config has 55
logical source-location keys that resolve to these 51 physical files; four `.m4v` keys are aliases
to retained `.mov` originals, not additional files. The accepted-loss migration package,
the earlier stage, migration source, operations snapshot, evidence packages, import workspaces,
current stores, and every protected intake file remain in place.

This is one bounded source family. M3 does not retire the complete 0108 root. The known missing
histories and processor-run records remain unresolved, but no candidate path represents those
records. Any additional reference to a recovery-video copy, a changed digest, an active writer, or a
failed recovery check cancels apply. M3 preserves the protected source bytes in `data/intake` and
records the retired physical recovery paths; it does not rewrite closed Epic 0108 reports.

## Frozen checks and commit boundary

Before apply: inspect the full 0108 migration manifests and source-root config; verify all 51
candidate and intake hashes; confirm no writer has an open recovery-root file; hash every retained
path outside the candidate subtree; run the M1 recovery verifier; and complete the isolated live
recovery, edit, review, and restart workflow. The M1 real-backend workflow completed before the
M3 apply; M3 preflight also read the frozen review revisions and decisions across two backend
starts. Create a dry-run with `cleanup_0115.py` and require `apply_permitted: true` for the frozen
set. Apply once through the M2 tool.

After apply: verify its complete 51-file receipt; confirm all protected intake hashes and the full
retained-tree manifest are unchanged; rerun the M1 recovery verifier and isolated live workflow;
measure allocated directory sizes and actual volume free space before and after. Record any unknown
APFS allocation separately from observed volume changes.

The commit contains the bounded M2 hard-link-reference correction and fixture tests, M3 report and
audit artifacts, this epic and board state update, and the current execution handoff. It changes no
runtime contract.

## Apply result and retained evidence

M3 retired 51 verified duplicate video files under
`data/operations-recovery/0108-m10-20261105/recording-videos/data/intake/recordings`,
with 14,516,434,567 logical bytes. The exact removed paths, original sizes, SHA-256 values, and
per-file outcomes are in the [M2 receipt](0115-M3_Recovery_Tree_Retirement.artifacts/retirement-receipt.json).
The physical directory remains documented at its former location. M3 left the accepted-loss
stage, earlier stage, migration source, operations snapshot, evidence packages, import workspaces,
current stores, intake originals, and all unknown reference histories untouched.

The complete reference audit resolved 1,429 source-video references in each of the M10 and
accepted-loss migration manifests to the same 51 protected intake paths. Their 51 recovery-file
entries match the frozen hashes. The source-root config has 55 location keys; four `.m4v` keys
are aliases to retained `.mov` files. The audit retains 167 earlier-stage and 156 accepted-stage
unrelated migration uncertainties. The [preflight audit](0115-M3_Recovery_Tree_Retirement.artifacts/preflight-audit.json)
and [candidate manifest](0115-M3_Recovery_Tree_Retirement.artifacts/recording-video-candidates.json)
record the exact reference identities. The [reference audit](0115-M3_Recovery_Tree_Retirement.artifacts/reference-audit.json)
lists every unique protected path and its reference count. A scan of runtime code found no reader or
writer for the candidate family.

Before and after apply, the retained-tree audit used the same path ordering and canonical JSON
serialization. After excluding only the 51 authorized paths and M2 plan, receipt, and lock files
created by the apply, its 142,695 files, 11,091,939,040 logical bytes, and SHA-256
`67b0f903076797ca5f81d8937e44c90611940e2d94321543bda95fdbe0e2502e` match exactly. All 51
protected intake originals still match their frozen size and SHA-256. The M1 verifier still reports
the accepted-loss package as activation-ready with 2,086 resources and 34,414 files; see the
[postflight verifier](0115-M3_Recovery_Tree_Retirement.artifacts/postflight-recovery.json).

The [family recovery record](0115-M3_Recovery_Tree_Retirement.artifacts/family-recovery.json)
captures both affected-family recovery checks. The 51-file family restored from the frozen copies before apply and from intake originals
after apply. Both reconstructions passed every byte-length and SHA-256 check. The actual backend
served the two selected M1 independent-review revisions and 50 persisted review records across two
server starts before apply. The M1 report records the pre-apply edit/save/readback/restart, from
base revision `2a8bf3d6-6e65-59d3-a0d0-e7048e566ce9` to `8d67df70-6f7d-591f-8093-21ecdf5b31fb`.
After apply, the same exact M1 base revisions and all 50 review records were copied into isolated
storage. The real backend edited and saved a scene revision, read back the new and original
revisions, and retained all review records and downstream selection digests across restart. The
new scene revision is `381d56db-90c1-51e1-a990-8215f1321cad`; the pose center changed from
`[-0.014023, 0.091126]` to `[-0.013023, 0.091126]`. See
the [preflight read evidence](0115-M3_Recovery_Tree_Retirement.artifacts/live-review-recovery.json),
[postflight edit evidence](0115-M3_Recovery_Tree_Retirement.artifacts/live-review-edit-restart-post.json),
and [M1 edit evidence](0115-M1_Recovery_and_Cleanup_Plan.artifacts/independent-review-recovery.json).
A full copied-store import attempt ran for about 16 minutes and stayed on deep JSON serialization;
it was stopped in temporary storage. It changed no source data. This limit is recorded in the
[postflight audit](0115-M3_Recovery_Tree_Retirement.artifacts/postflight-audit.json).

The 0108 root allocated size changed from 25,308,296 KiB to 11,132,028 KiB; the video directory
changed from 14,176,352 KiB to 84 KiB. The filesystem reported 76,379,940 KiB available immediately
before apply and 76,378,452 KiB immediately after, an observed change of -1,488 KiB. After M3's
temporary drill trees were removed, a later filesystem sample reported 76,365,200 KiB available,
an observed change of -14,740 KiB from the pre-apply sample. These are measurements, not a savings
estimate. APFS clones and other filesystem activity limit attribution.

## M3 checks

- M2 cleanup tests: 12 passed, including hard-linked protected references allowed for read-only
  identity/digest validation and single-link candidate rejection.
- Ruff check and Ruff format check passed for the M2 helper and tests.
- M2 apply receipt reports complete for all 51 exact candidate files.
- Postflight recovery verifier passed; accepted-loss snapshot digest and all retained M1 counts match.
- Family recovery checks passed before and after apply; protected originals match all 51 frozen hashes.
- Pre-apply M1 edit/save/readback/restart passed; M3 preflight review reads and postflight edit,
  save, readback, review reads, and restart passed for the representative revisions.
- Retained-tree file count, logical bytes, and exact canonical manifest digest match the preflight.
- Writer/open-file check passed immediately before apply; no backend or cleanup process was active.

## M2 tool correction found during preflight

The first dry-run stopped before writing a plan. Four protected intake files have multiple hard
links, while every recovery candidate has one link. The M2 helper used its candidate-only
single-link rule for protected references too. M3 changed the helper so references may have more
than one link, while it still checks their regular-file type, stable identity, size, and digest at
planning and apply. Candidates still require one link. Two fixture tests cover both cases. No
retained data changed during the rejected dry-run.
