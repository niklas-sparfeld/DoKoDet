# 0096 M0 input freeze

Date: 2026-10-17

## Outcome

M0 is complete. The batch has 34 recordings with selected event revisions. No segmentation or
proposed-scene inference ran. The final read-only preflight returned ready for the exact 34-recording
list and identified the pinned 0092 M4 bundle.

The machine-readable freeze is in [`0096-M0_Preflight.json`](0096-M0_Preflight.json). It records all
52 catalog dispositions, source permissions, source groups, selected event revisions, current
selection pointers, maintained-reference and draft digests, deterministic run IDs, implementation
digests, model identity, and resource limits.

## Catalog dispositions

| Disposition | Count |
| --- | ---: |
| Execution eligible | 34 |
| Protected test sources | 4 |
| System-holdout recordings | 5 |
| Legacy-device policy | 5 |
| Non-flat surface | 1 |
| Missing selected event revision | 3 |
| **Catalog total** | **52** |

The protected test recordings are `IMG_0654`, `IMG_0659`, `IMG_0656`, and `IMG_0660`. The system
holdout recordings are `IMG_0669`, `IMG_0670`, `IMG_0671`, `IMG_0673`, and `IMG_0674`. The related
protected source-group check found no additional catalog entries. The five legacy-device recordings
and `IMG_0092` remain excluded by the existing policies.

All 34 recordings can be used for segmentation and scene proposal generation. Thirty-one have
validation, evaluation, or test permission. Thirty-one have training permission. The three
training-only recordings can be processed for training preparation, but not scored. Three other
catalog entries have no selected event revision and remain outside this batch.

## Exact event frames and comparison coverage

[`0096-M0_Event_Frame_Inputs.json`](0096-M0_Event_Frame_Inputs.json) freezes all 1,756 event frames
for the 34 eligible recordings. It uses the selected event's `end_us`, `exact-event/v1`, JPEG
encoding, `ffmpeg/8.1.2`, and `ffmpeg-mjpeg/8.1.2`. Each entry retains its source-video digest and
decoded image SHA-256.

[`0096-M0_Exact_Frame_Comparison.json`](0096-M0_Exact_Frame_Comparison.json) compares these decoded
frames with the selected maintained visible-card references. A frame is paired only when its source
digest, extraction provenance, dimensions, encoding, and decoded JPEG SHA-256 match.

| Coverage | Frames / recordings |
| --- | ---: |
| Recordings with a selected maintained visible-card reference | 28 of 34 |
| Reviewed reference frames | 1,381 |
| Exact decoded-image matches | 1,003 |
| Unpaired reference frames, uncovered for scores | 378 |
| Recordings without a selected maintained visible-card reference | 6 |

The comparison keeps both frame receipts for every exact match. It records no detector score.

## Source overlap and eligibility

Sixteen of the 34 recordings overlap the 20-source 0092 M4 final-refit set. Report these results as
in-sample. Seven recordings also have prior evaluation use recorded in the campaign lineage. The
manifest marks each recording's overlap and permission separately so later scores can use supported
denominators.

## Frozen processing contract

- Provider: `local-rfdetr-segmentation`, explicitly selected for every run.
- Device: MPS; confidence threshold: `0.5`.
- Bundle digest: `05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`.
- Checkpoint SHA-256: `80accf8a7c55ec65fdd346c0cd2bfcdd28b936260c242c30f1c39ced6043179e`.
- Bundle manifest SHA-256: `826ccba533531c62a2059be5889b9c48aa44800df5d216997575a238c37f5816`.
- Limits: at most 34 segmentation runs and 34 scene runs; one active processor; 24 active-processing
  hours total; 32 GiB process memory; sample RSS every 10 seconds; zero cloud requests.
- M1 and M2 run IDs are deterministic UUIDv5 values frozen per recording. Reuse them on resume.
- Preserve all selection pointers and maintained-reference drafts. Store processor results through the
  existing backend pipeline APIs and stores.
- On resume, reuse unchanged completed runs. Do not retry terminal failures or replace timed-out runs.

The manifest pins the application commit, source-file digests, and tool versions. The event and
visible-card batch controllers accept caller-supplied run IDs. Their preflight returns before any
processor request when the batch is not ready. The final exact-list preflight returned ready, and no
processor request ran during M0.

## Scope correction

An exploratory pass initially included the five 0088 system-holdout recordings and read their
selected reference state and decoded frames before their exclusion was caught. A later scoped-list
pass also queried the event-selection pointer for `IMG_0659`, which epic 0096 explicitly excludes.
No inference ran. The scratch measurements were deleted and are not used. The final manifest excludes
all protected and system-holdout sources; their rows contain no reference pointers or frame evidence.

## Next milestone

M1 can run the 34 frozen inputs. Keep the three no-event recordings, all protected sources, and all
system-holdout sources outside the batch. Evaluate only permitted, exact-frame pairs, and report
M4-overlap results separately.
