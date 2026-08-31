# Local visible-card detector end-to-end PoC

## Plan status

- **Summary:** Fine-tune one local visible-card detector from cached Gemini proposals and run it as
  an alternative to Gemini visible-card detection in the normal round-analysis path.
- **Status:** Ready
- **Depends on:** Completed plans 0020, 0021, 0027, 0032, and 0034, and the implemented exact-event,
  visible-card provider, and observation contracts from plan 0022
- **Builds on:** Plan 0022 exact-event frames and cached Gemini visible-card result artifacts
- **Outcome:** Prove one complete path from pseudo-label materialization through CUDA fine-tuning,
  bundle loading, local inference, backend selection, and persisted table observation. Detection
  quality is not an acceptance condition.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Purpose

Add `LocalVisibleCardProvider` as a peer of `GeminiVisibleCardProvider`. Select the visible-card
provider through backend configuration. Keep Gemini as the default provider and keep the existing
Gemini visual card identity classifier in both modes. This plan changes card finding only.

The proof of concept succeeds when one fine-tuned local bundle loads on the target Mac and one real
evidence package reaches a terminal result through the normal backend worker and persistence path.
The result can contain bad boxes, no boxes, or insufficient evidence.

Gemini boxes are proposals, not ground truth. The reviewed `card_played` event supplies the trusted
event time. Gemini supplies pseudo-label boxes for the frame at that time. Plan 0038 owns human box
review and the first quality comparison.

## 2. Model choice

Use `RFDETRLarge` from `rfdetr==1.9.4` with the official `rf-detr-large.pth` pretrained checkpoint:

- task: one-class object detection with class `visible_card`;
- input: the complete exact-event frame and the model's standard 704 x 704 preprocessing;
- target: axis-aligned boxes;
- training: one explicit CUDA device on RunPod;
- local inference: native PyTorch on explicit `cpu` or `mps`, with no silent device fallback;
- output: the package's end-to-end detections at one frozen confidence threshold, with no added
  non-maximum suppression;
- experiment bound: one model variant, pretrained checkpoint, dataset, split, seed, and fixed epoch
  count. Do not run a sweep or change the published architecture, loss, or default augmentation.

RF-DETR is a current state-of-the-art real-time detector family with a supported fine-tuning API.
The official benchmark reports RF-DETR Large at 56.5 COCO AP, 6.8 ms on its declared T4 TensorRT
benchmark, 33.9 million parameters, and 704 x 704 input. Large is the highest-accuracy core variant
under Apache 2.0. Do not use the larger PML-licensed variants. The larger input is useful for small
cards, while the packaged training and native PyTorch inference paths keep this work out of research.
See the [RF-DETR paper](https://arxiv.org/abs/2511.09554),
[official model table](https://github.com/roboflow/rf-detr), and
[`rfdetr` 1.9.4 release](https://pypi.org/project/rfdetr/1.9.4/).

Pin the full dependency set in the package lock. Record the pretrained checkpoint digest. Tests
must use generated data and local test doubles. They must not download model weights.

## 3. PoC scope

The plan includes only:

1. a small COCO-format dataset view over existing exact-event frames and cached Gemini results;
2. one frozen RF-DETR fine-tuning recipe and one CUDA run;
3. one native PyTorch bundle and local provider adapter;
4. explicit `gemini` or `local` backend selection; and
5. one real evidence-package run through the normal backend path.

The plan does not include human box review, a quality gate, model comparison, threshold tuning,
model promotion, identity-model changes, offline round analysis, ONNX or CoreML export, quantization,
compilation, batching, worker concurrency, or a generic training framework. Create a follow-up plan
only if measured evidence requires one of these changes.

## 4. Pseudo-label slice

Reuse the exact-event frame and cached Gemini result artifacts from plan 0022. Do not add another
source extraction or provider-result contract.

Select 20 complete frames in a deterministic order. Add frames only when needed to put non-empty
examples in both splits and represent at least three source-lineage groups. Use 40 frames as a hard
cap. Keep valid empty Gemini results as empty pseudo-label frames. Exclude unavailable or malformed
results with a recorded reason. Exclude the system holdout. Stop if the slice cannot meet these
conditions within the cap.

Freeze train and validation membership by session or a stricter source-lineage group. The manifest
must identify each source asset, event, frame digest, Gemini request and result digest, converted
pixel boxes, split, and allowed use. It must label every target as an unreviewed pseudo-label and
must not satisfy a reviewed-reference contract.

This slice proves data flow and fine-tuning only. It does not claim useful coverage.

## 5. Bundle and provider contract

The bundle is one directory with:

- the selected native RF-DETR checkpoint;
- a manifest with the bundle schema version, file digests, model variant, class map, package and
  dependency versions, preprocessing, confidence threshold, dataset and split digests, recipe,
  seed, code revision, and training device; and
- quality state `unreviewed`.

`LocalVisibleCardProvider` must accept the existing `VisibleCardRequest` and return the existing
`ProviderResult`. It loads one explicit bundle at backend startup, converts each pixel box to the
existing normalized box and four-corner polygon, uses `side=unknown` and `label=visible_card`, and
records detector scores, device, and bundle identity in `raw_response` and latency in `latency_ms`.
Load, decode, and inference failures return an explicit unavailable result.

Do not change `TableObservation`, `VisibleCardTableAnalyzer`, or the visual card identity contract
for the model.

## 6. Delivery milestones

### M0 — Materialize the PoC dataset and recipe

- Add a narrow command that converts existing exact-event frames and cached Gemini results into the
  bounded COCO dataset and manifest.
- Freeze one RF-DETR Large recipe, split, seed, epoch count, and confidence threshold.

Acceptance:

- repeated fixture runs produce the same manifest and dataset digest;
- one real-data run selects no more than 40 non-system-holdout frames;
- train and validation groups do not overlap;
- each included box links to its frame and Gemini result digest; and
- the output cannot pass as reviewed reference data.

### M1 — Fine-tune and bundle one detector

- Add the smallest adapter needed to invoke the pinned RF-DETR package with the frozen recipe.
- Run it once on an explicit RunPod CUDA device and select the declared final checkpoint.
- Write the bundle and a run record with resolved inputs, environment, finite-loss confirmation,
  checkpoint digest, and failure details when applicable.

Acceptance:

- a generated fixture verifies dataset-to-training argument mapping without downloading weights;
- the documented RunPod command uses only declared mounted inputs and output paths;
- the real run finishes with a checkpoint whose weights differ from the pretrained input, or writes
  a complete failure record; and
- the bundle manifest validates all file digests before load.

### M2 — Add the local provider

- Load the native bundle on explicit CPU or MPS.
- Adapt RF-DETR detections to the existing provider result.
- Add deterministic tests for empty detections, one detection, several detections, invalid input,
  bundle validation failure, and inference failure.

Acceptance:

- the provider passes the existing provider contract tests;
- one fixture result contains valid normalized geometry and bundle provenance;
- CPU inference loads and runs one real frame on the target Mac;
- MPS inference is exercised when available and any unsupported operation is reported, not silently
  moved to CPU; and
- failure returns an unavailable result without crashing the analyzer.

### M3 — Select the provider in the backend

- Add a `gemini` or `local` visible-card provider setting. Keep `gemini` as the default.
- Require a local bundle path and explicit local device for `local`.
- Keep the Gemini identity classifier and its credential requirement in both modes.
- Run one stored real evidence package through the normal worker and persistence path.

Acceptance:

- backend tests prove both provider selections without network calls;
- Gemini mode keeps current behavior;
- local mode does not call `GeminiVisibleCardProvider`;
- one fixture analysis persists a schema-valid table observation;
- one real analysis reaches a terminal state with the local provider; and
- the run record includes load time and one-frame inference time and states that they are not a
  latency or quality evaluation.

## 7. Verification

Run the focused analyzer and backend tests, Ruff, formatting, and the local fixture flow. Record the
exact data, training, and backend commands. Do not compare or promote the bundle.

## 8. Stop conditions

Stop and record the blocking artifact when:

- the existing exact-event and cached Gemini artifacts cannot produce the bounded slice without a
  new source-data contract;
- the pinned RF-DETR package or pretrained checkpoint cannot run on the declared Python, CUDA, or
  target-Mac CPU environment; or
- local provider integration requires a change to `TableObservation` or the identity contract.

An MPS failure does not block the PoC when explicit CPU inference works. Bad detector output is not
a stop condition.
