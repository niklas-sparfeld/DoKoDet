# Round recording analysis PoC

## Plan status

- **Summary:** Let an operator record one round in the iOS app, then show the backend analysis
  progress and reconstruction result.
- **Status:** In Progress
- **Depends on:** Completed Plan 0031.
- **Boundary:** This is a local, foreground-polling proof of concept. It reuses the current live
  preview, evidence-package, and repository-bundle paths. One recording owns both the complete
  video and its evidence packages. The app does not create evidence packages outside a recording.

## Milestone status

- **M0:** Complete — freeze the reusable reconstruction and PoC analyzer boundaries.
- **M1:** Complete — add the backend analysis contract, persistence, restart conversion, and
  artifact storage.
- **M2:** Complete — add the backend worker, lifecycle handling, and APIs.
- **M3:** Complete — make one iOS recording own video, evidence, lineage, and package tracking.
- **M4:** Pending — add iOS upload gating, durable analysis submission, and polling.
- **M5:** Pending — add the result UI, end-to-end fixtures, and local documentation.

## 1. Outcome

An operator can start and stop a **round recording** from the Record view. Start creates one
recording workflow. That workflow creates the existing complete recording bundle and all evidence
packages for the recording. Live preview and model readiness can exist before Start, but they do
not persist evidence packages. Stop closes evidence creation and the complete recording together.

After the operator stops the round recording and its recording bundle and evidence packages are
acknowledged, the app requests one backend round analysis. The backend analyzes the selected
evidence packages, reconstructs the round with the Plan 0031 integration path, and retains a
small status and result record. The app polls that record and displays its current stage and final
result.

Use *round recording* for this feature. A recording remains one uninterrupted capture and is not
the canonical Round. The round reconstruction is an analysis result, not a reviewed
reconstruction.

## 2. Fixed PoC decisions

1. Reuse `TrainingRecordingCoordinator`, `EvidencePackageCoordinator`, their durable upload
   queues, and the current repository-bundle and evidence-package APIs. Treat them as internal
   parts of one recording workflow. Do not expose or retain a separate evidence-recording mode.
   Do not add another camera pipeline, upload protocol, media type, or source bundle.
2. Start evidence-package creation only when the recording starts. Give both coordinators the same
   recording ID and the selected profile's canonical session ID. Round-recording profiles must use
   the UUID session form that the existing evidence contract accepts. Snapshot the recording ID
   when an event sequence is reserved, and write it to the package's existing
   `parent_recording_id` lineage field. Stop must close the evidence membership boundary, finalize
   events already reserved for the recording, clear the active recording ID, and prevent later
   live events from joining the stopped recording. The app keeps the ordered IDs of the packages
   created within that boundary.
3. Add only the round setup that Plan 0031 requires: game ID, four fixed seat IDs
   (`seat-1` through `seat-4`), dealer, and first trick leader. Generate the round ID from the
   recording ID. The Record view provides dealer and first-leader pickers; it uses the selected
   real-game profile's game ID. Do not add player management, dealer rotation, or game assembly.
4. The app requests analysis only after the recording bundle and every associated evidence package
   have received successful backend acknowledgements. Stopping the recording starts this chain;
   the operator does not select or upload evidence again.
5. Use a backend process-local, single-worker queue. Persist the analysis row and terminal result
   in SQLite, but do not implement resumable work. On backend startup, change a non-terminal row
   to `failed` with a clear restart error. The app can start a new analysis by recording again.
6. Use polling, not WebSockets, push notifications, background iOS execution, or server-sent
   events. Poll every second while the Record view is visible and an analysis is non-terminal.
7. Keep the Plan 0031 result semantics. `resolved`, `ambiguous`, `incomplete`, and `impossible`
   are successful analysis results. Upload, analyzer, contract, and internal errors are `failed`.
8. Keep the analyzer replaceable through the existing `TableEvidenceAnalyzer` protocol. For this
   PoC, configure a deterministic local analyzer that consumes the accepted package and emits a
   valid `insufficient_evidence` table observation. This makes the real recording flow reproducible
   without claiming a recognition capability that Plan 0022 has not established. Tests can inject
   deterministic analyzers for all four reconstruction outcomes. A measured analyzer replaces this
   PoC implementation later without changing the analysis API or worker.

## 3. Backend contract and persistence

Add a `round_analyses` SQLite table and Alembic migration. Each row contains:

- immutable IDs: `analysis_id`, `recording_id`, `round_id`, and `session_id`;
- canonical request JSON and SHA-256, including explicit round setup, ordered evidence package
  IDs, and the three Plan 0031 search limits;
- state: `queued`, `analyzing_evidence`, `reconstructing`, `complete`, or `failed`;
- progress counts: total and completed evidence packages;
- result status and canonical result JSON for `complete`, or a short safe error for `failed`;
- created, started, and completed timestamps.

Add these JSON APIs:

| Method and path | Purpose | Response |
| --- | --- | --- |
| `POST /v1/round-analyses` | Create one analysis request after uploads finish. | `202` status document with `analysis_id`. |
| `GET /v1/round-analyses/{analysis_id}` | Read state, stage, counts, and terminal result. | Same status document. |

Before submission, the app allocates and durably stores an `analysis_id`. The create request
contains that analysis ID, the recording ID, round setup, ordered evidence package UUIDs, and
explicit Plan 0031 search limits. Reject unknown fields, duplicate package IDs, an empty list,
unknown packages, a package whose stored lineage does not name the recording, mixed sessions,
and a recording bundle that is not stored. A repeated request with the same `analysis_id` and
canonical input returns the existing analysis. Reuse of that ID with different canonical input is
a conflict. This is the idempotency boundary for a response lost before the app stores it.

The result is a compact API model, not a new source artifact: analysis ID, terminal status,
reconstruction status, hypotheses, focused decisions, diagnostics, and the IDs and hashes of the
Plan 0031 `input.json` and `result.json` artifacts. Store those artifacts under a new disposable
runtime root, atomically, using the existing Plan 0031 serialization. Do not copy or mutate
accepted evidence packages or repository bundles.

Add a small backend analysis service that, for each request, runs the configured
`TableEvidenceAnalyzer` once per requested package, persists or reuses its immutable table
observation, then invokes the reusable non-CLI Plan 0031 orchestration code. Extract that code
from the completed `doko reconstruct round` path into an operations library entry point that
accepts validated values and explicit source and output paths; the command and the backend must use
the same assembly, engine invocation, publication, and serialization code. Add `doko-operations`
as an explicit backend dependency. Do not duplicate round-input validation or
reconstruction-result conversion in the backend.

The app lifespan owns the worker. Start it after repositories and storage are ready, and stop it
cleanly during shutdown. Add a test-only synchronous worker hook so API tests do not depend on
timing.

## 4. iOS flow

Rename the visible training-recording controls and states for this path to **round recording**;
keep the existing implementation types where that avoids a broad rename. The Record view must:

1. Require a complete real-game collection profile, a live preview, a ready model, and a connected
   backend before Start is enabled. Require the profile session ID to be a UUID accepted by the
   existing evidence contract. The live preview does not own a persisted evidence session.
2. Show the two round-setup pickers before recording. Preserve their values while the view stays
   open and disable them during capture and analysis.
3. On Start, allocate the existing recording ID, save the round setup and an empty ordered evidence
   ID list in durable app state, create the recording capture context from the profile session ID,
   start both recording components with the same recording and session IDs, and enable evidence
   creation.
4. On each evidence-package persistence callback, read the persisted package ID and lineage. Append
   that package ID only when its snapshotted lineage names the active recording. On successful
   upload acknowledgement, mark that ID acknowledged.
5. On Stop, close the recording's evidence membership boundary, finalize its reserved events, and
   finalize the complete recording. Once the recording bundle and all collected evidence IDs are
   acknowledged, allocate and persist the analysis ID and submit `POST /v1/round-analyses`. If an
   upload fails, show the existing retry control and do not submit early. If the recording contains
   no evidence packages, show `No evidence packages captured` as a terminal local failure and do
   not submit an invalid analysis request.
6. Show `Waiting for uploads`, `Queued`, `Analyzing evidence 3 of 8`, `Reconstructing`,
   `Complete`, or the failed message. A completed result shows its reconstruction status plus a
   concise summary: resolved hypothesis, ambiguity count, or the engine diagnostics. Keep the
   full JSON out of the first PoC UI.

Persist the pending round-analysis submission and analysis ID beside the current recording queue
metadata so an app relaunch resumes polling or submits only after all acknowledgements. Do not
support multiple simultaneous round recordings or a history screen in this epic.

## 5. Delivery milestones

### M0 — Reusable reconstruction and analyzer boundary

- Extract a value-based orchestration entry point from the completed Plan 0031 command path.
- Add the explicit backend dependency and deterministic local PoC analyzer configuration.
- Keep the command behavior and deterministic artifact bytes unchanged.

#### M0 implementation evidence — 2026-08-30

- Added `run_round_reconstruction_values` and explicit-path observation loading in
  `doko_operations`. The existing request-file command delegates to this entry point, and tests
  verify identical input and result artifact bytes.
- Added the deterministic local analyzer with fixed `deterministic-local`/`v1` identity. It emits a
  valid `insufficient_evidence` table observation and is configured on the backend application.
- Declared `doko-operations` as a backend dependency and aligned local analyzer package sources in
  both lockfiles.
- Verification: full operations and backend test suites, Ruff checks, and both lock checks pass.

### M1 — Analysis contract and persistence

- Add strict create, status, and result models with the client-generated `analysis_id`.
- Add the migration, repository methods, restart conversion, and atomic runtime artifact storage.

#### M1 implementation evidence — 2026-08-30

- Added strict `round-analysis/v1` create, status, and compact result models. Canonical create
  request bytes and their SHA-256 include the explicit round setup, ordered package IDs, and all
  three Plan 0031 search limits.
- Added the `round_analyses` Alembic migration and repository lifecycle methods for queued,
  analyzing, reconstructing, complete, and failed rows. Backend creation converts interrupted
  non-terminal rows to a clear restart failure.
- Added atomic runtime publication for exact `input.json` and `result.json` bytes below
  `.runtime/round-analyses` and wired its directory into readiness checks.
- Added focused contract, repository, storage, migration, and startup regression tests.
- Verification: full backend and operations test suites, Ruff checks, both lock checks, and diff
  whitespace checks pass. The existing backend repository-wide format check still reports one
  unrelated pre-existing assertion layout in `tests/test_table_observation_pipeline.py`.

### M2 — Worker and APIs

- Implement the lifespan-owned single worker and its clean shutdown behavior.
- Add the two routes, synchronous test hook, validation, idempotency, and failure handling.

#### M2 implementation evidence — 2026-08-30

- Added the lifespan-owned process-local queue and one worker task. The worker analyzes each
  selected package once through the configured analyzer runner, reuses immutable observations, and
  drains queued work during clean shutdown.
- Added `POST /v1/round-analyses` and `GET /v1/round-analyses/{analysis_id}` with strict request
  handling, recording/package/session/lineage validation, canonical idempotency conflicts, and
  compact terminal results.
- Added the synchronous test hook, safe terminal worker failures, and an integration test for the
  analyzer-to-observation-to-Plan-0031 artifact path. Runtime artifacts retain the exact Plan 0031
  input and result bytes with their hashes.
- Verification: full backend tests, focused API/worker tests, Ruff checks, lock checks, and
  whitespace checks pass.

### M3 — Unified iOS recording

- Make Start and Stop own both complete-video and evidence-package creation.
- Add snapshotted lineage, the shared session invariant, the stop boundary, and durable package
  tracking.

#### M3 implementation evidence — 2026-08-30

- Added the fixed real-game round setup contract with four seat IDs, dealer, first trick leader,
  recording-derived round ID, and a durable ordered package and acknowledgement state file.
- Made the live preview in-memory only. Start now resets the preview buffers, uses the profile UUID
  as the shared capture session ID, saves round state before starting both coordinators, and creates
  evidence packages only for the active recording.
- Snapshotted the recording ID when evidence reserves an event sequence. Persisted packages carry
  that recording in the existing lineage document. Stop closes membership, finalizes pending
  evidence and the complete recording, and blocks later live events from joining it.
- Added Record view setup pickers, round-profile validation, locked controls, Xcode target wiring,
  and focused iOS core tests for setup, persistence, lineage, and the start boundary.
- Verification: focused round-recording tests and the iOS Simulator Xcode build pass. The Swift
  package suite still reports four baseline failures: two evidence-manifest contract checks, one
  package-fixture date-precision equality check, and one live-video timing fixture check.

### M4 — Analysis submission and polling

- Add upload acknowledgement gating and the empty-evidence terminal state.
- Add the client-generated analysis ID, durable idempotent submission, relaunch recovery, and
  foreground polling.

### M5 — Result UI and end-to-end verification

- Add the concise result and failure UI, including the empty-evidence outcome.
- Extend deterministic local fixtures and document the flow, endpoints, polling behavior, PoC
  analyzer limitation, and backend restart limitation.

## 6. Tests and acceptance criteria

Add focused tests before each implementation change where practical.

- Backend API tests cover request validation, idempotent creation, lineage and session rejection,
  each progress state, worker failure, terminal result retrieval, and restart conversion of
  non-terminal work to `failed`.
- An integration test uploads one recording bundle and its linked evidence fixture, drives the
  worker synchronously, and verifies the analyzer-to-observation-to-Plan-0031 artifact path.
  Cover `resolved`, `ambiguous`, `incomplete`, and `impossible` as completed outcomes.
- iOS unit tests cover round setup validation, the shared recording and session identity, the
  evidence start and stop boundary, snapshotted lineage, package ordering, acknowledgement gating,
  the empty-evidence outcome, durable relaunch recovery, polling state transitions, terminal
  rendering data, and retry after an upload failure. Extend the existing local-pipeline test with
  a deterministic analysis status fixture.
- An operator can start one round recording, stop it, and see a terminal backend reconstruction
  result without manually handling evidence packages.
- The backend performs no analysis before all selected uploads are acknowledged and never changes
  accepted source bytes.
- Existing evidence capture, training-recording bundle, upload queue, analyzer, Plan 0031,
  backend, and iOS tests remain green. Run their relevant tests plus Ruff and Swift package/Xcode
  checks through `mise exec`.

## 7. Non-goals

- Automatic round boundaries, round setup inference, player identity, dealer rotation, game
  assembly, scoring, correction, or review.
- Streaming or live partial reconstruction.
- Background transfers, background iOS analysis tracking, push updates, WebSockets, or resume of
  interrupted backend analysis.
- Production job infrastructure, parallel workers, retention policy, authentication, or cloud
  deployment.
- A new evidence, recording, table-observation, or reconstruction contract.
- Evidence-package creation outside an active recording.

## 8. Completion direction

Close this epic when a local iOS simulator or device can complete the stated start-to-terminal
flow against the local backend, the deterministic fixture coverage passes, and the restart
limitation is documented. Use measured upload, analysis, and reconstruction durations plus failure
rates to decide whether durable jobs, push progress, or more round setup automation are justified.
