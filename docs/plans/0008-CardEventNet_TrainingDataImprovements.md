# CardEventNet Training-Data Expansion Plan
## Plan status

- **Summary:** Extend CardEventNet training data
- **Status:** Draft

## Objective

Expand CardEventNet’s training data through an iterative workflow in which tooling handles extraction, organization, model-assisted selection, and validation, while a human makes the semantic and quality-sensitive decisions.

The first target domain will be footage from modern iPhones under realistic deployment conditions. Other phones and older footage will be introduced gradually to measure whether they improve robustness without reducing performance in the primary domain.

## Working label definition

An event is positive when it should cause the system to reevaluate the visible card state—not only when it represents a valid play.

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

Ambiguous tiny movements will be labeled according to this rule:

> Label an event positive if rerunning card detection after it could legitimately produce a different table state.

## Phase 1: Establish the data contract

### LLM/tooling work

- Define the annotation schema.
- Define required video metadata:
  - device and camera
  - resolution and frame rate
  - recording date
  - game/session identifier
  - table/setup identifier
  - lighting and camera-position tags
  - source and usage permission
- Define event fields:
  - event start
  - state-change or contact time
  - event end or settled state
  - event subtype
  - confidence
  - ambiguity notes
- Create a machine-readable annotation format.
- Create written labeling guidelines with representative examples.

### Human work

- Review the event definition against actual product behavior.
- Decide how much movement is “meaningful.”
- Review a small collection of ambiguous examples.
- Approve or correct the initial taxonomy.

### Completion gate

Two people—or the same person on two separate passes—can label a sample set with reasonably consistent results.

## Phase 2: Build ingestion and dataset-indexing tooling

### LLM/tooling work

Implement a video-ingestion command that:

- Registers each original video without modifying it.
- Extracts technical metadata automatically.
- Generates a low-resolution review copy if needed.
- Creates stable video, session, and clip identifiers.
- Detects duplicate or near-duplicate videos.
- Produces thumbnails or contact sheets.
- Stores annotations separately from the original video.
- Tracks dataset and annotation versions.

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

### LLM/tooling work

Build a lightweight review interface or annotation workflow that supports:

- Fast video scrubbing
- Event start/end selection
- Keyboard shortcuts
- Event-subtype selection
- Explicit hard-negative marking
- Ambiguity flags
- Side-by-side display of frames before and after the event
- Export to the training format

Preselect candidate moments using simple signals such as motion, visual change, or the existing CardEventNet model. The tool must also sample low-motion periods so the dataset is not limited to candidates found by the current model.

### Human work

- Label positives, hard negatives, and ordinary background.
- Correct proposed time boundaries.
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
- Timing error around event onset and completion
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

- Invalid or overlapping timestamps
- Duplicate clips
- Missing metadata
- Suspiciously short or long events
- Conflicting labels
- Leakage between dataset splits
- Class and source imbalance

### Step D — Human quality-control sample

The human relabels a small random sample without seeing the original labels. Disagreements are used to improve the guidelines or correct the dataset.

### Step E — Retraining and comparison

The tooling retrains the model and compares it with the current accepted model on the unchanged test set. It generates clips for every new regression and major improvement.

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

1. Finalize the positive-event rule and event subtypes.
2. Collect 10–20 independent modern-iPhone sessions.
3. Implement ingestion, metadata indexing, and session-safe splits.
4. Build candidate extraction and a fast manual review workflow.
5. Label a small but diverse seed dataset.
6. Train a baseline and generate error-review clips.
7. Add labels specifically for the largest error categories.
8. Repeat until modern-iPhone performance stabilizes.
9. Introduce one other-phone domain and measure its effect.
10. Continue expanding by demonstrated coverage gaps rather than indiscriminately adding old footage.

## Division of responsibility

The LLM/tooling side should handle repetitive, measurable, and reproducible work: extraction, candidate selection, metadata, validation, training, evaluation, and review-queue creation.

The human should retain decisions that depend on product intent or visual interpretation: whether a state change matters, whether a label is correct, whether footage is representative, and whether a model regression is acceptable.

The central rhythm is:

> Tool proposes → human corrects → tool validates and retrains → human reviews failures → tooling is improved → next data batch is selected.