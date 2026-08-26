# DokoDetector Game Engine — Contract and Core PoC

## Plan status

- **Summary:** Freeze the vision-to-game contract and build the rules core with synthetic inputs
- **Status:** Ready
- **Reviewed:** 2026-08-26 against plan 0005 and the current repository
- **Starts with:** Plan 0005 M0. Neither plan waits for a useful vision model.
- **Next:** [Plan 0023](../0-to-specify/0023-Game_Reconstruction_Development.md) covers scalable
  uncertain-sequence inference.

## 1. Outcome

Build the game-engine boundary and deterministic core early enough that game reconstruction can
develop independently from card recognition.

At the end of this plan, a developer can run:

```text
legal synthetic game
  -> deterministic vision-error generator
  -> versioned sequence of ranked card candidates
  -> shared contract parser
  -> deterministic rules replay or small exhaustive solver
  -> resolved, ambiguous, or impossible result
```

This plan must not depend on trained VisionDetector weights or real detector quality.

## 2. First contract decisions

### 2.1 Name the deck variant

The old plans disagree about game length:

- the VisionDetector card list contains 24 visual identities and 48 physical cards;
- the old game-engine completion condition assumes 40 plays.

Do not use an ambiguous value such as `standard`. Define explicit deck manifests:

```text
doko-40-v1   ranks J Q K 10 A, two physical copies, 40 plays
doko-48-v1   ranks 9 J Q K 10 A, two physical copies, 48 plays
```

The first shared fixture must declare one variant. The rules and generator use the manifest's card
count. They must not hard-code 40 or 48. Supporting both manifests is small and removes this
contract ambiguity before the product chooses its first playing variant.

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
calibration label and must not present an uncalibrated result as a calibrated game confidence.

### 2.3 Preserve visual identity and physical-card count

VisionDetector predicts a visual identity such as `HEARTS_QUEEN`. It does not distinguish the two
physical copies. The game engine enforces the maximum count from the deck manifest.

Synthetic ground truth may use a private physical-copy identifier to generate hands. That identifier
must not appear as a VisionDetector candidate.

### 2.4 Keep acquisition failures explicit

The sequence contract keeps these vision outcomes distinct:

```text
confident
uncertain
no_card_found
insufficient_evidence
```

The engine must not silently replace an empty candidate set with every card in the deck. A caller
may choose an explicit missing-observation policy, but that policy is game reconstruction logic and
must be visible in diagnostics.

## 3. Shared contracts and fixtures

Plan 0005 creates the single-event `vision-detection/v1` contract. This plan adds a sequence
envelope, for example:

```json
{
  "schema_version": "game-reconstruction-input/v1",
  "game_id": "synthetic-normal-001",
  "ruleset": {"name": "doko-normal", "version": "v1"},
  "deck_variant": "doko-40-v1",
  "players": ["north", "east", "south", "west"],
  "first_player": "north",
  "vision_results": []
}
```

The sequence contract owns game setup and ordering. The single-event VisionDetector result remains
free of player, turn, legal-move, and game-state context.

Create canonical artifacts:

```text
GAME_ENGINE_CONTRACT.md
fixtures/game-engine/v1/decks/doko-40.json
fixtures/game-engine/v1/decks/doko-48.json
fixtures/game-engine/v1/unambiguous-game.json
fixtures/game-engine/v1/late-resolution.json
fixtures/game-engine/v1/ambiguous-game.json
fixtures/game-engine/v1/impossible-game.json
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

## 4. Synthetic game and observation generator

Build a seeded generator as a first-class test tool. It starts from rules, not from random candidate
lists.

### Ground-truth generation

For one selected deck and ruleset:

1. Create each physical card exactly once.
2. Shuffle with a supplied seed.
3. Deal equal hands.
4. Select only legal plays for each trick.
5. Record the player, visual card identity, physical copy, trick, and winner.
6. Assert that replaying the generated game reproduces every winner.

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

Implement normal-game rules behind a `Ruleset` interface:

- deck membership and physical multiplicity;
- suit and trump classification;
- trick-following category;
- card ordering within a trick;
- trick winner;
- clockwise player rotation;
- next-trick leader;
- expected hand, play, and trick counts from the deck manifest.

Record disputed or table-specific Doppelkopf rules in the ruleset configuration. Do not hide them
in solver branches.

The PoC does not need Hochzeit, solos, announcements, scoring, or tournament variants.

## 6. Result contract

Return enough information to distinguish rules from visual evidence:

```text
status: resolved | ambiguous | impossible | incomplete
plays[]:
  event/result identity
  attributed player
  selected card, if resolved
  source vision probability
  rejected alternatives with reasons
tricks[]:
  leader
  plays
  winner
diagnostics:
  ruleset and deck versions
  explored and rejected hypotheses
  missing observations
  calibration labels seen
```

Preserve the raw VisionDetector result unchanged. Do not overwrite it when game rules select a
lower-ranked card.

## 7. Small implementation milestones

### M0 — Freeze the boundary

1. Reconcile plan 0005 with the normalized candidate-probability rule.
2. Add the deck manifests and shared schemas.
3. Add one single-event fixture and one complete unambiguous sequence fixture.
4. Add contract tests in the VisionDetector and game-engine packages.

Acceptance:

- one canonical fixture crosses the component boundary unchanged;
- 40-card and 48-card counts come from data;
- the engine never takes the logarithm of an arbitrary score;
- VisionDetector results contain no player or rule context.

### M1 — Rules and deterministic replay

1. Scaffold `game_engine/` with the root Python 3.13 toolchain.
2. Implement cards, deck manifests, normal-game rules, and trick comparison.
3. Replay an already resolved game and derive player attribution and trick winners.
4. Add exhaustive rule tests for every card ordering and following category.

Acceptance:

- every generated game replays without contradiction;
- duplicate-card and play-count violations fail clearly;
- ordinary tests need no model, video, network, or GPU.

### M2 — Synthetic generator and scenario corpus

1. Generate legal games from a seed.
2. Add deterministic vision-error injection.
3. Commit the canonical scenarios from section 3.
4. Add property tests across many seeds without committing every generated game.

Acceptance:

- every candidate probability vector validates;
- every clean scenario resolves to its source game;
- each error scenario exercises its documented branch.

### M3 — Small exhaustive inference oracle

Implement a deliberately simple exhaustive solver for short games and constrained scenario
fixtures. It branches over supplied candidates, rejects deck-count and local trick-rule violations,
and sums log probabilities.

This solver is a correctness oracle. It is not required to scale to a complete ambiguous game.

Acceptance:

- a lower-ranked visual candidate can win when the top candidate is illegal;
- genuinely tied legal solutions return `ambiguous`;
- a missing true candidate can return `impossible`;
- diagnostics explain every rejected fixture branch.

### M4 — Local integration handoff

1. Read stored plan 0005 results through the shared schema.
2. Assemble ordered results by session event sequence outside VisionDetector.
3. Run one scripted complete sequence through deterministic replay.
4. Keep the integration usable with checked-in files before HTTP orchestration exists.

Acceptance:

- game-engine development remains independent from real recognition;
- the backend and engine use one result schema;
- no game rule leaks into the detector input.

## 8. Out of scope

Move these to [plan 0023](../0-to-specify/0023-Game_Reconstruction_Development.md):

- scalable full-game beam search;
- initial-hand feasibility through CSP, SAT, or another solver;
- hypothesis merging and performance tuning;
- confidence calibration for resolved games;
- automatic recovery from missing card-play events;
- player setup UI;
- Hochzeit, solos, announcements, and scoring;
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

- the vision-to-game contract is frozen and tested on both sides;
- deck size and card multiplicity are explicit data;
- a seeded generator creates legal games and controlled vision errors;
- canonical resolved, ambiguous, impossible, and incomplete fixtures exist;
- deterministic rules replay passes exhaustive card-order tests;
- a small exhaustive solver acts as a correctness oracle;
- game-engine work no longer waits for useful VisionDetector output;
- later scalable inference has a tested contract and oracle to build on.
