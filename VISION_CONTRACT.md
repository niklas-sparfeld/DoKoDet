# DokoDetector Vision Result Contract V1

This document defines the boundary between visual evidence and later game reconstruction.

> **Transition status:** This contract documents the current local PoC from closed plan 0005. It is
> not the target architecture. [Plan 0006](docs/plans/2-ready/0006-GameEngine_v1.md) replaces it with
> `table-observation/v1`, produced by the deployment-neutral `TableEvidenceAnalyzer`. Do not extend
> this contract or maintain both undeployed runtime paths. See
> [Table Observation and Game Reconstruction](docs/TableObservationReconstruction.md).

## Schema and shared card data

The result schema version is `vision-detection/v1`. The canonical result fixtures are:

- `fixtures/vision/v1/example-ranked.json`
- `fixtures/vision/v1/example-abstained.json`

The shared card configuration is in `fixtures/game-engine/v1/`:

- `card-set.json` lists the 24 visual identities;
- `decks/doko-40-v1.json` defines five ranks, two physical copies, and 40 plays;
- `decks/doko-48-v1.json` defines six ranks, two physical copies, and 48 plays.

`HEARTS_QUEEN` means one visual identity. It does not identify which of the two physical copies was
seen.

## Result shape

Every result has these fields and no other top-level fields:

| Field | Type | Rule |
| --- | --- | --- |
| `schema_version` | string | Always `vision-detection/v1`. |
| `result_id` | UUID string | Unique identity for this immutable result. |
| `package_id` | UUID string | Accepted evidence package that produced the result. |
| `session` | object | Contains only `session_id` and positive `event_sequence`. |
| `status` | string | `confident`, `uncertain`, `no_card_found`, or `insufficient_evidence`. |
| `selected_card` | card or null | Set only for `confident`; it equals the first candidate. |
| `candidates` | array | Ranked unique candidates, or empty for an abstention. |
| `calibration` | string | `fixture`, `uncalibrated`, or `calibrated`. |
| `detector` | object | Non-empty `name` and `version`. |
| `diagnostics` | object | Bounded `frames_received` and `frames_decoded` counts. |
| `observations` | array | Optional bounded diagnostic JSON objects. |
| `created_at` | UTC timestamp | Serialized in UTC with millisecond precision and a `Z` suffix. |

Candidate probabilities are positive, finite numbers. They are ordered from highest to lowest and
sum to `1.0` within an absolute tolerance of `0.000001`. Every candidate must be one of the visual
identities in the shared card set. A non-empty candidate list is required for `confident` and
`uncertain`. Both abstention statuses use an empty list and `selected_card: null`.

`fixture` values are deterministic test controls. They are not calibrated recognition confidence.
`uncalibrated` values can rank candidates but are not empirical confidence claims.

The Python domain package serializes valid results as UTF-8 JSON with sorted keys, compact
separators, ASCII escaping, and `allow_nan=false`. Consumers must preserve this raw result when
later game rules select another candidate.

## Detector input boundary

The detector input contains only:

- `package_id`;
- `event_time_ms`;
- frame `part_name`, event-relative `actual_offset_ms`, dimensions, and either immutable JPEG
  bytes or a read-only local reference.

It does not contain session identity, event sequence, client or device metadata, CardEventNet
metadata or score traces, decoder configuration, player identity, seats, turn order, legal moves,
or game state. Those values belong to orchestration or the game engine.

Detector adapters must normalize logits, distances, or other internal scores before creating a
result. An invocation or persistence error is an operational error, not
`insufficient_evidence`.

## Scripted detector

The local scripted detector is test control code. It reads the checked-in package-ID mapping at
`fixtures/vision/v1/scripted-results.json` and returns the mapped result template. It does not
decode JPEG bytes or claim visual recognition. An unmapped package returns `insufficient_evidence`,
with `calibration: fixture`, detector name `scripted`, and `frames_decoded: 0`.
