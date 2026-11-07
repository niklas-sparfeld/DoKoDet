# Interactive UI and backend startup performance

## Plan status

- **Status:** In Progress
- **Depends on:** Existing local backend, web UI, and filesystem storage. No unmet epic dependency.
- **Outcome:** Every endpoint used by the interactive UI has repeatable speed coverage. Backend
  startup has repeatable process measurements. A frozen hard-data corpus, baseline, regression
  gates, and two bounded improvement cycles make later performance changes measurable.

## Problem and evidence

Interactive delays need one shared measurement system. Small unit fixtures and isolated service
measurements do not establish the time that a person waits for an HTTP response or a usable page.
Backend startup must also be measured, including work deferred until the first useful request.

Source inspection on 2026-11-07 identifies these starting points:

- [Browser API client](../../../web/src/api/client.ts): UI traffic includes both `/v1` and `/api`,
  job polling and controls, revision selection, review writes, derived images, and video URLs.
  Client methods alone are not a complete inventory: inspect other callers and browser traffic.
- [Recordings API](../../../backend/src/dokodetector_backend/recordings_api.py): the recordings
  list assembles the recording catalog and pipeline statuses before response serialization.
- [Workspace service](../../../backend/src/dokodetector_backend/pipeline_workspace_service.py),
  [revision storage](../../../backend/src/dokodetector_backend/pipeline_store.py), and
  [node storage](../../../backend/src/dokodetector_backend/pipeline_node_store.py): listing,
  filesystem reads, lineage validation, and response assembly are profiling candidates.
- [Jobs API](../../../backend/src/dokodetector_backend/jobs_api.py): history filtering and sorting
  occur before pagination. Test growth in unrelated history as well as the returned page size.
- [Application factory](../../../backend/src/dokodetector_backend/app.py): application creation,
  provider configuration, service startup, and recovery need separate startup measurements.
- [Backend test factory](../../../backend/tests/app_factory.py) provides explicit local analyzer
  injection. Existing [Playwright configuration](../../../web/playwright.config.ts) starts the
  preview server; existing browser fixtures include intercepted API responses. Add a dedicated
  real-backend performance configuration rather than interpreting mocked browser tests as HTTP
  latency evidence.

These are hypotheses and integration points, not measured bottlenecks. This planning change does
not establish current timings, select a fix, or claim that a hard-data corpus already exists.

Coordinate with active 0109 working-area changes, 0112 module cleanup, and 0113 launch UX. Record
coverage changes as those paths change. They do not block measurement of the current application.
Coordinate measurement coverage with the surviving 0112 cleanup plan.

## Scope

Measure all backend endpoints that serve interactive UI actions: list and detail reads, workspace
and lineage views, result and comparison reads, frame and crop images, thumbnails, video range
requests, review and selection writes, imports or uploads exposed by the UI, and job submission,
status, logs, cancellation, retry, and queue controls. Measure synchronous request work for job
submission; job completion duration is a different metric. Include relevant success, empty,
not-found, stale-revision, and conflict paths. Avoid a combinatorial test of every invalid input.

Enumerate endpoints by HTTP method and route template. Cover relevant query and payload variants,
not only one request per template. Include routes outside OpenAPI, media URLs used by HTML
attributes, and same-origin proxy paths. Explicitly classify non-UI routes and infrastructure
routes. No UI-serving endpoint may be excluded merely because it is expensive or difficult.
Static web delivery belongs in browser workflow timings; it need not become a Python route test.

Measure backend startup from fresh process launch to readiness and from launch to the first
successful, representative recordings/workspace response. Also record factory construction,
lifespan initialization, recovery, and first-use costs where instrumentation permits. Measure
startup with empty storage, hard populated storage, and deterministic interrupted-job recovery.
Use the normal local backend launch path. Verify a ready backend can actually answer requests.

Do not add cloud dependencies, require a phone, benchmark model quality, or optimize background
inference in this epic. Use deterministic local job handlers for controlled contention and
recovery. Normal import, validation, scheduler, serialization, storage, and media paths must stay
real. Do not stub away a cost and then report its absence as an improvement.

## Measurement and data contract

### Endpoint coverage and hard data

Maintain a machine-readable inventory with method, route, UI caller/workflow, scenario, fixture,
measurement tier, cache mode, and budget key. Reconcile registered routes, browser call sites, and
observed requests. An automated coverage check must fail for unclassified routes, missing cases,
and UI requests with no speed scenario. A new endpoint cannot silently escape the suite.

Find difficult data by first inventorying metadata and file sizes in exact storage roots. Do not
recursively parse all retained operation artifacts as a discovery shortcut. Rank cases by recording
count, nodes and revisions, lineage depth and fan-out, items per result, polygon/identity payload
size, review draft size, job/history/log count, video dimensions/duration, and derived-cache state.
Retain the measured dimensions and selection reason for each chosen case.

Use two reproducible sources:

1. Small, valid snapshots derived from the hardest observed local examples, with exact source
   references, hashes, schema versions, and all required lineage/media dependencies.
2. Seeded valid generated datasets that independently scale expensive dimensions. Include small,
   representative, hard, and stress sizes. Freeze numeric sizes after the inventory, before the
   baseline; do not choose sizes solely because they are fast on the current implementation.

Cover many unrelated recordings/revisions/jobs, one large recording, deep/shared lineage, large
review and result payloads, cold/warm derived images, bounded video ranges, and growing job history.
Include valid empty and sparse states. Test relevant corrupt matching resources as correctness
cases; filtering unrelated resources must never relax validation of matching content.

Publish a fixture manifest and a deterministic materializer. Keep compact manifests and generators
in Git; retain larger assets at a documented content-addressed local location. A clean checkout
must run the generated tier without access to the developer's data. Missing required assets must
fail the full qualification command with a useful diagnostic, not silently skip hard cases.
Never benchmark writes against live review data. Reset a disposable clone between write samples.

### Timing protocol

Use a monotonic clock. Separate setup, fixture materialization, server startup, measured requests,
and cleanup. Retain raw samples, status codes, response byte counts, and correctness results.
Measure full HTTP response completion including serialization and body consumption. For media,
record first-byte and bounded transfer completion separately; do not require an entire video
transfer to meet a JSON response budget. For uploads, state the fixed payload size and separate
transfer time from response completion after the final byte.

Use two endpoint tiers: controlled in-process HTTP tests for repeatability and real loopback HTTP
against an isolated backend process for qualification. Browser scenarios add page-to-usable-view
and action-to-updated-view timings, request count, and request waterfall evidence. API routes in
these scenarios must use the real backend. Browser cache and server derived-view cache are separate.

For each warm endpoint scenario, use at least 5 unmeasured warmups and 30 measured requests per
batch, with 3 independent batches. Report median and p95 per batch and across retained samples.
Process-cold endpoint measurements use at least 10 fresh processes; startup uses at least 10
fresh launches per profile. Report all cold samples and medians/maxima; do not present a p95 from
10 samples as a stable tail estimate. Measure browser scenarios at least 10 times with fresh
contexts and report the full distribution. M2 may increase counts where variance requires it.

Define cold precisely: a new backend process, empty application caches, and a declared derived
cache state. Do not call this a cold OS filesystem cache. Do not flush machine-wide caches.
Record OS, hardware, tool versions, commit, fixture digest, launch command, worker configuration,
cache policy, sample counts, background load, and run order. Run sequentially on a documented
local Mac profile; do not compare timings across dissimilar machines as a regression verdict.

Add one controlled load profile with job polling and fake background work while reading, saving,
and loading media. Bound concurrency and request rate. Report errors and timeouts as failures,
not dropped timing samples. Verify cache invalidation after revision changes, saves, and restart.

### Regression policy and candidate selection

Keep a versioned baseline with raw results and per-scenario budgets. M11 derives absolute ceilings
and relative regression tolerances from repeated measurements and user-visible delay. Use both
relative change and an absolute noise allowance, so a tiny endpoint does not fail for negligible
jitter. Set separate budgets for JSON/control paths, cold derived media, transfers, browser actions,
and startup. Do not invent one latency ceiling for every operation.

Separate present speed from the desired budget. Record existing slow cases as explicit performance
debt with target, measured gap, and candidate. Do not silently give each slow endpoint an acceptable
budget equal to its current time. Gate regressions against the frozen baseline immediately, then
ratchet budgets when verified improvements land. Keep original baseline evidence. A baseline
refresh requires a reviewed explanation and before/after comparison; tests must never update it.

Fast deterministic coverage, correctness, and operation-count checks run in the normal test loop.
The isolated timing suite is a separate local command with finite runtime and machine-readable
exit status. Document when to run the full suite before performance-sensitive commits. Connect
it to existing automation only where the runner profile supports meaningful timing comparison.
A deliberately slowed fixture handler must make the regression comparator fail. A correctness
failure must fail the run even when the response is faster.

Rank candidates by measured user wait, frequency/request fan-out, p95, startup impact, scaling,
confidence, effort, and correctness risk. Retain a profile and named hard case per candidate.
Investigate storage enumeration, repeated parsing/validation, response size, pagination work,
cache misses/invalidation, lock contention, and eager startup work only when evidence supports them.
Deferring startup cost to the first UI request is not an improvement unless both metrics pass.

## Milestone status

- **M0:** Complete — inventory registered routes, browser callers, and startup phases.
- **M1:** Complete — bounded hard-data examples and seeded fixtures pass production schema and lineage validation.
- **M2:** Complete — controlled endpoint and startup timing harness.
- **M3:** Complete — add named catalog and evidence JSON read cases with preliminary generated-empty and hard-snapshot samples.
- **M4:** Complete — cover pipeline workspace, lineage, revision, review, and calibration reads.
- **M5:** Complete — cover pipeline run, selection, result, and comparison reads.
- **M6:** Complete — cover job history, polling, detail/status, logs, and calibration-preview reads.
- **M7:** Complete — add durable timing and correctness cases for interactive writes and controls.
- **M8:** Complete — measure eight residual real-backend write routes and durable effects.
- **M9:** Complete — add named real-backend media cases and verify cold/warm and saved-review, revision, and restart cache behavior.
- **M10:** Complete — seven real-process Playwright scenarios passed across 70 fresh contexts; 10 backend startup processes passed. See the [M10 report](../../reports/0114-M10_Real_Process_Browser_and_Load.md).
- **M11:** Not started — run the complete corpus in three independent sessions and freeze budgets and regression gates.
- **M12:** Not started — profile and rank candidates, then implement candidate cycle one.
- **M13:** Not started — implement candidate cycle two, qualify the full suite, and close the epic.

## M0 — Inventory routes and startup phases

- Create the route/scenario inventory from backend registration, UI callers, and bounded browser
  traces. Include every method, media path, and interactive write. Explain all non-UI exclusions.
- Map actual launch, readiness, service startup, recovery, and first-use paths. Define readiness
  probes, startup profiles, environment isolation, and watchdog/cleanup behavior.
- Add the inventory consistency check. Record current tests, commands, and baseline check failures
  in an M0 report. Acceptance: every current UI route has a planned case and no unknown route
  classification remains. Later coverage milestones replace planned cases with executable ones.

## M1 — Discover and freeze hard data

- Run the bounded metadata inventory. Record observed extremes and select exact local examples.
- Add the hashed manifest, seeded materializer, and disposable storage recipe. Validate all
  schemas, dependency closure, exact revisions, and media identities before timing them.
- Acceptance: generated fixtures reproduce on a clean checkout; local snapshots verify by hash;
  the report lists numeric sizes, selection evidence, asset locations, and reconstruction commands.
  Missing assets and invalid lineage fail clearly. No live data or review authority changes.

## M2 — Build the endpoint and startup timing harness

- Add controlled HTTP and isolated loopback runners with raw result export and process startup
  profiles. Record measurement metadata, warmup policy, cache resets, and finite timeouts.
- For each controlled HTTP case, run five warmups and 30 measured requests in each of three
  isolated batches. For each startup profile, run ten fresh backend processes. Record a full JSON
  response and, for hard storage, a bounded media range with loopback first-byte and completion
  timings.
- Acceptance: repeated runs follow this protocol; process cleanup works after errors/timeouts;
  startup and deferred first-use costs are visible. Export raw samples and per-batch distributions.
  Comparator tests detect injected slowdown, incompatible fixture/machine profiles, and invalid
  responses. No baseline gate is enabled yet.

## M3 — Cover catalog and evidence reads

- Implement executable scenarios for the UI JSON reads in the `/v1` catalog, recording,
  repository-bundle, round-analysis, counterfactual, timeline, table-observation, and evidence
  package families. Include relevant success, empty, and not-found cases from the inventory.
- Use generated data and the frozen hard snapshot where it applies. Check response identity and
  correctness as well as full response timing. Do not measure media routes here.
- Acceptance: every in-scope inventory row has a named speed and correctness case; the coverage
  check reports no missing case for these families. Focused pytest and Ruff pass. Retain preliminary
  samples only; do not call them a baseline.

## M4 — Cover pipeline workspace and revision reads

- Implement scenarios for workspace and lineage reads, node revision content and review reads, and
  calibration-refinement snapshots. Include full and stage-filtered workspace queries, maximum
  identity and polygon payloads, and relevant missing/stale cases from the inventory.
- Use real storage, lineage validation, and response serialization. Exercise declared cold and warm
  server-cache states. Do not write reviews or measure derived media here.
- Acceptance: every in-scope inventory row has a named speed and correctness case; returned node,
  revision, and parent identities match the frozen fixture. Focused pytest and Ruff pass. Retain
  preliminary samples only.

## M5 — Cover pipeline run and result reads

- Implement scenarios for pipeline run lists, selected runs, run details and results, comparison
  reads, and other inventoried stage result JSON. Include valid sparse/empty responses and relevant
  missing or stale-revision cases. Use hard result and lineage sizes where available.
- Check exact selected run and result identities. Include query variants and response correctness;
  do not cover review writes or derived media.
- Acceptance: every in-scope inventory row has executable speed and correctness coverage and passes
  the inventory coverage check. Focused pytest and Ruff pass. Retain preliminary samples only.

## M6 — Cover job history and polling reads

- Implement scenarios for job history, detail/status, logs, and calibration preview reads used by
  the UI. Seed valid jobs with the production model. Increase unrelated history, check page
  boundaries and cursor correctness, and include relevant missing or wrong-type cases.
- Measure synchronous response work only. Job completion time is outside this milestone. Do not
  add job writes or simulated background contention here.
- Acceptance: every in-scope inventory row has executable speed and correctness coverage; history
  page content and cursors remain correct as unrelated records grow. Focused pytest and Ruff pass.
  Retain preliminary samples only.

## M7 — Cover interactive writes and controls

- Measure pipeline node edit/copy/restore and item, coverage, and overall review writes; selection
  changes; pipeline-run submission; job submit/cancel/retry/queue controls; frame-review save; and
  calibration draft start/update/discard. Include the unregistered UI video URL as an explicit
  not-found boundary case. These are the M7 write families; do not claim coverage for another
  route without a named executable case.
- Use resettable fixture storage. Measure the complete HTTP response for each write scenario, then
  read back exact content, lineage, selection revision, queue state, job parent, or analysis identity.
  Keep unrelated fixture state isolated. Record the known UI write routes not covered by M7 for M8.
- The M0 browser URL `/api/recordings/{recording_id}/video` has no registered route or request
  constructor. Measure its observable not-found response as an inventory boundary; do not create a
  backend contract for it.
- Acceptance: every M7 case has an executable named timing and durable correctness check. The
  combined M7 and M8 gates cover all inventoried UI write routes. Focused tests, lint,
  format, and applicable type checks pass; verify generated API output if contracts change. Retain
  preliminary samples only.

## M8 — Cover residual write APIs

- Add named real-backend API timing and durable readback cases for M7's remaining UI writes:
  event, visible-card, proposed-card-scene, visual-identity, and observation stage submissions;
  both round-analysis intake routes; and calibration apply. Build each request from exact upstream
  revisions in resettable storage and verify its persisted run, analysis, calibration, and lineage.
- Acceptance: hard fixtures work through real HTTP handlers. Every residual stage submission,
  round-analysis intake route, and calibration apply has a named speed and durable readback case.
  Focused checks pass. Retain preliminary samples only; do not call them a baseline.

## M9 — Cover media routes and cache invalidation

- Depends on: M0–M8 route inventory, frozen fixture and timing harness, and existing read/write cases.
- Add named real-backend timing and correctness cases for every inventoried media route: frame, crop,
  thumbnail, video snippet, bounded video range, and media identity reads. Include the registered
  source-video route and document the unregistered `/api/recordings/{recording_id}/video` UI URL as
  an explicit 404 boundary; do not use that 404 as a media performance result.
- Verify cold and warm server derived-view behavior and invalidation after saved edits, revision
  changes, and backend restart. Keep browser cache out of these API checks; M10 measures it.
- Acceptance: each inventoried media route has named real-backend speed and identity/correctness
  coverage. Cold/warm, save, revision, and restart cases verify exact returned media identity and
  cache behavior. Focused tests, lint, and format checks pass. Retain preliminary samples only.

## M10 — Cover real-process browser workflows and controlled load

- Depends on: M9 media identities and cache behavior.
- Add a dedicated real-process Playwright configuration and workflows for recordings-to-workspace,
  displayed revision switching, frame/crop navigation, review save, Jobs drawer/history, and job
  submission-to-visible-status. Run each workflow at least 10 times with fresh browser contexts.
  Include real video-range traffic. Verify visible data identity, usable controls, actual request
  counts, waterfalls, startup, and browser/server cache behavior.
- Add bounded polling and deterministic background work while reads, writes, and media loads run.
  Keep uncontended and controlled-load results separate.
- Acceptance: all six workflows and controlled-load cases pass against an isolated real backend;
  their visible identities, controls, request counts, waterfalls, and cache modes are retained.
  Focused browser, backend, lint, format, and applicable type checks pass. Samples remain
  preliminary until M11.

**Complete.** Seven scenarios passed: the six requested browser workflows and controlled load.
Each scenario ran in 10 fresh contexts. Ten fresh backend processes passed startup, readiness,
catalog, and exact-workspace probes. The [M10 report](../../reports/0114-M10_Real_Process_Browser_and_Load.md)
records all checks, distributions, cache distinctions, and limits. The fixture is compact and
generated, so these samples do not replace M11's full-corpus runs or enable a baseline gate.

## M11 — Run the full corpus and freeze the baseline

- Depends on: M9 media suite and M10 real-process browser and controlled-load suites.
- Run the complete endpoint corpus, all startup profiles, media routes, browser workflows, and
  controlled-load suite in three independent sessions on the declared local machine profile.
  Keep uncontended and controlled-load results separate.
- Publish raw samples, a readable baseline table, measured noise, absolute ceilings, relative
  tolerances, finite suite runtime, and explicit slow-case debt. Enable the comparator and coverage
  gates. Confirm an injected slowdown fails through the real suite command.
- Acceptance: every UI endpoint and startup profile has a reproducible baseline and budget key.
  Missing cases/assets, invalid responses, timeouts, and incompatible profiles cannot return a
  passing qualification result. Separate environment failures from measured regressions.

## M12 — Profile candidates and candidate cycle one

- Depends on: M11 frozen baseline and regression gates.
- Profile the highest-cost measured cases, including startup. Attribute time to specific work;
  retain bounded traces and operation counts. Create a ranked candidate table with baseline,
  affected routes, expected gain, risk, verification command, and stop condition.
- Select at most two small changes for M12/M13. Select a startup change if startup is a leading
  measured source of delay; do not force a startup rewrite without evidence. Freeze a numeric
  improvement target for cycle one before implementation. Reserve one untouched hard case per
  affected family.
- Add a targeted regression case, implement cycle one, then rerun the same cold/warm, startup, and
  affected browser scenarios on the frozen corpus and machine profile.
- Acceptance: cycle one meets its predeclared gain and all correctness/budget gates on affected and
  reserved cases. Verify restart and invalidation for cache changes. Revert unsuccessful changes
  and record evidence. Update the ranking and select or confirm cycle two.

## M13 — Candidate cycle two, full qualification, and closure

- Depends on: M12 candidate ranking and cycle one results.
- Implement the next highest-value bounded candidate using the current ranking. Compare with both
  the original baseline and the result after cycle one. If no safe candidate remains, publish the
  measurements and exact stop reason instead of implementing an unmeasured change.
- Run the complete endpoint, startup, contention, and browser suite from the documented setup.
  Reconcile route coverage after concurrent UI work. Run applicable backend/web checks and local
  Markdown link checks. Record unrelated baseline failures separately.
- Publish before/after results, retained gains, unsuccessful experiments, remaining slow cases,
  suite cost, commands, fixture locations, baseline-update policy, and follow-up candidates.
- Acceptance: every UI endpoint and startup profile is covered; regression gates detect slowdown;
  all in-scope correctness and verification gates pass; a clean checkout runs the generated tier.
  State exactly which full-tier assets are needed. Do not claim all latency targets are achieved
  if performance debt remains. Close with a closure reason, move the file, and repair board links.

## Execution handoff

### Current state — M10 complete; M11 next

- M0–M10 are complete. Their reports and evidence remain linked in the board and prior milestone
  reports.
- M6 adds focused read samples in
  `backend/scripts/run_interactive_ui_job_read_performance.py` and coverage checks in
  `backend/tests/test_interactive_ui_read_performance.py`. It covers job history, job detail/status,
  log pages, missing detail/log records, and calibration-preview reads for a valid preview job and
  a wrong job type. Reads use real HTTP handlers and valid production `Job` and `Intent` models in
  disposable storage. Fixture setup creates the successful preview before timing; timed reads do
  not write job state or simulate contention.
- History pagination is checked at 12 and 300 total jobs, with the same six target-recording jobs.
  Both sizes return the exact newest-first ID sequence across two pages, without overlap, and the
  final page has no next cursor. The timing runner retains 15 full-response samples; all status,
  JSON, and page checks pass. M6 samples are preliminary and are not a baseline.
- Checks: focused pytest (4 tests), Ruff check and formatting, inventory coverage check (76
  registered operations classified; one documented UI URL gap), and the 15-sample M6 runner passed.
  See `docs/reports/0114-M6_Job_History_and_Polling_Reads.md` and
  `docs/reports/0114-M6_Job_Read_Samples.json`.
- Decision: compare the same filtered target jobs against 12 and 300 unrelated-history sizes.
  This verifies page and cursor correctness as unrelated records grow; no latency claim beyond
  these preliminary samples is made.
- Known limit: one request per named read and per size is only a preliminary sample. M11 will
  establish repeated measurements and budgets. The successful preview uses a small deterministic
  fixture and does not represent a hard calibration payload.
- Decisions: M7 covers measured durable write/control families and the unregistered video URL
  not-found boundary. M8 completes named real-backend scenarios for the five residual stage
  submissions, both round-analysis intake routes, and calibration apply. The revised sequence keeps
  M9 on media API timing and cache invalidation; M10 on six real-process Playwright workflows and
  bounded controlled load; M11 on three independent full-corpus sessions and baseline gates; M12
  on profiling and candidate cycle one; and M13 on candidate cycle two and final qualification.
  The `/api/recordings/{recording_id}/video` URL remains an explicit unregistered 404 boundary.
  It is not a media timing case.
- M7 retains 36 passing response samples and 14 matching durable-effect comparisons for pipeline
  node edit/copy/restore/reviews, four selection families, pipeline-run submission, job controls,
  frame-review save, and calibration draft start/update/discard. The unregistered video URL returns
  the measured 404 boundary response. See `docs/reports/0114-M7_Interactive_Writes_and_Controls.md`
  and `docs/reports/0114-M7_Interactive_Writes_and_Controls_Samples.json`.
- M7 checks: focused pytest, Ruff check and format, the 36-sample runner, inventory coverage check,
  API generation, and API verification passed. The restore request model now declares optional
  `base_pointers`, which its production handler already reads.
- M8 checks: the combined residual-write pytest passed (2 tests, 8 named responses), Ruff and
  format checks passed, and inventory coverage reports no missing write scenario. Calibration
  apply persisted its exact published calibration revision, reflow proposal, and visible-card node
  revision. The real endpoint test also exposed and fixed calibration snapshot revision lookup and
  published-run schema errors.
- See `docs/reports/0114-M8_Residual_Writes.md` and
  `docs/reports/0114-M8_Residual_Write_Samples.json`. M8 samples are preliminary, one response per
  case, and are not a baseline.
- M9 completed named real-backend API cases for evidence frame and snippet, recording video and
  bounded range, thumbnail, derived event frame, and identity crop. Cold/warm responses retained
  exact bytes and identity. A persisted new identity revision was read through its own crop path;
  a saved review did not alter that immutable crop; and the saved crop remained readable after app
  restart. The unregistered UI video URL remains a 404 boundary. These are preliminary samples, not
  a baseline. See `docs/reports/0114-M9_Media_Routes_and_Cache.md` and
  `docs/reports/0114-M9_Media_Samples.json`.
- M9 uses the real route and cache handlers with a deterministic thumbnail renderer stub because
  the small local source recording is not decodable. Its range response is 55 bytes, below the
  65,536-byte cap. M11 must measure the frozen hard video asset before freezing transfer budgets.
- M10 passed seven scenarios in 70 fresh contexts: the six browser workflows and controlled load.
  It retained all request waterfalls, exact recording/revision/review/job identities, request counts,
  browser cache events, derived-media ETags/cache-control, and actual 206 video-range bodies. Ten
  fresh backend processes passed liveness, readiness, catalog, and exact workspace checks. See
  `docs/reports/0114-M10_Real_Process_Browser_and_Load.md` and
  `docs/reports/0114-M10_Real_Process_Browser_Samples.json`.
- M10 used an isolated generated 64×64 recording with four identity outcomes, two identity
  revisions, deterministic local processors, the production FastAPI app, real Uvicorn, and real
  Vite. Its samples are preliminary. They do not qualify the frozen hard-data corpus or establish
  production budgets. The hard asset returned a 1,554-byte range in this fixture; M11 must measure
  the frozen hard video before it freezes transfer budgets.
- M10 checks: the 7-scenario/70-context browser run and 10-process startup suite passed. Web
  TypeScript, targeted Prettier, backend Ruff check, and backend Ruff format checks passed. HTTP
  errors, failed requests, timeouts, incorrect identities, and invalid range responses fail the
  runner. Intentional navigation cancellations are retained separately from request errors.
- Next milestone: M11. Run the endpoint corpus, startup profiles, media routes, browser workflows,
  and controlled load in three independent sessions. Freeze budgets and gates only after those
  runs pass on the declared machine profile.
- Run authorization: 9 milestones requested, 6 completed, 3 remaining (M11–M13). This fixed run
  limit does not authorize adding milestones.
