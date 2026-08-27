# DokoDetector app training recordings

## Plan status

- Summary: Record live video and model predictions, upload them, and import them into CardEventNet
- Status: In Progress
- Depends on: completed plans 0003, 0004, and 0014; completed plan 0016; and the shared source-data
  contract from plan 0020 (M1, complete). Plan 0020 M3 can proceed in parallel.
- Current phase: Phase 5 — Prove the local end-to-end workflow
- Boundary: This plan owns recording capture, upload, and immutable intake. The data-foundation
  [plan](0020-Data_Foundation.md) owns canonical dataset identity, annotation lineage, review, and
  promotion.

## 1. Outcome

Add an explicit training-recording mode to the app.

When the app is connected to a ready local backend, an operator can start and stop a recording.
During the recording, the app continues normal live inference and evidence-package upload. It also
records:

- the complete oriented camera video, without audio;
- every model probability produced by the live inference path;
- every event proposal emitted by the causal decoder;
- the model, decoder, camera, app, device, and timing metadata needed to reproduce the recording.

After the operator stops the recording, the app finalizes an immutable local bundle and uploads it
to the backend. The backend validates the bundle and stores it in a local CardEventNet intake area.
A CardEventNet command can then import the recording without a custom conversion script.

The intended flow is:

```text
live camera frames
  +--> CardEventNet inference --> evidence packages --> existing evidence API
  |
  +--> video recorder
  |
  +--> prediction recorder
          |
          v
    finalized recording bundle
          |
          v
    training-recording API
          |
          v
    immutable backend intake bundle
          |
          v
    cardevent import-recording
          |
          +--> source video
          +--> device prediction proposals
          +--> draft dataset metadata
          +--> optional review queue
```

The normal development loop must work with a short checked-in or generated video fixture. It must
not require a phone, a cloud service, or a real game. The fixture can show staged activity.

This plan is not a prerequisite for the first TableEvidenceAnalyzer dataset work. Existing local
videos and evidence packages can establish the data and training contracts first. Implement
recording intake after the local app-to-backend path in plan 0016 is proven.

## 2. Fixed decisions

### 2.1 Keep session, recording, and evidence identities separate

Do not add a full video to each evidence package. Evidence packages remain small, centered on one
event proposal, and independently retryable.

Add a versioned `cardevent-recording/v1` contract for one complete recording. Give it separate
`session_id` and `recording_id` fields. The operator starts a new session or selects an existing
session independently from starting a recording. Several recordings from the same occasion reuse
the session ID.

Correlate evidence packages with both identities. Do not use the recording UUID as the session ID.
The closed V1 evidence contract calls its recording-level correlation value `capture_session_id`.
Preserve that field only as a compatibility value equal to `recording_id`; do not interpret it as a
canonical session. Add canonical `session_id` and `recording_id` fields in the next evidence
contract version before this plan is implemented.

### 2.2 Record only explicit live recordings

The operator must press **Start training recording**. Starting the camera or inference does not
start a recording. The first version records the live camera only. Replaying an existing video does
not create a second training recording.

Require a ready backend when the operator starts. A later network loss must not stop capture or
delete data. Finalize the recording locally and queue it for retry.

Show a persistent recording indicator, elapsed time, estimated stored size, and final upload state.
Do not record audio.

### 2.3 Use one recording-relative timeline

Use one recording clock for video, predictions, decoder event proposals, and evidence packages.
Adapt or replace the existing `EvidenceSessionClock` name when this plan changes that code; it
measures a recording timeline, not a canonical session. Normalize the first accepted video frame
to `0` seconds. Preserve monotonic presentation times in the video. Store probability and event
proposal times as seconds relative to the same zero point.

Do not align data by wall-clock timestamps. Record the UTC start time only as metadata.

### 2.4 Preserve raw model output as provenance, not truth

Device predictions are proposals. They are not annotations and must not enter training as positive
labels without human review.

Store every produced probability sample. Store the device-decoded event proposals as a derived
list. Include the model version, weights SHA-256, preprocessing identifier, inference rate,
threshold, peak confirmation, and minimum event gap.

The final `predictions.json` should use the useful parts of the existing `cardevent infer` output:

```json
{
  "schema_version": "cardevent-device-predictions/v1",
  "source_video": "<video-id>.mov",
  "model": {},
  "decoder": {},
  "probabilities": [
    {"time_s": 0.125, "probability": 0.23, "inference_ms": 14.2}
  ],
  "event_proposals": [
    {"time_s": 12.375, "emitted_at_s": 12.5, "probability": 0.83}
  ]
}
```

The CardEventNet importer must validate and convert this file to the existing proposal and
probability-stream types. Do not make the training code read an iOS-specific JSONL log directly.

### 2.5 Keep the uploaded source immutable

The app and backend must calculate byte lengths and SHA-256 hashes for all bundle files. The backend
must retain the exact accepted bytes. Review, annotation, and training commands must not modify the
accepted intake bundle.

Use a client-generated recording UUID and idempotent `PUT` semantics. An identical retry succeeds.
Reuse of the UUID with different content returns a conflict.

### 2.6 Require human annotation before training

The backend may create a review queue from device-decoded event proposals. Such a queue helps find
false triggers and classify proposals. It cannot reveal model misses outside those proposals.
Therefore, it is not proof of complete ground truth.

Before a new video becomes training or evaluation input, a reviewer must complete a video-wide
annotation pass. Start that pass with the device event proposals:

```bash
cardevent annotate <video> --proposals <predictions.json>
```

An optional seed review queue may use the existing `cardevent-review-queue-v1` format and
`unmatched_model_candidate` items. Mark it as candidate-only provenance. Do not apply it as a
complete annotation set by default.

## 3. Recording bundle contract

The finalized app bundle is:

```text
<recording-id>/
  manifest.json
  <video-id>.mov
  <video-id>.json
```

Use H.264 in a QuickTime container for V1. Record the complete oriented camera frames used by the
live pipeline. Do not crop, letterbox, add overlays, or re-encode on the backend.

The manifest must contain:

```text
schema_version              cardevent-recording/v1
recording_id
session_id
video_id
started_at_utc
ended_at_utc
duration_s
state                       complete
video                       name, type, byte length, SHA-256, codec, size, frame rate
predictions                 name, type, byte length, SHA-256, sample and event-proposal counts
model                       name, version, weights SHA-256, preprocessing
decoder                     threshold, peak confirmation, minimum event gap
camera                      position, orientation, source size
client                      app version, build, device model, OS version
capture_metrics             received, written, and dropped frame counts
source                      self_recorded
source_permission           explicit operator choice
```

Use a stable filename derived from `video_id`, not an operator-provided path. V1 records one video
per recording bundle.

The app writes working files below a staging directory. On stop, it closes the video writer,
closes the prediction writer, validates both artifacts, writes the manifest, and atomically moves
the directory to a queued state. Never upload a staging directory.

If the app terminates during capture, retain the incomplete directory for diagnostics. Do not
upload it as a complete recording. A later recovery command may salvage it in a separate plan.

## 4. HTTP and backend contract

Add these local API operations:

```http
PUT /v1/training-recordings/{recording_id}
GET /v1/training-recordings/{recording_id}
```

The `PUT` request is file-backed multipart data with `manifest`, `video`, and `predictions` parts.
Do not load the video into memory. Enforce separate manifest, prediction, video, and total request
limits. Make the limits visible through backend configuration and app error messages.

Return:

- `201 Created` for a new recording;
- `200 OK` for an identical retry;
- `409 Conflict` for a different bundle with the same recording ID;
- a stable validation error for a malformed or incomplete bundle.

Stream each part to a temporary directory while calculating its hash and size. Validate the full
bundle before an atomic rename. Store searchable metadata in SQLite, but keep the video and JSON
files on the local filesystem.

Use this backend layout:

```text
<evidence-root>/
  training-recordings/
    <recording-id>/
      manifest.json
      videos/
        <video-id>.mov
      predictions/
        <video-id>.json
      intake/
        dataset-record.yaml
        candidate-review-queue.json
```

`dataset-record.yaml` is a draft CardEventNet video-metadata record. Populate measured and known
fields. Leave facts that require an operator as explicit nulls. Do not guess the table setup,
lighting, background, deck, scenario tags, or known limitations.

The optional candidate queue must be derived deterministically from `predictions.json`. Regenerating
it must produce the same item IDs and order.

Do not expose a delete operation in the first implementation. Document how to remove local test
data manually. Add retention and deletion policy before this feature handles contributed footage.

## 5. CardEventNet import contract

Add a command similar to:

```bash
cd card_event_net
uv run cardevent import-recording \
  --recording-dir ../backend/.runtime/training-recordings/<recording-id> \
  --videos-dir data/raw \
  --predictions-dir data/device-predictions \
  --metadata completed-dataset-record.yaml \
  --manifest data/dataset-manifest.yaml
```

The command must:

1. Validate the recording manifest and every file hash.
2. Reject an incomplete recording.
3. Reject a `video_id` collision unless the existing video has the same hash.
4. Copy or hard-link the immutable video into the dataset intake location.
5. Copy the validated prediction file without changing it.
6. Merge a complete, operator-approved video-metadata record into the dataset manifest.
7. Copy the optional candidate queue to a review intake directory.
8. Write an import receipt with the source recording ID and hashes.

The command must stop before writing if required dataset metadata is incomplete. Require an
operator-approved metadata YAML file when the backend draft is incomplete. Keep all recordings
from one session in one `session_id` leakage group. Record explicit game and round time spans when
known. Use staged activity when the recording does not show part of a game.

Do not assign the video to train, validation, or test automatically. Split selection is a separate,
reviewed dataset decision. Do not run training automatically.

After import, the existing commands must work:

```bash
uv run cardevent annotate data/raw/<video-id>.mov \
  --proposals data/device-predictions/<video-id>.json
uv run cardevent prepare --videos data/raw/<video-id>.mov
uv run cardevent split --manifest data/dataset-manifest.yaml --group-by session_id \
  --out data/splits/session-aware.yaml
```

## 6. Implementation phases

### Phase 0: Freeze the shared contract

Add JSON schemas for the recording manifest and device prediction file. Add one small fixture bundle
with deterministic hashes. The fixture may use a generated short video.

Progress (2026-08-27): The versioned schemas, deterministic fixture, and contract validators are
implemented in Swift, the backend, and CardEventNet. The Python contract tests and full suites pass.
The Swift core package builds; XCTest execution remains pending a toolchain with XCTest support.

Add contract tests in Swift, the backend, and CardEventNet. Each component must accept the same
fixture and reject the same malformed variants.

Acceptance:

- one versioned fixture passes all three implementations;
- hash, time, identity, and file-name mismatches fail with clear messages;
- the contract states that device predictions are not ground truth.

### Phase 1: Add the bounded iOS recorder

Create a recording coordinator that receives the same oriented `VideoFrame` values as inference.
Use `AVAssetWriter` behind an injected protocol so unit tests do not require a camera or encoder.

The camera callback must not block on file I/O. Use one bounded serial writer path. If the writer is
not ready, drop that recording frame and increment a metric. Do not build an unbounded raw-frame
queue. Inference and evidence capture must continue if recording falls behind.

Write prediction samples as they arrive. Finalize `predictions.json` without retaining the full
video or raw frames in memory.

Acceptance:

- video and prediction timestamps share one zero point;
- a slow or failed recorder cannot block inference;
- start, stop, duplicate stop, writer failure, dropped frame, and finalization tests pass;
- the output bundle validates against the shared fixture contract.

Progress (2026-08-27): Added `TrainingRecordingCoordinator` with one bounded frame slot, a serial
`AVAssetWriter` path, streaming device-prediction JSON, failure metrics, and atomic bundle
finalization. The writer is injected behind a protocol for local unit tests. The Swift package
build passes. XCTest execution remains pending a toolchain with XCTest support.

### Phase 2: Add app state, durable queue, and upload

Add the start and stop controls to the live detection view. Require explicit source permission and
show the recording and upload states:

```text
idle -> recording -> finalizing -> queued -> uploading -> acknowledged
                                      |             |
                                      +--> failed <--+
```

Persist queued bundles in Application Support. Reconstruct the queue on launch. Use a file-backed
`URLSessionUploadTask`. Preserve failed bundles and allow retry. Check free disk space before start
and enforce a configurable maximum duration or size.

Pass both the recording ID and session ID into the evidence coordinator. Until the versioned
evidence-contract update is complete, map its legacy `capture_session_id` compatibility field to
the recording ID. Evidence packages continue to use their existing endpoint and retry behavior.

Acceptance:

- the app can recover and retry a finalized bundle after restart;
- network loss during recording does not lose the finalized bundle;
- an acknowledged bundle is not uploaded again;
- UI tests cover invalid state transitions and operator-visible failures.

Progress (2026-08-27): Added durable Application Support queue recovery, immutable bundle
validation, file-backed multipart upload, retry and failure preservation, explicit live-recording
consent, recording limits, free-space checks, operator-visible workflow states, and automatic
upload recovery. Live inference now sends the same frames and predictions to the recorder. Evidence
coordination keeps the canonical session ID separate and maps the recording ID to the legacy
capture_session_id compatibility value. XCTest execution remains pending a toolchain with XCTest
support; the Swift package build and source parsing pass.

### Phase 3: Add backend ingestion and storage

Add the recording routes, validation, SQLite metadata, streaming file storage, idempotency, and
read-back response. Keep this work independent from the evidence-package request path except for
shared low-level hash and atomic-file helpers.

Create the draft dataset record and optional candidate queue only after the immutable upload is
committed. Treat these files as derived artifacts that can be regenerated.

Acceptance:

- complete upload, identical retry, conflict, truncation, invalid hash, and size-limit tests pass;
- a failed request leaves no final directory or database row;
- the read endpoint reports the recording, file hashes, derived-artifact state, and related evidence
  package count;
- the service streams a large fixture without loading it into one byte string.

Progress (2026-08-27): Added the versioned training-recording `PUT` and `GET` routes, separate
SQLite recording metadata, streamed video storage, atomic bundle commits, idempotent retries,
conflict detection, configured manifest/prediction/video/total limits, and rollback after storage
or database failure. Accepted recordings produce deterministic draft dataset metadata and a
candidate-only review queue after the immutable bundle is committed. The read endpoint reports
file hashes, derived-artifact state, and evidence-package count by canonical session ID. Backend
tests, migration checks, lint, formatting, and the local HTTP pipeline pass.

### Phase 4: Add CardEventNet import and review entry points

Implement `cardevent import-recording`. Extend proposal loading to accept the versioned device
prediction schema. If candidate queues are enabled, test their compatibility with `cardevent
review` and mark their provenance as candidate-only.

Acceptance:

- importing the fixture produces a video, prediction file, metadata record, and receipt;
- repeated identical import is safe;
- conflicting content and incomplete metadata stop before partial writes;
- the imported video opens in `cardevent annotate` at each device proposal;
- source asset bytes remain unchanged.

Progress (2026-08-27): Added `cardevent import-recording` for backend recording intake. The
command validates the versioned manifest, prediction document, streamed video hash, complete
operator metadata, and optional candidate-only review queue before writing. It copies the source
video and prediction bytes, merges the approved record into the dataset manifest, preserves
session grouping without assigning a split, writes an import receipt, and safely handles repeated
imports and collisions. Versioned device predictions now load as annotation proposals, and the
candidate queue passes the existing review-queue validator.

### Phase 5: Prove the local end-to-end workflow

Run a short saved-video simulation through the same frame, recorder, prediction, upload, backend,
and import interfaces used by live capture. Then annotate the imported video with device proposals
and prepare its frame cache.

Acceptance:

- the recording video duration and prediction timeline agree within one source-frame interval;
- every uploaded and imported hash matches the app manifest;
- evidence packages from the recording use the same recording ID and canonical session ID;
- the imported recording passes `cardevent prepare`;
- no phone, Docker service, or cloud resource is required for the automated gate.

## 7. Required tests and checks

Add tests for:

- recording and prediction schema validation in all components;
- common clock alignment and non-monotonic timestamp rejection;
- frame drop behavior and bounded queues;
- video-writer and prediction-writer failures;
- atomic finalization and startup queue recovery;
- multipart streaming and configured limits;
- upload idempotency and conflict detection;
- backend rollback after storage or database failure;
- deterministic draft metadata and candidate-queue generation;
- CardEventNet import idempotency and collision handling;
- proposal loading from device predictions;
- session grouping across several recordings and prevention of automatic split assignment;
- an end-to-end local fixture flow.

Run:

```bash
cd ios
swift test

cd ../backend
uv run pytest
uv run ruff check .
uv run ruff format --check .

cd ../card_event_net
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Use `mise install` after a tool version changes. Do not add a `mise` task that only wraps these
commands.

## 8. Non-goals

This plan does not:

- record audio;
- record without an explicit operator action;
- upload video continuously while capture is active;
- replace evidence packages centered on one event proposal;
- treat device predictions as labels;
- guarantee that a candidate-only review queue finds missed events;
- assign a dataset split or start training automatically;
- add background iOS uploads, cloud storage, authentication, or remote deployment;
- define production retention, consent, or deletion policy;
- support multi-video recording bundles.

## 9. Final acceptance gate

The plan is complete when a developer can:

1. Start the local backend.
2. Start a new session or select an existing session.
3. Start one explicit training recording in the app or saved-video simulator.
4. Continue to receive normal evidence packages during the recording.
5. Stop and finalize the recording without losing video or prediction data.
6. Retry the upload after a simulated connection failure.
7. Verify the immutable video and predictions on the backend.
8. Import the bundle with one CardEventNet command.
9. Open the imported video with device predictions as event proposals.
10. Complete a video-wide annotation pass before adding the video to a dataset split.
11. Prepare the imported video with the existing CardEventNet pipeline.

No manual JSON conversion, file renaming, or timestamp alignment is required.
