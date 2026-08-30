# DokoDetector Round Reconstruction — Non-streaming Integration Harness

## Plan status

- **Summary:** Reproducibly assemble stored table observations into one explicit round input and
  record a round-reconstruction result.
- **Status:** Closed
- **Depends on:** Plan 0006 contracts and rules core; the existing `table-observation/v1` producer
  and backend persistence path.
- **Closure reason:** Complete
- **Closure note:** Implemented all seven phases, including deterministic local artifacts, the
  analyzer-to-persistence integration path, and four harness scenario outcomes.
- **Builds on:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md) and
  [Plan 0023](../0-to-specify/0023-Game_Reconstruction_Development.md).

## Milestone status

- **M0 (phase 1):** Complete — strict request and result contracts with canonical serialization.
- **M1 (phase 2):** Complete — deterministic observation loading, validation, ordering, and input
  assembly.
- **M2 (phase 3):** Complete — engine-result serialization with source provenance.
- **M3 (phase 4):** Complete — atomic artifact publication and the `doko reconstruct round` command.
- **M4 (phase 5):** Complete — analyzer-to-backend-persistence-to-harness integration fixture.
- **M5 (phase 6):** Complete — separate observation files adapted from the game-engine fixtures,
  covering resolved, ambiguous, incomplete, and impossible harness outcomes. The incomplete case
  includes an `insufficient_evidence` observation.
- **M6 (phase 7):** Complete — local command, request, artifact, error, and ambiguous-result
  inspection documentation.

## 1. Goal

Build a local, non-streaming integration harness for one round. The harness reads a fixed set of
stored table observations, combines them with explicit round setup, runs the existing reconstruction
oracle, and writes reproducible artifacts.

This work proves the analyzer-to-round boundary with persisted observation bytes. It does not make
a table observation into a card play.

## 2. Scope

Add the `doko reconstruct round --request <path>` command to the `operations` package. The command
must:

1. Read canonical `table-observation/v1` documents from explicit local file paths. A backend-stored
   observation uses
   `<runtime-root>/table-observations/<observation-id>/observation.json`.
2. Read explicit round setup with the game ID, round ID, ruleset, deck variant, active players,
   dealer, and first trick leader.
3. Validate every source document with `game_engine.parse_observation_bytes`.
4. Reject duplicate observation IDs and mixed session IDs.
5. Require the request list to have strictly increasing `session.event_sequence` values and
   nondecreasing `observed_at_ms` values. Do not sort invalid input. Report the two list positions
   and the conflicting values.
6. Construct and validate one `round-reconstruction-input/v1` value without changing source bytes.
7. Run `reconstruct_round` with the three search limits from the request.
8. Publish canonical `input.json` and `result.json` artifacts together.
9. Return `resolved`, `ambiguous`, `incomplete`, and `impossible` as successful data outcomes.
   Invalid requests, invalid source data, and file-system errors are command failures.

The request selects the observations for the round. The harness validates their contract, session,
identity, and order. It does not infer or verify round membership because `table-observation/v1`
does not contain a round ID.

## 3. Non-goals

- Streaming, incremental, or event-by-event reconstruction.
- Reading observations from HTTP or querying backend database metadata.
- Backend API changes, background jobs, or a persistent reconstruction service.
- Automatic round detection, player identification, dealer inference, or first-leader inference.
- Game assembly, dealer rotation, round scoring, game scoring, or session continuation.
- New game rules, visual capabilities, calibration claims, or changes to `table-observation/v1`.
- Human review UI or correction workflows.
- A new reconstruction algorithm or changes to the engine result semantics.

## 4. Request contract

Define a strict `round-reconstruction-run/v1` JSON object in `operations`. Reject unknown fields.
It has this shape:

```json
{
  "schema_version": "round-reconstruction-run/v1",
  "run_id": "example-round-01",
  "round_setup": {
    "game_id": "game-01",
    "round_id": "game-01-round-01",
    "ruleset": {"name": "doko-normal", "version": "v1"},
    "deck_variant": "doko-40-v1",
    "active_players": ["player-01", "player-02", "player-03", "player-04"],
    "dealer": "player-04",
    "first_trick_leader": "player-01"
  },
  "observation_paths": [
    "observations/observation-001.json",
    "observations/observation-002.json"
  ],
  "search": {
    "max_missing_plays": 1,
    "max_hypotheses": 256,
    "max_search_nodes": 250000
  },
  "output_root": "artifacts/round-reconstruction"
}
```

Use the identifier restrictions from the game-engine contract for `run_id`. Require at least one
observation path. Require unique path strings. Resolve relative observation paths and `output_root`
from the request file's parent directory. The command must not depend on the current working
directory.

Use the same bounds as `reconstruct_round`: `max_missing_plays` is nonnegative, and
`max_hypotheses` and `max_search_nodes` are positive. Do not add implicit defaults to the request.

## 5. Artifact contract

Write artifacts to `<output_root>/<run_id>/`. Fail if that path already exists. First write both
files in a new sibling staging directory. Rename the staging directory to the final path only after
both files are complete. Remove the staging directory after an expected failure.

`input.json` is the canonical game-engine serialization of the assembled
`round-reconstruction-input/v1` value.

`result.json` is a strict `round-reconstruction-result/v1` object owned by `operations`. It
contains:

- `schema_version`, `run_id`, and the `operations` package version;
- the canonical request SHA-256;
- one source record per request entry, in request order, with the request path string,
  `observation_id`, byte length, and source-byte SHA-256;
- the three requested search limits;
- the full engine status, hypotheses, focused decisions, and diagnostics.

Serialize `result.json` as finite UTF-8 JSON with sorted keys and stable separators. Do not include
timestamps, absolute paths, elapsed time, host data, or generated confidence values. Preserve the
engine's list order. These rules make both artifact files byte-identical for identical request
content and source bytes in equivalent clean output roots.

Do not rewrite, copy, or normalize the source files. Calculate each source digest from the bytes
that are passed to the parser. Calculate the canonical request digest after parsing and validation,
so insignificant request formatting does not change it.

## 6. Errors and command behavior

Use exit code `0` for all four engine result statuses. Print the final artifact directory and result
status to standard output.

Use exit code `2` for request parsing, contract, source, grouping, ordering, and
artifact-publication errors. Print one concise error to standard error. Include the field or path
and the conflicting values when available. Do not leave a final run directory after a failed
command.

## 7. Delivery steps

1. Add strict request and result models, canonical serialization, and focused contract tests.
2. Add deterministic source loading, digest calculation, grouping checks, ordering checks, and
   round-input assembly.
3. Add engine-result serialization without changing the engine package.
4. Add atomic artifact publication and the `doko reconstruct round` command.
5. Add an integration fixture that passes an analyzer-produced observation through
   `TableObservationPersister`, reads its persisted `observation.json`, and runs the harness.
6. Adapt the existing game-engine scenario fixtures into separate observation files for
   `resolved`, `ambiguous`, `incomplete`, and `impossible` harness runs. Include one incomplete run
   with an `insufficient_evidence` observation.
7. Document the local command, request file, artifact fields, error behavior, and ambiguous-result
   inspection.

## 8. Acceptance criteria

- One command reconstructs a round from persisted `table-observation/v1` bytes and explicit round
  setup.
- The game engine has no runtime import from the analyzer or operations packages.
- The output contains canonical `input.json` and deterministic `result.json`. Source observations
  remain byte-for-byte unchanged.
- Repeated fixture runs in clean output roots produce byte-identical artifacts.
- The harness rejects duplicate IDs, mixed sessions, and invalid ordering before it calls the
  engine. Tests assert the reported conflicting values.
- Tests cover the analyzer-to-backend-persistence-to-harness-to-engine path and all four engine
  result statuses.
- Tests cover an existing target directory and verify that a failed run leaves no final directory.
- The operations and game-engine tests and their Ruff checks pass locally through `mise exec`.

## 9. Completion direction

Close this epic when the harness provides a reproducible round-level integration path and its
fixture corpus passes. Benchmark fixture runs separately so elapsed time does not make the result
contract nondeterministic. Use runtime, search truncation, ambiguity, missing-observation, and
source-quality measurements to specify the next scalable reconstruction work in Plan 0023.
