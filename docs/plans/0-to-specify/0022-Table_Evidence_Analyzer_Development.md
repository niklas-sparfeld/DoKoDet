# DokoDetector TableEvidenceAnalyzer — Capability Development

## Plan status

- **Summary:** Produce measured table observations from reviewed real frames and video snippets
- **Status:** To Specify
- **Depends on:** Plans 0020 and 0021, with enough reviewed real evidence for held-out
  evaluation
- **Tracking stages depend on:** Plan 0025 video snippets
- **Builds on:** The plan 0006 table-observation contract and plan 0021 training pipeline
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Purpose

Replace the scripted and synthetic table-observation producers with the smallest measured visual
pipeline that can report visible cards and useful optional evidence.

Do not require the TableEvidenceAnalyzer to select the final played card. It reports anonymous
observed cards, identity candidates, and declared optional capabilities. Game reconstruction decides
which visual evidence represents a card play.

Do not select a final model architecture in this plan yet. Available pixels, reviewed annotations,
baseline results, and observed failure categories must select the experiments.

## 2. Entry evidence

Before writing concrete implementation milestones, record:

- reviewed table observations from real recordings by visible-card count, visual identity, physical
  copy when known, deck, session, table setup, and device class;
- reviewed false event proposals, empty observations, incomplete evidence, and unusable evidence;
- selected-frame and video-snippet counts, durations, frame rates, sizes, and decode failures;
- crop size, blur, glare, perspective, occlusion, movement, and frame-boundary distributions;
- reviewed newly-visible, active-area, reappearance, movement, and tracklet labels when visible;
- frozen group-safe development, validation, and held-out splits;
- the first operator workflow and compute budget;
- the plan 0006 reconstruction scenarios and feature-ablation interface.

The current six target frame offsets remain an unvalidated capture hypothesis:

```text
[-800, -400, -100, 150, 400, 700] ms
```

Plan 0025 adds a bounded snippet around the same proposal. First confirm that the frames and snippet
show enough of the visible cards and transition. Change capture configuration or version the
evidence contract when required pixels are absent. Do not compensate for missing evidence with
model complexity.

## 3. First specification experiment: fixed selected-frame suitability

Test the cheapest path to real analyzer input before card localization or visual card identity
work. Extract one evidence package for each reviewed `card_played` annotation. Then review one fixed
selected frame from each package.

Keep two source classes separate:

1. Start with annotation-derived packages. They provide trusted event times and test whether the
   selected frames contain useful visual evidence.
2. Add CardEventNet-proposal packages later. They measure proposal-time behavior and supply false
   proposals, hard cases, and useful visual negatives after separate review.

Do not mix the two classes in the first frame-suitability measurement.

This experiment answers two bounded questions:

1. Does one fixed selected-frame target provide usable visual card evidence often enough for the
   first proof of concept?
2. Does the run provide a diverse set of real frames for the card localization and visual card
   identity experiments?

It does not measure CardEventNet recall, evaluate model proposals, label an empty frame as a true
negative, or create a table observation.

### 3.1 Freeze the run

Before extraction or review, record:

- every included recording, source digest, session, table setup, deck design, and existing split or
  system-holdout assignment;
- the exact annotation version and annotation-file digests;
- the extraction implementation and configuration;
- the evidence-package contract and the six selected-frame targets;
- the fixed target under review;
- one run identifier and deterministic output location.

For the first run, define the fixed frame as the selected frame with target offset `+150 ms`. Do not
silently substitute another frame when that target is missing. Record the package as incomplete for
this experiment.

Extract packages for all eligible annotated recordings. Do not extract or review sealed system-
holdout groups during development. Exclude those groups from the review queue and from the next
training inputs.

### 3.2 Extract annotation-derived packages

Use the annotation-driven producer:

```bash
cd card_event_net
uv run cardevent extract-evidence \
  --videos-dir data/raw \
  --annotations-dir data/annotations \
  --manifest data/dataset-manifest.v1.yaml \
  --split data/splits/batch-2026-08-24.yaml \
  --partition train val \
  --out data/outputs/annotation-evidence-<version>
```

The command must:

1. accept an explicit dataset manifest and optional split or video selection;
2. process each source recording without modifying it;
3. select only `card_played` events whose confidence is absent or `confirmed`;
4. exclude `uncertain`, `ignore`, `proposed`, and non-card-play events;
5. create one evidence package per selected annotation;
6. extract the six selected frames from the original source resolution;
7. preserve source-video, annotation, event, recording, session, and configuration lineage in the
   extraction manifest;
8. record missing targets instead of substituting another target;
9. use stable package identities and publish the output directory atomically;
10. report video, annotation, decode, missing-frame, and output failures.

Use a generated-video fixture with known annotation times. Verify selected source frame indices,
actual offsets, JPEG dimensions and digests, missing boundary frames, event filtering, and import by
the existing table-observation tooling.

### 3.3 Run a fast binary review

Create a resumable review queue containing exactly the `+150 ms` selected frame from each complete,
non-holdout package. Keep the reviewer blind to the other frames, video snippet, model probability,
and event truth during this pass.

Ask one question:

> Does this exact frame contain at least one face-up card whose boundary and visual card identity
> you can recognize without another frame?

The only decisions are:

```text
GOOD
BAD
```

`GOOD` means that the frame can enter the first positive localization and identity experiments.
`BAD` means only that this frame does not meet the criterion. It does not revoke the reviewed event,
mean that the package contains no useful frame, or make the image a reviewed negative.

The review tool must preload the next image, provide one key for each decision, save after every
decision, resume without repetition, and record reviewer, package identity, frame member, frame
digest, target offset, run identity, and decision time. Run a 20-item pilot first. Freeze the
wording and discard the pilot decisions if the criterion changes.

### 3.4 Audit the binary result

The central-frame-only review measures yield, but it cannot explain a `BAD` result. After the fast
pass, select a deterministic, session-stratified audit sample of:

- at least 30 `BAD` packages;
- at least 20 `GOOD` packages;
- every package with a missing `+150 ms` target, up to a separately reported cap.

Inspect all selected frames and the video snippet when present. Record whether:

```text
FIXED_FRAME_GOOD
OTHER_SELECTED_FRAME_GOOD
NO_SELECTED_FRAME_GOOD
PACKAGE_INCOMPLETE
```

For `OTHER_SELECTED_FRAME_GOOD`, record every usable target offset. This audit estimates how much
yield the fixed target loses and whether another single target would work better. It is not a full
table-observation review.

### 3.5 Report and publish the candidate frame set

Write one machine-readable result and one short report. Include:

- source recording, session, and package counts;
- selected-annotation and package counts per recording and session;
- complete, incomplete, `GOOD`, and `BAD` counts;
- fixed-frame good rate overall and by session, table setup, and deck design;
- missing-target and processing failure rates;
- audit outcomes and usable rate for every selected-frame target;
- the number of `BAD` fixed frames recovered by another target;
- review throughput and median decision time;
- repeated or near-duplicate package concentration;
- the exact source, annotation, extractor, queue, review, and report digests.

Publish a manifest that references each `GOOD` frame by package member and digest. Preserve its
session and source-lineage group. Do not copy the JPEGs into a new source directory and do not label
the visual card identities yet.

Use these decisions:

- Continue with the fixed-frame proof of concept when the review yields at least 100 `GOOD` frames
  from at least five sessions and no one session supplies more than 40% of them.
- Keep the `+150 ms` target when the audit does not show another single target that improves usable
  package yield by more than 10 percentage points.
- Select and repeat the binary review for a better fixed target when one target clears that margin.
- Stop the fixed-frame approach when no single target supplies the minimum candidate set. Plan a
  multi-frame input instead.

These are proof-of-concept gates. They do not claim production coverage. Keep all observed rates in
the report even when the absolute candidate-frame gate passes.

## 4. Additive experiment sequence

Add one capability at a time. Preserve the identity-only reconstruction baseline. Run plan 0006
ablation scenarios before and after each addition.

### Identity feasibility with oracle crops

Use human boxes to separate visual card identity from localization. Compare a small pretrained crop
classifier, fixed-deck visual matching, and other cheap baselines justified by the data.

Measure top-1 and top-k identity, per-card confusion, high-score errors, and performance by visual
quality tag. Use real held-out crops. Synthetic transforms can supplement training only.

Gate: continue when identity is recoverable from the pixels for a declared set of conditions.

Output capability:

```text
identity_candidates
```

### Visible-card detection

Detect all visible card proposals in selected frames. Do not assume that one evidence package
contains one card, that only one card moves, or that the played card remains visible in the last
frame.

Measure card-proposal recall, duplicate rate, false proposal rate, usable-crop recall, and identity
accuracy after localization. Include human hands, side cards, old tricks, partial cards, and false
CardEventNet event proposals.

Gate: continue when visible-card recall supports useful table observations.

### Multi-frame table observation

Aggregate per-frame card proposals into one anonymous observed-card list. Start with deterministic
matching and quality features. Preserve disagreements and several identity candidates.

An observed empty list means that no card was detected. Keep it distinct from insufficient visual
evidence. Do not infer persistent gameplay state in this stage.

Gate: continue when repeated selected frames produce stable observed-card lists on held-out events.

### Presence evidence

Estimate whether each observed-card proposal represents a card. Compare a direct card-versus-background
score with simple temporal persistence evidence.

Output capability:

```text
presence_score
```

Measure how presence evidence affects duplicate and false-card hypotheses in plan 0006. Do not use
identity confidence as a substitute for card presence.

### Transition evidence

Compare pre-event and post-event selected frames. Estimate whether an observed card became newly
visible and whether it can continue an earlier observed card.

Output capabilities:

```text
newly_visible_score
association_candidates
```

Use `newly_visible`, not `played`, as the visual claim. Include occlusion, reappearance, movement,
old tricks shown again, and missed detection in the previous observation.

First test selected-frame methods. Use the video snippet only when it provides measured improvement.

### Spatial evidence

Estimate a dynamic active table area from recent visual activity or a reviewed table setup. Compare
simple normalized distance, overlap with an active-area mask, and one learned baseline only if data
supports it.

Output capability:

```text
active_area_score
```

Include cards retained outside the active area, old tricks shown at the side, off-center cameras,
and active-area movement. Do not emit game-specific claims such as a captured fox.

### Video card tracklets

Use bounded plan 0025 snippets for short-term tracking. Start with tracking by detection. Compare
spatial overlap, identity-distribution similarity, appearance features, movement continuity, and
optical flow only as justified by measured failures.

Track within one snippet first. Add cross-snippet predecessor candidates only when overlapping
evidence supports them. Do not create round-long physical-card identities.

Output capabilities:

```text
association_candidates
card_tracklets
```

Measure association accuracy, identity switches, recovered short occlusions, false continuations,
and effect on reconstruction. A tracker metric alone is not proof of gameplay improvement.

### Calibration and ablation

Freeze a selected capability implementation before calibration. Fit calibration on validation
sessions only. Report on held-out sessions:

- observed-card identity top-1 and top-k accuracy;
- visible-card recall and false proposals;
- empty and insufficient-evidence rates;
- presence, newly-visible, active-area, and association reliability where labels exist;
- high-confidence errors;
- results by deck, device, session, table setup, and visual-quality group;
- plan 0006 reconstruction results with and without each capability.

Do not multiply correlated outputs as independent probabilities. Keep calibration metadata for each
bundle and composed table-observation producer.

## 5. Failure feedback

Classify important failures as:

```text
FALSE_EVENT_PROPOSAL
EVENT_TIMING
MISSING_FRAME
MISSING_OR_CORRUPT_SNIPPET
CARD_NOT_VISIBLE
VISIBLE_CARD_MISS
DUPLICATE_CARD_PROPOSAL
FALSE_CARD_PROPOSAL
UNUSABLE_CROP
IDENTITY_ERROR
NEWLY_VISIBLE_ERROR
ACTIVE_AREA_ERROR
TRACK_FRAGMENT
TRACK_IDENTITY_SWITCH
OCCLUSION_FAILURE
AGGREGATION_ERROR
CALIBRATION_ERROR
```

Use the distribution of failures to choose the next data, capture, or model change. Preserve source
frames, snippets, derived crops, tracklets, model bundles, and table observations for reviewed
failures.

## 6. Specification measurements

Before moving this plan to `Ready`, define measured gates for:

- supported visible-card count and table conditions;
- identity, proposal, transition, spatial, and tracking quality;
- maximum snippet and observation-processing cost;
- required reconstruction improvement for each optional capability;
- acceptable high-score error rates;
- calibration and abstention behavior;
- device, deck, and table-setup support.

Remove an optional capability from the first implementation if it does not improve held-out
reconstruction enough to justify its complexity.

## 7. Completion direction

Completion will require:

- a selected visible-card and identity pipeline that beats documented baselines;
- a schema-valid `table-observation/v1` producer;
- evaluation on unseen session groups, including false event proposals and incomplete evidence;
- measured calibration or an explicit uncalibrated declaration;
- measured ablations for every claimed optional capability;
- versioned bundles from plan 0021;
- an explicit statement of supported decks, devices, table setups, and capture conditions;
- unresolved risks handed to plan 0024.

Do not use crop accuracy, visible-card average precision, tracking accuracy, or a model name alone
as proof of completion.
