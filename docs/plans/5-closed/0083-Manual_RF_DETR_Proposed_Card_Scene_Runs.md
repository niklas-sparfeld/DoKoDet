# Manual RF-DETR runs for proposed card scenes

## Plan status

- **Summary:** Run the configured local RF-DETR segmentation provider, automatic table-plane
  calibration, and proposed card scene generation for an operator-supplied list of recordings.
- **Status:** Closed
- **Closure reason:** Complete
- **Closure note:** All 30 recordings reached a terminal proposed-scene outcome. The run reports five partial results and two failures for operator review. This epic records processing outcomes; it does not assess detector or calibration quality.
- **Depends on:** Completed 0048, 0049, 0068, and 0073
- **Outcome:** Local preflight, visible-card, and proposed-card-scene commands create processor runs
  through the same backend APIs and durable stores used by the recording workspace. The operator can
  inspect each run and result in the UI and use them in later analysis.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — add a manual preflight command that checks the complete recording list,
  selected event revisions, backend readiness, and the configured RF-DETR segmentation provider
  before any processor run can start.
- **M1:** Complete — ran local RF-DETR visible-card detection for all 30 eligible recordings with
  the explicit `local-rfdetr-segmentation` provider. All runs completed and retained exact input,
  model, run, and output revision lineage.
- **M2:** Complete — generated proposed card scenes for all 30 local RF-DETR results, recorded
  calibration and frame coverage, and retained every terminal run outcome. See the result table below.

## 1. Scope

The operator supplies a text file with one recording ID per line to the local preflight, visible-card,
and proposed-card-scene commands. The file is runtime input; the run evidence below records the list
used for this batch. The local backend must be running with the RF-DETR provider loaded. Preflight the
complete list before starting work. Require each
recording to have an accepted recording video, a selected event revision, and an available
configured `local-rfdetr-segmentation` provider. Freeze the exact event revision in each
visible-card run request.

For each eligible recording, start the visible-card run through the same backend endpoint used by
the recording workspace. Wait for a terminal state and use its exact generated visible-card
revision to start proposed card scene generation through the workspace endpoint. The processor
performs automatic table-plane calibration and stores its calibration diagnostics
and proposed card scenes through the existing backend pipeline services. Poll each durable run
until it reaches a terminal state. Report failures and partial outcomes per recording, and continue
with other eligible recordings.

Use the current configured RF-DETR segmentation bundle when the command starts. Each run must
record the exact provider and model identity selected by the backend. The command is manual and
local; it does not schedule future runs.

## 2. Result and review boundaries

Keep processor run records, data revisions, table-plane calibration revisions, and proposed card
scenes in the existing pipeline stores. Do not write a second copy of processor output. Print a
batch summary with recording IDs, input revisions, run IDs, result revision IDs, calibration status,
and failures so the operator can find each result in the UI and refer to it later.

The command does not create or update a maintained reference, accept proposed card scenes, assess
detector or calibration quality, compare models, or perform later analysis. Proposed card scenes
remain processor output for operator inspection.

## 3. Completion checks

- The operator can run preflight, visible-card detection, and proposed card scene generation with a
  supplied recording list and no UI interaction.
- Invalid list entries and missing prerequisites are reported before any run starts.
- Each started processor run uses the same backend API and storage path as the UI action and records
  exact input, model, and output lineage.
- A terminal failure or partial result for one recording is visible in the summary and does not hide
  the outcomes for other recordings.
- The UI can open each persisted visible-card result and proposed card scene result by recording.

### M0 implementation evidence — 2026-09-25

- Added `doko pipeline proposed-card-scenes-preflight --recordings <path>`. The runtime file has
  one recording ID per line. The command rejects invalid and duplicate IDs before contacting the
  backend.
- Added a read-only provider availability endpoint. It loads the configured
  `local-rfdetr-segmentation` provider and returns its validated bundle identity.
- The command checks backend readiness, accepted recordings, and each selected completed-reference
  or generated event revision. It visits every listed recording and starts no processor runs.
- Focused checks passed: four operations tests, 20 backend app tests, and Ruff on all changed Python
  files. CLI help renders the new command and its options.

### M1 implementation evidence — 2026-09-25

- Added `doko pipeline proposed-card-scenes-visible-cards --recordings <path>`. It repeats the full
  M0 preflight before it starts any run, then freezes each selected event revision and explicitly
  selects `local-rfdetr-segmentation` through the recording workspace API.
- The command polls each durable run to a terminal state, retrieves completed or partial results,
  and reports the event revision, run ID, exact model and implementation identity, output revision
  IDs, and per-recording failures. It continues after a failed recording.
- Focused operations tests cover event and provider selection, lineage capture, blocked preflight,
  continuation after failure, and result-fetch errors. Eight focused preflight and batch-run tests
  passed; Ruff and CLI help checks passed.
- The operator-supplied list contained 30 recordings. All 30 runs reached `complete`; there were no
  partial or failed runs. Every request froze its selected event revision, and every stored result
  retained its output revision ID.
- The backend used bundle schema `rfdetr-segmentation-bundle/v1`, digest
  `b3deef701e26d91ebfd9d357bff69b45ae9360e3722de340f1044214179df29`.

### M2 implementation evidence — 2026-09-25

- Ran proposed card scene generation from the exact local RF-DETR output revision for each of the 30
  recordings. Each run used the backend workspace API and retained its processor run, result revision,
  and automatic calibration data where calibration completed.
- All 30 runs reached a terminal state: 23 complete, five partial, and two failed. The partial and
  failed outcomes are recorded as processor results; this epic does not assess their quality.
- IMG_0645 failed with `unstable_table_transform`. IMG_0092 failed with
  `inconsistent_card_geometry`. The interrupted IMG_0097 attempt was rerun and the final run completed.
- Successful and partial result revisions report 1,383 supported frames and 13 unsupported frames
  across 1,396 frames.

### Per-recording results

| Recording | Outcome | Proposal run | Result / failure | Frame coverage |
| --- | --- | --- | --- | --- |
| IMG_0636 | complete | `card-scene-proposal-da736f54-af74-4a8d-82ed-c5694c5e2b56` | `card-scene-proposals-card-scene-proposal-da736f54-af74-4a8d-82ed-c5694c5e2b56-attempt-1` | 50/50 supported |
| IMG_0637 | complete | `card-scene-proposal-ccd2462d-69f8-41c6-a867-50d846a03749` | `card-scene-proposals-card-scene-proposal-ccd2462d-69f8-41c6-a867-50d846a03749-attempt-1` | 50/50 supported |
| IMG_0638 | complete | `card-scene-proposal-d8b6c2d7-1a8b-40d3-8dea-7dee4feb38cc` | `card-scene-proposals-card-scene-proposal-d8b6c2d7-1a8b-40d3-8dea-7dee4feb38cc-attempt-1` | 51/51 supported |
| IMG_0639 | complete | `card-scene-proposal-2002449e-1fc3-42b7-b487-727e4a91c634` | `card-scene-proposals-card-scene-proposal-2002449e-1fc3-42b7-b487-727e4a91c634-attempt-1` | 50/50 supported |
| IMG_0640 | complete | `card-scene-proposal-f6edc3c8-fdde-40a3-9ed2-1c09d8fc6f31` | `card-scene-proposals-card-scene-proposal-f6edc3c8-fdde-40a3-9ed2-1c09d8fc6f31-attempt-1` | 50/50 supported |
| IMG_0641 | partial | `card-scene-proposal-963ff4a7-1b56-4c1f-af9c-b4934b67be1a` | `card-scene-proposals-card-scene-proposal-963ff4a7-1b56-4c1f-af9c-b4934b67be1a-attempt-1` | 52/53 supported |
| IMG_0642 | complete | `card-scene-proposal-7d6ab874-5976-4987-a248-8780043a5bdb` | `card-scene-proposals-card-scene-proposal-7d6ab874-5976-4987-a248-8780043a5bdb-attempt-1` | 50/50 supported |
| IMG_0643 | complete | `card-scene-proposal-2ed272f2-f92a-438a-ba35-cf59408ae8b3` | `card-scene-proposals-card-scene-proposal-2ed272f2-f92a-438a-ba35-cf59408ae8b3-attempt-1` | 52/52 supported |
| IMG_0644 | complete | `card-scene-proposal-d8ef1e9a-8120-46c5-a4cd-d8066a45d29d` | `card-scene-proposals-card-scene-proposal-d8ef1e9a-8120-46c5-a4cd-d8066a45d29d-attempt-1` | 54/54 supported |
| IMG_0645 | failed | `card-scene-proposal-b491688b-a168-4512-8e10-7fef402ccf30` | `unstable_table_transform` | — |
| IMG_0646 | complete | `card-scene-proposal-5edb14c4-9057-4416-878b-8dc7f9a86317` | `card-scene-proposals-card-scene-proposal-5edb14c4-9057-4416-878b-8dc7f9a86317-attempt-1` | 51/51 supported |
| IMG_0648 | complete | `card-scene-proposal-598ba897-4ec3-474e-b857-54de187a5915` | `card-scene-proposals-card-scene-proposal-598ba897-4ec3-474e-b857-54de187a5915-attempt-1` | 52/52 supported |
| IMG_0649 | complete | `card-scene-proposal-5ce9fa63-c753-407e-885b-38999487aa2b` | `card-scene-proposals-card-scene-proposal-5ce9fa63-c753-407e-885b-38999487aa2b-attempt-1` | 54/54 supported |
| IMG_0650 | complete | `card-scene-proposal-1968d038-f7a0-4a53-ad96-cd9c010b1a29` | `card-scene-proposals-card-scene-proposal-1968d038-f7a0-4a53-ad96-cd9c010b1a29-attempt-1` | 36/36 supported |
| IMG_0651 | complete | `card-scene-proposal-b72d7b69-e3f1-4f25-8c81-b3327f921eed` | `card-scene-proposals-card-scene-proposal-b72d7b69-e3f1-4f25-8c81-b3327f921eed-attempt-1` | 51/51 supported |
| IMG_0652 | complete | `card-scene-proposal-03998c53-0081-4d8b-9b16-ed3678362f68` | `card-scene-proposals-card-scene-proposal-03998c53-0081-4d8b-9b16-ed3678362f68-attempt-1` | 51/51 supported |
| IMG_0653 | complete | `card-scene-proposal-5a3fd358-1deb-46df-9105-707539580841` | `card-scene-proposals-card-scene-proposal-5a3fd358-1deb-46df-9105-707539580841-attempt-1` | 50/50 supported |
| IMG_0654 | complete | `card-scene-proposal-08021347-ad49-4c86-8e9b-2aebd9eeaa85` | `card-scene-proposals-card-scene-proposal-08021347-ad49-4c86-8e9b-2aebd9eeaa85-attempt-1` | 51/51 supported |
| IMG_0669 | complete | `card-scene-proposal-de21ce5d-2b56-4215-a672-ac01461a9c7d` | `card-scene-proposals-card-scene-proposal-de21ce5d-2b56-4215-a672-ac01461a9c7d-attempt-1` | 61/61 supported |
| IMG_0670 | partial | `card-scene-proposal-ec8a4d6b-890d-4816-b193-3271459c36a2` | `card-scene-proposals-card-scene-proposal-ec8a4d6b-890d-4816-b193-3271459c36a2-attempt-1` | 53/55 supported |
| IMG_0671 | complete | `card-scene-proposal-b171ee5d-c79a-4487-b971-14591841784f` | `card-scene-proposals-card-scene-proposal-b171ee5d-c79a-4487-b971-14591841784f-attempt-1` | 33/33 supported |
| IMG_0673 | complete | `card-scene-proposal-92e2b32f-e1cd-4ab0-a30c-c62749ca7190` | `card-scene-proposals-card-scene-proposal-92e2b32f-e1cd-4ab0-a30c-c62749ca7190-attempt-1` | 50/50 supported |
| IMG_0674 | partial | `card-scene-proposal-a579c7bc-efe1-40de-bd59-1f13e7b64010` | `card-scene-proposals-card-scene-proposal-a579c7bc-efe1-40de-bd59-1f13e7b64010-attempt-1` | 31/34 supported |
| IMG_0090 | partial | `card-scene-proposal-f443c0c1-0a9b-4353-9d15-3fead727eacb` | `card-scene-proposals-card-scene-proposal-f443c0c1-0a9b-4353-9d15-3fead727eacb-attempt-1` | 44/50 supported |
| IMG_0091 | complete | `card-scene-proposal-64858096-0b5c-4b8f-8e45-e9e87a4d38d0` | `card-scene-proposals-card-scene-proposal-64858096-0b5c-4b8f-8e45-e9e87a4d38d0-attempt-1` | 50/50 supported |
| IMG_0092 | failed | `card-scene-proposal-06370ebd-7f5a-42ff-9380-ea14bcb09cfc` | `inconsistent_card_geometry` | — |
| IMG_0095 | complete | `card-scene-proposal-0eb9512c-fe28-415f-8f52-ef1d1c62b4bf` | `card-scene-proposals-card-scene-proposal-0eb9512c-fe28-415f-8f52-ef1d1c62b4bf-attempt-1` | 53/53 supported |
| IMG_0096 | partial | `card-scene-proposal-c6aaaacb-63ad-4cd0-a475-26edace8fc38` | `card-scene-proposals-card-scene-proposal-c6aaaacb-63ad-4cd0-a475-26edace8fc38-attempt-1` | 49/50 supported |
| IMG_0097 | complete | `card-scene-proposal-6a30dacd-c8fe-49ac-8ae1-df954971af76` | `card-scene-proposals-card-scene-proposal-6a30dacd-c8fe-49ac-8ae1-df954971af76-attempt-1` | 50/50 supported |
| IMG_0661 | complete | `card-scene-proposal-fa992c98-35ba-4f31-b296-23d4d38d2916` | `card-scene-proposals-card-scene-proposal-fa992c98-35ba-4f31-b296-23d4d38d2916-attempt-1` | 54/54 supported |

Closure: The planned local processing and result reporting are complete for this batch. Later
operator review, maintained-reference changes, and model or calibration quality decisions remain
outside this epic.
