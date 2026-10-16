# 0089 M0 fresh failure replay

## Decision

No algorithm failure family is selected. Fresh 0087 detector outputs produced zero
reviewed-card matches at polygon IoU 0.5 across 494 proposals and 331 reviewed cards. The
largest proposal IoU was 0.254798. These inputs do not let us isolate a pose, order, occlusion,
or crop defect from detector output quality. No 0089 algorithm change is justified.

The current calibration rejected IMG_0095 because spatial coverage and the held-out boundary
gates failed. IMG_0657 and IMG_0662 published calibration, but neither recording had a proposal
match to reviewed geometry. Their pose residuals are diagnostic only; they do not validate pose
quality against human review. Keep the calibration gates unchanged.

## Replay scope

The replay used 130 exact-event frames from IMG_0095, IMG_0657, and IMG_0662: 42 confidence
calibration frames and 88 model-selection frames. It did not use the sealed final test. The
selected human reference revisions and exact model bundle digests are in the accompanying JSON.
Detector proposals were freshly cropped with `predicted_visible_region` and classified by the
0088 M6 primary and M3 control. All identity outputs remain proposals for human review. The 0.90
threshold is diagnostic routing only.

The M6 and M3 top-one labels disagreed on 29 of 494 crops. Each model routed 276 crops below the
0.90 review threshold. Neither result establishes identity accuracy because these automatic crops
do not have associated reviewed cards.

## Reproduction

Run the replay with the frozen runtime bundles and the selected reviewed references:

```sh
PYTHONPATH=operations/src:table_evidence_analyzer/src mise exec -- \
  uv run --project table_evidence_analyzer --group inference \
  --with opencv-python==4.11.0.86 python operations/scripts/run_0089_m0_replay.py \
  --artifact-root <checkout-with-frozen-runtime-bundles>
PYTHONPATH=table_evidence_analyzer/src mise exec -- \
  uv run --project table_evidence_analyzer python \
  operations/scripts/summarize_0089_m0_replay.py .runtime/0089-m0-replay/report.json
```

The raw replay retains source frames, generated crops, calibration, fit diagnostics, and
classifier outputs under ignored `.runtime/0089-m0-replay`. The checked-in
[machine-readable summary](0089-M0_Fresh_Failure_Replay.json) records the raw report digest,
reference revisions, per-frame associations, calibration gates, pose residuals, and identity
diagnostics.

## Handoff

Close 0089 without an algorithm change. Start future geometry or crop work only after fresh
detector outputs overlap reviewed cards enough to assess those boundaries. This replay publishes
the no-fix algorithm handoff required by 0090; it does not claim that the 0089 edge cases pass.
