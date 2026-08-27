# DokoDetector Data Foundation

## Plan status

- **Summary:** Make source, annotation, review, split, and lineage data reliable before analyzer work
- **Status:** Closed
- **Closure reason:** Complete
- **Closure note:** M0 through M4 are complete. The shared data lifecycle, reviewed table-observation
  path, deterministic dataset and split assembly, and lifecycle receipts are implemented and verified.
- **Depends on:** None
- **Reviewed:** 2026-08-27 against the glossary, current CardEventNet data tools, and local dataset
- **Starts now:** In parallel with plans 0006 and 0025
- **Unblocks:** The TableEvidenceAnalyzer training pipeline and later capability experiments
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Outcome

Create one coherent, versioned data lifecycle for DokoDetector while keeping component-specific
labels separate.

At the end of this plan, a developer can answer:

```text
Where did this source asset come from?
May we use it for this purpose?
Which recording, if any, did it come from, and which session contains that recording?
Which games and rounds does the recording show, if any?
Which annotation and review version applies?
Is it eligible for training, validation, or test?
Which derived frames and crops came from it?
Which training run consumed it?
```

This foundation starts before a useful TableEvidenceAnalyzer exists. Do not postpone data design
until model training produces failures.

## 2. Current baseline

The repository already contains strong CardEventNet foundations:

- immutable raw videos under `card_event_net/data/raw/`;
- typed point-event annotations and separate reviewed annotation versions;
- video metadata and annotation JSON schemas;
- deterministic ingestion and dataset inspection;
- session-aware split validation;
- deterministic caches and preprocessing identifiers;
- review queues, interactive review, and apply receipts;
- run records and event-level diagnostics;
- the V1 evidence-package contract and stored-package backend.

The current worktree also shows why a formal intake state is needed: five new annotated videos are
indexed but are not in `full-frame-development.yaml`, so the manifest test fails. New source data
must be allowed to exist as reviewed or unreviewed intake before a human promotes it into a split.

The current worktree also contains the first strict `vision-annotation/v1` frame-only event schema,
review artifacts, and contract tests. Its validation and review mechanics are reusable, but its
event-shaped schema follows the superseded boundary.

The repository does not yet contain:

- a table-observation annotation schema;
- a shared identity and lineage model across sessions, recordings, evidence packages, frames, and
  crops;
- explicit dataset eligibility and promotion states;
- one coverage report for cards, devices, decks, environments, and failure conditions;
- a stable handoff from reviewed table observations to TableEvidenceAnalyzer datasets;
- one policy for source permission, retention, deletion, and derived artifacts.

Do not replace the working CardEventNet formats without a migration need. Add shared identity and
lineage around them.

## 3. Data layers

Keep these layers distinct:

```text
source
  immutable videos, evidence packages, and clean deck references
      |
      v
annotations
  human claims about events, cards, boxes, visibility, and quality
      |
      v
reviews
  decisions, reviewer provenance, and apply receipts
      |
      v
dataset versions
  frozen eligible records and group-safe splits
      |
      v
derived artifacts
  decoded frames, crops, tensors, previews, and caches
      |
      v
training and evaluation runs
  exact dataset, split, config, code, and artifact hashes
```

Never edit an accepted source asset to correct an annotation. Never treat a model proposal as human
ground truth. Never infer dataset eligibility only from the presence of a file.

## 4. Canonical identity and lineage

Define stable identifiers for:

```text
source_asset_id
session_id
game_id, when known
round_id, when known
recording_id
video_id
evidence_package_id
video_snippet_id, when present
event_id
frame_id
observation_id
observed_card_id
card_tracklet_id, when present
annotation_set_id
review_id
dataset_version
split_version
derived_artifact_id
training_run_id
model_bundle_id
```

Add the video-snippet, observation, observed-card, and card-tracklet identifiers when their owning
contracts exist. They are additive lineage extensions and do not block the current M1 source and
dataset contract.

Rules:

- derive content identity from SHA-256 where practical;
- keep operator-owned semantic identity separate from a content hash;
- preserve the session and recording identities across a recording and its evidence packages;
- preserve video-snippet identity as one immutable part of its evidence package;
- record which snippet and time range produced each decoded tracking frame;
- let one session contain several recordings and parts of several games;
- let one game span several sessions;
- associate a recording with games and rounds through explicit time spans instead of one scalar
  `game_id`;
- keep staged activity associated with its session and recording, with no invented game or round;
- group all assets from one session, game, table setup, or shared source lineage for leakage checks;
- record the source frame and transform for every crop;
- record the annotation and review version used to create every target;
- never reuse an identifier for different bytes or meaning;
- do not use an absolute local path as identity.

Session identity is operator-owned semantic data. Do not derive it from a recording UUID, file
name, timestamp, or dataset partition. Use explicit nullable fields when a game, round, or session
fact is not known. Do not invent grouping data to make a manifest validate.

## 5. Source and permission model

Each source asset records:

- byte length and SHA-256;
- media type and technical probe data;
- acquisition method and original filename;
- session identity and table setup, when known;
- referenced game and round time spans, when known;
- staged-activity classification when the recording is not part of a game;
- camera/device class and orientation, when known;
- deck design and physical-deck identifier, when known;
- environment and scenario tags confirmed by a human;
- source permission and allowed uses;
- retention and deletion state;
- known limitations;
- import receipt and parent asset, if derived from another accepted bundle.

Keep raw source bytes immutable. Derived review videos, thumbnails, frames, and crops are disposable
artifacts that can be regenerated from a versioned transform.

Plan 0019 may later add app-sourced recording bundles. Those bundles enter through this same source
and permission model. They do not create a parallel dataset lifecycle.

## 6. Annotation boundaries

### CardEventNet annotations

Continue to use typed temporal point events and separate hard negatives. Preserve event proposals
as unconfirmed provenance. Keep complete-video review as the gate for detecting proposal misses.

### TableEvidenceAnalyzer annotations

The current worktree establishes `vision-annotation/v1` for one visual event, its selected frames,
and an optional reviewed played-card identity. That implementation follows the old event-result
boundary. Replace it with the table-observation annotation shape before other work depends on it.
Reuse internal validation and review code where it fits, but do not maintain both undeployed schemas.

Add a versioned table-observation annotation schema. One annotation set refers to an accepted
evidence package or to equivalent evidence derived from an accepted recording. It can label several
visible cards across selected frames and a video snippet.

Keep event review and visual review separate. An event proposal can be false while its frames still
contain visible cards. A visible card is not automatically a card play.

```json
{
  "schema_version": "table-observation-annotation/v1",
  "annotation_set_id": "...",
  "source": {"package_id": "..."},
  "observed_cards": [
    {
      "observed_card_id": "...",
      "visual_card_identity": "HEARTS_QUEEN",
      "visibility": "identifiable",
      "frame_observations": [
        {
          "frame_id": "...",
          "bbox": [412, 280, 611, 527],
          "usable_for_identity": true,
          "tags": ["glare", "partial_occlusion"]
        }
      ],
      "became_newly_visible": true,
      "active_area_class": "inside"
    }
  ],
  "event_review": "false_event_proposal",
  "review_state": "draft"
}
```

The exact schema is part of milestone M2. Support explicit non-card, empty, and unusable cases:

```text
false_event_proposal
no_visible_cards
card_not_visible
visible_but_not_identifiable
ambiguous_card
insufficient_visual_evidence
```

Do not invent a card label for them. Keep the human claim that a card was played separate from the
visual claim that a card was visible. Preserve uncertain associations across frames instead of
assigning a false persistent identity.

Record deck design and visual card identity as data. A physical-copy identifier may exist in
controlled source-deck references, but it is not a model target.

Tracking annotations can associate visible instances over a bounded snippet. They produce card
tracklets, not physical-card identities. Record newly-visible, active-area, movement, and occlusion
labels only when a reviewer can determine them from the evidence.

## 7. Review and promotion states

Use explicit states instead of directory names as implied truth:

```text
intake
annotating
review_required
reviewed
eligible
excluded
retired
```

Promotion to `eligible` requires:

- valid and permitted source bytes;
- complete required metadata;
- a schema-valid annotation set;
- completed review at the level required by the task;
- no unresolved duplicate or grouping conflict;
- an explicit intended use such as train, validation candidate, or sealed test candidate.

Assigning an eligible record to a split is a separate reviewed action. Ingesting or annotating a
record must not assign it automatically.

Review application writes a new annotation version and a receipt. It does not modify its input.

## 8. Dataset versions and splits

A dataset version is a frozen manifest of eligible records plus content digests. It records:

- source, annotation, and review versions;
- task and target schema;
- deck and card-set versions;
- allowed-use filter;
- inclusion and exclusion reasons;
- group keys used for leakage prevention;
- derived-artifact transform versions;
- creation code revision and dirty-state marker.

Create splits from a dataset version. Enforce isolation by session, game, table setup, and shared
source lineage. A game that spans sessions remains in one partition. Report, rather than hide,
unassigned eligible records.

Do not require every indexed or annotated intake item to belong to the current development split.
Tests should distinguish:

- all source assets are indexed;
- all split members are eligible and known;
- no isolation group crosses partitions;
- unassigned records are explicit;
- sealed test records are not used for training decisions.

## 9. Coverage and quality reports

Generate one machine-readable and one human-readable report for each dataset version.

For CardEventNet, group by:

- reviewed event type, event proposal type, and hard-negative type;
- session, game, round, table setup, device class, and content type;
- lighting, camera, background, and scenario tags;
- event spacing and known difficult transitions.

For the TableEvidenceAnalyzer, also group by:

- visual card identity and physical copy coverage;
- deck design;
- candidate crop size;
- visibility, blur, glare, perspective, occlusion, and frame boundary;
- complete versus incomplete evidence;
- false event proposals and not-visible reviewed events.
- available selected frames versus video snippets;
- visible-card count, newly-visible labels, active-area labels, and reviewed card tracklets;
- movement, reappearance, short occlusion, and complete-occlusion cases.

Coverage reports guide collection. They do not create arbitrary minimum counts or silently rebalance
sealed evaluation data.

## 10. Small implementation milestones

### M0 — Reconcile current intake and restore invariants

1. Inspect the five new videos that are outside `full-frame-development.yaml`.
2. Confirm their session, recording, game or round spans, staged-activity classification,
   permission, and intended state.
3. Keep them explicitly unassigned or promote them through a reviewed split change.
4. Update manifest tests so indexed intake is not confused with split membership.
5. Refresh the dataset index report after the human decisions.

Acceptance:

- all current raw videos and annotations are indexed;
- unassigned assets are visible and valid;
- the CardEventNet test suite passes without forcing intake into a split;
- no session, game, table setup, or shared source-lineage group crosses partitions.

### M1 — Shared identity, lineage, and eligibility contract

1. Write `DATA_CONTRACT.md` with the layers and identifiers from this plan.
2. Add schemas or typed models for source records, lineage edges, eligibility, and dataset versions.
3. Add a small fixture that links one session, recording, evidence package, frame, annotation, and
   crop. Include either a game and round span or an explicit staged-activity classification.
4. Preserve adapters for the existing CardEventNet V1 manifests.

Acceptance:

- the fixture traces a derived crop back to immutable source bytes;
- permissions and review state survive export;
- identical inputs produce the same dataset-version digest.

### M2 — Table-observation annotation and review path

1. Replace the current `vision-annotation/v1` draft with `table-observation-annotation/v1`.
2. Reuse the strict source, box, review, and receipt code where its meaning still matches.
3. Extend the evidence viewer so that it can confirm or reject an event proposal and annotate all
   visible cards, identity, visibility, boxes, and quality tags.
4. Allow optional newly-visible, active-area, occlusion, and tracklet annotations when the evidence
   supports them.
5. Keep immutable review and apply artifacts for the table-observation path.
6. Import a small set of real evidence packages or recording-derived events.

Acceptance:

- false event proposals and invisible, ambiguous, and identifiable reviewed events remain
  distinct;
- all annotation fixtures and review receipts use the table-observation schema;
- a reviewer can inspect all frames and the optional snippet around one event proposal;
- visible-card evidence remains distinct from a reviewed card-play claim;
- source evidence is unchanged;
- event proposals never become labels without review.

### M3 — Dataset assembly and group-safe splits

1. Build a TableEvidenceAnalyzer dataset manifest from reviewed annotations.
2. Add deterministic eligibility filtering and split creation.
3. Add leakage, duplicate, and lineage validation.
4. Add coverage reports and explicit unassigned output.

Acceptance:

- no source lineage group crosses train, validation, and test;
- one command validates a frozen dataset version;
- training code can consume the manifest without scanning ad hoc directories.

### M4 — Lifecycle documentation and receipts

Document the normal operator flow from source intake through review and dataset promotion. Add
receipts for import, annotation application, dataset creation, split creation, and retirement.

Acceptance:

- a new contributor can add data without editing source bytes;
- a model run can name every source and label version it used;
- deletion or permission withdrawal can identify affected derived artifacts and runs.

## 11. Out of scope

- recording capture and upload implementation from plan 0019;
- video-snippet capture and transport implementation from plan 0025;
- model architecture selection;
- TableEvidenceAnalyzer training loops;
- automatic training after annotation;
- cloud object storage or a hosted labeling platform;
- automatic labels accepted without human review;
- production retention periods before product requirements exist.

## 12. Verification

Run the existing CardEventNet tests plus the new data-contract and TableEvidenceAnalyzer-data tests.
Keep fixtures small and local. Tests must not require a camera, network, display server, or GPU.

Before this plan closes, run one clean-room exercise:

```text
new source asset
  -> immutable intake
  -> annotation and review
  -> eligible dataset version
  -> group-safe split
  -> derived crop with complete lineage
```

## 13. Definition of done

- current intake and split invariants are correct and tests pass;
- shared source identity, permission, lineage, and eligibility contracts exist;
- CardEventNet keeps its working annotation and review workflow;
- TableEvidenceAnalyzer has one reviewed table-observation annotation path;
- dataset versions and splits are deterministic and leakage-safe;
- unassigned and excluded data remain explicit;
- coverage reports guide the next sourcing work;
- every training sample can be traced to immutable source and reviewed annotation versions.
