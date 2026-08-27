# DokoDetector Game Reconstruction — Scalable Development

## Plan status

- **Summary:** Scale the table-observation oracle from bounded scenarios to uncertain rounds and games
- **Status:** To Specify
- **Depends on:** Plan 0006 contracts, rules core, synthetic generator, exhaustive oracle, and search
  measurements
- **Uses later evidence from:** Plan 0022 real table-observation behavior
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Purpose

First extend the plan 0006 correctness oracle from partial-round scenarios to complete uncertain
rounds. Then reconstruct a game as an ordered set of rounds with players, dealers, round scores, and
a final game score.

Use ordered table observations as visual evidence. Treat card plays, persistent table state,
observation association, trick clearing, missing plays, and active-player attribution as latent
values. Keep the deterministic rules core independent from search strategy.

Support the canonical many-to-many relationship between sessions and games. One session can show
parts of several games, and one game can continue in a later session.

Use `player_count × 4` as the typical number of rounds, not as an unconditional completion rule.
Record game completion explicitly. Do not infer it from the end of a recording or session.

## 2. Likely work areas

### Scalable observation search

Compare beam search, hypothesis merging, dynamic programming, and targeted backtracking against the
exhaustive oracle on identical bounded scenarios.

Separate these branch types in diagnostics:

- observed-card identity;
- card presence or false proposal;
- persistence and predecessor association;
- newly-visible and active-area evidence;
- card play or non-play transition;
- missing card play;
- active-player attribution and logical order;
- trick clearing and boundary;
- ruleset branch.

Apply hard rules only for deterministic game constraints. Use visual evidence to rank, not reject,
unless the table-observation contract defines an impossible value.

### Hypothesis merging

Several observation explanations can produce the same gameplay result. Merge them before presenting
ambiguity to a person. Preserve enough provenance to explain which observations support the merged
result.

Define equivalence at several levels:

```text
same completed trick
same completed round
same unresolved focused decision
same final game score
```

Measure how much each equivalence rule reduces search and review work.

### Initial player-hand feasibility

For each round, model whether at least one initial player-hand distribution remains compatible with
the reconstructed card plays and following constraints. Start with the smallest clear formulation.
Consider CSP or SAT only after profiling.

### Missing and false observations

Support explicit scored branches for:

- missed event proposals and missing observations;
- false event proposals and repeated observations;
- false or duplicate observed cards;
- true identities absent from candidate lists;
- cards that remain latent through short occlusion;
- cards shown outside the current trick;
- early physical appearance before logical turn order.

One missing play can be resolved by the remaining deck when its slot and all other cards are known.
Two known missing cards in two known slots produce at most two assignments. Do not generalize that
bound when the missing slots or other observations are uncertain.

Do not manufacture hidden evidence. Every inferred missing play must be a named hypothesis branch
with a cost, reason, and source gap.

### Optional visual capabilities

Support identity-only observations as the permanent baseline. Add presence, newly-visible,
active-area, association, and card-tracklet evidence through capability adapters.

For each capability:

- define the score transform and weight configuration;
- keep absence neutral;
- test misleading evidence;
- run synthetic and real ablations;
- avoid double-counting correlated evidence;
- preserve producer calibration metadata.

### Diagnostics and focused alternatives

Explain rejected candidates, binding constraints, unresolved alternatives, merged hypotheses, and
search truncation. Return the smallest gameplay decision that differs between retained hypotheses.

Keep evidence score, reconstruction rank, round confidence, and game confidence separate. Do not
claim calibration until synthetic and real validation support it.

### Human correction constraints

Apply the immutable correction contract from plan 0006 at any supported scope. Re-run search after a
constraint. Preserve earlier results and report exact conflicts.

Produce a stable machine-readable set of focused questions for plan 0026. The reconstruction package
does not own the graphical review UI.

### Ruleset and game expansion

Add game assembly, dealer rotation, round scoring, and final game scoring after normal-round
reconstruction is stable. Then add Hochzeit, solos, announcements, and table variants behind
versioned rules and fixtures.

## 3. Entry measurements

Before splitting this plan into implementation milestones, record from plan 0006:

- hypothesis growth by branch type on every synthetic scenario;
- exhaustive-search cost by partial-round length;
- how often deck count and local trick rules resolve identity and persistence ambiguity;
- how often player-hand feasibility is required;
- how many observation explanations merge into the same gameplay result;
- how optional presence, transition, spatial, and tracklet evidence changes retained hypotheses;
- how misleading optional evidence affects correctness;
- how many focused decisions remain after merging;
- correction-constraint recomputation cost.

Also record from plan 0022 when available:

- real observed-card candidate-list behavior;
- false and duplicate observed-card rates;
- missing and repeated observation behavior;
- capability calibration state and correlations;
- track fragmentation and identity switches;
- supported interactive latency and correction requirements.

## 4. Future specification order

When entry measurements exist, split delivery in this order:

1. complete-round identity-only search with oracle equivalence tests;
2. hypothesis merging and focused differences;
3. bounded missing and false observation branches;
4. player-hand feasibility;
5. optional visual-capability adapters and ablations;
6. correction constraints and incremental recomputation;
7. game assembly and continuation across sessions;
8. ruleset and scoring expansion.

Each step must keep the earlier identity-only corpus passing. Do not add an optimization without an
oracle comparison on the bounded cases it replaces.

## 5. Completion direction

A later concrete plan must define measured limits for:

- complete-round and complete-game runtime and memory;
- retained hypothesis count and search truncation;
- ambiguity and focused-question count;
- recovery from missing and false observations;
- optional-capability improvement and regression;
- explainability and correction latency;
- scoring and continuation across sessions.

It must preserve the plan 0006 contracts, identity-only baseline, oracle tests, raw observations,
and immutable correction history.
