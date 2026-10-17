# 0099 M2 bounded candidate results

Date: 2026-10-17

## Outcome

M2 is complete. Two candidates tested the transform-precision handoff identified in M1. Neither
candidate fixed the saved `IMG_0641` calibration failure. The baseline remains unchanged. M3 must
record the final decision and handoff.

The comparison used the unchanged 0096 geometry matcher, ignore-region policy, and one-to-one
matching. It read saved detector outputs and references. It did not open media, run detector
inference, write selections or review drafts, or contact a cloud service. These sources were
previously examined during 0096. This result is not a holdout or a generalization claim.

See the [machine-readable result](0099-M2_Bounded_Candidate_Results.json) and the preserved
[frozen-corpus and calibration replay diagnostics](0099-M2_Replay_Diagnostics.json).

## Segmentation comparison

| Scope | Scoreable frames | Matches | False positives | Misses | Duplicates | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen baseline outside refit-training sources | 323 | 786 | 90 | 64 | 2 | 0.897260 | 0.924706 |
| Candidate replay | 323 | 786 | 90 | 64 | 2 | 0.897260 | 0.924706 |

All eight outside-training recordings retain their frozen per-recording counts. The machine report
lists each recording and zero deltas for matches, false positives, misses, and duplicates. The
candidates change calibration matrix handling only. They do not change segmentation outputs.

## Candidate results

| Candidate | Policy | Result |
| --- | --- | --- |
| A | Preserve full-precision matrices and apply a `1e-9` reciprocal check. | Rejected. `IMG_0641` still fails reciprocal-transform validation. |
| B | Preserve full-precision matrices and apply the frozen `0.001` reciprocal tolerance. | Rejected. `IMG_0641` still fails with the same error. |

All four saved calibration failure codes stayed unchanged in both replays. The two fit-quality
failures remain `inconsistent_card_geometry`. The population failure remains
`insufficient_validation_population`. `IMG_0641` remains `unstable_table_transform`. The candidate
run digest differs from the frozen M1 digest for `IMG_0641`; the diagnostics retain that digest and
the failure detail. No gate was lowered. No candidate is selected, and no runtime change remains in
the source tree.

Each candidate comparison command took about 24 seconds of wall time, for 47.5 seconds total.
Process RSS was not captured. The experiment made zero cloud requests and started no active
processor. The terminal `backend_restarted` failure was not retried.

## Limits and verification

Pile relations, pose, stacking order, and zero-card quality remain unsupported. The references have
no reviewed pile regions, pose or stacking labels, or explicit reviewed-empty frames.

The calibration and geometry suites passed during candidate work. After removing both rejected
candidate changes, the focused fixture and related suites passed again. `git diff --check` and local
Markdown link checks passed.

The frozen report and pipeline outputs were read through a temporary evidence overlay because the
clean checkout did not contain all retained 0096 revisions. The overlay referenced the exact
pre-existing frozen M3 report and saved pipeline artifacts in the main checkout. Their hashes
matched the M0 manifest. No files in that checkout were changed by M2.
