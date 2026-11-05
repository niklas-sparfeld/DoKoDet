# Epic 0110 M0 execution contract

This contract records the source tree inspected on 2026-11-05, including uncommitted pipeline
changes. Later milestones must recheck their owning source before cutover.

## Execution owners found

| Work | Current owner and entry points | Planned disposition |
| --- | --- | --- |
| Event processing | `event_pipeline_service.py`: `start_inference`, `retry`, private executor. `pipeline_stage_api.py`: start and retry routes. | Managed leaf, M5. |
| Visible-card processing | `visible_card_pipeline_service.py`: `start_detection`, `retry`, private executor and inner executor. Stage API start and retry routes. | Managed leaf with bounded inner workers, M6. |
| Proposed card scenes | `proposed_card_scene_pipeline_service.py`: `start_proposal`, `retry`, private executor. Stage API start and retry routes. | Managed leaf, M7. |
| Visual identities | `visual_identity_pipeline_service.py`: `start_classification`, `retry`, private executor and inner executor. Stage API start and retry routes. `pipeline_reference_api.py` also calls the service for auto-approval. | Managed leaf; keep review authority separate, M8. |
| Table observations | `observation_pipeline_service.py`: `start_assembly`, `retry`, private executor. Stage API start and retry routes. | Managed leaf, M9. |
| Round analysis | `round_analysis_service.py`: async queue and worker, with an inner executor. `round_analysis_api.py` and `recordings_api.py` start analysis. Automated pipeline worker also enqueues analysis. | Managed leaf, M10. |
| Automated recording pipeline | `automated_pipeline_worker.py`: async queue and worker. `pipeline_run_api.py` accepts runs. | Managed parent and child jobs, M11. |
| Calibration preview | `calibration_refinement_api.py` calls `calibration_refinement_service.py` from draft routes, including review draft routes. | Managed calculation, M12; apply remains a domain command. |
| Counterfactual | `round_analysis_api.py` calls `create_counterfactual` synchronously. | Managed calculation, M12; retain immutable results. |

The browser has separate controls in `web/src/pipeline/RunControls.tsx`,
`ObservationRunControls.tsx`, `RoundAnalysisControls.tsx`, and `AutomatedPipelineControls.tsx`.
The visible-card editor and `web/src/analysis/CounterfactualWorkbench.tsx` are also callers.
The stage API has separate start, retry, status, and result routes for its five processors.
Result and selection routes have domain roles and must be assessed separately from lifecycle routes.

## Further source findings

- `pipeline_coordinator.py` contains both the in-process stage executor used by the automated
  worker and an HTTP executor used by `pipeline_coordinator_cli.py`. Both poll until a stage is
  terminal. The CLI is a separate caller that must move to the shared job API in M11/M15.
- The visual-identity auto-approval plan can start its own local classification. Both plan and
  apply routes call that planning method. M8 must route that dependency through job acceptance;
  it must not apply a review decision when the job completes.
- Event import executes synchronously in `import_predictions` and writes a processor run and
  revision. Its cost depends on imported data size. Assign it to an `event_import` leaf in M5,
  with exact import bytes/digest frozen before acceptance. The import route and its test caller
  must switch with event processing. It is not a separate scheduler.
- `CalibrationRefinementService._response` builds a preview for full responses, including the
  start and read paths. Apply also rebuilds and checks the preview. M12 must make reads return
  saved state only and must preserve apply's digest and conflict checks.
- The RF-DETR availability route accesses provider bundle identity and can trigger loading.
  It is a bounded availability check, not accepted processor work. M6 must ensure it does not
  perform model inference or start a private background worker.
- The executor/queue search in `backend/src` found the seven owners in the inventory above;
  the remaining executors are inner work for visible cards, visual identities, and analysis.
  The backend tests call the service and HTTP entry points directly, including
  `test_pipeline_api.py`, `test_proposed_card_scene_pipeline.py`,
  `test_visual_identity_pipeline_api.py`, `test_pipeline_coordinator.py`, and
  `test_automated_pipeline_run.py`. Adapt those tests at the owning cutovers.
- Browser callers also include `RoundAnalysisControls.tsx`, `PipelineRoundAnalysisWorkbench.tsx`,
  `PipelineVisualIdentityEditor.tsx`, and the visible-card editor/controller. The client API and
  generated OpenAPI types are shared boundaries. Remove independent polling only after each
  launch and result path is connected to the shared client.

## Frozen execution contract

### Durable acceptance and recovery

Use `jobs/<job-id>/job.json`, `jobs/queue.json`, `jobs/intents/<job-id>.json`, and
`jobs/owner.lock` under the operations root. IDs are opaque UUIDs. Files use versioned,
validated JSON and atomic replacement with durable file and directory synchronization. One
exclusive OS lock covers recovery, acceptance, queue changes, and scheduler ownership. Failure
of a write stops acknowledgement and dispatch. Invalid records are quarantined from dispatch and
shown as diagnostics; they are not silently deleted.

Normalize and validate the typed request and resolve exact inputs before writing an intent. Scope
an idempotency key to the operations root and hash the canonical type, context, and request. Under
one writer lock, persist an intent containing the key, hash, allocated job ID, exact inputs,
participant operations and deterministic domain identities. Then idempotently create the domain
run and accepted-use protection, validate those writes, write the queued job, and add its ID to the
queue. Mark the intent committed only after all writes verify. Dispatch requires a committed intent
and verified participants. A `202` is returned only after commit. The key index is reconstructible
from intents, including unfinished intents; it is not an independent authority.

At restart, hold the owner lock and process intents before dispatch. Replay missing participant,
job, and queue writes using their fixed identities. If a participant cannot verify its exact content,
leave the intent non-dispatchable and expose an error. A repeated key with the same normalized
request returns the same job after recovery; a different request conflicts. A crash after any one
write, including after commit but before the response, cannot create a second job. Accepted-use
records already created are retained if acceptance fails; do not silently remove input protection.
The queue is a validated index: reconcile committed queued jobs absent from it by appending them in
intent creation sequence; remove terminal or non-dispatchable IDs, and report unknown IDs. Persist
one new queue revision for reconciliation. Queue order is not inferred from timestamps.

A handler writes output under a deterministic attempt/output identity, validates the full artifact
and provenance, and commits the domain publication before recording success. Serialize publication
and cancel decisions with the manager lock. On restart, validate a committed publication and link
it to the job before marking success; an uncommitted or invalid artifact does not prove success.
If cancellation wins before publication, do not publish. If publication wins, record the actual
outcome and expose that cancellation was too late.

### State, history, resource and checkpoint policy

Job transitions are `queued -> running|cancelled`, `running -> waiting|cancelling|succeeded|failed|interrupted`,
`waiting -> queued|cancelling|failed|interrupted`, and `cancelling -> cancelled|succeeded|failed|interrupted`.
Only a parent can return from waiting to queued. A terminal state cannot transition. On restart,
queued jobs stay queued; active leaves become interrupted unless a verified publication proves
completion. A waiting parent resumes only with a complete durable child/step checkpoint; an
interrupted required child interrupts the parent. Explicit retry creates a new linked attempt with
exact frozen inputs and new child IDs. Reuse only completed outputs whose identity, input digest,
configuration, and content validate. All other handlers restart their unit from the start; no
partial frame, library call, or unpublished file is a checkpoint.

Existing processor and analysis states `queued` and `running` are not imported as runnable jobs.
At cutover, retain their domain records and show them in domain history as legacy execution records,
including their recorded status, timestamps, and failure. Do not synthesize job IDs, counts, or
progress. Their domain result links remain available. Existing restart handling must settle any
active old work before removing its worker. New runs link to jobs, and their status comes from the
job; do not maintain two mutable lifecycle authorities.

Initially configure one processing slot, a CPU-worker budget of one, and one accelerator and one
external-service permit. Every running leaf claims one slot and at least one CPU permit; actual
worker pools cannot exceed their allocation. Local accelerator providers claim the accelerator;
remote provider calls claim an external-service permit for the duration of the call. Domain write
locks use the exact recording and output kind; calibration apply and review edits retain their own
revision checks. A waiting parent holds none of these claims. Do not enable more slots until the
fairness fixtures pass. Select the earliest eligible queued job that fits. Once an earlier eligible
job cannot get a claimed resource, reserve that resource for it: later jobs that need it cannot pass,
while jobs requiring disjoint resources may run. Inputs and dependencies that are not ready do not
reserve resources. Release claims only after the handler actually stops.

Safe-stop checks occur before each bounded item, after each non-interruptible call, and before
publication. A native/model/provider call can finish before cancellation takes effect; retain claims
and show `cancelling` until it returns. Parent cancellation stops new children, requests cancellation
of active owned children, and becomes terminal only after all stop. Inner worker pools must stop
submitting new work and drain running calls. Do not claim hard termination without a tested subprocess.

Valid empty results succeed when their owning domain contract permits them. A completed result with
partial coverage reports the exact coverage and warnings; it does not imply a complete review. The
pipeline contract decides whether that result satisfies a required stage. Its current coordinator
fails the parent for `partial` or `failed` stages and for a required complete stage without an output
reference; preserve those rules. Skipped optional stages remain skipped.

For a preview freeze the draft revision and digest, proposal/calibration and evidence digests. Store
results under that snapshot identity. An edit makes an old result stale; completion cannot replace
the current preview. Apply verifies the current draft, evidence and preview digest and remains an
explicit domain action. Counterfactual jobs freeze the analysis input/result digests and full
correction request; they publish an immutable result and never apply corrections to source data.

### Queue groups and ordering

`queue.json` contains `schema_version`, integer `revision`, and an ordered list of group entries.
A standalone queued job is a group with its own job ID. A parent group has its parent job ID and
an ordered list of its queued child IDs; the parent coordination continuation is represented by the
parent ID when it is queued. The group keeps its position while the parent waits and has no queued
children. A child's dependencies and the parent's stable step order determine eligibility, not
its position alone. A newly accepted standalone job or parent group appends. A child is inserted
into its existing parent group in step order. Dispatch scans groups in order and eligible members
in step order, subject to resource reservation. Only the scheduler can mutate membership.

A move names a queued standalone job or a nonterminal parent group, a target group ID or null for
the end, and the expected queue revision. Move the entire group atomically and increment revision.
Reject child-only moves, self moves, unknown IDs, terminal parents, and nonqueued standalone jobs.
The target can be a waiting parent group. Reordering never changes child dependencies or preempts.
For `[A, P(child P1), B]`, moving `P` before `A` gives `[P(P1), A, B]`; a later P2 enqueue goes
inside P, not at the end of the global queue. If B is enqueued after a client read revision 4,
the enqueue makes revision 5; a move with revision 4 fails with the current revision and order.
Moving a waiting P with no queued child changes the preference of its next child. Cancellation,
dispatch, completion, child insertion, and every other membership change also increment revision.

### API and persisted record schema

All JSON objects reject unknown fields. IDs are opaque UUID strings except validated domain IDs;
timestamps are UTC RFC 3339 strings. `schema_version` is `backend-job/v1` for a job and
`backend-job-queue/v1` for a queue. Hashes are lowercase SHA-256 hex. Null is explicit where
shown. The job record and detail response contain:

- `id`, `type`, `label`, `state`, `revision`, `created_at`, `updated_at`, `started_at`,
  `finished_at`, `creator`, `correlation_id`, `idempotency_key`, and `request_hash`.
- `context` with `recording_id` and optional exact domain IDs; `request` is the immutable,
  validated type-specific request; `inputs` is a list of `{kind, id, digest}` exact references;
  `implementation` contains the resolved implementation, version, model/configuration identity.
- `parent_id`, `parent_step_id`, `retry_of`, `worker_owner`, `phase`, and `waiting_reason` are
  nullable. `steps` contains `{id, label, state, started_at, finished_at, completed, total,
  unit, message, failure, child_job_id}`. Counts are both null when total is unknown; otherwise
  `0 <= completed <= total`. Step IDs are stable within a logical parent across retry attempts.
- `failure` is null or `{code, message, details, retryable}`; `warnings` is a list of structured
  `{code, message}`; `coverage` is null or a type-specific domain summary; `results` is a list of
  validated `{kind, id, digest, available}` exact domain references, never user-supplied URLs.
- `capabilities` gives `{allowed, reason}` for `cancel`, `retry`, and `reorder`. It is computed on
  read, not an authorization to execute a stale command. Diagnostic entries use a monotonically
  increasing sequence, timestamp, level, code, and message; bounded retention reports truncation.

`POST /api/jobs` takes `{type, context, request}` and a required `Idempotency-Key` UUID header.
It returns `202` and a job detail with `Location: /api/jobs/{id}` on acceptance or same-key replay.
Each type registers a closed validated request schema. The initial type names are `event_processing`,
`event_import`, `visible_card_processing`, `proposed_card_scenes`, `visual_identities`,
`table_observations`, `round_analysis`, `automated_pipeline`, `calibration_preview`, and
`counterfactual`. The five processor schemas use the existing `ProcessorRunRequest` contract in
`doko_operations.pipeline_data`, with the owning service validations and exact resolved inputs;
they freeze defaults and exact inputs; event import also freezes its source digest. Round analysis uses
`RoundAnalysisCreateRequest`; counterfactual uses `RoundCounterfactualCreateRequest`. The parent
uses the existing stage configuration and round facts; the preview requires draft ID/revision/digest,
proposal ID, and evidence digests. The registry owns these schemas and produces a discriminated
OpenAPI union; no arbitrary handler name or path is accepted. Job IDs are manager-generated; domain
IDs are allocated or validated by the owning participant. For processor requests the participant
allocates `run_id` before validating and storing the complete `ProcessorRunRequest`. Retry preserves the original exact inputs.

`GET /api/jobs` accepts `state`, `type`, `recording_id`, `parent_id`, `scope=active|history|all`,
`cursor`, and `limit` (default 50, maximum 100). It returns `{items, next_cursor, queue_revision}`.
The opaque cursor binds the filters and a stable `(created_at, id)` descending boundary. The
response also contains `groups`, the current ordered group entries defined above, on every page. `GET /api/jobs/{id}` returns
the job. `POST /api/jobs/{id}/cancel` takes `{}` and returns the current detail; repeat requests are
idempotent. `POST /api/jobs/{id}/retry` takes `{}` and a new `Idempotency-Key` and returns `202`,
new detail, and Location. `POST /api/jobs/queue/move` takes `{group_id, before_group_id,
expected_revision}` and returns `{revision, groups}`. `GET /api/jobs/{id}/logs` accepts `after`
(sequence, default 0) and `limit` (default 100, maximum 500) and returns `{entries, next_after,
truncated_before}`. Missing exact result artifacts remain unavailable links.

Errors use `{error: {code, message, details}}`: `404 job_not_found`, `422 invalid_request` or
`unknown_job_type`, `409 idempotency_conflict`, `invalid_transition`, `retry_not_supported`, or
`queue_revision_conflict`; queue conflict details include current revision and groups. Storage or
ownership failures return `503 job_manager_unavailable` and never acknowledge acceptance. A request
disconnect after commit does not cancel the job; retry with the same key obtains its identity.

### Fixture matrix

- M1: inject a crash before and after intent, each participant, job, queue, and commit write;
  restart and replay the same key. Assert exact input protection, one job and one domain identity,
  stable queue membership, and conflict on changed request. Corrupt each record and test visible
  diagnostics and no dispatch. Race two owners and prove only one can write or dispatch.
- M2: assert queued versus running at claim time, single-slot budget, bounded inner workers,
  blocked-input bypass, exclusive accelerator/domain locks, resource reservation, deterministic
  FIFO, group moves, enqueue/reorder conflict, and restart order. Exercise a multi-slot fake budget
  before enabling it in configuration.
- M3: race enqueue/cancel and cancel/publication in both orders; hold a fake uninterruptible call,
  check claims until it exits, and test graceful and forced restart. Validate committed output after
  a crash, reject a partial artifact, retry with exact inputs and new IDs, and retain prior history.
- M4: exercise every endpoint, filters and cursor binding, limits, invalid schemas/types, duplicate
  keys, unavailable results, capabilities, log truncation, disconnect after commit, and stale moves.
- M5–M10: use local providers and frozen domain fixtures for each listed handler. Cover input
  protection, empty and partial coverage, failure, cancellation at each bounded unit, publication,
  interruption, retry and exact output links; cover inner worker budgets for the three inner pools.
  Include event import and auto-approval dependency without review mutation.
- M11: one-slot fake six-stage parent, independent queued work, child-creation crash at each write,
  cancellation while a child is active, required partial/failure, permitted skip, empty output,
  verified completed-stage reuse and explicit retry with stable logical step IDs.
- M12: edit a draft during preview and attempt stale apply; verify old output remains inspectable
  without becoming current. Retry a counterfactual with exact constraints and validate immutable
  publication. Exercise cancellation during calculation and the publication race.
- M13–M16: fake polling responses out of order, hidden/visible pages, failed connections, bounded
  pagination and logs, reload and exact result links; test keyboard/focus and narrow layout. Run
  mixed-recording reorder/cancel/restart/retry fixtures and source inventory after cutover.
