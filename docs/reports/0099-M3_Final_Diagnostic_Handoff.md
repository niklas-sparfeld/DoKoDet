# 0099 M3 final diagnostic handoff

Date: 2026-10-17

## Decision

M3 is complete. Retain the unchanged baseline. Candidate A and candidate B did not repair the
saved `IMG_0641` calibration failure, and neither improved a named measured failure. No runtime
change remains. Close epic 0099 on this no-fix decision.

The candidate replay left the outside-refit-training comparison unchanged:

| Scope | Scoreable frames | Matches | False positives | Misses | Duplicates | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen baseline | 323 | 786 | 90 | 64 | 2 | 0.897260 | 0.924706 |
| Candidate comparison | 323 | 786 | 90 | 64 | 2 | 0.897260 | 0.924706 |

All eight per-recording deltas are zero. Both candidates left the four calibration outcomes
unresolved. Candidate A used full-precision matrices with a strict `1e-9` reciprocal check.
Candidate B used full-precision matrices with the frozen `0.001` tolerance. Neither made the
`IMG_0641` reciprocal-transform validation pass. No calibration gate was lowered.

The M2 reports contain the detailed candidate replay and its digests. The temporary evidence
overlay used to read retained artifacts is not part of the repository, and the transient replay
invocation was not retained. The commands below verify the preserved evidence and focused fixture
coverage; they do not rerun the candidate comparison.

## Limits and outstanding review

These measurements use sources already examined during 0096. They are not holdout or generalization
evidence. The 90 unmatched predictions and 64 misses do not establish which differences require a
model change. Existing references do not support pile relations, pose, stacking order, or zero-card
quality. The 0096 M4 queue remains 165 frames across 33 reviewable recordings and awaits human
review. That queue is outside this epic's diagnostic decision and remains unchanged.

The terminal `backend_restarted` run was not retried. No detector inference, media access, selection
or draft write, cloud request, or active processor run was part of this handoff. The M2 candidate
replays took 47.5 seconds total; process RSS was not captured, so no peak-memory claim is made.

Questions for later review are whether the unmatched predictions and misses correspond to visible
cards, unreviewed card-like regions, or other objects, and whether later work should add reviewed
pile, pose, stacking-order, or explicit-empty references. Do not resolve these questions by treating
missing coverage as a negative label.

## Evidence and reproduction

The [machine report](0099-M3_Final_Diagnostic_Handoff.json) records the input and output digests,
source digests, candidate dispositions, queue digest, and commands. The earlier [M0 freeze](0099-M0_Baseline_and_Experiment_Freeze.md), [M1 diagnosis](0099-M1_Failure_Diagnosis.md), [M2 results](0099-M2_Bounded_Candidate_Results.md), and [M2 replay diagnostics](0099-M2_Replay_Diagnostics.json) retain the staged evidence.

Run these commands from the repository root to check the retained fixture and report inputs:

```sh
mise exec -- uv run --project operations pytest -q operations/tests/test_0099_m1_calibration_fixture.py operations/tests/test_card_plane_geometry.py operations/tests/test_card_plane_calibration.py operations/tests/test_card_plane_calibration_refinement.py
python3 -m json.tool docs/reports/0099-M3_Final_Diagnostic_Handoff.json >/dev/null
python3 -m json.tool docs/reports/0099-M2_Bounded_Candidate_Results.json >/dev/null
shasum -a 256 docs/reports/0099-M0_Experiment_Manifest.json docs/reports/0099-M1_Failure_Diagnosis.json docs/reports/0099-M2_Bounded_Candidate_Results.json docs/reports/0099-M2_Replay_Diagnostics.json docs/reports/0096-M3_Exact_Reference_Evaluation.json docs/reports/0096-M4_Human_Review_Queue.json
git diff --check
```

The candidate comparison is not reproducible from the committed source tree alone because its
temporary overlay and invocation were not retained. The hashed reports preserve its recorded
results. No claim of exact experiment rerun is made here.
