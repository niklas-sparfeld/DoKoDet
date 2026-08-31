# Local visible-card detector end-to-end PoC

## Plan status

- **Summary:** Fine-tune one local visible-card detector from cached Gemini proposals and run it as
  an alternative to Gemini visible-card detection in the normal round-analysis path.
- **Status:** In Progress
- **Depends on:** Completed plans 0020, 0021, 0027, 0032, and 0034, and the implemented exact-event,
  visible-card provider, and observation contracts from plan 0022
- **Builds on:** Plan 0022 exact-event frames and cached Gemini visible-card result artifacts
- **Outcome:** Prove one complete path from pseudo-label materialization through CUDA fine-tuning,
  bundle loading, local inference, backend selection, and persisted table observation. Detection
  quality is not an acceptance condition.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete for the fixture path — add bounded COCO pseudo-label materialization, provenance
  validation, and the frozen RF-DETR Large recipe. The real-data exercise waits for the required
  exact-event extraction and cached-result inputs.
- **M1:** Complete for the fixture path — add the pinned RF-DETR adapter, explicit training
  arguments, failure receipts, and digest-checked native bundle. The real CUDA run waits for a
  materialized real slice and mounted pretrained checkpoint.
- **M2:** Pending — add the local visible-card provider.
- **M3:** Pending — select the provider in the backend and run the end-to-end path.

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

#### M0 implementation evidence — 2026-08-31

- Added `table-analyzer data materialize-visible-card-dataset` with an alias named
  `materialize-visible-card`. It reads `annotation-evidence-extraction/v1` packages and
  `visible-card-run/v1` or `visible-card-cache/v1` artifacts without copying source frames.
- The command selects 20 frames in stable order and adds only the frames needed to represent at
  least three source-lineage groups and non-empty pseudo-label examples in both partitions, with
  a hard cap of 40. It excludes system holdout, incomplete, unavailable, malformed, missing, and
  ambiguous inputs with recorded reasons.
- It writes `annotations.json`, `dataset-manifest.json`, `split.json`, and `recipe.json`. The
  manifest stores source asset, event, frame, Gemini request and result digests, normalized boxes,
  converted pixel boxes, split, allowed use, and the `unreviewed_pseudo_label` state. It cannot be
  loaded as a reviewed-reference manifest.
- The recipe freezes RF-DETR Large, `rfdetr==1.9.4`, `rf-detr-large.pth`, 704 × 704 input, one
  CUDA device, 20 epochs, seed 37, and a 0.5 confidence threshold. The checkpoint file digest is
  resolved and recorded by M1 when the mounted pretrained input is materialized.
- Verification: all 59 table-analyzer tests, focused Ruff checks, CLI help, and whitespace checks
  pass. A real-data run was not possible from the available inputs: the untracked backend data
  has no exact-event extraction manifest and its cached requests cover one source-lineage group;
  the command therefore stops before producing an invalid training slice.

Acceptance:

- repeated fixture runs produce the same manifest and dataset digest;
- one real-data run selects no more than 40 non-system-holdout frames;
- train and validation groups do not overlap;
- each included box links to its frame and Gemini result digest; and
- the output cannot pass as reviewed reference data.

#### M1 implementation evidence — 2026-08-31

- Added `table-analyzer train-visible-card-detector` with a `train-visible-card` alias. The
  command accepts only the materialized dataset, evidence root, mounted pretrained checkpoint, and
  output directory, with `--runner fixture` for local contract tests and `rfdetr` for the CUDA run.
- The adapter verifies the M0 dataset, split, COCO digest, source-frame digests, recipe digests,
  and mounted pretrained checkpoint before training. It stages RF-DETR's `train` and `valid` COCO
  views with symlinks to source frames, so the source media stays in the mounted input.
- The real runner uses `RFDETRLarge`, `rfdetr==1.9.4`, one class, 704 × 704 input, 20 epochs,
  `cuda:0`, and the declared `checkpoint_best_total.pth`. It confirms finite numeric losses and
  rejects a checkpoint identical to the pretrained input.
- Every run writes `run.json`, including resolved input digests, model and training arguments,
  environment, loss confirmation, checkpoint digests, bundle identity, and failure details when
  the run cannot complete. The bundle stores the native checkpoint and a manifest with file
  digests, recipe, dependency versions, dataset and split digests, `quality_state: unreviewed`,
  and a manifest digest. The loader validates all declared file digests before returning the
  checkpoint path.
- Added the optional `training` dependency group and lock entries for `rfdetr[train,augment]==1.9.4`
  and its training dependencies. The documented RunPod command uses only mounted input and output
  paths.
- Verification: all 63 table-analyzer tests, Ruff checks, CLI help, lock validation, and whitespace
  checks pass. A real CUDA run was not started because the available workspace still lacks a valid
  M0 exact-event dataset slice and mounted `rf-detr-large.pth`; the fixture path verifies the
  dataset-to-training mapping and bundle contract without downloading weights.

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
