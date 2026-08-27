# DokoDetector Video Snippet Evidence — Local Transport PoC

## Plan status

- **Summary:** Add bounded and accurately timed iOS-to-backend video snippets at a useful
  exploratory resolution
- **Status:** In Progress
- **Depends on:** None
- **Builds on:** Plans 0003, 0004, and 0016 provide the completed frame-only baseline
- **Reviewed:** 2026-08-27 against the current iOS and backend evidence pipeline
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)
- **Unblocks:** Measured transition, occlusion, movement, and card-tracklet experiments in plan 0022

## 1. Outcome

Extend the local evidence pipeline with one optional bounded video snippet around a CardEventNet event
proposal. Preserve selected JPEG frames as part of the new contract. Record enough spatial and
temporal detail for later analyzer experiments, and make the manifest describe the encoded media
instead of the requested capture limit.

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

### 2.5 Keep exploratory motion evidence useful

Use 960×540 at a target rate of 15 frames per second for new exploratory video snippets. Keep the
six selected 1920×1080 JPEG frames. Do not use 1920×1080 video snippets unless analyzer experiments
show that 960×540 loses required card detail.

Treat the accepted 960×540 snippet as source evidence. Derive smaller model inputs or review proxies
from it. Do not replace the accepted bytes with a derived proxy. This approach permits controlled
640×360 and lower-resolution comparisons without losing the original motion detail.

The exploratory profile starts with these bounds:

```text
max_width: 960
max_height: 540
max_nominal_frame_rate: 15.0
encoder_average_bit_rate: 1200000
max_byte_length: 750000
temporary_byte_capacity: 83886080
queued_byte_capacity: 10485760
```

These are measurement targets, not production limits. Confirm them on a supported iPhone before
closing this epic. A 10 MiB video queue holds at least 13 maximum-size snippets. Record total
evidence-package storage separately because the six selected JPEG frames can be larger than the
video snippet.

### 2.6 Distinguish requested and actual frame rate

`video_capture.max_nominal_frame_rate` is a limit. It is not the actual encoded rate.
`video_snippet.nominal_frame_rate` must describe the encoded stream when it is present. The snippet
duration and end offset must agree with the encoded media within a documented tolerance.

Use a target-time sampling schedule that does not accumulate drift. Select one camera frame for each
15 fps target time. Account for common 30 fps and 29.97 fps source rates and timestamp rounding. Do
not duplicate frames to claim a higher rate when capture or conversion cannot supply distinct
frames.

Configure a stable camera source rate of at least 30 fps when the selected device format supports
it. Preserve the measured source rate when the device uses a fallback. The encoder frame-rate
setting remains a compression hint and must not be the source of manifest metadata.

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
M5 revisits the 640×360 transport choice after live evidence showed that collection must retain
more motion detail for later analyzer experiments.

Acceptance:

- the selected format decodes with the local iOS and backend toolchains;
- the fixture is small enough for ordinary tests;
- all canonical evidence fixtures use V2;
- no dual V1/V2 runtime path remains;
- missing optional snippet evidence remains distinct from a corrupt declared snippet.

### M1 — Backend round trip — Complete

1. [x] Accept and validate the V2 multipart fixture.
2. [x] Persist snippet bytes atomically with the manifest and frames.
3. [x] Return metadata and byte-identical media.
4. [x] Add idempotency, size-limit, hash, unsupported-media, truncation, and rollback tests.

Progress (2026-08-27): Added local FFmpeg probing with decoded-frame checks, atomic snippet
read-back, safe metadata and media routes, and backend regression coverage for accepted and
rejected video packages.

Acceptance:

- accepted snippet bytes read back with the original SHA-256;
- corrupt or unsupported media is rejected before commit;
- migrated frame-only V2 backend tests pass;
- tests need no external service.

### M2 — Deterministic iOS replay capture — Complete

1. [x] Feed the checked-in source through the replay path.
2. [x] Create the bounded snippet around a scripted event proposal.
3. [x] Create the selected frames and one V2 manifest.
4. [x] Verify timing, hashes, technical metadata, and queue recovery.

Progress (2026-08-27): Added deterministic midpoint replay capture with a bounded H.264/MP4
writer, explicit frame-only fallback on capture failure, durable video storage, multipart upload,
and local backend byte-identical read-back verification.

Acceptance:

- [x] repeated replay produces equivalent semantic metadata;
- [x] encoded bytes pass the backend probe and upload fixture tests;
- [x] capture and encoding do not block the main thread;
- [x] a failed snippet still produces an explicit frame-only V2 package when frames are usable.

### M3 — Live capture integration

1. [x] Add the bounded rolling capture path to the camera session.
2. [x] Finalize snippets for confirmed causal event proposals.
3. [x] Enforce queued-byte and temporary-storage limits.
4. [x] Show snippet status in diagnostics.

Progress (2026-08-27): Added a resized H.264/MP4 rolling buffer fed by every live camera frame,
event-time capture requests with bounded post-event waiting, explicit stop and storage failures,
queued-byte enforcement, and live diagnostics for buffer, temporary storage, and package outcomes.
The frame-only path remains active beside the optional snippet path.

Acceptance:

- [x] the existing frame-only UI and uploads still work;
- [x] one live proposal creates one bounded package;
- [x] cancellation and low-storage paths release temporary resources;
- [x] no unbounded sample buffer exists.

### M4 — Live cadence and media-metadata correction

Evidence package `da5a9fc7-2c9c-4e8e-a741-5bc0c0bb2165` exposed a live-path defect. Its manifest
declares 15 fps, but its MP4 contains 21 distinct frames at 100 ms intervals. The encoded stream is
10 fps. Its six selected frames remain 1920×1080.

1. [x] Add a deterministic 30 fps input test that reproduces the 10 fps output.
2. [x] Replace elapsed-time threshold sampling with a 15 fps target-time schedule.
3. [x] Add 29.97 fps, timestamp-rounding, backward-timestamp, and short-gap tests.
4. [x] Replace the single in-flight conversion gate with a bounded serial conversion pipeline.
5. [x] Allocate converted buffers from a reusable pool and release them after the rolling window and
   all active captures no longer need them.
6. [x] Record separate counts for rate-limited frames, frames replaced before conversion, conversion
   failures, and accepted frames.
7. [x] Calculate actual rate, duration, start offset, and end offset from the samples and completed
   media. Do not copy the configured maximum rate into the snippet manifest.
8. [ ] Make backend probing reject material disagreements between declared and encoded dimensions,
   duration, and frame rate.
9. [x] Show the measured rolling-buffer rate and frame-drop counts in iOS diagnostics.
10. [ ] Configure the camera for a stable supported source rate and report the selected or fallback
    rate.

Progress (2026-08-27): Added fixed target-time cadence selection with deterministic tests for 30 fps,
29.97 fps, rounded timestamps, backward timestamps, and short gaps. Live conversion now uses a
bounded serial queue, a reusable pixel-buffer pool, separate cadence counters, and encoded-media
metadata for the V2 snippet manifest. The iOS diagnostics show the measured rolling rate and the
separate frame counters. Camera source-rate selection and backend disagreement tests remain.

Acceptance:

- a two-second synthetic 30 fps input produces 30 or 31 distinct output frames near 15 fps;
- a 29.97 fps input remains within one output frame of the expected count;
- the manifest rate and duration agree with the encoded MP4 within the tested tolerance;
- a slow converter causes a measured lower actual rate, not a false 15 fps declaration;
- capture queues and raw buffers remain bounded under concurrent event proposals;
- the 8 Hz inference sampler does not limit video-snippet cadence.

### M5 — Exploratory resolution profile

1. [ ] Add a configurable encoder bitrate instead of the fixed 400 kbit/s setting.
2. [ ] Change the exploratory live profile to 960×540, 15 fps, and the bounds in section 2.5.
3. [ ] Update Swift and Python contracts, fixtures, and tests in the same change.
4. [ ] Verify that the raw rolling-buffer capacity can hold the required pre-event and post-event
   samples at 960×540 before live capture starts.
5. [ ] Fail explicitly when a configured profile cannot satisfy required coverage within its memory
   bound.
6. [ ] Create 640×360 and 960×540 derivatives from the same representative source snippets.
7. [ ] Record encoded size, peak temporary memory, encode latency, decode latency, and visible card
   detail for both profiles.
8. [ ] Keep 960×540 as the accepted source profile unless measurements show no useful difference or
   unacceptable device cost.

Acceptance:

- a supported iPhone holds the complete rolling window at 960×540 without an unbounded allocation;
- one event proposal produces a complete snippet within the 750,000-byte bound;
- the accepted snippet keeps enough visible corner and card detail for plan 0022 experiments;
- the comparison uses the same source times and does not infer quality from unrelated packages;
- any change back to 640×360 or up to 1920×1080 records measured analyzer or device evidence.

### M6 — Local end-to-end measurement

1. [x] Capture and upload an initial real V2 package on a supported iPhone.
2. [x] Verify its selected frames and snippet decode.
3. [ ] Capture at least three corrected 960×540 packages with different card transitions.
4. [ ] Verify each package through byte-identical iOS-to-backend read-back.
5. [ ] Record actual size, frame count, frame rate, duration, timing coverage, peak memory, encode
   latency, upload latency, and storage use.
6. [ ] Replay each snippet in a minimal human-review view.
7. [ ] Record whether 960×540 reveals useful card detail that is absent from a derived 640×360
   version.

Acceptance:

- the real package survives byte-identical iOS-to-backend transport;
- the snippet shows the transition covered by the selected frames;
- the manifest agrees with the encoded media;
- device measurements confirm or revise the exploratory capture bounds;
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
- live sampling produces the intended cadence without timestamp aliasing;
- snippet metadata describes the encoded media rather than only configured limits;
- new exploratory snippets use the measured 960×540 profile within bounded memory and storage;
- backend ingestion verifies bytes and supported media before atomic commit;
- selected frames remain available beside the snippet;
- corrected real-device packages complete the local round trip;
- plan 0022 has measured evidence for transition and tracking experiments.
