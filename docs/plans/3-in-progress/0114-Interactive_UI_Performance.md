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
The board currently has two 0112 files; this epic does not renumber unrelated plans.

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

Keep a versioned baseline with raw results and per-scenario budgets. M9 derives absolute ceilings
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
- **M4:** Not started — cover pipeline workspace, lineage, revision, review, and calibration reads.
- **M5:** Not started — cover pipeline run, selection, result, and comparison reads.
- **M6:** Not started — cover job history, polling, detail, and log reads.
- **M7:** Not started — cover writes, media, and contention.
- **M8:** Not started — measure real browser workflows.
- **M9:** Not started — establish the baseline and regression gates.
- **M10:** Not started — profile and rank improvement candidates.
- **M11:** Not started — implement and verify candidate cycle one.
- **M12:** Not started — implement and verify candidate cycle two.
- **M13:** Not started — qualify the full suite and close the epic.

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

## M7 — Cover interactive writes, media, and contention

- Add review edits/saves, selection changes, submission, cancellation/retry/queue controls, and
  UI upload/import paths. Validate durable effects and isolation in resettable fixture storage.
- Add frame/crop/thumbnail and video-range cases, cache invalidation, and the controlled load
  profile. Include repeated saves and polling during simulated background work.
- Acceptance: all remaining UI endpoint scenarios run. Compare exact content/lineage, write
  effects, and media identity as well as speed. Focused tests, lint, format, and applicable type
  checks pass; verify the generated API if API contracts change.

## M8 — Add real browser workflow measurements

- Add a dedicated Playwright configuration with isolated backend and web processes. Cover
  recordings-to-workspace, displayed revision switching, frame/crop navigation, review save,
  Jobs drawer/history, and job submission-to-visible-status. Include browser video-range traffic.
- Define useful completion with visible data identity and usable controls; do not time only a
  loading indicator or successful navigation. Collect actual UI requests and reconcile inventory.
- Acceptance: hard fixtures work without mocked API routes. The report separates backend wait,
  frontend work, duplicate requests, cache behavior, and process startup. Relevant web checks pass.

## M9 — Freeze the baseline and enable regression gates

- Run the complete corpus and all startup profiles in three independent sessions on the declared
  local machine profile. Keep uncontended and controlled-load results separate.
- Publish raw samples, a readable baseline table, measured noise, absolute ceilings, relative
  tolerances, finite suite runtime, and explicit slow-case debt. Enable the comparator and coverage
  gates. Confirm an injected slowdown fails through the real suite command.
- Acceptance: every UI endpoint and startup profile has a reproducible baseline and budget key.
  Missing cases/assets, invalid responses, timeouts, and incompatible profiles cannot return a
  passing qualification result. Separate environment failures from measured regressions.

## M10 — Profile and select bounded candidates

- Profile the highest-cost measured cases, including startup. Attribute time to specific work;
  retain bounded traces and operation counts. Create a ranked candidate table with baseline,
  affected routes, expected gain, risk, verification command, and stop condition.
- Select at most two small changes for M11/M12. Select a startup change if startup is a leading
  measured source of delay; do not force a startup rewrite without evidence. Freeze a numeric
  improvement target per cycle before implementation. Reserve one untouched hard case per
  affected family to check that improvements generalize beyond the profiled input.
- Acceptance: candidates have concrete code scope and correctness oracles. A candidate too large
  for one milestone becomes later work; it does not expand this epic into an architecture rewrite.

## M11 — Candidate cycle one

- Add the targeted regression case, implement one selected change, then rerun the same cold/warm,
  startup, and affected browser scenarios on the frozen corpus and machine profile.
- Acceptance: meet the predeclared gain and all correctness/budget gates on affected and reserved
  cases. Verify restart and invalidation behavior for any caching change. Revert unsuccessful
  changes and record evidence; do not retain complexity without measured benefit. Run applicable
  tests, lint, format, types, generated API, and browser checks for changed paths. Update the
  ranking from measurements and select or confirm the next candidate before M12.

## M12 — Candidate cycle two

- Repeat the M11 procedure for the next highest-value bounded candidate using the current ranking.
  Compare with both the original baseline and the result after cycle one.
- Acceptance: retain only a verified gain with unchanged correctness. If no safe candidate remains,
  publish measurements and the exact stop reason instead of implementing an unmeasured change.
  An unsuccessful cycle may complete as a documented experiment; it cannot be called a speedup.

## M13 — Full qualification and closure

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

### Current state — M4 complete

- M0–M3 are complete. Their reports and evidence remain listed above and in the M3 handoff history.
- M4 adds `backend/scripts/run_interactive_ui_pipeline_read_performance.py` with 14 named speed
  and correctness cases across six UI GET routes. Cases cover full and stage-filtered workspace
  reads, exact lineage, maximum identity and polygon revisions, review reads, calibration-refinement
  validation, published calibration snapshots, and missing or stale reads. Each case measures a
  first cold app request and a warm request after one warmup. All cases use real storage, production
  validation, full response serialization, and exact fixture identity checks.
- M4 adds 12 hashed hard-fixture dependency assets. The fixture manifest now names 54 assets. The
  new lineage parent records make both exact copied parent revisions available to the lineage read.
  The new published-calibration GET route is classified in the M0 inventory.
- The hard calibration-refinement draft predates current node lineage metadata. Its GET returns the
  expected 422 `invalid_calibration_refinement` response. M4 measures this validation path and the
  successful exact published-calibration snapshot route. A successful current-draft read remains a
  fixture follow-up.
- The preliminary sample export contains 42 samples and is not a baseline. The full workspace and
  lineage reads are slow on the current fixture: about 20 seconds and 29 seconds per request.
  Initial 30-second experiments timed out on lineage. The retained run uses a finite 180-second
  timeout. No performance budget or baseline gate is active.
- Checks: focused pytest, Ruff check and formatting, hard-fixture validation, inventory check, and
  the 42-sample runner passed. Details and machine profile are in
  `docs/reports/0114-M4_Pipeline_Workspace_and_Revision_Reads.md`.
- Next milestone: M5, pipeline run and result reads.
- Run authorization: 10 milestones requested, 1 completed, 9 remaining. M5–M13 are the nine
  planned incomplete milestones. This fixed run limit does not authorize adding milestones.
