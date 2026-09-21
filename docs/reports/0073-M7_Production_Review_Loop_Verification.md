# Epic 0073 M7 production review-loop verification

Date: 2026-09-21

## Result

The local proposal and review path is verified. A retained local RF-DETR cascade result reached
the proposal service without fixture injection or hand-edited JSON. The service published one
calibration revision and one immutable proposal revision in a temporary operations root. The
detector revision was not changed.

## Retained real cascade run

Input:

- Recording: `game-2026-09-18-01-001`
- Generated revision: `visible-cards-visible_cards-run-5bd52a7b-3ba-attempt-1`
- Provider: `local-rfdetr-cascade-0070`
- Input digest: `0dfeed0e1a49b056ce994874b90f045032cfaa4c0a681ab65e5caf66e35a7a53`
- Requested frames: 57
- Detector outcomes: 55 detected, 319 raw candidates

Service result:

- Runtime: 89,884.658 ms on the local MacBook run
- Run state: `partial`, with progress `57 / 57`
- Calibration revision: `calibration-2122a8f9936e2e9a7d63e7e5`
- Calibration digest: `1617927fe50e4292a82d513453ae08dfd08bb38fec0fc1cc4056616729c06681`
- Proposal revision: `card-scene-proposals-m7-real-cascade-proposal-attempt-1`
- Proposal digest: `4062ff7232a99dad66e03b7efc3ed12564fe18416356e8e9e7420cf29e6390f0`
- Supported frames: 55
- Unsupported frames: 2
- Unsupported reason: `no model polygon produced an initial fixed-size card pose`

The proposal manifest retains the detector revision ID and digest, source-frame digests, the
calibration revision and digest, the initializer recipe, fit diagnostics, and the explicit
unsupported results. The old detector revision and all prior revisions remain immutable.

A changed initializer recipe produces a different proposal digest while retaining the same
detector revision and detector digest. The immutable proposal contract therefore supports replay
and comparison of changed processor recipes without replacing the original proposal.

## Calibration and failure evidence

The real result produced a published calibration. All calibration gates passed:

- candidate count
- fit quality
- held-out alignment and population
- orientation diversity
- spatial coverage
- table-position diversity
- temporal diversity

Candidate accounting was `319` raw, `132` valid geometry, `81` above confidence, `71`
deduplicated, and `71` accepted. The retained rejection reasons were `187` quadrilateral-fit,
`51` frame-boundary, and `10` overlapping-prediction rejections. These reasons remain in the
calibration diagnostics and explain why a candidate did not become an anchor.

Explicit calibration-failure evidence remains covered by the local processor tests for
`inconsistent_card_geometry`, `insufficient_diversity`, changed frame dimensions, and changed
source transforms. Each failure includes a stable code and recovery action; no failure is converted
to a plausible calibration.

The small stable-camera regression path also completed with 12/12 supported frames. The review
loop fixture covers distant cards, two- and three-card overlap, wrong count, wrong order, and an
explicit unsupported frame. It records 2 moves, 2 rotations, 2 reorder actions, 1 card addition,
1 removal, and 1 unusable-frame decision. The completed visible-card reference contains derived
region receipts, and the materialized dataset contains 11 reviewed targets with explicit input
lineage.

Calibration refinement coverage includes candidate, accepted, adjusted, pinned, and excluded
anchor states. A conflicting pinned pair blocks preview with an actionable failure. The preview
fixture reports one changed frame and one most-affected frame. Apply, discard, reviewed-pose
reflow, affected confirmation, duplicate retry, and revision-conflict paths are covered by the
M6 focused backend and operations tests.

## Operator guidance

The editor now has a concise, accessible “How to review and refine” section. It explains:

- Source versus Rectified table views;
- Review cards versus recording-wide Refine mapping;
- body, rotation, corner, keyboard, constraint, and Escape behavior;
- complete-card anchor eligibility and clipped or rejected candidates;
- preview gates and affected-frame links; and
- Apply, Discard, failed-gate recovery, and explicit “Apply and mark affected” use.

The focused browser test checks that the guidance is rendered with the editor.

## Verification

- Operations calibration, refinement, and proposal tests: passed (`20` tests)
- Backend proposal and pose review-loop tests: passed (`3` tests)
- Focused browser editor tests: passed (`5` tests)
- Changed-file Ruff, formatting, and `git diff --check`: passed
- Full web check: passed (`21` test files, `191` tests)
