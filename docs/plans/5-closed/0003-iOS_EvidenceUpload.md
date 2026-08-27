# DokoDetector iOS Evidence Upload — Backend-Handoff PoC

## Plan status

- **Summary:** Produce a real evidence package and freeze the server contract
- **Status:** Closed
- **Closure reason:** Complete
- **Reviewed:** 2026-08-26 against report 0015 and the current iOS code
- **Implemented through:** Commit `60af200` and the current iOS evidence-package tests
- **Next:** Plan 0016 connects the completed client package writer to the local backend

## 1. Outcome

Extend `CardEventProbe` only far enough to unblock backend development.

At the end of this plan, a saved replay can:

```text
full camera frames
  -> CardEventNet transition V2
  -> causal card-event decoder
  -> full-frame evidence samples
  -> evidence package on disk
  -> file-backed multipart request
```

The repository also contains one versioned HTTP contract and shared fixtures. Plan 0004 can then
implement the backend without reading Swift code or waiting for production iOS behavior.

This plan does not make the app production-ready. Plans 0016 and 0017 contain that work.

## 2. Fixed decisions

### 2.1 Full frames only

There is no configured region of interest (ROI).

Both paths start with the complete oriented camera frame:

- CardEventNet applies `full_frame_letterbox_v1` to the complete frame.
- Evidence capture encodes the complete frame as JPEG.

Letterboxing is not an ROI. It preserves the frame aspect ratio, resizes the complete frame, and
adds black padding to make the `224 x 224` model input.

The current app still contains the legacy ROI design. This plan must remove it:

- remove `NormalizedROI` and ROI validation from `ModelPreprocessing`;
- change `LetterboxGeometry` to use the complete oriented frame size;
- remove the `roi` property, initializer arguments, `setROI`, and `roiNotConfigured` failure from
  `CoreMLCardEventModelRunner`;
- change `CardEventTensorBuilder.makeInput` to accept only the frames;
- replace the ROI unit tests with full-frame letterbox tests;
- remove ROI controls or defaults from the app UI and configuration.

Do not retain a full-frame ROI value such as `(0, 0, 1, 1)`. That would keep a configuration
concept which the model does not use.

### 2.2 No player or turn context

The iOS app does not identify a player and does not track turns.

Do not add seats, player identifiers, current-player controls, `PlayerContext`, or a
`PlayerContextProvider`. Do not put player or turn fields in the evidence manifest.

The app records a session ID, an ordered event sequence, and event/frame timestamps. The game
engine owns retrospective player attribution and game-rule decisions.

### 2.3 Use Apple frameworks

Add no third-party iOS runtime dependency for this work.

Use:

- AVFoundation;
- Core ML;
- Foundation and `URLSession`;
- CryptoKit for SHA-256;
- the test framework already used by the project.

Do not add Alamofire, a ZIP library, a database wrapper, or a dependency-injection framework.

### 2.4 Keep the local loop independent of a phone

Use saved videos, saved probability streams, image fixtures, `URLProtocol` test doubles, and the
simulator for normal development. A camera smoke test on one iPhone is useful, but it does not
block the backend handoff.

## 3. Pinned PoC operating configuration

Use the experimental result from
[`0015-CardEventNet_Transition_Targets_Report.md`](../../reports/0015-CardEventNet_Transition_Targets_Report.md).
This pin is for the pipeline PoC. It does not promote V2 to the repository-wide default.

```text
source model:
  card_event_net/data/outputs/run-20260825-235429/CardEventNet-v2.mlpackage

iOS resource name:
  CardEventNetTransitionV2.mlpackage

model version:
  transition-v2-run-20260825-235429

weights SHA-256:
  f5eccd8e580d1dccecfa7835b3a0d9d5858cc47fdd0098aa33c3c47f01a38d04

preprocessing:
  full_frame_letterbox_v1

clip offsets:
  [-1.4, -1.2, -1.0, -0.8, -0.6, -0.4, -0.2, 0.0] s

inference target:
  8 Hz

offline threshold candidate:
  0.3442875146865845

offline confirmation assumption:
  125 ms

minimum event gap:
  625 ms
```

Do not replace `card_event_net/CardEventNet.mlpackage`. It remains the legacy model until a
separate promotion decision changes it.

Report 0015 passed deterministic Core ML output parity. It did not prove Swift full-frame tensor
parity or live event-decoder parity. It also found a material device-domain gap. Treat this model
as good enough for the pipeline PoC only.

## 4. Scope

### In scope

1. Integrate the pinned V2 model as a separate iOS resource.
2. Remove the legacy ROI path and prove full-frame preprocessing parity.
3. Replace the current hysteresis logic with a bounded causal peak decoder.
4. Sample and retain a small ring of compressed full-frame JPEGs.
5. Assemble one immutable evidence package for each event.
6. Write the package to a simple filesystem store.
7. Define the V1 manifest and HTTP contract.
8. Generate a file-backed multipart request.
9. Add shared fixtures and contract tests.

### Out of scope

- player attribution and turn tracking;
- Doppelkopf rules;
- card recognition;
- server implementation;
- background `URLSession`;
- automatic retry and relaunch reconciliation;
- storage quotas and retention;
- production capture UI;
- authentication;
- cloud deployment;
- broad device support claims.

## 5. Small implementation milestones

Implement each milestone as a buildable, tested change.

### M0 — Full-frame model integration

1. Copy the pinned model to the tracked iOS resource name.
2. Load that resource explicitly.
3. Remove the ROI API and implementation listed in section 2.1.
4. Keep orientation handling, aspect-ratio-preserving resize, black padding, RGB channel order,
   and normalization identical to `full_frame_letterbox_v1`.
5. Add a recorded full-frame fixture with Python reference tensor values or a stable tensor digest.
6. Assert Swift/Python parity within the documented numeric tolerance.

Acceptance:

- inference starts without ROI configuration;
- every source pixel can contribute to the model input;
- portrait and landscape geometry tests pass;
- the parity fixture passes.

### M1 — Causal event decoder

The report uses an offline `candidate_peaks` function. Its `peak_confirmation_s` value affects the
reported latency, but the function does not implement the required live confirmation state.

1. Add a bounded causal Python decoder as the reference.
2. Define threshold, peak confirmation, end-of-stream flush, and minimum-gap behavior.
3. Replay saved validation probability streams through it.
4. Start with the report threshold.
5. If the event set changes, select a new threshold from validation only.
6. Do not tune on the test partition.
7. Implement the same state machine in Swift.
8. Assert equal event time, peak score, and emission time for both implementations.

Record the frozen live values in a short report. Update the manifest fixture if they differ from
the values in section 3.

Acceptance:

- the Swift decoder matches the causal Python reference on saved streams;
- the existing guessed high/low hysteresis thresholds are gone;
- decoder memory is bounded.

### M2 — Evidence frame ring

Route each accepted camera or replay frame to two independent bounded paths:

```text
frame -> inference
     -> evidence sampler -> JPEG encoder -> compressed frame ring
```

Starting evidence settings:

```text
sample target:           8 Hz
JPEG quality:            0.85
ring duration:           3.0 s
target offsets:          [-800, -400, -100, 150, 400, 700] ms
maximum lookup distance: 175 ms
finalization delay:      900 ms
```

These offsets are an unvalidated evidence-quality hypothesis. Keep them in typed configuration.

Only the bounded encoder may retain one accepted raw pixel buffer. Only compressed JPEG data may
enter the multi-second ring. If the encoder is busy, drop the sample and record the drop.

For each target, select the nearest frame within the maximum distance. Resolve ties in a tested,
deterministic way. Record both the target and actual offset.

Acceptance:

- inference and JPEG encoding cannot create unbounded queues;
- evidence JPEGs contain the complete frame;
- lookup and eviction unit tests pass;
- missing targets remain explicit.

### M3 — Evidence package

Assign each event:

- a client-generated package UUID;
- a capture-session UUID;
- a positive, monotonically increasing event sequence;
- event and emission times in session-relative milliseconds.

Wait for the configured positive evidence offsets, then finalize one immutable package. Support
multiple pending events. If frames are missing, persist the package anyway. A metadata-only
package is valid when all targets are listed as missing.

Use this package layout:

```text
<package-id>/
  manifest.json
  frames/
    frame_00.jpg
    ...
```

For this PoC, an atomic write to a staging directory followed by a rename is sufficient. Durable
queue states and crash recovery belong to plan 0016.

Acceptance:

- one decoded event produces one package;
- no raw pixel buffer enters a package;
- all present frame hashes and byte lengths validate;
- complete, incomplete, and metadata-only package tests pass.

### M4 — Shared V1 contract

Create these canonical repository artifacts:

```text
SERVER_CONTRACT.md
fixtures/evidence/v1/example-complete/manifest.json
fixtures/evidence/v1/example-incomplete/manifest.json
```

The manifest has these top-level fields:

```text
schema_version
package_id
session
event
model
event_decoder
evidence_capture
camera
frames
missing_frame_targets_ms
score_trace
client
```

It has no player or turn context.

Required identities and timing:

- `session.session_id` and `session.event_sequence` form the logical event identity;
- `event.event_time_ms` is the selected peak time;
- `event.emitted_at_ms` is the causal decoder output time;
- each frame records target offset, actual offset, session time, capture UTC time, dimensions,
  byte length, content type, and SHA-256;
- the present targets and missing targets form the configured target set with no duplicates;
- `event.evidence_complete` is true only when no targets are missing;
- `client.device_model_identifier` is a device model class, not a stable device identifier.

Freeze this endpoint:

```http
PUT /v1/evidence-packages/{package_id}
Content-Type: multipart/form-data
```

Multipart parts:

```text
manifest  application/json
frame_00  image/jpeg
...
frame_05  image/jpeg
```

Responses:

```text
201: new package accepted
200: identical replay accepted; return the current state
409: the package ID already has different content
```

The response contains `package_id`, `state`, `created`, and `received_at`. Document size limits,
hash validation, incomplete-package rules, and other `4xx`/`5xx` behavior in
`SERVER_CONTRACT.md`.

Both Swift and Python contract tests must use the same JSON fixtures.

Acceptance:

- the Swift manifest type decodes and re-encodes both fixtures;
- a backend implementer can build the endpoint from `SERVER_CONTRACT.md` and fixtures only;
- plan 0004 contains no competing manifest definition.

This acceptance gate unblocks plan 0004.

### M5 — Multipart request proof

Generate multipart data as a file. Do not build a multi-megabyte body in one `Data` value.

Use a deterministic test boundary and exact CRLF formatting. Validate:

- boundary syntax;
- manifest part headers;
- frame part names and filenames;
- part byte order;
- closing boundary;
- content length;
- zero-frame packages.

Add a small `URLSession` client that prepares the request. Use a custom `URLProtocol` in automated
tests. A foreground upload is sufficient for this plan.

Do not add a second JSON format or an in-memory test-only upload path.

Acceptance:

- a replay-generated package becomes a contract-valid multipart request file;
- the request test double receives the expected method, path, headers, manifest, and JPEG parts;
- identical preparation does not mutate package content.

## 6. Configuration

Keep one typed configuration for values that can change during the PoC:

```swift
struct AppConfiguration {
    struct Inference {
        let modelVersion: String
        let preprocessing: String
        let targetHz: Double
        let threshold: Double
        let peakConfirmationMs: Int
        let minimumEventGapMs: Int
    }

    struct Evidence {
        let targetHz: Double
        let jpegQuality: Double
        let historySeconds: Double
        let targetOffsetsMs: [Int]
        let maximumLookupDistanceMs: Int
        let finalizationDelayMs: Int
    }
}
```

Do not add ROI, player, or turn settings. Do not scatter operating values across views and types.

## 7. Verification

Run the normal local checks after each milestone:

```text
cd ios
swift test
```

Also run the existing Python tests affected by the causal decoder and fixture generation. Use the
project's declared `mise` runtimes and normal language commands.

Before handoff, verify one saved replay end to end and inspect one generated package. Manual
inspection supplements the automated contract tests. It does not replace them.

## 8. Definition of done

Plan 0003 is complete when:

- the V2 model uses the complete oriented frame with verified Swift/Python preprocessing parity;
- the live Swift decoder matches the causal Python reference;
- a saved replay creates complete or explicitly incomplete full-frame evidence packages;
- package persistence and multipart generation are file-backed;
- shared complete and incomplete fixtures pass Swift contract tests;
- `SERVER_CONTRACT.md` freezes the V1 upload behavior;
- plan 0004 can start with no iOS implementation dependency;
- no player/turn model, ROI configuration, or third-party iOS runtime dependency was added.

## 9. Follow-on plans

- [`0016-iOS_EvidenceUpload_Integration.md`](../3-in-progress/0016-iOS_EvidenceUpload_Integration.md) connects the
  client to the local plan 0004 backend and makes the queue durable.
- [`0024-System_Production_Readiness.md`](../0-to-specify/0024-System_Production_Readiness.md) will select required
  iOS hardening after local and field measurements. Plan 0017 remains a reference checklist.
