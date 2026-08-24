# CardEventNet review queue workflow plan

## Plan status

- Summary: Add an interactive workflow for reviewing CardEventNet review queues
- Status: Implemented
- Depends on: plans 0008, 0011, and 0013

## Problem

`cardevent review-queue` creates deterministic model and annotation discrepancies. `cardevent
apply-review` applies completed decisions to a new annotation version. The human step between
these commands is not integrated.

Today, a reviewer must:

1. Read a queue item from JSON.
2. Find the source video.
3. Open the video with `cardevent annotate` or another player.
4. Seek to the item timestamp.
5. Inspect the visible state change.
6. Edit the queue JSON by hand.

`cardevent annotate --proposals` does not solve this problem. It reads a top-level `events` or
`proposals` list. A review queue uses `items`, can contain several videos, and stores review
categories and outcomes. The annotator also writes an annotation file when it exits. A queue
review must not modify annotations directly.

## Decision

Add a separate command:

```text
cardevent review
```

Keep `cardevent annotate` as the video-centric annotation editor. Make `cardevent review`
queue-centric and read-only with respect to source annotations. Both commands should use shared
video display, seeking, before/after comparison, event-type selection, and keyboard handling
components.

Do not add `--review-queue` mode to `cardevent annotate`. The two workflows have different units
of work and different outputs:

| Workflow | Unit of work | Output |
|---|---|---|
| `cardevent annotate` | One video | One annotation file |
| `cardevent review` | Ordered queue items across videos | One reviewed queue |
| `cardevent apply-review` | One reviewed queue | A new annotation version and hard negatives |

This separation prevents an inspection session from changing source annotations. It also gives
hard-negative and ignore decisions a proper home. These decisions do not belong in positive-event
annotation JSON.

## Intended workflow

```text
model + annotations
        |
        v
cardevent review-queue
        |
        v
unreviewed queue
        |
        v
cardevent review       human visual decisions, autosaved
        |
        v
reviewed queue
        |
        v
cardevent apply-review
        |
        +--> new annotation directory
        +--> reviewed hard-negative file
        +--> change and provenance summary
```

No step should overwrite the source queue or source annotation directory by default.

## Command contract

The initial command should be:

```bash
cardevent review \
  --queue data/outputs/run/review-val.json \
  --out data/reviews/review-val-niklas.json \
  --videos-dir data/raw \
  --annotations-dir data/annotations \
  --reviewer niklas
```

Required arguments:

- `--queue`: an unreviewed or partly reviewed `cardevent-review-queue-v1` file;
- `--out`: the reviewed queue copy;
- `--videos-dir`: the source video directory;
- `--annotations-dir`: the read-only annotation directory used for context;
- `--reviewer`: a stable reviewer name.

Optional filters:

- `--video VIDEO_ID`: review one video;
- `--category CATEGORY`: review one queue category;
- `--include-reviewed`: include completed items when navigating;
- `--start-item ITEM_ID`: start at a specific item.

The default order must match the queue order. Filters must not reorder items. The command must
show the number of selected, reviewed, and remaining items before it opens a video window.

If `--out` does not exist, create it as a reviewed working copy. If it exists, resume it only when
its source queue checksum and item identities match `--queue`. Reject a different queue, reviewer,
or immutable item set with a clear error.

## Review screen

Open the video for the current item and seek directly to `timestamp_s`. When the next item uses a
different video, close the old capture and open the new one automatically.

Show this information in the video overlay:

- queue position and remaining count;
- video name and timestamp;
- review category;
- model score;
- nearest annotation type, time, and distance;
- selected semantic event type;
- current outcome;
- reviewed or unreviewed status;
- current playback state.

The current frame is the primary view. Before/after comparison should show frames 0.5 seconds
before and after the current position. The reviewer must be able to toggle this view.

Do not extract hundreds of duplicate preview clips for the normal workflow. Decode the requested
frames from the source video. Evidence extraction can remain a separate diagnostic command.

## Controls

Reuse familiar annotator controls where their meaning is unchanged:

```text
P       pause or play
A / D   seek backward or forward about 250 ms
J / L   seek backward or forward about 2 s
C       toggle before/after comparison
1-7     select semantic event type
N / B   next or previous queue item
Q       save and exit
```

Add review decisions:

```text
Y       add a new confirmed positive at the current frame
E       confirm the nearest existing annotation
H       confirmed hard negative
R       correct the nearest annotation timestamp to the current frame
I       ignore this item
U       clear the decision and return the item to unreviewed
M       add or edit a review note
```

Decision behavior:

- `Y` requires a selected event type. Set `positive_target` to `new_event`, set `timestamp_s` to
  the current frame, and preserve the original candidate timestamp for provenance.
- `E` requires exactly one nearest source annotation. Set `positive_target` to
  `existing_annotation`. Preserve that annotation's time and type. This records that the existing
  label is correct and must not add a duplicate event.
- `H` clears event type and corrected-timestamp fields.
- `R` requires exactly one nearest source annotation. Set the corrected time to the current frame.
- `I` clears event type and corrected-timestamp fields.
- `U` clears all mutable decision fields.
- `M` stores human context. Require a note for `anomalous_state_change`.
- A completed decision sets `status` to `reviewed` and advances to the next selected item.
- Navigation without a decision keeps the item `unreviewed`.

Ask for confirmation before changing an already reviewed item. Do not ask for confirmation for a
new decision because every decision is reversible until `apply-review` runs.

## Queue persistence contract

Keep read compatibility with `cardevent-review-queue-v1`. The reviewed output should preserve all
existing queue fields and item IDs. Do not change model evidence or matching data.

The UI may change only these existing fields:

- `status`;
- `outcome`;
- `event_type`;
- `timestamp_s` when the reviewer selects a corrected time.

Add these decision fields so application does not infer annotation intent from queue category or
timestamp distance:

- `positive_target`: `new_event`, `existing_annotation`, or null;
- `source_annotation_time_s`: the immutable source annotation reference for `E` and `R`;
- `original_timestamp_s`: the queue timestamp before human adjustment;
- `review_notes`: optional human context.

Add explicit provenance fields:

```json
{
  "source_queue": "data/outputs/run/review-val.json",
  "source_queue_sha256": "...",
  "reviewer": "niklas",
  "review_started_at": "2026-08-24T10:00:00Z",
  "review_updated_at": "2026-08-24T10:12:00Z",
  "items": [
    {
      "id": "...",
      "original_timestamp_s": 56.554,
      "positive_target": "new_event",
      "source_annotation_time_s": null,
      "reviewed_at": "2026-08-24T10:04:00Z",
      "review_notes": null
    }
  ]
}
```

These fields are optional when loading an old V1 queue and required in output written by
`cardevent review`. Extend queue validation to check their types and consistency.

Write the complete output atomically after every decision and when the user exits. A crash may
lose the current undecided seek position, but it must not lose the last completed decision or
leave invalid JSON.

The input queue must remain byte-for-byte unchanged.

## Annotation and hard-negative safety

`cardevent review` must open annotations in read-only mode. It may show existing events and the
nearest annotation, but it must not save an annotation file.

`cardevent apply-review` remains the only command that derives annotation changes from queue
decisions. Update it to:

- accept the provenance fields written by `cardevent review`;
- add an event only when `positive_target` is `new_event`;
- preserve an existing event when `positive_target` is `existing_annotation`;
- reject a missing or ambiguous source annotation reference;
- use the queue reviewer by default;
- reject a conflicting `--reviewer` value;
- preserve the reviewed queue beside the derived annotation version;
- keep validation hard negatives separate from training hard negatives;
- continue to reject source and output directory equality.

Do not apply an unreviewed item. Do not interpret an absent decision as `ignore`.

## Implementation phases

### Phase 1: Extract shared viewer components

Move frame capture, resizing, overlays, before/after rendering, seeking, and key normalization out
of the annotation session loop. Keep annotation state changes in the annotation module.

Use injected capture, display, and key-input interfaces in tests. The normal development loop must
not require a camera, display server, or new recorded footage.

#### Acceptance gate

`cardevent annotate` behaves as before, and its existing tests pass. Shared viewer behavior has
unit tests that use local fixtures or mocks.

### Phase 2: Add a review session model

Create a review session that:

- validates and loads a V1 queue;
- resolves every selected video by stem and supported extension;
- rejects missing or ambiguous video matches;
- exposes deterministic filtered navigation;
- tracks the current frame and selected event type;
- applies reversible review decisions in memory;
- writes an atomic reviewed working copy;
- resumes only from the matching source queue.

Keep decision logic independent from OpenCV. Test it as a pure state model.

#### Acceptance gate

All decision transitions, validation rules, filters, autosave, and resume behavior pass without
opening a video window.

### Phase 3: Add `cardevent review`

Connect the review session to the shared viewer. Start at the first selected unreviewed item. Open
the correct video and seek to its item timestamp. Implement the overlay and controls defined in
this plan.

Update CLI help with the complete controls. Do not describe the queue as supported by
`annotate --proposals`.

#### Acceptance gate

A reviewer can process items from at least two videos without entering a video name or timestamp
manually. Closing and reopening the command resumes at the first remaining item.

### Phase 4: Integrate application and provenance

Update `cardevent apply-review` for the reviewed output contract. Validate the source queue hash,
reviewer, status/outcome pairs, event types, corrected timestamps, and immutable item fields.

Add a dry-run summary before writing derived annotations:

- reviewed and remaining counts;
- positives to add;
- timestamps to correct;
- hard negatives;
- ignored items;
- affected videos.

Require `--allow-partial` if unreviewed items remain. Without that flag, stop before writing.

#### Acceptance gate

A reviewed queue produces a complete new annotation version, provenance summary, and separate
hard-negative output. Input annotations and the input queue remain unchanged.

### Phase 5: Document the human workflow

Add a short operator guide with commands for:

1. generating a validation queue;
2. reviewing and resuming it;
3. applying a complete reviewed queue;
4. reviewing the training queue;
5. applying the training queue on top of the reviewed validation annotation version;
6. validating and preparing the resulting dataset.

State clearly that confirmed validation negatives must not become training input.

#### Acceptance gate

A new reviewer can complete a small fixture queue without editing JSON or manually seeking to a
timestamp.

## Required tests

Add tests for:

- CLI parsing and help;
- V1 queue loading and reviewed-output validation;
- immutable source queue preservation;
- video resolution across `.mov`, `.MOV`, `.m4v`, and `.mp4`;
- missing and ambiguous video failures;
- deterministic ordering and filters;
- next, previous, and resume position;
- each decision and its inverse;
- event-type requirement for confirmed positives;
- new-positive and existing-positive behavior without duplicate annotations;
- nearest-annotation requirement for timestamp corrections;
- atomic autosave after each decision;
- source checksum and reviewer mismatch failures;
- incomplete-queue rejection and `--allow-partial`;
- source annotation preservation;
- end-to-end review and apply using fixture videos, mocked display input, and a temporary output
  directory.

Run the full Python tests, Ruff lint, and formatting checks before completion.

## Non-goals

This plan does not:

- ask an LLM to decide review outcomes;
- automatically accept model candidates;
- modify annotations during inspection;
- replace the labeling guide;
- add a browser or cloud annotation service;
- retrain CardEventNet;
- change the review candidate-generation algorithm;
- evaluate a held-out test partition.

## Final acceptance gate

Using the existing full-frame validation queue, a reviewer can:

1. start at the first unreviewed item;
2. inspect before and after frames;
3. seek to the correct event frame;
4. record each supported outcome without editing JSON;
5. move across videos automatically;
6. exit and resume without losing a completed decision;
7. apply the completed queue to a new annotation version;
8. verify that the source queue and source annotations did not change.

The workflow is complete when manual file lookup, manual timestamp seeking, and manual queue JSON
editing are no longer required.
