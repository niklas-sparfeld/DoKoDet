# 0099 M0 baseline and experiment freeze

Date: 2026-10-17

## Outcome

M0 is complete. The freeze uses retained 0096 reports and receipts. It does not reopen media or
read protected test or system-holdout sources. Both candidate subsets come from 0096 measurements
already examined. Confirmation is not a new holdout and does not support a generalization claim.

The baseline is application commit `8bdc68f4243835d2b0d9b02f812e87585d07fc01` with RF-DETR bundle
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`. The manifest pins eight 0096 input artifacts, source file
digests, the 0096 M1/M2 receipts, and the current 0096 M3 measurements. See
[`0099-M0_Experiment_Manifest.json`](0099-M0_Experiment_Manifest.json).

The unchanged M3 comparison covers 870 scoreable frames. Outside
the 0092 M4 refit-training sources, it covers 323
frames with precision 0.897 and recall
0.925. The separate in-sample scope covers
547 frames. Per-recording counts and
lineage are frozen in the manifest.

## Candidate subsets and gates

A stable SHA-256 sort of the eight outside-training source groups assigns four groups to development
and four to confirmation. The exact assignments and maintained-reference provenance are in the
manifest. Keep all eight groups in the final unchanged regression report.

Allow at most two independent software candidates. Each candidate gets one frozen-corpus replay and
replays of the four calibration failures. Use one active processor, no more than 12 active hours,
32 GiB process RSS, and zero cloud requests. Instrument wall time and RSS. Do not run fresh
segmentation without a separate plan amendment.

A candidate must improve a named measured failure, preserve or improve outside-training precision
and recall, introduce no calibration failure on a previously passing recording, and pass fixtures for
each changed path. Report every per-recording regression. Keep unsupported pile, pose, stacking-order,
and zero-card measures unsupported.

The four calibration failure codes stay frozen: `inconsistent_card_geometry`, `inconsistent_card_geometry`, `unstable_table_transform`, `insufficient_validation_population`.
M2 runtime was 7508.539 seconds, peak RSS was
2190163968 bytes, and the recorded cloud request count was zero. The separate M1
terminal dependency failure remains in the manifest and will not be retried here.

0096 outputs, generated selections, human drafts, and the 165-frame review queue remain unchanged.
