# Game Engine Implementation Plan

## Plan status

- **Summary:** Reconstruct legal games
- **Status:** Draft

## Goal

Implement a deterministic/probabilistic Doppelkopf game engine that converts the VisionDetector's uncertain ordered card events into the most likely **legal played game**.

Initial scope: **normal game only**.

Inputs:

- ordered VisionDetector events with candidate cards + confidence
- four players / seating order
- first player
- declared game type (`normal` for now)
- configured ruleset

Output:

- resolved sequence of 40 played cards
- player for every play
- trick boundaries and winners
- confidence and alternative candidates where useful
- unresolved/invalid result when no plausible legal interpretation exists

## Ruleset v1

Deck:

- 40 cards
- suits: clubs, spades, hearts, diamonds
- ranks: ace, ten, king, queen, jack
- two copies of every card
- no nines
- no Schweinchen or other promotions

Normal-game trump order, highest first:

1. ♥10
2. ♣Q, ♠Q, ♥Q, ♦Q
3. ♣J, ♠J, ♥J, ♦J
4. ♦A, ♦10, ♦K

Rules:

- normal follow-suit / follow-trump obligation
- identical cards: first played wins
- exception: second ♥10 beats first ♥10
- winner of a trick leads the next trick
- no other special trick-winning rules

Keep these rules behind a `Ruleset` interface so Hochzeit and solos can be added later without changing the solver.

## Domain model

Create small immutable domain types:

```python
Card
Player
CandidateCard(card, probability)
VisionEvent(id, candidates)
Play(event_id, player, card)
Trick(leader, plays)
GameInput(events, players, first_player, game_type)
ResolvedGame(...)
```

Represent the two physical copies only through card multiplicity unless later inference requires explicit copy identity.

## Deterministic rules engine

Implement and test independently from probabilistic inference.

Core operations:

```python
is_trump(card, game_type)
compare_cards(first, second, lead, game_type)
trick_winner(trick)
next_player(player)
```

Also model information inferred from legal play.

Example:

- clubs are led
- a player plays another suit
- therefore that player had no non-trump clubs remaining at that point

The engine must preserve such constraints because they can invalidate interpretations later.

## Solver state

A hypothesis should contain at least:

```python
SolverState:
    next_event_index
    current_player
    current_trick
    completed_tricks

    played_card_counts
    player_constraints

    log_probability
    decisions
```

`player_constraints` tracks facts inferred from previous plays, especially suits/trump categories a player was known to be void in.

Do not invent complete starting hands unless necessary.

## Sequence decoding

Process events chronologically.

For each current hypothesis:

1. take the next VisionDetector event
2. branch once per candidate card
3. reject impossible branches
4. apply rule-derived constraints
5. add the candidate's log probability
6. complete the trick after four plays
7. derive its winner
8. set that player as leader of the next trick

Reject a branch when, for example:

- more than two copies of a card would exist
- inferred hand constraints make the play impossible
- a prior failure to follow suit conflicts with a later interpretation
- the resulting game cannot contain ten cards per player

## Hand-consistency checking

Following suit cannot be checked from observed cards alone because the initial hands are unknown.

Model the problem as constraints over possible initial card ownership.

For every hypothesis, ensure there still exists at least one assignment of the 40 physical cards to four 10-card starting hands that is compatible with:

- all cards attributed to each player
- exactly ten cards per player
- two copies of each card globally
- every observed failure to follow suit/trump

Start with a simple constraint solver/backtracking implementation.

If performance becomes an issue, replace this component with a more specialized CSP/SAT formulation without changing the outer game solver.

This feasibility test is the main mechanism that lets later observations resolve earlier ambiguous detections.

## Search strategy

Do not enumerate every candidate combination.

Start with beam search:

```text
expand hypotheses
→ remove illegal states
→ merge equivalent states where possible
→ retain best N hypotheses
```

Use summed log probabilities from VisionDetector as the base score.

Make beam width configurable.

For tests and small synthetic cases, also provide an exhaustive solver. Use it as an oracle to verify that beam search returns the same result.

## Candidate handling

VisionDetector candidates should include enough low-confidence alternatives that game rules can recover from recognition mistakes.

Support an explicit fallback candidate such as `unknown` if useful, but do not silently manufacture arbitrary cards inside the solver.

The contract should distinguish:

- detector candidate probability
- rules-derived posterior preference
- impossible candidates

## Result model

Return more than just the winning card sequence.

Example:

```yaml
plays:
  - event_id: 17
    player: bob
    card: diamonds_10
    confidence: 0.97
    vision_probability: 0.31
    alternatives:
      hearts_10:
        vision_probability: 0.54
        status: rejected
        reason: incompatible_with_game
```

Also return:

```yaml
status: resolved | ambiguous | impossible
tricks: [...]
global_confidence: ...
```

Keep enough diagnostics to understand whether failures originate from vision, rules, or inference.

## Implementation phases

### 1. Card and trick rules

Implement:

- card model
- deck definition
- trump classification
- card comparison
- Dulle exception
- trick winner
- player rotation

Tests should exhaustively cover card ordering.

### 2. Deterministic game replay

Given an already resolved sequence of cards:

- assign players
- divide into tricks
- calculate winners
- determine subsequent leaders

This establishes the non-probabilistic core.

### 3. Basic probabilistic solver

Add:

- candidate events
- branching
- duplicate-card constraints
- log-probability scoring
- exhaustive solver
- beam-search solver

Initially omit follow-suit hand inference.

### 4. Hand feasibility constraints

Implement legal-hand reconstruction / CSP checking.

Add tests where:

- the locally most probable card becomes impossible
- an off-suit play establishes a void
- an observation many tricks later resolves an early ambiguity

### 5. Diagnostics and confidence

Add:

- rejected-candidate reasons
- ambiguity detection
- confidence calculation
- serialization of `ResolvedGame`

### 6. Integration

Define a stable boundary such as:

```python
resolve_game(
    game_input: GameInput,
    ruleset: Ruleset,
) -> ResolvedGame
```

Integrate fixtures matching the VisionDetector output schema.

Use recorded detector outputs as end-to-end regression cases.

## Testing strategy

Prefer test-first development for each rule and inference behavior.

Maintain three layers:

- unit tests for Doppelkopf rules
- solver tests using synthetic ambiguous games
- regression tests using real VisionDetector output

Important generated/property tests:

- every resolved game contains exactly 40 plays
- every player plays exactly 10 cards
- no card occurs more than twice
- every trick has exactly four plays
- next trick leader equals previous trick winner
- exhaustive and beam solver agree on small test cases

## Deliberately out of scope

Do not implement yet:

- Hochzeit
- Armut
- solos
- Re/Kontra
- announcements
- team inference
- scoring
- game-type inference
- first-player inference
- seating-order inference

The surrounding app may later use the same solver to **suggest** first player, seating order, or game type by trying multiple inputs and comparing their resulting likelihoods. The core engine should continue treating them as explicit inputs.

## Completion criteria

The first version is done when it can take a 40-event normal-game VisionDetector result and either:

1. produce the highest-probability globally legal game with correct players and trick winners,
2. report multiple genuinely plausible games, or
3. explain that no legal game is compatible with the supplied evidence.

The architecture must allow a new game type to be added primarily by extending the ruleset rather than modifying the inference engine.
