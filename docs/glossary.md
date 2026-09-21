# DokoDetector glossary

This glossary defines the canonical domain language for DokoDetector. These meanings are
immutable. Use them in plans, documentation, code, schemas, APIs, fixtures, and user interfaces.

## Gameplay terms

### Player

A person who takes part in a game.

### Game

A set of rounds. A game typically has `player count × 4` rounds. Calculate the final score over all
rounds in the game.

A game is typically played during one evening. The players can continue the game on another day.

### Round

A set of 10 tricks. Each trick has four played cards. One player is the dealer for the round.

### Trick

One of the 10 units in a round. A trick contains one card play from each of the four active
players.

### Dealer

The player who deals the cards for a round. The dealer can sit out that round.

### Active player

A player who takes part in a specific round. Each round has four active players.

### Card play

The act of an active player playing one card into the current trick.

### Player hand

The cards held by one active player during a round and not yet played. Use **human hand** for the
body part when the distinction matters in vision work.

### Turn

One active player's required opportunity to make a card play in a trick.

### Trick leader

The active player who makes the first card play in a trick.

### Trick winner

The active player who wins a trick under the round rules.

### Round score

The score contribution produced by one round.

### Game score

The score calculated over all round scores in a game. The final game score is not the score of one
round.

## Activity and recording terms

### Session

One occasion during which related game or staged activity occurs in a shared physical setting.

A session can contain all or parts of multiple games. A game can span multiple sessions. A session
can also contain staged activity without a game. Starting or stopping a recording does not start or
end a session.

For example, one session can contain the final rounds of one game and the first 10 rounds of the
next game. A set of staged kitchen recordings can form another session without a game.

### Recording

Media captured during one uninterrupted start-to-stop capture. A recording belongs to one session.
It can contain parts of multiple games or staged activity.

### Staged activity

Deliberately arranged actions that are not part of a game. Staged activity can imitate card plays,
tricks, or other situations. It does not contain canonical games or rounds.

### Table setup

A repeatable physical and visual arrangement, such as the table, deck, background, and camera
placement. A session can use more than one table setup.

### Operator

A person who controls recording, review, or data tooling. An operator can also be a player, but the
roles are not interchangeable.

## Evidence and data terms

### Source asset

Immutable imported bytes, such as an original video or accepted evidence package. A source asset
records or represents source material. It is not the real-world recording or activity itself.

### Pipeline data set

A bounded collection of one concrete content type for a recording or synthetic fixture. Examples
are events, visible-card detections, visual card identities, and table observations. Human and
processor versions use the same content contract. Origin and review state are separate metadata.
A pipeline data set is not a training or evaluation dataset.

### Data revision

One immutable saved version of a pipeline data set. It records content, source references, coverage,
and lineage. Completed processor results and completed human reviews produce data revisions.
An autosaved review draft is mutable work toward a data revision.

### Processor

A component that transforms selected inputs into outputs. It can use a model, rules, or another
algorithm. Input and output describe a data revision's role in an execution, not its storage type.

### Processor run

One execution of a processor against exact source and input revisions with a recorded implementation,
model, configuration, and extraction policies. A completed run references its output data revisions.
A run can consume unreviewed inputs. Review and dataset eligibility are separate decisions.

### Maintained reference

The single human-maintained reference for one recording and review stage. It has at most one current
draft and selects one completed data revision when available. Earlier completed revisions remain
available to runs and datasets. A model rerun does not replace the maintained reference.

### Review coverage

The explicit intervals, frames, or visible cards that a person inspected for one data revision.
Review completion applies only to that coverage. Missing coverage is not a reviewed negative.
Ground truth means the reviewed reference for the declared question and coverage; upstream review
does not make downstream predictions ground truth.

### Derived view

A reproducible view calculated from source material, selected data revisions, and defined policies.
Frames, identity crops, video snippets, and derived boxes can be derived views. Materialization and
caching do not give them independent source or review authority.

### Dataset

A frozen selection of samples for training or evaluation. It records source groups, selected data
revisions, target eligibility, and sampling and derivation policies. Processor results can be inputs
or comparison predictions without becoming reviewed training or evaluation targets.

### Pending upload

A received source upload that is not yet a complete repository intake bundle. A pending upload stays
under `data/incoming` with its receipt, source digest, byte length, and measured media facts. It is
not visible to a data task, review, dataset, split, or model run. The HTTP contract may use a more
specific name, such as `pending video`.

### Event

A time-bounded occurrence that is relevant to detection or gameplay. Use a qualified event term
when its review state matters.

### Card-state change

A persistent card-related table-state change that can justify another table observation. A
card-state change can be a card placement, turn, meaningful move, removal, return, trick clear, or
multi-card change. It does not assert a card play, a face side, or another gameplay meaning.

Use `card_state_changed` as the event type for a generic CardEventNet proposal.

### Card-state change interval

A reviewed card-state change with different start and end times. It starts when a persistent
table-state change begins and ends when the new table state is stable. A trick clear can be a
card-state change interval. Its intermediate frames are part of the same change, not separate
card-state changes or ordinary negative evidence.

Use the end time as the CardEventNet event anchor unless a declared data task specifies another
anchor. A point card-state change has equal start and end times.

### Event proposal

A possible event reported by a person or model before review. An event proposal is not ground
truth.

### Reviewed event

An event that a person has confirmed through the review process.

### Evidence package

A bounded collection of recorded evidence around an event proposal. An evidence package can exist
without a reviewed event.

### Physical deck

One concrete set of physical cards used for a round or staged activity.

### Physical card

One concrete card in a physical deck. Two physical cards can have the same visual card identity.

### Deck design

The shared visible design of cards. Several physical decks can have the same deck design.

### Visual card identity

The visible suit-and-rank identity of a card, such as `HEARTS_QUEEN`. Two physical cards can have
the same visual card identity.

### Visual classification

The positive visual class reported for one visible card crop. A visual classification is either a
visual card identity or `FACE_DOWN`. `FACE_DOWN` means that the card back is positively visible. It
is not a visual card identity, a deck entry, or a legal card assignment.

`UNKNOWN` is an abstention because the crop does not support a positive visual class.

### Visible region

The pixels of one visible card that can be reviewed in a source frame. A visible region does not
include hidden card pixels, an occluding card, a human hand, or the background. One visible region
can use more than one polygon when an occluder splits the visible pixels.

### Card cluster

A spatial group of one or more visible cards that must be processed together by a fine visible-card
detector. A card cluster is an image-processing unit. It does not assert a pile, trick, card play,
or another gameplay relationship.

### Cluster crop

A derived view that contains one card cluster with declared surrounding context. A cluster crop
keeps its source-frame transform so that visible-card results can map back to the source frame. It
is not a source asset, maintained reference, or independent source group.

### Table-plane calibration

A recording-scoped mapping between one stable source image plane and a rectified table coordinate
system. It also records the common card dimensions robustly measured from complete-card evidence
across the recording. A table-plane calibration is not a camera model and is invalid after camera
or table movement.

### Calibration anchor

One operator-confirmed complete-card geometry observation that can constrain a table-plane
calibration. A calibration anchor belongs to one exact source frame and records its review state and
fit lineage. It does not make the complete frame or its card scene reviewed.

### Proposed card scene

A processor-generated initial set of card poses and card stacking order for one exact source frame
under one table-plane calibration. A proposed card scene is an editor prefill. It is not a reviewed
card scene or training authority until an operator accepts or corrects it through the maintained
reference.

### Card pose

The full rectangular placement of one card on a calibrated table plane. It contains a table-plane
center and rotation and uses the card dimensions from the table-plane calibration. A card pose is
geometric evidence. It does not assert a visual card identity, card play, pile, or trick.

### Card stacking order

The frame-local front-to-back order used to calculate card-card occlusion between card poses. It
does not assert a gameplay pile or the temporal order of card plays. The implementation can call
this value `z_order`.

### Reviewed card scene

The human-reviewed card poses and card stacking order for one exact source frame under one selected
table-plane calibration. It is the geometry authority for visible regions derived from card-card
occlusion. It is not a table observation or gameplay state.

### Card cutout

A training-only image and exact alpha mask made from one reviewed, complete visible region. A card
cutout is source material for offline compositing. It does not add hidden card pixels or change the
maintained reference.

### Synthetic training scene

One offline training image made by compositing reviewed card cutouts onto a reviewed background with
recorded geometry and z-order. Its exact visible-region masks are renderer outputs. A synthetic
training scene is not a reviewed source frame or an independent source group.

### Visible-card ignore region

A reviewed source-frame region that contains visible card-like evidence but does not support
reliable card-instance annotation. It is not a card, card side, visual classification, or model
class. A visible-card dataset must mask its pixels from loss or exclude the complete frame. It must
not use the region as a positive target or as ordinary background.

### Card side

The observed presentation of a visible card. It is `face_up` when the card face is visible,
`face_down` when the card back is visible, and `unknown` when the side is not classified.

### Derived box

The tight axis-aligned detector box calculated from a visible region. A derived box does not
describe the inferred full-card extent.

### Identity usability

The reviewed decision that a visible-card crop contains enough evidence for visual card identity.
An identity-unusable crop can still be a valid visible-card detection target.

### Visual identity outcome

The result of applying one visual identity processor to one visible-card proposal. A classified
outcome contains identity candidates. An unusable outcome means that the supplied visual evidence
cannot support an identity. A face-down outcome means that the card back is positively classified
and contains no identity candidates. A failed outcome means that processing did not complete. A
face-down, unusable, or failed visual identity outcome does not remove the visible-card proposal.

### Crop policy

A frozen rule that converts a visible region and its derived box into an identity crop, or rejects
the crop. A crop policy is an evaluation condition. It does not change the reviewed visible region.

### Visible-region exclusion

A derived crop operation that neutralizes pixels assigned to other visible-card proposals. It uses
only eligible visible regions in the same source frame. It does not change stored geometry, infer
hidden card pixels, determine stacking order, or assign a physical-card identity.

### Table observation

An uncertain visual report of cards that were visible during a bounded time interval. A table
observation is evidence. It is not the true table state and does not assert that a card was played.

### Analyzer capability

One declared evidence family that a TableEvidenceAnalyzer provides in a table observation. A
capability can be required or optional. An absent optional capability means that the evidence is
unavailable, not that its score is zero.

### Table evidence analyzer

The bounded component that analyzes supplied visual evidence and produces a table observation.
For recording-based development, derive that evidence from the original recording video. Device
evidence packages remain showcase artifacts and are not pipeline inputs.
The `TableEvidenceAnalyzer` can combine models and classical algorithms. It does not capture
evidence, apply game rules, or imply a deployment location.

### Observed card

One proposed card instance within one table observation. An observed card can have several visual
card identity candidates. It is not a physical card and can be a false detection.

### Card tracklet

A short-term visual association of observed cards within one video snippet or overlapping snippets.
A card tracklet is uncertain evidence. It is not a persistent physical-card identity.

### Active table area

The visually estimated table region where cards for the current trick normally appear. It is visual
evidence and can move between table setups. It does not determine whether a card belongs to a trick.

### Video snippet

A bounded media segment derived from a recording video around an event proposal or reviewed event.
A video snippet is not a recording. An evidence package can contain a video snippet, but packaging
is not required to derive or use one.

### Reconstruction hypothesis

One possible sequence of card plays and trick transitions that is compatible with selected table
observations, correction constraints, and round rules. Several reconstruction hypotheses can remain
valid.

### Correction constraint

An immutable human assertion that limits game reconstruction, such as a selected card identity or an
inserted card play. A correction constraint does not modify source evidence or table observations.

### Reviewed reconstruction

A reconstruction result that a person confirmed through the review process. It records the source
result and all applied correction constraints.

### Lifecycle receipt

An immutable record of one data operation and the source and versioned artifacts that it used or
created. A lifecycle receipt does not change source bytes or make an annotation ground truth.

### Data task

One declared purpose for annotation, dataset assembly, training, or evaluation. CardEventNet event
detection and TableEvidenceAnalyzer table-observation analysis are different data tasks even when
they use the same source asset.

### Task enrollment

A versioned operator decision that selects, defers, or excludes a source asset for one data task.
Task enrollment does not change the source asset, grant usage permission, complete review, or make
the source eligible for a dataset.

### Proposal generator

A versioned model and configuration that produces event proposals or other candidates used to
select source evidence for review. A proposal generator does not produce ground truth. Its output
records full lineage to the source asset and generator version.

### Visible-card review batch

One versioned unit of visible-card review work. It freezes the selected source frames and proposal
generator results, owns one resumable review queue, and can publish one completed review. A
visible-card review batch does not make an unreviewed proposal ground truth.

### Visual card identity review batch

One versioned unit of visual card identity review work. It freezes identity crops from completed
visible-card reviews and the selected proposal generator results. It owns one resumable review
queue and can publish one completed review. A visual card identity review batch does not change
reviewed visible geometry or make an unreviewed identity proposal ground truth.

### System holdout

A sealed set of source-lineage groups that no component can use for training or model selection.
Use the system holdout only for locked end-to-end evaluation.

### Champion model bundle

The versioned model bundle currently selected as the comparison and deployment candidate for one
component. Each component has its own champion model bundle.

### Model promotion

The explicit operation that replaces one component's champion model bundle after a locked candidate
passes its declared gates. Model promotion records the decision and artifacts in a lifecycle
receipt. It does not deploy the bundle to a production environment by itself.

## Relationships

- A game contains rounds. A round belongs to one game.
- A game and a session have a many-to-many relationship.
- A recording belongs to one session. Recording boundaries do not define session boundaries.
- One recording can contain parts of multiple games or staged activity.
- Staged activity belongs to a session but not to a game or round.
- A source asset can contain data from a recording. It is not interchangeable with that recording.
- One source asset can have separate task enrollments, annotations, review states, eligibility, and
  dataset membership for several data tasks.
- A proposal generator can select evidence for a data task without enrolling the source asset in
  the proposal generator's own training dataset.

## Terminology rules

- Use these terms only with the meanings above. This rule also applies to plurals, capitalization,
  identifiers, and compound terms.
- Do not use **game** for one round.
- Do not use **round** for one trick or for a complete game.
- Do not use **session** for one recording or for a dataset partition.
- Do not use **recording** for a session, source asset, or evidence package.
- Do not introduce a synonym for a canonical term.
- Qualify **event** as an **event proposal** or **reviewed event** when the review state matters.
- Add each new domain term to this glossary before its first use when it could overlap with a
  canonical term. Give the new term a distinct meaning.
- If existing text conflicts with this glossary, the glossary takes precedence. Update the
  conflicting text when that text is next changed.
