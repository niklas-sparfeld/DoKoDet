# Recording HEAD and bounded pipeline reads

## Plan status

- **Status:** In Progress
- **Depends on:** 0114 complete; [0115](../5-closed/0115-Data_Cleanup.md) M15 qualification and
  final storage map complete. Stabilize any remaining changes to node
  storage, transactions, and isolated storage before implementation. The separate
  [0118 lifecycle follow-up](../5-closed/0118-Operational_and_Recovery_Lifecycle.md) is not a
  prerequisite unless M0 finds a direct storage-contract conflict.
- **Outcome:** Give each recording one durable HEAD to its selected pipeline state. Make catalog
  and current-workspace reads independent of retained history. Load history on demand. Reduce
  measured delay while preserving exact inputs, human work, and recovery.
- **Planning decision:** On 2026-11-08, the user requested this plan after discussing history reads
  as a cause of slow operations. This revised the unstarted plan. M0–M3 are complete. On
  2026-11-09, the M4 review found that exact node revision reads still traverse parent history.
  Replan 1 splits M4 into M4a, which defines durable node revision publication authority, and
  M4b, which completes the real-API workflow. Review found that exact authority reads also scan all
  coordinated transaction journals. Replan 2 assigns that storage/transaction contract to M4b,
  moves the API workflow to M4c, and keeps M5 separate. The 13-slot run now covers M4a, M4b, M4c,
  and M5–M14. M15 and M16 remain after the run limit unless the user authorizes another run.

## Evidence and scope

The [0114 closure report](../../reports/0114-M13_Final_Qualification_and_Closure.md) records
hard workspace reads of 20.219 s cold median and 20.293 s warm maximum. Startup to useful response
was 8.041 s median at revision `132987095cc7d5921ed9f7a6edd005574e81c442`.
Five `node_store.history` traversals accounted for 14.325 s of a 20.351 s workspace request.
These are historical measurements, not current latency guarantees.

Read-only code inspection at `b7098c782` found these paths:

- `recordings_api.list_recordings` builds the recording catalog and calls workspace `get_statuses`.
- `get_statuses` requests compact status, but `_node_revisions_for_recordings` enumerates nodes,
  scans lineage records, and traverses matching node histories.
- `get_workspace` uses the same reconstruction path and can parse historical revision content.
- `PipelineNodeStore` already has a per-node `head.json`. `PipelineNodeSelectionStore` already
  stores exact generated and completed-reference pointers per recording and content type.
- `RoundAnalysisService.recording_catalog` also reads packages and analysis history. A new pipeline
  HEAD alone will not eliminate that work.

The hypothesis is that normal reads reconstruct more state than the operator needs. M0 must
measure history size, unrelated-data scans, repeated validation, and payload parsing separately.
Adding HEAD without removing these paths would not satisfy this epic.

[0115](../5-closed/0115-Data_Cleanup.md) owns cleanup and its selected storage-format change.
This epic owns the current-state read boundary and its publication contract. Compare versions on
identical retained inputs. Report cleanup gains separately from runtime gains. Keep closed epics
and original performance evidence unchanged.

Scope includes the recording catalog, current workspace, explicit history and revision access,
selection/edit publication, and processor input defaults. One evidence-selected startup change
remains in scope. Model training, new review decisions, Git-like branches or merges, automatic
history pruning, and a general database replacement are outside scope.

## State and read contract

Use [recording state snapshot and recording HEAD](../../glossary.md#recording-state-snapshot)
with their glossary meanings. The physical format and API shapes are implementation decisions
in M1. The following behavior is required:

1. One recording HEAD points to one immutable snapshot. The snapshot identifies its recording,
   schema, version/digest, predecessor when present, and exact selected node/revision references.
   The fixed set of slots covers events, visible cards, table-plane calibration, virtual scenes,
   visual identities, table observations, and reconstruction results where applicable. Inventory
   actual storage kinds before defining their references; do not force all resources into nodes.
2. Generated and selected completed-reference pointers remain distinct. Keep explicit references
   for current independent review work where the existing workflow needs them. Missing stages
   remain empty. Creating a result or completing a review does not select it by itself.
3. A snapshot describes selected state; it need not assert that every stage is compatible. Store
   or derive explicit stale states from exact dependencies. Changing upstream input cannot relabel
   an old downstream result as current for that input. Preserve it for inspection. Do not silently
   substitute another branch, revision, or newer result.
4. Normal reads follow exact content dependencies. They do not walk snapshot predecessors, every
   revision parent, or copy ancestry to discover current state. Lineage and ancestry remain
   available through bounded explicit requests. Independent reviews can be siblings; a single
   downstream result's ancestors cannot define all recording state.
5. The catalog returns compact metadata and current-state summaries. It reads no pipeline revision
   payloads, node histories, or full processor/analysis histories. Active job status is a separate
   compact projection with its own version/freshness contract; HEAD is not a job status record.
6. Opening a workspace reads one snapshot and bounded stage metadata. Opening a stage loads its
   exact selected content and required dependencies. History, candidate discovery, and comparison
   load explicitly with stable pagination. Existing historical links remain resolvable.
7. Inspecting a historical revision changes the operator's lineage selection only. Changing
   recording HEAD is an explicit selection action. UI navigation and browser reload must preserve
   that distinction. An autosave of the currently selected working node may advance its slot under
   the existing edit semantics; editing a historical or independent review cannot select it.
8. A processor start freezes the snapshot ID and all resolved input references in the durable
   request. Execution and retry use those inputs even if HEAD changes. Output publication alone
   cannot move HEAD. Any existing explicit select-on-completion action must be recorded at launch
   and compare against its expected state; a conflict keeps the output available without replacing
   newer selections. Cancellation, failure, and partial output remain explicit.
9. HEAD advances with compare-and-swap across processes. A reader observes a complete old or new
   snapshot. Snapshot publication, HEAD replacement, and summary visibility have tested crash
   boundaries. Partial writes and stale summaries cannot appear as valid current state. Preserve
   existing copy-on-edit, protected inputs, independent reviews, and exact digest validation.
10. Validation matches the operation: validate snapshot identity and summary authority on compact
    reads; validate exact content and dependencies when content is used. Define corrupt/missing
    resource behavior explicitly. Catalog isolation must identify an affected recording rather
    than repair or silently replace its state. An offline audit can inspect all retained history.
11. HEAD is not the only retention root. Preserve drafts, independent reviews, selected references,
    active jobs, frozen datasets/evaluations, and their exact transitive dependencies under 0115's
    policy. This epic does not authorize deletion of off-HEAD content.

## Ownership and replacement inventory

M0/M1 must expand this starting list into an exact reader/writer/schema matrix. Keep it current
through removal. Each row needs its actual paths, replacement owner, and verification command.

| Current boundary | Replacement responsibility | Required evidence |
| --- | --- | --- |
| Node HEAD, revisions, and history | Exact revision reads; bounded metadata/history access | Revision identity, digest, copy ancestry, pagination |
| Per-content selections | Recording snapshot slots and explicit HEAD updates | Separate generated/reference selections; compare-and-swap |
| Workspace and lineage service | Current snapshot read; explicit history/graph requests | No implicit branch substitution; exact historical access |
| Recording catalog and round-analysis service | Compact recording/current-state projection | No revision payloads or full run/analysis histories |
| Review/edit/calibration writers | Publication of selected working-state changes | Independent review isolation; copy-on-edit; restart |
| Lineage writer, processor runs, orchestration | Frozen inputs and conditional output selection | HEAD changes during jobs; failure, retry, cancellation |
| Job Manager | Compact active-job projection | Cross-process freshness; completion/restart |
| Storage setup and recovery | Snapshot activation and retained authority | Isolated roots; recovery; audit without old runtime path |

## Execution and acceptance contract

Each milestone has one focused implementation-and-plan commit, with its checks and evidence.
All milestones are unstarted. This plan does not authorize workers or a multi-milestone run.
Keep each milestone small enough for one Luna phase. Split before assignment if it introduces
more than one new storage/transaction contract or an unbounded set of producer adapters.
If two attempts reveal prerequisites or fail to reduce scope, revise the plan before retrying.

Use local deterministic fixtures and disposable persisted storage for normal development.
Processor stubs are allowed. Before converting remaining consumers, prove one complete workflow
through real APIs/services with the replaced path disabled. Test concurrent readers/writers
separately from crash recovery. Do not preserve obsolete runtime formats through dual authority
or compatibility fallback. Conversion tools and tested recovery evidence can remain offline.

Reuse the 0114 harness, route inventory, 57 hard assets or a verified replacement, and seven
browser/load workflows. Record code revision, tool versions, fixture/storage digests, cache state,
commands, timing, and file-read/parser counters. Generated fixtures do not qualify the hard corpus.

M0 freezes numeric latency targets and a finite measurement budget from fresh measurements and
noise. Structural acceptance also requires:

- Catalog: zero pipeline revision-payload reads and zero history traversals.
- Current workspace: zero implicit history traversals; work scales with selected stages and exact
  required dependencies, not retained node/revision/run count.
- Growth fixtures: hold current content and active jobs fixed, then add 10x historical revisions
  and unrelated recording history. Current-state revision-payload/parser counts must not grow.
  Catalog work may scale with the number of returned recordings. Paginate that list if needed;
  freeze the choice in M1. Record metadata enumeration and latency as well as payload reads.
- History: complete addressability across stable pages, without missing or duplicate entries;
  fetching one page must not parse all historical payloads.
- First use: report catalog, workspace, stage-open, and startup-to-useful-response together. A
  faster initial response cannot hide the same history scan in a later ordinary request.

Run applicable backend/web tests, lint, format, types, and API generation checks for each affected
boundary. Check local Markdown links for plan changes. Keep successful prior checks unless new
changes or evidence require repetition. Give unrelated baseline failures a named follow-up and
origin evidence; they do not waive acceptance criteria. No speedup is claimed until measured.

## Milestone status

| Milestone | Observable result / commit boundary | State |
| --- | --- | --- |
| M0 | Post-cleanup baseline, exact boundary inventory, growth fixtures, frozen targets | Complete |
| M1 | Snapshot, HEAD, summary, and API contracts with validation tests | Complete; [report](../../reports/0117-M1_Recording_State_Contracts.md) |
| M2 | Immutable snapshot store and bounded exact reads | Complete; [report](../../reports/0117-M2_Immutable_Snapshot_Store.md) |
| M3 | Atomic HEAD/summary publication and concurrency/recovery proof | Complete; [report](../../reports/0117-M3_Atomic_HEAD_Publication.md) |
| M4a | Durable node revision authority and direct revision lookup; transaction scan excluded | In progress; [report](../../reports/0117-M4a_Node_Publication_Authority.md) |
| M4b | Bounded coordinated transaction recovery and pending-journal authority | Not started; separate storage/transaction contract |
| M4c | One real API workflow with old discovery disabled and no parent traversal | Not started; [report](../../reports/0117-M4_Real_API_Workflow.md) |
| M5 | Historical metadata and candidate discovery APIs with stable pagination | Not started |
| M6 | Compact recording catalog without revision/history reconstruction | Not started |
| M7 | Current workspace API with exact stage loading | Not started |
| M8 | Web current-state, history, and explicit HEAD-switch flow | Not started |
| M9 | Selection and review/edit writers publish the selected working state | Not started |
| M10 | Processor and orchestration requests freeze snapshot inputs | Not started |
| M11 | Output publication and compact job-state integration | Not started |
| M12 | Retained-state conversion rehearsal and activation readiness | Not started |
| M13 | Verified activation and removal of replaced runtime paths | Not started |
| M14 | Startup contract and disposable proof, or measured stop decision | Not started |
| M15 | One bounded startup change, or documented skip | Not started |
| M16 | Combined performance, workflow, growth, and recovery qualification | Not started |

## M0 — Measure the post-cleanup paths

Confirm 0115 M15 and the final storage layout. Validate retained hard assets and map current routes
to 0114 cases. Inventory representative schemas and every active reader/writer in the ownership
matrix. Count node/lineage enumeration, history traversal, full payload reads, repeated validation,
and parsing for catalog, workspace, stage, history, processor launch, and startup.

Add deterministic growth fixtures with fixed current state, more history, sibling reviews, empty
and stale stages, and unrelated recordings. Measure hard cold/warm requests and startup in three
independent uncontended sessions. Freeze numeric latency budgets, operation counts, reserved
cases, and a finite trial budget. State whether the HEAD hypothesis is supported before proceeding;
if not, revise this plan rather than implement unsupported work.

Checks: exact identities/digests, fixture validators, growth-counter assertions, timing applicability
and noise. Commit: measurement tools, inventory, report, board, and plan only.

**M0 result — 2026-11-09:** Complete. The post-cleanup hard workspace median is 20.983 seconds
cold and 20.941 seconds warm. Three independent startup processes have a 9.603-second median to
useful response in the original capture. A named omission required a replay of those three startup
processes with a visual-identities stage-open request. The corrected process samples report 3.272
seconds for catalog first use, 4.986 seconds for workspace first use, 3.265 seconds for stage-open,
and 8.928 seconds to the first useful response. This replay adds no capture set and does not change
frozen gates. The current catalog enumerates 12 nodes and traverses 11 histories; the current
workspace enumerates the same 12 nodes and traverses five histories. A deterministic fixture holds
current content and sibling review fixed while history and unrelated recordings grow 10x. Its
returned history records grow from 3 to 21. The measured evidence supports the HEAD hypothesis.
The [M0 report](../../reports/0117-M0_Post_Cleanup_Baseline.md) records the reader/writer/schema
inventory, separate history and full-payload reads, revision and node-manifest validation counts,
lineage scans, parser counts, empty/stale persisted cases, frozen ceilings and targets, trial limit,
and measurement limits. It maps each current route to the 0114 case inventory and names two missing
comparisons. The growth fixture asserts payload, validation, parser, lineage and latency counters
while history and unrelated recordings grow 10x.

## Execution handoff

- Requested run: 13 milestones, starting at M4a; completed: 0; remaining: 13. M4a is reopened
  because review found an unbounded recovery scan. The cap covers M4a, M4b, M4c, and M5–M14;
  M15 and M16 remain outside this run.
- Current milestone: M4a. Replan count: 2/5 for M4a; 2/10 for this run.
- M4a implementation to date: added immutable per-revision authority records and a direct exact read. `create`
  publishes the first record with the node; `save` commits at HEAD replacement and records the prior
  revision before advancing. Coordinated transaction recovery applies the same order. A missing
  authority record is accepted only for the exact current HEAD after a crash. Direct reads reject
  pre-HEAD orphans and do not read parent revisions during authority lookup. However,
  `read_authorized_revision` calls `recover_transactions`, which scans and validates every retained
  coordinated transaction journal, including committed journals. The one-revision read count does
  not prove bounded total read work. M4b owns this recovery scan. No full-read bound is claimed yet.
- Existing M4a checks: 94 focused backend tests passed; Ruff check and format check passed; local
  Markdown links/anchors and `git diff --check` passed. They include 11-revision zero-parent-read
  evidence, concurrent reader/writer processes, competing writer processes, process death at four
  node-store boundaries, and coordinated transaction recovery after process death. They do not
  cover a save attempt between coordinated plan validation and journal publication. One existing
  Starlette `httpx` deprecation warning remains. API generation/browser checks do not apply; the
  backend has no configured type check.
- M4a correction acceptance: state the safe lock order explicitly and prove with separate processes
  that an ordinary save cannot change HEAD after a coordinated transaction validates its plan but
  before the prepared journal is published. The transaction must commit or fail without leaving a
  prepared journal that blocks later reads. Correct the stale run counts after this correction.
- M4b boundary: add one durable pending-transaction locator so normal authority reads inspect at
  most the active prepared transaction, not all committed journal history. Preserve transaction
  idempotency and recovery evidence. Define its writer, atomicity, lock order, freshness, and crash
  recovery. Prove bounded recovery work as committed transaction history grows, plus competing
  readers/writers and separate crash/restart cases. This is an explicit storage/transaction
  milestone; do not fold it into M5.
- M4c remains separate: adapt the existing disposable real-API workflow to the direct authority
  read and M4b bounded recovery. Keep legacy selection/history discovery disabled. Prove frozen
  inputs, selection/editing, independent reviews, stale writes, older snapshot reads, and restart.
  M4c cannot start until M4b passes.
- Retained data stays unchanged. M12 must rehearse authority and pending-journal migration, preserve
  exact review/use dependencies, report unprovable records, and include recovery evidence. M13 can
  switch existing readers only after that rehearsal passes.
- Next: finish M4a correction only. Run count: 0 complete, 13 remaining.

## M1 — Define current-state operation contracts

Specify versioned snapshot, HEAD, summary, exact-resource references, failure responses, and API
shapes. Resolve calibration/reconstruction resource kinds and current review references from M0.
Define which actions change HEAD, stale downstream behavior, historical inspection, and explicit
restoration. Define summary derivation, publication authority, cross-process freshness, and repair.
Specify compact analysis/package/job metadata so the catalog cannot keep its old scans.

Define stable history/candidate cursors and page bounds. Lineage edges use a total order over exact
source and target endpoint fields, edge kind, role, and a stable unique per-edge `item_key`
tie-breaker. Serialize the complete composite key as canonical JSON in the cursor to avoid delimiter
ambiguity. The cursor must hold the longest valid composite key. Freeze membership with the
per-recording publication-sequence upper bound. Test duplicate endpoint pairs with differing kinds
or roles, continuation across a page boundary, and maximum-length valid endpoint and role keys. List
all API consumers and replacements.
Freeze which exact dependency checks belong to each operation. No timestamp-only validity proof.

Checks: contract tests for identity, empty/stale slots, independent reviews, missing/corrupt
references, generated/reference separation, unique lineage-edge ordering, page boundaries, and long
valid cursor keys. Commit: contracts, tests, report, board, and plan only.

**M1 result — 2026-11-09:** Complete. The [M1 report](../../reports/0117-M1_Recording_State_Contracts.md)
records the contracts, operation dependency checks, replacement inventory, and limits. Tests pass
for typed snapshot/resource/lineage-edge page entries, separate generated/reference summary states,
bounded metadata pages, Job Manager projection freshness and restart rules, monotonic history
insertion sequences, and unique lineage-edge ordering. Edge order includes exact endpoints, kind,
role, and stable `item_key`; the cursor uses a canonical JSON composite key and holds all valid keys.
Tests cover duplicate endpoints and page boundaries. M5 must honor the atomic sequence/item
publication contract. M2 owns snapshot storage and bounded exact reads; M1 does not implement runtime
behavior.

## M2 — Implement immutable snapshots

Add one snapshot storage family under the resolved isolated root. Store exact references and
compact stage metadata under a verified immutable identity. Provide direct reads without node
listing or predecessor traversal. Do not mutate referenced content or change selection yet.

Checks: canonical bytes/digests, round-trip, duplicate identity, missing/corrupt snapshots, isolation,
and constant read counts as history grows. Commit: snapshot store, tests, and evidence.

## M3 — Implement atomic HEAD publication

Build one publication operation for an already durable snapshot, its HEAD version, and the compact
summary defined in M1. Use existing transaction infrastructure where valid. Define recovery of
orphan snapshots and interrupted publication. No request may reconstruct authority from history.

Replanned acceptance for the remaining reader gap: deterministically pause a separate publisher
after the HEAD replacement and before the summary replacement. Instrument a separate reader's
process-lock call to signal immediately before a nonblocking exclusive lock attempt and confirm
that attempt fails while the publisher holds the lock. Then let the reader perform its normal
blocking read. Release the publisher and verify the reader returns the complete new HEAD, snapshot,
and summary. Keep the existing version observations and all other concurrency, stale-version, and
crash/recovery checks.

Checks: two processes updating one HEAD; deterministic separate-process reader contention at the
HEAD/summary boundary; existing version observations; stale expected version rejection; crash
injection at each durable boundary; restart and summary freshness.
Commit: publication operation, concurrency/recovery tests, and evidence.

**M3 result — 2026-11-09:** Complete. After M3 acceptance was replanned to add deterministic
separate-process reader contention at the HEAD/summary boundary. The publication API validates the
already stored immutable snapshot before it writes a prepared journal. It verifies the current
selected snapshot before an advance. It then atomically replaces HEAD, atomically replaces the
matching compact summary, and marks the journal committed. HEAD and summary writes use the existing
atomic JSON replacement primitive. One per-recording local process lock serializes readers,
publishers, and recovery across threads and processes. A prepared journal always rolls forward.
Recovery validates the exact derived summary and expected-to-new version transition. Committed
publication evidence prevents reinitialization if HEAD is missing. An orphan snapshot stays retained
but has no selection authority. Neither recovery nor summary repair scans predecessor history. The
[M3 report](../../reports/0117-M3_Atomic_HEAD_Publication.md) records two-process compare-and-swap,
deterministic reader contention, stale-version, process death immediately after each durable
replacement, restart, and summary-freshness results. The injected process death does not simulate
termination during the atomic JSON replacement itself. This proves the file store only; API and
retained-data activation remain later milestones.

## M4a — Define and implement node revision publication authority

Add the glossary term [node revision publication authority](../../glossary.md#node-revision-publication-authority).
Inventory every active node revision writer and exact reader from M0 and update the inventory with
the new authority record, writer, and verification check. Specify the authority record identity,
digest, commit point, concurrency behavior, freshness, atomicity, orphan behavior, and recovery.
Cover `PipelineNodeStore.create` and `save`, coordinated node transactions, and every other active
node-revision publisher. The new `read_authorized_revision` operation must validate one authority
record and one revision; for a current revision with no receipt after a crash, it may validate the
exact HEAD and that revision. It must not follow parent revisions. Published revisions remain
directly readable after HEAD advances. An uncommitted orphan without authority is rejected. Keep
existing production reader routing in place and do not convert retained data in this milestone.

Checks: direct authority lookup over growing revision history with zero parent reads; orphan and
corrupt authority rejection; concurrent readers and writers in separate processes; stale writer
rejection; injected process death at each node publication boundary followed by restart; supported
writer inventory; and an interleaving proof for save versus coordinated transaction preparation.
Do not claim bounded total reads while recovery scans transaction history. Commit: authority
contract and store implementation, tests, report, board, and plan. M4b depends on this result.

**M4a implementation note:** The [M4a report](../../reports/0117-M4a_Node_Publication_Authority.md)
records the `pipeline-node-publication/v1` receipt, its identity and digest checks, and the writer
and reader inventory. Store creation publishes its first authority atomically with the node.
Revision save and coordinated recovery publish authority around the HEAD commit under per-node
process locks. Direct authority lookup checks one receipt and one revision, or the exact current
HEAD and one revision after a crash. It does not read parent revisions. The overall read remains
unbounded by the all-journal recovery scan assigned to M4b.

## M4b — Bound coordinated transaction recovery

Define and implement a durable locator for the active prepared coordinated transaction. Normal
exact authority reads must inspect a bounded number of journal records, independent of committed
transaction history. Keep transaction idempotency lookup direct by transaction ID. Define lock order
for readers, node writers, coordinated writers, and recovery. Keep prepared-journal recovery
idempotent and distinguish committed archives from pending work. Do not convert retained data in
this milestone.

Checks: read work stays constant as committed journals grow; recovery sees each prepared journal;
stale transaction IDs remain rejected or idempotent under the existing contract; separate-process
reader/writer contention; process death at locator, journal, HEAD, selection, and commit boundaries;
restart recovery; and affected backend lint/format checks. Commit: locator/journal contract,
implementation, tests, report, board, and plan. M4c depends on this result.

## M4c — Prove one complete replacement workflow

Use real APIs/services and disposable storage to create/select events, produce a deterministic
output from frozen inputs, create independent review work, edit/save selected working content,
read HEAD/current state, inspect an older revision, and restart. Disable old selection/history
discovery in this proof. Use M4a publication authority and M4b bounded transaction recovery for
every exact node revision read. Add only the minimum producer/editor adapter needed for this slice.

Checks: exact persisted content, selected generated/reference pointers, independent decisions,
copy-on-edit, frozen inputs, stale update rejection, and restart. Commit: vertical slice and report.
Do not begin broad conversion until this proof passes. Keep M5 historical metadata discovery separate.

## M4b — Prove one complete replacement workflow

Use real APIs/services and disposable storage to create/select events, produce a deterministic
output from frozen inputs, create independent review work, edit/save selected working content,
read HEAD/current state, inspect an older revision, and restart. Disable old selection/history
discovery in this proof. Use M4a publication authority for every exact node revision read, with no
parent traversal. Add only the minimum producer/editor adapter needed for this vertical slice.

Checks: exact persisted content, selected generated/reference pointers, independent decisions,
copy-on-edit, frozen inputs, stale update rejection, and restart. Commit: vertical slice and report.
Do not begin broad conversion until this proof passes. Keep M5 bounded historical discovery separate.

## M5 — Add bounded historical discovery

Implement metadata-only pages for snapshots, node revisions, sibling candidates, and lineage edges
using M1 contracts. Keep direct historical revision access. Any new persistent metadata index must
have its writer, freshness, rebuild, concurrency, and crash checks specified before implementation;
split this milestone before assignment if that is a separate storage contract.

Checks: complete stable traversal, simultaneous new revisions, no duplicate/missing records within
the cursor's frozen boundary, exact ancestry, corrupt requested entries, and bounded payload reads.
Commit: historical discovery APIs, tests, and evidence.

## M6 — Convert the recording catalog

Replace pipeline status reconstruction with compact HEAD summaries and the compact job/analysis
metadata contract. Remove full analysis-history fields from the list if needed; fetch them through
explicit detail/history APIs and update list consumers together. Cover blocker computation without
loading selected observation payloads. Do not move the old scan into a helper or first-use cache.

Checks: real HTTP catalog, empty/mixed/corrupt recordings, active/failed/completed jobs, recording
isolation, restart, and M0 growth counters. Commit: catalog boundary and affected consumers/tests.

## M7 — Convert current workspace reads

Return current snapshot/stage metadata with explicit exact content URLs or requests. Load stage
content and its required dependency closure directly. Keep unrelated history out of this path.
Define observable stale/missing stages and preserve exact references for stage switching.

Checks: real API current state, exact stage reads, empty/stale/corrupt dependencies, cross-recording
rejection, history disabled, and growth counts. Commit: current-workspace API and tests.

## M8 — Convert the web workspace

Load current state first, stage content when opened, and history/candidates when requested. Preserve
historical deep links, independent review switching, and reload behavior. Expose an explicit action
to select historical state as current with conflict handling. Do not change HEAD during browsing.

Checks: frontend regressions plus a real-backend browser workflow with disposable persistence for
current state, history pages, revision switch, explicit selection, reload, and stale HEAD conflict.
Record first-use timings. Commit: web consumers and API-generation updates with evidence.

## M9 — Convert selection and edit publication

Convert remaining selection, autosave, review completion, calibration, and copy-on-edit adapters
identified in M0. Publish a new snapshot only when selected working state actually changes. Keep
independent review edits and review completion separate from completed-reference selection.
Before assignment, list the remaining adapters and split this milestone if they cannot fit one phase.

Checks: real API edit/save/readback/restart for affected kinds, independent reviews, protected
inputs, stale downstream marking, concurrent selection/edit conflicts, and exact retained decisions.
Commit: the bounded writer adapter set and report; no processor execution changes.

## M10 — Freeze processor and orchestration inputs

Convert default-input resolution, launch requests, retries, and multi-stage orchestration to exact
snapshot inputs. Explicit input overrides remain explicit and validated. Sequential orchestration
uses its own exact stage outputs; it must not re-read unrelated current HEAD between stages.
List the adapter set before assignment and split if it exceeds one phase.

Checks: deterministic real-service launch/persistence/restart, HEAD changes while queued/running,
retry after selection changes, overrides, and exact downstream input membership. Commit: request
freezing adapters and tests; output selection remains M11.

## M11 — Integrate output publication and job state

Publish outputs without automatic current-state replacement. Apply only explicitly requested
selection updates with compare-and-swap. Keep conflicting outputs discoverable and explain the
conflict. Connect compact active-job metadata to catalog/workspace status through the existing Job
Manager; define terminal-state visibility without scanning all historical jobs.

Checks: success, partial output, failure, cancel, retry, simultaneous completions, a newer selection
winning over an older job, cross-process freshness, and restart. Commit: completion adapters and
compact job-state integration. Split before assignment if a new projection store is required.

## M12 — Rehearse retained-state conversion

Freeze representative and full retained input inventories from the final 0115 layout. Convert
existing explicit selections and working-state references into snapshots in disposable storage.
Do not choose newest-by-time, merge independent reviews, or invent missing selections. Preserve
unselected resources as addressable history; report ambiguous authority as a concrete blocker.

Disable old runtime selection discovery. Verify real catalog/workspace, stage content, historical
access, edit/save, selection, processor start, and restart. Freeze exact activation manifest and
minimal tested recovery evidence. Enumerate all replaced readers/writers and remaining references.

Checks: exact content/digests, review decisions, dependency membership, round-trip recovery,
conversion idempotence/interruption, and fixture replacement validation. Commit: converter,
rehearsal evidence, activation manifest, and report. No live activation in this milestone.

## M13 — Activate and remove replaced paths

Recheck the activation manifest against actual storage and coordinate writers before cutover. Apply
the rehearsed conversion, verify durable state, and remove obsolete runtime selection stores and
implicit history reconstruction from normal requests. Keep offline recovery tools isolated. Update
setup and data-authority guidance. No off-HEAD deletion is authorized.

Checks: activation hashes, no old-path calls, real edit/save/selection/job/restart workflows,
historical addressability, recovery drill, applicable backend/web/static/API checks, and read-growth
acceptance. Commit: activated replacement, obsolete-path removal, and evidence.

## M14 — Prove the remaining startup boundary

Measure startup after M13 with empty, populated, and interrupted-recovery storage. Select at most
one bounded remaining cause. Freeze its target, operation contract, useful-response requirement,
and finite trial budget. Deferral cannot hide the same delay in the first useful request. Any new
persistent index/cache needs explicit ownership, validity, publication, and recovery rules; split
before implementation if necessary. A measured no-change decision is acceptable.

Checks: disposable real-process proof, first useful catalog/workspace/stage response, failure
visibility, concurrent first requests, and interrupted recovery. Commit: contract/proof or stop report.

## M15 — Implement the selected startup change

Implement only M14's selected boundary. Keep recovery and resource failures visible. If no candidate
was selected, record the skip. Revert an unsuccessful candidate and retain its evidence.

Checks: M14 regressions, repeated empty/populated/recovery process trials, useful-response timings,
CPU/memory/I/O where work moved or overlapped, affected and reserved 0114 cases, and static checks.
Commit: one verified startup change or documented skip/reverted result.

## M16 — Qualify and close

Repeat affected M0 cases in three independent sessions with the same inputs and machine profile.
Run adapted 0114 qualification, all startup profiles, seven browser/load workflows, and the growth
fixtures. Justify reused unchanged checks. Report latency, reads, parses, noise, and any added
storage/publication cost. Keep catalog, workspace, stage-open, history, and startup costs separate.

Verify through real services and disposable persistence: all selected content kinds, independent
reviews, explicit HEAD switch, paginated history, historical links, exact processor inputs, jobs,
media, editing/save, restart, conversion, and recovery. Run combined tests and static/API checks.
Check local Markdown links and preserve original baselines. List remaining slow debt with owners.

Close as Complete only when required state/read contracts and frozen performance targets pass.
If evidence contradicts the plan, record the remaining work instead of claiming closure. Commit:
combined report, board, epic status/move, and mechanical link updates.
