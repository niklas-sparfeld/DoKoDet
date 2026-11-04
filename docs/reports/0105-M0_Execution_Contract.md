# Epic 0105 M0: Execution Contract

Date: 2026-11-04

## Decision

Build one recording-scoped run from the existing retained processor services. The run must freeze
every request and exact input revision before it schedules a stage. It must create new processor
runs and outputs for a new pipeline run. A resumed run may attach to its unchanged active processor
request and reuse completed stages only when the request digest and resolved input revisions still
match.

The 0090 coordinator is a useful local execution reference, not the web implementation. It stores
its manifest under a local runtime directory and runs in the CLI process. The workspace currently
has read-only status and per-stage start actions. M1 must add a recording-scoped start/status service
and durable overall run record. A worker must continue if the browser closes. Existing processor
runs, data revisions, calibration and scene artifacts, and round analyses remain the source of
stage results.

## Stage contract

| Order | Stage | Frozen input | Retained output and next use |
| --- | --- | --- | --- |
| 1 | Event proposals | Recording video identity and selected local provider, model, threshold, decoder, and extraction settings | Complete `events` revision. Its event frames feed visible-card detection. |
| 2 | Visible-card and pile proposals | Event revision from this run and frozen detector configuration | Complete `visible_cards` revision. It feeds calibration/scene proposals and identity proposals. |
| 3 | Calibration and proposed card scenes | Visible-card revision from this run and frozen automatic geometry settings | Calibration run and any published calibration and proposed-scene outputs. These remain inspectable in the existing scene/calibration views. A calibration fit candidate is diagnostic and cannot substitute for a published calibration. |
| 4 | Visual identity proposals | Visible-card revision from this run; use the configured automatic predicted-visible-region crop policy and local classifier | Complete `visual_identities` revision, visible in the identity workspace. Never use a review draft or selected reviewed geometry as an automatic crop input. |
| 5 | Table observations | Exact event, visible-card, and identity revisions from this run | Complete `table_observations` revision, visible in the observation workspace. |
| 6 | Round analysis | Observation revision from this run, recording session, explicit round context, rules version, and frozen search limits | Saved round analysis, visible in the analysis workspace. |

The card-scene stage is required. Identity crops use the supported automatic detector geometry path;
they do not depend on human review or on generated card poses. This keeps identity inference
possible when card-scene output is complete. If calibration cannot publish a calibration, or a
required scene result is partial or failed, stop the run at stage 3. Do not label the run complete
or silently skip the stage.

## Empty outputs and failures

- A complete empty event revision is a valid output. Continue to visible-card detection with that
  exact revision. The detector must return a complete output revision, including an empty one, for
  the run to continue.
- A complete empty visible-card revision is valid for identity inference. The identity processor
  must return a complete empty revision. Calibration/scene processing must also return a complete
  result; missing calibration or a partial scene result stops the run.
- A complete empty identity revision is a valid input to observation assembly. Assembly must return
  a complete observation revision. Preserve a valid empty observation revision, but round analysis
  cannot complete from it because analysis requires observations. Record that as a stage-6 failure
  with its cause; do not report overall completion.
- A processor `partial`, `failed`, invalid, or missing output is a blocking failure. Preserve all
  completed run records and revisions, stop dependent stages, and show the failed stage and cause.
- A cancellation or process interruption preserves the overall manifest and current processor run
  ID. Resume attaches to that request. If a frozen request or upstream revision changes, create a
  new processor run for the affected stage and every dependent stage. Keep prior results intact.

## Preflight, concurrency, and start behavior

Before accepting a start, validate the recording video and source digest; local provider and model
availability; required stage configuration; and round/session context, rules version, and search
limits. Verify that the round context belongs to the recording session and has the required player,
dealer, and first-trick facts. Do not infer missing facts. Return all actionable blockers and start
no work when preflight fails. Do not accept staged activity or a recording without a valid round
setup as a complete-pipeline run.

Freeze the normalized requests, provider/model identities, configuration, source digest, and any
initial inputs in the durable overall record. Resolve later-stage inputs only from outputs of this
run. Never read a maintained reference, review draft, or selected completed reference as an automatic
stage output. A fresh start always creates fresh processor run IDs; a client retry with the same
start key returns the existing overall run. Permit one active run per recording. Return the active
run on duplicate start; reject a different concurrent start with an actionable conflict. Preserve
completed runs and drafts without overwriting them.

## Fixture and acceptance

Use a deterministic local backend fixture, not model training or the old 0090 model campaign. The
fixture must have one accepted recording video, fixed local fake providers for each model stage,
reviewable event/card/identity revisions, a calibration and scene result, a non-empty observation
revision, and explicit valid round context. It must retain outputs through the same stores and
workspace reads as ordinary stage runs. Add variants for preflight failure, duplicate start,
complete empty event/card/identity output, calibration failure, partial scene output, failed stage,
empty observations, interruption/resume, and changed frozen input.

Acceptance follows one start through all six stages. Each downstream request names the exact
upstream output revision IDs; each output appears in its existing workspace view; round analysis
persists; and status remains readable after browser navigation and backend worker restart. A
successful execution claims only that all stages completed. It makes no claim that proposals,
observations, or reconstruction are correct.

## M0 result

M0 is complete. M1 can implement the overall run boundary and preflight around this contract. M2
must retain interruption and restart safety. M3 must expose all prerequisites before the single
start action and restore progress and links after reload. M4 must verify the full fixture path and
record its reproducible setup.
