# DokoDetector Game Reconstruction — Future Development

## Plan status

- **Summary:** Scale the game-engine PoC to uncertain complete games
- **Status:** To Specify
- **Depends on:** Plan 0006 contract, rules core, synthetic generator, and exhaustive oracle

## 1. Purpose

Extend the proven game-engine core from short correctness scenarios to complete uncertain games.
Keep development independent from real VisionDetector quality by using the seeded synthetic corpus.

## 2. Likely work areas

### Scalable sequence search

Compare beam search, hypothesis merging, and targeted backtracking against the exhaustive oracle on
small scenarios. Preserve raw vision probability separately from rules-based pruning.

### Initial-hand feasibility

Model whether at least one initial deal remains compatible with observed plays and following-suit
constraints. Start with the smallest clear formulation. Consider CSP or SAT only after profiling.

### Missing and false observations

Define explicit policies for missing plays, false CardEventNet events, and true cards absent from
the VisionDetector candidate list. Do not manufacture hidden evidence without a scored and
diagnosed hypothesis branch.

### Diagnostics and confidence

Explain rejected candidates, binding constraints, unresolved alternatives, and search truncation.
Do not claim calibrated game confidence until synthetic and real validation support it.

### Ruleset expansion

Add Hochzeit, solos, announcements, scoring, and table variants only after normal-game
reconstruction is stable. Keep each variant behind versioned rules and fixtures.

## 3. Entry measurements

Before splitting this plan into implementation milestones, record:

- hypothesis growth on the plan 0006 synthetic scenarios;
- how often deck-count and local trick rules resolve ambiguity;
- how often hand-feasibility constraints are required;
- the cost of exhaustive search on short games;
- expected missing-event and candidate-list behavior from recognition experiments;
- product requirements for interactive latency and correction.

## 4. Completion direction

A later concrete plan should define measured limits for complete-game runtime, ambiguity,
explainability, and recovery. It should preserve the plan 0006 contracts and oracle tests.
