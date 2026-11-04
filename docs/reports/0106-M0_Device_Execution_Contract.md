# Epic 0106 M0: Device execution contract

Date: 2026-11-04

## Decision and current boundary

Run the pipeline in the iOS app, without a backend. The existing `CardEventProbe` app targets
iOS 18 and already has camera sampling, a causal decoder, a movie writer, a prediction sidecar,
local stores, and diagnostic views. Its recording workflow currently expects a ready backend and
its analysis clients call that backend. These are starting points, not an on-device pipeline.
The Swift package tests cover only package-compatible code; an Xcode app build is a separate check.

The [0105 contract](0105-M0_Execution_Contract.md) is the reference for stage order, automatic
inputs, and terminal states. Each device stage must consume only outputs of this run. Keep
revision identifiers, source digests, configuration and parent identifiers in a local manifest.
Use the existing schemas and deterministic Python fixtures as the reference for the ports. The
ports below are implementation work, not existing capabilities or proven mobile performance.

## Frozen model inputs

The following packages were present under the primary checkout's ignored `.runtime` directory
and their directory digests were verified for this milestone. Hash sorted relative file paths,
then a NUL byte and each file's bytes, as in `scripts/0103_m3_export_cardeventnet.py`. Copy the
packages into an ignored local build input, check these digests before compilation, and record both
the source package digest and compiled model identity in each run. Do not commit packages.

| Model | Runtime package | Directory SHA-256 | Device input and output |
| --- | --- | --- | --- |
| CardEventNet | `0103-m3/cardeventnet.mlpackage` | `b3f41726c2029e6047bd9ea04ab742fc55868e815f2601410dc266a8ca736bfd` | Float32 `[1,8,3,224,224]`; one logit. RGB full-frame letterbox and ImageNet normalization. |
| RF-DETR | `0104-m1/rfdetr-seg-medium.mlpackage` | `425ec4edeaed510743778229c2d03b6ef3fa727e5c182f50b2e8336b63916947` | Float32 RGB `[1,3,432,432]`, bilinear resize without antialias and ImageNet normalization; boxes `[1,200,4]`, class logits `[1,200,3]`, masks `[1,200,108,108]`. |
| DINOv3 | `0104-m2/dinov3-identity.mlpackage` | `5e3af365eb1d0e7dd3543011a17189f68741dae926c3ec25e09c0fef358b1c25` | Float32 RGB `[1,3,224,224]`, Lanczos letterbox and ImageNet normalization; 25 logits. Freeze the target map, temperature `0.6487642659364355`, and review threshold `0.8235859761473482` from the source bundle. |

The bundled `CardEventNetTransitionV2` and its default decoder settings are not assumed to be
identical to the frozen 0103 package. M1 must wire and verify the frozen model and its own decoder
configuration: threshold `0.4271905720`, confirmation 0.125 s, gap 0.625 s. The existing decoder's
default threshold is `0.4996626377105713`. Record the explicit values in the run. The RF-DETR
package has the [documented threshold-free parity gap](0104-M1_RF-DETR_Export_Followup.md);
the user accepted it for the PoC. DINOv3 passed only the
[two frozen Mac crops](0104-M2_DINOv3_Core_ML_Export.md). CardEventNet's
[frozen sample](0103-M3_CardEventNet_Core_ML_Export.md) emitted no event. None proves iPhone
performance or model quality.

## Capture and time contract

Request 30 fps, record the actual selected rate and fallback. The inference sampler accepts at most
one frame per 0.125 s and drops frames when inference is busy. The causal model selects its eight
frames at offsets -1.4 to 0 s in 0.2 s steps from available earlier samples; early history repeats
the earliest sample. Freeze model and decoder parameters at recording start. Reset both at the
start and after any invalid or non-monotonic timeline; a discontinuity fails this recording instead
of silently joining separate timelines. Count received, written, sampling and busy drops.

The camera sample presentation timestamp is the common source clock. The first accepted movie
frame defines source time zero; persist its exact rational `CMTime` and every written frame's
relative presentation time, along with orientation, dimensions and video transform. Reject events
whose peak or emission precedes zero. On stop, drain in-flight inference, flush one pending peak,
then finalize the movie and sidecar. Record the peak, emission time, probability and stable event
ID; the decoder emits points, not measured action intervals. Represent each point as a zero-length
`start_us = end_us = peak` proposal, preserving the original rational times separately. This matches
the local event adapter's point conversion. Do not infer an action duration.

For the 0105 default extraction policy use `start_us`, offset zero. From the finalized movie select
the decodable frame with the nearest presentation time to the peak; ties select the earlier frame.
Persist requested and actual presentation times, frame index, image digest, orientation and absolute
delta. Use presentation timestamps, not `round(time * fps)`, because capture and writer can drop
frames. If no frame exists within 0.125 s, retain the event and fail the visible-card stage with the
mapping error; never silently substitute a different frame. Apply the stored video transform once
before all image models and geometry, and persist the resulting image dimensions. Lock orientation
for one recording; an orientation change or capture interruption stops and marks it interrupted.
M1 must prove the writer's first accepted time and this mapping with a variable-rate fixture; current
writer behavior alone does not prove the contract.

## Stage map and fixture obligations

| Stage and milestone | Device implementation and retained handoff | Required checks |
| --- | --- | --- |
| Events, M1 | Adapt `CameraSession`, `FrameInferenceCoordinator`, `CausalEventDecoder` and `TrainingRecordingCoordinator`; remove the backend readiness dependency for this workflow. Persist the finalized movie, point event revision, model identity, configuration and timing map. | Deterministic timestamp, early-history, decoder flush, delayed inference, dropped writer frames, orientation, interruption, empty events and reopen tests. |
| Visible cards, M2 | Use AVFoundation frame extraction, then port the local RF-DETR preprocessing, class/score filtering, box and mask postprocessing and polygon generation. Persist an event-keyed complete `visible_cards` revision and image provenance. Freeze extraction policy, class map and thresholds from the 0105 request. | Compare all six 0103 frames with the frozen reference and report threshold-free and above-threshold differences separately. Test masks, coordinate transforms, zero detections and missing frames. |
| Calibration and scenes, M2 | Port `card_plane_calibration.py`, `card_plane_calibration_refinement.py`, `proposed_card_scene_processor.py` and `card_scene_joint_fit.py`, including their NumPy/OpenCV operations, to a locally built iOS-compatible implementation. Persist calibration candidate, published calibration only when valid, per-frame scene outcomes and fit diagnostics. Identity does not consume scene poses. | Compare fixed detector inputs, calibration and scene results with Python, including empty, insufficient calibration, partial scenes and failure. OpenCV packaging, numerical tolerances and device cost are unverified implementation risks; do not replace the required stage with a placeholder. |
| Identity and observations, M3 | Port the automatic predicted-visible-region crop and DINOv3 postprocessing from the local identity processor. Preserve crop transform, logits, calibrated probabilities, class map, abstentions, `FACE_DOWN` and item errors. Assemble `table_observations` from the exact event, visible-card and identity revisions, using the existing schema. | Compare the two frozen crop tensors and all outputs, rankings and decisions with 0104. Test unusable and empty crops, partial probabilities, face-down and empty observation assembly. |
| Analysis, M4 | Port `game_engine/src/game_engine/reconstruction.py` and its rules and dependencies, plus the adapter in `operations/src/doko_operations/round_reconstruction_execution.py`, to on-device code. Persist search settings, intermediate outcomes and round analysis. | Compare deterministic complete and failing fixtures against Python, including missing round facts and empty observations. No Python backend is available on the device. |
| UI and export, M5 | Adapt the recording workspace and local stores to collect inputs, show stage progress and failures, reopen runs and export their bundles. No network readiness gate. | Component/app tests cover a complete fixture run, missing input, failure, restart and exported bundle. |
| Device trial, M6 | Execute capture through analysis on a real iPhone and compare the same saved inputs with 0105 M4. Retain device, OS, timing, memory and thermal observations, counts and discrepancies. | Run package and app checks, fixed model comparisons and a bounded device trial. A blocked or partial run is evidence, not an end-to-end success. |

Before processing require a session, four active players, dealer, first-trick leader, rules version
and search limits, with their explicit relationships validated as in 0105. Never invent round
facts. Recording may start before these are entered; processing cannot. Staged activity can test
capture and intermediate stages, but does not become a canonical round. A complete analysis trial
requires a valid round setup accepted by 0105.

## Failure, limits and diagnostics

A complete empty event revision proceeds to an empty visible-card revision. An empty visible-card
revision proceeds only if calibration and scene processing can return a complete result; failure to
publish required calibration stops stage 3. Empty identity is valid. Empty observations are retained,
but analysis fails with its cause. Any partial, missing or failed required output stops downstream
stages and leaves completed outputs intact. An interruption marks the active stage interrupted;
reopen preserves evidence, and a new run or explicitly verified resume must not overwrite it.

Use one active capture and one processing stage at a time. For the first PoC cap a recording at
10 minutes, 2 GiB of app-managed run storage, 100 event proposals and 100 MiB of diagnostics apart
from the movie and stage outputs. Check at least 1 GiB free before capture; stop safely and retain
partial evidence when any cap or write failure occurs. These are development bounds, not measured
device capacity. Do not delete runs automatically: show storage usage and provide explicit deletion.
Avoid buffering a full recording or all model tensors in memory; release each frame and model output
after its retained stage result. M2 must measure and report geometry runtime and memory before M6.

Each run bundle contains a versioned manifest and frozen inputs; recording and source timeline;
model source and compiled identities; event and frame mapping; each stage request, parent IDs,
outputs, status and failure; final analysis when present; per-stage elapsed time, frame/drop counts,
peak memory and thermal observations where available; device/OS/app version; and `run.log`.
Write manifest and stage results atomically. Keep partial files and their error visible. Export as
one archive without requiring the backend. The movie can contain people and speech: export it only
as part of the explicit diagnostic action, and avoid personal data in text logs.

Use UTF-8 log lines of the form `UTC_ISO8601 level run=<id> stage=<name> message`, with stage start,
finish, counts, duration, warnings and actionable errors. Aggregate sampling and frame drops; do not
log every frame. Never treat generated proposals or diagnostic overlays as reviewed ground truth.

## M0 result

M0 is complete as an execution and port contract. M1 can start with the local recording and event
stream. The geometry and reconstruction ports, model build integration, device resource behavior,
and the completed 0105 M4 comparison remain unverified prerequisites for a full trial, not claims
that the full pipeline is currently runnable.
