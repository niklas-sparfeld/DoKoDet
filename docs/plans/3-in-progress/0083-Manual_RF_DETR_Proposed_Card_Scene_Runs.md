# Manual RF-DETR runs for proposed card scenes

## Plan status

- **Summary:** Run the configured local RF-DETR segmentation provider, automatic table-plane
  calibration, and proposed card scene generation for an operator-supplied list of recordings.
- **Status:** In Progress
- **Depends on:** Completed 0048, 0049, 0068, and 0073
- **Outcome:** One manual local command creates visible-card and proposed-card-scene processor runs
  through the same backend API and durable stores used by the recording workspace. The operator can
  inspect every run and result in the UI and use them in later analysis.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — add a manual preflight command that checks the complete recording list,
  selected event revisions, backend readiness, and the configured RF-DETR segmentation provider
  before any processor run can start.
- **M1:** Complete — add a manual batch command that preflights the complete list, runs visible-card
  detection with the explicit `local-rfdetr-segmentation` provider, waits for terminal states, and
  reports exact input, model, run, and output revision lineage.
- **M2:** Not started — run proposed card scene generation from each available RF-DETR result,
  capture the automatic calibration and scene outcomes, and report all run IDs and terminal states.

## 1. Scope

The operator starts one local command and supplies a text file with one recording ID per line. The
file is runtime input; do not commit a fixed recording list. The local backend must be running with
the RF-DETR provider loaded. Preflight the complete list before starting work. Require each
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

- The operator can run the command with a supplied recording list and no UI interaction.
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
