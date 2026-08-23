# CardEventNet full-frame input plan

## Plan status

- Summary: Remove the manual CardEventNet ROI and use the complete camera frame
- Status: Planned

## Decision

CardEventNet will process the complete oriented camera frame. Training, replay, and live inference
will use the same full-frame preprocessing. Users and annotators will not select a table ROI.

The current recordings already frame the table closely. A manual ROI therefore removes little
irrelevant content, but it adds setup work and creates a training-to-production mismatch. The
model must learn to ignore hands, held cards, collected cards, score sheets, drinks, and other
full-frame motion.

This decision removes a manual geometric input. It does not define a hidden semantic active area.
Labels depend on the current trick and other game-relevant card states.

## Scope

Remove the CardEventNet ROI from:

- annotation creation and the new annotation format;
- Python cache generation;
- training, evaluation, inference, and replay preprocessing;
- the Core ML model contract;
- iOS live and replay inference;
- the probe app's ROI configuration and diagnostics UI;
- current CardEventNet documentation and tests.

Keep read compatibility for existing annotation files. Do not require a bulk rewrite before they
can be used.

Evidence upload already keeps full frames. ROI fields used by other future vision components are
outside this plan. Audit them separately before removing them from another contract.

## Current coupling

The ROI currently affects more than the annotation UI:

1. Each annotation requires normalized ROI coordinates.
2. Cache preparation crops to those coordinates and letterboxes the crop to `224 x 224`.
3. Existing cache metadata does not identify this preprocessing mode.
4. The trained checkpoint has learned from ROI crops.
5. The Core ML contract requires the same crop.
6. The iOS runner refuses inference until an ROI is configured.
7. The probe app exposes ROI controls and status.

Do not reuse an ROI-trained checkpoint as a full-frame production model. Do not reuse an old cache
after the preprocessing change.

## Phase 1: Lock the full-frame preprocessing contract

Use this initial contract:

1. Apply the source frame's recorded orientation.
2. Use the complete oriented frame.
3. Preserve its aspect ratio.
4. Resize it to fit inside the configured square input.
5. Center it on a black canvas.
6. Apply the existing RGB conversion and ImageNet normalization.

Keep `224 x 224` for the first comparison. Do not change input size, model architecture, labels,
decoder settings, or temporal sampling in the same experiment.

Add an explicit preprocessing identifier, such as `full_frame_letterbox_v1`, to cache metadata,
run summaries, exported-model metadata, and the model contract.

### Acceptance gate

The Python preprocessing contract has a fixed fixture and expected tensor. The preprocessing mode
is visible in each new Python artifact. Phase 5 applies the same fixture to iOS.

## Phase 2: Migrate annotation files

Define a V2 annotation record without an ROI:

```json
{
  "schema_version": "cardevent-annotation/v2",
  "video": "game-001.mov",
  "events": []
}
```

Update the loader as follows:

- Read existing V1 records with `video`, `roi`, and `events`.
- Read V2 records with `schema_version`, `video`, and `events`.
- Ignore the legacy ROI during full-frame preprocessing.
- Save new and edited annotations as V2.
- Preserve events, confidence, notes, ordering, and duplicate checks.

Remove ROI selection and the `R` shortcut from the annotator. A new video must be annotatable
without a setup dialog.

Do not rewrite all V1 files silently. Add an explicit migration command only if a bulk conversion
becomes useful.

### Tests

- Existing V1 annotations still load.
- V2 annotations load and save without an ROI.
- Editing a V1 annotation produces the declared migration result without losing events.
- New annotation sessions do not ask for an ROI.
- Invalid event data remains invalid in both versions.

### Acceptance gate

An annotator can label a new video and prepare it for training without defining any geometry.

## Phase 3: Rebuild full-frame caches

Replace crop-and-letterbox preprocessing with full-frame letterboxing. Annotation files still
provide events, but they do not provide image geometry.

Extend cache metadata with:

```json
{
  "preprocessing": "full_frame_letterbox_v1"
}
```

Make cache reuse require the same preprocessing identifier. Old ROI caches must fail the reuse
check and rebuild automatically. Do not delete them as part of cache validation.

Add image tests with content at frame edges. They must prove that the full source frame survives
letterboxing and that no hidden center crop occurs.

### Acceptance gate

All training videos have reproducible full-frame caches. No usable cache depends on annotation
geometry.

## Phase 4: Retrain and compare

Train a new checkpoint from the normal pretrained backbone with full-frame caches. Use the same
session-safe split, labels, seed, temporal sampling, architecture, and decoder as the latest
accepted ROI run.

Compare on validation only:

- target-recall attainment;
- false events per hour at target recall;
- maximum F1;
- worst-video recall;
- per-video false events;
- missed events and high-confidence false events;
- inference time and memory use.

Report results by `camera_framing`. The current dataset is mainly `table_fills_frame`, so good
aggregate results do not prove robustness for `table_with_context` or `wide_context`.

Do not use failures from the old ROI test result to choose preprocessing or input size. That
partition has already been evaluated. Reserve a new independent session for the final full-frame
test.

### Decision rule

Accept the full-frame contract when it meets target recall and has an acceptable false-event cost
on the locked validation set. Use the latest accepted ROI run as the comparison baseline, not as a
checkpoint initializer.

If recall drops because cards become too small, run a separate input-size experiment after this
comparison. Test one larger size at a time. Do not restore a manual ROI as the first response.

### Acceptance gate

A committed configuration and run reproduce the accepted full-frame validation result.

## Phase 5: Update Core ML and iOS

Export the accepted full-frame checkpoint. Record the preprocessing identifier in the exported
model metadata and update `MODEL_CONTRACT.md`.

In iOS:

- make the tensor builder letterbox the complete oriented frame;
- remove the ROI argument from the tensor builder and runner;
- remove the `roiNotConfigured` error;
- remove ROI state and controls from the probe app;
- reset temporal state only for normal stream discontinuities;
- keep live and replay preprocessing identical;
- retain Python-to-iOS tensor and model parity tests.

Do not silently pair the old ROI-trained model with the new app preprocessing. Change the model
contract version or preprocessing metadata so that an incompatible package fails clearly.

### Acceptance gate

Live and replay inference start without calibration. The accepted Core ML model matches Python on
recorded full-frame fixtures.

## Phase 6: Add full-frame data coverage

The current close framing makes the first migration practical, but it does not exercise the main
new risk. Collect or select footage with:

- table context around all edges;
- players' hands and held cards near frame edges;
- collected tricks and scoring cards outside the central trick;
- drinks, score sheets, sleeves, and unrelated objects;
- people entering the background;
- camera shake and changing exposure;
- portrait and landscape sources;
- the table occupying a smaller part of the frame.

Include quiet intervals and human-confirmed hard negatives. Do not label all peripheral motion as
positive. Use the semantic labeling guide.

### Acceptance gate

Validation contains independent `table_with_context` footage. A separate robustness subset covers
`wide_context` before production claims include that framing.

## Removal gate

ROI removal is complete when:

- new annotations contain no ROI;
- legacy annotations load without controlling preprocessing;
- old ROI caches cannot be reused silently;
- training and Python inference use full-frame letterboxing;
- the accepted model was retrained on full frames;
- Core ML and iOS use the same full-frame contract;
- live inference needs no ROI setup;
- ROI controls and errors are gone from the probe app;
- current CardEventNet documentation no longer instructs users to select an ROI;
- relevant Python and Swift tests pass;
- a new held-out test session is evaluated only after the migration decisions are frozen.

## Main risks

### Cards become too small at `224 x 224`

Measure this first. If necessary, test a larger input or a model change as a separate experiment.

### Full-frame distractors increase false events

Add reviewed hard negatives and real-game footage. Do not solve this by reintroducing manual
setup.

### Current data hides the problem

Track `camera_framing` and require contextual validation footage.

### Old and new artifacts are mixed

Version preprocessing in caches, run summaries, exports, and the app contract. Fail on a mismatch.
