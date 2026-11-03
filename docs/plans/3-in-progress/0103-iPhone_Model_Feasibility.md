# iPhone model feasibility

## Plan status

- **Summary:** Test whether the current local models can run on an iPhone with fixed test inputs.
- **Status:** In Progress
- **Depends on:** None to start. Device measurements require access to an iPhone and a suitable Apple development environment.
- **Outcome:** A reproducible proof of concept and report show which current models export and run, how their outputs compare with Python, and the measured device costs and remaining blockers. A documented negative result is a valid outcome.

## Milestone status

- **M0:** Complete — model artifacts, permitted inputs, Python references, and comparison checks are frozen. See the [M0 report](../../reports/0103-M0_Model_and_Input_Inventory.md).
- **M1:** Not started — export and compare the RF-DETR segmentation model.
- **M2:** Not started — export and compare the DINOv3 identity model.
- **M3:** Not started — export and compare CardEventNet on fixed temporal input.
- **M4:** Not started — run the exported models on an iPhone and report feasibility.

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

## M3 — Export CardEventNet

- Export the exact checkpoint with its required fixed input shape and temporal context. Record
  preprocessing, state or window boundaries, decoding settings, package identity, and unsupported
  operations. Do not substitute independent still frames for a temporal input.
- Compare scores and decoded event proposals with Python on the frozen sequence. Report timing
  offsets and threshold crossings. Add focused checks for the comparison and document any
  reproducible export blocker.

## M4 — Measure on an iPhone and decide

- Identify the available iPhone model, iOS version, development environment, and compute-unit
  configuration. Run each successfully exported model on its frozen input using a minimal local
  harness or Xcode. Capture output for the same M0 comparisons. If device access or signing is
  unavailable, record the exact blocker and leave this milestone incomplete until it is resolved.
- Measure package size, load time, warm per-inference latency, and peak memory where tools permit.
  Record repeated-run counts, input and batch sizes, device conditions, compute-unit placement when
  available, and measurement limitations. These are individual-model measurements, not a live
  pipeline throughput or battery claim.
- Publish a report with per-model export, device execution, parity, measurements, and blockers.
  State whether all three current models ran on the tested device and what further work a complete
  pipeline would need. Report failed models separately and give a bounded recommendation for the
  next experiment. Do not promote a model or change defaults.
