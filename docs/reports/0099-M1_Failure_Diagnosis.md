# 0099 M1 failure diagnosis

Date: 2026-10-17

## Outcome

M1 is complete. The analysis uses the frozen 0096 exact-frame pairs, detector revisions, maintained
references, and calibration receipts. It does not open media or rerun the detector. It replays the
four calibration calls from their saved detector revisions and frozen recipes. Each replay returns
the recorded run digest and failure code.

The 323 scoreable outside-refit-training frames reproduce 786 matches, 90 unmatched predictions,
64 unmatched reviewed cards, two duplicate proposals, precision `0.897260`, and recall `0.924706`.
These are previously examined 0096 measurements. The source-group confirmation subset is not a new
holdout and does not support a generalization claim.

See the [machine-readable diagnosis](0099-M1_Failure_Diagnosis.json). Recreate it from a checkout
with the retained pipeline data by running:

```sh
mise exec -- uv run --project operations python operations/scripts/diagnose_0099_m1.py
```

## Ranked failure families

| Rank | Family | Count | Evidence |
| --- | --- | ---: | --- |
| 1 | Unmatched predicted masks | 90 | 76 are in `IMG_0644`; all are interior. Two overlap a reviewed card at the duplicate threshold. |
| 2 | Unmatched reviewed cards | 64 | 43 are in `IMG_0645`; 8 touch the frame edge and 56 are interior. |
| 3 | Calibration safety rejections | 4 recordings | Two geometry-fit failures, one population failure, and one transform-serialization failure. 194 scene frames were left unprocessed. |
| 4 | Backend lifecycle failure | 1 run | `backend_restarted` at `0/49` frames. No detector output or postprocessing ran. |

The median predicted-mask area for unmatched predictions is 2,219 normalized-raster pixels. The
matched-reference median is 4,997 pixels. Missed reference cards have a median area of 5,062
pixels, close to the matched-card median. This does not point to one simple small-card rule.

The unmatched-prediction confidence scores have median `0.668457`, with range `0.501465–0.953613`.
Matched predictions have median `0.956055`, with range `0.573730–0.976562`. The ranges overlap.
These measurements do not justify a confidence-only rule. The two duplicate proposals account for
only two of the 90 extras. No other common postprocessing defect is reproduced by these aggregates
and geometric tags.

All 323 scored frames report pile detection as supported, but the maintained references contain no
reviewed pile regions. Pile relations, pose, stacking order, and zero-card quality remain
unsupported. The exact-frame comparison also has 142 frames with ignore regions, one unresolved
reference frame, and no explicit reviewed-empty frame. These are comparison limits, not detector
failures.

## Calibration replay

| Recording | Frozen failure | Replay | Fit evidence | Frames left unprocessed |
| --- | --- | --- | --- | ---: |
| `IMG_0090` | `inconsistent_card_geometry` | Same run digest and code | 6 fit cards; median boundary error 4.582 px; no held-out cards; fit-quality and held-out-population checks fail. | 50 |
| `IMG_0635` | `inconsistent_card_geometry` | Same run digest and code | 13 fit cards; median boundary error 5.267 px; 6 held-out cards, none pass; fit-quality check fails. | 51 |
| `IMG_0641` | `unstable_table_transform` | Same run digest and code | 44 fit cards; fit-quality check passes; 16 held-out cards, 6 pass. Final calibration construction rejects the serialized transforms as non-reciprocal. | 53 |
| `game-2026-08-20-01-005` | `insufficient_validation_population` | Same run digest and code | 6 fit cards and 1 held-out card; the held-out population and spatial coverage checks fail. | 40 |

The `IMG_0641` result has a minimal fixture in
[`0099_img_0641_reciprocal_transform.json`](../../operations/tests/fixtures/0099_img_0641_reciprocal_transform.json)
and a focused characterization test. The saved matrices are reciprocal before serialization. The
six-decimal matrices have a maximum reciprocal error of `0.0011695264`, above the `0.001` check,
which reproduces the recorded rejection. This fixture identifies a precision handoff defect; it
does not justify bypassing the held-out boundary check or publishing a calibration by itself.

## Runtime and decision boundary

The separate M1 run for `game-2026-08-20-01-001` records `backend_restarted`, `0/49` completed
frames, and no output revisions. It is a backend lifecycle failure. No local detector fixture can
exercise detector or postprocessing behavior from a run that produced no frame output. The run was
not retried.

The exact reviewed-card references support a bounded assessment of segmentation changes in M2.
They do not establish a winning policy. The calibration fixture supports a narrowly scoped
precision investigation, subject to the frozen calibration gates. Do not lower population, fit,
held-out, or transform safety checks. Do not use manual geometry to publish any failed recording.

## Inputs and reproduction

The JSON report pins all eight M0 input artifact digests. It also records each calibration run-state
digest, detector revision digest, replay digest, and replay failure code. The replay uses the saved
visible-card revision and the exact recipe from its M2 run receipt. It performs calibration only:
no media access, detector inference, proposal initialization, or publication.
