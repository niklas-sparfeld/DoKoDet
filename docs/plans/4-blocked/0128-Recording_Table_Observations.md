# Recording table observations

- **Status:** Blocked
- **Depends on:** [0127](0127-Recording_Classifications.md) closure and stable event/detection/scene/classification references.
- **Outcome:** Assemble, select, inspect, and reopen alternative table observation streams from the recording folder and use one for reconstruction.
- **Origin:** [Recording data storage](../../RecordingDataStorage.md).

## Problem and success

Observation assembly currently publishes generic node revisions and reconstructs workspace
history. Store concrete ordered observation streams with exact input references. Preserve uncertain
cards, piles, candidate identities, time coverage, and supported temporal associations. Use existing
assembly and reconstruction algorithms. A stream is evidence, not confirmed gameplay.

Use the recording-owned observation layout and root selection protocol. Adapt existing
`TableObservation` content explicitly; do not force the target to keep pipeline/node/run envelope
fields. Retain the existing reconstruction input shape through a small concrete input conversion
where needed. That does not require changing reconstruction storage or its search model.

Non-goals: reconstruction accuracy, game/round model redesign, new tracking, training, jobs/scheduler
replacement, all-history workspace optimization, and generic storage/framework cleanup outside the
converted recording workflow.

## Finite source owners

Backend: `observation_pipeline_service.py`, `round_analysis_service.py` selected-observation input
and recording-detail paths, `pipeline_workspace_service.py`, `pipeline_workspace_api.py`,
`recordings_api.py`, converted-resource branches of selection/lineage/composition, and aggregate
recording-state runtime wiring after its actual-consumer audit. Content:
`table_evidence_analyzer/table_observation.py` and `pipeline_data.py` observation portions.
Web: observation API client/inspection and current-recording workspace data loader. Historical
review links remain supported through tested explicit resource lookups; no global graph required.

## Closure check

Real API/browser: assemble from exact event/detection/classification resources and optional scene
evidence; inspect cards/piles; retain two streams; select one; invoke existing reconstruction with
a deterministic local substitute where needed; reopen stream and result after restart. Changing an
upstream selection must leave the retained stream's exact inputs unchanged. Include partial visual
identity evidence, zero-card observations, and unavailable evidence as distinct cases.

Rehearse named retained stream conversion and verify content, order, coverage, exact dependencies,
review decisions, unfinished work, and selection. Disable old observation-node reads. Current
workspace reads open exact selected resources; historical alternatives load only when requested.
Preserve independent review switching and conflict handling. Run affected observation/analysis/
workspace/API/browser/static tests and the bounded list regression.

Remove shared node/snapshot/history runtime exposure only when the finite consumer inventory proves
it unused after these resource cutovers. Do not bulk-delete retained history, old job records,
campaign inputs, or recovery data. Any remaining active non-recording consumer keeps its exact
access and gets a named follow-up; it does not restart a global migration inside this epic. Do not
claim that the entire repository is free of old formats unless the inventory proves it.

## Milestones

| Milestone | Observable result and commit boundary | State |
| --- | --- | --- |
| M0 | Concrete observation-stream storage; real API save/open of ordered evidence and exact inputs | Not started |
| M1 | Existing assembler and real browser inspect/select/restart workflow use observation resources | Not started |
| M2 | Existing reconstruction consumes the selected stream; current workspace opens exact resources without history discovery | Not started |
| M3 | Retained-data rehearsal, default observation cutover, verified unused-path removal, and qualification | Not started |

### Assignment preparation

After 0127 closes, freeze M0's stream metadata/item layout, observation schemas, exact API/client
paths, and source reference conversions. M0 adds only observation-stream persistence. Prove
save/open through a real API and restart, with bounded exact input resolution; parser-only tests
do not suffice. Commit: store/API, focused tests, evidence, and plan/board updates. Specify M1
before assignment, and the finite M2 current-workspace/reconstruction adapters after the first
browser proof. M2 must not become the old 0121 performance program. Qualify only the selected
recording workflow in M3; preserve 0123's measured list outcome.

## Execution handoff

Planning only. Baseline: 4 milestones; 4 remain. First API: M0; browser: M1; qualification: M3.
No run authorized. Two correction turns per family maximum under the execution scope review.
Stop before adding another infrastructure prerequisite, a scheduler conversion, or an unbounded
runtime-removal assignment. The older 0117/0120 failed approaches and counts remain historical.
