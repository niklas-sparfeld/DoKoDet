# Active pipeline module cleanup

## Plan status

- **Summary:** Split large, frequently changed pipeline modules by responsibility. Move focused
  tests with each owner. Reduce the source and test context needed for a normal change.
- **Status:** Blocked
- **Depends on:** [0108 M11](../3-in-progress/0108-Horizontal_Lineage_Workspace.md#m11--delete-replaced-architecture--in-progress)
  must finish removing replaced runtime storage and adapters. [0110 M15](../5-closed/0110-Global_Job_Manager.md#m15--remove-duplicate-ui-and-execution-contracts--complete)
  must finish removing duplicate execution and browser lifecycle code.
- **Outcome:** Six active code paths have small composition roots, explicit owners, focused test
  entry points, and size checks. All milestones are not started.
- **Readiness gate:** Verify both prerequisite milestones in their current files and Git history.
  Then move this epic to Ready and update the board. Full closure of 0106, 0108, or 0110 is not required.

## Evidence and selection

Inspection date: 2026-11-06. The repeatable baseline is commit `dcb249dea`. The activity window is
2026-11-02 00:00 Europe/Berlin through that commit. Counts are commits that touched the path;
line counts include comments and blank lines. Working files changed during inspection, so the
table uses committed bytes. It excludes generated API code from extraction candidates.

| Priority | Source path | Lines | Touches | Responsibilities to separate |
| --- | --- | ---: | ---: | --- |
| 1 | `backend/src/dokodetector_backend/visual_identity_pipeline_service.py` | 2,517 | 4 | Crop-input freezing, crop resolution and provenance, per-card classification, managed execution, publication, auto-approval |
| 2 | `web/src/api/client.ts` | 1,323 | 12 | Transport, errors, hand-written types, path builders, and methods for many features |
| 3 | `web/src/pipeline/RecordingPipelineWorkspace.tsx` | 922 | 12 | Workspace and graph requests, stale-response protection, URL selection, commands, and rendering |
| 4 | `backend/src/dokodetector_backend/pipeline_store.py` | 2,037 | 6 | Revision persistence, processor-run metadata/state/items, selection persistence, JSON parsing, and locking |
| 5 | `web/src/pipeline/RunControls.tsx` | 1,154 | 4 | Stage input choices, provider/model choices, request construction, launch controls, and private run monitoring |
| 6 | `backend/src/dokodetector_backend/job_store.py` | 1,034 | 7 | Job models, cancellation, acceptance intents, recovery, queue state, publication, and transitions |

The largest related tests also increase reading cost:

| Test path | Lines | Touches | Treatment |
| --- | ---: | ---: | --- |
| `backend/tests/test_visual_identity_pipeline_api.py` | 1,691 | 6 | Move crop, execution, and approval cases beside their new owners; retain HTTP contract cases. |
| `web/src/pipeline/RecordingPipelineWorkspace.test.tsx` | 1,568 | 7 | Separate loading/races, URL selection, commands, and composition cases. |
| `backend/tests/test_pipeline_reference.py` | 3,937 | 2 | Recheck after 0108 M11. Delete only cases for removed behavior; split retained cases with their actual owner. |

File size and activity identify expensive reading surfaces. They do not prove that file size caused
agent latency. No comparable agent timing or token measurement was available for this audit.

Reproduce the activity counts with:

```sh
git log dcb249dea --since='2026-11-02T00:00:00+01:00' --format='%h' -- <path>
git show dcb249dea:<path> | wc -l
```

### Candidates deferred from this epic

- `ios/CardEventProbe/App/AppState.swift`: 1,270 lines and three touches. Local round-analysis
  launch, restore, cleanup, and diagnostics form a useful future workflow boundary.
- `ios/CardEventProbe/Core/DeviceRecordingCalibration.swift`: 979 lines and three touches.
  Candidate selection and contour/geometry helpers form a useful future split. Keep numerical
  behavior under the existing Mac Swift fixtures before changing it.
- Migration inventory code is large, but 0108 owns its runtime isolation and retirement.
- `web/src/api/openapi.ts` is generated. Keep generation and contract verification intact.
- Large geometry/operations modules had fewer recent touches. Do not expand this epic into a
  repository-wide size campaign.

## Scope and fixed rules

Use the [glossary](../../glossary.md). This epic changes code ownership, not domain meanings.
Keep current request/response behavior, immutable revision bytes, crop identities, exact input
references, review applicability, job transitions, publication, and recovery behavior.

0108 owns lineage cutover, obsolete storage, adapters, and migration. 0110 owns shared job lifecycle,
polling, status UI, and launch receipts. 0109 owns working-area layout. This epic must not repeat
those changes or redesign launch inputs, model choices, or the frame surface. Do not refactor a
removed store or preserve obsolete imports with compatibility facades. Update internal callers.
Existing public API and persisted data behavior must not change as a side effect of moving code.

Each implementation milestone moves one bounded concern and its tests. Use explicit dependencies
and typed inputs. Do not pass the entire former service into an extracted helper. Do not add a
generic framework, event bus, global store, or many one-function wrapper files. A composition root
may delegate; it must not re-export all former internals.

Target budgets after cleanup: each selected composition root at most 500 lines; each new production
module at most 700 lines; each focused test file at most 800 lines. Count physical lines. M0 must
assign the surviving code to modules that fit these budgets. Split oversized cohesive operations
into explicit phases with tested inputs and outputs. Do not meet budgets by compressing code or
moving unrelated logic into an unbounded utility module. An exception requires evidence and an
explicit plan change before the affected milestone is marked complete.

## Milestone status

| Milestone | Work | State |
| --- | --- | --- |
| M0 | Freeze surviving owners, contracts, and verification | Not started |
| M1 | Extract visual-identity crop-input freezing | Not started |
| M2 | Extract visual-identity crop resolution and provenance | Not started |
| M3 | Separate identity execution and per-card classification | Not started |
| M4 | Split surviving pipeline persistence owners | Not started |
| M5 | Extract API transport and feature contract types | Not started |
| M6 | Split API methods and paths by feature | Not started |
| M7 | Extract workspace loading and selection state | Not started |
| M8 | Split processor launch controls from request construction | Not started |
| M9 | Split job models and recovery from lifecycle management | Not started |
| M10 | Enforce boundaries and verify the complete fixture workflow | Not started |

## M0 — Freeze surviving owners, contracts, and verification

Confirm the readiness gate. Recount the six paths and related tests after the prerequisites.
Write `docs/reports/0112-M0_Module_Map.md` with the current commit, source symbols, callers,
destination modules, dependency direction, exact test selectors, and per-file budgets.
Record removed targets instead of restoring them. Use a retained successor when the responsibility
still exists. If a target has disappeared completely, record its milestone as satisfied by removal
only after proving that no active caller remains.

Map at least these behavior gates: proposed-scene pose IDs to detector IDs; frozen crop revision and
provenance; finite normalized identity probabilities; job cancellation versus publication; restart
recovery and retries; exact node input selection; stale workspace responses; browser timeout and
abort behavior. Add only missing characterization tests needed for the planned moves.

Acceptance: each later milestone has named source symbols, typed boundaries, focused checks, and
budgets. Record baseline check failures separately. No implementation extraction belongs to M0.

## M1 — Extract visual-identity crop-input freezing

Move `_freeze_crop_input`, canonical input resolution, reviewed virtual-card item assembly, and
their source validation from `VisualIdentityPipelineService` into
`visual_identity_crop_inputs.py` and `visual_identity_crop_sources.py`. Use a frozen result type
with the exact input revision, crop items, and provenance. Pass stores and recording access
explicitly. Keep request acceptance and job ownership in the service.

Move the relevant crop-kind and source-validation tests into focused files.

Acceptance: all supported crop kinds produce the same frozen inputs and reject mismatched sources.
Proposed virtual cards retain the same-frame pose-to-detector mapping. No service callback cycle.

## M2 — Extract visual-identity crop resolution and provenance

Move `_ValidatedCropContext`, crop identity/fingerprint helpers, validated outcome lookup,
reviewed annotation crop lookup, browser preview, and provenance checks into
`visual_identity_crop_resolution.py` and `visual_identity_crop_provenance.py`.
Use the M1 input types. Keep HTTP error conversion at the existing service/API boundary.

Acceptance: crop bytes and identities match fixtures; stale or mismatched provenance is rejected.
Browser preview and reviewed annotation lookup use the same validated geometry. Geometry refinement
remains limited to its current supported crop input. Resolution tests run without starting jobs.

## M3 — Separate identity execution and per-card classification

Move `_process_card`, timing/concurrency helpers, classifier selection, and result conversion into
`visual_identity_classification.py`. Move `execute_job` orchestration into
`visual_identity_job.py`. Give publication and auto-approval planning focused owners if needed to
meet the M0 budgets. The service retains public operations and dependency composition.

Acceptance: service root is at most 500 lines. Keep bounded concurrency, safe cancellation,
probability normalization, exact output provenance, failure recording, and publication arbitration.
Auto-approval retains its existing authority rules. Split classification, job, approval, and HTTP
tests; do not create a second scheduler or lifecycle model.

## M4 — Split surviving pipeline persistence owners

Reconcile the M0 inventory with 0108 M11 before editing. Move surviving processor-run persistence
to `processor_run_store.py` and its state/item codecs to `processor_run_codec.py`.
Give surviving revision persistence its own `pipeline_revision_store.py`. Put common storage
errors, paths, JSON, and lock primitives in a bounded `pipeline_storage.py` only where shared.
If canonical stores replaced revision or selection persistence, remove the obsolete owner instead
of extracting it. Update callers directly; retire `pipeline_store.py` when it has no responsibility.

Acceptance: round-trip fixtures retain exact bytes and error behavior. Focused tests cover compact
status reads, split metadata/state/items, atomic publication, corrupted files, and lock ownership
where those paths survive. Retained reference tests are grouped by current owner. No legacy
selection adapter, dual write, or migration-format parser enters runtime through this extraction.

## M5 — Extract API transport and feature contract types

Move `ApiError`, `requestJson`, response-body handling, headers, timeout, and caller-abort handling
to `web/src/api/transport.ts`. Move retained hand-written types to feature contract modules for
recordings, pipeline, calibration, and analysis; use existing generated schemas where equivalent.
Reuse the existing lineage and jobs API modules rather than creating duplicate contracts.

Acceptance: one shared transport owns HTTP errors and cancellation. Transport tests cover JSON,
text/empty errors, timeout, caller abort, and listener/timer cleanup. Typecheck and generated API
verification pass. Existing callers work while M6 moves feature methods; no contract redesign.

## M6 — Split API methods and paths by feature

Move client methods and URL builders into recording, pipeline-processing, calibration, and analysis
modules beside their contract types. Keep shared frame URL/sampling helpers with one explicit
owner. Reuse existing jobs/lineage clients and the M5 transport. Update feature consumers and mocks.
Keep `createDokoDetectorClient` only if still useful as a small composition factory, without broad
type re-exports or implementation logic.

Acceptance: each feature can import its client without reading unrelated feature implementations.
URLs, query encoding, headers, request bodies, and result types pass focused client tests.
No feature module imports the aggregate composition root. Test files follow feature ownership.

## M7 — Extract workspace loading and selection state

Extract workspace/graph loading, refresh, abort, stale-response checks, and response validation into
`useRecordingPipelineData.ts`. Move URL sanitization, initial-step/item choice, and selection
commands into `recordingPipelineSelection.ts` and `useRecordingPipelineSelection.ts`, reusing
`recordingPipelineUrl.ts`. Keep layout and editor composition in `RecordingPipelineWorkspace`.

Acceptance: composition root is at most 500 lines. Tests cover recording switches during requests,
stage switches, graph errors, refresh, invalid/deleted nodes, URL restoration, and exact selection.
Retain a small composition integration test. No second selection authority or shared job poller.

## M8 — Split processor launch controls from request construction

Start from the controls left after 0110 M15. Move `buildStartPayload`, crop options, model/provider
defaults, and input validation into `pipelineLaunchRequest.ts`. Move stage-specific form sections
to `EventLaunchFields.tsx`, `VisibleCardLaunchFields.tsx`, and `VisualIdentityLaunchFields.tsx`
where those sections survive. Keep one thin `RunControls` composition and submission owner.

Acceptance: root is at most 500 lines. Focused tests cover exact input refs, proposed-scene crop
choice, provider/model defaults, validation, and submitted payloads. A UI test verifies submission
and shared job navigation. Do not restore private polling, retry/status UI, or removed input modes.

## M9 — Split job models and recovery from lifecycle management

Move job request/state models, queue/log/publication records, errors, and cancellation types from
`job_store.py` into `job_models.py`. Move acceptance-intent parsing/replay and restart reconciliation
into `job_recovery.py`, using explicit persistence operations. Move `FakeParticipant` to test
support after checking all consumers. Keep lock ownership and lifecycle mutations with one
`JobManager`; isolate filesystem encoding if required to meet the root budget.

Acceptance: root is at most 500 lines. Existing acceptance, idempotency, queue ordering,
cancellation, retry linkage, partial-write recovery, parent-child, and publication-race tests pass.
Recovery cannot mutate outside the manager's ownership lock. Do not add another journal or alter
the durable job schema. Split tests by lifecycle, persistence/recovery, and publication ownership.

## M10 — Enforce boundaries and verify the complete fixture workflow

Add an automated source/test size check for this epic's explicit file list. Include all extracted
modules and tests; exclude generated code and unrelated existing files. Add focused import checks
for dependency direction, especially feature clients importing the aggregate root, service/helper
cycles, and production imports of test support. Use the normal test tooling.

Run the focused backend and web suites identified in M0, backend Ruff lint/format, web typecheck,
lint/format, and generated API verification. Run a local fixture workflow from exact input selection
through managed identity processing, publication, reload, and result inspection. Use focused browser
checks for selection, launch, and shared job navigation. No cloud, phone, training, or sealed
evaluation is required.

Publish `docs/reports/0112-Cleanup_Handoff.md`: before/after sizes, owner/import map, precise check
commands and results, retained limits, and three example change paths showing the source/test files
now needed for crop validation, launch payloads, and restart recovery. Do not claim measured agent
speed gains without a comparable measurement.

Acceptance: every surviving target meets its budget, focused tests belong to the extracted owner,
and the fixture workflow passes. All prerequisite behavior gates remain covered. Close the epic,
move it to `5-closed`, repair links, and update the board in the final milestone commit.

## Execution handoff

- Planning only. No implementation milestone has started.
- Current blocker: 0108 M11 and 0110 M15 have not completed at the inspection baseline.
- Next: verify prerequisite completion, move to Ready, then execute M0.
- Preserve concurrent changes. The inspection found work in visual identity, app chrome, API client,
  and the Jobs drawer. No such implementation files belong to this planning change.
