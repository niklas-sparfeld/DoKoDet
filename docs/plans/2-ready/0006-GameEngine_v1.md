# DokoDetector Game Engine — Contract and Core PoC

## Plan status

- **Summary:** Freeze the vision-to-round contract and build the rules core with synthetic inputs
- **Status:** Ready
- **Reviewed:** 2026-08-27 against the glossary, plan 0005, and the current repository
- **Starts with:** Plan 0005 M0. Neither plan waits for a useful vision model.
- **Next:** [Plan 0023](../0-to-specify/0023-Game_Reconstruction_Development.md) covers scalable
  uncertain-sequence inference.

## 1. Outcome

Build the game-engine boundary and deterministic round core early enough that game reconstruction
can develop independently from card recognition.

At the end of this plan, a developer can run:

```text
legal synthetic round
  -> deterministic vision-error generator
  -> versioned sequence of ranked card candidates
  -> shared contract parser
  -> deterministic rules replay or small exhaustive solver
  -> resolved, ambiguous, or impossible result
```

This plan must not depend on trained VisionDetector weights or real detector quality.

## 2. First contract decisions

### 2.1 Name the deck variant

The old plans disagree about the number of cards in one card-play sequence:

- the VisionDetector card list contains 24 visual identities and 48 physical cards;
- the canonical round has 10 tricks and therefore 40 card plays.

Do not use an ambiguous value such as `standard`. Define the first explicit deck manifest:

```text
doko-40-v1   ranks J Q K 10 A, two physical copies, 40 card plays, 10 tricks
```

The first shared fixture must declare this variant. The rules and generator derive the card
identities and multiplicity from the manifest. They also validate the canonical 40-play and
10-trick round invariants. VisionDetector can recognize cards that are not in this round's deck,
but the game engine rejects them for this ruleset.

Do not describe a 48-card, 12-trick structure as a round. Supporting that structure requires a
separate canonical term and an explicit glossary decision.

### 2.2 Give the engine normalized candidate probabilities

At the VisionDetector boundary, every ranked candidate set uses positive, finite probabilities that
sum to one within a documented tolerance. The result also declares its calibration state:

```text
fixture
uncalibrated
calibrated
```

An internal model may produce logits, distances, or arbitrary scores. Its VisionDetector adapter
must convert them to normalized candidate probabilities before serialization. `uncalibrated` means
that the numeric distribution is useful for ranking but is not an empirical confidence claim.

The game engine may add log probabilities after applying a configured floor. It must preserve the
calibration label and must not present an uncalibrated result as calibrated round confidence.

### 2.3 Preserve visual identity and physical-card count

VisionDetector predicts a visual identity such as `HEARTS_QUEEN`. It does not distinguish the two
physical copies. The game engine enforces the maximum count within a round from the deck manifest.

Synthetic ground truth may use a private physical-copy identifier to generate player hands. That
identifier must not appear as a VisionDetector candidate.

### 2.4 Keep acquisition failures explicit

The sequence contract keeps these vision outcomes distinct:

```text
confident
uncertain
no_card_found
insufficient_evidence
```

The engine must not silently replace an empty candidate set with every card in the deck. A caller
may choose an explicit missing-observation policy, but that policy is round reconstruction logic and
must be visible in diagnostics.

## 3. Shared contracts and fixtures

Plan 0005 creates the single-event `vision-detection/v1` contract. This plan adds a round sequence
envelope, for example:

```json
{
  "schema_version": "round-reconstruction-input/v1",
  "game_id": "synthetic-game-001",
  "round_id": "synthetic-game-001-round-01",
  "ruleset": {"name": "doko-normal", "version": "v1"},
  "deck_variant": "doko-40-v1",
  "game_players": ["player-01", "player-02", "player-03", "player-04", "player-05"],
  "active_players": ["player-01", "player-02", "player-03", "player-04"],
  "dealer": "player-05",
  "first_trick_leader": "player-01",
  "vision_results": []
}
```

The sequence contract owns round setup and ordering. `game_players` lists the players in the game;
`active_players` lists the four players in this round. The dealer is a player and can be outside
`active_players`. The single-event VisionDetector result remains
free of player, turn, legal-move, and game-state context.

Create canonical artifacts:

```text
GAME_ENGINE_CONTRACT.md
fixtures/game-engine/v1/decks/doko-40.json
fixtures/game-engine/v1/unambiguous-round.json
fixtures/game-engine/v1/late-resolution-round.json
fixtures/game-engine/v1/ambiguous-round.json
fixtures/game-engine/v1/impossible-round.json
fixtures/game-engine/v1/incomplete-observations.json
```

Each scenario contains:

- the game-engine input;
- private ground truth for tests;
- the expected result status;
- expected trick winners or invariant checks;
- a short statement of the behavior it proves.

Swift, backend, VisionDetector, and game-engine code must not copy these fixtures into
component-only formats.

## 4. Synthetic round and observation generator

Build a seeded generator as a first-class test tool. It starts from rules, not from random candidate
lists.

### Ground-truth generation

For one selected deck and ruleset:

1. Create each physical card exactly once.
2. Shuffle with a supplied seed.
3. Select four active players and one dealer from the game's players.
4. Give each active player an equal-size player hand.
5. Select only legal card plays for each trick.
6. Record the active player, visual card identity, physical copy, trick, and winner.
7. Assert that replaying the generated round reproduces every winner.

### Vision-error generation

Convert ground truth to `vision-detection/v1` results with configured, deterministic errors:

- correct and confident;
- correct but ambiguous;
- wrong top candidate with the true card lower in the list;
- tied candidates;
- repeated visual identities from the two physical copies;
- `no_card_found`;
- `insufficient_evidence`;
- a missing true card, used to test impossible outcomes;
- a candidate that exceeds the deck count;
- probability distributions labeled `fixture`.

The generator writes its seed and configuration into the fixture. The same inputs must produce
byte-stable semantic content. Timestamps and UUIDs must be derived deterministically or omitted from
the comparison.

Do not use synthetic sequences as evidence of real VisionDetector accuracy. They test contracts,
rules, search, and failure handling.

## 5. Ruleset v1

Implement normal round card-play rules behind a `Ruleset` interface:

- deck membership and physical multiplicity;
- suit and trump classification;
- trick-following category;
- card ordering within a trick;
- trick winner;
- clockwise turn order among active players;
- next-trick leader;
- expected player-hand and card-play counts from the deck manifest;
- the canonical count of 10 tricks per round.

Record disputed or table-specific Doppelkopf rules in the ruleset configuration. Do not hide them
in solver branches.

The PoC does not need Hochzeit, solos, announcements, round scoring, game scoring, or tournament
variants.

## 6. Result contract

Return enough information to distinguish rules from visual evidence:

```text
status: resolved | ambiguous | impossible | incomplete
card_plays[]:
  reviewed_event_id or vision_result_id
  attributed active player
  selected card, if resolved
  source vision probability
  rejected alternatives with reasons
tricks[]:
  trick leader
  card plays
  trick winner
diagnostics:
  ruleset and deck versions
  explored and rejected hypotheses
  missing observations
  calibration labels seen
```

Preserve the raw VisionDetector result unchanged. Do not overwrite it when round rules select a
lower-ranked card.

## 7. Small implementation milestones

### M0 — Freeze the boundary

1. Reconcile plan 0005 with the normalized candidate-probability rule.
2. Add the deck manifests and shared schemas.
3. Add one single-event fixture and one complete unambiguous round fixture.
4. Add contract tests in the VisionDetector and game-engine packages.

Acceptance:

- one canonical fixture crosses the component boundary unchanged;
- the 40-card deck content comes from data and produces exactly 10 tricks;
- the engine never takes the logarithm of an arbitrary score;
- VisionDetector results contain no player or rule context.

### M1 — Rules and deterministic replay

1. Scaffold `game_engine/` with the root Python 3.13 toolchain.
2. Implement cards, deck manifests, normal round rules, and trick comparison.
3. Replay an already resolved round and derive active-player attribution and trick winners.
4. Add exhaustive rule tests for every card ordering and following category.

Acceptance:

- every generated round replays without contradiction;
- physical-card and card-play-count violations fail clearly;
- ordinary tests need no model, video, network, or GPU.

### M2 — Synthetic generator and scenario corpus

1. Generate legal rounds from a seed.
2. Add deterministic vision-error injection.
3. Commit the canonical scenarios from section 3.
4. Add property tests across many seeds without committing every generated round.

Acceptance:

- every candidate probability vector validates;
- every clean scenario resolves to its source round;
- each error scenario exercises its documented branch.

### M3 — Small exhaustive inference oracle

Implement a deliberately simple exhaustive solver for partial rounds and constrained scenario
fixtures. It branches over supplied candidates, rejects deck-count and local trick-rule violations,
and sums log probabilities.

This solver is a correctness oracle. It is not required to scale to a complete ambiguous round.

Acceptance:

- a lower-ranked visual candidate can be selected when the top candidate is illegal;
- genuinely tied legal solutions return `ambiguous`;
- a missing true candidate can return `impossible`;
- diagnostics explain every rejected fixture branch.

### M4 — Local integration handoff

1. Read stored plan 0005 results through the shared schema.
2. Assemble ordered reviewed events for one round from recording timelines and explicit round spans
   outside VisionDetector.
3. Run one scripted complete round through deterministic replay.
4. Keep the integration usable with checked-in files before HTTP orchestration exists.

Acceptance:

- game-engine development remains independent from real recognition;
- the backend and engine use one result schema;
- no round rule leaks into the detector input.

## 8. Out of scope

Move these to [plan 0023](../0-to-specify/0023-Game_Reconstruction_Development.md):

- scalable full-round search and complete-game reconstruction;
- initial player-hand feasibility through CSP, SAT, or another solver;
- hypothesis merging and performance tuning;
- confidence calibration for resolved rounds and games;
- automatic recovery from missing card-play events;
- session, game, round, player, and dealer setup UI;
- Hochzeit, solos, announcements, round scoring, and final game scoring;
- production persistence and APIs.

## 9. Verification

Run:

```bash
cd game_engine
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Also run the VisionDetector contract tests against the exact same fixtures. Ordinary CI must remain
CPU-only and offline.

## 10. Definition of done

- the vision-to-round reconstruction contract is frozen and tested on both sides;
- deck size and card multiplicity are explicit data;
- a seeded generator creates legal rounds and controlled vision errors;
- canonical resolved, ambiguous, impossible, and incomplete fixtures exist;
- deterministic rules replay passes exhaustive card-order tests;
- a small exhaustive solver acts as a correctness oracle;
- game-engine work no longer waits for useful VisionDetector output;
- later scalable inference has a tested contract and oracle to build on.
