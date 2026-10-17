# Epic 0095: Partial identity probability observations

- **Status:** Closed
- **Depends on:** 0050 M4 diagnostic complete
- **Outcome:** Allow the observation contract to retain a ranked subset of class probabilities, then measure downstream assembly on the retained 0050 inputs.
- **Closure reason:** Complete

## Goal

The M6 identity output has 25 classes: 24 card identities and `FACE_DOWN`. For an identity result,
it emits the 24 card probabilities and omits the `FACE_DOWN` probability. A valid subset can sum to
less than one. The observation contract must allow this and must still reject candidate sums above
one.

This epic only fixes the contract and measures observation assembly. It does not change model
outputs, normalize scores, make a model-quality claim, or reconstruct gameplay state.

## Milestones

- **M0:** Complete — allow candidate probability sums below one; preserve the upper bound and add
  contract regression coverage.
- **M1:** Complete — all three assemblies completed; see the
  [M1 result](../../reports/0095-M1_Partial_Identity_Observation_Result.md).

## M1 execution contract

- Use only the three recordings and exact input revision IDs listed in
  [0050 M4 result](../../reports/0050-M4_Diagnostic_Result.md).
- Reuse all event, visible-card, and identity revisions. Run no event, detector, scene, identity, or
  reconstruction processor.
- Run at most one observation assembly per recording, three total. Do not retry after a terminal
  failure. Stop if any input digest or source check differs from the frozen record.
- Use local services only. Make zero cloud requests. Do not access sealed data or collect labels.
- Record assembly outcomes, observation counts, zero-card frames, candidate score ranges and sums,
  request/input/output digests, run IDs, source revision, elapsed time, and sampled memory.
- Keep the three 0050 M4 observation rejections as rejected API requests. They created no processor
  runs; this epic creates the first observation processor runs for those exact inputs.
- Do not claim identity quality, choose a model, or infer gameplay state from this diagnostic.

## Closure

All three observation assemblies completed within the execution budget. They produced 147
observations, including all 19 zero-card observations, while preserving subunit candidate
probability sums. The report records a gap: process RSS was not sampled during the batch. No
upstream stage ran again and no quality claim was made.
