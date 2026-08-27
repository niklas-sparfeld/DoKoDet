# DokoDetector Table Observation Reconstruction — Contract and Core PoC

## Plan status

- **Summary:** Freeze the table-observation boundary and build the deterministic reconstruction core
- **Status:** In Progress
- **Depends on:** None
- **Reviewed:** 2026-08-27 against the target architecture, glossary, active plans, and current
  repository
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)
- **Next:** [Plan 0023](../0-to-specify/0023-Game_Reconstruction_Development.md) scales proven
  reconstruction to uncertain rounds and complete games

## 1. Outcome

Build a game-reconstruction contract and deterministic core that do not require the
TableEvidenceAnalyzer to produce authoritative card-play events.

At the end of this plan, a developer can run:

```text
legal synthetic round
  -> deterministic table-observation generator
  -> versioned stream of anonymous observed cards and optional visual evidence
  -> shared contract parser
  -> deterministic rules core and small exhaustive reconstruction oracle
  -> resolved, ambiguous, impossible, or incomplete hypotheses
  -> optional human correction constraints
  -> recomputed result
```

This plan must not depend on trained weights, real recognition quality, video tracking, a phone,
HTTP orchestration, or a GPU.

## 2. Boundary decisions

### 2.1 Replace the event-result contract

Replace `vision-detection/v1` in active code and fixtures with `table-observation/v1`. Plan 0005
remains an immutable historical record. The local PoC contract is not deployed, so do not maintain a
dual compatibility path.

A table observation is uncertain visual evidence. It is not the true table state and does not assert
that any observed card was played. One ordered observation contains zero or more anonymous observed
cards. Each observed card can contain ranked visual card identity candidates.

The minimal V1 capability is:

```text
identity_candidates
```

Later producers can add these optional capabilities without changing the reconstruction input
shape:

```text
presence_score
newly_visible_score
active_area_score
association_candidates
card_tracklets
```

Every result declares its capabilities. A missing optional field means that the producer did not
provide that evidence. It never means zero.

### 2.2 Keep visual and game claims separate

The TableEvidenceAnalyzer can report that a card became newly visible or appears inside the active
table area. It must not report a player, turn, legal move, trick number, deck-count decision, or final
card play.

The reconstruction engine infers:

- persistent cards across observations;
- false and repeated observations;
- card plays and their active players;
- trick clearing and trick boundaries;
- missing card plays;
- alternative round hypotheses.

The engine consumes derived visual scores. It does not consume frames, video, boxes, corners,
optical flow, or model tensors.

### 2.3 Name the deck variant

The shared card set contains 24 visual identities. A canonical round contains 40 card plays and 10
tricks. Use the explicit manifest:

```text
doko-40-v1   ranks J Q K 10 A, two physical copies, 40 card plays, 10 tricks
```

The rules and generator load
`fixtures/game-engine/v1/decks/doko-40-v1.json`. They derive deck membership, multiplicity, player
hand size, and trick count from the manifest.

The TableEvidenceAnalyzer can report an identity that is outside this round's deck. Reconstruction
rejects it for this ruleset. Do not describe the 48-card structure as a canonical round without a
separate glossary decision.

### 2.4 Preserve visual identity and physical-card count

The TableEvidenceAnalyzer predicts a visual card identity such as `HEARTS_QUEEN`. It does not
distinguish the two physical copies.

An observed-card identifier and a card-tracklet identifier refer only to derived visual evidence.
They are not physical-card identifiers. Reconstruction enforces physical multiplicity from the deck
manifest.

Synthetic ground truth can use private physical-copy identifiers to create player hands. Those
identifiers must not appear in the table-observation contract.

### 2.5 Keep score meaning explicit

Identity candidates use positive finite values that sum to one within a documented tolerance. They
are conditional on the observed-card proposal representing a card.

`presence_score` is separate evidence that the proposal represents a card. Transition, spatial, and
association scores are also separate evidence families. Do not normalize unrelated score families
together.

Every result declares one of:

```text
fixture
uncalibrated
calibrated
```

The engine can rank hypotheses with configured feature weights. It must not multiply correlated
scores as if they were independent calibrated probabilities. It must preserve calibration labels
and must not present an uncalibrated result as round confidence.

### 2.6 Keep acquisition failures explicit

The observation contract keeps these outcomes distinct:

```text
observed
insufficient_evidence
```

For `observed`, an empty observed-card list means that no card was detected. It does not prove that
the table was empty. `insufficient_evidence` means that the producer could not make an observation.

Missing event proposals, missing observations, false proposals, and false observed cards are
reconstruction concerns. They must remain visible in diagnostics.

## 3. Shared contracts and fixtures

Create canonical artifacts:

```text
GAME_RECONSTRUCTION_CONTRACT.md
fixtures/game-engine/v1/card-set.json
fixtures/game-engine/v1/decks/doko-40-v1.json
fixtures/game-engine/v1/observations/minimal.json
fixtures/game-engine/v1/rounds/unambiguous.json
fixtures/game-engine/v1/rounds/late-resolution.json
fixtures/game-engine/v1/rounds/ambiguous.json
fixtures/game-engine/v1/rounds/impossible.json
fixtures/game-engine/v1/rounds/incomplete.json
fixtures/game-engine/v1/rounds/occlusion.json
fixtures/game-engine/v1/rounds/side-card.json
fixtures/game-engine/v1/rounds/human-corrected.json
```

Each round scenario contains:

- the reconstruction input;
- private ground truth for tests;
- enabled observation capabilities;
- the expected result status;
- expected card plays, trick winners, focused alternatives, or invariant checks;
- a short statement of the behavior it proves.

Swift, backend, TableEvidenceAnalyzer, and game-reconstruction code must use the same canonical
contracts. Do not copy fixtures into component-only result formats.

## 4. Synthetic round and observation generator

Build a seeded generator as a first-class test tool. It starts from legal rounds, not random
candidate lists.

### Ground-truth generation

For one selected deck and ruleset:

1. Create each physical card exactly once.
2. Shuffle with a supplied seed.
3. Select four active players and a dealer.
4. Give each active player an equal-size player hand.
5. Select only legal card plays for each trick.
6. Record every player, visual card identity, private physical copy, trick, and winner.
7. Assert that deterministic replay reproduces every winner.

### Observation generation

Convert the latent round into a sequence of table observations. Support independent, deterministic
error modules:

- repeated observations from false event proposals;
- empty observations during occlusion;
- missing observations and missing card plays;
- a card that disappears and reappears;
- several identity candidates, wrong top candidates, and ties;
- false observed-card proposals and duplicate detections;
- cards retained outside the active table area;
- an old trick shown again;
- early physical appearance before the expected turn;
- trick clearing;
- repeated visual identities from the two physical copies;
- a true identity absent from the candidate list;
- a candidate that exceeds deck multiplicity;
- optional presence, transition, spatial, association, and tracklet evidence.

Each evidence family can be enabled or disabled. The generator writes its seed, configuration, and
capability set into the fixture. The same input must produce byte-stable semantic content.

Synthetic scenarios test contracts, rules, search, and failure handling. They do not measure real
TableEvidenceAnalyzer quality.

## 5. Ruleset v1

Implement normal round card-play rules behind a `Ruleset` interface:

- deck membership and physical multiplicity;
- suit and trump classification;
- trick-following category;
- card ordering within a trick;
- trick winner;
- clockwise turn order among active players;
- next-trick leader;
- player-hand and card-play counts from the deck manifest;
- the canonical count of 10 tricks per round.

Record disputed or table-specific Doppelkopf rules in ruleset configuration. Do not hide them in
search branches.

The PoC does not need Hochzeit, solos, announcements, round scoring, game scoring, or tournament
variants.

## 6. Reconstruction oracle

Implement a deliberately small exhaustive solver. It treats these values as latent:

- association between observed cards across observations;
- whether an observed card is false;
- whether a card persisted while not detected;
- which visual card identity was present;
- whether and when a card play occurred;
- active-player attribution and logical card-play order;
- trick clearing;
- a bounded number of missing card plays.

First support partial rounds and constrained scenarios. Use the deterministic rules core to reject
illegal branches. Use configured visual evidence weights only to rank legal branches.

Merge branches that produce the same gameplay result. Return ambiguity when retained branches differ
in a card play, player attribution, order, trick boundary, or winner.

This solver is the correctness oracle for plan 0023. It is not required to scale to a complete noisy
round.

## 7. Result and correction contracts

Return enough information to distinguish observations, visual ranking, rules, and human decisions:

```text
status: resolved | ambiguous | impossible | incomplete
hypotheses[]:
  gameplay result
  source observations
  visual evidence score breakdown
  applied constraints
focused_decisions[]:
  smallest difference between retained hypotheses
  alternatives and source evidence references
diagnostics:
  ruleset and deck versions
  capabilities and calibration labels seen
  missing and rejected observations
  merged and rejected hypotheses
  search limits
```

Preserve every raw table observation unchanged.

Define immutable correction constraints for:

- selecting a card identity;
- assigning an active player;
- inserting or deleting a card play;
- changing card-play order;
- marking an observation irrelevant;
- associating or separating observed cards;
- setting a trick boundary;
- supplying a complete card-play sequence.

Re-run reconstruction after applying constraints. Report rules or deck conflicts. The PoC needs
contract and command-line tests, not a graphical editor.

## 8. Small implementation milestones

### M0 — Freeze the minimal boundary

1. Write `GAME_RECONSTRUCTION_CONTRACT.md` and strict schema models.
2. Freeze identity-only `table-observation/v1` and capability extension rules.
3. Add the deck manifest and minimal observation fixture.
4. Add one complete exact-observation round fixture.
5. Add contract tests on both the TableEvidenceAnalyzer and reconstruction sides.

Acceptance:

- one canonical observation fixture crosses the boundary unchanged;
- the contract contains no player, turn, legal-move, or game-state claims from the
  TableEvidenceAnalyzer;
- an absent optional feature is distinct from a zero score;
- the 40-card manifest produces exactly 10 tricks.

Progress (2026-08-27): M0 is complete. Added the strict `table-observation/v1` and
`round-reconstruction-input/v1` models, the shared game-reconstruction contract document, and an
exact 40-observation scenario with private physical-copy ground truth. The analyzer-side and
reconstruction-side tests parse the same observation fixture and compare canonical semantic JSON.

### M1 — Rules and deterministic replay

1. Scaffold `game_engine/` with the root Python 3.13 toolchain.
2. Implement cards, deck manifests, normal round rules, and trick comparison.
3. Replay an already resolved round and derive trick winners.
4. Add exhaustive rule tests for card ordering and following categories.

Acceptance:

- every generated clean round replays without contradiction;
- deck-count and card-play-count violations fail clearly;
- ordinary tests need no model, video, network, or GPU.

Progress (2026-08-27): M1 is complete. Added the manifest-backed `Ruleset` interface and normal
round rules for trump, plain-suit following, clockwise turns, and trick comparison. Added complete
round replay with clear deck-count, card-play-count, hand, turn, and following-category failures.
The exact scenario now contains a legal 40-play sequence and replay derives all 10 trick winners.

### M2 — Synthetic observation generator

1. Generate legal rounds from a seed.
2. Generate identity-only table observations.
3. Add independent observation-error modules from section 4.
4. Commit the canonical scenarios from section 3.
5. Add property tests across many seeds.

Acceptance:

- every generated observation validates;
- every clean scenario reconstructs to its source round;
- each error scenario exercises its documented branch.

Progress (2026-08-27): M2 is complete. Added a seeded legal-round generator with private physical
copies and deterministic replay verification. Added composable observation-error modules for
repetition, empty and insufficient evidence, missing observations, candidate confusion, false and
duplicate proposals, retained side cards, old-trick replay, early appearance, trick clearing,
occlusion reappearance, missing identities, and candidate multiplicity conflicts. Optional evidence
capabilities are emitted only when enabled. Added property tests across 20 seeds and the eight
canonical scenario fixtures from section 3.

### M3 — Identity-only exhaustive oracle

1. Infer card plays from anonymous identity candidate lists.
2. Support repeated, empty, missing, false, and ambiguous observations.
3. Merge equivalent gameplay hypotheses.
4. Produce focused differences and diagnostics.

Acceptance:

- a lower-ranked identity can win when the top candidate is illegal;
- a bounded missed play can be inferred when only one legal card remains;
- tied legal results remain ambiguous;
- impossible and incomplete results remain distinct;
- diagnostics explain rejected fixture branches.

Progress (2026-08-27): M3 is complete. Added a bounded exhaustive identity-only oracle that selects
ranked candidates, ignores false and repeated proposals, handles empty observations, and infers
bounded missing plays. Complete branches derive player hands and pass through deterministic replay,
then merge equivalent gameplay results. Added focused first-difference decisions, identity score
breakdowns, source provenance, search limits, and rejection diagnostics. Exact card-tracklet reuse
is rejected when that optional association capability is present. Added tests for all canonical
scenario statuses, lower-ranked legal identity recovery, a uniquely slotted missing play, tied
legal alternatives, and the impossible/incomplete distinction.

### M4 — Additive visual evidence

Add synthetic support and scoring adapters in this order:

1. presence evidence;
2. newly-visible and predecessor evidence;
3. active-area evidence;
4. card-tracklet evidence.

Acceptance for each addition:

- the identity-only baseline still passes unchanged;
- the field is optional and capability-declared;
- one scenario proves that the evidence helps;
- one scenario proves that the engine can resist misleading evidence;
- an ablation records the result with and without the evidence family.

### M5 — Human constraints and local handoff

1. Add the correction-constraint contract.
2. Apply focused and full-sequence corrections to fixtures.
3. Re-run reconstruction and preserve the earlier result.
4. Read checked-in table observations through the shared schema.
5. Keep integration file-based before HTTP orchestration exists.

Acceptance:

- a focused correction resolves the ambiguous fixture;
- a conflicting correction reports the exact rule or deck conflict;
- a complete manual sequence can produce a reviewed reconstruction;
- no correction mutates source observations.

## 9. Out of scope

Move these to later plans:

- real video-snippet capture and backend transport: plan 0025;
- real card detection, identity recognition, spatial scoring, and tracking: plan 0022;
- scalable complete-round and complete-game search: plan 0023;
- graphical focused-review and complete-editor workflows: plan 0026;
- session and game setup UI;
- Hochzeit, solos, announcements, scoring, and final game scoring;
- production persistence, APIs, deployment, and operations: plan 0024.

## 10. Verification

Run:

```bash
cd game_engine
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Run TableEvidenceAnalyzer contract tests against the exact same observation fixtures. Ordinary CI
must remain CPU-only and offline.

## 11. Definition of done

- the table-observation and reconstruction contracts are frozen and tested on both sides;
- deck size and physical multiplicity are explicit data;
- a seeded generator creates legal rounds and controlled observation failures;
- canonical resolved, ambiguous, impossible, incomplete, occlusion, side-card, and corrected
  fixtures exist;
- deterministic rules replay passes exhaustive card-order tests;
- an identity-only exhaustive solver acts as a correctness oracle;
- optional evidence families can be added and ablated independently;
- human corrections are immutable constraints that trigger recomputation;
- later recognition, tracking, scalable search, and review UI have a tested boundary to build on.
