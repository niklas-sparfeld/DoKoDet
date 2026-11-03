# iPhone model feasibility

## Plan status

- **Summary:** Test whether the current local models can run on an iPhone with fixed test inputs.
- **Status:** Closed
- **Depends on:** None
- **Closure reason:** Complete
- **Closure note:** M0–M3 completed the frozen-input inventory and bounded Core ML exports. CardEventNet already runs on a physical iPhone under the completed [Epic 0002 iOS PoC](0002-iOS_CardEventNet_PoC.md). RF-DETR and DINOv3 did not export, so M4 had no new package to measure. No new device measurements were needed.
- **Outcome:** The exact RF-DETR and DINOv3 artifacts hit reproducible Core ML conversion blockers. The exact CardEventNet checkpoint exported and matched the frozen Python score on its eight-frame temporal input. Existing iPhone support for CardEventNet is recorded in Epic 0002. No new iPhone measurements or model-quality claims were made.

## Milestone status

- **M0:** Complete — model artifacts, permitted inputs, Python references, and comparison checks are frozen. See the [M0 report](../../reports/0103-M0_Model_and_Input_Inventory.md).
- **M1:** Complete — Core ML conversion of the exact checkpoint is blocked by a reproducible encoder `int` conversion error. See the [M1 report](../../reports/0103-M1_RF-DETR_Core_ML_Export.md).
- **M2:** Complete — the exact DINOv3 weights reproduce both M0 Python references, but Core ML conversion fails in the attention graph. See the [M2 report](../../reports/0103-M2_DINOv3_Core_ML_Export.md).
- **M3:** Complete — CardEventNet exported and matched the frozen eight-frame M0 Python reference within tolerance. See the [M3 report](../../reports/0103-M3_CardEventNet_Core_ML_Export.md).
- **M4:** Not required — CardEventNet already runs on iPhone; RF-DETR and DINOv3 produced no packages to run. No new device measurements were made.

## Scope and constraints

Use the existing local recipe in the [0100 M4 report](../../reports/0100-M4_Local_Model_Recipe.md)
as the initial source of model identities: the 0092 M4 RF-DETR SegMedium bundle, the 0088 M6
identity bundle, and the 0063 CardEventNet checkpoint. These are development models, not a claim
of production quality. Pin the exact artifact digests and all export dependencies before testing.
The local bundles are not in Git. Restore their retained bytes if needed; do not train replacements.

Use fixed, permitted development inputs. Do not access sealed tests, run a sealed evaluator, change
model selection or runtime defaults, or claim model accuracy from conversion checks. Do not change
the frozen source artifacts. Keep generated model packages and media out of Git unless their size,
license, and source permissions permit inclusion. Record reproducible paths and digests instead.

This is a model-execution proof of concept. It does not require live capture, video processing,
real-time performance, a full game pipeline, a product interface, model retraining, or release.
Use a minimal native harness or Xcode model report where needed. A fixed short sequence of frames
is in scope for CardEventNet if its input requires temporal context.

## M0 — Freeze the experiment

- Inspect the actual model loaders and input contracts. Record architecture, weight and bundle
  digests, input shapes, preprocessing, output decoding, thresholds, and temporal context. Check
  artifact availability and redistribution terms; record the limits.
- Select a small set of permitted development frames and identity crops, including an empty frame
  and frames with multiple cards where available. Select a fixed temporal sequence for
  CardEventNet. Record source lineage, hashes, dimensions, and selection rationale. Do not use
  reviewed labels as execution inputs. Preserve existing data and selection pointers.
- Run the existing Python models on those inputs and retain reference outputs and commands. Record
  the environment and per-stage timing as context, not an iPhone prediction.
- Before export, define comparison rules and tolerances for input preprocessing and postprocessed
  outputs: event scores or proposals, visible-card and pile masks and scores, and identity
  candidates and scores. Account for threshold and matching behavior. Record failures and missing
  inputs explicitly. Add small deterministic checks for the comparison tools.

## M1 — Export RF-DETR segmentation

- Attempt a fixed-shape Core ML export of the exact 0092 M4 checkpoint. Record tool versions,
  precision, package digest, commands, and any checkpoint or operator incompatibility. If a newer
  exporter is needed, prove it loads the same weights; do not replace the checkpoint silently.
- Compare preprocessing and postprocessed detections, masks, and scores with the M0 Python
  references on the fixed frames. Report unmatched results and threshold crossings. Test the
  comparison with known matching and differing outputs.
- Record conversion success or the specific blocker. A failed bounded attempt may finish this
  milestone with enough evidence to reproduce the failure; do not retrain to make it pass.

## M2 — Export DINOv3 identity

- Export the exact encoder and classification head with their configuration, target map, and
  calibration as applicable. Record package and dependency identities and any unsupported
  operations. Preserve the existing crop and normalization contract.
- Compare candidate identities and scores with Python on the same fixed crops, including any
  face-down handling. Report numerical differences and changed rankings. Add focused comparison
  checks and document a reproducible failure if export cannot proceed.

**Result:** The exact encoder and head loaded and matched both frozen 25-class Python logit vectors
with zero absolute difference. Core ML Tools 9.0 failed at `encoder/model/0/attention/160` with
`TypeError: only 0-dimensional arrays can be converted to Python scalars`. No package or exported
output parity was produced. See the [M2 report](../../reports/0103-M2_DINOv3_Core_ML_Export.md).

## M3 — Export CardEventNet

- Export the exact checkpoint with its required fixed input shape and temporal context. Record
  preprocessing, state or window boundaries, decoding settings, package identity, and unsupported
  operations. Do not substitute independent still frames for a temporal input.
- Compare scores and decoded event proposals with Python on the frozen sequence. Report timing
  offsets and threshold crossings. Add focused checks for the comparison and document any
  reproducible export blocker.

**Result:** The exact 0063 checkpoint exported to a 4,282,574-byte Core ML package. On the frozen
eight-frame input, the logit difference was `0.000030041` and the probability difference was
`0.0000000234`, within `atol=1e-4`, `rtol=1e-4`. Both outputs stayed below threshold and decoded no
event, so no event timing offset was measurable. The package digest and reproduction command are
in the [M3 report](../../reports/0103-M3_CardEventNet_Core_ML_Export.md). This is execution parity,
not an event-quality claim.

## M4 — Measure on an iPhone

**Disposition:** No new device run was needed. The completed [Epic 0002 iOS PoC](0002-iOS_CardEventNet_PoC.md)
already runs CardEventNet on a physical iPhone. Epic 0063 M15 also records a Core ML integration
bundle with local runtime loading and deterministic parity. M1 and M2 produced no packages, so
there was no new RF-DETR or DINOv3 model to run on-device. This epic did not measure the M3 package's
load time, latency, memory, or compute-unit placement. Those measurements are outside this bounded
export investigation.
