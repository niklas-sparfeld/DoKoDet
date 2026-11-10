# Recording catalog performance

- **Status:** In Progress
- **Depends on:** [0119](../5-closed/0119-Pipeline_Recovery_Defects.md) M1 complete.
  0114/0115 are closed; 0117 retained measurements and source inventories are available.
- **Outcome:** Open `/recordings` through compact metadata reads whose cost does not increase
  with retained pipeline, processor-run, or analysis history.
- **Origin:** [0117 exit decision](../../reports/0117-Supersession_and_Exit.md).

## Fixed boundary

Deliver only the recordings list, its API consumers, and required metadata publication. Preserve
recording identity, stage status precedence, selected table-observation blocker behavior, and links
to detailed results. Replace embedded unbounded analysis/package lists with counts, a bounded latest
summary and explicit detail loading. Update web callers in the same cutover. No hidden lazy full scan.

The list uses processor-run status, not Job Manager state. Keep `_compact_stage_state` semantics:
active processor runs first; analysis active/complete/failed where applicable; available revision;
partial/failed run; then empty/video-only. These are availability summaries, not a claim that the
newest output is selected or that review is complete. Inspect the actual web fields in M0 and test
their replacements. Do not introduce recording HEAD as a new selection authority for this list.

Use one rebuildable SQLite catalog metadata index with per-recording counters and exact compact
rows. Authoritative node, selection, processor-run, analysis, package and intake stores remain the
sources. Maintain per-source receipts and pending publication through one common outbox protocol.
Writers publish source deltas; readers query metadata. Ordinary reads neither compare every source
record nor scan journals/history. Recovery processes only explicitly pending publication; full
source enumeration is an explicit offline rebuild. Missing/corrupt/not-ready index state is visible,
not a fallback to reconstruction. Reuse existing outbox patterns and locking helpers; do not build
a second general transaction framework or copy payloads into the index.

## Source and verification inventory

| Source owner | Catalog projection | Verification |
| --- | --- | --- |
| `RecordingBundleStore.publish` | Recording identity and display metadata | New import, replay and restart |
| `PipelineNodeStore` and `PipelineNodeTransactions` | Available content-type counts, metadata only | Ordinary/coordinated publication, source-to-index crash |
| `PipelineNodeSelectionStore` | Exact selected table-observation availability for analysis blocker | Selection change, missing/corrupt exact target, restart |
| `ProcessorRunStore.create/update_state/update_progress` | Per-recording/type status counts | Queued/running/terminal transition, no request payload scan |
| `RoundAnalysisStore` mutation boundary | Analysis state counts and latest compact summary | Create/progress/complete/fail/restart |
| `EvidencePackageStore.publish` | Linked stored-package count | Publish/replay, exact recording/session lineage, invalid package |
| `recordings_api`, `RoundAnalysisService`, web list callers | Read indexed summaries; details explicit | Real API, browser reload and growing history |

M0 must confirm all direct/import/recovery writers and schema versions for these owners. Add
missing adapters to the named source milestone before assignment; do not treat a copied-file count
or index-only API stub as a complete workflow. No queue, acceptance-key or scheduler optimization.

## Milestones

| Milestone | Observable result and commit boundary | Status |
| --- | --- | --- |
| M0 | Frozen list contract, consumer/writer matrix and failing growth assertions | Complete |
| M1 | Catalog metadata index, common publication outbox and explicit rebuild contract | Complete |
| M2 | Node and selection publication through one real catalog workflow | Complete |
| M3 | Processor-run status publication with pending-only crash recovery | Complete |
| M4 | Recording, analysis and package metadata adapters | Not started |
| M5 | Retained-data conversion rehearsal and activation manifest | Not started |
| M6 | API/web cutover and obsolete list-path removal | Not started |
| M7 | Measured catalog qualification and closure | Not started |

## M0 — Freeze the list contract

Inspect current web list consumers, source schemas and every writer in the inventory. Freeze the
response fields, deterministic ordering, recording pagination if needed, latest-summary rule and
explicit detail routes. Freeze per-recording error behavior. Add API contract and growth fixtures
that keep returned recordings/current state/active work fixed while history and unrelated records
grow 10x. Tests must expose current reconstruction. Reuse 0117 M0 corpus and measurements; make
one bounded current catalog capture to quantify drift. No full workspace/startup remeasurement.

Checks: consumer mapping, empty/mixed/corrupt fixtures, stage precedence and blocker assertions,
source schema inventory, expected failing structural tests with baseline evidence. Commit: contract,
tests, exact adapter list and evidence. M0 does not claim implementation completion.

## M1 — Implement the one metadata index

Implement the versioned SQLite schema, indexed queries, counters and common outbox/receipt protocol.
Define commit order, source identity/version/digest, replay, conflicting deltas, readiness and
per-recording isolation. One delta updates only affected rows/counters. Separate index from source
authority. Rebuild into a staged generation and switch atomically after validation. Do not repair on
GET. Integrate one deterministic source adapter in disposable storage to prove the complete source
write, metadata read and restart workflow before extending other owners.

Checks: crash at each durable boundary, idempotent replay, absent/corrupt source, conflicting source
version, concurrent readers/writers, process restart, bounded row/page queries and 10x growth.
Commit: the single storage/publication contract, implementation and tests. No production list switch.

## M2 — Connect node and selection writers

Connect node creation/save, coordinated transaction recovery and selected table-observation
updates. Reuse durable publication authority; do not traverse ancestry. In a disposable app, connect
the new reader to the real `/v1/recordings` route for a fixture with no analyses/packages/runs.
Test a real source write and selection change through service/API persistence, then read the list
with old discovery disabled and restart the app. Do this before connecting the remaining source
families. Preserve generated versus completed-reference selection and independent review identity.
Checks: source/index crash gaps, duplicate retries, concurrent selection/publication, exact target
failure, availability counts, blocker update and restart. Commit: these adapters and evidence.

## M3 — Connect processor-run status writers

Connect create and all durable state/progress/recovery paths in `ProcessorRunStore`. Extend M1's
common outbox with one prepare/finalize intent for processor-run publication. Under the run lock,
then the catalog publication lock, write a compact intent with the exact run ID, source key,
recording/type/status projection, and expected old and target run-state digests. Commit the existing
authoritative run state or staged run directory, then finalize the catalog receipt and counters and
clear the intent. Progress-only writes keep the same status projection and must not inflate counts.
On restart, process only pending intents. Exact-read the named run request/state and finalize only
when its state digest matches the target; cancel only when it matches the expected old state (or the
run is absent for create). Any other state is a visible error. Do not enumerate runs or parse saved
request payloads on list reads. The run store remains authoritative; do not copy full request/state
payloads into the catalog. Jobs retain their contracts.

This is one explicit persistent transaction contract added to M1, not a new store or general
transaction framework. Checks: all status transitions, identical replay, create and update crash
gaps before/after source commit, restart recovery, same-run concurrency, progress-only count
stability, and 10x historical run growth. Keep crash recovery coverage separate from concurrency
coverage. Commit: the outbox extension, run adapter, plan and tests.

## M4 — Connect remaining catalog metadata writers

Connect the recording intake publish boundary, analysis state replacement boundary, and package
publish boundary using M1's common protocol. Record exact recording/session package linkage and
latest analysis metadata without reading result payloads. Cover import and recovery callers.
Checks: empty/mixed state, concurrent publication, identical retry, crash/restart, analysis failure
and complete results, missing/corrupt lineage and 10x history growth. Commit: these finite adapters
and tests. Do not redesign intake, analysis execution, or evidence-package storage.

## M5 — Rehearse retained conversion

Freeze representative persisted schemas and the retained storage inventory. Build the index in
disposable storage. Verify identities, stage summaries, exact blocker inputs, counts, detail links,
review decisions and restart through real services with old list reconstruction disabled. Rehearse
interruption and recovery. Freeze the activation manifest and tested recovery copy. No live data
activation. Commit: offline rebuild tooling, manifest and rehearsal evidence.

## M6 — Activate the catalog and web consumers

Recheck the manifest and source writers, activate the rehearsed index, switch `/v1/recordings` and
web list callers, and remove list-only reconstruction. Existing workspace paths remain until 0121.
Update generated API types and an active route-inventory supplement; preserve the closed 0114
inventory. Real browser checks must cover list, detail navigation, job/analysis status, import and
reload using disposable backend persistence. Verify durable state and restart after activation.
Commit: API/web cutover, affected checks and evidence. No compatibility fallback to full scanning.

## M7 — Qualify and close

Structural gates: zero revision-payload/result/request-payload reads, history traversals or global
run/analysis enumerations during list requests. Metadata read/parse counts stay bounded under M0's
10x fixtures. Work may scale with the returned recording page. Prove every supported writer keeps
summaries correct after restart and that corrupt/not-ready state is visible and isolated.

Compare the same hard corpus in three uncontended sessions. Catalog first-use median target:
at most 2.5 seconds; no-regression ceiling: 3.9 seconds, from 0117 M0. Retain code/fixture hashes,
read counters, samples, write overhead and machine profile. Run at most two candidate capture sets;
do not repeat a passing set without changed code or a named measurement defect. Probe unchanged
workspace/stage first-use for displaced cost, without claiming workspace improvement.

Run affected backend tests, web tests/types/lint, API generation/inventory, persisted browser
workflows and local links. Close Complete only when structural gates and the latency target pass.
A missed target ends in a bounded report with a named cause; do not add startup, queue or workspace
redesign to this epic. Commit: qualification, board and closure move.

## Execution handoff

Original outcome: make `/recordings` metadata reads independent of retained pipeline, processor-run,
and analysis history. Non-goals: recording HEAD selection authority, queue/scheduler/workspace
redesign, startup optimization, and global write optimization. Closure requires M7 structural and
latency gates, source-writer correctness after restart, and retained-data qualification.

First complete workflow: M1 proves one source write, catalog metadata read, and restart; M2 proves a
real `/v1/recordings` route with old discovery disabled and restart. M2 passed after one correction.
M0 confirms existing exact node publication authority and selection cannot
supply catalog summaries; the common publication protocol remains a single contract prerequisite.
No production source owners were added. M1 implements the one planned catalog index and shared
publication contract. The initial plan has eight milestones.

The initial M1 submission was recorded as run progress 2/8. Sanity review found defects in rebuild,
generation switching, and paging. Correction 1/2 fixed current source versions, safe generation
switching, and null-time pagination. Correction 2/2 adds overlapping reader/writer coverage and
compares 1x and 10x retained source history with fixed page output and bounded SQL work. M1 passed
sanity review. Current run progress is 2/8 complete and 6 remain. Run re-plannings: 0/10.
M0 correction attempts: 1/2. The first M0 submission had only a Pydantic payload-size fixture and
an unpopulated hard-corpus capture. Correction 1 adds a real route fixture with persisted package,
analysis, processor-run and node histories, unrelated records, counters, and fixed-state checks.
Its structural assertions confirm source reads grow with 10x retained data while the returned
recording, stage state, latest analysis state, and active processor-run count remain fixed. Bounded
response and source-row checks remain strict expected failures until M6 removes reconstruction.
M6 must assert each growth counter separately; the combined expected-failure test stops at the
first failing response-size assertion.
Scope decision after the two-correction limit: keep the bounded catalog index approach. M1 proves
the index contract with one disposable source write/read/restart workflow. No production list
behavior has improved yet. The exact next proof is M2: publish real node and selection changes, read
`/v1/recordings` with old discovery disabled, verify the blocker, and restart. Continue only if M2
meets that acceptance. If it fails, perform the scope review before more implementation; do not add
another prerequisite or contract. The 0117 exit decision remains the wider scope boundary.

M0 correction changes: retain the first response-size fixture and add real persisted growth
evidence. See [M0 contract and source map](../../reports/0120-M0_Recording_Catalog_Contract.md) and
[growth capture](../../reports/0120-M0_Growth_Capture.json). M0 is complete after the correction
passed its fixture and source-growth checks.
The [0117 exit decision](../../reports/0117-Supersession_and_Exit.md#execution-control) governs
scope stops.

M1 result and correction history: [catalog index and publication contract](../../reports/0120-M1_Catalog_Index.md).
Correction 1 addresses rebuild from current source versions, generation switching with open readers
and interrupted switching, and keyset pagination through rows with no `received_at`. M1 does not
connect production writers or switch `/v1/recordings`; the first complete API workflow remains M2.

M1 family corrections: 2/2; sanity review passed. No re-planning or scope change occurred. Next
proof: M2 connects node and selection publication and reads the real `/v1/recordings` route with
old discovery disabled, verifies the blocker and restarts. Stop if M2 misses its assigned
acceptance. Run the scope review before any additional implementation; do not add a contract or
source authority. M1 checks and known limits are in its report.

M2 first submission: [node and selection publication through the real recordings route](../../reports/0120-M2_Node_Selection_Publication.md).
The route test proved fresh node/selection publication, disabled node discovery, blocker update,
concurrency, and restart. Sanity review did not accept the workflow: standalone selection writes
persist the pointer before the catalog outbox, coordinated recovery can skip an already-written
selection without publishing it, and the production route reads an unpopulated index before the
planned retained-data rehearsal and activation. See the report for exact evidence.

Scope review after the missed first-workflow checkpoint: keep the bounded M2 approach and use local
corrections. The route switch is premature; preserve production list behavior until the planned
M5/M6 activation. Use the existing M1 publication outbox and existing coordinated transaction
journal to make standalone and coordinated selection publication recoverable. This adds no source
authority, persistent contract, or prerequisite. The exact proof is a disposable real API workflow
with explicit catalog activation, node discovery disabled, separate crash/restart regressions for
standalone and coordinated selection writes, retry/concurrency/target/count/blocker checks, and a
production-default route regression. Stop and report the evidence if this cannot pass within M2's
correction allowance. M2 correction 1/2 passed: selection writes now use the existing coordinated
transaction journal, and its recovery republishes an already-written selection. The indexed route
is gated to explicit test activation; the production default retains the existing reader until
M5/M6 activation. Separate crash/restart tests cover standalone and coordinated selection updates.
The real API workflow still disables node and selection discovery after publication. No source
owner, authority, persistent contract, or prerequisite was added. Run progress is 3/8 complete and
5 remain; re-plannings were 0/10 at M2 closeout. M3 was the next planned milestone.

M3 scope review: the processor-run source store has no existing durable outbox or recovery journal.
Its state file commits before `publish_latest` can create an M1 pending record. A crash in that gap
leaves no evidence for pending-only recovery; startup run enumeration would violate the frozen
recovery boundary. Keep the bounded catalog approach and extend M1's common outbox with one
processor-run prepare/finalize intent contract. The run store remains the authority. The intent
records only exact run identity, compact target projection and old/target state digests. Recovery
reads only the named pending run and reconciles by digest. This adds one persistent contract within
M3, with no new store, authority, or general transaction framework. Run progress remains 3/8
complete and 5 remain; run re-plannings are 1/10 and this M3 scope-review re-planning is 1/5.
M0 corrections remain 1/2, M1 corrections 2/2, M2 corrections 1/2; M3 corrections start at 0/2.
M2's first complete workflow and its accepted evidence remain unchanged.

M3 result: [processor-run status publication](../../reports/0120-M3_Processor_Run_Publication.md).
Create, state changes, progress writes and pending-only recovery now publish compact status counts
through the M1 index. The indexed disposable route reads aggregate counters and does not parse saved
run requests. Tests cover every status, replay, pre/post source-commit crashes, same-run create
concurrency, progress count stability and 10x terminal-run history. The production list remains on
its old reader until M5/M6. M3 is complete; run progress is 4/8 complete and 4 remain. The run
re-planning count is 1/10, the M3 scope-review count is 1/5, and M3 corrections are 0/2. No further
source owner or contract was added after the recorded M3 decision. Next: M4 connects recording,
analysis and package metadata writers. The next proof is M4's empty/mixed state, concurrent publish,
retry, crash/restart, result-state and 10x history checks. Stop if M4 requires another contract or
source family.
