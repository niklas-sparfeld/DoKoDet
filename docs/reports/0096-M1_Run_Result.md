# 0096 M1 segmentation run

Date: 2026-10-17

## Outcome

M1 is complete with one named terminal run failure. The batch used the pinned local 0092 M4
segmentation bundle. It made no cloud requests and ran no scene or identity processor.

The first 34 planned run IDs did not satisfy the M0 input freeze. The service used event `start_us`
instead of the frozen `end_us` anchor. One run failed after a backend restart with 0 of 49 frames
complete. The other 33 runs completed 1,707 frame outcomes. Only 1,407 matched M0. Keep those
outputs for audit and do not use them in M2.

The correction plan added 33 deterministic run IDs. Each request selected the frozen event revision
and stored `event_time_anchor: end_us`. All 33 runs completed. Their 1,707 outcomes match all 1,707
corresponding M0 frame identities. They contain 1,525 detected outcomes and 182 empty outcomes.
They contain 3,669 card candidates and 782 pile regions. These counts describe output volume; they
do not measure quality. The remaining 49 frozen frames belong to the terminal failed run and have
an explicit unprocessed reason.

The correction raised the M1 run-ID cap from 34 to 67 before corrective processing. The batch used
67 IDs: 34 original IDs and 33 corrective IDs. It used 1,102.678 active processing seconds of the
24-hour limit. The 110 RSS samples, taken at 10-second intervals, show a peak of 1,660,223,488
bytes, below the 32 GiB limit.

The live provider identity matched the frozen bundle digest
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`. All corrected run requests
selected the local RF-DETR provider and all output manifests retained the expected model ID. The
corrective manifest links each output revision and its content digest to the verified bundle
digest. No identity data was produced.

All 33 generated selection pointers now refer to the corrected output revisions. Completed
reference pointers remain unchanged. The original wrong-anchor outputs and failed run remain in the
pipeline store. The machine-readable results are in
[`0096-M1_Run_Result.json`](0096-M1_Run_Result.json); the pre-run correction budget and IDs are in
[`0096-M1_Input_Anchor_Correction.json`](0096-M1_Input_Anchor_Correction.json).

## Handoff

M2 can use the 33 corrected revisions listed in the JSON result. Treat
`game-2026-08-20-01-001` as a named M1 dependency failure. Do not retry its terminal failed run.
No M2 run has started.
