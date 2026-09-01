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

### Pending upload

A received source upload that is not yet a complete repository intake bundle. A pending upload stays
under `data/incoming` with its receipt, source digest, byte length, and measured media facts. It is
not visible to a data task, review, dataset, split, or model run. The HTTP contract may use a more
specific name, such as `pending video`.

### Event

A time-bounded occurrence that is relevant to detection or gameplay. Use a qualified event term
when its review state matters.

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

### Visible region

The pixels of one visible card that can be reviewed in a source frame. A visible region does not
include hidden card pixels, an occluding card, a human hand, or the background. One visible region
can use more than one polygon when an occluder splits the visible pixels.

### Derived box

The tight axis-aligned detector box calculated from a visible region. A derived box does not
describe the inferred full-card extent.

### Identity usability

The reviewed decision that a visible-card crop contains enough evidence for visual card identity.
An identity-unusable crop can still be a valid visible-card detection target.

### Crop policy

A frozen rule that converts a visible region and its derived box into an identity crop, or rejects
the crop. A crop policy is an evaluation condition. It does not change the reviewed visible region.

### Table observation

An uncertain visual report of cards that were visible during a bounded time interval. A table
observation is evidence. It is not the true table state and does not assert that a card was played.

### Analyzer capability

One declared evidence family that a TableEvidenceAnalyzer provides in a table observation. A
capability can be required or optional. An absent optional capability means that the evidence is
unavailable, not that its score is zero.

### Table evidence analyzer

The bounded component that analyzes a supplied evidence package and produces a table observation.
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

A bounded media segment around an event proposal in an evidence package. A video snippet is not a
recording and can be incomplete or absent.

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
