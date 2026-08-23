# CardEventNet Training-Data Expansion Plan

## Plan status

- **Summary:** Extend CardEventNet training data
- **Status:** In progress; Phase 1 drafted, full-frame migration and consistency gate pending

## Objective

Expand CardEventNet's training data through an iterative workflow. Tooling handles extraction,
organization, model-assisted selection, and validation. A human makes semantic and
quality-sensitive decisions.

The primary target domain is real Doppelkopf footage from modern iPhones under realistic
deployment conditions. Introduce other phones and older footage gradually. Measure whether each
domain improves robustness without reducing performance in the primary domain.

## Related work and current evidence

This plan uses the tooling and findings from:

- [0010](0010-CardEventNet_Training_Diagnostics.md), which added event-level threshold,
  per-video, and failure diagnostics;
- [0011](0011-CardEventNet_Corrective.md), which added typed annotations, three-way temporal
  labels, peak-based decoding, optimal event matching, exact threshold calibration, and
  session-aware manifest support;
- [0012](0012-CardEventNet_Unattended_Improvement_Loop.md), which used those diagnostics to reduce
  validation false events and then stopped after one final test evaluation;
- [0013](0013-CardEventNet_FullFrameInput.md), which removes manual ROI setup and aligns training
  with full-frame production input.

The completed improvement loop showed that threshold tuning is not sufficient. Validation recall
reached 0.9875 and false events fell from 144 to 44. The one-time test evaluation reached only
0.8951 recall. Many remaining false triggers have high confidence, and no
confirmed-hard-negative manifest was used. Before the next data cycle, annotations must cover
every meaningful state change. Otherwise, a real but missing event can be trained as a negative.

Do not use the old test failures to tune the full-frame pipeline. Treat that result as the final
estimate for the ROI pipeline. Record a new independent held-out session before the final
full-frame evaluation.

## Current data domain

The current videos are **staged trick sequences**. A staged trick sequence is real camera footage
in which a person plays repeated groups of four cards without playing a real game. Use
`staged_trick_sequence` in video metadata. Do not call this footage synthetic or artificial.

This footage has useful diversity:

- realistic camera setups and angles;
- varied lighting and backgrounds;
- varied card positions.

It also has known domain gaps:

- play cadence is too regular;
- pauses between tricks are shorter than many game pauses;
- separate plays do not overlap enough;
- mistakes and corrections are rare;
- one actor moves the cards;
- no game decisions occur.

Record these properties in metadata. Do not infer them later from filenames. More footage from
the same domain will not by itself close these gaps.

Most current videos use tight table framing. This makes full-frame migration practical, but it is
also a coverage gap. Add contextual and wide framing after the migration. Record the framing in
`camera_framing`.

## Working label definition

An event is positive when it should cause the system to reevaluate the visible card state. It does
not have to be a valid play.

Positive examples include:

- A normal card play
- A card being removed or withdrawn
- A card being moved to a meaningfully different position
- A card from an old trick falling onto the table
- Multiple cards being dropped
- A correction or other anomalous card-state change

Hard negatives include:

- A hand hovering over cards
- Pointing or touching without meaningful displacement
- Temporary occlusion
- Shadows, sleeves, drinks, or unrelated objects moving
- Camera shake, autofocus, or exposure changes
- Cards being handled exclusively in a player’s hand

Use this rule for ambiguous movement:

> Label an event positive if rerunning card detection after it could legitimately produce a different table state.

The operational movement threshold is one quarter of a card's visible short edge or 15 degrees of
rotation. Also label smaller movement when it changes card identity, overlap, role, or ownership.
Do not label smaller taps or jitter when the useful state stays the same.

The complete class and timing rules are in
[CardEventNet labeling guidelines](../CardEventNet_LabelingGuidelines.md).

## Phase 1: Establish the data contract

### Decisions

- Use `staged_trick_sequence` for the current repeated four-card recordings.
- Use the complete camera frame. Do not define a manual ROI or a geometric active area.
- Keep annotations as point events. Do not store movement intervals.
- Set an event time at the earliest frame where the new state is observable.
- Do not wait for a hand to leave or for the table to become empty.
- Label close semantic events separately, even inside the current decoder gap.
- Store hard negatives separately from positive event annotations.
- Keep model proposals unconfirmed until a human reviews them.

### Implemented tooling work

- The versioned video metadata contract is defined in
  [`video-metadata-v1.schema.json`](../../card_event_net/schemas/video-metadata-v1.schema.json).
- A complete staged-video example is in
  [`dataset-manifest.example.yaml`](../../card_event_net/data/dataset-manifest.example.yaml).
- Metadata distinguishes a recording session, a real game, and a physical table setup.
- Metadata records content type, technical capture data, camera geometry, lighting, scenario
  coverage, known limitations, provenance, and usage permission.
- The current annotation JSON remains backward compatible. Its machine-readable V1 contract is
  [`annotation-v1.schema.json`](../../card_event_net/schemas/annotation-v1.schema.json).
- The V1 ROI is legacy preprocessing data. Plan 0013 will introduce ROI-free V2 annotations and
  keep V1 read compatibility.
- Events contain `time_s`, `type`, optional `confidence`, and optional `notes`.
- The labeling guide defines every event class, timing, meaningful movement, close events, hard
  negatives, and confidence states.
- The manifest loader accepts legacy records. It applies the complete field contract when
  `schema_version` is `cardevent-video-metadata/v1`.

### Human work

- Review a small sample of real and staged video with the new guide.
- Check the movement threshold against actual VisionDetector state changes.
- Review close plays and immediate trick collection.
- Review face-down cards, visible collection stacks, and scoring cards left aside.
- Approve or correct the taxonomy and controlled metadata values.

### Completion gate

Two people, or the same person on two separate passes, can label a sample with consistent event
counts, classes, and timestamps. Record disagreements and update the guide before Phase 3 starts.

**Current gate status:** The metadata schema and semantic guide exist. Full-frame migration and
the two-pass human consistency check remain.

## Prerequisite: remove CardEventNet ROI setup

Implement [plan 0013](0013-CardEventNet_FullFrameInput.md) before the next large data cycle. It
will:

- remove ROI selection from annotation;
- keep legacy annotation files readable;
- rebuild caches from complete frames;
- retrain CardEventNet with full-frame inputs;
- align Python, Core ML, live iOS, and replay preprocessing;
- add contextual footage and hard negatives.

Do not mix an ROI-trained checkpoint or ROI cache with full-frame inference.

## Phase 2: Build ingestion and dataset-indexing tooling

**Current state:** Session-aware split creation and validation exist. No populated metadata
manifest proves that the current split is session-isolated. The general ingestion and
dataset-indexing command does not exist.

### LLM/tooling work

Implement a video-ingestion command that:

- Registers each original video without modifying it.
- Preserves and indexes the complete source frame.
- Extracts technical metadata automatically.
- Generates a low-resolution review copy if needed.
- Creates stable video, session, and clip identifiers.
- Detects duplicate or near-duplicate videos.
- Produces thumbnails or contact sheets.
- Stores annotations separately from the original video.
- Tracks dataset and annotation versions.
- Writes records that conform to `cardevent-video-metadata/v1`.

Add safeguards that prevent clips from the same game or session from being split across training, validation, and test sets.

### Human work

- Supply an initial batch of modern-iPhone videos.
- Group them into actual games and recording sessions.
- Add metadata that cannot be inferred automatically.
- Exclude footage without suitable permission or with unusable framing.

### Completion gate

A newly supplied folder of videos can be ingested reproducibly and appears in a searchable dataset index.

## Phase 3: Create a small, carefully labeled seed dataset

Start with a relatively small number of varied sessions rather than a huge number of clips from one recording.

**Current state:** The annotator supports typed point events, timestamp edits, confidence changes,
model proposals, and before/after comparison. The versioned review-queue and apply workflow from
plan 0011 is implemented. The first full-frame validation queue contains 78 unreviewed items. The
apply command requires explicit review status and writes a complete new annotation directory. It
does not modify the source annotations. A new confirmed positive also requires an explicit event
type. A separate training queue contains 278 unreviewed items across all 19 training videos.

### LLM/tooling work

Build a lightweight review interface or annotation workflow that supports:

- Fast video scrubbing
- Point-event timestamp selection
- Keyboard shortcuts
- Event-subtype selection
- Separate, reviewed hard-negative marking
- Ambiguity flags
- Side-by-side display of frames before and after the event
- Export to the training format

Preselect candidate moments using simple signals such as motion, visual change, or the existing CardEventNet model. The tool must also sample low-motion periods so the dataset is not limited to candidates found by the current model.

### Human work

- Label positives and review proposed hard negatives and ordinary background.
- Correct proposed point-event timestamps.
- Mark unusual or ambiguous cases.
- Identify missing event categories.
- Note recurring false triggers such as hands, shadows, and camera motion.

A suggested seed set should contain:

- Normal plays
- Repositioning and corrections
- Accidental or anomalous card events
- Hard negatives involving hands near cards
- Quiet background intervals
- A range of players, tables, decks, lighting, and camera positions

### Completion gate

The seed dataset covers every known event type and contains enough hard negatives to train a meaningful baseline.

## Phase 4: Train and evaluate the baseline

**Current state:** The reproducible training and event-diagnostic pipeline exists. Dataset-domain
and per-session reporting remain limited until V1 metadata is populated.

### LLM/tooling work

Implement a reproducible training and evaluation pipeline with:

- Dataset-version recording
- Session-level train/validation/test splits
- Fixed random seeds
- Saved configurations and checkpoints
- Class and subtype statistics
- Event-level precision, recall, and F1
- False triggers per hour
- Missed events per game
- Event timestamp error and emission latency
- Per-domain results, initially including modern-iPhone footage
- Automatically generated false-positive and false-negative review queues

Event-level evaluation should be primary. Frame-level accuracy alone can look excellent because most video frames contain no event.

### Human work

- Inspect false positives and false negatives as video clips.
- Decide whether failures reflect:
  - incorrect model behavior
  - incorrect labels
  - unclear labeling policy
  - missing training scenarios
  - unsuitable evaluation matching rules
- Rank failure categories by product impact.

### Completion gate

The baseline has a trustworthy test set, reproducible metrics, and an understandable error breakdown.

## Phase 5: Active-learning loop

Repeat this loop for each new batch of footage.

### Step A — Machine triage

The tooling runs CardEventNet over unlabeled videos and selects:

- High-confidence predicted events
- Low-confidence or unstable predictions
- Disagreements between model versions
- Likely false triggers
- Long intervals with no predicted events
- Visually novel footage
- A random control sample

### Step B — Human review

The human:

- Confirms or rejects proposed events.
- Adds missed events.
- Labels event subtypes and ambiguous cases.
- Identifies new hard-negative categories.
- Reviews a random sample of supposedly empty footage to estimate missed-event bias.

### Step C — Automated validation

The tooling checks for:

- Invalid timestamps and effective duplicates
- Close point events that need review but are not automatically invalid
- Duplicate clips
- Missing metadata
- Suspicious event gaps and dense event clusters
- Conflicting labels
- Leakage between dataset splits
- Class and source imbalance

### Step D — Human quality-control sample

The human relabels a small random sample without seeing the original labels. Disagreements are used to improve the guidelines or correct the dataset.

### Step E — Retraining and comparison

The tooling retrains the model and compares it with the current accepted model on an unchanged
validation set. It generates clips for every new regression and major improvement. Use the sealed
test set only after labels, decoder settings, threshold policy, and checkpoint selection are
frozen.

### Step F — Human acceptance

The human accepts the new model only when:

- Improvements correspond to genuine product improvements.
- Important modern-iPhone performance has not regressed.
- False triggers remain acceptable.
- Gains are not limited to nearly duplicated footage.

## Phase 6: Expand to other devices and older footage

Introduce new source domains one at a time:

1. Other modern iPhones
2. Older iPhones
3. Modern Android phones
4. Older Android phones
5. Compressed, transferred, or otherwise degraded footage
6. Unusual orientations, frame rates, and lighting conditions

For each domain:

### LLM/tooling work

- Create a domain-specific evaluation subset.
- Measure the existing model before adding the new footage.
- Select representative and failure-heavy samples for labeling.
- Train with several mixing ratios.
- Report target-domain and new-domain results separately.

### Human work

- Verify that the footage still represents plausible use.
- Reject videos whose card state cannot be labeled reliably.
- Review whether improvements in the new domain justify any regression in the primary domain.
- Decide whether the source belongs in general training, pretraining only, or a robustness test set.

Initially, aim for approximately:

- 70–80% footage matching the intended deployment domain
- 20–30% controlled diversity from other domains

Treat this as an experiment rather than a permanent fixed ratio.

## Phase 7: Improve coverage deliberately

After the first active-learning cycles, stop measuring progress primarily by hours of video. Track coverage instead:

- Number of independent games and sessions
- Number of tables, decks, and players
- Number of camera positions
- Device distribution
- Lighting distribution
- Frequency of each event subtype
- Frequency of each hard-negative subtype
- Rare-event coverage
- Label confidence and disagreement rate

The human should prioritize collecting scenarios missing from this matrix. The tooling should report which cells are empty or underrepresented.

## Phase 8: Ongoing dataset maintenance

### LLM/tooling work

- Version datasets and label revisions.
- Produce a changelog for each dataset release.
- Detect duplicate sessions and split leakage.
- Track which examples affect recurring failures.
- Maintain a small regression suite of difficult, representative clips.
- Generate periodic data-quality and source-balance reports.

### Human work

- Approve changes to label definitions.
- Review recurring ambiguous cases.
- Retire incorrect labels without silently rewriting dataset history.
- Add real-world failures from product testing to the regression suite.
- Decide when a domain deserves its own model or preprocessing path.

## Recommended first iteration

1. Preserve the locked ROI result. Do not tune from its test failures.
2. Review the 78 candidates in the generated full-frame validation queue. Python annotation,
   cache, training, inference, and review-queue tooling is implemented. The first paired run had
   40.9% more false events/hour than the ROI baseline, so iOS migration remains blocked.
3. Complete the two-pass Phase 1 consistency check on a small sample.
4. Review the generated V1 metadata and capture-time session groups for the existing footage.
5. Correct missing state-change annotations before mining hard negatives.
6. Collect independent real-game sessions and targeted staged scenarios for the known gaps.
7. Reserve a new independent session for future full-frame testing.
8. Apply the reviewed queue to a new annotation version. Then train on a session-safe split and
   generate the next failure-review queue.
9. Repeat until modern-iPhone real-game validation performance stabilizes.
10. Evaluate the new held-out test once, then introduce one other-phone domain.

## Division of responsibility

The LLM/tooling side should handle repetitive, measurable, and reproducible work: extraction, candidate selection, metadata, validation, training, evaluation, and review-queue creation.

The human should retain decisions that depend on product intent or visual interpretation: whether a state change matters, whether a label is correct, whether footage is representative, and whether a model regression is acceptable.

The central rhythm is:

> Tool proposes → human corrects → tool validates and retrains → human reviews failures → tooling is improved → next data batch is selected.
