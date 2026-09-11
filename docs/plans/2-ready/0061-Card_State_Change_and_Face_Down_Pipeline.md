# Card-state change and face-down pipeline

## Plan status

- **Summary:** Make CardEventNet report generic card-state changes, process every event through the
  existing visible-card stage, and preserve face-down evidence through visual identity and table
  observation assembly.
- **Status:** Ready
- **Depends on:** 0048 and 0049 complete
- **Readiness:** The current processor boundaries and the required breaking contract changes are
  known. No new processor, model head, training campaign, or reconstruction behavior is required.
- **Builds on:** The recording pipeline from 0048 and 0049 and the identity-outcome preservation
  completed in 0051 M1
- **Outcome:** Every CardEventNet proposal means `card_state_changed`. Every event produces a
  visible-card outcome. Face-up, face-down, and unknown card sides remain explicit through the last
  pre-reconstruction processor. Face-down cards produce an explicit unusable identity outcome
  instead of a fabricated identity or a missing card.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — align the binary CardEventNet target and generated event contract.
- **M1:** Not started — process every event with the existing visible-card processor.
- **M2:** Not started — preserve card side and handle face-down visual identity outcomes.
- **M3:** Not started — preserve card side through observation assembly and publish the boundary.

## 1. Problem

CardEventNet is a binary temporal trigger. It cannot determine whether a visible transition is a
card play, a card turn, a card removal, or a trick clear. The training path already collapses
confirmed annotation types into one positive class, but generated pipeline results call every
proposal `card_played`. The visible-card processor then selects only events with that name. These
two behaviors give a gameplay meaning to an output that contains no such evidence.

The visible-card provider can report `face_up`, `face_down`, or `unknown`, but the recording-pipeline
visible-card candidate does not preserve that value. The visual identity processor therefore
cannot make a deliberate face-down decision, and observation assembly cannot publish the side for
later reconstruction work.

## 2. Decisions

### 2.1 CardEventNet is a binary resampling trigger

Train and evaluate CardEventNet to answer one question:

> Did a persistent card-related table state change enough to justify another table observation?

Use the glossary definition of
[card-state change](../../glossary.md#card-state-change) throughout the active contracts.

Treat confirmed card placements, turns, meaningful moves, removals, returns, trick clears,
multi-card changes, and other meaningful card-state changes as positive examples. Treat transient
human-hand motion, temporary occlusion, lighting changes, camera motion, and insignificant card
jitter as negative examples.

Every generated proposal uses `event_type=card_state_changed`. CardEventNet does not emit a face
side or a gameplay action. Detailed annotation types can remain in offline annotations for data
audit and evaluation breakdowns. They are all collapsed into the same binary training target and
are not required in an automatic processor run.

This epic changes the declared target and processor output. It does not add a multiclass event
head, collect data, retrain or promote a model, or claim that the current checkpoint meets a new
quality gate.

### 2.2 Every event receives a table snapshot

The visible-card processor consumes every event in its selected event revision. It does not select
events by semantic type. A trick clear can correctly produce an empty visible-card outcome. A card
turn can produce the same card region with a different side. Both are useful processor results.

Event review can still correct event time, remove a false event, or retain a detailed offline
annotation type. Downstream execution must not require human classification of the event.

### 2.3 Visible-card detection includes both sides

Keep the existing visible-card processor. Do not add a side estimator or temporal association.
Every retained candidate has one required side:

```text
face_up | face_down | unknown
```

The Gemini provider preserves its current side result. A provider that does not classify side,
including the current local detector, emits `unknown`. Detection never removes a candidate because
it is face down.

### 2.4 Visual identity abstains on known face-down cards

For `face_up` and `unknown`, keep the existing crop and classifier path. For `face_down`, do not call
the visual identity classifier. Publish a successful `unusable` visual identity outcome with an
explicit `face_down` reason. This is not a failed processor item and does not remove the visible-card
candidate.

The rule uses only the side already present on the selected visible-card revision. It adds no side
inference and no confidence threshold.

### 2.5 Observation assembly preserves evidence without reconstruction policy

Add side to each assembled observed card. Preserve face-down cards with
`identity_status=unusable` and no identity candidates. Keep face-up and unknown outcomes unchanged.

Update the mirrored game-engine input contract only as required to parse and retain the new field.
Do not change card-play inference, trick inference, hypothesis ranking, or any other reconstruction
behavior. A later reconstruction epic will decide how to use face-down observations and generic
state-change snapshots.

## 3. Scope

In scope:

- CardEventNet training-target semantics, evaluation labels, model contract, and generated event
  type;
- event review and generated client contracts needed to represent `card_state_changed`;
- visible-card execution for every event in the selected revision;
- side in visible-card candidates, persistence, review data, APIs, and generated clients;
- explicit face-down visual identity abstention;
- side in assembled table observations and the mirrored reconstruction input parser; and
- focused fixtures, processor tests, contract tests, and documentation.

Out of scope:

- a new event model architecture or multiclass event prediction;
- a new side estimator, side confidence, or provider;
- temporal association, state differencing, or card tracklets;
- detector or identity quality experiments;
- data collection, model retraining, promotion, or runtime-default model changes;
- game rules or reconstruction behavior; and
- compatibility layers for the previous undeployed contracts.

## 4. Delivery milestones

### M0 — Align the CardEventNet target and event contract

- Define `card_state_changed` as the only generated CardEventNet event type.
- Change backend and iOS adapters that currently stamp generated proposals as `card_played`.
- Update event contracts, the event editor, API clients, fixtures, and presentation text to accept
  and show the generic type.
- Lock the binary training rule with tests that collapse every confirmed meaningful annotation type
  into a positive target while excluded confidence states remain excluded.
- Update active CardEventNet documentation and evaluation wording. Do not edit closed epics.

Acceptance:

- a generated CardEventNet run contains only `card_state_changed` events;
- no generated proposal claims face side or gameplay meaning;
- training tests include a play, turn or move, removal, and trick clear as the same positive class;
- proposal review and comparison can load the new event type; and
- CardEventNet, backend, iOS, and web contract tests pass.

### M1 — Propagate every event to visible-card detection

- Remove the `card_played` filter from recording-pipeline visible-card execution.
- Produce exactly one visible-card item outcome for every event in the frozen input revision.
- Preserve retry, ordering, exact-frame resolution, and failure behavior for the expanded input.
- Add mixed-event fixtures with a detected card, an empty trick-clear frame, and a failed frame.
- Update run counts and review coverage tests so non-play events cannot disappear silently.

Acceptance:

- input event count equals visible-card item count for completed or explicitly failed items;
- a successful empty result remains different from a failed result;
- retry resumes retained outcomes for all event types; and
- visible-card service, API, workspace, and comparison tests pass.

### M2 — Preserve side and abstain on face-down identity

- Add required `side` to the active visible-card candidate contract.
- Preserve provider side through backend conversion, persistence, maintained-reference edits, API
  serialization, generated clients, and visible-card review.
- Emit `unknown` from providers that do not classify side.
- Skip classifier execution for a `face_down` candidate and publish `unusable` with reason
  `face_down`.
- Keep the existing classifier path for `face_up` and `unknown` candidates.
- Add mixed-side fixtures and verify classifier call counts.

Acceptance:

- a face-down detector result remains a visible-card candidate after save, reload, and review;
- a face-down candidate makes zero identity-classifier calls and produces a successful unusable
  outcome;
- face-up and unknown candidates keep their current classification behavior;
- one face-down candidate does not fail or suppress other items; and
- visible-card, visual-identity, backend, web, and generated-client tests pass.

### M3 — Preserve side through observation assembly

- Add required side to the active `ObservedCard` contract and its mirrored game-engine input model.
- Copy side from each visible-card candidate during observation assembly.
- Preserve face-down cards as anonymous observed cards with an unusable identity.
- Update diagnostics and fixtures for mixed face-up, face-down, and unknown observations.
- Update the target architecture and active component documentation with the completed boundary.
- Record the explicit reconstruction handoff without changing reconstruction decisions.

Acceptance:

- every assembled card has the same side as its selected visible-card input;
- face-down cards survive assembly without identity candidates;
- serialization and parsing preserve side exactly;
- existing reconstruction scenarios retain their current results after fixture updates; and
- analyzer, backend, game-engine contract, and integration tests pass.

## 5. Verification

For each milestone, run the smallest affected test suites first. Before closing the epic, run:

- CardEventNet annotation, dataset, evaluation, and inference tests;
- backend event, visible-card, visual-identity, observation, and pipeline API tests;
- TableEvidenceAnalyzer pipeline-data and observation-assembly tests;
- web event, visible-card, visual-identity, and recording-workspace tests;
- iOS CardEventNet contract and event-decoder tests; and
- game-engine contract and reconstruction regression tests.

Regenerate checked-in API clients after the backend contract changes. Run applicable formatting,
lint, and type checks for each changed component. Verify one fixture pipeline from a generic event
through an assembled face-down observed card.

## 6. Relationship to other epics

- 0048 and 0049 provide the processor, revision, review, and workspace boundaries changed here.
- 0051 M1 provides the rule that unusable identity evidence must not remove a visible-card
  proposal. This epic gives face-down evidence one explicit use of that rule.
- 0051 must freeze and report the post-0061 side and identity semantics before it executes another
  classifier comparison. This epic does not change its crop experiment.
- 0050 remains responsible for later detector quality and optional analyzer-capability measurement.
  This epic does not measure or replace a detector.
- 0023 remains the owner of later reconstruction work. This epic supplies stable generic-event and
  face-side evidence without deciding how reconstruction uses it.
