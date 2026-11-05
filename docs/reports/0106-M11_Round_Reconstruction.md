# 0106 M11 — Round reconstruction

## Result

The iOS core now reads M10's retained `table-observations.json` and runs a local, bounded Doko V1
reconstruction. It orders proposals by observation time, uses identity probabilities to rank card
choices, limits each of the 20 deck identities to two copies, follows the selected trick leader and
winner, and checks each completed round against clockwise play, following-category rules, and the
40-card deck.

The stage records the automatic context from the recording ID and session: stable game and round
IDs, `player-1` through `player-4`, `dealer-unspecified`, and `player-1` as first-trick leader. These
are 0105 execution defaults. They do not describe confirmed gameplay facts.

Each analysis has its own directory under `.device/stages/round-analysis/<analysis-id>/`. It stores
`request.json`, `result.json`, and `run.log`. A preflight or input error stores `failure.json` and
the error log. Results retain source revision IDs, hypotheses, selected and inferred plays, trick
winners, search counts, truncation state, and elapsed time. Existing results are not overwritten by
a new analysis.

## Verification

- Six focused tests pass. They cover the 40-play `unambiguous.json` card sequence, ten trick outputs,
  empty observations, impossible duplicate-deck evidence, missing session context, lineage mismatch,
  failure retention, and reload of a saved result.
- The complete Release Swift package suite passed 161 tests with 2 existing reference tests skipped
  because their frozen external model inputs were not set.
- The iPhone 18 Pro Simulator build on iOS 27.2 passed.
- `swift-format` lint and `git diff --check` pass for the new Swift sources.

## Limits

This is the bounded on-device reconstruction path for the PoC. The iOS search currently ranks
identity candidates and validates Doko play rules. It does not yet port Python's ignore-proposal
branches, visual evidence weights, tracklet evidence, pile handling, or correction constraints. Its
result is not a Python parity or gameplay-accuracy claim. M13 must compare the same saved inputs with
the 0105 local workflow and report these differences. No iPhone runtime or resource result is
claimed.
