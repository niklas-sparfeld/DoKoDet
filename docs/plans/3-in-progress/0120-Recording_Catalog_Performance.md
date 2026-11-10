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
| M2 | Node and selection publication through one real catalog workflow | Not started |
| M3 | Processor-run status publication | Not started |
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

Connect create and all durable state/progress/recovery paths in `ProcessorRunStore`. Progress-only
updates must not inflate counts. Preserve status precedence without parsing saved run request
payloads on list reads. Jobs keep their existing contracts. Checks: all status transitions, replay,
source/index crash, restart and 10x historical run growth. Commit: run adapters and tests.

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
real `/v1/recordings` route with old discovery disabled and restart. The checkpoint remains M2 and
has not been reached. M0 confirms existing exact node publication authority and selection cannot
supply catalog summaries; the common publication protocol remains a single contract prerequisite.
No production source owners were added. M1 implements the one planned catalog index and shared
publication contract. The initial plan has eight milestones; six remain.

Current run requested 8 milestones, completed 2, and has 6 remaining. Run re-plannings: 0/10.
M0 correction attempts: 1/2. The first M0 submission had only a Pydantic payload-size fixture and
an unpopulated hard-corpus capture. Correction 1 adds a real route fixture with persisted package,
analysis, processor-run and node histories, unrelated records, counters, and fixed-state checks.
Its structural assertions confirm source reads grow with 10x retained data while the returned
recording, stage state, latest analysis state, and active processor-run count remain fixed. Bounded
response and source-row checks remain strict expected failures until M6 removes reconstruction.
M6 must assert each growth counter separately; the combined expected-failure test stops at the
first failing response-size assertion.
Scope decision: keep the bounded catalog index approach. M1's disposable write/read/restart proof
passed through one deterministic fixture adapter. It adds no production writer or source owner.
The 0117 exit decision remains the scope boundary.

M0 correction changes: retain the first response-size fixture and add real persisted growth
evidence. See [M0 contract and source map](../../reports/0120-M0_Recording_Catalog_Contract.md) and
[growth capture](../../reports/0120-M0_Growth_Capture.json). M0 is complete after the correction
passed its fixture and source-growth checks.
The [0117 exit decision](../../reports/0117-Supersession_and_Exit.md#execution-control) governs
scope stops.

M1 result: [catalog index and publication contract](../../reports/0120-M1_Catalog_Index.md). The
versioned SQLite index, source receipts, atomic pending-publication files, explicit pending replay,
and staged rebuild are implemented. The fixture proves source publication, metadata reads, restart,
replay, recovery and bounded pages. M1 does not connect production writers or switch
`/v1/recordings`; the first complete API workflow remains M2.

M1 family corrections: 0/2. No re-planning or scope change occurred. Next proof: M2 connects node
and selection publication and reads the real `/v1/recordings` route with old discovery disabled.
Stop if this requires another persistent contract or a source authority beyond the frozen M0
inventory. M1 checks and known limits are in its report.
