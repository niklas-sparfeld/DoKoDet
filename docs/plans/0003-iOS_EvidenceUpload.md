# DokoDetector iOS App — Evidence Capture & Upload Implementation Plan

## Plan status

- **Summary:** Capture and upload evidence
- **Status:** Draft

## 0. Mission

Evolve the existing `CardEventProbe` PoC into the first real **DokoDetector iOS application**.

The app's responsibility in this phase is:

1. continuously capture the real Doppelkopf table with the iPhone camera;
2. run the existing `CardEventNet` Core ML model on-device;
3. convert the model's probability stream into discrete card-play events using the existing `EventPostProcessor`;
4. preserve a small set of high-resolution camera frames around each event;
5. assemble those frames plus event/model/session metadata into a durable **evidence package**;
6. upload each package to a hypothetical HTTP server;
7. survive temporary loss of connectivity, app suspension, upload failures, and process restarts without silently losing already-captured packages.

The server itself is **not implemented in this phase**. This phase must define the wire contract precisely enough that the server can be implemented as the next independent step.

The intended end-to-end architecture remains:

```text
iPhone camera
  -> low-resolution causal CardEventNet
  -> discrete card-play event
  -> high-resolution evidence package
  -> durable local upload queue
  -> HTTP server
  -> later: cloud card recognition
  -> later: game-state validation
```

This is the first production-oriented iOS implementation, but it is still deliberately narrow.

The goal is not yet a polished App Store product. The goal is a reliable capture/upload client whose boundaries can survive the later addition of recognition results, game state, player attribution, authentication, and better UX.

---

## 1. Starting Point: Reuse the PoC

Assume the previous `CardEventProbe` implementation exists and works.

It already established these boundaries:

```text
VideoFrame
  -> CardEventModelRunner
  -> ModelPrediction
  -> EventPostProcessor
  -> DetectionEvent
```

It also already contains, or has equivalents of:

```text
CameraSession
CameraPreview
CameraFrameDelegate

CardEventModelRunner
CoreMLCardEventModelRunner
ModelContract
ModelPrediction
FrameInferenceCoordinator

EventPostProcessor
DetectionEvent

DiagnosticsStore
```

Do **not** rewrite those components merely because the app is becoming "real".

Preserve the tested PoC behavior unless a production requirement below explicitly requires a change.

In particular:

- keep `CardEventModelRunner.consume(_:)`;
- keep model preprocessing isolated inside the model runner;
- keep one bounded serial inference path;
- keep `EventPostProcessor` independent of Core ML;
- keep live capture independent from networking;
- keep the model's exact training-time preprocessing unchanged;
- keep `AVCaptureVideoDataOutput.alwaysDiscardsLateVideoFrames = true`;
- do not create an unbounded frame queue.

The previous replay/diagnostics functionality is useful for development. It may remain available behind a Debug/developer mode, but it is no longer the primary app flow.

---

## 2. Target Implementer

This plan is written for a capable coding model that should not be expected to make major architecture decisions.

Implementation rules:

1. Prefer ordinary Swift and Apple frameworks.
2. No third-party runtime dependencies.
3. Compile and run tests after every phase.
4. Keep files small and responsibilities explicit.
5. Do not invent server behavior beyond the contract in this document.
6. Do not invent new Core ML preprocessing.
7. Do not introduce a database unless the filesystem-based queue proves insufficient.
8. Do not introduce a generic networking framework.
9. Do not let networking backpressure the camera or inference pipeline.
10. Persist a package before attempting its upload.
11. Never silently delete an unacknowledged package.
12. Every package must have a stable client-generated UUID and sequence number.

---

## 3. Technology Choices

Use:

- Swift
- SwiftUI
- AVFoundation
- Core ML
- Foundation
- `URLSession`
- `CryptoKit` for SHA-256
- `Network` only if connectivity observation becomes necessary
- XCTest / Swift Testing as already used by the project

Deployment target:

```text
iOS 18+
```

unless the existing Xcode project already uses another explicit target.

Do not add:

- Alamofire
- SQLite wrappers
- Core Data
- SwiftData
- ZIP libraries
- Combine-heavy architecture
- generic dependency-injection frameworks

Use Swift concurrency where it simplifies ownership, but keep the concurrency model intentionally small.

---

# 4. Core Architectural Change

The PoC had one main consumer of camera frames: model inference.

The real app needs a second bounded consumer: evidence capture.

Use this conceptual flow:

```text
                                      +--------------------------+
                                      |  CardEventModelRunner    |
                                      |  low-resolution causal   |
                                      +-------------+------------+
                                                    |
                                                    v
Camera -> VideoFrame -> FrameRouter -> FrameInferenceCoordinator
             |                                      |
             |                                      v
             |                              EventPostProcessor
             |                                      |
             |                                      v
             |                               DetectionEvent
             |                                      |
             v                                      |
      EvidenceSampler                               |
             |                                      |
             v                                      |
      EvidenceFrameBuffer <-------------------------+
             |
             v
      EventPackageAssembler
             |
             v
         PackageStore
             |
             v
      UploadCoordinator
             |
             v
         ServerClient
             |
             v
     hypothetical server
```

There are two important rules.

### Rule 1 — evidence capture and inference are independent

A slow JPEG encode must not stall Core ML inference.

A slow Core ML inference must not prevent the evidence sampler from preserving useful frames.

Both paths are bounded and may drop work rather than accumulate an unbounded latency queue.

### Rule 2 — networking begins only after durable persistence

The flow is:

```text
event
  -> assemble package
  -> atomically persist package
  -> mark queued
  -> schedule upload
```

Never:

```text
event
  -> construct in memory
  -> upload directly
  -> hope it succeeded
```

Connectivity is an optional downstream condition, not part of event capture correctness.

---

# 5. Proposed Project Layout

Refactor approximately toward:

```text
DokoDetector/
├── DokoDetectorApp.swift
│
├── App/
│   ├── AppState.swift
│   ├── AppConfiguration.swift
│   └── AppEnvironment.swift
│
├── Camera/
│   ├── CameraSession.swift
│   ├── CameraPreview.swift
│   ├── CameraFrameDelegate.swift
│   └── FrameRouter.swift
│
├── Inference/
│   ├── CardEventModelRunner.swift
│   ├── CoreMLCardEventModelRunner.swift
│   ├── ModelContract.swift
│   ├── ModelPrediction.swift
│   └── FrameInferenceCoordinator.swift
│
├── Events/
│   ├── EventPostProcessor.swift
│   ├── DetectionEvent.swift
│   └── PredictionHistory.swift
│
├── Evidence/
│   ├── EvidenceSampler.swift
│   ├── EvidenceFrame.swift
│   ├── EvidenceFrameBuffer.swift
│   ├── EventPackageAssembler.swift
│   ├── EvidencePackage.swift
│   └── EvidenceImageEncoder.swift
│
├── Sessions/
│   ├── CaptureSession.swift
│   ├── SessionController.swift
│   ├── SessionClock.swift
│   └── PlayerContext.swift
│
├── Persistence/
│   ├── PackageStore.swift
│   ├── StoredPackage.swift
│   ├── PackageState.swift
│   └── UploadReceiptStore.swift
│
├── Networking/
│   ├── ServerClient.swift
│   ├── HTTPServerClient.swift
│   ├── UploadCoordinator.swift
│   ├── BackgroundSessionDelegate.swift
│   ├── MultipartBodyWriter.swift
│   └── ServerConfiguration.swift
│
├── Diagnostics/
│   ├── DiagnosticsStore.swift
│   ├── SessionLog.swift
│   └── PipelineMetrics.swift
│
├── UI/
│   ├── RootView.swift
│   ├── SessionSetupView.swift
│   ├── CaptureView.swift
│   ├── SessionSummaryView.swift
│   ├── UploadQueueView.swift
│   └── Components/
│
├── Models/
│   └── CardEventNet.mlpackage
│
├── MODEL_CONTRACT.md
├── SERVER_CONTRACT.md
│
└── Tests/
    ├── EventPostProcessorTests.swift
    ├── EvidenceFrameBufferTests.swift
    ├── EventPackageAssemblerTests.swift
    ├── PackageStoreTests.swift
    ├── MultipartBodyWriterTests.swift
    ├── UploadCoordinatorTests.swift
    └── ServerContractTests.swift
```

Do not force a rename of every existing PoC type merely to match this tree.

The conceptual boundaries matter more than exact filenames.

---

# 6. Phase 1 — Turn the PoC into the DokoDetector App Shell

## Goal

The app starts as a real capture application while retaining the proven PoC pipeline.

## Tasks

- Rename the visible app from `CardEventProbe` to `DokoDetector`.
- Keep the existing bundle identifier if changing it would create unnecessary signing work during development.
- Make the primary root flow:

```text
No active session
  -> SessionSetupView
  -> CaptureView
  -> SessionSummaryView
```

- Keep Replay and detailed PoC controls under a Debug/developer entry point.
- Move experimental threshold/inference-rate controls out of the primary capture UI.
- Read normal defaults from `AppConfiguration`.

Suggested initial defaults:

```text
inference target:       use validated PoC value
capture resolution:     1920 x 1080 when supported
evidence sample rate:   8 Hz
evidence JPEG quality:  0.85
evidence history:       3.0 s
```

The selected model threshold and post-processing configuration should come from the validated PoC results/configuration rather than being re-guessed here.

## Acceptance criteria

- existing on-device model behavior still works;
- one physical card play still emits one `DetectionEvent`;
- Debug replay remains available;
- production capture flow no longer looks like a model-testing utility.

## Commit

```text
ios: evolve CardEventProbe into DokoDetector shell
```

---

# 7. Phase 2 — Add an Explicit Capture Session

## Goal

Every event package belongs to one durable local session with deterministic ordering.

Create:

```swift
struct CaptureSession: Codable, Sendable {
    let id: UUID
    let startedAtUTC: Date

    var endedAtUTC: Date?

    // Optional human-readable development label.
    var label: String?

    // Four seat slots are useful context even before automatic
    // player attribution exists.
    var seats: [PlayerSeat]
}
```

Suggested seat type:

```swift
struct PlayerSeat: Codable, Sendable, Identifiable {
    let id: UUID
    let seatIndex: Int       // 0...3, clockwise
    var displayName: String?
}
```

Do not require real names.

The server should be able to operate on opaque seat/player IDs.

## Session sequence

`SessionController` owns:

```swift
private var nextEventSequence: Int
```

Every emitted event gets exactly one monotonically increasing sequence:

```text
1, 2, 3, 4, ...
```

The sequence is assigned **before** package assembly.

Persist enough session state that a process restart cannot reuse an already assigned sequence number.

A simple session JSON file is sufficient.

## Session clock

Create a stable logical session timeline.

Internally camera/model events may use `CMTime`.

For serialization use integer milliseconds since the beginning of the capture session:

```text
session_elapsed_ms
```

Also store UTC wall-clock time for coarse correlation:

```text
captured_at_utc
```

Do not use wall-clock time for frame-to-event alignment.

Wall clocks can change.

## Lifecycle

Support:

```text
start session
pause due to camera/app interruption
resume same session
end session
```

Do not silently create a new session when the app briefly backgrounds.

If the app was terminated during an active session, on next launch:

- show that an interrupted session exists;
- allow the user to resume or end it;
- do not merge it silently into a new session.

## Acceptance criteria

- every event has a session UUID;
- every event has a stable sequence number;
- sequence numbers survive app restart;
- frame/event timing is based on one session-relative time domain.

## Commit

```text
ios: add durable capture session lifecycle
```

---

# 8. Phase 3 — Route Camera Frames to Inference and Evidence Capture

## Goal

One AVFoundation camera callback feeds two independent bounded pipelines.

Create `FrameRouter`.

Conceptually:

```swift
final class FrameRouter {
    let inferenceCoordinator: FrameInferenceCoordinator
    let evidenceSampler: EvidenceSampler

    func consume(_ frame: VideoFrame) {
        inferenceCoordinator.offer(frame)
        evidenceSampler.offer(frame)
    }
}
```

Do not perform expensive work in `FrameRouter`.

It only forwards references synchronously to consumers that themselves decide whether to accept the frame.

## Camera output

Continue using the production-friendly PoC behavior:

```swift
videoDataOutput.alwaysDiscardsLateVideoFrames = true
```

Use the capture resolution selected by the PoC, expected initially to be:

```text
1920 x 1080
```

with a fallback if unsupported.

Do not reduce the camera itself to `224 x 224`.

CardEventNet preprocessing still creates its own model input.

Evidence capture must have access to the higher-resolution source frame.

## Pixel buffer lifetime

Do not retain arbitrary `CVPixelBuffer` objects indefinitely.

An evidence frame is retained only after it is converted to compressed image data.

Do not build a raw 1080p pixel-buffer ring containing seconds of frames.

## Acceptance criteria

- inference output is unchanged from the PoC;
- evidence sampling can be enabled/disabled independently;
- blocking evidence encoding cannot create an inference queue;
- the camera delegate remains bounded.

## Commit

```text
ios: split camera frames into inference and evidence paths
```

---

# 9. Phase 4 — Implement the High-Resolution Evidence Sampler

## Goal

Maintain a short compressed ring buffer of source-resolution frames that can later be queried around an event timestamp.

This is not a video recorder.

It is a sparse evidence-frame sampler.

## Starting cadence

Use:

```text
8 evidence frames / second
```

Make this configuration-driven.

Allowed diagnostic range:

```text
4 ... 12 Hz
```

Do not automatically couple it to camera FPS.

## Image format

Encode accepted evidence frames as:

```text
JPEG
quality: 0.85
```

Preserve the full camera frame in v1.

Do **not** crop to the CardEventNet ROI before upload.

The downstream recognizer may need context around sloppy card placement or a future revised ROI.

Package metadata will include the normalized ROI separately.

Later optimization may upload both a full frame and a high-resolution ROI crop, but do not add that complexity now.

## `EvidenceFrame`

```swift
struct EvidenceFrame: Sendable {
    let timestamp: CMTime
    let sessionElapsedMs: Int64

    let jpegData: Data

    let width: Int
    let height: Int
    let orientation: CGImagePropertyOrientation
}
```

If the implementation physically normalizes image orientation before JPEG encoding, record that fact and use a canonical orientation instead.

Do not rotate twice.

## Encoding

Create `EvidenceImageEncoder`.

Encoding must run outside:

- the main actor;
- the camera capture queue;
- the model inference queue.

Use one serial or otherwise strictly bounded encoding path.

Never create a new unstructured task for every camera frame.

`EvidenceSampler` behavior:

```text
camera frame arrives
  -> too soon since last accepted evidence frame?
       yes -> discard
  -> encoder already busy?
       yes -> discard and increment metric
  -> otherwise
       encode
       insert compressed frame into EvidenceFrameBuffer
```

Dropping an occasional evidence sample is acceptable.

Accumulating stale frames is not.

## Performance note

Do not assume 8 Hz JPEG encoding is free.

Measure:

- encode duration;
- actual accepted evidence FPS;
- encoder-busy drop count;
- memory used by the ring;
- thermal behavior.

If 1080p JPEG encoding is too expensive on the test device, first reduce evidence cadence.

Do not reduce the source resolution until measurements show it is needed.

## Acceptance criteria

- app maintains an 8 Hz-ish compressed evidence stream;
- no raw multi-second pixel-buffer history exists;
- camera preview and Core ML inference remain responsive;
- memory stays bounded over a 30-minute session.

## Commit

```text
ios: maintain bounded high-resolution evidence buffer
```

---

# 10. Phase 5 — Implement `EvidenceFrameBuffer`

## Goal

Provide deterministic nearest-frame lookup around an event.

Use a bounded in-memory ring.

Starting retention:

```text
3.0 seconds
```

At 8 Hz this is normally around 24 JPEGs.

Retain based on timestamps, not merely array length.

## Interface

Conceptually:

```swift
actor EvidenceFrameBuffer {
    func append(_ frame: EvidenceFrame)

    func nearestFrame(
        to target: CMTime,
        maximumDistance: CMTime
    ) -> EvidenceFrame?

    func frames(
        around eventTime: CMTime,
        offsets: [CMTime],
        maximumDistance: CMTime
    ) -> [ResolvedEvidenceFrame]
}
```

Exact actor/class choice can vary.

The important property is serialized mutation and bounded memory.

## Target offsets

Use the evidence offsets already defined by the CardEventNet pipeline:

```text
-0.80 s
-0.40 s
-0.10 s
+0.15 s
+0.40 s
+0.70 s
```

These are **targets**, not assumptions that frames exist at exact timestamps.

For every requested offset, record:

```text
target_offset_ms
actual_offset_ms
absolute session timestamp
```

Starting maximum lookup distance:

```text
175 ms
```

This is wide enough for an 8 Hz sampling cadence plus occasional dropped evidence samples without selecting unrelated frames from far away.

If no frame is close enough, record the target as missing.

Do not silently substitute an arbitrarily distant frame.

## Tests

Test at least:

1. exact timestamp;
2. nearest frame before target;
3. nearest frame after target;
4. tie behavior is deterministic;
5. old frames are evicted;
6. lookup never escapes maximum distance;
7. out-of-order append is rejected or normalized explicitly;
8. buffer remains bounded.

## Acceptance criteria

Given synthetic frames and an event timestamp, the exact expected nearest evidence set is returned.

## Commit

```text
ios: resolve event-relative frames from evidence ring
```

---

# 11. Phase 6 — Assemble an Event Evidence Package

## Goal

A `DetectionEvent` becomes one immutable package after enough future evidence has arrived.

Do not immediately finalize a package when the event fires, because some requested evidence offsets are in the future.

## Assembly lifecycle

When `EventPostProcessor` emits:

```swift
DetectionEvent
```

create:

```swift
PendingEventPackage
```

containing:

- package UUID;
- session UUID;
- event sequence;
- event timestamp;
- event peak probability;
- event emission timestamp;
- model metadata snapshot;
- current ROI;
- optional current player/turn context.

Then wait until at least:

```text
event timestamp + 0.90 s
```

has passed on the camera/session timeline.

This provides enough time for the `+0.70 s` target and one evidence-sampling interval.

At that point query `EvidenceFrameBuffer` for all configured target offsets and finalize the package.

## Why 0.90 seconds

Package assembly is intentionally delayed by less than one second.

Inference and further event detection continue normally during that delay.

Do not block the UI or event pipeline while a package waits for future evidence.

## Multiple pending events

The assembler must support more than one pending event.

Do not assume that two cards can never be played close together.

Use an ordered collection keyed by package UUID/event time.

Each new evidence frame may make one or more pending packages eligible for finalization.

## Incomplete packages

A detection event must not disappear merely because evidence capture was imperfect.

If one or more target frames are missing:

- finalize the package anyway;
- include explicit missing-target metadata;
- set:

```text
evidence_complete = false
```

If no images at all are available, still persist a metadata-only package.

That case is a serious diagnostic signal, but silent event loss is worse.

## `EvidencePackage`

The in-memory package should be immutable after finalization.

Conceptually:

```swift
struct EvidencePackage: Sendable {
    let manifest: EvidencePackageManifest
    let frames: [PackagedEvidenceFrame]
}
```

Do not retain original `CVPixelBuffer`s.

## Acceptance criteria

- every `DetectionEvent` creates exactly one package UUID;
- package finalization does not block detection;
- future frames are included;
- missing evidence is represented explicitly;
- multiple close events finalize independently.

## Commit

```text
ios: assemble immutable evidence packages from card events
```

---

# 12. Phase 7 — Define the Package Manifest Schema

## Goal

Create a stable versioned wire model for the next server implementation.

Create:

```text
SERVER_CONTRACT.md
```

and Codable Swift models matching it.

Use:

```text
schema_version = 1
```

Do not serialize Swift implementation details.

Use explicit JSON names.

## Required manifest shape

Use approximately:

```json
{
  "schema_version": 1,
  "package_id": "6D8E87F1-...",
  "session": {
    "session_id": "F350D124-...",
    "event_sequence": 12,
    "started_at_utc": "2026-08-19T20:10:12.481Z"
  },
  "event": {
    "event_time_ms": 73625,
    "emitted_at_ms": 73875,
    "peak_probability": 0.982,
    "evidence_complete": true
  },
  "model": {
    "name": "CardEventNet",
    "version": "v1",
    "model_sha256": "...",
    "inference_target_hz": 8.0
  },
  "post_processing": {
    "high_threshold": 0.75,
    "low_threshold": 0.35,
    "minimum_positive_hits": 2,
    "cooldown_ms": 600
  },
  "camera": {
    "width": 1920,
    "height": 1080,
    "orientation": "up"
  },
  "roi": {
    "x": 0.12,
    "y": 0.18,
    "width": 0.72,
    "height": 0.63
  },
  "player_context": {
    "seat_index": 2,
    "player_id": "optional-opaque-id"
  },
  "frames": [
    {
      "part_name": "frame_00",
      "filename": "frame_00.jpg",
      "target_offset_ms": -800,
      "actual_offset_ms": -764,
      "session_elapsed_ms": 72861,
      "width": 1920,
      "height": 1080,
      "sha256": "..."
    }
  ],
  "missing_frame_targets_ms": [],
  "score_trace": [
    {
      "offset_ms": -500,
      "probability": 0.12
    },
    {
      "offset_ms": -375,
      "probability": 0.31
    },
    {
      "offset_ms": -250,
      "probability": 0.81
    }
  ],
  "client": {
    "app_version": "1.0",
    "build": "1",
    "ios_version": "..."
  }
}
```

Fields that are not available must be omitted or explicitly nullable according to `SERVER_CONTRACT.md`.

Do not send fake/default player context merely to satisfy the shape.

## Event time versus emitted time

These are deliberately separate:

```text
event_time_ms
```

is the logical timestamp selected by the event detector/post-processor.

```text
emitted_at_ms
```

is when the app actually emitted the discrete event.

The difference is useful for debugging detection latency.

## Score trace

Keep a small prediction history around each event.

Create `PredictionHistory` with bounded retention, for example:

```text
2.5 seconds
```

Attach raw CardEventNet probabilities around the event when available.

This is diagnostic metadata, not an input required by the later card recognizer.

Do not attach thousands of predictions.

## Model identity

Compute the packaged model's SHA-256 once at startup.

Do not hash it for every event.

Include enough identity that a server-side failure can later be correlated with the exact Core ML model.

## Manifest encoding

Use:

```swift
JSONEncoder
```

with:

```text
UTF-8
ISO-8601 UTC dates
stable documented field names
```

Pretty printing is optional for local inspection but must not be required.

## Contract tests

Add a checked-in JSON fixture:

```text
Tests/Fixtures/evidence-package-v1.json
```

Decode it into the Swift model and re-encode it.

Also verify required field names.

This fixture should become an input to the next server implementation.

## Acceptance criteria

`SERVER_CONTRACT.md` alone is sufficient for a backend engineer to implement the receiving endpoint without reading Swift code.

## Commit

```text
ios: define versioned evidence package contract
```

---

# 13. Phase 8 — Add Optional Player / Turn Context Without Game Logic

## Goal

Allow later game-state knowledge to travel with a package without coupling this app phase to Doppelkopf rules.

Create:

```swift
struct PlayerContext: Codable, Sendable {
    let seatIndex: Int?
    let playerId: UUID?
}
```

and a tiny provider boundary:

```swift
protocol PlayerContextProvider: Sendable {
    func contextForNextEvent() async -> PlayerContext?
}
```

For this phase, use one simple implementation:

```text
NoPlayerContextProvider
```

or, if session setup already allows selecting a current seat for development, a manual provider.

Do **not** implement:

- trick winner calculation;
- card legality;
- turn advancement based on recognized cards;
- server-driven game state;
- automatic player detection from the image.

The important design property is merely that adding player context later does not require redesigning `EvidencePackage`.

## Acceptance criteria

- package schema supports player context;
- current implementation works when it is absent;
- no Doppelkopf rule engine is added.

## Commit

```text
ios: reserve player context boundary for later game state
```

---

# 14. Phase 9 — Persist Packages Atomically

## Goal

Once a package is finalized, killing the app must not lose it.

Use Application Support, not temporary storage.

Suggested structure:

```text
Application Support/
└── DokoDetector/
    ├── sessions/
    │   └── <session-id>.json
    │
    ├── packages/
    │   ├── staging/
    │   ├── queued/
    │   ├── failed/
    │   └── corrupt/
    │
    └── receipts/
```

Each package directory:

```text
queued/<package-id>/
├── manifest.json
└── frames/
    ├── frame_00.jpg
    ├── frame_01.jpg
    ├── frame_02.jpg
    └── ...
```

Do not make a ZIP archive.

There is no benefit yet that justifies adding archive-format complexity.

## Atomic write protocol

For a new package:

1. create:
   ```text
   staging/<package-id>/
   ```
2. write every JPEG using atomic file writes where practical;
3. compute and record frame SHA-256 hashes;
4. write `manifest.json`;
5. validate that manifest references match the files;
6. rename/move the directory atomically into:
   ```text
   queued/<package-id>/
   ```

Only packages under `queued/` are uploadable.

The filesystem is the initial source of truth for queue state.

Do not maintain a separate queue database that can disagree with the files.

## Startup recovery

At app startup:

1. enumerate `queued/`;
2. enumerate `staging/`;
3. validate queued manifests;
4. reconcile queue state with background URLSession tasks;
5. attempt recovery of complete staging packages;
6. move invalid unrecoverable staging data to `corrupt/`;
7. surface corruption in diagnostics.

Never simply delete unexplained staging data on launch.

## File protection

Use normal application file protection appropriate for user-generated app data.

Do not weaken protection to make uploads easier without a demonstrated requirement.

## Acceptance criteria

After finalization, force-terminating and relaunching the app leaves the package queued and uploadable.

## Commit

```text
ios: persist evidence packages as atomic filesystem queue
```

---

# 15. Phase 10 — Define the Hypothetical HTTP Server Contract

## Goal

Implement the client against one exact endpoint even though the server does not yet exist.

Use:

```http
PUT /v1/evidence-packages/{package_id}
```

The client-generated `package_id` is the resource identifier.

`PUT` is intentional: retrying the same package URL should be idempotent.

The later server must enforce:

```text
same package_id + same content -> accepted as duplicate/idempotent retry
same package_id + conflicting content -> HTTP 409
```

## Request content type

Use:

```text
multipart/form-data
```

Parts:

```text
manifest
frame_00
frame_01
...
```

### Manifest part

```http
Content-Disposition: form-data; name="manifest"
Content-Type: application/json
```

### Frame part

Example:

```http
Content-Disposition: form-data; name="frame_00"; filename="frame_00.jpg"
Content-Type: image/jpeg
```

The part name and filename must match the manifest.

## Request headers

Use:

```text
Accept: application/json
X-Doko-Schema-Version: 1
```

Authentication is intentionally not specified yet.

Reserve an abstraction for request authorization, but do not invent tokens or user accounts.

## Successful response

The next server should return one of:

```text
201 Created
200 OK
202 Accepted
```

with:

```json
{
  "package_id": "6D8E87F1-...",
  "status": "accepted",
  "received_at": "2026-08-19T20:11:27.004Z"
}
```

The iOS client only requires:

- successful HTTP status;
- matching `package_id`;
- parseable response body.

Do not require recognition results synchronously in this phase.

## Error policy

Treat:

```text
408
429
5xx
network transport errors
```

as retryable.

Treat most other `4xx` as permanent package/client failures.

Special handling:

```text
409
```

means either:

- duplicate/conflicting package identity;
- inspect response;
- do not retry forever.

When authentication is implemented later:

```text
401 / 403
```

must become blocked-on-auth rather than a package corruption state.

## `SERVER_CONTRACT.md`

Document:

- endpoint;
- method;
- multipart field names;
- complete manifest schema;
- maximum package assumptions;
- successful response;
- idempotency behavior;
- HTTP error semantics;
- example request manifest;
- example response.

The next backend implementation plan should start from this file.

## Acceptance criteria

The iOS networking code can be integration-tested against a local stub that implements exactly this contract.

## Commit

```text
ios: specify evidence upload HTTP contract
```

---

# 16. Phase 11 — Implement Multipart Body Generation as a File

## Goal

Generate a complete upload body on disk so it can be handed to a background `URLSessionUploadTask`.

Create:

```swift
struct MultipartBodyWriter {
    func writeBody(
        package: StoredPackage,
        boundary: String,
        destination: URL
    ) throws
}
```

The writer must stream/copy package files into the body file.

Do not load all evidence JPEGs plus the complete multipart body into memory simultaneously.

Suggested generated location:

```text
Library/Caches/DokoDetectorUploads/<package-id>.multipart
```

This generated file is disposable because the canonical package still lives in `queued/`.

## Required correctness

Test:

- CRLF placement;
- opening boundary;
- closing boundary;
- manifest headers;
- image headers;
- image bytes unchanged;
- all manifest frame entries represented exactly once.

Use deterministic test fixtures.

Do not test multipart correctness only by pointing at the eventual server.

## Cleanup

Delete generated multipart files after:

- successful upload;
- permanent failure where no retry will occur;
- regeneration on next attempt.

If the app crashes, stale multipart files may be removed after reconciling active URLSession tasks.

Do not delete a multipart file that may still be used by an active background upload task until reconciliation proves it is safe.

## Acceptance criteria

A test parser or local stub can reconstruct the original manifest and JPEG bytes exactly.

## Commit

```text
ios: generate file-backed multipart evidence payloads
```

---

# 17. Phase 12 — Implement `ServerClient`

## Goal

Keep HTTP mechanics isolated from queue policy.

Define:

```swift
protocol ServerClient: Sendable {
    func prepareUpload(
        package: StoredPackage
    ) async throws -> PreparedUpload
}
```

`PreparedUpload` should contain enough information for `UploadCoordinator` to create a URLSession upload task:

```swift
struct PreparedUpload {
    let request: URLRequest
    let bodyFileURL: URL
    let packageID: UUID
}
```

`HTTPServerClient` owns:

- base URL;
- endpoint construction;
- request headers;
- multipart body preparation;
- response decoding helpers.

It does **not** own:

- retry policy;
- package deletion;
- camera state;
- event state.

## Server configuration

For Debug:

```text
server base URL can be supplied through a configuration file
or Xcode scheme/environment setting
```

For Release:

```text
use an HTTPS configured endpoint
```

Do not hard-code a developer laptop IP into source code.

Do not disable App Transport Security globally.

## Local development

Support a local/stub server configuration for device testing.

If plain HTTP is temporarily needed for a specific development host, use the narrowest possible Debug-only ATS exception.

Do not ship broad arbitrary-load exceptions.

## Acceptance criteria

Given a stored package, `HTTPServerClient` deterministically prepares the expected request and body file.

## Commit

```text
ios: add HTTP client for evidence package contract
```

---

# 18. Phase 13 — Implement Durable Background Uploads

## Goal

Queued packages continue uploading independently from the live capture pipeline and can complete while the app is suspended.

Use a background URL session:

```swift
URLSessionConfiguration.background(
    withIdentifier: "eu.sparfeld.DokoDetector.evidence-upload"
)
```

Use a stable identifier appropriate to the actual bundle ID.

Create file-backed upload tasks:

```swift
session.uploadTask(
    with: request,
    fromFile: bodyFileURL
)
```

Set:

```swift
task.taskDescription = packageID.uuidString
```

so tasks can be reconciled after relaunch.

## Background session delegate

Create one long-lived delegate object:

```text
BackgroundSessionDelegate
```

It must receive:

- task completion;
- HTTP response;
- transport error;
- background session completion events.

Bridge those events back into `UploadCoordinator` using package IDs.

Do not build the core upload state machine around closure-only foreground APIs.

## Queue policy

Starting behavior:

```text
maximum active package uploads: 1
```

One in-flight package is sufficient initially and naturally keeps session packages close to order.

Do not make server correctness depend on arrival order.

The manifest sequence number is authoritative.

If real measurements later show upload throughput cannot keep pace with gameplay, increase to 2.

Do not start with high concurrency.

## Cellular

Expose one user preference:

```text
Upload over cellular
default: enabled
```

The purpose of the application is near-live cloud processing, so Wi-Fi-only should not be the default.

When disabled, retain packages locally until an allowed network is available.

## Connectivity

Prefer normal `URLSession` behavior with:

```swift
waitsForConnectivity = true
```

before adding an explicit network-monitor state machine.

Use `NWPathMonitor` only if the UI needs network status or testing demonstrates it materially improves retry behavior.

## Relaunch reconciliation

On launch:

1. recreate the background URLSession with the same identifier;
2. enumerate active tasks;
3. map `taskDescription` to package IDs;
4. enumerate locally queued packages;
5. do not schedule a duplicate task for a package that already has one;
6. schedule eligible queued packages that do not have an active task.

This reconciliation is mandatory.

## Acceptance criteria

- package uploads from a file-backed background task;
- leaving the app does not cancel an active upload;
- relaunch does not duplicate active tasks;
- a queued package remains recoverable after termination.

## Commit

```text
ios: upload queued packages with background URLSession
```

---

# 19. Phase 14 — Retry and Failure State Machine

## Goal

Make package state explicit and observable.

Use these conceptual states:

```text
assembling
queued
preparingUpload
uploading
retryWaiting
blocked
permanentFailure
acknowledged
```

Not every state needs a directory.

The durable source of truth should remain simple.

A useful approach is:

```text
queued/<id>/manifest.json
queued/<id>/state.json
```

with images beside it.

Use atomic writes for `state.json`.

## Retryable failures

Examples:

```text
network disconnected
connection timeout
408
429
500
502
503
504
```

Persist:

```text
attempt_count
last_attempt_at
last_error_category
next_attempt_not_before
```

Use bounded exponential backoff with jitter.

Example baseline:

```text
2 s
10 s
30 s
2 min
10 min
30 min
```

Do not depend on an exact timer firing while the application is suspended.

`next_attempt_not_before` means "do not intentionally retry earlier than this".

When the app is active or the background machinery gives another execution opportunity, retry eligible packages.

## Permanent failures

Examples:

```text
malformed request according to server
unsupported schema
payload rejected
conflicting package ID
```

Move/logically mark these as permanent failures.

Do not delete their evidence automatically.

Expose them in the UI so a developer can inspect/export them.

## Success

On a valid success response:

1. verify returned `package_id`;
2. persist a tiny upload receipt;
3. mark package acknowledged;
4. delete JPEG/package payload;
5. delete disposable multipart body;
6. retain the receipt for diagnostics.

Suggested receipt:

```json
{
  "package_id": "...",
  "session_id": "...",
  "event_sequence": 12,
  "acknowledged_at_utc": "...",
  "server_received_at": "...",
  "attempt_count": 2
}
```

Retain receipts for a modest time, for example 7 days, or until an explicit diagnostics cleanup.

Do not retain uploaded evidence images by default.

## Acceptance criteria

- transient failures retry;
- malformed packages do not retry forever;
- successful packages free their image storage;
- no acknowledged package is re-uploaded after relaunch.

## Commit

```text
ios: make evidence upload retries durable and observable
```

---

# 20. Phase 15 — Production Capture UI

## Goal

The user can run a complete table session without model-development controls.

## `SessionSetupView`

Keep it small.

Required:

- Start Session button.
- Optional session label.
- Optional four player/seat labels.
- server status/configuration visible only in developer builds unless needed.

Do not require account creation in this phase.

## `CaptureView`

Primary view:

```text
+--------------------------------------+
| camera preview                       |
|                                      |
|              EVENT                   |  <- brief flash
|                                      |
+--------------------------------------+

Session       18:24
Events        17
Uploads       15 sent / 1 uploading / 1 queued
Connection    Online
Model         Running
```

Controls:

```text
End Session
```

Optional compact developer disclosure:

```text
raw score
inference latency
evidence encode FPS
evidence drops
queue disk size
last upload error
```

Do not expose threshold sliders in the normal UI.

## Event feedback

When an event is emitted:

- flash a small overlay;
- increment event count immediately.

Do not wait for:

- evidence finalization;
- persistence;
- upload;
- server response.

These are separate pipeline stages.

## Upload status

The user should be able to distinguish:

```text
captured
queued
uploading
uploaded
failed
```

But do not clutter the camera view with one row per event.

A compact aggregate is enough.

## `SessionSummaryView`

After ending:

Show:

```text
Events detected:      48
Uploaded:             46
Still queued:          2
Permanent failures:    0
```

Ending a capture session must **not** cancel queued uploads.

Queued uploads continue after the session ends.

## Acceptance criteria

A non-developer can start a session, leave the camera running, end it, and understand whether all event packages reached the server.

## Commit

```text
ios: add production session capture and upload status UI
```

---

# 21. Phase 16 — Storage Limits and Retention

## Goal

Offline use cannot fill device storage without bound.

## Package size metrics

Track:

```text
individual JPEG bytes
package total bytes
queued bytes
oldest queued package age
```

Display these in developer diagnostics.

## Soft warning

Starting soft threshold:

```text
500 MB queued evidence
```

At that point show a visible warning.

Do not stop capturing automatically at the soft threshold.

## Hard guard

Starting hard threshold:

```text
1.5 GB queued evidence
```

or a lower value if device free-space checks indicate danger.

Before finalizing a package, check that sufficient application/device capacity remains.

If storage is critically low:

- continue CardEventNet detection if possible;
- emit an explicit capture-storage error;
- persist metadata-only event information if feasible;
- do not crash;
- do not silently pretend the evidence package was complete.

Use actual available-capacity APIs rather than assuming the hard byte threshold alone is safe.

## Retention

Default:

```text
acknowledged package images: delete immediately
receipts: retain ~7 days
unacknowledged packages: retain until uploaded or explicitly deleted
permanent failures: retain until user/developer action
```

Do not build automatic age-based deletion of unacknowledged packages in this phase.

## Acceptance criteria

A long offline session produces warnings rather than uncontrolled storage growth or silent data loss.

## Commit

```text
ios: bound evidence storage and clean acknowledged payloads
```

---

# 22. Phase 17 — App / Camera Interruption Behavior

## Goal

Make lifecycle behavior explicit.

## App moves to background

Camera capture stops according to normal iOS camera lifecycle.

Before stopping:

- keep already finalized packages;
- allow already-created background upload tasks to continue;
- finalize pending event packages only if enough evidence is already available;
- otherwise persist the event as an incomplete package.

Do not pretend future frames can be collected while camera capture is suspended.

## App returns foreground

- restore camera session;
- reset `CardEventModelRunner`;
- reset/re-arm `EventPostProcessor` appropriately;
- restart evidence sampling with an empty ring;
- continue the same logical `CaptureSession` unless the user ended it.

Avoid a false event caused purely by restarting temporal model context.

## Camera interruption

Examples:

```text
phone call/system camera interruption
camera unavailable
capture runtime error
```

Show a visible paused/error state.

Packages already queued remain independent from camera health.

## Acceptance criteria

Backgrounding and returning cannot:

- create duplicate capture sessions;
- duplicate an upload;
- accidentally reuse stale temporal model frames;
- create evidence timestamps from before/after the interruption as if they were continuous.

## Commit

```text
ios: handle capture interruptions without losing upload state
```

---

# 23. Phase 18 — Diagnostics and Observability

## Goal

When a game fails, there is enough local information to determine which pipeline stage failed.

Track session-level metrics:

```text
camera frames received
camera frames dropped by AVFoundation if available

inference frames accepted
inference sampling skips
inference busy drops
predictions produced
mean/recent inference latency

events emitted

evidence frames requested
evidence frames encoded
evidence encoder busy drops
mean/recent JPEG encode latency
evidence buffer bytes

packages assembled
packages incomplete
packages persisted
package persistence failures

uploads scheduled
uploads succeeded
uploads retryable-failed
uploads permanently failed
queued bytes
```

## Structured log

Keep a small text/JSON-lines session log under developer diagnostics.

Do not log JPEG bytes.

Do not log personal player names unnecessarily.

Useful log events:

```text
session_started
camera_started
camera_interrupted
event_emitted
package_finalized
package_persisted
upload_started
upload_retry
upload_acknowledged
upload_permanent_failure
session_ended
```

Each should carry:

```text
session_id
package_id where applicable
event_sequence where applicable
session_elapsed_ms where applicable
```

## Export

Retain the existing diagnostics export capability in developer builds.

Allow exporting:

- session log;
- package manifests;
- receipts;
- selected failed package payloads.

Do not make diagnostics export part of normal gameplay UX.

## Acceptance criteria

For an event visible to the tester, diagnostics can answer:

```text
Did CardEventNet emit it?
Did evidence finalize?
Was it persisted?
Was an upload task created?
What did the server return?
```

## Commit

```text
ios: add end-to-end capture upload diagnostics
```

---

# 24. Phase 19 — Security and Privacy Baseline

This phase does not implement user accounts, but do not create avoidable security debt.

## Network

Production server configuration must use HTTPS.

Do not globally disable ATS.

## Local data

Evidence frames are temporary operational data.

Default behavior:

```text
keep until server acknowledgement
then delete
```

Do not place evidence in:

- Photos;
- Documents exposed to Files;
- shared pasteboards.

Keep it in application-managed storage.

## Manifest data

Use opaque IDs whenever possible.

Player display names are not necessary for card recognition.

If display names exist in UI, do not copy them into every package unless the server actually needs them.

Prefer:

```text
player_id
seat_index
```

over:

```text
full_name
```

## Logs

Never log:

- request body bytes;
- JPEG data;
- future auth secrets.

When authentication is added later, redact authorization headers.

## Acceptance criteria

Normal successful operation does not leave a long-lived archive of game images on the phone.

## Commit

```text
ios: establish evidence privacy and transport baseline
```

---

# 25. Phase 20 — Unit Tests

At minimum implement the following.

## `EvidenceFrameBufferTests`

- exact nearest frame;
- nearest earlier/later selection;
- maximum-distance cutoff;
- deterministic tie behavior;
- timestamp eviction;
- bounded retention.

## `EventPackageAssemblerTests`

- event waits for future evidence;
- package resolves all six target offsets;
- missing frame target is explicit;
- metadata-only package can finalize;
- two pending events finalize correctly;
- session/event sequence preserved;
- model metadata snapshot preserved.

## `PackageStoreTests`

Use a temporary directory.

Test:

- atomic staging -> queued promotion;
- valid package reload;
- incomplete staging recovery;
- corrupt package detection;
- package survives new `PackageStore` instance;
- acknowledged payload deletion;
- receipt retention.

## `MultipartBodyWriterTests`

- manifest part exists exactly once;
- every frame exists exactly once;
- bytes round-trip;
- proper closing boundary;
- no complete-body in-memory requirement.

## `UploadCoordinatorTests`

Use a fake `ServerClient` / fake task adapter.

Test:

- only queued package starts;
- max concurrency enforced;
- active task prevents duplicate scheduling;
- retryable status schedules retry;
- permanent status stops retry;
- success creates receipt and removes payload;
- launch reconciliation;
- event sequence not used as sole identity.

## Manifest contract tests

- decode/encode checked-in v1 fixture;
- field names remain stable;
- schema version required;
- frame hashes are required for present frames;
- package ID and path package ID must match.

## Existing tests

Keep:

- `EventPostProcessorTests`;
- model contract smoke tests;
- replay regression where practical.

Do not weaken PoC model tests to make the networking work easier.

---

# 26. Phase 21 — Local Stub Server for iOS Development

The production backend is explicitly the **next project step**, but the iOS app needs something deterministic to test against.

Do not build the real server here.

Create the smallest possible development stub, either:

```text
a tiny script under tools/stub-server/
```

or use an existing test server inside automated tests.

If a script is created, keep it intentionally disposable.

Required behavior only:

```text
PUT /v1/evidence-packages/{package_id}

parse multipart
validate manifest.package_id
count frames
return accepted response
```

Developer switches should make the stub return:

```text
201 success
429 retryable
500 retryable
400 permanent
409 conflict
slow response
connection drop
```

Do not implement:

- card recognition;
- database;
- authentication;
- sessions table;
- queues;
- cloud deployment;
- game state.

The real backend plan must not evolve accidentally inside this stub.

## Acceptance criteria

The physical iPhone can complete an end-to-end package upload to the development stub.

## Commit

```text
dev: add minimal evidence upload stub for ios testing
```

---

# 27. Phase 22 — End-to-End Physical Device Validation

## Test 1 — ordinary online game-like capture

Run at least:

```text
15 minutes
real table geometry
real lighting
normal player movement
network available
```

Verify:

- CardEventNet remains responsive;
- events create packages;
- packages upload;
- queue normally remains near zero;
- no thermal collapse;
- no unbounded memory growth.

## Test 2 — network disappears

During capture:

1. start online;
2. disable Wi-Fi/cellular;
3. play several cards;
4. verify queue grows;
5. restore connectivity;
6. verify every queued package uploads once.

Record package IDs before/after.

## Test 3 — process termination with queued packages

1. disable network;
2. create at least 3 events;
3. confirm 3 queued packages;
4. terminate app;
5. relaunch;
6. restore network;
7. verify the same 3 package IDs upload.

## Test 4 — background during active upload

1. create a deliberately slow server response;
2. begin upload;
3. background the app;
4. verify background upload behavior;
5. return/relaunch;
6. verify final state reconciles correctly.

## Test 5 — camera interruption

1. start session;
2. generate an event;
3. background/interruption before all future evidence offsets exist;
4. verify event becomes an incomplete package rather than disappearing;
5. resume;
6. verify inference state is reset cleanly.

## Test 6 — server failures

Exercise:

```text
429
500
400
409
```

Verify expected retry/permanent behavior.

## Test 7 — long thermal/storage run

Run:

```text
30–60 minutes
```

Track:

```text
memory
thermal state
evidence encode time
inference time
queued bytes
UI responsiveness
```

## Acceptance criteria

No test produces:

- duplicate package IDs at the server;
- silently missing locally emitted events;
- an ever-growing in-memory work queue;
- unrecoverable queue state after relaunch.

---

# 28. Explicit Out of Scope

Do **not** implement in this phase:

- cloud card recognition;
- Qwen or other vision model calls;
- ChatGPT/OpenAI calls;
- Doppelkopf rules;
- game-state reconciliation;
- automatic trick winner detection;
- automatic turn advancement;
- recognition-result push notifications;
- WebSockets;
- server-sent events;
- user accounts;
- authentication;
- cloud persistence;
- real backend deployment;
- analytics SDKs;
- crash-reporting SDKs;
- App Store onboarding;
- subscriptions/payments;
- multi-device session coordination;
- full-game video recording;
- uploading continuous video;
- local card rank/suit recognition;
- object detection or segmentation.

The server implementation is intentionally the next step.

---

# 29. Concurrency Rules

Keep concurrency deliberately boring.

## Main actor

Only:

- SwiftUI state;
- UI-facing observable state;
- lifecycle coordination that must touch UI.

## Capture queue

Only:

- AVFoundation sample callbacks;
- timestamp normalization;
- extremely cheap routing.

## Inference path

- one bounded serial execution path;
- at most one inference in flight;
- model runner state confined there.

## Evidence encoding path

- one bounded serial path;
- at most one JPEG encode in flight initially;
- skipped frame rather than unbounded queue.

## Evidence/package actor or serial owner

Own:

- compressed frame ring;
- pending package assemblies;
- package finalization.

## Persistence

Serialize package mutations enough that:

```text
staging -> queued -> acknowledged
```

cannot race.

## Upload coordinator

One owner for:

- mapping package IDs to URLSession tasks;
- retry state;
- task reconciliation.

Do not create independent upload tasks from views.

Do not let SwiftUI views mutate package files directly.

---

# 30. Error Handling Rules

Never use `try!`.

Do not use broad empty `catch` blocks.

User-visible fatal capture errors:

```text
camera unavailable
camera permission denied
Core ML model unavailable
model contract incompatible
cannot write package storage
critically low device storage
```

Non-fatal operational errors:

```text
network unavailable
server temporarily unavailable
one evidence frame missed
upload retry scheduled
```

These should not stop CardEventNet capture.

Permanent package failure:

```text
package persists
failure visible
capture may continue
```

The app must distinguish:

```text
capture failure
evidence degradation
persistence failure
upload failure
server rejection
```

Do not collapse all of them into "Something went wrong."

---

# 31. Configuration

Create one central typed configuration.

Conceptually:

```swift
struct AppConfiguration {
    struct Inference {
        let targetHz: Double
    }

    struct Evidence {
        let targetHz: Double
        let jpegQuality: Double
        let historySeconds: Double
        let targetOffsetsMs: [Int]
        let maximumLookupDistanceMs: Int
        let finalizationDelayMs: Int
    }

    struct Upload {
        let serverBaseURL: URL
        let allowsCellular: Bool
        let maximumConcurrentUploads: Int
    }

    struct Storage {
        let softQueueBytes: Int64
        let hardQueueBytes: Int64
    }
}
```

Starting values:

```text
Inference:
  use validated PoC value

Evidence:
  targetHz:                 8
  jpegQuality:              0.85
  historySeconds:           3.0
  targetOffsetsMs:          [-800, -400, -100, 150, 400, 700]
  maximumLookupDistanceMs:  175
  finalizationDelayMs:      900

Upload:
  allowsCellular:           true
  maximumConcurrentUploads: 1

Storage:
  softQueueBytes:           500 MB
  hardQueueBytes:           1.5 GB
```

Do not scatter these constants across views and actors.

---

# 32. Definition of Done

This phase is complete when all of the following are true.

## Capture

- physical iPhone camera works in the real table setup;
- CardEventNet runs continuously on-device;
- one real card play normally produces one `DetectionEvent`.

## Evidence

- every emitted event receives a package UUID and sequence;
- package contains the configured high-resolution frame set when available;
- future frames are actually included;
- frame timestamps and offsets are recorded;
- missing evidence is explicit.

## Persistence

- finalized package is on disk before upload starts;
- app termination cannot lose a queued package;
- queue is reconstructed on launch.

## Networking

- packages are uploaded as file-backed multipart requests;
- requests target:
  ```text
  PUT /v1/evidence-packages/{package_id}
  ```
- retry semantics work;
- duplicate scheduling across relaunch is prevented;
- successful acknowledgement deletes image payload and leaves a receipt.

## Lifecycle

- backgrounding does not destroy queued uploads;
- returning to the camera resets temporal inference correctly;
- ending a game does not cancel remaining uploads.

## Diagnostics

For every event sequence, it is possible to determine:

```text
event emitted?
package assembled?
evidence complete?
package persisted?
upload attempted?
server acknowledged?
```

## Contract

`SERVER_CONTRACT.md` exists and contains everything required for the next backend implementation.

---

# 33. Recommended Implementation Order

Do the work in exactly this dependency order unless the repository forces a small adjustment:

```text
1.  Production app shell
2.  CaptureSession + SessionClock
3.  FrameRouter
4.  EvidenceImageEncoder + EvidenceSampler
5.  EvidenceFrameBuffer
6.  PredictionHistory
7.  EventPackageAssembler
8.  EvidencePackage manifest v1
9.  PackageStore
10. SERVER_CONTRACT.md
11. MultipartBodyWriter
12. ServerClient
13. Background URLSession wiring
14. UploadCoordinator + retry state
15. Production capture UI
16. Lifecycle/relaunch reconciliation
17. Diagnostics/storage limits
18. Stub-server integration
19. Physical-device end-to-end validation
```

Do not start with networking.

The critical path is:

```text
DetectionEvent
  -> correct evidence
  -> durable package
```

Only after that works should upload behavior be added.

---

# 34. Commit Sequence

A reasonable commit sequence is:

```text
ios: evolve CardEventProbe into DokoDetector shell
ios: add durable capture session lifecycle
ios: split camera frames into inference and evidence paths
ios: maintain bounded high-resolution evidence buffer
ios: resolve event-relative frames from evidence ring
ios: assemble immutable evidence packages from card events
ios: define versioned evidence package contract
ios: reserve player context boundary for later game state
ios: persist evidence packages as atomic filesystem queue
ios: specify evidence upload HTTP contract
ios: generate file-backed multipart evidence payloads
ios: add HTTP client for evidence package contract
ios: upload queued packages with background URLSession
ios: make evidence upload retries durable and observable
ios: add production session capture and upload status UI
ios: bound evidence storage and clean acknowledged payloads
ios: handle capture interruptions without losing upload state
ios: add end-to-end capture upload diagnostics
ios: establish evidence privacy and transport baseline
dev: add minimal evidence upload stub for ios testing
test: validate physical-device evidence upload pipeline
```

Each commit should build.

Prefer tests in the same commit as the behavior they cover.

---

# 35. Handoff to the Following Server Phase

At the end of this implementation, the repository must contain these server-facing artifacts:

```text
SERVER_CONTRACT.md
Tests/Fixtures/evidence-package-v1.json
at least one anonymized/sample multipart fixture or fixture generator
```

The next server implementation can then be specified around:

```text
receive versioned evidence package
validate manifest and frame hashes
persist original evidence
deduplicate by package_id
respond quickly with accepted acknowledgement
enqueue asynchronous card recognition
process packages in session/event sequence
later return recognized card + confidence + game-state result
```

Do not implement those backend responsibilities in the iOS repository.

The boundary between phases should be clean:

```text
THIS PHASE ENDS:
HTTP server has durably acknowledged evidence package.

NEXT PHASE BEGINS:
Server validates, stores, recognizes, and reasons about the package.
```
