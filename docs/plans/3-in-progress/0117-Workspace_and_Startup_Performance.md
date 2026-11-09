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
  moves the API workflow to M4c, and keeps M5 separate. The prior 13-slot run stopped after two
  M4a correction turns. The new 15-slot run includes M15 and excludes M16. On 2026-11-09, M5
  review found that the shared history sequence must be published
  atomically with metadata across several existing stores. Replan 3 splits M5 into M5a, which
  defines and implements the durable shared history authority, and M5b, which adds discovery APIs.
  Replan 4 adds a history generation to cursors because rebuild can change sequence membership and
  sequence-only cursors cannot expire safely. To keep the current 15-slot run limit, M16 is outside
  this run. M5a review then found that exact item digests, authority sequence bounds, generation
  validation before pointer switch, and missing active-pointer handling need stronger checks. It
  also confirmed that four separate source owners can commit before the history index, leaving a
  crash gap, and M1/M0 do not identify a persisted candidate source. Replan 5 assigns the bounded
  query APIs to M5b and source adapters, gap reconciliation, and candidate-source identification to
  M5c. The prior 15-slot run ended at M14. A new 14-milestone run starts at M5a and includes M5b,
  M5c, and M6–M16. On 2026-11-09, review found that the M5b API used sequence order, unsigned
  base64 cursors, and a full metadata scan per page. M1 requires collection-key ordering, signed
  cursors, and bounded page reads. Replan 6 splits M5b into M5b1, an ordered cursor-addressable
  index with atomic publication and rebuild, and M5b2, the M1-compliant API. The committed M5b API
  is unaccepted and disabled until M5b2. Persisted corruption must return HTTP 500. M5c remains
  independent. The current 14-slot run ends at M15; M16 is outside this run. On 2026-11-09, M5c
  source inspection found no persisted candidate source or candidate-specific selection rule. It
  also found three independent source transaction boundaries. Replan 7 splits M5c into M5c1 node
  revision publication, M5c2 snapshot publication, and M5c3 lineage publication. This keeps the
  14-slot cap: M14 and M15 move outside this run. Replan 8 found that `/state/candidates` has no
  publisher, persisted source, or web consumer. Actual proposal values remain in exact node content
  or calibration-refinement preview; applying a calibration refinement publishes a calibration
  revision. M5c4 removes the unsupported generic collection, route, index entry, and contract types
  while preserving those existing discovery flows. This supersedes the earlier plan to identify or
  publish a generic candidate source. M5 discovery is complete. The 14-slot cap stays unchanged and
  M13 remains outside this run. On 2026-11-09, M6 inspection found no runtime implementation for
  M1's compact catalog metadata or Job Manager authority/projection contracts. Job records are
  read in full, and durable `job.json` writes occur across acceptance, scheduler, API, publication,
  and recovery paths. Replan 9 splits M6 into M6a (durable authority and journaled job transitions),
  M6b (bounded active-job projection), M6c (bounded analysis/package metadata), and M6d (catalog
  conversion). M11 retains output publication ownership. The 14-milestone run now covers M6a–M6d
  and M7–M9; M10–M16 are outside this run.

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
   exact selected content and required dependencies. History and comparison load explicitly with
   stable pagination. Proposal discovery reads exact selected node content or the existing
   calibration-refinement preview; it does not use generic history pagination. Existing historical
   links remain resolvable.
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
| M4a | Durable node revision authority and direct revision lookup; transaction scan excluded | Complete; [report](../../reports/0117-M4a_Node_Publication_Authority.md) |
| M4b | Bounded coordinated transaction recovery and pending-journal authority | Complete; [report](../../reports/0117-M4b_Bounded_Transaction_Recovery.md) |
| M4c | One real API workflow with old discovery disabled and no parent traversal | Complete; [report](../../reports/0117-M4_Real_API_Workflow.md) |
| M5a | Durable shared history authority and rebuild contract | Complete; [report](../../reports/0117-M5a_History_Authority.md) |
| M5b | Bounded history API pages over the durable metadata index | Incomplete; split by replan 6 |
| M5b1 | Ordered cursor-addressable history index with atomic publication and rebuild | Complete; correction 1/2; [report](../../reports/0117-M5b1_Ordered_History_Index.md) |
| M5b2 | M1-compliant pages, signed cursors, lineage continuation, corruption mapping | Complete; [report](../../reports/0117-M5b2_M1_Compliant_History_Pages.md) |
| M5c | Source publisher adapters, gap reconciliation, and candidate-source decision | Complete; see M5c1–M5c4 reports |
| M5c1 | Pipeline node revision publisher with bounded crash-gap recovery | Complete; [report](../../reports/0117-M5c1_Node_Revision_History_Publisher.md) |
| M5c2 | Recording snapshot publisher with bounded crash-gap recovery | Complete; [report](../../reports/0117-M5c2_Recording_Snapshot_History_Publisher.md) |
| M5c3 | Pipeline lineage run and edge publisher with bounded crash-gap recovery | Complete; [report](../../reports/0117-M5c3_Lineage_History_Publisher.md) |
| M5c4 | Remove unsupported generic candidate history while preserving exact proposal discovery | Complete; [report](../../reports/0117-M5c4_Candidate_History_Removal.md) |
| M6 | Compact recording catalog without revision/history reconstruction | Incomplete; split by replan 9 |
| M6a | Durable Job Manager authority and journaled job-record transitions | Complete; [report](../../reports/0117-M6a_Job_Projection_Authority.md) |
| M6b | Bounded active-job projections over the M6a authority | Not started |
| M6c | Bounded analysis and package metadata pages | Not started |
| M6d | Recording catalog from verified HEAD and compact metadata | Not started |
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

- Requested run: 14 milestones, starting at M5a; completed: 8; remaining: 6. The revised cap
  covers M5a, M5b1, M5b2, M5c1–M5c4, M6a–M6d, and M7–M9. M10–M16 are outside this run.
- Next: M6b. M6a replan count: 0/5; M6a correction count: 0/2; M5c replan count: 2/5; this run
  replan count: 4/10. M5c4 correction count:
  0/2. M5c3 correction count: 1/2. M5b replan count: 1/5; M5b1 correction
  count: 1/2; M5b2 correction count: 2/2. Previous-run
  correction history is preserved in the milestone report and does not count against this run.
  Current-run M5a correction count: 2/2. M6a completed with authority advances for each durable
  `job.json` write, journal recovery after restart, digest conflict rejection, and serialized readers
  and writers. Checks and the full writer inventory are in the [M6a report](../../reports/0117-M6a_Job_Projection_Authority.md).
  The M6a commit does not implement job projections, analysis/package metadata pages, or catalog
  conversion. Those remain M6b–M6d. M6b is next; 6 run milestones remain.
- M5b2 result: complete after the resumed authority-loss fix. The four history routes use M5b1's stable collection order and frozen
  sequence roots. HMAC cursors bind recording, collection, empty-filter digest, generation,
  sequence, full stable key, and page size. The private cursor key and local digest record use
  atomic mode-0600 writes with file and directory sync. A separate operations-root authority stores
  the key digest. Tested key-loss and mismatch cases fail closed, except as noted below. Legacy data requires explicit
  bootstrap, preserving an available key or requiring explicit cursor invalidation if no key
  remains. New publishers establish cursor authority before history publication. Unknown recordings
  return 404 without initializing history.
  Invalid cursors map to 422, expired generations to 410, and persisted history corruption to 500.
  Corrections 1/2 and 2/2 add crash/loss/restart and authority recovery tests, simultaneous revision
  publication, exact lineage endpoint checks, and bounded metadata/no-payload API evidence. Source
  publication and durable gap reconciliation remain with M5c. See the
  [M5b2 report](../../reports/0117-M5b2_M1_Compliant_History_Pages.md).
  The resumed fix checks inactive retained generations when the active generation is empty. Its
  regression proves that loss of the key, marker, and authority after a non-empty generation was
  retained returns HTTP 500 and requires explicit cursor invalidation. Initial empty-generation
  rebuilds remain supported. Focused API/store/index/contract/workflow tests, Ruff check and format,
  and OpenAPI verification passed. Browser checks were not applicable because no web consumer or API
  contract changed. Replan 7 raised the current run replan count to 2/10 and split source adapters
  by their durable transaction owners. M5c1 correction count: 2/2.
- M5c1 result: complete for recording-owned `PipelineNodeStore` revisions. A pending outbox intent
  is durable before revision commit. Node creation commits its initial revision, publication
  authority, HEAD, and source manifest together; ordinary saves publish the node HEAD and revision
  authority before dispatch; coordinated transactions append exact revision intents and dispatch
  after journal recovery. Replay reads only the pending outbox, node manifest/HEAD, and publication
  authority. It does not parse revision content. Missing uncommitted source revisions are removed;
  committed revisions publish idempotently through M5a before the outbox clears. History page reads
  recover the named pending coordinated transaction, then reconcile the pending revision outbox.
  Crash/restart checks cover source HEAD commit and history commit gaps. A coordinated two-node
  transaction publishes all four exact revisions. The history API recovery test rejects revision
  payload reads. Focused pytest, Ruff check and format, diff check, and local link checks passed;
  OpenAPI and browser checks were not applicable. See the
  [M5c1 report](../../reports/0117-M5c1_Node_Revision_History_Publisher.md).
- M5c1 correction 1/2: reconciliation now treats only an absent node directory as an uncommitted
  create. An existing corrupt or unreadable node fails closed and retains its outbox intent. Ordinary
  saves reject an already-used revision ID before writing an intent. Focused regressions pass.
- M5c1 correction 2/2: a missing or malformed revision path now fails closed when HEAD or publication
  authority proves the revision was committed. Reconciliation drops a missing revision only when no
  commit evidence exists. A missing uncommitted revision regression confirms the outbox can still
  clear safely. Focused tests, Ruff checks, format, diff, and link checks pass.
- M5c2 result: complete for snapshots written through `RecordingStateSnapshotStore.put`. The
  per-recording process lock protects one durable snapshot-history outbox entry. The entry binds
  the exact snapshot ID, content digest, predecessor, and compact stage metadata before the
  snapshot directory commits. Replay validates the committed metadata without reading snapshot
  payloads, publishes the exact history item idempotently, and clears the outbox with a directory
  sync. A history page replays only its named recording's pending snapshot entry. A missing source
  is discarded only when its exact history item is absent; an already-published item with a missing
  source fails closed and retains the intent. Malformed intent, source metadata mismatch, and
  symlink paths fail closed. Replay also requires a regular, non-symlink snapshot payload without
  reading it. An exact repeated `put` can publish a legacy source without listing
  storage. Retained snapshots without writer intents remain for the M12 rehearsal.
  Child-process stops cover before source commit, after source commit, and after history commit.
  Two-process writers preserve both items. The real history API recovery check forbids snapshot
  payload reads. Focused snapshot/history/store/workflow tests, Ruff, OpenAPI verification, and
  `git diff --check` passed. Browser and type checks do not apply: no web consumer or OpenAPI
  contract changed, and backend has no configured type checker. M5c2 correction count: 1/2. The
  correction verifies exact history evidence before dropping a missing source and rejects missing,
  symlinked, or non-regular snapshot payload paths without reading payload bytes. See
  the [M5c2 report](../../reports/0117-M5c2_Recording_Snapshot_History_Publisher.md).
- M5c3 result: complete for terminal `PipelineLineage` runs. The writer stores a per-recording
  outbox with exact `used` and `produced` edges before it commits the terminal run. It validates
  the exact run identity, publishes idempotently through the recording history store, and syncs
  outbox removal. The history API replays only the requested recording's lineage intent. A
  simulated source-to-index failure leaves a durable intent; replay publishes the exact edge.
  Malformed intent, digest mismatch, source mismatch, and published edges with a missing source
  fail closed. Focused lineage/history/API tests (61 passed), including two spawned writers for one
  recording, Ruff check/format, OpenAPI
  verification, and `git diff --check` passed. No web consumer or schema changed; browser and
  backend type checks do not apply.
  Correction 1/2 makes identical terminal retries reconcile and republish from the committed run
  before success. Regressions cover corrupt intent retries, stop before source commit, partial
  two-edge publication and idempotent retry, mismatched and missing source, FIFO rejection, and
  recovery through the real history API. The complete focused suite now passes 65 tests.
  See the [M5c3 report](../../reports/0117-M5c3_Lineage_History_Publisher.md). M5c4 removed the
  unsupported generic collection and completed M5 discovery. The run is 7/14 complete, with 7
  milestones remaining.
- M5c evidence and replan 8: code and OpenAPI inspection found no candidate-history publisher,
  persisted source, or web consumer. Actual proposal values remain discoverable in exact node
  content and calibration-refinement preview. Applying a calibration refinement materializes a
  calibration revision, which remains in `/state/revisions`. The generic collection duplicated no
  defined source and had no defined semantics. M5c4 removes only that unused generic API/index
  contract. It preserves existing proposal and refinement discovery and makes no human-review
  claim.
- M4a result: direct node revision authority remains as recorded below. The final review gaps are
  fixed: exact node reads hold the root transaction lock across recovery and content read; exact
  selection reads do the same; selection writes take the root lock before their selection lock.
  This prevents a coordinated writer from publishing between recovery and read and prevents the
  selection/recovery lock inversion. M4b still owns bounded journal discovery. No full-read bound
  is claimed.
- M4a checks: 105 focused backend tests passed, including deterministic same-instance thread and
  separate-process recovery/read interleavings and a separate-process selection lock-order
  interleaving. All `test_pipeline_node_*.py` tests passed. Ruff check, Ruff format check, and
  `git diff --check` passed. One existing Starlette `httpx` deprecation warning remains. API
  generation/browser checks do not apply; the backend has no configured type check.
- Earlier M4a evidence remains valid: direct authority lookup over 11 revisions reads no parents;
  crash/restart and stale-writer checks cover node and coordinated publication boundaries; the
  earlier correction turns proved recovery serialization. See the [M4a report](../../reports/0117-M4a_Node_Publication_Authority.md).
- M4b result: `.coordinated-transactions/.locator/pending.json` names at most one active prepared
  transaction. Its directory is separate from direct transaction-ID journal paths, so valid IDs
  such as `pending` remain safe. The writer publishes the locator atomically before the prepared
  journal under the root transaction lock. Recovery reads only that journal, rolls it forward
  idempotently, and atomically clears the locator. Committed journals remain available for direct
  transaction-ID replay checks. Exact authority reads inspect no committed journals when there is
  no pending transaction.
- M4b checks: transaction tests pass, including transaction ID `pending` through recovery and
  replay; 100 committed journals with zero journal reads for
  an exact authority read; same-ID replay and conflicting reuse; six separate-process crash points
  from locator through committed journal; restart recovery; and existing thread/process lock
  interleavings. Ruff check, Ruff format check, and `git diff --check` pass. See the [M4b report](../../reports/0117-M4b_Bounded_Transaction_Recovery.md).
- M4c result: Complete. The real-API workflow routes frozen producer reads, review validation,
  accepted-use validation, selected editing, and exact revision HTTP reads through M4a authority.
  The test fails on the legacy parent-traversing reader and old selection/history/workspace
  discovery. It seeds 25 committed journals and observes zero journal reads during exact reads,
  both before and after restart.
- M4c checks: recording-state workflow, contract, store, publication, and all pipeline-node tests
  pass. Ruff check and format check pass; `git diff --check` passes. The workflow proves exact
  persisted content, separate generated and completed-reference selections, independent review
  decisions, copy-on-edit, frozen inputs, stale and cross-recording update rejection, older
  snapshot access, and restart. The existing Starlette `httpx` deprecation warning remains.
  See the [M4c report](../../reports/0117-M4_Real_API_Workflow.md).
- M5a result: the shared history store assigns a per-recording sequence and publishes immutable
  metadata through a recoverable journal. Readers validate metadata digest and sequence against
  authority. Rebuild validates each item and authority before switching the active pointer. Recovery
  retries empty initialization after process death during staging. It asks callers to retry a
  nonempty initial rebuild with source metadata. It preserves the prior active generation when a
  replacement rebuild dies before commit. A missing active pointer with committed generation data
  remains corruption. The store does not read payloads or connect source publishers or discovery APIs.
- M5a checks: 39 history-store and contract tests passed, including publication crash boundaries,
  actual child-process death during empty, nonempty, and replacement generation staging, restart
  recovery, invalid retry input, and process death immediately before and after retry-journal
  replacement, injected staging exception with restart, rebuild validation before pointer switch,
  cursor expiration, digest and sequence corruption, missing active pointer, two-process
  publication, corrupt-journal rejection, and page/cursor contracts. Ruff check and format check
  passed for changed backend files and tests;
  `git diff --check` and local Markdown link checks passed. See the
  [M5a report](../../reports/0117-M5a_History_Authority.md).
- M5a prior correction 2/2 adds a durable generation journal. A child process exits after committing the
  initial generation directory but before publishing `active.json`; a fresh process validates that
  generation and publishes the pointer. Missing pointers without a matching generation journal
  remain corruption.
- M5a current-run correction 1/2 preserves the pending generation journal while retry source
  metadata is validated. Atomic journal replacement provides the handoff to the new retry. Invalid
  input and process death immediately before or after this replacement both retain a retry-required
  state, not empty history.
- M5a current-run correction 2/2 also preserves the retry journal after a caught exception during
  initial nonempty staging. Restart still requires the source metadata; tests verify this path and
  the existing publication, rebuild, and pointer-recovery boundaries.
- M5b status: incomplete. Commit `475f011f` exposed a sequence-ordered API with unsigned base64
  cursors and a full metadata scan on each request. This violates M1 stable-key ordering, cursor
  integrity, and bounded page reads. Replan 6 splits the ordered index contract into M5b1 and the
  M1-compliant API into M5b2. Disable the current API until M5b2. M5c retains source publishers and
  durable-to-index gap reconciliation.
- M5b1 result: the store writes immutable AVL index nodes and a collection-root snapshot for every
  authority sequence. Each root contains the complete M1 order for snapshots, revisions, candidates,
  and lineage edges. Publication writes the item and index before advancing authority; recovery
  retries that sequence. Rebuild simulates every publication in memory and checks each root against
  its exact prefix, then validates nodes reachable from all historical roots before it changes the
  active generation. This detects missing nodes exclusive to an older tree and checksum-valid roots
  with the wrong prefix. The old unaccepted page route and full-scan method are removed.
- M5b1 checks: focused index, store, contract, and workflow tests passed. They cover stable
  order for all collections, exact lineage continuation keys, a later insertion sorting before a
  frozen cursor, bounded tree and metadata reads at 256 items, corruption checks, actual child
  process death after item/index/authority publication, restart, rebuild, missing historical-only
  nodes, and checksum-valid wrong historical membership rejected before activation. Ruff, OpenAPI
  generation/verification, and `git diff --check` passed. A temporary 256-item local probe measured
  2,296 immutable nodes, 257 sequence roots, and 816,428 index bytes. See the
  [M5b1 report](../../reports/0117-M5b1_Ordered_History_Index.md).
- Replan 1 split M5 into the durable authority store (M5a) and discovery APIs (M5b). Replan 2
  added generation pinning because sequence-only cursors cannot expire safely after rebuild.
- Replan 3 assigned source publication and crash-gap reconciliation to M5c. Replan 7 split its
  owners: M5c1 is `PipelineNodeStore`/`PipelineNodeTransactions`; M5c2 is
  `RecordingStateSnapshotStore`; M5c3 is `PipelineLineage`. The following candidate-source
  requirement was superseded by Replan 8 and M5c4: M0/M1 did not name a source or meaning for the
  generic `candidates` collection. M5 discovery is now complete after removal of that unsupported
  collection; proposal discovery remains in exact node content and calibration-refinement preview.
- Retained data stays unchanged. M12 must rehearse authority and pending-journal migration, preserve
  exact review/use dependencies, report unprovable records, and include recovery evidence. M13 can
  switch existing readers only after that rehearsal passes.
- Historical acceptance note: this pre-Replan 8 instruction is complete and superseded. M5c1–M5c3
  publish snapshots, revisions, and lineage edges with crash-gap recovery; M5c4 removes the
  unsupported generic candidate collection. M5 discovery is complete.

## Replan 8 — Candidate discovery decision

The M5a and M5b specifications below record the original four-collection design. Their `candidates`
collection references, the earlier M5c source-identification requirement, and the M5b2 statement
that source discovery remained incomplete are historical and superseded by Replan 8 and M5c4.
History contains snapshots, revisions, and lineage edges. The unsupported generic candidate route
and index collection are removed. Actual proposal values remain inside exact pipeline node content
or the existing calibration-refinement preview. Applying a calibration refinement materializes a
calibration revision. M5 discovery is complete. Do not add a candidate publisher or generic
candidate-history consumer.

## M1 — Define current-state operation contracts

Specify versioned snapshot, HEAD, summary, exact-resource references, failure responses, and API
shapes. Resolve calibration/reconstruction resource kinds and current review references from M0.
Define which actions change HEAD, stale downstream behavior, historical inspection, and explicit
restoration. Define summary derivation, publication authority, cross-process freshness, and repair.
Specify compact analysis/package/job metadata so the catalog cannot keep its old scans.

Define stable history cursors and page bounds for snapshots, revisions, and lineage edges. Lineage
edges use a total order over exact source and target endpoint fields, edge kind, role, and a stable
unique per-edge `item_key` tie-breaker. Serialize the complete composite key as canonical JSON in
the cursor to avoid delimiter ambiguity. The cursor must hold the longest valid composite key.
Freeze membership with the per-recording publication-sequence upper bound. Test duplicate endpoint
pairs with differing kinds or roles, continuation across a page boundary, and maximum-length valid
endpoint and role keys. List all API consumers and replacements.
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

**M4a result — 2026-11-09:** Complete for direct node authority lookup and serialized writers. The
[M4a report](../../reports/0117-M4a_Node_Publication_Authority.md)
records the `pipeline-node-publication/v1` receipt, its identity and digest checks, and the writer
and reader inventory. Store creation publishes its first authority atomically with the node.
Revision save and coordinated recovery publish authority around the HEAD commit under per-node
process locks. A deterministic multi-process interleaving proves that save, transaction preparation,
and recovery serialize under the documented lock order. Recovery takes the reentrant root
transaction lock; reentrancy is thread-local, so another thread cannot skip a partially applied
journal. Same-instance thread and separate-process tests pause recovery between node HEAD updates
and prove readers wait for the full transaction. Direct authority lookup checks one receipt
and one revision, or the exact current HEAD and one revision after a crash. It does not read parent
revisions. Exact node and selection reads hold the root transaction lock across recovery and the
read. Exact selection writes take the root lock before the selection lock. Deterministic thread and
process interleavings prove the read interval excludes a partial coordinated publication and that a
selection writer cannot hold its lock while waiting for recovery. The overall read remains
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

## M5a — Define and implement shared history authority

Define and implement the durable per-recording `RecordingHistoryAuthority` store that assigns a
strictly increasing insertion sequence to snapshots, node revisions, candidates, and lineage
edges. Keep each metadata item and its authority sequence atomically visible. The history index is
derived metadata: specify how writers publish, how readers detect stale or corrupt state, how an
offline rebuild derives a valid authority and expires old cursors. Cursors pin the authority
generation. Rebuild creates and validates a complete generation, then changes one active pointer.
Define how concurrent writers and crash recovery behave. Do not convert producer stores in this
milestone; their publication adapters belong to the relevant follow-up milestones.

Checks: exact item identity and digest validation; sequence monotonicity and idempotent duplicate
publication; two-process writer serialization; metadata and authority visibility across every
crash point; restart recovery; corruption and rebuild behavior; no content-payload reads. Commit:
history authority contract, store, tests, report, board, and plan.

## M5b1 — Add the ordered history index contract

Extend the M5a generation with an immutable ordered index for snapshots, revisions, candidates,
and lineage edges. A page at authority sequence N must resolve an index root for exactly N, so later
publications cannot move or enter that traversal. Use the M1 collection-specific total-order keys.
Lineage keys include every exact endpoint identity, edge kind, role, and stable item key. Publish
the immutable item and index nodes before advancing the authority sequence. Recovery must complete
or reject each crash state without scanning source history. Rebuild creates and validates every
sequence root before switching the generation pointer. Keep source publishers and their durable to
index gap reconciliation in M5c. Disable the prior M5b API and remove its full metadata scan.

Checks: exact sorted traversal for every collection; frozen membership when a later key sorts
before the cursor; bounded node and item reads as history grows; complete lineage-key continuation;
index corruption and missing-node detection; duplicate index identity rejection; two-process
publication; death after item, index-root, and authority publication; retry and restart; deterministic
rebuild; and generation cursor expiry. Commit: ordered-index storage contract, recovery and rebuild,
tests, evidence, and the disabled unaccepted API. No page API or source publisher is completed here.

## M5b2 — Expose M1-compliant history pages

Expose metadata-only pages over M5b1's immutable ordered roots. Sign cursors with an integrity key
and bind recording, collection, normalized filters, generation, frozen sequence, full canonical
last key, and page size. Continue by the exact M1 total order. Keep direct historical revision
access. Map invalid input to 422, expired cursors to 410, and corrupt persisted authority or index
state to 500. Do not read content payloads. M5b2 does not complete source discovery until M5c
publishes all source items and closes durable-to-index crash gaps.

Checks: complete stable traversal and canonical lineage continuation; simultaneous new revisions,
including keys before the current cursor; no duplicate or missing entries at the frozen sequence;
cursor tamper, filter, collection, page-size, and generation checks; exact ancestry; corrupt requested
entries map to 500; bounded metadata and content reads; OpenAPI generation; and real API restart.
Commit: historical discovery APIs, signed cursors, tests, API types, evidence, and board updates.

## M5c — Connect supported history sources and reconcile gaps

This parent milestone is complete through M5c1–M5c4. Publish the supported snapshot, revision, and
lineage-edge sources through M5a after source data is durable. Define per-source recovery or an
outbox so a crash between source commit and history publication cannot leave a permanent omission.
Reconcile idempotently without a full scan on each page request. M5c4 removed the unsupported
generic candidate collection; do not add a candidate publisher. Actual proposal values remain in
exact pipeline node content or calibration-refinement preview, and apply materializes a calibration
revision. Keep history entries metadata-only and exact.

Checks completed: inventory each writer and its source transaction; deterministic crash/restart tests
between source commit and index publication for each supported source family; duplicate-free
reconciliation after restart; complete page traversal against durable sources; no payload reads for
metadata pages; remove the candidate route and collection from code, contract, index, and OpenAPI;
preserve actual proposal discovery. See the M5c1–M5c4 reports. M5 discovery is complete.

## M6a — Publish durable Job Manager authority

Implement the M1 `JobProjectionAuthority` with a stable manager identity, durable epoch, and
monotonic sequence. Route every durable `job.json` replacement through one journaled transaction
that binds the prior and next job revisions/digests and authority values. Recover a prepared
transaction idempotently after restart. The existing manager owner lock and thread lock serialize
writers. Cover acceptance, dispatch, scheduler/API mutation, publication metadata, cancellation,
and recovery. Do not create per-recording projections or change output selection.

Checks: inventory every writer path; crash recovery at each journal boundary; digest conflict
handling; restart; concurrent reader/writer and second-manager ownership behavior. Commit: authority
and journaled job transition boundary with tests and report.

## M6b — Build bounded active-job projections

Use the M6a authority to build compact active-job projections. Validate freshness across processes
and rebuild stale or missing projections from authoritative Job Manager records. Keep terminal job
history out of the active projection and preserve M11 output publication ownership.

Checks: active job pages, status transitions, frozen cursor authority, process restart, stale
projection detection/rebuild, concurrent reader/writer freshness, and recording isolation. Commit:
bounded job projection read contract and tests.

## M6c — Add bounded analysis and package metadata

Add metadata-only reads and bounded per-recording pages for analyses and evidence packages using
the M1 contracts. Do not parse analysis results, package content, lineage history, or unbounded
collections to build a page.

Checks: empty, mixed, corrupt, isolated, restart, and 10x growth cases over persisted metadata.
Commit: bounded analysis/package metadata APIs and tests.

## M6d — Convert the recording catalog

Replace pipeline status reconstruction with verified compact HEAD summaries and bounded compact
job, analysis, and package metadata. Remove full analysis-history fields from the list; use explicit
detail or metadata pages and update consumers together. Cover blocker computation from exact
selected table-observation metadata without loading selected observation payloads. Do not move the
old scan into a helper or first-use cache.

Checks: real HTTP catalog, empty/mixed/corrupt recordings, active/failed/completed jobs, recording
isolation, restart, and M0 growth counters. Commit: catalog boundary and affected consumers/tests.

## M7 — Convert current workspace reads

Return current snapshot/stage metadata with explicit exact content URLs or requests. Load stage
content and its required dependency closure directly. Keep unrelated history out of this path.
Define observable stale/missing stages and preserve exact references for stage switching.

Checks: real API current state, exact stage reads, empty/stale/corrupt dependencies, cross-recording
rejection, history disabled, and growth counts. Commit: current-workspace API and tests.

## M8 — Convert the web workspace

Load current state first and stage content when opened. Load snapshot, revision, and lineage-edge
history on request. Read proposal values from exact selected node content and the existing
calibration-refinement preview; the preview is computed by its existing GET workflow, and apply
materializes a calibration revision. Do not add or call a generic candidate-history API. Preserve
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
