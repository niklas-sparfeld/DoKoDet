# CardEventNet iOS PoC — Implementation Plan

## Plan status

- **Summary:** Test CardEventNet on iPhone
- **Status:** Draft

## 0. Mission

Build a small native iOS application that runs the provided `CardEventNet` Core ML model **entirely on-device** and makes it easy to answer:

1. Does the model produce sensible outputs on real iPhone camera frames?
2. What end-to-end inference latency and sustainable inference rate do we get?
3. Does it still work with the real table geometry, oblique camera angle, lighting changes, hands, motion blur, and sloppy card placement?
4. Can repeated positive model outputs be converted into exactly one useful **card-play event**?
5. Can we replay known test videos deterministically on the device and inspect where the model fails?

This is a PoC, but **do not build it as disposable code**. The camera, inference, event post-processing, and diagnostic boundaries should be usable in the later real app.

Do **not** implement cloud recognition, player/game state, networking, accounts, persistence beyond diagnostics, or polished UX in this phase.

---

## 1. Target Implementer

This plan is intentionally explicit enough for a capable coding model that is weaker than the model that designed the architecture.

Recommended implementation model: **GPT-5.6 Terra**.

The implementer should optimize for:

- simple Swift
- few dependencies
- small files with obvious responsibilities
- compile/test after each milestone
- no speculative abstractions
- no invented assumptions about the Core ML model

When a model detail is unknown, inspect the supplied model and adapt the `CardEventModelRunner`. **Never guess model input/output names, tensor shapes, normalization, temporal window length, or label semantics.**

---

## 2. Technology Choices

Use:

- Swift
- SwiftUI
- AVFoundation for camera capture
- Core ML for inference
- Vision only if it materially simplifies the supplied model's image preprocessing
- AVFoundation / AVAssetReader for deterministic video replay
- XCTest / Swift Testing as available in the generated project
- no third-party runtime dependencies

Deployment target:

- iOS 18+ unless the surrounding repository already defines another target.

Primary test hardware:

- physical iPhone
- simulator support is useful for UI work but is **not** a model-performance target

Default model compute configuration:

```swift
MLModelConfiguration.computeUnits = .all
```

Expose alternative compute-unit configurations later only as a diagnostic option if useful.

---

## 3. Important Architectural Decision

### Keep the PoC evolvable

Use this flow:

```text
Live Camera --------------------\
                                 \
                                  -> VideoFrame
                                 -> CardEventModelRunner
Replay Video -------------------/   -> ModelPrediction
                                     -> EventPostProcessor
                                     -> DetectionEvent
                                     -> DiagnosticsStore
                                     -> UI
```

The key boundary is `CardEventModelRunner`.

The rest of the app must not care whether CardEventNet is:

- a single-frame classifier
- a temporal model
- an image model
- a tensor model
- later replaced with a newer Core ML model

Similarly, live camera and replay must converge on the same logical frame/model/post-processing path.

Do not create a generic framework. These protocols exist only to isolate the parts that are expected to change.

---

## 4. Repository / Project Layout

Use approximately this structure:

```text
CardEventProbe/
├── CardEventProbeApp.swift
│
├── App/
│   ├── AppState.swift
│   └── AppConfiguration.swift
│
├── Camera/
│   ├── CameraSession.swift
│   ├── CameraPreview.swift
│   └── CameraFrameDelegate.swift
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
│   └── DetectionEvent.swift
│
├── Replay/
│   ├── VideoReplayRunner.swift
│   └── ReplayResult.swift
│
├── Diagnostics/
│   ├── DiagnosticsStore.swift
│   ├── SessionLog.swift
│   └── DiagnosticFrameWriter.swift
│
├── UI/
│   ├── RootView.swift
│   ├── LiveDetectionView.swift
│   ├── ReplayView.swift
│   ├── DiagnosticsPanel.swift
│   └── Components/
│
├── Models/
│   └── CardEventNet.mlpackage     # or supplied model format
│
└── Tests/
    ├── EventPostProcessorTests.swift
    └── ModelContractTests.swift
```

Adapt names to the actual generated Xcode project if necessary.

Do not use MVVM ceremony for every view. `AppState` plus small observable controllers is sufficient.

---

## 5. Phase 1 — Project Bootstrap

### Goal

A minimal app builds and launches on a physical iPhone.

### Tasks

- Create a SwiftUI iOS app named `CardEventProbe`.
- Add camera permission to `Info.plist`:
  - `NSCameraUsageDescription`
- Add the supplied Core ML model to the application target.
- Confirm Xcode compiles the model into the application bundle.
- Add a two-tab or segmented root UI:
  - `Live`
  - `Replay`
- Add a compact diagnostics area shared by both modes.

### UI at this stage

Live screen can initially show:

```text
CardEventProbe

[ camera placeholder ]

Model: loading / ready / error
Inference: —
Score: —
Event count: 0
```

Replay screen can initially show:

```text
Replay

[ Choose Video ]

No replay loaded
```

### Acceptance criteria

- project builds from command line with `xcodebuild`
- app launches on device
- camera permission prompt appears when entering Live mode
- model resource can be located and loaded
- failures are displayed in the UI instead of crashing

### Commit

```text
ios: bootstrap CardEventProbe app
```

---

## 6. Phase 2 — Inspect and Lock Down the Model Contract

### Goal

Before implementing inference, determine exactly what the supplied Core ML model expects and returns.

### Required implementation

Create:

```swift
struct ModelContract {
    let inputNames: [String]
    let outputNames: [String]

    // Populate applicable fields from MLModelDescription.
    let imageInput: ImageInput?
    let multiArrayInputs: [MultiArrayInput]
    let metadata: [String: String]
}
```

The exact shape can be adjusted to the real model.

Add a diagnostic function that inspects:

```swift
model.modelDescription
```

and logs / displays:

- input feature names
- feature types
- image width / height if image input
- image pixel format / color space information available
- MLMultiArray shapes and element types
- output feature names
- output feature types
- model metadata
- predicted label feature, if present
- probability dictionary feature, if present

### Also create

`MODEL_CONTRACT.md` in the repository after inspection.

It must record the **actual** contract, for example:

```text
Model: CardEventNet
Input:
- frames: image / multiarray
- size: ...
- temporal window: ...
- expected frame sampling: ...
- preprocessing: ...

Output:
- card_event_probability: ...
- semantic meaning: probability that ...
```

Do not invent temporal sampling or preprocessing from the `.mlpackage` if it is not encoded there.

If the model itself does not contain enough information, look for adjacent training/export config in the repository.

If still unknown, make the uncertainty explicit in `MODEL_CONTRACT.md` and implement only what can be established.

### Important rule

**Exact training-time preprocessing is part of the model.**

Do not casually add:

- extra normalization
- arbitrary center crop
- arbitrary aspect-fill crop
- rotation
- RGB/BGR swapping
- temporal resampling

unless the model contract requires it.

### Acceptance criteria

- the app loads the model
- the model contract is printed once at startup in Debug
- `MODEL_CONTRACT.md` contains the actual observed contract
- inference implementation can now be based on facts rather than guesses

### Commit

```text
ios: document CardEventNet Core ML contract
```

---

## 7. Phase 3 — Define the Stable Inference Boundary

Create the following conceptual types.

Exact Swift syntax may vary, but keep these semantics.

### `VideoFrame`

```swift
struct VideoFrame {
    let pixelBuffer: CVPixelBuffer
    let timestamp: CMTime
    let orientation: CGImagePropertyOrientation
}
```

If rotation is applied before this boundary, orientation can instead be normalized and omitted. Pick one approach and document it.

### `ModelPrediction`

```swift
struct ModelPrediction {
    let timestamp: CMTime

    // Canonical score used by the app.
    // 0 = definitely no new card event
    // 1 = definitely card event
    let cardEventProbability: Double

    // Useful during PoC if the model exposes additional scalar outputs.
    let rawOutputs: [String: Double]

    let inferenceDurationMs: Double
}
```

### `CardEventModelRunner`

Use an interface with a **consume** operation, not merely `predict(image:)`, so a temporal CardEventNet remains possible:

```swift
protocol CardEventModelRunner: AnyObject {
    var contract: ModelContract { get }

    func reset()

    /// Returns nil when the model does not yet have enough temporal
    /// context to produce a prediction.
    func consume(_ frame: VideoFrame) throws -> ModelPrediction?
}
```

### Why this interface matters

If CardEventNet needs a window of frames, the runner owns:

- its frame ring buffer
- temporal sampling
- tensor assembly

If CardEventNet is a single-frame model, `consume` simply returns one prediction per accepted frame.

The UI, replay code, and event post-processing should not need to know which case applies.

---

## 8. Phase 4 — Implement Core ML Inference

### Goal

Run CardEventNet against a known frame on-device and show its raw result.

### Strategy

Choose the implementation based on the inspected contract.

#### Case A — ordinary image input

Prefer the simplest correct path.

Vision is acceptable when it exactly matches the required crop/scale behavior.

Possible path:

```text
CVPixelBuffer
  -> Vision request using VNCoreMLModel
  -> prediction result
```

Alternatively call Core ML directly if preprocessing has already produced the exact expected pixel buffer.

#### Case B — temporal/tensor input

Use Core ML directly.

Implement explicit preprocessing according to `MODEL_CONTRACT.md`:

```text
CVPixelBuffer(s)
  -> resize/crop as required
  -> tensor conversion
  -> temporal stack
  -> MLFeatureProvider / generated model API
  -> output
```

Keep all such logic in `CoreMLCardEventModelRunner`.

### Model loading

- load once
- do not reload per prediction
- default to `.all` compute units
- surface load errors
- call `reset()` when input source changes

### Timing

Measure inference around the actual prediction call with a monotonic clock.

Do not include UI work in `inferenceDurationMs`.

### Threading

Model inference must not run on the main actor.

Use one serial inference execution path.

Do not allow an unbounded queue of camera frames.

### Acceptance criteria

Given at least one known test image/frame:

- app executes the model on a physical iPhone
- app displays raw card-event probability
- app displays inference duration
- no model reload occurs between frames
- no main-thread stalls are caused by inference

### Commit

```text
ios: run CardEventNet inference on device
```

---

## 9. Phase 5 — Live Camera Pipeline

### Goal

Show the rear camera and continuously feed selected frames into the model.

### Camera setup

Use:

- `AVCaptureSession`
- rear wide-angle camera
- `AVCaptureDeviceInput`
- `AVCaptureVideoDataOutput`
- `AVCaptureVideoPreviewLayer`

Recommended starting capture preset:

```text
1920 × 1080 if available
fallback: 1280 × 720
```

The model should still receive its own required input resolution after preprocessing.

### Capture behavior

Configure:

```swift
videoDataOutput.alwaysDiscardsLateVideoFrames = true
```

Deliver frames on a dedicated serial capture queue.

The preview should remain smooth even if ML inference is slower.

### Orientation

Use current AVFoundation rotation APIs rather than old manual device-orientation mappings.

Do not perform expensive physical pixel rotation merely for the preview.

Ensure the model sees a consistent orientation matching training assumptions.

### Camera controls

For the first PoC:

- rear wide camera only
- continuous autofocus
- continuous auto exposure
- no zoom UI
- no manual exposure UI

Later diagnostics may add exposure/focus controls if real tests show they matter.

### Camera lifecycle

Correctly handle:

- permission denied
- entering background
- returning foreground
- capture interruption
- capture session failure

Do not overengineer recovery. Display a useful error state.

### Acceptance criteria

- smooth camera preview
- model score updates while camera runs
- inference runs off the main thread
- rotating the phone does not silently feed incorrectly oriented content to the model
- leaving/re-entering Live mode does not create duplicate capture sessions

### Commit

```text
ios: add live camera inference pipeline
```

---

## 10. Phase 6 — Backpressure and Inference Sampling

### Goal

The app must remain responsive and must not build a latency queue.

For card-play detection, processing every camera frame is unnecessary.

### Starting configuration

Use a configurable target inference rate:

```text
default: 8 predictions / second
range for diagnostics: 1 ... 15 Hz
```

If the model contract specifies its own temporal cadence, that takes precedence.

### Required behavior

When a live frame arrives:

1. reject it if it is too soon after the previous accepted frame
2. reject it if an inference is already in flight
3. otherwise process it
4. never queue dozens of stale frames

Conceptually:

```swift
if shouldSample(timestamp),
   inferencePermit.tryAcquire() {
    inferenceQueue.async {
        defer { inferencePermit.release() }
        runInference(frame)
    }
}
```

Any implementation with equivalent bounded behavior is acceptable.

### Metrics to count

- camera frames received
- frames intentionally skipped due to sampling
- frames dropped because inference was busy
- model predictions produced
- average / recent inference latency

### Acceptance criteria

- UI stays responsive
- prediction latency does not grow over time
- a slow model causes dropped/skipped frames, not a growing work queue
- diagnostic counters make the behavior visible

### Commit

```text
ios: bound live inference and expose pipeline metrics
```

---

## 11. Phase 7 — Convert Model Scores into Card-Play Events

### Goal

One physical card play should become approximately one `DetectionEvent`, not 5–20 consecutive positives.

Keep this logic independent of Core ML.

### `DetectionEvent`

```swift
struct DetectionEvent: Identifiable {
    let id: UUID
    let timestamp: CMTime
    let peakProbability: Double
}
```

### `EventPostProcessor`

Start with a simple state machine with:

- high threshold
- low threshold
- minimum consecutive positives
- cooldown / re-arm period
- optional short moving average or EMA

Suggested initial values are only defaults and must be tweakable:

```text
high threshold:          0.75
low threshold:           0.35
minimum positive hits:   2
cooldown:                0.6 s
```

Do not bury these values inside the model runner.

Example states:

```text
idle
  -> candidate
  -> active/event emitted
  -> cooldown
  -> idle
```

A new event is emitted only once when entering the active state.

### Important

The post-processor is not allowed to compensate for a fundamentally bad model by becoming highly complicated.

Its job is mainly to:

- suppress isolated noisy spikes
- collapse a burst of positive windows into one event
- make threshold experiments easy

### Unit tests

Create tests for:

1. all-low scores -> no event
2. one isolated high spike -> no event if two hits required
3. sustained high scores -> exactly one event
4. high -> low -> high after cooldown -> two events
5. high -> brief dip -> high -> still one event if within active/cooldown logic
6. reset -> clean state

### Acceptance criteria

- event count is visible in UI
- card event causes a clear visual pulse/banner
- repeated high predictions from one action normally collapse to one event
- post-processing logic has deterministic unit tests

### Commit

```text
ios: derive discrete card-play events from model scores
```

---

## 12. Phase 8 — Build the Live Diagnostics UI

### Goal

Make real-world testing useful without attaching Xcode.

The Live screen should show:

### Camera area

- full-width preview
- compact overlay:
  - current model score
  - event flash / marker

### Status panel

Show:

```text
Model                  Ready
Inference target       8 Hz
Actual predictions     7.8 Hz
Last inference         14 ms
Recent avg             15 ms
Dropped/busy           3
Thermal state          nominal/fair/serious/critical
Raw score              0.82
Smoothed score         0.79
Events                 12
```

Do not spend time on advanced visual design.

### Controls

Add a collapsible diagnostics/settings area:

- high threshold slider
- low threshold slider
- target inference Hz
- reset event count
- diagnostics recording on/off

Potentially add compute units later:

- all
- CPU + Neural Engine
- CPU only

Only add this if reloading the model cleanly is straightforward.

### Score history

Add a lightweight short history visualization if cheap to implement:

- last ~10 seconds
- raw score line
- threshold line
- vertical marker on emitted event

If implementing a graph becomes disproportionately complex, defer it and show a scrolling event/prediction log instead.

### Acceptance criteria

A tester can operate the app without Xcode and understand:

- whether the model is running
- what it currently thinks
- when the app emitted an event
- whether performance is degrading

### Commit

```text
ios: add on-device CardEventNet diagnostics UI
```

---

## 13. Phase 9 — Deterministic Replay of Existing Videos

### Goal

Run the same model code over prerecorded videos on the physical iPhone.

This is a first-class PoC feature, not an optional extra.

### Import

Use a simple SwiftUI file importer for movie files.

The selected file may need to be copied into the app's temporary/application-support area before processing, depending on the security-scoped URL lifecycle.

Avoid Photos integration unless it is clearly simpler.

### Replay implementation

Use:

- `AVAsset`
- `AVAssetReader`
- `AVAssetReaderTrackOutput`

Request pixel buffers compatible with the inference preprocessing path.

Read sample buffers in timestamp order.

### Deterministic sampling

Do **not** process based on wall-clock playback speed.

Instead:

```text
video timestamps
  -> select frames according to configured/model-required sampling cadence
  -> process each selected frame sequentially
```

Replay may run slower or faster than real time.

Do not drop a sampled replay frame merely because inference is busy; replay should await/process deterministically.

### Source reset

Before each replay:

```swift
modelRunner.reset()
eventPostProcessor.reset()
diagnostics.resetForNewSession()
```

This is critical for temporal models.

### Replay UI

Show:

- chosen filename
- duration
- current processing timestamp
- progress
- current score
- emitted event count
- inference average
- cancel button
- results summary

### Acceptance criteria

- same video produces the same event timestamps within reasonable numerical determinism
- replay uses the same model runner and post-processor as live mode
- no camera session is required
- changing threshold and rerunning a video is easy

### Commit

```text
ios: add deterministic on-device video replay
```

---

## 14. Phase 10 — Session Logging and Failure Capture

### Goal

Produce artifacts that help improve CardEventNet after field tests.

### Session log

For each Live or Replay session write JSONL or CSV.

Prefer JSONL because fields can evolve without migration pain.

One prediction record should contain approximately:

```json
{
  "type": "prediction",
  "source": "live",
  "timestampSeconds": 12.375,
  "rawProbability": 0.83,
  "smoothedProbability": 0.78,
  "eventEmitted": true,
  "inferenceMs": 14.2
}
```

Session metadata record:

```json
{
  "type": "session",
  "appVersion": "...",
  "device": "...",
  "osVersion": "...",
  "modelName": "...",
  "modelVersion": "...",
  "targetInferenceHz": 8.0,
  "highThreshold": 0.75,
  "lowThreshold": 0.35
}
```

### Diagnostic images

When diagnostics recording is enabled:

- save a JPEG when an event is emitted
- optionally save a JPEG for a manually marked failure
- include timestamp in filename

Do not continuously save every inference frame.

### Manual annotations

Add two debug buttons if cheap:

```text
[ Missed event ]
[ False event ]
```

Behavior:

- write an annotation record into the session log
- save the nearest current frame as JPEG if diagnostics capture is enabled

This is very useful for later retraining.

### Export

Use the standard iOS share sheet to export:

- session log
- diagnostic JPEGs, preferably zipped if straightforward

If zipping creates needless dependency/work, export the log first and leave image bundle export as follow-up.

### Privacy

No cloud upload in this phase.

All diagnostic data remains on device until the user explicitly exports it.

### Acceptance criteria

After a tabletop test, we can obtain:

- model scores over time
- emitted event timestamps
- inference performance
- manually flagged misses/false positives
- representative failure frames

### Commit

```text
ios: record and export CardEventNet diagnostics
```

---

## 15. Phase 11 — Performance / Thermal Validation

### Goal

Verify the configuration can run for a realistic game duration without silently becoming unusable.

### Test matrix

At minimum on the target iPhone test:

```text
Live camera
Capture: 1080p
Inference: 5 Hz
Duration: 15 min

Live camera
Capture: 1080p
Inference: 8 Hz
Duration: 15 min

Live camera
Capture: 1080p
Inference: 12 Hz
Duration: 15 min
```

If 1080p capture is unsupported or unexpectedly expensive, repeat at 720p.

### Record

For each run:

- prediction latency
- actual inference rate
- busy/drop count
- device thermal state transitions
- obvious battery impact
- UI responsiveness
- event behavior

### Selection rule

Pick the lowest inference cadence that still reliably detects real card plays.

Do not optimize for maximum FPS.

For this application, stable 5–10 Hz may be better than trying to process 30/60 FPS.

### Acceptance criteria

Document the chosen default in:

```text
IOS_POC_RESULTS.md
```

Include:

- device model
- OS version
- CardEventNet version/hash
- chosen capture resolution
- chosen inference rate
- typical latency
- thermal observations
- event detection observations

---

## 16. Tests

### Required unit tests

`EventPostProcessor`:

- state-machine cases described above

`ModelContract`:

- contract extraction does not crash
- expected supplied model inputs/outputs match a small set of assertions

Do not assert every automatically generated metadata field.

### Useful integration smoke test

If a known test frame can be checked into the repository:

- load model
- run one inference
- verify output is finite and within expected range

Do **not** assert an overly precise floating point value across different compute units/devices.

### Replay regression test

If practical, keep a tiny short video fixture and expected coarse behavior:

```text
event count approximately N
or
at least one event in [t1, t2]
```

Do not make the application build dependent on a large video asset.

---

## 17. Error Handling Rules for the Implementer

The app should never silently continue after one of these:

- Core ML model missing
- model failed to compile/load
- model output cannot be mapped to `cardEventProbability`
- expected input shape differs from documented `MODEL_CONTRACT.md`
- camera device unavailable
- video cannot be decoded

Show a readable error in the UI and log the technical details.

Do not use `try!`.

Avoid broad `catch {}` blocks that discard the error.

---

## 18. Concurrency Rules

Keep concurrency deliberately boring.

### Main actor

Only:

- SwiftUI state
- UI-facing observable properties
- preview-layer UI updates

### Capture queue

Only:

- AVFoundation frame callbacks
- lightweight timestamp/rate gating
- forwarding accepted frames to inference

### Inference execution

- one serial execution path
- maximum one live inference in flight
- no unbounded task creation
- Core ML runner state is confined to that path

### Replay

- sequential
- deterministic
- cancellable
- not main actor

Avoid introducing a complex actor graph unless Swift compiler safety makes a small actor clearly simpler.

---

## 19. Things Explicitly Out of Scope

Do **not** add any of the following in this PoC:

- backend
- authentication
- cloud upload
- card identity recognition
- Qwen/VLM integration
- OpenAI integration
- game rules
- Doppelkopf state machine
- player identification
- trick ownership
- score calculation
- remote configuration
- analytics SDK
- database
- Core Data / SwiftData
- dependency injection framework
- navigation framework
- elaborate design system
- App Store onboarding
- TestFlight automation
- continuous video recording
- background inference

These belong to later phases.

---

## 20. Definition of Done for the PoC

The PoC is complete when all of these are true:

- [ ] App builds and runs on the target physical iPhone.
- [ ] Supplied CardEventNet Core ML model loads once at startup/session start.
- [ ] Actual model I/O is documented in `MODEL_CONTRACT.md`.
- [ ] Live rear-camera preview works.
- [ ] Live frames are sampled at a bounded configurable rate.
- [ ] No inference backlog can build up.
- [ ] CardEventNet runs off the main thread.
- [ ] Current raw card-event probability is visible.
- [ ] Per-inference latency and basic throughput metrics are visible.
- [ ] Raw predictions are converted into discrete card-play events.
- [ ] Event post-processing is unit tested.
- [ ] Existing prerecorded videos can be imported and replayed deterministically.
- [ ] Live and Replay use the same model runner and post-processor.
- [ ] Diagnostic logs can be exported.
- [ ] Tester can mark a missed event or false event.
- [ ] Optional diagnostic image is stored for emitted/marked events.
- [ ] A 15-minute live test has been completed without runaway latency.
- [ ] Results and selected default inference cadence are recorded in `IOS_POC_RESULTS.md`.

---

## 21. What We Intentionally Preserve for the Real App

The following should survive into later implementation phases:

```text
CameraSession
VideoFrame
CardEventModelRunner
CoreMLCardEventModelRunner
ModelPrediction
EventPostProcessor
DetectionEvent
bounded live inference/backpressure
diagnostics logging concepts
```

Likely PoC-only or debug-only:

```text
ReplayView
threshold sliders
raw model score UI
manual missed/false event buttons
verbose model contract display
performance counters
diagnostic frame export
```

In the real app, the event boundary becomes roughly:

```text
DetectionEvent
    -> select best evidence frame(s)
    -> cloud card-recognition request
    -> recognized card candidate(s)
    -> game-state validator
    -> accepted card play
```

That later pipeline should **consume `DetectionEvent`**, not reach back into AVFoundation or Core ML internals.

---

## 22. Suggested Implementation Order for an Agent

Implement one numbered step at a time and compile after each step.

1. Bootstrap project.
2. Add/load Core ML model.
3. Inspect and document model contract.
4. Implement `CardEventModelRunner`.
5. Prove one prediction.
6. Add camera preview.
7. Feed bounded live frames into model.
8. Add diagnostics metrics.
9. Add `EventPostProcessor` and tests.
10. Add event UI.
11. Add deterministic video replay.
12. Add logging and manual annotations.
13. Run tests/build cleanly.
14. Write `IOS_POC_RESULTS.md` template.
15. Remove dead experimental code.

After each logical stage run appropriate commands, for example:

```bash
xcodebuild -project CardEventProbe.xcodeproj \
  -scheme CardEventProbe \
  -destination 'generic/platform=iOS' \
  build
```

Use the actual workspace/project/scheme names if they differ.

For tests, prefer a simulator destination available on the machine.

Do not claim device performance results unless the code was actually run on a physical device.

---

## 23. Agent Guardrails

The coding agent must follow these rules:

1. **Inspect before inventing.**
   The supplied model is the source of truth for model I/O.

2. **Compile frequently.**
   Do not produce the entire app before checking Swift/Xcode errors.

3. **Do not replace current APIs with remembered deprecated snippets.**
   Prefer current AVFoundation/Core ML APIs available to the chosen deployment target.

4. **Keep model logic isolated.**
   No Core ML output parsing in SwiftUI views.

5. **Keep event logic isolated.**
   No threshold/cooldown state machine in the camera delegate.

6. **Never build a frame backlog.**
   Live camera processing must be bounded.

7. **Replay must be deterministic.**
   It is an evaluator, not a fake real-time player.

8. **Make diagnostics useful.**
   We are building this app to discover model failures, not merely to make a green indicator blink.

9. **Do not refactor unrelated code.**
   Keep the diff focused.

10. **Leave the repository buildable.**
    No phase should finish with known compile errors.

---

## 24. Later Phases, Not Part of This Implementation

Once this PoC establishes that CardEventNet works on-device, evolve the same app approximately as follows:

### Phase A — evidence selection

When an event fires, retain/select the best frame or small image set around the event.

Potential inputs:

- model confidence
- blur metric
- occlusion/card visibility
- temporal distance from hand motion

### Phase B — cloud card recognition

Upload only the small evidence payload for a detected play, not continuous video.

Cloud service returns card identity probabilities/candidates.

### Phase C — game-aware correction

Use known:

- player whose turn/action this is
- cards already played
- cards impossible for that player
- Doppelkopf deck constraints

to reject or repair uncertain recognition.

### Phase D — production UI

Replace diagnostic controls with:

- game setup
- players
- live trick/card state
- correction workflow
- confidence/failure handling

The PoC architecture is intentionally shaped so these phases can be added after `DetectionEvent` without rewriting the camera/model pipeline.
