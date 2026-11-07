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

Keep a versioned baseline with raw results and per-scenario budgets. M6 derives absolute ceilings
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
- **M1:** Complete — freeze a hashed local hard example and seeded disposable workload profiles.
- **M2:** Not started — implement the timing and startup harness.
- **M3:** Not started — cover UI JSON reads and job polling.
- **M4:** Not started — cover writes, media, and contention.
- **M5:** Not started — measure real browser workflows.
- **M6:** Not started — establish the baseline and regression gates.
- **M7:** Not started — profile and rank improvement candidates.
- **M8:** Not started — implement and verify candidate cycle one.
- **M9:** Not started — implement and verify candidate cycle two.
- **M10:** Not started — qualify the full suite and close the epic.

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
- Exercise one JSON read, one bounded media response, and startup through first useful response.
- Acceptance: repeated runs follow the protocol; process cleanup works after errors/timeouts;
  startup and deferred first-use costs are visible. Comparator tests detect injected slowdown,
  incompatible fixture/machine profiles, and invalid responses. No baseline gate is enabled yet.

## M3 — Cover UI reads and polling

- Implement inventory scenarios for all JSON reads: recordings, workspace/lineage, revisions,
  results, review state, comparisons, analysis views, job status/history/logs, and other M0 reads.
- Exercise hard sizes, query variants, cold/warm state, and relevant errors. Use real storage and
  serialization. Include growth in unrelated resources and page-boundary correctness.
- Acceptance: every inventoried JSON read has executable speed and correctness coverage. Record
  preliminary measurements without claiming a complete baseline. Relevant pytest and Ruff pass.

## M4 — Cover interactive writes, media, and contention

- Add review edits/saves, selection changes, submission, cancellation/retry/queue controls, and
  UI upload/import paths. Validate durable effects and isolation in resettable fixture storage.
- Add frame/crop/thumbnail and video-range cases, cache invalidation, and the controlled load
  profile. Include repeated saves and polling during simulated background work.
- Acceptance: all remaining UI endpoint scenarios run. Compare exact content/lineage, write
  effects, and media identity as well as speed. Focused tests, lint, format, and applicable type
  checks pass; verify the generated API if API contracts change.

## M5 — Add real browser workflow measurements

- Add a dedicated Playwright configuration with isolated backend and web processes. Cover
  recordings-to-workspace, displayed revision switching, frame/crop navigation, review save,
  Jobs drawer/history, and job submission-to-visible-status. Include browser video-range traffic.
- Define useful completion with visible data identity and usable controls; do not time only a
  loading indicator or successful navigation. Collect actual UI requests and reconcile inventory.
- Acceptance: hard fixtures work without mocked API routes. The report separates backend wait,
  frontend work, duplicate requests, cache behavior, and process startup. Relevant web checks pass.

## M6 — Freeze the baseline and enable regression gates

- Run the complete corpus and all startup profiles in three independent sessions on the declared
  local machine profile. Keep uncontended and controlled-load results separate.
- Publish raw samples, a readable baseline table, measured noise, absolute ceilings, relative
  tolerances, finite suite runtime, and explicit slow-case debt. Enable the comparator and coverage
  gates. Confirm an injected slowdown fails through the real suite command.
- Acceptance: every UI endpoint and startup profile has a reproducible baseline and budget key.
  Missing cases/assets, invalid responses, timeouts, and incompatible profiles cannot return a
  passing qualification result. Separate environment failures from measured regressions.

## M7 — Profile and select bounded candidates

- Profile the highest-cost measured cases, including startup. Attribute time to specific work;
  retain bounded traces and operation counts. Create a ranked candidate table with baseline,
  affected routes, expected gain, risk, verification command, and stop condition.
- Select at most two small changes for M8/M9. Select a startup change if startup is a leading
  measured source of delay; do not force a startup rewrite without evidence. Freeze a numeric
  improvement target per cycle before implementation. Reserve one untouched hard case per
  affected family to check that improvements generalize beyond the profiled input.
- Acceptance: candidates have concrete code scope and correctness oracles. A candidate too large
  for one milestone becomes later work; it does not expand this epic into an architecture rewrite.

## M8 — Candidate cycle one

- Add the targeted regression case, implement one selected change, then rerun the same cold/warm,
  startup, and affected browser scenarios on the frozen corpus and machine profile.
- Acceptance: meet the predeclared gain and all correctness/budget gates on affected and reserved
  cases. Verify restart and invalidation behavior for any caching change. Revert unsuccessful
  changes and record evidence; do not retain complexity without measured benefit. Run applicable
  tests, lint, format, types, generated API, and browser checks for changed paths. Update the
  ranking from measurements and select or confirm the next candidate before M9.

## M9 — Candidate cycle two

- Repeat the M8 procedure for the next highest-value bounded candidate using the current ranking.
  Compare with both the original baseline and the result after cycle one.
- Acceptance: retain only a verified gain with unchanged correctness. If no safe candidate remains,
  publish measurements and the exact stop reason instead of implementing an unmeasured change.
  An unsuccessful cycle may complete as a documented experiment; it cannot be called a speedup.

## M10 — Full qualification and closure

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

### M0 — complete

- Changes: added the checked route inventory at `docs/reports/0114-M0_Interactive_UI_Performance_Inventory.json`
  and the startup/browser report at `docs/reports/0114-M0_Interactive_UI_Performance_Inventory.md`.
  The inventory covers registered OpenAPI operations and records the unregistered UI video URL as
  a route discrepancy.
- Checks: inventory checker passed for registered operations and one unregistered UI URL;
  `npx playwright test jobs.spec.ts --trace on` passed 4 tests. Those browser responses are
  intercepted and are call-path evidence only.
- Decisions and limits: `/api/recordings/{recording_id}/video` is emitted by a UI video element
  but is not registered by the backend. Resolve that contract before measuring it. No backend
  latency baseline or performance fix was selected. No full baseline suite was run.
- Next: M1 hard-data discovery and frozen fixture setup.
- Run count: requested 11 milestones; completed 1; remaining 10. Continue only after explicit
  authorization under the persistent milestone command.

### M1 — complete

- Changes: added the bounded metadata report and source manifest at
  `docs/reports/0114-M1_Hard_Data_and_Fixture_Freeze.md` and
  `backend/fixtures/interactive-ui-performance/v1/manifest.json`. Added the seeded disposable
  materializer, SHA-256 validation, exact hard-snapshot importer, and regression tests.
- Checks: `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_performance_fixtures.py`
  passed (5 tests); scoped Ruff check passed. Two clean small-profile materializations were
  byte-identical. The representative profile materialized and validated 805 assets. Hard snapshot
  import and `--require-hard` passed against all six local content-addressed assets.
- Decisions and limits: the metadata pass read 1,006 node manifests only. It selected the exact
  1,061,930,405-byte source video and 40-frame, 2,641,025-byte revision. The cache is outside the
  repository and uses a hard link on the current volume. The generated tier uses a fixed 64 KiB
  media asset. Review-draft size, result fan-out, and additional lineage extremes still need bounded
  discovery before those cases are frozen. No timings or speed claims were made.
- Next: M2 timing and startup harness. The full qualification command must require the hard cache
  and fail clearly when one of its six pinned assets is missing.
- Run count: requested 11 milestones; completed 2; remaining 9.

The user requested interactive UI endpoint speed coverage and backend startup timings. This epic
includes two bounded improvement cycles, not an open-ended optimization loop. No persistent run or
This invocation authorizes the requested M1 milestone only. Preserve unrelated worktree changes.
