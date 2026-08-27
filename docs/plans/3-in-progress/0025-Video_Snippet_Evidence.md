# DokoDetector Video Snippet Evidence — Local Transport PoC

## Plan status

- **Summary:** Add bounded event-relative video snippets to iOS evidence packages and backend storage
- **Status:** In Progress
- **Depends on:** None
- **Builds on:** Plans 0003, 0004, and 0016 provide the completed frame-only baseline
- **Reviewed:** 2026-08-27 against the current iOS and backend evidence pipeline
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)
- **Unblocks:** Measured transition, occlusion, movement, and card-tracklet experiments in plan 0022

## 1. Outcome

Extend the local evidence pipeline with one optional bounded video snippet around a CardEventNet event
proposal. Preserve selected JPEG frames as part of the new contract.

At the end of this plan, a developer can run:

```text
recorded local video or live camera
  -> CardEventNet event proposal
  -> selected JPEG frames plus bounded video snippet
  -> versioned evidence manifest
  -> multipart upload
  -> backend validation and immutable storage
  -> byte-identical read-back and decode check
```

The ordinary development loop uses a checked-in media fixture. It does not require a phone, camera,
network service, trained model, or GPU.

## 2. Contract decisions

### 2.1 Add a V2 evidence package

Use `cardevent-evidence/v2` with one optional video snippet part. A
V2 package can remain frame-only when snippet capture fails or is disabled. Update all local
producers, consumers, and fixtures in the same epic. Do not maintain a dual parser for the undeployed
PoC format.

The manifest records:

```text
part_name
event-relative start_offset_ms and end_offset_ms
duration_ms
container
video codec
width and height
nominal_frame_rate, when known
byte_length
content_type
sha256
capture_complete
missing or failure reason, when absent or incomplete
```

Use a closed list of supported containers, codecs, and media types. Do not trust the declared media
type alone. The backend must decode or probe the supported fixture before accepting it.

### 2.2 Preserve selected frames

Do not replace the six selected-frame path. Frames remain useful for:

- simple recognition baselines;
- deterministic contract fixtures;
- previews and human review;
- fallback when the snippet is absent or corrupt;
- comparison of frame-only and video-based methods.

### 2.3 Keep capture bounded and configurable

The first snippet covers at least the time span of the selected frame offsets around the event
proposal. Record the requested and actual start and end. Do not promise exact event-relative timing
when the encoder or ring buffer cannot supply it.

Set explicit limits for:

- maximum duration;
- maximum dimensions and nominal frame rate;
- maximum byte length;
- one snippet part per evidence package;
- local queued-byte capacity.

Choose the first values from the M0 measurements. Keep them versioned. Do not infer production limits
from the PoC.

### 2.4 Preserve immutable source evidence

Hash the encoded snippet bytes before upload. Persist them unchanged. Record capture and encoding
configuration in the manifest. Do not transcode accepted bytes during ingestion.

If a future derived proxy is needed, store it as a derived artifact with lineage to the accepted
snippet.

## 3. Local fixture

Add one small, redistributable video fixture that shows a simple card entering and leaving a table
area. Keep it short enough for ordinary tests.

The fixture package contains:

- a V2 manifest;
- selected JPEG frames derived from named times;
- one encoded snippet;
- byte lengths and SHA-256 values;
- expected technical probe data;
- a malformed or truncated snippet fixture generated during the test, not committed as a large
  duplicate.

The fixture tests transport and media integrity. It is not recognition training data and does not
measure tracking quality.

## 4. iOS capture design

Use one bounded rolling source of recent camera samples. When the causal event decoder confirms a
proposal:

1. retain enough pre-event samples to cover the requested start;
2. continue until the requested post-event end or a declared timeout;
3. encode one bounded snippet off the main thread;
4. keep the existing selected-frame extraction;
5. finalize one V2 evidence package after both paths finish or fail explicitly;
6. enqueue the package through the existing durable upload queue.

First prove snippet creation from the existing replay path. Add live-camera integration only after
the deterministic replay test passes.

Do not keep unbounded raw sample buffers. Release encoded and raw temporary data after the durable
package owns the final bytes. Make cancellation, backgrounding, and storage exhaustion explicit
package outcomes.

## 5. Backend ingestion

Extend the existing strict multipart ingestion path:

- accept V2 packages;
- require exactly the parts declared by the manifest;
- stream size-limited bytes to temporary storage;
- verify byte length and SHA-256;
- validate the supported container and video stream;
- reject path traversal, duplicate parts, unsupported codecs, and truncated media;
- commit manifest, frames, and snippet atomically;
- return the existing package on an idempotent replay;
- expose snippet metadata and a safe read path for local TableEvidenceAnalyzer work.

A failed upload must not leave accepted partial media or database rows.

## 6. Small implementation milestones

### M0 — Media choice and V2 contract — Complete

1. [x] Use a representative recorded source to compare at least two locally supported encoding settings.
2. [x] Record size, encode time, decode time, dimensions, frame rate, and event-relative coverage.
3. [x] Select one PoC container, codec, and bounded configuration.
4. [x] Write the V2 manifest contract and canonical fixture.
5. [x] Add strict Swift and Python contract tests.

The measured selection is recorded in
[the M0 media report](../../reports/0025-Video_Snippet_M0_Media_Selection.md).

Acceptance:

- the selected format decodes with the local iOS and backend toolchains;
- the fixture is small enough for ordinary tests;
- all canonical evidence fixtures use V2;
- no dual V1/V2 runtime path remains;
- missing optional snippet evidence remains distinct from a corrupt declared snippet.

### M1 — Backend round trip

1. Accept and validate the V2 multipart fixture.
2. Persist snippet bytes atomically with the manifest and frames.
3. Return metadata and byte-identical media.
4. Add idempotency, size-limit, hash, unsupported-media, truncation, and rollback tests.

Acceptance:

- accepted snippet bytes read back with the original SHA-256;
- corrupt or unsupported media is rejected before commit;
- migrated frame-only V2 backend tests pass;
- tests need no external service.

### M2 — Deterministic iOS replay capture

1. Feed the checked-in source through the replay path.
2. Create the bounded snippet around a scripted event proposal.
3. Create the selected frames and one V2 manifest.
4. Verify timing, hashes, technical metadata, and queue recovery.

Acceptance:

- repeated replay produces equivalent semantic metadata;
- encoded bytes pass the backend probe and upload fixture tests;
- capture and encoding do not block the main thread;
- a failed snippet still produces an explicit frame-only V2 package when frames are usable.

### M3 — Live capture integration

1. Add the bounded rolling capture path to the camera session.
2. Finalize snippets for confirmed causal event proposals.
3. Enforce queued-byte and temporary-storage limits.
4. Show snippet status in diagnostics.

Acceptance:

- the existing frame-only UI and uploads still work;
- one live proposal creates one bounded package;
- cancellation and low-storage paths release temporary resources;
- no unbounded sample buffer exists.

### M4 — Local end-to-end measurement

1. Capture at least one real V2 package on a supported iPhone.
2. Upload it to the local backend.
3. Verify selected frames and snippet decode.
4. Record actual size, duration, timing coverage, encode latency, upload latency, and storage use.
5. Replay the snippet in a minimal human-review view.

Acceptance:

- the real package survives byte-identical iOS-to-backend transport;
- the snippet shows the transition covered by the selected frames;
- measured limitations are recorded for plan 0022 and plan 0024;
- the result does not claim recognition or tracking quality.

## 7. Out of scope

- visible-card detection and identity recognition;
- optical flow, card tracking, and tracklet output;
- reconstruction rules and game inference;
- automatic upload of complete recordings;
- production background-transfer and retry objectives;
- production retention, privacy, authentication, and remote storage;
- tuning CardEventNet from snippet results.

## 8. Verification

Run the existing iOS and backend test suites plus the V2 contract and round-trip tests. Use the
project toolchain from `mise.toml`. Keep ordinary tests offline and hardware-independent.

Before closing the plan, run one optional real-device capture and local upload. Record the command,
app build, device class, operating-system version, backend revision, and resulting package digest.

## 9. Definition of done

- V2 replaces V1 and adds one optional bounded video snippet;
- one canonical fixture crosses Swift and Python unchanged;
- replay-based iOS capture is deterministic enough for contract tests;
- backend ingestion verifies bytes and supported media before atomic commit;
- selected frames remain available beside the snippet;
- one real device package completes the local round trip;
- plan 0022 has measured evidence for transition and tracking experiments.
