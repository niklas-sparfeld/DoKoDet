# VisionDetector v1 — Implementation Plan

## Plan status

- **Summary:** Recognize cards from evidence
- **Status:** Draft

## 1. Goal

Implement and validate a specialist vision pipeline that takes an evidence package for a suspected card-play event and returns a calibrated visual hypothesis for the played Doppelkopf card.

The VisionDetector must reason **only from visual evidence**.

It must **not** receive or use:

- player identity,
- inferred turn order,
- legal-move constraints,
- previously played cards,
- current game state,
- retrospective player attribution.

Those belong to the later game reconstruction engine.

The detector should be able to abstain when the visual evidence is insufficient.

---

## 2. Target Contract

Conceptually:

```python
result = vision_detector.detect(evidence_package)
```

Input:

```text
EvidencePackage
├── event_id
├── approximate_event_timestamp
├── frames[]                    # burst around suspected play event
├── frame_timestamps[]
├── optional CardEventNet scores / event timing metadata
└── camera metadata
```

Output:

```json
{
  "status": "confident",
  "prediction": {
    "card": "HEARTS_QUEEN",
    "confidence": 0.982
  },
  "alternatives": [
    {"card": "DIAMONDS_QUEEN", "confidence": 0.009},
    {"card": "HEARTS_JACK", "confidence": 0.004}
  ],
  "observations": [
    {
      "frame_index": 13,
      "bbox": [412, 280, 611, 527],
      "detector_confidence": 0.97,
      "quality": 0.91,
      "prediction": "HEARTS_QUEEN",
      "confidence": 0.96
    }
  ],
  "diagnostics": {
    "frames_received": 21,
    "frames_with_candidate": 9,
    "frames_used": 6
  }
}
```

Alternative status:

```json
{
  "status": "uncertain",
  "prediction": null,
  "alternatives": [
    {"card": "HEARTS_QUEEN", "confidence": 0.46},
    {"card": "DIAMONDS_QUEEN", "confidence": 0.41}
  ]
}
```

Do not force a card prediction when evidence is weak.

---

## 3. v1 Architecture

Implement the first version as separate, replaceable stages.

```text
Evidence burst
      │
      ▼
CardDetector
detect all visible card faces
      │
      ▼
Temporal association / tracking
associate card detections across frames
      │
      ▼
Event candidate selection
determine which track appeared around the event
      │
      ▼
CardClassifier
classify multiple crops from candidate track
      │
      ▼
Quality-weighted aggregation
      │
      ▼
Confidence calibration / abstention
      │
      ▼
VisionDetectionResult
```

### ML components

1. **CardDetector**
   - one-class object detector,
   - class: `card`,
   - initially predicts ordinary bounding boxes,
   - does not identify the card.

2. **CardClassifier**
   - 24-class image classifier,
   - one class for each visually distinct Doppelkopf face,
   - physical duplicate cards share the same class.

### Non-ML components

- frame extraction,
- crop extraction,
- simple temporal tracking,
- candidate-track selection,
- crop quality scoring,
- multi-frame probability aggregation,
- calibration,
- evaluation,
- diagnostic artifact generation.

### Explicitly defer

Do not initially implement:

- card corner/keypoint detection,
- homography/perspective rectification,
- segmentation,
- learned video tracking,
- video transformers,
- multimodal LLM/VLM inference,
- game-state reasoning.

Add these only if evaluation shows a concrete need.

---

## 4. Supported Card Set

Start with the exact deck/card design used for development.

Represent the standard 48-card Doppelkopf deck as 24 visual identities:

```text
CLUBS:    9 J Q K 10 A
SPADES:   9 J Q K 10 A
HEARTS:   9 J Q K 10 A
DIAMONDS: 9 J Q K 10 A
```

The two physical copies of a card map to the same class.

The card-set definition must be configuration/data rather than hard-coded assumptions so that a 40-card variant or another card design can be introduced later.

Suggested enum:

```python
class CardIdentity(str, Enum):
    CLUBS_9 = "CLUBS_9"
    CLUBS_JACK = "CLUBS_JACK"
    ...
```

---

## 5. Repository Structure

A reasonable initial structure:

```text
vision-detector/
├── pyproject.toml
├── README.md
├── configs/
│   ├── cards.yaml
│   ├── classifier.yaml
│   └── detector.yaml
│
├── data/
│   ├── source_cards/
│   ├── events/
│   ├── detector_annotations/
│   ├── generated/
│   └── splits/
│
├── models/
│   └── .gitkeep
│
├── src/
│   └── vision_detector/
│       ├── domain/
│       │   ├── cards.py
│       │   ├── evidence.py
│       │   └── result.py
│       │
│       ├── classifier/
│       │   ├── model.py
│       │   ├── dataset.py
│       │   ├── augmentations.py
│       │   └── inference.py
│       │
│       ├── detector/
│       │   ├── model.py
│       │   ├── dataset.py
│       │   └── inference.py
│       │
│       ├── tracking/
│       │   ├── association.py
│       │   └── candidate_selection.py
│       │
│       ├── aggregation/
│       │   ├── quality.py
│       │   ├── aggregate.py
│       │   └── calibration.py
│       │
│       ├── pipeline.py
│       └── diagnostics.py
│
├── scripts/
│   ├── prepare_source_cards.py
│   ├── generate_classifier_samples.py
│   ├── extract_video_frames.py
│   ├── train_classifier.py
│   ├── evaluate_classifier.py
│   ├── train_detector.py
│   ├── evaluate_detector.py
│   ├── extract_real_card_crops.py
│   └── evaluate_events.py
│
├── tests/
│   ├── unit/
│   └── integration/
│
└── notebooks/
    └── exploration/
```

Keep notebooks optional and exploratory. Production logic belongs under `src/`.

---

# Milestone 1 — Domain Model and Evaluation Dataset

## 6. Define the Event Ground Truth Format

Before model training, define the end-to-end unit of truth.

Example:

```json
{
  "session_id": "game-001",
  "video": "game-001.mov",
  "events": [
    {
      "event_id": "game-001-0001",
      "timestamp_seconds": 12.43,
      "card": "HEARTS_QUEEN"
    },
    {
      "event_id": "game-001-0002",
      "timestamp_seconds": 14.18,
      "card": "CLUBS_ACE"
    }
  ]
}
```

Only store information required to evaluate visual recognition.

Do not store player/turn metadata in VisionDetector training data unless it is isolated metadata explicitly unavailable to the model.

## 7. Dataset Splitting

Split by entire recording/session.

Never randomly split frames.

Bad:

```text
frame 100 -> train
frame 101 -> validation
```

Good:

```text
game-001 -> train
game-002 -> train
game-003 -> validation
game-004 -> test
```

This prevents near-identical adjacent frames from leaking across splits.

Create persistent split manifests:

```text
data/splits/train.txt
data/splits/validation.txt
data/splits/test.txt
```

Do not regenerate them implicitly between runs.

## Acceptance Criteria

- card identity enum/config exists,
- evidence/result domain objects exist,
- at least one real video has event timestamps and ground-truth card labels,
- session-level dataset split code exists,
- no player or game-state field is consumed by the detector API.

---

# Milestone 2 — Classifier-Only Feasibility Experiment

This is the cheapest high-value experiment and should happen before object detection work.

## 8. Capture Source Card Images

For the actual deck:

- photograph or scan both physical copies of every card,
- use high resolution,
- use flat, even lighting,
- keep the full card visible,
- capture the card approximately front-on,
- use a neutral background.

Expected source set:

```text
24 identities × 2 physical copies = 48 source images
```

Store metadata:

```text
card identity
physical copy id
source image
```

Do not use the physical copy id as a classifier target.

## 9. Build Synthetic Training Augmentation

Use the clean source images as templates and transform them dynamically during training.

Include:

- random rotation,
- perspective distortion,
- scale,
- translation,
- crop,
- brightness/contrast,
- white-balance/color changes,
- shadows,
- motion blur,
- defocus blur,
- sensor/image noise,
- downsampling,
- compression artifacts,
- partial occlusion,
- finger/hand-like occluders,
- table/background compositing.

The augmentation pipeline should be deterministic when supplied a seed.

Expose augmentation ranges in configuration.

Do not pre-render a giant static synthetic dataset unless profiling later shows a need.

## 10. Initial Classifier

Start with a small pretrained image classifier such as EfficientNet-B0 or an equivalently lightweight modern backbone.

Requirements:

```text
input: RGB card crop
output: logits over 24 card identities
```

Initial input resolution:

```text
224 × 224
```

Preserve aspect ratio by padding where sensible rather than arbitrarily destroying card geometry.

Training:

1. initialize from general image-pretrained weights,
2. replace classification head with 24 outputs,
3. train head,
4. fine-tune the whole network,
5. use synthetic augmentation continuously,
6. track validation metrics per class.

Record:

- training config,
- code revision,
- random seed,
- source dataset version,
- resulting checkpoint,
- metrics.

## 11. Real-Crop Smoke Test

Before building CardDetector, manually extract approximately 100–300 card crops from real gameplay videos.

Make them intentionally representative:

- easy,
- strongly angled,
- shadowed,
- blurred,
- partly occluded,
- small,
- glare,
- near image borders.

Label each crop manually.

Evaluate the synthetic-trained classifier on these real crops.

Generate a report containing:

- top-1 accuracy,
- top-3 accuracy,
- confusion matrix,
- examples of confident mistakes,
- examples of low-confidence correct predictions,
- accuracy grouped by rough quality/difficulty.

## Decision Gate A

Continue with the architecture if the classifier shows useful transfer from synthetic data to real footage.

Do not require production accuracy yet.

The purpose is to answer:

> Is card identity recoverable from the visual quality produced by our camera setup?

If the answer is unexpectedly poor, inspect failure modes before investing in object detection.

Potential responses:

- improve crop resolution,
- improve synthetic augmentation,
- include more real crops,
- introduce perspective rectification earlier,
- reconsider camera/evidence capture.

---

# Milestone 3 — Real Card Detection Dataset

## 12. Select Frames for Annotation

Extract diverse frames from real gameplay recordings.

Initial target:

```text
~500–1,500 annotated frames
```

Prefer diversity over quantity.

Sampling should deliberately cover:

- multiple recordings,
- different lighting conditions,
- empty table,
- card entering,
- card lying on table,
- multiple cards,
- hands over cards,
- motion blur,
- severe perspective,
- glare,
- cards partly outside frame,
- confusing non-card rectangular objects.

Avoid selecting hundreds of nearly identical adjacent frames.

## 13. Annotation Specification

For every sufficiently visible playing card face:

```text
class = card
bbox = [x_min, y_min, x_max, y_max]
```

Use exactly one object class.

Do not annotate card identity for the detector.

Define and document edge cases:

- minimum visible fraction,
- whether card backs count,
- whether cards held in hands count,
- whether tiny/unusable cards count,
- whether stacked cards receive multiple boxes.

Suggested initial rule:

> Annotate a card when enough of the face is visible that a human can reasonably identify it or recognize it as a playing card.

Refine after reviewing the first 100 annotations.

## 14. Annotation QA

Before full training:

- manually review a random sample,
- find missed cards,
- find inconsistent box tightness,
- resolve ambiguous annotation policy,
- freeze annotation guidelines.

Dataset versioning must make annotation changes traceable.

---

# Milestone 4 — CardDetector v0

## 15. Train a One-Class Detector

Start with a small pretrained object detector.

A YOLO-family implementation is acceptable for rapid prototyping.

Model task:

```text
image -> zero or more CARD bounding boxes + confidence
```

Prioritize recall over precision.

A false positive can often be rejected downstream.

A missed played card cannot.

Track at least:

- recall,
- precision,
- mAP,
- recall grouped by object size,
- recall on occluded/blurred subsets where available.

## 16. Detector Diagnostics

Generate visual overlays for validation frames showing:

- ground-truth boxes,
- predicted boxes,
- confidence,
- missed detections,
- false positives.

Do not rely only on aggregate detector metrics.

## Decision Gate B

The detector is sufficient for v1 if:

- played cards are detected reliably in at least several frames of most event bursts,
- failures are primarily difficult visual cases rather than systemic annotation/model errors,
- downstream tracking has enough candidate detections to work with.

Exact thresholds should be derived from the held-out event dataset rather than chosen arbitrarily.

---

# Milestone 5 — Temporal Association

## 17. Track Card Detections Across the Burst

Do not train a tracker initially.

Associate detections between neighboring frames using simple features:

- IoU,
- center-point distance,
- box size similarity,
- motion continuity,
- optional classifier embedding/probability similarity.

Represent:

```python
CardTrack:
    track_id
    observations[]
    first_seen_timestamp
    last_seen_timestamp
```

Each observation contains:

```python
frame_index
timestamp
bbox
detector_confidence
```

## 18. Candidate Track Selection

The event timestamp supplied with the evidence burst indicates when a card-play-like event probably occurred.

Select candidate tracks based on temporal behavior, for example:

- absent before event,
- appears close to event,
- persists for several frames,
- moves into/stabilizes in table area,
- has sufficiently large/usable crops.

Do not use player position.

Do not use game legality.

Do not assume the relevant card must be the only new object.

Return multiple candidate tracks internally when ambiguous.

## 19. Tracking Diagnostics

For each event optionally emit a debug visualization:

```text
frame timeline
track IDs
first/last appearance
selected event candidate
rejected candidates
```

This will be critical for separating localization/tracking failures from recognition failures.

---

# Milestone 6 — Bootstrap Real Classifier Data

## 20. Extract Real Crops from Labeled Events

Once candidate tracking works, exploit the event-level card label.

For a labeled event:

```text
event -> HEARTS_QUEEN
```

and selected candidate track with eight good observations:

```text
crop 1 -> HEARTS_QUEEN
crop 2 -> HEARTS_QUEEN
...
crop 8 -> HEARTS_QUEEN
```

This turns one human event label into multiple real training samples.

Store provenance:

```text
event_id
session_id
frame_index
source bbox
card label
extraction model version
quality values
```

Do not blindly add every automatically extracted crop.

Reject obvious low-quality/outlier crops.

## 21. Fine-Tune Classifier on Synthetic + Real Data

Construct batches that contain both:

- aggressively augmented clean/synthetic samples,
- genuine gameplay crops.

Avoid allowing many near-identical crops from a single event to dominate training.

Options:

- cap crops per event per epoch,
- sample events first and then crops,
- weight sessions/events rather than individual frames.

Continue evaluating exclusively on held-out sessions.

## Decision Gate C

Measure the improvement from:

```text
synthetic only
vs.
synthetic + real
```

Keep both checkpoints and metrics.

The real-data pipeline should demonstrate measurable benefit before becoming more complex.

---

# Milestone 7 — Crop Quality Scoring

## 22. Implement Cheap Quality Features

For every candidate crop calculate deterministic quality indicators where practical:

- crop pixel area,
- detector confidence,
- clipping against image boundary,
- sharpness / blur estimate,
- overexposed pixel fraction,
- underexposed pixel fraction,
- crop aspect/shape anomaly.

Do not initially train a dedicated quality model.

Normalize features into a simple `quality_score`.

Keep the individual components in diagnostics.

The score is primarily for:

- selecting the best observations,
- weighting multi-frame aggregation,
- rejecting unusable evidence.

---

# Milestone 8 — Multi-Frame Classification

## 23. Classify Multiple Observations

For the selected event track:

1. rank observations by quality,
2. retain a bounded number of useful crops,
3. run the classifier on each,
4. retain the full 24-class probability vector.

Do not simply select the single best frame.

Example:

```text
frame 11 -> ♥Q .54
frame 12 -> ♥Q .81
frame 13 -> ♥Q .96
frame 14 -> ♥Q .94
frame 15 -> ♦Q .51
```

The system should preserve disagreement rather than hide it.

## 24. Aggregate Probabilities

Implement a simple baseline first.

Possible baseline:

```text
weighted mean of per-frame probability vectors
```

where weights use:

- crop quality,
- detector confidence,
- optionally classifier entropy/confidence.

Compare several simple strategies during evaluation:

- best-frame only,
- unweighted mean,
- quality-weighted mean,
- log-probability aggregation.

Choose based on held-out event accuracy, not intuition.

---

# Milestone 9 — Confidence Calibration and Abstention

## 25. Separate Ranking from Confidence

Raw softmax scores are not automatically calibrated probabilities.

Use held-out validation data to calibrate the final event score.

Possible methods:

- temperature scaling,
- simple threshold calibration,
- later isotonic regression if justified.

Track:

- reliability/calibration curve,
- expected calibration error,
- accuracy versus coverage.

## 26. Define Abstention Policy

The important production metric is not simply accuracy.

Measure:

```text
coverage = fraction of events where VisionDetector gives a confident answer

selective_accuracy =
    correctness among events where it does give an answer
```

Generate a curve such as:

```text
confidence threshold -> coverage -> accuracy
```

Choose product thresholds later.

VisionDetector v1 must support:

```text
CONFIDENT
UNCERTAIN
NO_CARD_FOUND
INSUFFICIENT_EVIDENCE
```

Do not collapse these into one generic error.

---

# Milestone 10 — End-to-End Event Evaluation

## 27. Evaluate the Full Pipeline

Run complete held-out sessions:

```text
event burst
  -> detector
  -> tracking
  -> candidate selection
  -> classifier
  -> aggregation
  -> calibration
  -> result
```

Primary metrics:

- event top-1 accuracy,
- event top-3 accuracy,
- coverage,
- selective accuracy,
- no-card-found rate,
- wrong-confident-prediction rate.

The most important failure category is:

```text
high-confidence wrong card
```

Treat abstentions as recoverable; confident mistakes are substantially more dangerous to later game reconstruction.

## 28. Attribute Failures by Stage

Every failed event should be classifiable as roughly:

```text
EVENT_TIMING
DETECTOR_MISS
TRACKING_ERROR
WRONG_CANDIDATE
BAD_CROP
CLASSIFIER_ERROR
AGGREGATION_ERROR
CALIBRATION_ERROR
INSUFFICIENT_VISUAL_EVIDENCE
```

Build a simple evaluation report that links each failed event to its diagnostic frames/crops.

This is more valuable than chasing model metrics blindly.

---

# Milestone 11 — Decide Whether Perspective Rectification Is Necessary

## 29. Measure Perspective-Related Failures

Do not implement card-corner detection preemptively.

First inspect classifier failures.

If significant failures correlate with severe perspective, build a second experiment.

### Optional CardQuadDetector

Task:

```text
image -> card bbox + 4 card corners
```

Then:

```python
homography = cv2.getPerspectiveTransform(...)
rectified = cv2.warpPerspective(...)
```

Classifier input becomes the normalized card.

Compare, on exactly the same held-out events:

```text
bbox crop classifier
vs.
rectified crop classifier
```

Only retain the keypoint/homography stage if it materially improves end-to-end results.

---

# Milestone 12 — Packaging the VisionDetector

## 30. Stable Python Interface

Expose the complete pipeline behind a small interface:

```python
class VisionDetector:
    def detect(self, evidence: EvidencePackage) -> VisionDetectionResult:
        ...
```

The rest of the backend must not depend directly on:

- PyTorch,
- YOLO,
- OpenCV internals,
- model-specific tensor formats.

Keep model implementation behind adapters.

## 31. Model Artifacts

Every model bundle should include:

```text
model weights
model type
card-set version
input preprocessing config
training dataset version
git revision
calibration parameters
metrics summary
```

The result should record the model bundle version used for inference.

This is necessary for reproducible debugging when detections stored months apart were produced by different models.

---

# Milestone 13 — Integration with the Evidence Backend

The backend built in the previous phase owns evidence persistence and job orchestration.

VisionDetector consumes an immutable evidence package or references to stored evidence.

Suggested interaction:

```text
backend
  │
  ├── stores EvidencePackage
  │
  ├── invokes VisionDetector
  │
  └── stores VisionDetectionResult
```

Persist:

- raw visual hypothesis,
- top alternatives,
- confidence/calibrated score,
- detector/model version,
- diagnostic metadata,
- references to crops used for inference.

Do not overwrite the raw visual result when a later game engine derives a different interpretation.

For example, preserve:

```text
VisionDetector:
    ♥Q .44
    ♦Q .40
```

separately from any future result such as:

```text
GameReconstruction:
    resolved as ♦Q because ♥Q is impossible
```

---

# Milestone 14 — Hard-Case Dataset Flywheel

## 32. Retain Valuable Failures

As real games accumulate, prioritize examples where:

- confidence is low,
- top classes are close,
- frames disagree,
- detector misses,
- candidate selection is ambiguous,
- later reconstruction conflicts with visual prediction,
- manual review finds a confident mistake.

These become the highest-value future training data.

## 33. Future Labeling Assistance

A larger multimodal/VLM system may later be used for:

- suggesting labels,
- reviewing hard cases,
- adjudicating specialist-model uncertainty,
- bootstrapping additional training data.

It must remain a separate component.

Do not couple VisionDetector v1 to a VLM.

---

# Testing Strategy

## 34. Unit Tests

Test deterministic code heavily:

### Domain

- card serialization,
- evidence validation,
- result validation.

### Tracking

Synthetic detection sequences:

```text
existing tracks remain stable
new card appears
card disappears
crossing detections
short false positive
```

### Quality

Known sharp/blurred/clipped examples.

### Aggregation

Hand-crafted probability vectors with known expected result.

### Calibration

Threshold and abstention behavior.

### Dataset splitting

Assert no session appears in more than one split.

---

## 35. Integration Tests

Maintain a tiny checked-in or separately fetched fixture dataset containing a few small event bursts.

Test:

```text
EvidencePackage
  -> pipeline
  -> structurally valid VisionDetectionResult
```

Do not make ordinary CI depend on GPU availability.

Model-heavy regression evaluation can run separately.

---

# Experiment Tracking

Every training/evaluation run must produce a machine-readable record.

At minimum:

```json
{
  "run_id": "...",
  "git_revision": "...",
  "model": "...",
  "config": "...",
  "dataset_version": "...",
  "train_sessions": ["..."],
  "validation_sessions": ["..."],
  "seed": 1234,
  "metrics": {}
}
```

A heavyweight experiment platform is optional.

Start with:

```text
config files + JSON metrics + model artifacts
```

Add MLflow/W&B/etc. only if the workflow begins to justify it.

---

# Compute Strategy

The workflow should run locally for:

- preprocessing,
- dataset inspection,
- unit tests,
- inference debugging,
- small experiments.

GPU training can run on RunPod or another commodity GPU provider.

Do not design training around a specific cloud.

Training scripts must be executable as normal CLI programs against local filesystem paths so they can be moved between:

```text
local machine
RunPod
other GPU VM
CI/evaluation environment
```

without changing application logic.

---

# Initial Dependency Direction

Use ordinary Python tooling.

Likely core dependencies:

```text
PyTorch
torchvision
OpenCV
NumPy
Pillow
Pydantic/dataclasses
scikit-learn
```

For the prototype detector, an Ultralytics YOLO implementation is acceptable.

Keep it isolated behind the detector abstraction because licensing and deployment requirements may later motivate replacing it.

Pin an internally compatible dependency set when implementation begins rather than encoding library-version assumptions into the architecture.

---

# Recommended Implementation Order

Execute in this exact order unless measurements force a change.

## Stage 1 — Recognition hypothesis

```text
[ ] define card/domain model
[ ] label event timestamps in existing videos
[ ] capture 48 clean source-card images
[ ] implement synthetic augmentations
[ ] train 24-class classifier
[ ] manually crop 100–300 real examples
[ ] evaluate synthetic -> real transfer
```

**Gate:** card identities are visually recoverable from real footage.

## Stage 2 — Localization

```text
[ ] sample diverse gameplay frames
[ ] define annotation policy
[ ] annotate ~500–1,500 frames
[ ] train one-class detector
[ ] inspect detector failures
```

**Gate:** played cards appear in detector output in enough frames per event.

## Stage 3 — Event pipeline

```text
[ ] implement temporal association
[ ] implement candidate-track selection
[ ] run end-to-end on labeled events
[ ] extract real card crops automatically
```

**Gate:** the correct physical card track is usually selected.

## Stage 4 — Improve recognition

```text
[ ] fine-tune classifier with real crops
[ ] implement crop quality scoring
[ ] classify multiple frames
[ ] compare aggregation strategies
```

**Gate:** multi-frame event recognition materially beats single-frame recognition.

## Stage 5 — Reliability

```text
[ ] calibrate event confidence
[ ] implement abstention
[ ] produce accuracy-vs-coverage curves
[ ] categorize every important failure
```

**Gate:** confident errors are rare enough for later reconstruction work.

## Stage 6 — Add complexity only if justified

Potential additions, in order of likely value:

```text
[ ] four-corner/keypoint detector + homography
[ ] better temporal association
[ ] learned crop-quality model
[ ] segmentation
[ ] specialist hard-case model
[ ] VLM fallback/reviewer
```

Each requires an A/B evaluation against the existing event-level benchmark.

---

# Definition of Done for VisionDetector v1

VisionDetector v1 is complete when:

1. it accepts a stored evidence burst through a stable Python API,
2. it does not consume player/turn/game-state information,
3. it detects and temporally associates visible cards,
4. it identifies the most likely newly appearing card track,
5. it classifies the event using multiple real frames,
6. it returns the complete ranked card hypothesis rather than only a label,
7. confidence has been calibrated on held-out gameplay sessions,
8. it can explicitly abstain,
9. every result records model/version diagnostics,
10. the full pipeline has been measured on whole unseen game sessions,
11. major failures can be attributed to a specific pipeline stage,
12. the raw visual result can be stored unchanged for later retrospective game reconstruction.

---

# Main Engineering Principle

Do not optimize individual ML benchmarks in isolation.

The objective is:

```text
Given a suspected card-play event,
how often can VisionDetector produce a highly reliable visual card hypothesis?
```

The primary benchmark is therefore the **held-out event**, not the frame, crop, detector mAP, or classifier accuracy.

The system should remain deliberately decomposed until real evaluation data demonstrates that additional complexity is warranted.
