# Global Job Manager

## Plan status

- **Summary:** Unify backend work under one durable job contract, HTTP API, scheduler, and global
  Jobs drawer. Keep processor results and data lineage in their owning stores.
- **Status:** In Progress
- **Depends on:** Existing backend execution and filesystem storage. No completion gate from
  [0107](../5-closed/0107-Unified_Pipeline_Data_Lineage.md),
  [0108](../3-in-progress/0108-Horizontal_Lineage_Workspace.md), or
  [0109](../4-blocked/0109-Working_Area_Interface_Unification.md).
- **Outcome:** M0–M9 complete; M10–M16 not started. The [execution contract](../../reports/0110-M0_Execution_Contract.md)
  freezes the inventory, recovery protocol, API, queue rules, and fixture cases.

## Problem and inspected scope

Long backend operations have separate execution, persistence, recovery, status, and UI paths.
The operator cannot see or manage all work from one place. Some services mark a run as running
before its executor starts it. Queue order and resource use are not controlled globally.

These findings come from the current source tree, including ongoing local pipeline changes.
They are not a completed runtime inventory. M0 must verify the code that exists when work starts.
Use the domain terms in the [glossary](../../glossary.md).

| Work                            | Current execution and presentation                                                                     | Planned treatment                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| Event processing                | `event_pipeline_service.py`; private single-worker executor; `RunControls.tsx`                         | Managed leaf job.                                                                                     |
| Visible-card processing         | `visible_card_pipeline_service.py`; private executor and inner frame workers; `RunControls.tsx`        | Managed leaf job with bounded inner concurrency.                                                      |
| Proposed card scenes            | `proposed_card_scene_pipeline_service.py`; private single-worker executor; visible-card editor polling | Managed leaf job.                                                                                     |
| Visual identities               | `visual_identity_pipeline_service.py`; private executor and inner workers; run and auto-approval UI    | Managed leaf job; retain explicit review decisions.                                                   |
| Table observations              | `observation_pipeline_service.py`; private executor; `ObservationRunControls.tsx`                      | Managed leaf job.                                                                                     |
| Round analysis                  | `round_analysis_service.py`; private async queue and worker; `RoundAnalysisControls.tsx`               | Managed leaf job with analysis/reconstruction steps.                                                  |
| Automated recording pipeline    | `automated_pipeline_worker.py`; private async queue; coordinator and `AutomatedPipelineControls.tsx`   | Managed parent job with scheduled child jobs.                                                         |
| Calibration preview calculation | `calibration_refinement_service.py`; calculation through synchronous request paths                     | Managed calculation job against an exact draft snapshot. Reads must not start expensive calculations. |
| Counterfactual reconstruction   | `round_analysis_api.py`; synchronous create-or-reuse route                                             | Managed calculation job; retain immutable correction and result semantics.                            |

Inventory every caller, including HTTP routes, coordinator, tests, and browser controls. Include
other request-bound expensive work if inspection proves it belongs to these flows. Record each
disposition. This epic does not convert every HTTP request into a job. Reads, edits, bounded cached
frame/crop retrieval, uploads, and short validation remain normal requests. Browser prefetch queues
and human review queues are different mechanisms.

## Queue decision

| Option                                             | Benefit                                                                      | Cost                                                                                      | Decision                                                                                        |
| -------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| One strict global FIFO worker                      | Simple order and low resource use                                            | One slow operation blocks all other work; parent/child execution can deadlock             | Use one processing slot initially, but do not make strict head blocking the scheduler contract. |
| Independent queues per job type                    | Separate type limits                                                         | Competing pools can overload the MacBook; no meaningful global reorder; duplicated policy | Do not retain separate schedulers.                                                              |
| One global ordered queue with resource constraints | One visible order, lifecycle, and fairness policy; explicit safe concurrency | Needs resource admission and clear waiting reasons                                        | Recommended design.                                                                             |

Use one durable queue and one scheduler owner per local operations root. Job types register their
handler, validated request schema, resource requirements, progress adapter, cancellation boundaries,
and retry/resume policy. They do not own queues or background lifecycle records.

Start with one processing slot. Parent coordination that is waiting for children consumes no
processing slot. Define bounded CPU-worker, accelerator, and external-service claims where a
handler needs them. Inner frame pools must respect the allocated budget. Do not add a cloud broker,
Redis, Celery, or a distributed worker system for the normal local loop.

Dispatch the earliest eligible queued job that fits the configured resource budget and domain
write locks. A job waiting for inputs or a resource does not block independent eligible work.
Expose its waiting reason. Preserve FIFO among equally eligible jobs unless the operator reorders
them. Do not automatically prefer a job type or pipeline children. Once an eligible job is waiting
for a resource, stop admitting later jobs that would repeatedly take that resource ahead of it.
M0 specifies deterministic resource reservation tests before enabling more than one processing slot.
Queue position is dispatch preference, not a promised start time or completion order.

## Job contract

### Identity, state, and steps

- Give every accepted job an opaque stable ID, type, display label, recording/context references,
  immutable validated request, exact input references, implementation/configuration references,
  creation time, creator/request correlation, and optional parent/step and retry-source IDs.
- Use one lifecycle: `queued`, `running`, `waiting`, `cancelling`, `succeeded`, `failed`,
  `cancelled`, and `interrupted`. The final four states are terminal. Terminal records do not
  return to an active state. `waiting` means accepted work needs a dependency or orchestration
  result; resource contention alone leaves a job `queued` with a waiting reason.
- Validate before acceptance. Invalid requests return an error without creating executable work.
  Change `queued` to `running` only when the scheduler claims execution. Record start/finish times,
  monotonic record revision, worker ownership, current phase, waiting reason, and structured failure.
- A leaf normally goes `queued → running → succeeded/failed`. A parent can go
  `running → waiting → queued` to continue coordination. Cancellation and restart transitions
  follow the rules below. Reject all other transitions through one state machine.
- Each job has ordered stable step IDs, labels, state, timestamps, optional completed/total units,
  unit name, message, failure, and optional child-job link. Step states are `pending`, `running`,
  `succeeded`, `failed`, `cancelled`, and `skipped`. Retain an interrupted step's recorded progress
  with an explicit interruption reason. Never report skipped work as completed processing.
- Progress can be unknown. Use counts only with a known denominator. Do not average unlike steps,
  invent an ETA, or show 100% while results are still publishing. UI can show “3 of 6 steps”.
- Execution success is separate from result quality. Valid empty results can succeed. Partial
  domain coverage stays explicit in a result summary with warnings and exact coverage. A required
  failed stage fails its parent; optional skipped work does not silently become success evidence.

The Job Manager owns execution lifecycle, queue order, cancellation, and progress. Processor runs
and analysis records retain domain identity, frozen inputs, provenance, result coverage, and output
references. They link to job IDs. Remove their competing mutable background lifecycle state after
cutover; derive any domain status response from the job instead. Data nodes, revisions, review,
accepted downstream use, and maintained references retain their own authority.

### Acceptance and storage

- Store jobs under the configured operations root, provisionally `jobs/<job-id>/job.json`.
  Store queue order and its revision in `jobs/queue.json`. Use repository filesystem storage
  primitives where applicable. Exact schema names and paths are frozen in M0.
- The job document contains request, steps, progress, result links, and latest structured failure.
  Keep domain output bytes in domain stores. Use a bounded per-job diagnostic log with stable
  sequence numbers for paginated retrieval. Routine progress writes must be rate-limited.
- Use atomic replacement, schema validation, and one writer/owner lock for the root. Refuse a
  second scheduler owner. An in-memory queue is only a reconstructible index. Persist order,
  cancel requests, parent links, and state before acknowledging their changes.
- A job request uses an idempotency key. Same key plus same normalized request returns the same
  accepted job; a different request returns conflict. Explicit repeated work uses a new key.
- Acceptance must durably record exact domain inputs and required accepted downstream use before
  work is dispatchable. Do not claim that several file renames form one transaction. M0 defines
  an acceptance intent/recovery protocol for job, domain-run, and downstream-use writes. No crash
  may expose an executable job without its protected inputs or create duplicate work on retry.
- Queue membership and order must also recover if a crash separates job and queue writes. New
  durable queued jobs cannot disappear from scheduling. Unknown or damaged records produce a
  visible diagnostic; never silently discard them or dispatch unvalidated work.
- Completion publishes durable result references before marking success. Reconcile a crash between
  result publication and terminal state using deterministic output identity and validation. Do not
  infer success from a file name or publish the same revision twice.
- Retain terminal job metadata by default. Bound logs separately. Deleting domain artifacts is
  outside queue management; missing results remain an explicit broken/unavailable link. No automatic
  deletion of historical jobs or domain data in this epic.

### Cancellation, retry, reorder, and restart

- Cancelling a queued job prevents it from starting and records `cancelled`. Cancelling running
  work records `cancelling`; the UI states that it is waiting for a safe stop. Add cooperative
  checks between bounded units and before publication. Do not claim a Python thread has stopped
  when only its future was cancelled. Retain resource claims until execution actually stops.
- An uncancellable library call can finish before cancellation takes effect. Show this limitation.
  If bounded termination needs a subprocess, isolate that handler and test cleanup locally. Do not
  kill the backend process to cancel one job.
- Serialize cancellation against result publication. If cancellation wins before publication,
  stop and do not publish a new completed output. If validated publication has already committed,
  report the actual terminal outcome and that cancellation arrived too late. Preserve completed
  outputs and diagnostics; cancellation does not undo accepted downstream use or human edits.
- Cancelling a parent stops further child creation and cancels its owned active children. The
  parent is not terminal until they have stopped. Do not share executable children across parents
  in this epic. Existing completed results can be referenced through exact inputs.
- Retry is explicit and creates a new linked job and execution attempt. Preserve the previous
  job's outcome. Freeze inputs again from exact references, never from “latest”. Reuse only
  verified completed checkpoints where the handler declares that policy. No automatic retry loop.
- Reorder only queued work. Use a move-before operation with the expected queue revision. Stale
  revisions return conflict plus current order. Dependencies and resource limits still apply.
  Reordering is not preemption. Completed and running work cannot be moved.
- Show parent jobs as groups. Child steps retain dependency order and cannot be dragged into an
  invalid sequence. Moving a queued group changes the dispatch preference of its queued children
  together; a waiting parent can use that group action even though it is not itself executable.
  M0 freezes a precise group-order representation and concurrent enqueue/reorder examples.
- On restart, retain queued order and cancellation requests. Reconcile previous active ownership
  before dispatch. Leaves without a verified completion/checkpoint become `interrupted`, not
  silently successful or automatically restarted. A parent can resume coordination only when
  child IDs and durable checkpoints prove no duplicate execution. An interrupted required child
  makes its parent interrupted. Explicit retry creates a new parent attempt with verified
  completed-step references and new child attempts. Link the same logical steps across attempts;
  never mutate a terminal parent back to running.
- Graceful shutdown stops dispatch, persists state, and gives active handlers a bounded safe-stop
  period. A forced stop is resolved by the same restart rules. Browser closure never cancels work.

## HTTP API

Use one typed `/api/jobs` resource for management. The following endpoints are the proposed contract;
M0 freezes their schemas and error responses. Generate browser types from OpenAPI.

| Method and path              | Purpose                                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `POST /api/jobs`             | Validate and enqueue a registered job type; require an idempotency key; return `202`, job, and `Location`.  |
| `GET /api/jobs`              | Cursor-paginated list; filter by state, type, recording, parent, and active/history; return queue revision. |
| `GET /api/jobs/{id}`         | Full state, steps, progress, capabilities, exact context/results, and record revision.                      |
| `POST /api/jobs/{id}/cancel` | Idempotent cancel request; return current state, including too-late outcome.                                |
| `POST /api/jobs/{id}/retry`  | New linked job with a new idempotency key; reject unsupported/invalid retries.                              |
| `POST /api/jobs/queue/move`  | Move a queued job/group before a target or to the end; require queue revision.                              |
| `GET /api/jobs/{id}/logs`    | Bounded diagnostic pages after a sequence number; report truncation.                                        |

Return explicit capabilities and reasons for disabled cancel, retry, and reorder commands. Use
consistent not-found, invalid-request, invalid-transition, and revision-conflict errors. Request
disconnects do not stop accepted work. Validate job type, context IDs, and result-link targets;
do not accept arbitrary executable names, filesystem paths, or navigation URLs.

Domain-specific forms remain responsible for input selection and validation feedback. They submit
typed jobs and get a job ID; all lifecycle and management actions use the common API. Domain result
and data APIs remain. Remove old enqueue/status/retry API paths after their callers switch, rather
than keeping compatibility facades. Embedded processor algorithms do not call HTTP to schedule
children; orchestration uses the same application service as HTTP.

Job-start workflows are outside this epic. Do not redesign where or how operators launch work,
choose processors, models, inputs, or exact revisions, configure parameters, or resolve missing
prerequisites. Keep existing launch forms and choices. Integrating their submission with the shared
enqueue service is in scope, including validation and exact-input recording. The Jobs drawer has
no generic New job form or input picker. Explicit retry of a frozen request remains in scope;
changing its inputs or configuration belongs to a separate job-start workflow.

Start with one shared browser polling client. Poll active work at a bounded interval, back off on
failure, stop unnecessary polling for hidden pages, and refresh on return. Paginate history and
detail/log requests. Preserve last-known data and show disconnection/staleness. Late responses
cannot overwrite newer record revisions. SSE/WebSockets are optional later work, not a prerequisite.

## Parent jobs and domain boundaries

An automated pipeline is a parent job. Its existing ordered stage graph and failure/empty-result
rules remain owned by the pipeline contract. Each scheduled stage is a child job linked to a stable
parent step. Completed children are reused only with verified exact inputs and output references.
Persist child creation idempotently before dispatch; restarting coordination cannot enqueue it twice.
The waiting parent holds no execution slot, CPU budget, accelerator claim, or domain write lock
needed by its children. No worker blocks while polling another job that needs its only slot.

Leaf handlers execute processor logic directly under manager ownership. Remove their private
background executors and lifecycle recovery loops. Bounded algorithm-internal parallel work can
remain within its allocated budget. Domain result publication still validates input revisions,
calibration, review applicability, and current write preconditions. A completed job does not select
a result for inspection, change a maintained reference, accept review, or grant dataset eligibility.

Calibration preview jobs freeze draft and evidence digests. Editing while a calculation runs must
not let a stale preview replace a newer one. Applying a preview remains an explicit domain command
with its existing digest and conflict checks. Counterfactual jobs freeze correction constraints
and exact analysis inputs; viewing a result does not apply corrections to upstream evidence.

0107 owns data/provenance contracts. 0108 owns lineage navigation and its data cutover. 0109 owns
the central frame surface and inspector/rail layout. This epic owns global execution and job UI.
Integrate the current owning APIs at each milestone; do not require these epics to finish merely
to add the job foundation, or introduce a second lineage migration. Preserve domain history and
output artifacts. M0 defines how old execution-only status records remain inspectable without
inventing precise progress or restarting historical work. No compatibility API or dual scheduler.

## Global Jobs drawer

Add a Jobs button to persistent application chrome above recording-specific navigation. Show
running and queued counts, and a failure indicator since the operator last inspected failures.
It is available from the recording list, any recording, review routes, and job detail routes.

Open a full-width drawer below the app header, inspired by a global queue panel. On desktop it
expands the layout downward and leaves the current workspace available below. It does not cover
the frame with controls. Constrain drawer height and scroll its content. Keep it separate from
0108's lineage drawer: Jobs answers “what is executing”; lineage answers “which data am I viewing”.
Both can be open. On narrow screens use a labelled accessible sheet with focus handling and a
clear close action. Closing the drawer preserves work, filters, and current workspace selection.

```text
App header                               Jobs [1 running · 3 queued]
-------------------------------------------------------------------
Jobs       Active | History        Recording: All     Type: All
Running    Pipeline · Recording A     2/6 steps       Cancel  Details
             Visible cards            18/90 frames    Open step
Queued  1  Events · Recording B        Waiting        Move    Cancel
Queued  2  Identities · Recording C    CPU busy       Move    Cancel
History    Failed · Recording D       Reason          Retry   Details
-------------------------------------------------------------------
Recording navigation and lineage drawer
Current workspace
```

- Active shows running/cancelling work, waiting parent groups, and ordered queued jobs. History
  shows terminal work with filters. Expand parents to see steps and all attempts, without counting
  parent and child work twice in the header. Show resource/dependency waiting reasons plainly.
- Rows show name/type, recording context, state, step/count progress, elapsed time, and relevant
  actions. Use text and icons as well as color. No guessed completion times.
- Details open a stable `/jobs/{id}` route with exact request/input references, steps, warnings,
  failures, log pages, and links to domain results. “Open results” navigates to exact saved output,
  including the 0108 lineage route when available. Multiple outputs have separate links. Missing
  results show an explanation, never a fallback to another run's latest output.
- Reorder supports drag-and-drop plus keyboard-accessible Move up/down or Move before controls.
  Refresh on queue conflicts and explain why a move was rejected. Never optimistically claim a
  running job was preempted. Confirm state from the server for all management actions.
- Existing processor buttons keep their domain forms. After acceptance show a compact linked job
  status and an Open Jobs action. Use the shared client and status components everywhere. Remove
  local polling loops, queue lists, and duplicate cancel/retry/progress widgets after cutover.
- Do not auto-navigate on completion. Show a restrained completion/failure notice with a result or
  detail link. Preserve the operator's recording, lineage, time cursor, edits, and focus. Announce
  meaningful state changes accessibly without announcing every progress update.

## Milestones

Each milestone is one bounded implementation phase. Use local fixtures and fake handlers. Commit
each completed milestone to main, update the epic and board, and report all milestone states.

### M0 — Freeze inventory and execution contract — Complete

Verify every in-scope producer and caller. Record lifecycle mappings, domain write boundaries,
checkpoint policies, cancellation limits, resource claims, old-history treatment, API schemas,
acceptance recovery protocol, and group reorder rules in a short report. Define fixture cases.

Acceptance: no in-scope asynchronous producer is unassigned. Decisions cover partial/empty results,
preview staleness, parent retries, resource fairness, and crashes between each acceptance write.
No real jobs, data migration, or runtime changes in this milestone.

### M1 — Add durable job records and lifecycle — Complete

Implement typed records, state transitions, root ownership, atomic writes, idempotency, and queue
index reconciliation. Add the acceptance intent mechanism and fake domain-store participant.

Acceptance: restart/crash fixtures prove no lost accepted job, unprotected execution, duplicate
acceptance, invalid terminal transition, or simultaneous scheduler ownership.

Result: [M1 storage and recovery](../../reports/0110-M1_Job_Storage.md).

### M2 — Add the scheduler and resource admission — Complete

Implement persistent order, single-slot default, resource claims, bounded handler budgets,
waiting reasons, queue moves, revision conflicts, and deterministic fairness policy.

Acceptance: fake jobs prove actual dispatch state, blocked-head bypass, resource exclusivity,
budget limits, conflict handling, and stable order after restart. No real model execution needed.

Result: [M2 scheduler and resource admission](../../reports/0110-M2_Scheduler.md).

### M3 — Add cancellation, retry, and recovery — Complete

Implement cooperative cancellation tokens, publication arbitration, new linked retry attempts,
checkpoint declarations, restart reconciliation, and bounded graceful shutdown.

Acceptance: fixtures cover enqueue/cancel races, cancel during a library call, late cancel,
result-publication crash, interruption, and retry without duplicate outputs or leaked claims.

Result: [M3 cancellation, retry, and recovery](../../reports/0110-M3_Cancellation_Recovery.md).

### M4 — Expose the unified HTTP API — Complete

Add job list/detail, enqueue, cancel, retry, move, and paginated log routes. Register fake types
for tests. Generate browser contracts and test validation and error responses.

Acceptance: API tests cover idempotency, filters, pagination, capabilities, concurrent moves,
unknown types, disconnect after acceptance, and unavailable results.

Result: [M4 unified job HTTP API](../../reports/0110-M4_Job_HTTP_API.md).

### M5 — Connect event processing as the first leaf — Complete

Adapt the event processor to manager ownership, accepted-use recording, progress, cancellation,
and domain output publication. Switch its callers and remove its private background executor.

Acceptance: recorded/fake-provider runs succeed, fail, cancel, retry, and restart through jobs;
exact inputs and completed output references remain valid. No second event queue remains.

Result: [M5 event processing](../../reports/0110-M5_Event_Processing.md).

### M6 — Connect visible-card processing — Complete

Adapt visible-card processing and its frame workers. Enforce the allocated worker budget and add
safe cancellation checks. Preserve valid empty detections, piles, coverage, and failure details.

Acceptance: fixture runs verify bounded inner concurrency, partial/empty outcomes, cancellation,
and exact domain outputs. Existing focused processor tests pass.

Result: [M6 visible-card processing](../../reports/0110-M6_Visible_Card_Processing.md).

### M7 — Connect proposed card scenes — Complete

Adapt scene processing, progress, and safe stopping. Preserve exact frame/calibration inputs,
uncertain outcomes, and output validation. Remove its private scheduling and recovery path.

Acceptance: fixture jobs preserve scene semantics and diagnostics, including failed and empty
frames; cancelled work cannot publish an unvalidated completed result.

Result: [M7 proposed card scenes](../../reports/0110-M7_Proposed_Card_Scenes.md).

### M8 — Connect visual identities — Complete

Adapt identity processing and inner workers. Report bounded progress and unusable/failed crop
outcomes. Connect auto-approval's processing dependency without changing explicit review authority.

Acceptance: exact crop inputs, partial coverage, and human decisions retain their meanings.
Cancellation and retry do not duplicate completed outputs or exceed the worker budget.

Result: [M8 visual identities](../../reports/0110-M8_Visual_Identities.md).

### M9 — Connect table observations — Complete

Adapt observation assembly, progress, publication, and cancellation. Remove its private executor.

Acceptance: multi-input fixtures retain provenance and valid zero-card observations. Failed or
missing evidence remains distinct; accepted input protection and retries are verified.

Result: [M9 table observations](../../reports/0110-M9_Table_Observations.md).

### M10 — Connect round analysis — Not started

Replace the analysis queue/worker with a handler and job steps. Preserve exact observations, round
facts, rules, search limits, immutable results, and diagnostics.

Acceptance: local analysis fixtures cover analysis/reconstruction phases, failure, safe-stop
limits, cancellation, interruption, and retry. No private analysis scheduler remains.

### M11 — Connect automated pipelines as parent jobs — Not started

Replace the automated worker queue with durable coordination and scheduled child jobs. Preserve
the pipeline's stage graph, verified completed-stage reuse, and required failure/empty rules.

Acceptance: a full fake pipeline completes with one processing slot. Crash/restart cannot create
duplicate children. Parent cancel waits for owned children; explicit failed-stage retry keeps
history. Independent jobs remain schedulable between eligible stages.

### M12 — Connect calibration and counterfactual calculations — Not started

Move expensive preview and counterfactual calculations behind registered jobs. Keep reads free of
expensive calculation and retain explicit apply/commit commands. Switch their existing callers.

Acceptance: a preview for an old draft cannot replace current evidence or be applied as current.
Counterfactual retries preserve exact constraints and immutable results. Both support job details,
failure, cancellation limits, and exact result navigation with local fixtures.

### M13 — Add the shared browser job client and details — Not started

Implement one app-level state/polling owner, reusable status/action components, and `/jobs/{id}`.
Add bounded list/detail/log loading and validated exact-result navigation.

Acceptance: multiple consumers share polling; late responses, disconnection, hidden-page return,
history pagination, reload, and browser back/forward preserve correct job state and links.

### M14 — Add the global Jobs drawer — Not started

Add persistent app chrome, counts, active/history lists, parent expansion, filters, management
actions, accessible reorder, and narrow-layout behavior. Use the shared client and details route.

Acceptance: the drawer works on every existing app route. Keyboard/focus tests and desktop/narrow
browser checks cover empty, queued, running, cancelling, disconnected, and failed states. The
drawer can coexist with lineage navigation without covering central frame controls.

### M15 — Remove duplicate UI and execution contracts — Not started

Replace remaining per-feature polling/status/action UI with shared job components and links.
Remove obsolete lifecycle endpoints, service pools, worker loops, and browser types. Apply the
M0 history treatment without changing domain output bytes, review decisions, or sealed artifacts.

Acceptance: source inventory has no in-scope private background scheduler or independent job
poller. All launch paths return job IDs. Existing domain result routes and retained history remain
inspectable. No compatibility facade, dual write, or second lineage cutover remains.

### M16 — Verify the complete local workflow and close — Not started

Run a mixed-recording fixture workflow covering leaf and parent jobs, reorder conflicts, cancel,
restart, retry, failures, and exact result navigation. Publish the ownership and operator handoff.

Acceptance: relevant backend tests, web tests, lint/format/type checks, generated API verification,
and focused browser checks pass. Demonstrate bounded MacBook resource use without cloud services,
phones, full training, or sealed evaluation. Record any baseline failures separately. Close only
when every in-scope producer and UI path uses the shared manager.

## Scope limits

Job-start UX, processor/input/model selection, parameter configuration, new launch controls,
and automatic selection of prerequisites are out of scope. Existing launch controls only change
their submission and job-status integration. Plan future launch workflows in a separate epic.

No distributed execution, multi-host scheduling, arbitrary user scripts, recurring schedules,
automatic retries, pause/resume of arbitrary native calls, model training campaign, new processor
algorithms, or automatic review/reference changes. Global queue pause, bulk destructive history
cleanup, and configurable priority classes are deferred. The design must permit later job types
without another lifecycle or drawer implementation.
