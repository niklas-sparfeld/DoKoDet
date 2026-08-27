# DokoDetector VisionDetector — Recognition Development

## Plan status

- **Summary:** Find a recognizer for reviewed real events after data and training foundations exist
- **Status:** To Specify
- **Depends on:** Plans 0020 and 0021, with enough reviewed events from real recordings for held-out
  evaluation
- **Builds on:** The plan 0005 detector contract and scripted pipeline

## 1. Purpose

Replace the scripted detector with the smallest measured recognizer that can rank the played card
from one V1 evidence package.

Do not select a model architecture in this plan. The available pixels, annotations, and observed
failure categories must select the experiments.

## 2. Entry evidence

Before writing a concrete experiment plan, record:

- reviewed event count from real recordings by card, physical copy, deck, session, and device class;
- counts of complete and incomplete evidence packages, false event proposals, and proposals where
  the card is not visible;
- crop size, blur, glare, perspective, occlusion, and frame-boundary distributions;
- actual V1 frame offsets and missing-frame rates;
- frozen group-safe development and held-out splits;
- the first operator workflow and compute budget.

The current six target offsets are an unvalidated capture hypothesis:

```text
[-800, -400, -100, 150, 400, 700] ms
```

First confirm that these frames expose the played card. Change capture configuration or version the
evidence contract when the required visual information is absent. Do not compensate for missing
pixels with model complexity.

## 3. Experiment sequence

### Identity feasibility with oracle crops

Use human played-card boxes to separate identity recognition from localization. Compare a small
pretrained crop classifier, fixed-deck visual matching, and any other cheap baseline justified by
the data.

Measure top-1 and top-k identity, per-card confusion, high-probability errors, and performance by
visual-quality tag. Use real held-out crops. Synthetic transforms may supplement training only.

Gate: continue when card identity is recoverable from the pixels in the evidence packages.

### Played-card localization

Compare a direct per-frame baseline with one temporal method that uses negative and positive frame
offsets. Candidate architectures may include direct identity detection, one-class localization plus
classification, template/embedding matching, or temporal change detection.

Do not assume that only one card moves, that the new card is absent from every pre-event frame, or
that it remains visible in the final frame.

Measure whether at least one usable crop of the correct physical card reaches identity recognition.
Include false CardEventNet event proposals and older cards already on the table.

Gate: continue when localization recall supports useful reviewed event recognition.

### Multi-frame aggregation

Start with bounded deterministic quality features and simple aggregation. Compare best frame,
unweighted mean, quality-weighted mean, and log-probability aggregation. Preserve disagreement and
return several candidates.

Add tracking only if per-frame association errors require it. Add card corners and homography only
if perspective failures dominate. Evaluate each addition against the same held-out reviewed events.

### Calibration and abstention

Freeze the selected model and aggregation method before calibration. Fit calibration on validation
sessions only. Report on held-out sessions:

- reviewed event top-1 and top-k accuracy;
- coverage and selective accuracy;
- false event proposal rejection;
- no-card-found and insufficient-evidence rates;
- reliability and calibration error;
- high-confidence wrong-card rate;
- results by deck, device, session, and visual-quality group.

Keep `confident`, `uncertain`, `no_card_found`, and `insufficient_evidence` distinct.

## 4. Failure feedback

Classify important failures as:

```text
FALSE_EVENT_PROPOSAL
EVENT_TIMING
MISSING_FRAME
CARD_NOT_VISIBLE
LOCALIZATION_MISS
WRONG_INSTANCE
UNUSABLE_CROP
IDENTITY_ERROR
AGGREGATION_ERROR
CALIBRATION_ERROR
```

Use the distribution of these failures to choose the next data, capture, or model change. Preserve
source frames, crops, model bundle, and result contract for every reviewed failure.

## 5. Completion direction

This plan becomes concrete only after its entry evidence exists. Completion will require:

- a selected architecture that beats documented reviewed event baselines;
- evaluation on unseen session groups, including false event proposals and incomplete evidence;
- measured calibration and abstention;
- an exported model bundle from plan 0021;
- inference through the unchanged plan 0005 boundary;
- an explicit statement of supported decks and capture conditions;
- unresolved risks handed to [plan 0024](0024-System_Production_Readiness.md).

Do not use crop accuracy, detector mAP, or a model name alone as proof of completion.
