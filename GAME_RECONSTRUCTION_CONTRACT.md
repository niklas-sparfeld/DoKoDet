# DokoDetector game-reconstruction contracts

This document freezes the M0 boundary between the TableEvidenceAnalyzer and game reconstruction.
The contracts use strict JSON objects. Unknown fields are invalid. The canonical serializer uses
UTF-8, sorted keys, compact separators, ASCII escaping, and no non-finite numbers.

## Shared card data

The shared card set is `doko-german-suited-v1`. It contains 24 visual card identities. The canonical
round uses `doko-40-v1`:

- ranks: Jack, Queen, King, Ten, and Ace;
- two physical copies of every visual identity;
- 40 physical cards;
- 40 card plays;
- 10 tricks with four card plays each.

The manifests are:

- [`fixtures/game-engine/v1/card-set.json`](fixtures/game-engine/v1/card-set.json);
- [`fixtures/game-engine/v1/decks/doko-40-v1.json`](fixtures/game-engine/v1/decks/doko-40-v1.json).

The 48-card manifest remains shared card data. It is not a canonical round for this contract.

## `table-observation/v1`

One table observation is uncertain visual evidence from one bounded point in an ordered stream. It
does not assert that a card was played.

```json
{
  "schema_version": "table-observation/v1",
  "observation_id": "observation-001",
  "source": {
    "package_id": "package-001",
    "snippet_part_name": "event_snippet"
  },
  "session": {
    "session_id": "session-001",
    "event_sequence": 1
  },
  "observed_at_ms": 42125,
  "status": "observed",
  "capabilities": ["identity_candidates"],
  "cards": [
    {
      "observed_card_id": "observation-001-card-01",
      "identity_candidates": [
        {"card": "HEARTS_TEN", "probability": 1.0}
      ]
    }
  ],
  "calibration": "fixture",
  "analyzer": {"name": "synthetic", "version": "synthetic-v1"},
  "diagnostics": {}
}
```

Top-level fields are:

| Field | Rule |
| --- | --- |
| `schema_version` | Always `table-observation/v1`. |
| `observation_id` | Unique simple identifier for this observation. |
| `source` | Contains `package_id` and an optional `snippet_part_name`. |
| `session` | Contains `session_id` and a positive `event_sequence`. |
| `observed_at_ms` | Non-negative time in the source session. |
| `status` | `observed` or `insufficient_evidence`. |
| `capabilities` | Unique capabilities in the order defined below. |
| `cards` | Zero or more anonymous observed-card proposals. |
| `calibration` | `fixture`, `uncalibrated`, or `calibrated`. |
| `analyzer` | Non-empty analyzer `name` and `version`. |
| `diagnostics` | A finite JSON object. It is not gameplay state. |

An `observed` result with `cards: []` means that no card proposal was reported. It does not prove
that the table was empty. An `insufficient_evidence` result must have no cards. These outcomes are
not interchangeable.

Each observed card has an anonymous `observed_card_id` and at least one ranked
`identity_candidates` entry. A candidate contains a visual `card` identity and a positive finite
`probability`. Candidates are unique, ordered from highest to lowest probability, and sum to one
within an absolute tolerance of `0.000001`. The probabilities are conditional on the observed-card
proposal representing a card. They do not identify a physical copy.

The identity-only capability is required in V1. The full capability order is:

1. `identity_candidates` — ranked visual identities;
2. `presence_score` — evidence that the proposal represents a card;
3. `newly_visible_score` — evidence that the card became newly visible;
4. `active_area_score` — evidence that the card is in the active table area;
5. `association_candidates` — uncertain links to observed cards in another observation;
6. `card_tracklets` — an uncertain short-term tracklet identifier.

Optional capabilities are additive. When a capability is declared, its field is present on every
observed card, including a score of `0.0` or an empty association list. When it is not declared, its
field is absent. An absent field is unavailable evidence. It is not a zero score. All scores are in
the inclusive range from zero to one. They are not calibrated probabilities unless the calibration
label and held-out measurements support that claim.

The analyzer contract has no player, turn, legal-move, trick, deck-count, card-play, or game-state
field. `observed_card_id` and `card_tracklet_id` identify visual evidence only. They are not
physical-card identifiers.

## `round-reconstruction-input/v1`

This contract adds game and round setup around an ordered list of table observations:

```json
{
  "schema_version": "round-reconstruction-input/v1",
  "game_id": "synthetic-game-001",
  "round_id": "synthetic-game-001-round-01",
  "ruleset": {"name": "doko-normal", "version": "v1"},
  "deck_variant": "doko-40-v1",
  "active_players": ["player-01", "player-02", "player-03", "player-04"],
  "dealer": "dealer-01",
  "first_trick_leader": "player-01",
  "observations": []
}
```

The reconstruction input has exactly four unique active players. The dealer may sit out the round.
The first trick leader must be active. Observations are unique and ordered by `observed_at_ms`.
The input does not contain private physical-card identifiers.

The M0 contract freezes only `doko-40-v1` and `doko-normal/v1`. Reconstruction derives the hand
size, play count, and trick count from the deck manifest. It must not hard-code a 40-card count in
place of the manifest.

## Scenario fixture

[`fixtures/game-engine/v1/rounds/unambiguous.json`](fixtures/game-engine/v1/rounds/unambiguous.json)
uses `round-scenario/v1`. It contains:

- `input`: one reconstruction input with 40 exact identity-only observations;
- `enabled_capabilities`: the capabilities used by the input;
- `ground_truth`: private synthetic physical-copy assignments for tests only;
- `expected`: the expected result status and manifest-derived trick count.

Only `input` crosses the analyzer boundary. The private ground truth never appears in a table
observation. Later milestones add the ambiguous, impossible, incomplete, occlusion, side-card, and
human-corrected scenarios without changing these contracts.

## Ownership

The analyzer-side model is in
[`vision_detector/src/vision_detector/table_observation.py`](vision_detector/src/vision_detector/table_observation.py).
The reconstruction-side model is in
[`game_engine/src/game_engine/contract.py`](game_engine/src/game_engine/contract.py).
Both sides parse the exact shared fixture and compare canonical semantic JSON. Neither side imports
the other's runtime package.
