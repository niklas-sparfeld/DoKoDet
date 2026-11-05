# One-click recording pipeline

## Plan status

- **Summary:** Start the complete recording pipeline from one web workspace action and retain each
  intermediate result for later review.
- **Status:** Closed
- **Closure reason:** Complete
- **Depends on:** Existing recording workspace and stage services; the retained 0090 coordinator is
  available for assessment. No human review campaign is a prerequisite.
- **Outcome:** M0–M4 complete. A local fixture run retains six-stage lineage and can be restored
  in the workspace after reload. Execution completion does not establish reconstruction correctness.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Purpose

An operator starts one run from a recording. The system executes the applicable stages in order
without further input. The workspace exposes intermediate runs and results in the same way as
manual stage execution. A completed run saves the round analysis for inspection after reload.
Execution success does not assert that predictions or reconstruction are correct.

## Execution decisions

- Each new run creates fresh results for every stage. Resume an interrupted run with its existing
  completed results; a new run is not a resume.
- Require recording, provider, and stage configuration before the run starts. Derive analysis IDs
  from the recording and use generic seat labels. Do not ask the operator for player IDs, dealer,
  trick leader, or game, round, and session IDs.

M0 must define the automatic path when calibration cannot be published or there are no event
proposals. It must state which outcomes stop the run and which valid empty outputs can continue.
It must not silently skip a required stage or report a partial result as complete.

## Scope and behavior

- Cover the recording video through event proposals, visible cards and piles, any required
  calibration and proposed card scenes, visual identity proposals, table observations, and round
  analysis. M0 freezes the actual dependencies and the compatible automatic geometry and crop path.
- Collect and validate all required recording, model, and stage configuration before the single
  start action. Read the session ID from the recording. Derive game and round IDs from the
  recording ID and use `player-1` through `player-4` for analysis. A running pipeline does not wait
  for human review or input.
- Use the configured providers and explicit policies. Freeze the request and exact input lineage for
  each run. Do not silently change provider or use reviewed results as automatic outputs.
- Persist ordinary stage requests, run states, output revisions, lineage, and analysis results so
  existing workspace views can inspect them. Preserve failures and partial results. Generated output
  is not reviewed ground truth. Do not overwrite drafts, completed references, or selections.
- Run independently of the browser page. Show overall and per-stage progress and a clear terminal
  result. On failure, stop dependent work and identify the stage and cause. Preserve completed work
  across a reload or interruption; define safe restart and duplicate-start behavior in M0.
- Use fixtures and local substitutes for routine tests. No model training, accuracy claim, campaign
  review, iOS work, or production deployment is in scope.

## Milestones

### M0 — Freeze the execution contract — Complete

Inspect current manual requests, workspace persistence, calibration requirements, coordinator,
model configuration, and analysis inputs. Record the stage graph, inputs, output lineage, valid empty
results, failure behavior, restart rules, concurrency, and the execution decisions above.
Identify any manual-only prerequisite and a bounded automatic path or an actionable preflight error.
Select a small deterministic fixture and define acceptance before implementation.

Acceptance: the contract maps each output to the next input and to its existing review view; it
requires no input after start and does not change review authority. The implementation milestones
below are adjusted if the inspection finds a material gap.

Result: [0105 M0 execution contract](../../reports/0105-M0_Execution_Contract.md). The retained
0090 coordinator is a CLI reference. M1 must add a durable recording-scoped start/status boundary.
The report freezes the six-stage graph, automatic crop path, valid empty outputs, blocking failures,
preflight facts, restart and duplicate-start rules, and deterministic fixture acceptance.

### M1 — Start and persist an automated run — Complete

Add a recording-scoped start and status boundary and durable run record. Freeze and validate inputs
before scheduling. Reuse the existing coordinator or stage services where they satisfy the contract.
Prevent duplicate concurrent runs for the same recording and retain actionable preflight errors.

Acceptance: fixture tests cover valid and invalid starts, status reads, duplicate starts, and frozen
inputs. No work starts for a failed preflight.

Result: [0105 M1 run start and preflight](../../reports/0105-M1_Run_Start_and_Preflight.md). The
recording-scoped API validates the recording, local providers, search limits, and stage settings
before it writes an `accepted` run. The session ID comes from the recording. Game and round IDs
and generic seat context are generated internally. Same-key retries return that run; another
active start for the recording conflicts. M2 owns stage scheduling and restart recovery.

### M2 — Execute and retain intermediate results

Execute the frozen stage graph through the existing persistence paths. Link each completed output
to its downstream input and the overall run. Retain stage failure and partial results; stop on a
blocking failure. Make interruption and restart safe without duplicating completed work.

Acceptance: fixture tests exercise full lineage, ordinary workspace visibility, failure, empty
results, interruption, and restart. Existing review drafts and selections remain unchanged.

Result: [0105 M2 execution and lineage](../../reports/0105-M2_Execution_and_Lineage.md). The
backend worker now runs the frozen six-stage graph outside the request and browser lifecycle. It
stores stage requests, processor run IDs, exact input and output revision IDs, and failures in the
overall run. Startup resumes accepted or interrupted runs from the coordinator manifest and retries
an interrupted processor request. Completed stages keep their retained outputs.

### M3 — Add the recording workspace action — Complete

Expose prerequisite entry and validation, one start action, progress, failure details, and links to
the existing stage results and saved analysis. Restore the run status after navigation and reload.

Acceptance: browser-level fixture tests start once and observe all stages and the saved analysis
without intermediate input. They cover missing inputs and a failed stage.

Result: [0105 M3 workspace action](../../reports/0105-M3_Workspace_Action.md). The recording
inspector starts one complete run without asking for round facts. It restores its saved run ID after
reload and polls durable status. It shows stage state, failure causes, and links to the existing
stage and analysis views. Browser fixtures cover preflight, start, reload, and stage failure. M4
must verify the full local workflow with the backend fixture.

## Operator inputs correction

The original M1/M3 contract required game, round, session, player, dealer, and first-trick-leader
inputs. The complete pipeline does not ask the operator for these values. It reads the session from
the recording, derives stable game and round IDs from the recording ID, uses `player-1` through
`player-4`, and stores `dealer-unspecified`. The current reconstruction contract still requires a
first-trick leader, so the pipeline uses `player-1` as its deterministic default. This default is
not an inferred gameplay fact and does not establish reconstruction correctness.

### M4 — Verify the complete local workflow — Complete

Run the relevant backend, coordinator, and web checks. Exercise the complete fixture through the
same user-facing path and record setup, selected configuration, evidence, and limitations. A bounded
real-model smoke test is optional when the local prerequisites are available; it is not an accuracy
gate.

Acceptance: a second local operator can reproduce the fixture workflow and inspect each retained
result after reload. The report distinguishes a completed execution from a correct reconstruction.

Result: [0105 M4 complete workflow verification](../../reports/0105-M4_Complete_Workflow_Verification.md).
The deterministic fixture completes all six stages with exact revision lineage. The workspace
fixture restores completion and stage links after reload. Focused backend and web checks pass.
The report records that these are layered fixture checks, not a live model run or an end-to-end
browser-to-backend Playwright test; the current Playwright suite has unrelated workspace assertion
failures.
