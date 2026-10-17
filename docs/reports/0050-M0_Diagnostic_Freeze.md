# 0050 M0 diagnostic freeze

Date: 2026-10-17

## Decision

Freeze the retained 0090 inputs, outputs, implementation contracts, and M4 budget for the 0050 diagnostic. M0 used deterministic local inspection only. No processor or model stage ran, and no runtime code changed. The machine-readable companion records all source and reference revisions, the nine original requests and states, their file hashes, and output revision hashes.

## Retained evidence

The baseline is the 0090 freeze at source revision `41532a756`. The nine run request and state records are preserved in the [machine-readable freeze](0050-M0_Diagnostic_Freeze.json), each with a SHA-256. Output content hashes were checked against their revision manifests. The three fixed recordings and reviewed references remain unchanged.

| Recording | Event run / output revision | Detector run / output revision | Scene run / output revision |
| --- | --- | --- | --- |
| `cardeventnet-IMG_0657` | `coord-d991572cdb65618247c1` / `events-coord-d991572cdb65618247c1-attempt-1` | `coord-07d852bb91cfc6b19f7a` / `visible-cards-coord-07d852bb91cfc6b19f7a-attempt-1` | `coord-3c10c8bdaa3a72b0c361` / `card-scene-proposals-coord-3c10c8bdaa3a72b0c361-attempt-1` |
| `cardeventnet-IMG_0662` | `coord-08c097cc5f1b4024e867` / `events-coord-08c097cc5f1b4024e867-attempt-1` | `coord-aa2ab2751f97e23f4dd2` / `visible-cards-coord-aa2ab2751f97e23f4dd2-attempt-1` | `coord-20c6e5e069cd8c74a97b` / `card-scene-proposals-coord-20c6e5e069cd8c74a97b-attempt-1` |
| `game-2026-08-20-01-001` | `coord-adf623bae2f082065bba` / `events-coord-adf623bae2f082065bba-attempt-1` | `coord-d7821eb650044d5b3606` / `visible-cards-coord-d7821eb650044d5b3606-attempt-1` | `coord-d0e13247e47284a18828` / `card-scene-proposals-coord-d0e13247e47284a18828-attempt-1` |

The retained producer source revision is `41532a756`; the M0 parent revision is recorded in JSON. M4 must record the exact implementation revision and per-processor digests after M1–M3. Event, RF-DETR 0092 M4, and DINOv3 0088 M6 model digests, extraction versions, crop policy, and prior frozen policies are copied from the 0090 freeze. M6 remains unqualified; identity predictions require human review.

## Unsupported frames

The scene revision marks 19 frames unsupported with `no model polygon produced an initial fixed-size card pose`. Every one has zero individual-card candidates. Piles are separate detector outputs. These are detector outcomes; they do not establish that the image has no cards.

| Recording | Frame IDs | Cards | Piles | Detector status |
| --- | --- | ---: | ---: | --- |
| `cardeventnet-IMG_0657` | `event-000004`, `event-000005`, `event-000010`, `event-000011`, `event-000021`, `event-000029`, `event-000033`, `event-000042`, `event-000051` | 0 each | 1, 0, 0, 0, 0, 0, 0, 0, 0 | detected, empty |
| `cardeventnet-IMG_0662` | `event-000011`, `event-000030`, `event-000031`, `event-000040`, `event-000041`, `event-000042`, `event-000047`, `event-000051` | 0 each | 1, 2, 2, 2, 2, 3, 3, 3 | detected |
| `game-2026-08-20-01-001` | `event-000030`, `event-000040` | 0 each | 0, 1 | detected, empty |

The first recording has 9 unsupported frames (1 pile-only, 8 empty); `IMG_0662` has 8 pile-only frames (1–3 piles each); the real round has 2 frames (one empty, one with 1 pile). No candidate-bearing frame has a failed pose suggestion or failure reason. Calibration diagnostics have no failed or unavailable gates. The `held_out_boundary` gate is false for `IMG_0657` and the real round and true for `IMG_0662`. This is recorded separately from frame failures. M1–M3 must preserve true calibration failures as blockers.

## Decoded-image comparison

Pair by source video hash, decoded image hash, frame index, presentation timestamp, dimensions, content type, decoder, transform, output encoding, extraction policy, and schema version. Only `requested_time_us` may differ. Preserve both full identities and event IDs. Reject any other identity mismatch. This is a comparison-only rule; revision lineage, crop authority, cache keys, and mutation checks stay strict.

| Recording | Predicted frames | Reviewed frames | Shared decoded images |
| --- | ---: | ---: | ---: |
| `cardeventnet-IMG_0657` | 52 | 51 | 0 |
| `cardeventnet-IMG_0662` | 52 | 50 | 2 |
| `game-2026-08-20-01-001` | 43 | 49 | 0 |

The two `IMG_0662` matches are byte-identical decoded JPEGs. All identity fields other than request time agree:

| Predicted event | Reviewed item | Frame | Presentation time | Predicted / reviewed request time (us) | Image SHA-256 |
| --- | --- | ---: | ---: | ---: | --- |
| `event-000002` | `cardeventnet-event-img_0662-002` | 300 | 5005000 us | 5000000 / 5004836 | `bfc307c47fcb232270eed4b37b12c926bc1bd68cc192442bc660bdef88fbbcd0` |
| `event-000003` | `cardeventnet-event-img_0662-003` | 375 | 6256667 us | 6250000 / 6256044 | `f9a4fc3dc5f4460fa649b73882325db422544d53b739be93572fb7639805565f` |

`IMG_0657` and the real round have no shared decoded image hashes. These two `IMG_0662` matches do not support a three-recording detector quality claim. M1 must report coverage denominators beside scores, use polygon IoU `0.5`, keep card and pile metrics separate, treat unpaired reviewed frames as uncovered rather than misses, and exclude unpaired predictions from that quality scope.

## Zero-card and downstream contracts

- A successful detector result with zero individual-card candidates needs no card pose. Preserve pile regions separately and state that no cards were detected. Do not claim reviewed absence.
- Failed or unusable detector results remain failures.
- In a mixed recording, keep calibration and fitting requirements for frames with card candidates. In a recording with no such candidates, do not invent calibration or run pose fitting to create an empty result.
- Identity does no crop extraction or model work for zero-card frames. Observation assembly keeps frame/event coverage and pile evidence under existing contracts.
- Missing or failed upstream evidence cannot become an empty success or gameplay assertion. Real calibration, crop-authority, pose, source, or lineage failures stop dependent work.

## M4 execution budget and preflight

M0–M3 use artifact inspection and local fixtures only. Do not run model or processor inference. Use retained 0090 revisions without rewriting selections or substituting missing source assets. M1–M3 may run focused local tests for changed code. Do not make cloud requests, train or tune models, use alternate providers, or promote a model.

- Three fixed recordings. Reuse all retained event and detector outputs; allow zero new event or detector inference runs.
- At most one new scene, identity, and observation execution per recording: nine executions total. Allow at most one reconstruction run for the real round if trusted complete round context exists.
- Six hours total wall time, 32 GiB peak process memory, and zero cloud requests.
- Resume only unchanged durable work with the exact same request and inputs. Failed preflight starts no stages. A terminal failure blocks dependants for that recording; other recordings may continue. No undeclared retry or model substitution.
- Do not use sealed holdout data. Keep the 0090 protected exclusions. Do not add manual annotation or collection.

The two available staged source videos match their frozen SHA-256 values. Preflight found all three model artifacts at their frozen paths. The real-round video is missing at `data/intake/recordings/game-2026-08-20-01-001/videos/video-game-2026-08-20-01-001.mov`; its required SHA-256 is `2464d0e65547b2db31ea5ca49f4d57cefcb999e34cbacec7e7cca8ee9d549faa`. This blocks M4 until that exact source is restored and verified. Do not substitute another video or retained frames.

## M1 handoff

Start with `backend/src/dokodetector_backend/pipeline_comparison_service.py` and `operations/src/doko_operations/pipeline_comparison_execution.py`; add focused cases in `backend/tests/test_pipeline_comparison_api.py`. Use local fixtures based on the retained revisions; do not execute processors.

Expected pairs:

- `IMG_0662`: `event-000002` with `cardeventnet-event-img_0662-002` at frame 300; request times 5,000,000 and 5,004,836 us.
- `IMG_0662`: `event-000003` with `cardeventnet-event-img_0662-003` at frame 375; request times 6,250,000 and 6,256,044 us.
- Reject changed source, pixels, frame location, dimensions, decoder, transform, encoding, policy, or schema. Preserve original provenance and counts.
- Expect zero shared images for `IMG_0657` and the real round. Do not claim detector quality from only two shared images.

Publish `docs/reports/0050-M1_Frame_Comparison_Correction.md` and add a dated correction and link to the 0090 M3 report without rewriting its original results. M1 covers comparison only; keep crop and lineage checks strict. All later milestones remain unstarted.

## Verification

The JSON parses. Retained frame revisions reproduce the 19 zero-card cases and exactly two decoded-image pairs. Revision content hashes agree with their manifests. No inference ran and no runtime file changed.
