# Epic 0114 M12: profile and cycle one

Date: 2026-11-08
Status: Complete

## Profile and ranked candidates

The profile used the frozen M11 hard fixture on Mac14,10 with Python 3.13.18. It made one
validated request to each hard pipeline route and retained bounded operation totals in the
[profile data](0114-M12_Candidate_Profile_and_Cycle_One.json). The cold and warm requests used
disposable storage. No OS file cache was flushed.

| Rank | Candidate | Baseline and affected routes | Expected gain | Risk | Verification | Stop condition |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Reuse node history metadata while building a lineage snapshot instead of traversing the full history for each parent revision. | `pipeline/lineage_hard`: 29.422 s cold median, 29.569 s warm p95; `GET /api/recordings/{recording_id}/pipeline/lineage`. Profile: 10 history traversals and 28.723 s attributed to those traversals. | Cycle-one target frozen before implementation: at least 20% faster; cold median <=23.538 s and warm p95 <=23.655 s. | Incorrect `revised`, `copied`, or `restored` edges if a metadata lookup misses a parent. | `test_pipeline_lineage.py`; the same hard cold/warm runner; lineage reserved and workspace reserved cases; full M11 qualifier. | Revert if the target or any correctness/budget gate fails. Do not alter the baseline to pass. |
| 2 | Attribute and reduce repeated validated revision parsing in full workspace assembly. | `pipeline/workspace_full_hard`: 20.788 s cold median, 21.059 s warm p95; workspace GET and the startup workspace-first-use probe (4.451 s median). Profile: 5 history traversals and 14.325 s in them. | Not frozen. Profile shows a cost, but a safe reduction path is not established yet. | Skipping validation or changing full-history content would weaken the persisted-data contract. | Re-profile before selecting it for M13. | Stop if a change needs weaker validation or changes response semantics. |
| 3 | Reduce startup and recording-catalog first-use work. | Startup-to-useful response: 8.040 s median; recordings first use: 3.010 s median; workspace first use: 4.451 s median. | Not frozen; M11 has endpoint times and server logs, not phase-level operation attribution for catalog startup. | May shift work after readiness or change first-use behavior. | Profile process startup and catalog reads before selection. | Stop until a bounded operation-level target is available. |

Startup evidence shows process launch reaches `backend_started` in about 0.39 s; most measured
startup-to-useful time is in recording and workspace first-use requests. The selected cycle-one
change improves lineage snapshots and does not claim a startup gain. The startup/catalog candidate
remains ranked for M13 profiling, because no safe startup reduction is yet supported by an
operation-level profile.

## Frozen cycle-one target and reserved case

The selected change is one bounded in-memory history lookup within a single snapshot request.
It adds no persistent cache and has no cross-request invalidation path. The numeric target was
declared before implementation: at least 20% reduction against the M11 `lineage_hard` cold and
warm references, with the limits above. The unchanged hard `workspace_full_hard` case is reserved
for regression coverage. Startup profiles remain a required check because the plan requires the
same startup scenarios; the full startup probe does not call the lineage route.

## Cycle-one results

The selected change builds one history per selected node and uses that history to resolve parent
metadata. It adds no cache and retains the same revision, copy, and restore edge output. The
[focused hard-route samples](0114-M12_Cycle_One_Samples.json) contain 3 cold and 9 warm requests
for each route, across three disposable storage batches.

| Case | M11 reference | M12 result | Frozen target or gate | Result |
| --- | ---: | ---: | ---: | --- |
| `pipeline/lineage_hard/cold` median | 29.422 s | 14.451 s | <=23.538 s; M11 ceiling 35.430 s | Pass; 50.9% faster |
| `pipeline/lineage_hard/warm` max across 9 samples (median 14.412 s) | 29.569 s p95 | 14.520 s | <=23.655 s; M11 ceiling 35.966 s | Pass; 50.9% faster than M11 p95 reference |
| Reserved `pipeline/workspace_full_hard/cold` median | 20.788 s | 20.387 s | M11 ceiling 25.161 s | Pass |
| Reserved `pipeline/workspace_full_hard/warm` max across 9 samples (median 20.273 s) | 21.059 s p95 | 20.469 s | M11 ceiling 25.671 s | Pass |

The pipeline runner checked response status, schema, exact fixture node and revision identities,
and response digests. All 24 samples passed. The hard startup runner then passed 10 fresh process
trials. The median startup-to-useful response was 8.077 s; recordings first use was 3.015 s and
workspace first use was 4.464 s. These remain within their M11 ceilings. No startup improvement is
claimed. See the [startup samples](0114-M12_Startup_Samples.json).

The real-process Playwright lineage revision-switch scenario passed in 10 fresh contexts on the
M10 generated fixture. It retained zero errors. See the [browser samples](0114-M12_Lineage_Browser_Samples.json).

The focused lineage tests passed (7 tests), and the lineage/workspace API tests passed (8 tests).
Ruff check and format checks passed. The hard fixture validator passed all 57 assets. The inventory
gate passed for 76 registered API operations, with the existing single documented UI URL gap. Its
scan logged pre-existing legacy run-state warnings from the checkout's normal `data/operations`
tree; it did not change that data. Local Markdown links in the updated plan, board, and report
passed. The M11 baseline was not changed.

## Updated ranking and cycle two

Cycle one met its frozen target, preserved the reserved workspace route, and passed the startup and
browser checks. Cycle two is selected for further profiling of full workspace revision-history
parsing (rank 2 above). M13 may implement a bounded change only after it identifies a path that
preserves full persisted-content validation and freezes a numeric target. The M11 startup results
show that workspace first use is a leading delay, but the current profile does not justify weaker
validation or a startup rewrite. If no safe operation-level candidate emerges, M13 should record
that stop reason and complete final qualification without a speculative change.
