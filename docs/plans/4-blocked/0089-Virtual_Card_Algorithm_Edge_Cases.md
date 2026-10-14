# Virtual-card algorithm edge cases

## Plan status

- **Summary:** Reproduce current failures with fixed model bundles and correct only measured
  calibration, pose, stacking-order, or crop integration defects.
- **Status:** Blocked
- **Depends on:** 0086 reviewed development evidence; 0087 and 0088 reports with exact bundle decisions
- **Blocker:** Current-model failures and the regression inputs have not been frozen.
- **Outcome:** A small real regression set, bounded algorithm fixes, and a reproducible comparison.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — replay failures and freeze the regression set and fix scope.
- **M1:** Not started — correct one reproduced pose or occlusion failure family.
- **M2:** Not started — correct one further integration failure family only if M0 selected it.
- **M3:** Not started — verify combined behavior and publish remaining limits.

## 1. Scope and selection

Use fresh runs with the exact bundle and crop-policy decisions from
[0087](../5-closed/0087-Reviewed_Virtual_Card_RF_DETR_Campaign.md) and
[0088](0088-Reviewed_Virtual_Card_DINO_Campaign.md). A campaign can select a retained baseline;
it need not produce a better model to unblock this epic.

0088 must report whether its useful-model quality gates passed. A retained or unqualified diagnostic
bundle can support failure reproduction here, but does not establish successful model delivery.
Annotation/crop preparation belongs to 0093; training/runtime recipes belong to 0094. Do not defer
those prerequisites to this epic or introduce a dependency from 0088 back to 0089.

The [0091 capability handoff](../../reports/0091-Pile_Region_Capability_Handoff.md) records the
current boundary: piles are preserved in engine input but do not affect search or gameplay claims.

The current fitter already tries quarter-turn candidates and refits with occluder masks. Stored
v1 and v3 overlays do not prove a current 90-degree defect. Start from fresh reproductions of
partial visibility, deep overlap, frame edges, human-hand occlusion, and orientation ambiguity.
Distinguish detector errors, calibration errors, pose ambiguity, order errors, and crop errors.

M0 selects at most two small failure families. Specify each fix and numerical acceptance before
implementation. Create a separate epic for a larger rewrite or new analyzer capability. Detector
and identity training are out of scope. Preserve reviewed geometry as the authority. A proposed
pose remains a proposal even when a classifier prefers its crop.

Annotation blockers discovered during 0086 can be fixed there within its bounded scope. Record
those fixes in this regression inventory; do not wait for this epic to make review possible.

## 2. Delivery milestones

### M0 — Freeze fresh failure evidence

Replay selected development examples under exact current recipes. Retain source frames, reference
revisions, masks, pose alternatives, calibration, stacking order, crop outputs, and runtime. Select
two failure families at most and unaffected comparison cases. Freeze residual, orientation, mask,
identity, and runtime gates as relevant. Declare unsupported or physically ambiguous cases.

Acceptance: every selected defect reproduces; no sealed or system-holdout input is used; the
report names the responsible boundary and exact implementation scope. If no defect warrants a fix,
close with the replay evidence rather than inventing an algorithm change.

### M1 — Correct the first selected failure family

Write a regression test, implement the smallest change at the responsible boundary, and replay
the frozen cases. Keep physical dimensions, recipe versions, projection, and derived masks aligned.

Acceptance: the selected failure passes the frozen gate; unaffected cases and runtime limits pass;
no reviewed correction is overwritten; diagnostic candidates do not become geometry authority.

### M2 — Correct the second selected failure family

Implement only the separate M0-selected family with its own regression test and comparison.
If M0 selected only one family, record this milestone as not required with a reason.

Acceptance: exact source and geometry provenance survive the change; ambiguity produces an
inspectable result instead of an unsupported forced decision; no model or dataset tuning occurs.

### M3 — Publish the combined comparison

Replay all frozen cases with both fixes and representative unaffected recordings. Publish recipe
versions, quality and runtime deltas, unresolved limits, and the exact handoff to
[0090](0090-Local_End_to_End_Recording_Pipeline.md).

Acceptance: the final behavior and metrics reproduce locally; tests cover the combined paths;
remaining failures have item-level evidence and a bounded follow-up decision.

## 3. Verification

Run focused geometry, calibration, pose, stacking-order, crop, and provenance tests for changed
paths, plus relevant static checks. Keep real recorded regressions and deterministic fixtures.
Do not require new capture hardware or cloud services.
