# Epic 0108 retrospective

Date: 2026-11-07

This review inspected commit history, retained chat records, current source, focused tests, and
the main checkout's persisted migration data. Source and test results below refer to `be4ed7243`.
Other work continued in the main checkout during this review. This report does not change the
closed epic, runtime code, or agent policy.

The main failure was planning and verification. M10 combined migration discovery, importer
development, activation, and runtime integration. M11 combined architecture development, consumer
conversion, data conversion, and deletion. Both exceeded the project's one-phase milestone rule.
The agents kept completing local packages while the remaining system contract stayed open.

## What the result supports

The architectural change is substantial and useful. Runtime composition constructs the node store,
exact selection store, lineage writer, node editing, and node review services. Processor output
publication goes through the lineage writer. Calibration uses node-native working state. See
[composition](../../backend/src/dokodetector_backend/pipeline_composition.py),
[publication](../../backend/src/dokodetector_backend/pipeline_lineage_writer.py), and
[selections](../../backend/src/dokodetector_backend/pipeline_node_selection_store.py).

Read-only inspection of `/Users/niklas.sparfeld/Developer/doko_detector` confirmed:

| Check | Current result |
| --- | --- |
| Active node manifests / revision directories | 1,006 / 1,223 |
| Canonical selection files / nonempty pointers | 136 / 187 |
| Selected target recording, content type, and revision existence | All 187 pass |
| Selected revision content SHA-256 | All 187 match their stored content digests |
| Active old reference and review stores | Both absent |
| Reference recovery snapshot | 511 files, 121,556,946 bytes; receipt counts match |
| Review recovery snapshot | 53 files, 21,514,843 bytes; receipt counts match |

The recovery inspection repeated file and byte counts. It did not repeat the complete historical
tree-digest audit or prove the semantic preservation of every migrated review. The selection audit
validated the selected revisions, not every historical revision or every downstream dependency.

Fresh automated checks passed 112 focused backend tests and 34 web tests. One additional backend
test failed: `test_factory_converts_interrupted_round_analysis_to_failed`. The stored analysis
remains queued. Commit `12bef8a6b` removed the `round_analysis_store.fail_non_terminal()` startup
call during Epic 0110. This supports a separate origin for that failure. It still needs an owner
and a decision about the required recovery behavior.

The review also reproduced a transaction visibility defect described below. The evidence supports
successful migration and substantial functional integration, with incomplete concurrency assurance.
It does not support an unqualified claim that all coordinated publication behavior is correct.

## Where the process went wrong

### 1. The migration readiness gate came too late

The [0107 migration milestones](../plans/5-closed/0107-Unified_Pipeline_Data_Lineage.md)
qualified fixtures and staged packages. They explicitly left real activation to 0108. That split
was reasonable, but it lacked a representative persisted-data rehearsal before runtime integration.

The first real M10 inventory found 147 blockers: 78 old proposed-scene formats, 47 calibration
format issues, 20 draft/calibration digest mismatches, and two unresolved calibration references.
Commit `3106de0c2` records the initial findings. Historical parsing work reduced these to three
missing detector revisions; the user then explicitly accepted their loss. This safety decision was
necessary. Discovering most of the format diversity at activation time was avoidable.

Prevention: select examples of every persisted resource kind and schema before implementation.
Rehearse conversion into a disposable target. Require semantic readback, exact dependencies, and
editable draft/review behavior there. Keep the final writer stop and activation short.

### 2. File preservation was treated as sufficient progress toward runtime cutover

M10 preserved draft and review bytes in `.migrated-records` and served old store APIs from
`.migrated-readers`. Selections stored exact pointers while callers still received old scalar IDs.
These steps protected data, but carried the old architecture inside the new store.

M11 then had to convert retained drafts into editable nodes, split virtual scenes, bind review
records, replace calibration state, introduce coordinated transactions, change crop provenance,
convert every processor input, and remove duplicate publication. These were planned outcomes whose
implementation boundaries had not been resolved. Calling the work “delete replaced architecture”
hid its size. See the [M10 reconciliation](0108-M10_Migration_Reconciliation.md) and
[M11 handoff](../plans/5-closed/0108-Horizontal_Lineage_Workspace.md#execution-handoff--2026-11-06).

Git records 13 commits updating the epic during M10, from `3106de0c2` through `0acf2ca6d`,
plus the preceding inventory implementation commit. M11 has 33 epic-updating commits from
`e597b62d4` through `767a966f5`. These are commit counts, not independent attempts or active hours.

Prevention: define one complete replacement path first: UI choice → request → accepted input →
worker read → output publication → review/edit → restart. Require the old store to be unavailable
in that test. Apply the established contract to the other paths. Keep a finite consumer-removal
table with a test and owner for each row.

### 3. Two epics changed the same runtime contracts concurrently

Epic 0110 changed managed job IDs, submission routes, retries, and application composition while
0108 changed lineage and processor contracts in the same checkout. The M11 handoff records nine
API fixture failures. Worker receipts identify job-ID/run-ID confusion, counterfactual route
changes, and observation polling races. A later worker could not collect identity tests because
the shared checkout temporarily lacked `PipelineStageRequestBuilder`.

The accumulated cutover commit `d599af92d` changed 47 files, with 3,323 insertions and 1,083
deletions. Several workers inherited uncommitted work before that checkpoint. This made review,
failure attribution, and rollback more expensive.

Prevention: serialize changes to a shared dependency boundary. Finish or freeze the job submission
contract before converting its lineage consumers. Separate worktrees help isolate incomplete files;
integration still needs a stable shared contract. Unrelated work can continue in parallel. Commit
each green, coherent package before another worker inherits it.

### 4. The loop managed an oversized milestone rather than bounded work packages

The receipts repeatedly used `BLOCKED` for ordinary unfinished implementation. The orchestrator
then spent correction turns asking workers to continue, reached the correction limit, and stopped.
The user had to renew the run. Meanwhile the handoff repeatedly recorded “M11 incomplete” and
changing “latest package” entries. It grew to hundreds of lines with stale next steps and run counts.

The first recorded M11 loop spawned 11 workers: seven at Medium reasoning, then four at High.
The later loop used High workers, including two very long M11 worker histories. The evidence does
not isolate model choice as the cause. It shows that both frequent restarts and long retained
contexts were used against a milestone with no small, stable completion boundary.

Prevention: distinguish a finished package, normal next work, a failed check, and a required external
decision. Give each worker one package with a commit boundary. Reserve correction turns for defects
in that assignment. When two packages expose new prerequisites or fail to reduce the removal table,
pause expansion and replan the remaining work. Keep one current handoff; move detailed history to
a report. Track completed packages as well as milestones.

### 5. Repeated orchestration and validation increased context processing

The two principal M11 orchestrators made 197 and 299 `wait_agent` calls, all with a 60,000 ms
timeout: 496 calls in total. Their final counters record 36,046,707 input tokens, including
35,803,008 cached input tokens, and 33,609 output tokens. Those counters cover the entire two
orchestrator sessions, not only waiting. They exclude worker usage and do not measure subscription
quota consumption. They therefore cannot explain an exact number of five-hour windows.

The earlier 0108 session also accumulated 2,070 tool calls across the epic. Retained replies report
aborted graph validation and scene sweeps because payload revalidation was too expensive. Current
`find_revision()` still enumerates nodes and uses history traversal. This is a concrete scaling
concern, but this review did not measure a latency regression or assign all that cost to 0108.

Prevention: use blocking completion notifications with the longest permitted wait, subject to
active tool instructions. Avoid repeated monitoring. Record the package's check results against
its commit and input digest. Rerun affected checks after changes, then perform the combined gate
once. Use bounded representative data early and a reproducible full migration audit at activation.

### 6. Completion evidence did not match the breadth of the claim

The [M12 report](0108-M12_Verification_and_Closure.md) accurately says the browser regression uses
recorded API fixtures. At closure commit `fc3224e70`, the test intercepted `/api/**`, returned
`copied: true` itself, and supplied a constant review record. This verifies UI behavior. It cannot
establish backend copy decisions, durable review preservation, transaction isolation, or actual
restart persistence. Other backend tests and migration audits supplied separate evidence, but no
single real-backend workflow connected those boundaries.

The transaction tests cover successful publication and recovery after an interrupted first head
update. They omit a concurrent reader during publication. That omission permitted the defect below
despite passing focused tests.

Prevention: retain fast UI fixtures, and add one real-backend browser workflow using disposable
persisted data and deterministic processor stubs. Preserve real storage, serialization, reviews,
and restart. Test live concurrency separately from crash recovery. State the evidence boundary
explicitly in completion receipts.

## Reproduced correctness defect: coordinated transaction visibility

Affected source:
[node recovery](../../backend/src/dokodetector_backend/pipeline_node_store.py#L139) and
[transaction publication](../../backend/src/dokodetector_backend/pipeline_node_transactions.py).
The node-store file last changed in `741ed132f`, during M11.

`recover_transactions()` uses a store-wide `_recovering_transactions` Boolean. A transaction sets
it while publishing its journal. A second thread using that store skips recovery and reads the
heads directly. The public read path does not take the transaction lock before returning them.

A deterministic temporary-storage probe:

1. Create two nodes and prepare one coordinated update of both.
2. Wrap the transaction module's `atomic_replace_json` to pause the writer immediately after the
   first `head.json` update. Keep all actual writes and journal processing real.
3. From another thread, call public `get()` for both nodes on the shared store.
4. Release the writer and verify the transaction finishes.

All three trials returned the new first head and the old second head while the recovery flag was
true. The transaction completed after release. This proves transient mixed visibility. It does not
prove existing user data was corrupted. The production composition shares node-store instances
across services, so shared-instance behavior matters.

Repair needs a defined read/transaction synchronization contract, including same-instance threads
and separate store instances/processes. A thread-local recursion flag alone does not establish
that contract. Add a barrier-based regression for concurrent reads and retain restart/retry tests.

## A smaller workflow for future replacements

Use the existing epic process with these gates:

1. **Readiness:** inventory real resource/schema diversity, map every runtime reader and writer,
   establish baseline failures, and settle shared contracts and transaction semantics.
2. **One complete path:** demonstrate processing, editing, review, copy, and restart with old
   storage unavailable in a disposable store.
3. **Remaining paths:** one bounded package per processor or editor; each removes named consumers,
   passes its checks, and commits before handoff.
4. **Migration rehearsal:** convert a representative snapshot directly into usable canonical
   state; reconcile content, reviews, dependencies, and explicit losses.
5. **Activation:** stop writers, freeze and verify the full snapshot, convert, restart, and run
   the real-backend smoke workflow. Retain recovery evidence.
6. **Removal and closure:** remove the enumerated old paths and run combined functional,
   concurrency, restart, and populated-data checks. Assign every remaining failure an owner.

Each numbered gate can contain several small milestones. A milestone that introduces a transaction
system or changes all processor input contracts should be named and scoped as that implementation.
The final removal milestone should have a known, finite deletion list.

Immediate priorities are the transaction visibility repair and one real-backend persisted workflow.
The startup-recovery failure needs separate triage. More repeated broad audits will add little
confidence until those exact gaps are tested.

## Verification commands and process evidence

Fresh backend checks used `mise exec -- uv run --project backend pytest` with these modules:

- First batch: `test_pipeline_node_store`, `test_pipeline_node_selection_store`,
  `test_pipeline_node_transactions`, `test_pipeline_node_uses`, `test_pipeline_lineage_writer`,
  `test_lineage_migration_import`, and `test_calibration_refinement_service` — 28 pass. The
  additional named `test_app` recovery case fails as described above.
- Second batch: `test_pipeline_lineage`, `test_pipeline_node_edits`, `test_pipeline_node_reviews`,
  `test_lineage_migration_inventory`, `test_lineage_migration_apply`,
  `test_lineage_draft_projection`, `test_visible_card_pipeline_api`,
  `test_observation_pipeline_api`, and `test_visual_identity_pipeline_api` — 84 pass.
- From `web`, Vitest selected `RecordingPipelineWorkspace.test.tsx`,
  `PipelineLineageDrawer.test.tsx`, and `PipelineNodeEventEditor.test.tsx` — 34 pass.
  The supplied `pipelineWorkspaceUrl.test.ts` filter matched no file. No full web or browser suite
  was rerun.

Local process records are under `~/.codex/sessions/2026/11/`. Relevant session IDs:

| Session | Evidence used |
| --- | --- |
| `01a1abc0-2596-71d0-99c6-8add731157be` | Initial epic, M10 inventory and cutover, early M11, expensive validation |
| `01a1b0ea-05e1-78a3-9700-8ade6c1d3499` | Manual handoffs, first loop, worker settings, 197 waits, run stops |
| `01a1b152-c4ca-7e02-acd0-c19a0b0a75ff` | Incomplete selection cutover and failing API fixtures |
| `01a1b164-64cb-72d3-95b1-6e3b9b11c849` | Fixture stabilization and accumulated commit |
| `01a1b1a8-83d3-7972-8468-5c029739079d` | Shared-checkout import/collection blocker |
| `01a1b218-95f4-72c0-bfc4-c6a01f4207cb` | Later loop, 299 waits, M11 acceptance and M12 closure |
| `01a1b219-d40c-7381-9e38-51edee3ad33b` | Review/calibration/store retirement packages |
| `01a1b2a0-689e-7823-b2b8-2772eab9c6e4` | Final runtime conversion and M11 verification |

The earlier memory summary supplied a navigation pointer. Conclusions above use the current
repository, retained session records, and fresh checks rather than the summary's success label.
