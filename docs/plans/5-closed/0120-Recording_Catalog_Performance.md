# Recording catalog performance

- **Status:** Closed
- **Closure reason:** Superseded
- **Depends on:** [0119](../5-closed/0119-Pipeline_Recovery_Defects.md) M1 complete.
  0114/0115 are closed; 0117 retained measurements and source inventories are available.
- **Outcome:** Open `/recordings` through compact metadata reads whose cost does not increase
  with retained pipeline, processor-run, or analysis history.
- **Origin:** [0117 exit decision](../../reports/0117-Supersession_and_Exit.md).

## Supersession — 2026-11-10

The user selected simple domain resources, conventions instead of a resource framework, and a
recording list that reads root/current metadata. The [storage decision](../../RecordingDataStorage.md)
and [0123](0123-Simple_Recording_List.md) replace this delivery plan. M9's proposed
publication ledger and adapters are cancelled. Do not resume the old loop or reset its counters.
M0–M2 and M8 remain historical evidence; M3 was unaccepted with corrections exhausted at 2/2.
The production latency outcome was not achieved. Closing as Superseded claims no speedup and
changes no runtime or retained data. The sections below preserve the earlier plans and handoffs.

## Current disposition — recording root and HEAD

On 2026-11-10 the user changed the validation boundary. Listing a recording must
read its root and current state, not validate the data inside it or its historical
revisions. A virtual-card view, processor, or other operation validates the resource
it opens. The node-availability review remains historical evidence; its proposed
requirement to detect arbitrary historical damage during every list request is
superseded. Missing or corrupt list metadata must remain visible; it must not become
an invented empty, complete, or runnable state.

The catalog index, catalog outbox and run-intent approach were removed. The source
transaction journal for node and selection changes remains. The backend still
refuses startup for a nonempty or invalid retired catalog outbox and preserves it
for reconciliation. No retained catalog or source data was deleted. See the
[disposition](../../reports/0120-Catalog_Disposition.md), [partial list result](../../reports/0120-Source_List_Progress.md),
[feasibility review](../../reports/0120-Node_Availability_Feasibility.md), and
[0117 exit](../../reports/0117-Supersession_and_Exit.md). This plan supersedes the
0117 exit's freeze on HEAD **for the list proof only**. It does not authorize a
workspace or processor-input migration. Coordinate with 0121 before changing any
shared state or selection authority.

### Outcome and limits

Open `/recordings` quickly with per-recording root and current-state reads. With the
number of recordings and active work fixed, list reads must not grow with retained
pipeline revisions, processor runs, analyses, or packages. The recording count may
still affect list cost. Preserve the visible five stages, current active/failed/
partial behavior and analysis blocker, unless the user explicitly approves a
specific semantic change. Do not report a reference as verified content: an
operation must check the exact resource it uses. Keep detail/history accessible
through their existing explicit paths.

The list enumerates `RecordingBundleStore.list_metadata()` today. A recording HEAD
is a separate pointer to an immutable selected snapshot; its compact summary
contains selected/stale slot states. `get_current()` reads HEAD and the selected
snapshot and may repair its summary. This is a candidate for bounded current-state
reads, not evidence that every recording has initialized HEAD or that ordinary
writers maintain it. The current list instead reconstructs availability from every
node revision, reads processor-run histories and analysis states, and derives the
blocker from an exact table-observation selection or a valid linked package.
HEAD's selected state is not automatically equivalent to the old “any historical
revision exists” state. Preserve the distinction and establish a truthful mapping;
do not turn historical availability into current selection by assertion.

The web list uses recording/round identity, timestamp, session, thumbnail and five
stage states. The list API also returns counts, latest analysis and blocker fields;
the detail API has full histories. Audit real callers before changing any field.
The requested blocker behavior remains a requirement even if the current web list
does not render it. It is not permission to scan package history on every request.

### Existing owners and open boundaries

| Need | Current owner and known gap | Proof or decision |
| --- | --- | --- |
| Identity and order | `RecordingBundleStore` and intake metadata | Read recording roots without video or history; preserve order and navigation. |
| Selected state | `RecordingStateSnapshotStore`, `RecordingStateWorkingEditor` and state API | Existing HEAD is an experimental selected-state path; normal node and selection writers are not shown to maintain it. Prove a real selected event workflow first. |
| Visible available stage | `PipelineWorkspaceService.get_statuses`, node and selection stores | Old code uses any valid historical `data_revision`; selected/stale HEAD slots have different meaning. Test unselected and stale output. Stop if exact visible behavior needs a broad authority migration. |
| Active, partial and failed stage | `ProcessorRunStore` | HEAD has no run status. Identify a bounded current source and prove ordinary run lifecycle, interruption and restart; do not substitute Job Manager status without proving equivalent behavior. |
| Analysis stage and blocker | `RoundAnalysisStore`, `PipelineNodeSelectionStore`, `EvidencePackageStore`, `RoundAnalysisService` | HEAD alone has neither analysis states nor package availability. Keep exact selection/package blocker and actual analysis precedence; identify bounded current authority and its writers. |
| Detail and validation | Existing workspace, resource and analysis APIs | Check exact referenced content when used; old and corrupt unrelated history must not prevent the list from opening. |

The current hard-corpus list capture took 18.482 seconds, read 14 revision
records and about 70 MB. It is one instrumented sample, not a latency qualification.
The bounded response and shared analysis scan have not proved a speedup. The 1x/10x
fixture still shows separate node, node-history, run, analysis and package growth.

### Finite delivery plan

M0–M2 remain accepted historical results. M3 remains unaccepted after correction
2/2; M4–M7 are superseded, not completed. The original eight-milestone baseline,
its correction history and the stopped run's 1/10 re-planning count remain in the
handoff. The new work is a materially different HEAD-based feasibility and delivery
approach, with at most two corrections for its proof family. It does not reset M3's
exhausted corrections or authorize another Luna loop. This user-directed re-plan is
outside the stopped run; it does not add to or reset that run's recorded count.
M8 proved the first workflow. M9–M11 remain unstarted, with qualification in M11.

| Milestone | Observable result and commit boundary | Status |
| --- | --- | --- |
| M8 | One real, persisted HEAD-backed recording list workflow with old node discovery disabled; measure and make a go/stop decision. Commit the narrow proof, checks and report together. | Complete; limited proof |
| M9 | Complete a finite, explicitly specified current-status and blocker publication path for the remaining supported list workflow, only if M8 establishes a small set of owners and at most one new persistent contract. Commit that bounded work and evidence. | Not started; specified below |
| M10 | Rehearse initialization for retained recordings and activate the production list for the supported corpus; verify behavior and restart, or stop. Commit activation and evidence. | Not started; specify after M8 |
| M11 | Qualify real browser/list latency, independent retained-history growth, correctness and recovery; remove only proved obsolete list code and close or record an unmet outcome. Commit qualification and report. | Not started; qualification |

**M8 assignment.** Use the existing `RecordingBundleStore`,
`RecordingStateSnapshotStore`, state API and `RecordingStateWorkingEditor` with
`recordings_api` and the web list. In disposable persisted storage, import an
accepted recording, initialize its recording HEAD using the real state API, select
and edit an events revision using the real working editor, then open the actual
`/recordings` page and navigate to the recording. The selected events stage must
show the truthful current status; include an empty recording and the unchanged
analysis blocker. Restart the backend and repeat the list. Disable the legacy node
history discovery for the tested list path and fail the test if it is called. Use
processor stubs only if a processor is needed. A fixture-only state API request or
mocked browser response alone is not this proof.

**M8 result:** The opt-in workflow passed with explicit unavailable states. The
[proof report](../../reports/0120-M8_HEAD_List_Proof.md) records the checks, growth
and stop decision. The production outcome remains unmet. Do not assign M9 until its
bounded publication and recovery boundary is established within the stated limits.

### M9 review and assignment — bounded list publication

**Decision:** A single list-specific publication contract is feasible for M9. M8 did not
prove this contract impossible. It proved that HEAD alone cannot represent all existing
list states. Keep the source stores and exact selection as authorities. Do not migrate
selection authority to HEAD. This is a design decision, not evidence that the new
contract already works. M9 must prove it before M10 activation.

The smallest existing-authority candidate retains `recording_catalog` and
`get_statuses`, using exact selection and existing node transactions for their own
writes. It preserves the current result after ordinary restart, and atomic source writes
and existing node recovery protect their own resources. Concurrent readers can still
see different source instants. It must enumerate node revisions, run directories,
analyses and package metadata on each list, as M8's separate 1x/10x counts show.
HEAD only describes selected slots and misses unselected revisions. Neither it nor
existing source journals supplies the required aggregates or a durable indication of
all source-to-summary gaps. Thus this candidate cannot meet bounded reads by itself.

The bounded candidate adds **one persistent contract**, a recording-list publication
ledger with a compact projection and durable pending intents. It is specific to this
list, not a general multi-store transaction. Source records remain authoritative; the
projection is rebuildable metadata. Under a cross-process publication lock, an adapter
records an intent *before* the source commit, containing the exact source identity,
recording, prior and intended source version or digest, and the affected compact
projection. After the source commit it atomically applies an idempotent receipt and
projection and clears the intent. A coordinated node transaction is one intent tied to
its existing transaction journal and all affected recording projections. Define and test
one lock order with the existing source locks; do not hold a publication lock while
waiting for a source lock in the opposite order. The projection stores bounded stage
availability and per-status run and analysis counts, latest analysis summary, valid
linked package count, and exact selection/blocker inputs. It never stores resource
content or changes what a selected reference means.

A reader obtains a consistent committed projection snapshot. While a relevant intent is
pending, it must wait for reconciliation or show an explicit unavailable/error state;
it must never return an old projection as current. After interruption, reconciliation
uses only the named source and, for coordinated node writes, the existing transaction
journal. It distinguishes absent source from invalid existing source, compares exact
versions/digests, applies or cancels only a proved outcome, and leaves ambiguity visible.
Replay cannot double count. Recovery and ordinary reads must not enumerate retained
history. Concurrent source writers, recovery and list readers must observe this same
protocol, including within one process and across processes. External corruption or
out-of-band source changes are not silently represented as a valid empty result; define
visible invalid/not-ready behavior. Explicit resource operations still validate content.

| List input and reader | Finite source writers and M9 adapter |
| --- | --- |
| Any valid historical stage revision; `PipelineWorkspaceService.get_statuses` | `PipelineNodeStore.create/save` and `PipelineNodeTransactions` commit/recovery, including edit, copy, restore, lineage, processor, calibration and import callers. Publish availability from the actual source publication, including unselected output; selected/stale HEAD alone is insufficient. |
| Processor-run precedence; workspace status reader | `ProcessorRunStore.create`, `update_state`, `update_progress`, `complete`, `fail` and `fail_non_terminal`, including lifecycle/restart callers. Track queued/running, partial and failed per processor type; progress-only updates cannot change counts. |
| Analysis precedence, count and latest; `RoundAnalysisService.recording_catalog` and workspace | `RoundAnalysisStore.insert/create`, `update_progress`, `mark_complete`, `mark_failed` and `fail_non_terminal`, including job/restart callers. Latest uses `(created_at, analysis_id)`; preserve active, complete and failed precedence. |
| Linked package count and blocker; `recording_catalog` | `EvidencePackageStore.publish`, including API and operator import, with idempotent replay. Count only stored, valid metadata and lineage with matching recording and session. Invalid package or lineage does not unblock. |
| Exact table-observation blocker; `recording_catalog` | `PipelineNodeSelectionStore.update_exact` and coordinated transaction/recovery, including processor lineage and import paths. Preserve the current exact-reference test and validation-error blocker; do not validate referenced content on the list. `RecordingBundleStore` remains identity/session authority and its publish/intake/import path supplies recording identity for matching. |

**Observable result:** In disposable persisted storage, the real recordings API and browser
show the existing five stage states, compact analysis/package fields and exact blocker for
ordinary writes from all five families, with legacy history discovery disabled. Include
unselected and stale outputs, empty and mixed recordings, invalid source metadata, linked
and unlinked packages, and selected-reference changes. The production default remains
unchanged until M10. The finite owners are the stores and adapters in the table,
`recordings_api`, `RoundAnalysisService`, `PipelineWorkspaceService`, and the web list.
Keep explicit detail/history readers on their existing paths. Inspect all direct and
recovery writers of these owners before connecting them; if another independent owner or
contract is required, stop and report the concrete boundary rather than expanding M9.

**Required checks:** Exercise each source commit boundary before intent, after intent,
after source commit, after projection receipt and before intent cleanup; restart and
reconcile each exact source. Cover absent versus invalid paths, duplicate replay,
coordinated node recovery and existing restart regressions. Separately test overlapping
readers, writers and recovery across processes, including pending visibility and lock
order. Verify all status precedence and blocker cases against the existing reader on the
same valid fixtures, including package lineage/session mismatch and selection errors.
Use the real API/browser with persisted data and restart, then independently measure
node manifests/history, run directories, analysis rows and package rows under fixed
recordings/active work and 1x/10x retained history. Assert bounded reads and bounded
response; do not claim M11 latency qualification. Run targeted backend and browser tests,
type/lint/format and API checks. Record revision, fixture and results. One commit contains
the contract, finite adapters, tests, report and plan/board update. No retained-data
activation, general transaction framework, scheduler change or M11 movement is authorized.
If these checks reveal that the single protocol cannot preserve the behavior or recover
unambiguously, stop with the failed boundary and smallest alternatives.

M8 must not claim the whole production cutover. It must give an explicit, visible
unavailable state for recordings whose HEAD is missing, invalid or cannot represent
required list fields; never silently synthesize empty status, an unblocked action,
or fall back to full history. Exercise two recordings so one unavailable state does
not hide a valid row. The proof may use a disposable opt-in app configuration until
all required writers and retained recordings are covered. It must use the real list
route and browser and must not make a fixture-only endpoint the claimed workflow.
No new persistent storage or transaction contract is authorized in M8. If the
existing HEAD APIs cannot support this proof without such a contract, stop and
report the missing boundary instead of adding one.

M8 checks: supported HEAD selection and update, no-op and stale HEAD behavior,
missing/corrupt HEAD and selected snapshot, invalid historical node payload with
valid current state, selected content corruption deferred to the operation that
opens it, blocker and stage mapping, restart, and separate concurrent HEAD reader/
writer checks using the existing state-store guarantees. Measure node-history,
node-manifest, run, analysis and package reads independently in 1x/10x fixtures;
report the remaining growth, do not mark it passing. Capture comparable hard-corpus
list timing only where its HEAD initialization is valid, documenting fixture and
measurement limits. Run targeted backend and browser/API checks, type/lint checks,
and record revision and data snapshot. Keep older crash and concurrency regressions.

At M8 close, inventory the concrete supported and unsupported cases, current
writers, preserved data schemas and the exact remaining blockers. Specify M9 before
assignment with one observable result, a finite owner/adapter list, authority,
checks and one commit boundary. Do the same for M10 and M11 before each starts.
One milestone may add at most one persistent storage or transaction contract. Do
not require bounded writes or optimize scheduling unless measured contention or
moved work blocks the list. Do not hide a writer or transaction contract inside
retained-data initialization. If multiple independent contracts are necessary,
stop and return a smaller outcome or ask for a new scope decision; do not silently
extend this plan or move qualification.

**Retained data and removal.** Before production activation, inventory representative
recording bundle and state schemas, existing HEADs, node selections, package and
analysis records, and all affected readers/writers. Rehearse initialization in a
disposable frozen snapshot. Verify actual current selections, blocker inputs, usable
content, editing, restart and exact dependencies; counts or copies alone do not
prove cutover. An absent HEAD must not be initialized as empty when existing source
state is present. Record the activation snapshot, a way to recover and rollback,
and how concurrent writes are excluded or reconciled. Never delete retained source
history or the retired catalog/outbox data as part of this plan. Remove replaced
list-only scans or other code only after the consumer/writer audit and proof show
that detail, selection, recovery and explicit history readers still work; preserve
all other code until separately justified.

**Stop and closure.** Stop after M8 if the real workflow needs a broad selection
migration, unbounded owner discovery, a new general multi-store transaction, or a
semantic change to visible status/blocker that has not been approved. Also stop if
M8 cannot prove the workflow without another persistent contract, or if later work
cannot be split into the finite boundaries above. Report the measured result, source
owners and decision; do not add prerequisites to postpone qualification. Closure
requires default production list and browser navigation on retained initialized data,
truthful status/blocker behavior, explicit resource validation at use, no list-time
history/content scan, independent 1x/10x bounds, recovery/concurrency checks and
comparable repeated latency sessions against the same corpus. If any requirement is
unmet, leave the epic open and state exactly what remains.

## Historical original plan (superseded)

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
| M3 | Processor-run status publication with pending-only crash recovery | In Progress |
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

## Historical execution handoff

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

M3 initial submission: [processor-run status publication](../../reports/0120-M3_Processor_Run_Publication.md).
It connects create, state changes, progress writes and pending-only recovery to compact catalog
status counts. The indexed disposable route reads aggregate counters and does not parse saved run
requests. Initial checks cover all statuses, replay, pre/post source-commit crashes, same-run create
concurrency, progress count stability and 10x terminal-run history. The production list remains on
its old reader until M5/M6. Initial status was reported complete with 4/8 accepted and 4 remaining;
sanity review found a recovery race and a same-process receipt-replay gap, so M3 acceptance is
pending correction. Current goal progress is 3/8 accepted and 5 remain. Run re-plannings are 1/10;
the M3 scope-review re-planning is 1/5. M0 corrections remain 1/2, M1 corrections 2/2, M2
corrections 1/2, and M3 corrections are now 2/2. Correction 1/2 serialized exact-run recovery
with writers and added same-process replay of a converted ordinary outbox record. Correction 2/2
protects the pending-intent snapshot with the catalog publication lock, releases that lock before
per-run recovery, and keeps the exact reread under the run lock. Tests also cover intent removal and
replacement during enumeration and cancellation of a create intent when its staged directory never
commits. Prior overlap, concurrent recovery, same-process retry and restart receipt-gap tests remain.
The targeted tests, lint, format and diff checks pass; see the M3 report. Sanity review acceptance
is pending and the M3 correction allowance is exhausted. Goal progress remains 3/8 accepted and 5
remain. No new contract or authority was added. Do not start M4 until acceptance. If re-review does
not accept, perform scope review before further M3 work.

M3 scope review after correction exhaustion: final sanity review found that recovery treats an
existing run path with a missing, non-file, or symlinked `state.json` as if the run were absent.
For a create intent with no old state digest, recovery can then cancel the intent and hide the
invalid persisted run. This is another edge in the same intent-recovery approach, not evidence for a
materially different or smaller approach. M3 remains In Progress and is not accepted. Do not make
another code correction or start M4 without explicit authorization because the two-turn correction
limit is exhausted.

Finite remaining M3 correction, if authorized: distinguish a truly absent run directory from an
existing invalid run path; fail visibly and preserve the intent for an existing symlink, non-directory,
missing state file, symlinked state file, or non-file state path. Keep cancellation only for a truly
absent create source or a valid exact old-state digest. Add separate regressions for absent-create
cancellation and existing-invalid-path preservation. Retain the earlier pre/post-commit, writer
overlap, concurrent-recovery, same-process retry, and restart receipt-gap tests. Then run the M3
targeted checks and diff/link checks. Stop if any case needs another contract or broader recovery.

Initial plan count remains eight. M0–M2 are accepted and M2's first disposable API workflow remains
proved. M3 is pending; M4 recording/analysis/package adapters, M5 retained-data rehearsal, M6 API/web
activation, and M7 qualification/closure remain. Goal progress is 3/8 accepted and 5 remain. M3
scope-review re-plannings are 1/5; run re-plannings are 1/10; M3 corrections are 2/2. No new
milestone or re-planning was added. Stop until the user explicitly authorizes one additional M3
correction or chooses a materially different disposition. Do not reset counts on a new run.
