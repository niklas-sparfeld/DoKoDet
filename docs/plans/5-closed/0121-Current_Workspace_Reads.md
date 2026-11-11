# Current workspace reads

- **Status:** Closed
- **Closure reason:** Superseded
- **Depends on:** Completed exact-read and history foundations from closed 0117. No implementation
  dependency on the new catalog index. Schedule after 0120 to keep performance measurements isolated.
- **Outcome:** Open the current workspace and a selected stage without enumerating retained
  history. Keep explicit historical browsing and independent review switching usable.
- **Origin:** [0117 exit decision](../../reports/0117-Supersession_and_Exit.md).

## Supersession — 2026-11-10

The [storage decision](../../RecordingDataStorage.md) replaces this node/history-oriented workspace
plan with concrete recording resources. [0124](../5-closed/0124-Recording_Folders_and_Events.md)
through [0128](../4-blocked/0128-Recording_Table_Observations.md) own their explicit current reads,
editing, historical alternatives, and consumer cutovers. No M0–M4 implementation was started in
0121. Do not run this plan in parallel with those conversions. Closing as Superseded does not
remove code or retained human work. The sections below preserve the original plan.

## Boundary

Use existing exact per-content selections as the current selection authority. Keep generated,
completed-reference and independent review identities distinct. Split current stage summaries from
explicit historical option/run/lineage pages. Reuse 0117's exact node reads and history paging where
their contracts fit. Do not migrate all processor inputs or output publication to recording HEAD.
Normal processing continues to use its existing exact launch requests and explicit selections.

The aggregate recording HEAD API and experimental working editor have not been adopted by the
current workspace. Audit actual consumers and persisted snapshots before removal. Do not erase
human work or silently replace an existing selection. If active human state depends on an
experimental route, retain that exact access until a tested explicit replacement exists.

## Milestones

| Milestone | Observable result and commit boundary | Status |
| --- | --- | --- |
| M0 | Current-stage API from exact selections and bounded stage metadata | Not started |
| M1 | Explicit history/options APIs with stable pages | Not started |
| M2 | Web loads current state first and selected content on demand | Not started |
| M3 | Retained workflow rehearsal, cutover and unused-path removal | Not started |
| M4 | Workspace qualification and closure | Not started |

## M0 — Deliver a current-stage API

Inventory existing selection readers/writers and schema versions, default/no-selection behavior,
workspace consumers and actual recording-state API consumers. Specify explicit empty/stale/error
states; do not guess newest-by-time when selection is absent. Read exact selected revisions and
their bounded dependency closure. Put historical option discovery outside this route. Use compact
stage metadata; do not parse unrelated stages or recreate lineage graphs for the initial response.
Any missing metadata must have an explicit bounded source adapter, not a first-use scan/cache.
If that requires a new persistent contract beyond the existing sources, stop and revise this plan
before implementation. Prove one real API/service workflow with old discovery disabled.

Checks: independent reviews, generated/reference separation, exact missing/corrupt dependencies,
empty/stale state, concurrent selection/edit, restart and 10x history growth. Commit: API contract,
bounded implementation, consumer/retained-state audit and evidence.

## M1 — Deliver explicit historical options

Reuse the supported 0117 snapshot/revision/lineage pages and add only metadata needed by actual
workspace option selectors. No generic candidate collection or all-history request. Preserve exact
deep links, stable traversal and recording isolation. Checks: complete paged traversal, concurrent
publication, expired/tampered cursor, historical exact reads and backend restart. Commit: finite
API adapter set, types and tests. Do not change current selection when browsing.

## M2 — Convert the web workspace

Load current summaries first, exact stage content when opened, and history when requested. Keep
selection/edit commands on their existing authority and concurrency contracts. Preserve independent
review switching, copy-on-edit, autosave, browser reload and historical links. Checks: frontend
regressions and one real-backend browser workflow with disposable persistence for current state,
history, edit/save, selection conflict, independent reviews and restart. Commit: web cutover and
generated API changes. No processor orchestration change.

## M3 — Rehearse and remove replaced runtime paths

On frozen disposable retained storage, disable workspace history reconstruction and verify current
state, stage content, all retained human decisions, history, edit/save, processor start and restart.
Confirm exact identities/digests and dependencies. No selection conversion should be needed; if
the audit finds one, specify and rehearse it before activation instead of inventing selections.
Remove replaced workspace reconstruction and unused experimental recording-state wiring/contracts
identified by M0. Preserve persisted resources and exact historical access; no off-HEAD deletion.
Remove disabled job-page leftovers only after confirming no active consumer. Recheck the frozen
manifest before runtime activation and verify restart and recovery. Commit: cutover/removal,
consumer inventory, retained-data evidence and tests.

## M4 — Qualify and close

Use 0117 M0's hard fixture and uncontended three-session method. Target hard current-workspace
cold/warm medians at most 16 seconds and workspace first-use at most 3.6 seconds. Require zero
implicit history traversal and no read/parser growth under 10x history with selected content fixed.
Initial summary improvement cannot hide old reconstruction in normal stage open. Report initial
summary, stage content, explicit history, catalog and startup-to-useful separately. Run at most two
candidate capture sets. Reuse unaffected checks; run affected backend/web/API/static and real
persisted-browser checks. Close Complete only when workflow, structural and latency gates pass.
Commit: qualification and closure. Startup optimization and unrelated defects need separate epics.

## Execution handoff

Planning only. Delivery is deferred; no worker loop or migration is authorized by this plan.
Next when selected: M0. Use the exit decision's scope-stop rules; do not revive 0117 M9–M16.
