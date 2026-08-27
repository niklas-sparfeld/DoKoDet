# DokoDetector Game Reconstruction — Future Development

## Plan status

- **Summary:** Scale the game-engine PoC from uncertain rounds to complete games
- **Status:** To Specify
- **Depends on:** Plan 0006 round contract, rules core, synthetic generator, and exhaustive oracle

## 1. Purpose

First extend the proven game-engine core from partial-round correctness scenarios to complete
uncertain rounds. Then reconstruct a game as an ordered set of rounds with players, dealers, round
scores, and a final game score. Keep development independent from real VisionDetector quality by
using the seeded synthetic corpus.

Support the canonical many-to-many relationship between sessions and games. One session can show
parts of several games, and one game can continue in a later session.

Use `player_count × 4` as the typical number of rounds, not as an unconditional completion rule.
Record game completion explicitly. Do not infer it from the end of a recording or session.

## 2. Likely work areas

### Scalable sequence search

Compare beam search, hypothesis merging, and targeted backtracking against the exhaustive oracle on
partial rounds. Preserve raw vision probability separately from rules-based pruning. Keep round
search separate from game-level ordering and scoring.

### Initial player-hand feasibility

For each round, model whether at least one initial player-hand distribution remains compatible with
observed card plays and following-suit constraints. Start with the smallest clear formulation.
Consider CSP or SAT only after profiling.

### Missing and false observations

Define explicit policies for missing card plays, false CardEventNet event proposals, and true cards
absent from the VisionDetector candidate list. Do not manufacture hidden evidence without a scored
and diagnosed hypothesis branch.

### Diagnostics and confidence

Explain rejected candidates, binding constraints, unresolved alternatives, and search truncation.
Keep round confidence separate from game confidence. Do not claim either is calibrated until
synthetic and real validation support it.

### Ruleset expansion

Add game assembly, dealer rotation, round scoring, and final game scoring after normal-round
reconstruction is stable. Then add Hochzeit, solos, announcements, and table variants behind
versioned rules and fixtures.

## 3. Entry measurements

Before splitting this plan into implementation milestones, record:

- hypothesis growth on the plan 0006 synthetic scenarios;
- how often deck-count and local trick rules resolve ambiguity within a round;
- how often round player-hand feasibility constraints are required;
- the cost of exhaustive search on partial rounds;
- expected missed reviewed event and candidate-list behavior from recognition experiments;
- product requirements for interactive latency and correction.

## 4. Completion direction

A later concrete plan should define measured limits for complete-round and complete-game runtime,
ambiguity, explainability, scoring, continuation across sessions, and recovery. It should preserve
the plan 0006 contracts and oracle tests.
