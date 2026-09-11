# Canonical card-state data and face-down identity

## Plan status

- **Summary:** Remove the retired event taxonomy from active data and UI, and make `FACE_DOWN` a
  first-class visual classification without adding it to the Doppelkopf card identities.
- **Status:** Ready
- **Depends on:** 0061 complete
- **Readiness:** The remaining legacy data, UI controls, classifier vocabulary, and review paths are
  identified. The change uses the existing event and visual-identity processors.
- **Builds on:** The generic event propagation and card-side boundary completed in 0061
- **Outcome:** Current CardEventNet annotations and selected pipeline references contain only
  `card_state_changed`. Event review no longer asks for a semantic event type. Visual identity can
  report `FACE_DOWN` separately from a suit-and-rank identity, generic unusable evidence, and
  processor failure. The last pre-reconstruction output preserves the result without changing
  reconstruction decisions.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — canonicalize active event data and record the durable revision replacement.
- **M1:** Not started — remove the retired event taxonomy from active contracts and UI.
- **M2:** Not started — add the `FACE_DOWN` visual classification and processor outcome.
- **M3:** Not started — make visual-identity review and training data use the face-down class.
- **M4:** Not started — publish the face-down result through observation assembly and freeze the
  reconstruction handoff.

## 1. Problem

Epic 0061 changed generated CardEventNet proposals to `card_state_changed`, but it intentionally
kept detailed annotation types. The active repository therefore has two event meanings. The
CardEventNet annotation corpus still contains 1,680 `card_played`, 397 `trick_cleared`, 61
`card_moved`, and one `anomalous_state_change` event. Durable operations data contains another
1,683 legacy event values across 33 JSON files. The web editor still exposes the complete retired
type selector.

Epic 0061 also preserved card side and skipped identity classification for known face-down cards.
However, the visual classifier still maps face-down, blur, occlusion, and insufficient evidence to
one `UNKNOWN` result. The visual-identity processor then stores a known face-down card as generic
`unusable`. Review and training data have no positive face-down visual class.

These gaps keep the previous semantics alive in data, review, and model targets even though the
automatic processor boundary changed.

## 2. Decisions

### 2.1 One active event type

`card_state_changed` is the only active CardEventNet annotation and pipeline event type. It means
that a persistent card-related table state changed enough to justify another table observation.
It does not classify a play, move, removal, or trick clear.

Preserve event time, confidence, notes, identifiers, scores, coverage, and lineage during data
replacement. Do not retain the former event type in a new active field or note. The downstream
processors receive the resulting table snapshots and must not depend on the retired label.

### 2.2 Replace current data without rewriting history

Mechanically rewrite the tracked CardEventNet annotation corpus because it is the active training
source. Update active fixtures and manifests that embed those annotations.

Completed pipeline data revisions and frozen datasets remain immutable. For every maintained
reference or current selection that points to a legacy event revision, publish a canonical
replacement revision with unchanged event evidence and `event_type=card_state_changed`. Record an
old-to-new revision receipt and move the current selection to the replacement. Keep the old revision
available as historical data. Future dataset freezes use only canonical revisions.

Do not add a compatibility write path. New processor results, reference drafts, completed
references, fixtures, and datasets must reject retired event types.

### 2.3 Event review is temporal review

The event UI reviews whether a card-state change happened and when it happened. It does not ask the
operator to infer a semantic action. Remove event-type selection, type shortcuts, type guidance,
and type-specific visual treatments. Keep accept, reject, add, remove, timing correction, source
navigation, review coverage, and comparison.

### 2.4 `FACE_DOWN` is a visual class, not a card identity

The visual classifier vocabulary contains:

```text
24 suit-and-rank visual card identities
FACE_DOWN
UNKNOWN
```

`FACE_DOWN` means that the visible card back is positively recognizable. `UNKNOWN` means that the
crop cannot support either a suit-and-rank identity or the face-down class. Keep `FACE_DOWN` and
`UNKNOWN` outside `CARD_IDENTITIES`, deck manifests, legal card sets, and reconstruction card
assignments.

The visual-identity processor outcome states become:

```text
classified  -> one or more suit-and-rank candidates
face_down   -> the card back is positively classified; no identity candidates
unusable    -> no supported visual class can be established
failed      -> the processor did not complete
```

A visible-card input with `side=face_down` produces `face_down` without a classifier request. For a
`face_up` or `unknown` input, the existing classifier can return `FACE_DOWN`. Record this as a
`face_down` outcome and retain the upstream side in the visible-card revision for audit.

### 2.5 Reconstruction remains unchanged

Observation assembly maps a `face_down` visual-identity outcome to an observed card with
`side=face_down`, no identity candidates, and neutral identity evidence. The table observation can
record the face-down visual outcome in diagnostics. The game-engine input parser must continue to
accept the observation, but this epic does not change card-play inference, trick inference, search,
or hypothesis ranking.

## 3. Scope

In scope:

- the active CardEventNet annotation schema and tracked annotation corpus;
- replacement revisions for current durable event references and selections;
- event review, comparison, Timeline Rail, APIs, clients, and active fixtures;
- the Gemini visual-classification response and normalized classifier result;
- visual-identity outcome persistence, retry, APIs, generated clients, and review;
- face-down visual-identity training targets and class maps;
- observation assembly of the face-down result; and
- focused data-audit, contract, UI, processor, and integration tests.

Out of scope:

- semantic event classification;
- a new processor, side estimator, temporal association, state differencing, or card tracking;
- detector changes;
- collection of new recordings or annotations;
- training, evaluating, promoting, or selecting a new model checkpoint;
- adding `FACE_DOWN` to a deck or legal card identity; and
- reconstruction behavior.

## 4. Delivery milestones

### M0 — Canonicalize active event data

- Freeze an inventory of tracked annotations, active event fixtures, durable event revisions,
  maintained references, current selections, and frozen datasets that contain retired event types.
- Rewrite every tracked CardEventNet annotation event to `card_state_changed` without changing its
  other fields or ordering.
- Publish canonical replacement revisions for current maintained references and selections. Use
  the existing revision and reference stores.
- Write a durable receipt with each old revision ID, replacement revision ID, content digest, and
  changed selection.
- Leave completed historical revisions and frozen datasets unchanged and list them in the receipt.
- Validate event counts, timestamps, confidence values, notes, coverage, and source lineage before
  and after replacement.

Acceptance:

- every tracked training annotation uses `card_state_changed`;
- every current maintained reference and selected event revision uses `card_state_changed`;
- event count, order, time, confidence, notes, coverage, and source lineage are unchanged;
- old immutable revisions remain readable and are not selected as current data; and
- a repeated migration is a no-op with the same audit result.

### M1 — Remove the retired event taxonomy from contracts and UI

- Make `card_state_changed` the only value accepted by active annotation, processor-output,
  reference-write, and dataset-freeze contracts.
- Remove retired event-type shortcuts, labels, guidance, selectors, and editor state.
- Make every newly added event a `card_state_changed` event without exposing the fixed field.
- Use one card-state-change label and visual treatment in event review, history, comparison, run
  summaries, and the Timeline Rail.
- Update active documentation and fixtures. Do not edit closed epics.

Acceptance:

- the UI contains no event-type selector or old event-type guidance;
- the active write paths reject `card_played`, `trick_cleared`, `card_moved`, and the other retired
  values;
- add, edit, complete, compare, and reload preserve the singleton event type; and
- CardEventNet, backend, web, operations, and API-client checks pass.

### M2 — Add the face-down visual classification

- Add `FACE_DOWN` beside `UNKNOWN` in the visual classifier response contract without adding either
  value to `CARD_IDENTITIES`.
- Make the normalized classifier result distinguish an identity, `FACE_DOWN`, and `UNKNOWN`.
- Add `face_down` to the visual-identity processor outcome contract and its persistence, retry,
  API, and generated-client representations.
- Produce `face_down` directly for a known face-down visible-card input without a classifier call.
- Map a classifier `FACE_DOWN` response to the same outcome for face-up or unknown inputs.
- Keep generic unusable evidence and processor failure distinct.

Acceptance:

- a face-down response cannot enter deck manifests or identity candidate lists;
- known face-down input produces a successful `face_down` outcome with zero classifier calls;
- classifier `FACE_DOWN`, `UNKNOWN`, malformed output, and provider failure produce four distinct
  results;
- mixed identity, face-down, unusable, and failed items survive save, restart, and retry; and
- analyzer, backend, contract, and generated-client tests pass.

### M3 — Make review and training data face-down aware

- Show `Face down` as a first-class visual-identity result and review action.
- Keep `Identity unusable` for blur, occlusion, and other insufficient visual evidence.
- Extend review coverage decisions so face-down is complete, not pending or unusable.
- Publish replacement current visual-identity references when an unusable item has a selected
  visible-card input with `side=face_down`. Preserve historical completed revisions.
- Extend visual-classification dataset targets and class maps with `FACE_DOWN` as the twenty-fifth
  positive class.
- Mark existing 24-class local classifier bundles as obsolete for the new target contract. Do not
  train or promote a replacement in this epic.

Acceptance:

- the UI distinguishes Face down, Identity unusable, and Source problem;
- face-down review items complete coverage without a suit-and-rank identity;
- current reviewed face-down items freeze as `FACE_DOWN` training targets;
- identity datasets never encode `FACE_DOWN` as a legal Doppelkopf card; and
- review, dataset, local-class-map, backend, and web tests pass.

### M4 — Publish the pre-reconstruction boundary

- Make observation assembly consume `face_down` outcomes explicitly.
- Emit `side=face_down`, no identity candidates, and neutral identity evidence for those cards.
- Preserve the exact visual-identity outcome in assembly diagnostics and lineage.
- Update the target architecture, glossary, and active component documentation.
- Add one end-to-end fixture from `card_state_changed` through a face-down visual classification to
  a table observation.
- Record the remaining reconstruction decisions as later work without changing the engine.

Acceptance:

- the fixture contains one generic event, one retained face-down card, and no fabricated identity;
- table-observation serialization preserves the face-down side and source lineage;
- the game-engine parser accepts the result and existing reconstruction results do not change;
- no retired event type appears in active processor or UI fixtures; and
- analyzer, backend, web, game-engine contract, and integration tests pass.

## 5. Verification

Run focused tests after each milestone. Before closure, run:

- CardEventNet annotation, dataset, evaluation, and data-validation tests;
- migration inventory, idempotence, revision, reference, selection, and receipt tests;
- backend event, visual-identity, observation, API, and recovery tests;
- TableEvidenceAnalyzer classifier, pipeline-data, review-freeze, dataset, and assembly tests;
- web event, Timeline Rail, visual-identity, comparison, and recording-workspace tests;
- generated-client checks; and
- game-engine contract and unchanged-result reconstruction tests.

Run applicable formatting, lint, type, schema-generation, and Markdown-link checks. After the data
replacement, repeat the repository validation and compare the final counts with the frozen M0
inventory.

## 6. Relationship to other epics

- 0061 remains the immutable record of generic event propagation and card-side preservation. This
  epic removes the legacy semantics that 0061 deliberately retained.
- Complete this epic before 0051 freezes another classifier comparison. The baseline must use the
  final face-down outcome and visual-classification target contract.
- 0043 must evaluate future local identity models with the 25-class visual-classification target.
  This epic does not train that model.
- 0050 remains responsible for detector quality and optional analyzer capabilities. It does not
  need to redefine face-down identity semantics.
- 0023 remains responsible for concentrated reconstruction work after the pre-reconstruction
  processors and contracts are stable.
