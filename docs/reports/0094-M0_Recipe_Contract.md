# Epic 0094 M0 recipe contract

Date: 2026-10-14. This document freezes software recipes for later implementation. It does not
select a campaign candidate or claim model quality.

## Recipe values

Every training, evaluation, calibration, export, and inference record names the same explicit
recipe. No field may come from an ambient default.

| Field | Allowed value | Contract |
| --- | --- | --- |
| `input_size` | `224`, `384`, or `448` | Square RGB canvas; size is divisible by patch size 16. Use 224 as the control and 384 as the first larger recipe. A 448 recipe is valid only when the calling campaign freezes its resource and data gate before fitting. |
| `feature_layout` | `cls`, `cls_mean_patch` | `cls` uses final CLS (`384` features for ViT-S/16). `cls_mean_patch` concatenates CLS and the unweighted mean of final spatial patch tokens (`768` features); exclude CLS and register tokens from the mean. Padding patches remain in this declared baseline. |
| `encoder_training` | `frozen`, `last_two_blocks` | `frozen` trains only the linear head. `last_two_blocks` trains the final two transformer blocks, final normalization, and head. Record exact parameter names and optimizer groups. All other encoder parameters stay frozen. |
| `sampler` | `uniform_epoch`, `class_source_balanced_epoch` | Each epoch has a deterministic schedule derived from seed, epoch, and frozen sample IDs. The receipt records schedule digest, class and source exposure, and the next-example cursor. The chosen exposure policy is fixed before a fit. |
| `augmentation` | `source_safe_v2` | Train-only transforms operate on source pixels before resize. Rotate by at most ±15 degrees; adjust brightness and contrast by at most ±10%; apply Gaussian blur with sigma at most 1 source pixel; crop at most 2% per edge and retain at least 95% of visible-mask support. Transform image and visible mask together. Keep neutral fill stable, disable mirrors, preserve red/black marks, and reject a view that removes positive card evidence. |
| `confidence` | `raw`, `temperature_scaled` | Preserve raw logits and probabilities. Optional scalar temperature must be positive and fit on an explicitly identified, disjoint calibration view. Record top-1 probability, top-2 margin, ranked candidates, and calibration identity. Thresholds are reported as review aids; they do not discard candidates or create an `UNKNOWN` class. |

The output map is the exact ordered `VISUAL_IDENTITY_TARGETS` map: 24 canonical card identities
followed by `FACE_DOWN`. `UNKNOWN` remains abstention and is not a softmax target. The target-map
schema remains `dinov3-identity-target-map/v2` because its ordered 25-class contract is unchanged.

## Artifact versions

The first implementation uses explicit new versions. It does not reinterpret old files in place.

| Artifact | Version for implementation | Required contract fields |
| --- | --- | --- |
| Identity config | `dinov3-identity-config/v2` | recipe schema, input size, transform digest, target-map digest, pretrained model/revision/weight digest, and license provenance |
| Processor and transform | `dinov3-identity-processor/v2`; `dinov3-identity-letterbox-v2` | input size, Lanczos resize, aspect ratio, RGB 128 center fill, normalization, channel/layout/dtype, and transform digest |
| Augmentation | `dinov3-identity-augmentation/v2` | operation names, bounds, train-only flag, mask policy, mirroring flag, and deterministic key contract |
| Training run | `dinov3-identity-training-run/v2` | recipe and digest, exact frozen inputs, source and class exposure, environment, code revision, progress, and checkpoint references |
| Checkpoint | `dinov3-identity-checkpoint/v2` | model/feature layout, actual encoder and head state, optimizer and scheduler state, sampler schedule/cursor, RNG state, augmentation key, and recipe/input digests |
| Linear head | `dinov3-identity-linear-head/v2` | class count, input feature dimension, feature layout, checkpoint digest, and head state |
| Bundle | `dinov3-identity-bundle/v3` | complete recipe and transform digests, target map, pretrained provenance, actual inference encoder weights and digest, head digest, and optional calibration metadata |
| Predictions and evaluation | `dinov3-identity-predictions/v2`; `dinov3-identity-evaluation/v2` | recipe/bundle digest, all-class support and confusion, per-source-group slices, raw and calibrated scores, paired outcomes, and explicit missing/unusable/failed cases |

The pretrained asset identity and the weights used for inference are separate records. A frozen
bundle points to the verified pretrained weights. An adapted bundle contains the adapted encoder
weights plus the original pretrained model ID, revision, and digest as provenance. Export never
overwrites materialized weights, an earlier checkpoint, or a prior bundle. A training checkpoint
is not an inference bundle.

## Frozen fixture set and rejection cases

Later milestone tests use generated images, masks, a tiny encoder, and the exact 25-class map. They
do not need the reviewed corpus or model downloads.

- Valid transform fixtures cover portrait, landscape, square, and masked crops at 224 and 384; the
  448 path is conditional on a declared gate. Each fixture checks shape, finite values, stable
  letterbox fill, deterministic pixels, and transform digest.
- Feature fixtures include CLS, patch, and register tokens with distinct values. They prove the
  mean excludes CLS/register tokens and that both layouts have the declared dimensions.
- Training fixtures record sample IDs across two seeds and epochs, class/source exposure, and an
  interruption cursor. Resume must reproduce the exact remaining schedule and final model state
  within the declared device tolerance.
- Augmentation fixtures use a visible mask and red/black card marks. They check deterministic
  replay, aligned mask geometry, parameter bounds, retained support, and rejection when positive
  evidence is removed. A mirrored view is invalid.
- Weight and bundle fixtures use distinct pretrained and adapted tensor values. They verify exact
  source provenance, adapted-weight export/reload, digest failures, incompatible recipe rejection,
  and no writes to the pretrained input directory.
- Evaluation fixtures include all 25 targets, absent-class support, one `FACE_DOWN` example,
  reviewed-side bypass, paired provider results, and explicit failed/unusable/missing outcomes.
  They check denominators, candidate ordering, calibration-view separation, and no `UNKNOWN` logit.

Every reader rejects unknown recipe values, invalid size/layout/weight combinations, changed
digests, and old artifact versions where a new contract is required. Fixture tests do not run live
provider calls or make quality claims.
