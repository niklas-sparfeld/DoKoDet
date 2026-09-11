# Table Observation and Game Reconstruction

## Status

This document defines the target architecture and the order in which to build it. The active epics
own implementation details. Update this document when an active epic changes the shared boundary.

## 1. Current development scope

The current scope is pipeline development and feasibility. The device collects recordings. Keep
its evidence packaging and upload as a showcase, but never use device packages or their media as
recording pipeline inputs or fallbacks. Preserve original video as the source asset. Derive frames,
crops, and bounded snippets from video using selected data revisions and explicit policies. Caching
and materialization are implementation details. Synthetic component fixtures remain valid.

The [glossary](glossary.md) defines pipeline data sets, data revisions, processor runs, maintained
references, review coverage, and derived views. Inputs and outputs are roles of data in a run.
Generated and reviewed content of the same type share a contract. Origin, scores, review state,
and lineage are separate metadata. Human authorship alone does not establish ground truth.

Retain completed processor results and completed reference revisions. Each recording has one
maintained reference per visual review stage, with at most one draft. A model rerun creates a new
result without changing that reference. The UI normally shows selected Generated and Reviewed
content, with other runs and completed revisions available through secondary controls.

Epic 0048 completed the shared recording-pipeline data and execution foundation. Epic 0049
completed the recording-owned review, comparison, analysis, and dataset-readiness workspace and
removed the obsolete review-batch routes and duplicate recording state. Their closed plans retain
implementation evidence. Future changes follow the active [epic board](plans/README.md).

## 2. Target process

```text
original recording video
  -> CardEventNet -> event data revision
  -> detector -> visible-card data revision
  -> classifier -> visual identity data revision
  -> observation assembly -> table observations
  -> game reconstruction -> reconstruction hypotheses and analysis
```

Each processor selects exact input revisions. Detector and classifier runs can use generated or
reviewed inputs. Resolve visual input from the video and selected content. Observation assembly
uses compatible selected event, geometry, and identity results; it is not another learned model.
The table evidence analyzer contains the detection, classification, and observation assembly work.

An event proposal is not proof of a card play. Table observations are uncertain visual evidence.
The reconstruction engine consumes observations, rules, round context, and optional correction
constraints. It does not consume pixels or make one recording equivalent to one round or game.
A reviewed visual identity is not a human assertion that a player played that card.

Observation assembly copies the selected visible-card `side` into every `ObservedCard`. The value is
`face_up`, `face_down`, or `unknown`. A known face-down card remains an anonymous observed card with
`identity_status=unusable` and no identity candidates. The table-observation publisher and the
mirrored game-engine parser retain this field exactly. Reconstruction does not use card side yet;
that decision belongs to a later reconstruction epic.

## 3. Data, review, and reproducibility

Every processor run pins its video source, input revisions, implementation, model, configuration,
and extraction policies. Selection pointers are resolved once at creation. Retrying incomplete work
uses frozen inputs; an intentional rerun retains another result. Failures remain distinct from
successful empty predictions. Keep normal local tests independent of phones and cloud services.

A maintained reference can begin empty or use generated suggestions. Review changes its draft,
not the original result. Completion publishes an immutable revision. Event review covers the full
video; visible-card review covers named frames; identity review covers named visible cards.
Unreviewed scope is never a reviewed negative. Input review does not confer truth on predictions.

Upstream changes expose affected reference work. A changed event time can select a different frame;
a changed region can alter an identity crop. Preserve unaffected work, require review on changed
evidence, and keep old revisions valid for their original scope. Runs and datasets with pinned old
revisions do not change when the maintained reference advances.

Dataset freezes select completed reference revisions, source groups, and derivation policies.
Generated data can be robustness inputs or comparison results without becoming reviewed targets.
Match comparisons on shared evidence and report missing reference coverage separately. Reuse the
same reference across model runs; do not create one human reference per model.

## 4. Table-observation contract target

The existing observation contract and adapters are the starting implementation. Epic 0048 M6
replaces package-based source identity with video and run/input lineage. Preserve the following
semantics while changing the undeployed source contract:

- `cards: []` means that the TableEvidenceAnalyzer detected no cards. It does not prove that the table was
  empty.
- `insufficient_evidence` remains distinct from an observed empty card list.
- An observed card is anonymous outside its table observation.
- Identity candidates are conditional on the proposal being a card.
- `presence_score` represents the separate possibility of a false card proposal.
- Optional evidence is absent when it is unavailable. Absence never means a score of zero.
- Association candidates and card tracklets remain uncertain. They never identify a physical copy.
- Scores in the interval from zero to one are not calibrated probabilities unless held-out evidence
  proves calibration.
- Raw evidence and earlier result versions remain unchanged.

Geometry can stay inside the TableEvidenceAnalyzer. The engine-facing `active_area_score` or
normalized distance is sufficient for the first spatial experiment. Do not add game-specific labels
such as `captured_fox` to the visual contract.

## 5. Reconstruction input and result

The round input contains:

```text
ruleset and deck manifest
game and round identifiers
active players, dealer, and first trick leader
ordered table observations
optional correction constraints
reconstruction configuration and evidence-feature weights
```

The engine treats card plays, persistent table state, observation-to-card association, trick
clearing, and missing plays as latent values.

The result contains:

```text
status: resolved | ambiguous | impossible | incomplete
ranked reconstruction hypotheses
selected card plays and tricks for each retained hypothesis
focused decisions that differ between hypotheses
source observation and evidence references
applied correction constraints
rejected alternatives and rule conflicts
search limits and calibration labels
```

One missing card play can become unique when every other card and its missing slot are known. Two
known missing cards in two known slots allow at most two assignments. More hypotheses can exist when
the missing slots or other observations are also uncertain. The engine must merge hypotheses that
produce the same gameplay result.

## 6. Human correction contract

Human review is part of the target design. Do not treat it as a production-only fallback.

The review UI should first ask about the smallest unresolved decision, for example:

```text
Trick 1, Niklas's card play:
HEARTS_10 or HEARTS_KING?
```

It can also offer a complete round editor. Supported corrections include:

- choose a card identity;
- assign or change the active player;
- insert or delete a card play;
- change card-play order;
- mark an observation as irrelevant;
- associate or separate two observed cards;
- set a trick boundary;
- replace the complete card-play sequence.

Store each correction as an immutable constraint with reviewer provenance. Re-run reconstruction
after a correction. Do not overwrite the table observations or the earlier machine result. Show a
clear conflict if a correction violates the selected ruleset or deck manifest.

## 7. Implementation order

0048 and 0049 provide the completed data, execution, recording review, and comparison foundations.
Follow the [epic board next steps](plans/README.md#next-steps) for current work. The existing
editors, local models, filesystem stores, and reconstruction engine remain the starting point for
the active follow-up epics.

After those foundations, use reviewed real coverage to select the bounded identity proof in 0043
or detector/capability measurements in 0050. Productive model operations remain in 0044 after a
passing candidate. Search development, full reconstruction correction, and production scope remain
in 0023, 0026, and 0024. None is required to reconnect the existing local feasibility pipeline.

## 8. Rules for independent improvements

Each new evidence family must obey these rules:

1. Declare a capability in the observation result.
2. Keep the field optional for consumers that support an earlier capability set.
3. Treat a missing field as unavailable, not negative evidence.
4. Add a synthetic scenario in which the feature helps and one in which it can mislead.
5. Run an ablation that compares reconstruction with and without the feature.
6. Preserve source video, completed processor results, and completed reference revisions. Derived
   views can be regenerated from their pinned policies.
7. Version feature semantics, preprocessing, and model bundles.
8. Do not multiply correlated visual scores as if they were independent calibrated probabilities.
9. Keep deterministic rule rejection separate from visual ranking.
10. Allow the result to remain ambiguous.

These rules let identity recognition, presence estimation, transition comparison, spatial evidence,
and tracking improve independently.

## 9. Plan ownership

- Closed epic [0048](plans/5-closed/0048-Pipeline_Data_and_Execution.md) delivered shared data and
  execution contracts, video-derived inputs, maintained reference storage, analysis integration,
  and dataset adapters.
- Closed epic [0049](plans/5-closed/0049-Recording_Pipeline_Review_and_Comparison.md) delivered the
  recording UI, reference editing, explicit run input selection, comparison, and obsolete
  review-route removal.
- [0043](plans/4-blocked/0043-Local_Visual_Card_Identity_Quality_Proof.md) owns bounded identity quality.
- [0044](plans/4-blocked/0044-Productive_Local_Identity_Model_Operations.md) owns later productive
  campaigns, promotion, and rollback.
- [0050](plans/4-blocked/0050-Detector_Quality_and_Analyzer_Capabilities.md) owns detector baseline
  measurements and justified optional analyzer capabilities.
- [0023](plans/0-to-specify/0023-Game_Reconstruction_Development.md),
  [0026](plans/0-to-specify/0026-Reconstruction_Review_Workflow.md), and
  [0024](plans/0-to-specify/0024-System_Production_Readiness.md) retain later specification work.

Closed epics record delivered or superseded work. They do not override the current scope above.
