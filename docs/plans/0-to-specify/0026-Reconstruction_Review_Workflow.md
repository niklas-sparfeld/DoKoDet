# DokoDetector Reconstruction Review — Human Correction Workflow

## Plan status

- **Summary:** Review alternative reconstructions and apply complete, traceable human corrections
- **Status:** To Specify
- **Depends on:** Plan 0006 result and correction contracts, plan 0023 focused alternatives, and
  measured review cases
- **Uses evidence from:** Plans 0022 and 0025
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Purpose

Build a human review workflow for unresolved or incorrect round reconstruction. Support two modes:

1. focused questions about the smallest decision that differs between retained hypotheses;
2. a complete round editor for card identity, active player, order, missing plays, false plays, and
   trick boundaries.

Human input becomes immutable correction constraints. The reconstruction engine recomputes the
result. The UI does not overwrite raw evidence, table observations, or earlier machine results.

## 2. Likely work areas

### Review queue

Create queue items for:

- ambiguous reconstruction;
- impossible or incomplete reconstruction;
- low-ranked but retained alternatives;
- search truncation;
- explicit operator request;
- regression review after a model or ruleset change.

Keep queue state separate from reconstruction truth. Record assignment, reviewer, timestamps,
priority, source result, and completion reason.

### Focused questions

Present the smallest unresolved gameplay decision, for example:

```text
Trick 1, Niklas's card play:
HEARTS_10 or HEARTS_KING?
```

Show the relevant selected frames and video snippet. Show visual evidence and rule effects in simple
language. Do not require a reviewer to compare complete rounds when one local choice resolves them.

Allow:

- choose one alternative;
- mark all alternatives wrong;
- defer because evidence is insufficient;
- open the complete editor.

### Complete round editor

Allow a reviewer to:

- insert, delete, or replace a card play;
- assign or change the active player;
- reorder card plays;
- insert a missing card;
- mark an inferred play as false;
- set or change trick boundaries;
- associate or separate observed cards;
- mark an observation irrelevant;
- replace the complete card-play sequence.

Validate continuously against the selected deck and ruleset. Show conflicts without silently
discarding the edit. Require an explicit reviewed exception if the source activity does not follow
the configured rules.

### Evidence playback

Synchronize selected frames, the optional video snippet, table observations, card tracklets, and
reconstructed card plays. Keep geometry as a visual overlay for the reviewer when available. It does
not enter the game-engine contract.

### Correction provenance

Each applied correction records:

```text
constraint schema and identifier
source reconstruction result
target round and decision
reviewer identity
created time
reason or note
source evidence shown
replacement or selected value
```

Applying corrections creates a new reconstruction result. Reverting a correction creates another
recorded action. Do not mutate history.

### Model and ruleset changes

When the TableEvidenceAnalyzer, reconstruction weights, or rules change, preserve the reviewed
result and its constraints as immutable history. Do not add a compatibility layer by default.
Specify a migration or re-run path only when product requirements need it.

## 3. Entry measurements

Before writing concrete implementation milestones, collect:

- retained hypotheses per ambiguous round after plan 0023 merging;
- focused decisions per round;
- question types and evidence needed to answer them;
- frequency of insert, delete, reorder, identity, player, and trick-boundary corrections;
- unresolved cases where the evidence cannot answer the question;
- reconstruction time after one correction;
- expected reviewer roles, authentication, and audit needs;
- supported review device and local or remote deployment requirements;
- privacy and retention requirements for snippet playback.

Use a small scripted usability exercise before selecting the full editor design.

## 4. Future specification order

Specify implementation in this order:

1. file-based fixture viewer for one focused decision;
2. correction-constraint round trip and recomputation;
3. local review queue and completion receipt;
4. synchronized frame and snippet evidence playback;
5. complete round editor;
6. reviewed reconstruction lifecycle across model and ruleset changes;
7. multi-user, authentication, and remote deployment only if product requirements need them.

Keep every stage usable with checked-in fixtures and a local reconstruction process.

## 5. Completion direction

A later concrete plan must define acceptance limits for:

- time to resolve common focused questions;
- correction error rate and conflict handling;
- complete-editor task success;
- reconstruction latency after an edit;
- audit and provenance completeness;
- accessibility and supported devices;
- evidence privacy, retention, and deletion;
- explicit replacement or migration behavior when product requirements need it.

Completion requires both focused review and complete correction. A UI that only selects the top
machine alternative is insufficient.
