# Local visual card identity classifier PoC

## Plan status

- **Summary:** Prove that one current pretrained vision encoder can train and run locally behind
  the existing visual card identity classifier contract.
- **Status:** In Progress
- **Depends on:** Completed plans 0021 and 0028
- **Builds on:** The existing deterministic crop, identity-candidate, capability-bundle, training,
  evaluation, and promotion contracts
- **Related:** Plan 0040 creates reviewed visible regions. Plan 0042 will add human visual card
  identity review after this proof fixes the proposal and bundle contracts.
- **Outcome:** A local DINOv3 ViT-S/16 classifier can train on the target Mac, emit a validated
  24-identity bundle, classify a supplied crop through the current runtime interface, and run as an
  explicit non-default backend option. This epic makes no quality or replacement claim.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — freeze the model, license, crop, target, and run contracts.
- **M1:** Not started — train one local smoke classifier and preserve its run record.
- **M2:** Not started — export and load one native local identity bundle.
- **M3:** Not started — select the local classifier explicitly in the backend and run one proof.

## 1. Purpose

Replace the dependency-free RGB-centroid smoke adapter with a capable local model foundation. Keep
the existing Gemini classifier as the backend default until reviewed real evidence proves that a
local candidate is good enough.

Use `facebook/dinov3-vits16-pretrain-lvd1689m` as the frozen architecture choice for this proof. It
is an approximately 21 million parameter, patch-16 vision encoder. The official model card supports
a simple classifier over its frozen features and recommends fine-tuning only when measured evidence
needs it. This gives the project a current high-quality visual representation without architecture
development. See the [DINOv3 paper](https://arxiv.org/abs/2508.10104),
[official model card](https://huggingface.co/facebook/dinov3-vits16-pretrain-lvd1689m), and
[DINOv3 license](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md).

The proof uses the pinned Transformers `pooler_output`, a frozen encoder, and one trainable linear
24-class head. Plan 0043 can compare one bounded partial fine-tune only if reviewed data shows that
the frozen representation is not sufficient.

## 2. Scope

This epic includes:

- one pinned DINOv3 ViT-S/16 runtime and pretrained-weight identity;
- one deterministic 224 x 224 classifier input transform over the existing PPM crop boundary;
- one linear head for all 24 canonical visual card identities;
- local CPU and MPS training and inference with explicit device selection;
- run, checkpoint, resume, evaluation, and bundle records through the plan 0021 foundation;
- a `CardIdentityClassifier` adapter that returns ranked identity candidates; and
- explicit `gemini` or `local` backend selection while Gemini remains the default.

This epic does not include:

- real-data quality gates, architecture comparison, hyperparameter search, threshold selection, or
  model promotion;
- identity annotation, review, dataset coverage work, or web UI changes;
- changes to visible-card detection, visible regions, crop-policy comparison, tracking,
  reconstruction, or the table-observation contract;
- Core ML, ONNX, quantization, compilation, or remote training; or
- automatic weight downloads in tests or an unattended acceptance of the DINOv3 license.

## 3. Fixed decisions

1. Use the official DINOv3 ViT-S/16 LVD-1689M pretrained weights. Record the model revision,
   safetensors digest, license version, processor configuration, and dependency versions.
2. Require the operator to accept the DINOv3 license and materialize the gated pretrained weights
   before a real run. Tests use a generated local double and never authenticate or download.
3. Decode the existing binary PPM crop, preserve its aspect ratio, pad with the frozen neutral RGB
   value, and resize to 224 x 224. Do not stretch the card or infer hidden pixels.
4. Use all 24 visual card identities from the canonical card set. Do not train an `unknown` class.
   Rejection and calibration require reviewed validation data and belong to plan 0043.
5. Freeze the encoder in this proof. Train one linear head from the pinned Transformers
   `pooler_output`. Do not compare pooling strategies, heads, optimizers, augmentations, or backbone
   variants.
6. Freeze one small augmentation policy that preserves identity. It can include color and exposure
   variation and the declared card-orientation transforms. It must not mirror suit or rank marks or
   apply arbitrary rotations that create unsupported card views.
7. Use one explicit `cpu` or `mps` device. An unsupported MPS operation fails with a complete run
   record. It does not move silently to CPU.
8. Keep the existing `CardIdentityClassifier` and ranked `IdentityCandidate` contracts. Add a new
   bundle version only where the current RGB-centroid artifact cannot describe PyTorch weights,
   preprocessing, and the encoder license.
9. The proof bundle declares `quality_state: unusable_smoke_artifact` and calibration
   `uncalibrated`. It cannot become a champion or backend default.
10. Keep Gemini as the backend default. Local mode must not construct or call Gemini for visual
    card identity. Detector and identity provider selections remain separate settings.

## 4. Delivery milestones

### M0 — Freeze the model and data contracts

- Add the pinned optional training and inference dependencies through the normal package lock.
- Add the DINOv3 classifier configuration, weight-materialization check, and license record.
- Add the deterministic 224 x 224 transform and strict 24-identity target mapping.
- Extend the run and bundle manifests only where the existing contracts lack required fields.

Acceptance:

- a generated crop maps to the same tensor and digest on repeated runs;
- invalid PPM bytes, unknown identities, changed processor data, and changed weight bytes fail;
- the complete pretrained revision, weight digest, license, transform, card set, and dependency set
  participate in run identity; and
- tests do not use the network or require gated model access.

Progress (2026-09-01): M0 is complete. Added the frozen DINOv3 ViT-S/16 metadata, explicit
license-acceptance record, local materialization and digest checks for model, config, and
processor files, the strict zero-based 24-identity target map, and the deterministic 224 x 224
letterbox transform with normalized CHW float32 output. Pinned PyTorch, TorchVision, Transformers,
and Safetensors in the optional training and inference groups. The contract suite uses generated
local doubles and does not authenticate, download weights, or call the network.

### M1 — Train one local smoke classifier

- Add the DINOv3 frozen-encoder task adapter and linear head.
- Reuse checkpoint, resume, failure-record, and sample-prediction mechanics from plan 0021.
- Run one generated CPU contract test and one real MPS smoke run on the target Mac.

Acceptance:

- the generated task can overfit its tiny training partition;
- the real MPS run executes finite optimization steps and writes a loadable checkpoint;
- interrupted and resumed runs preserve the frozen inputs and semantic progress;
- a device or training failure leaves a complete failure record; and
- the run is labelled as a capability proof, not a real-data metric.

### M2 — Export and load the local bundle

- Export the encoder, trained head, processor, target map, and manifest as one self-contained
  bundle.
- Add a runtime-only adapter that does not import training modules.
- Return normalized ranked candidates through `CardIdentityClassifier`.

Acceptance:

- bundle load verifies every file digest before model construction;
- repeated CPU inference returns the same ranked fixture candidates;
- MPS inference runs when available and never falls back silently;
- corrupt weights, target-map mismatch, invalid input, and inference failure are explicit; and
- the bundle claims only visual card identity candidates and remains uncalibrated.

### M3 — Prove the backend boundary

- Add an explicit identity-classifier setting with `gemini` and `local` values.
- Require a local bundle path and device in local mode.
- Keep detector selection independent and preserve the normal table-observation persistence path.
- Run one stored fixture evidence package and one local crop proof.

Acceptance:

- backend tests cover Gemini and local identity selection without network calls;
- local identity mode does not require `GEMINI_API_KEY` when the visible-card provider is also
  local;
- one fixture analysis persists a schema-valid table observation with local bundle provenance;
- one real crop reaches a terminal local result on the target Mac; and
- the proof report records load and inference time without making latency or quality claims.

## 5. Verification

For each milestone, run the focused analyzer and backend tests, Ruff checks, formatting checks,
package-lock validation, CLI help checks, and fixture contract tests. M1 and M2 need explicit CPU
tests and one recorded MPS proof. Tests must remain weight-free and network-free.
