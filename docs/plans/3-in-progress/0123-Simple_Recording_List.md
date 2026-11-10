# Simple recording list

- **Status:** In Progress
- **Depends on:** None. Existing recording and exact-selection metadata is sufficient.
- **Outcome:** Open `/recordings` from recording metadata and explicit selected-data indicators
  without reading content, process history, or validating referenced resources.
- **Origin:** The user's 2026-11-10 storage discussion and [storage decision](../../RecordingDataStorage.md).

## Problem, success, and non-goals

`recordings_api.list_recordings()` calls `RoundAnalysisService.recording_catalog()` and
`PipelineWorkspaceService.get_statuses()`. They scan packages, analyses, node revisions, lineage,
and processor runs. Even `RecordingBundleStore.list_metadata()` recursively enumerates bundle
files and reads proposal records. None of this is needed to display recording identity and exact
current selection metadata.

The user selected authoritative domain data and direct reads over preserving aggregated process
status. Intentionally change the list contract: identity, display name, date, session, thumbnail
URL, and generated/reference indicators for existing selected content. States are selected, no
explicit selection, and unavailable metadata. An unselected saved result is not missing data; the
list only says that it is unselected. Remove list progress states, historical counts, latest
analysis, and analysis readiness. Keep their existing explicit detail/job operations usable.

The current web list renders pipeline progress. It does not render analysis/package counts or
readiness. `RecordingAnalysisSummary` currently derives its type from the list's latest-analysis
field; move that alias to the detail response when removing the field. Do not break the detail
contract or change processor execution semantics.

Non-goals: recording-folder migration, recording HEAD adoption, producer changes, generic resource
code, catalog/projection/ledger/outbox storage, scheduler or startup optimization, and bounded
writes. Do not preserve the old list contract through a compatibility flag or side endpoint.

## Smallest solution and finite owners

Use direct reads of `manifest.json`, `source-record.json`, and `initial-task-enrollment.json` in
each accepted recording directory. Parse only root metadata required by the row. Do not use bundle
validation or file metadata enumeration as a list-read prerequisite. Intake publication keeps its
full validation. Existing missing/corrupt root metadata produces an explicit error row.

Read at most six exact `.pipeline-node-selections/<recording-id>/<type>.json` files for events,
visible cards, virtual scenes, card-scene proposals, visual identities, and table observations.
Keep virtual scenes and card-scene proposals distinct if both exist; never substitute one as an
implicit selection of the other. Parse document identity, pointer fields, and revision shape only.
Do not call `get_exact()`, `_parse_exact()`, or `_validate_exact_pointer()`; they can read referenced
content. Factor a narrow pure metadata parser only if needed by this concrete owner.

Read the existing coordinated-transaction locator once. A pending/invalid locator makes selection
indicators unavailable, not the recording list empty. Do not recover source writes, block on an
active writer, or promise a coherent multi-type selection snapshot on the list. Atomic selection
file reads suffice for the declared indicators. Add no new persistent contract.

Source owners: backend `recordings_api.py`, `recording_bundle_store.py`,
`pipeline_node_selection_store.py`, `pipeline_node_transactions.py` (existing locator shape only),
and `config.py` (remove list-proof flag only after consumer check). Web owners: `recordings.tsx`,
`api/recordingContracts.ts`, generated `api/openapi.ts`, and their direct test fixtures. The old
workspace and analysis readers remain for explicit consumers; this epic stops calling them.

## Closure check

The production route and actual browser list show real persisted metadata and selected-data
indicators, navigate to a recording, survive backend restart, and surface corrupt metadata. No
list request reads video/proposal/resource content, runs ffprobe, traverses dependencies/history,
enumerates package/analysis/run stores, or performs a write. No N+1 status requests replace that
work in the browser. Lazy thumbnail work is measured separately.

With recording count/current metadata fixed, independently multiply each history family by ten.
File opens, decoded bytes, directory visits, and response size remain fixed. The read budget is at
most three root and six selection files per recording plus one locator per request. Freeze a
reasonable metadata size limit; oversized input is unavailable, not read without a bound.
On the frozen local corpus, fresh-process and warm request medians must each be below one second
across three uncontended sessions after startup. Record revision, corpus digest, recording count,
file/byte counters, and browser timing. Do not claim a cold disk-cache measurement. If timing fails,
inspect this finite path; do not introduce a cache or writer-publication protocol.

## Milestones

| Milestone | Observable result and commit boundary | State |
| --- | --- | --- |
| M0 | Production metadata-only route and web rows; one persisted select/list/open/restart workflow | Complete |
| M1 | Independent history-growth, invalid-metadata, and concurrent-selection checks; local latency qualification | Not started |
| M2 | Remove unused list-only proof/reconstruction code, complete affected checks, and close | Not started |

### M0 — Deliver the simple list

**State: Complete.** The list route now reads at most the manifest, source record, and initial
enrollment for each recording, six exact-selection files, and the transaction locator once. It
does not call the recording catalog, history stores, or workspace status readers. It reports
invalid root metadata as an unavailable row and malformed selection metadata as unavailable.
Selections show pointer identity and shape only. A pointer can refer to absent content and still
appears as selected; the row does not verify that resource. Selection rows require revision 1 or
greater; zero and negative revisions are unavailable. An empty locator is accepted, while a
pending or invalid locator makes all six indicators unavailable. Root metadata reads stop at 1 MiB
per file; selection and locator reads stop at 64 KiB per file. Oversized files are unavailable.

The web row shows the source filename, date, session, thumbnail, and six selected-data states. It
does not show pipeline progress. `RecordingAnalysisSummary` now comes from the detail response.
Backend API tests prove selection through the existing selection route, missing referenced content,
unselected saved content, distinct virtual-scene and card-scene proposal choices, corrupt root and
selection metadata (including zero and negative revisions), pending transaction behavior, and restart.
The real browser workflow reads the
persisted selection, opens the recording, and confirms the workspace after backend restart.

Checks passed: focused recording, bundle-store, and exact-selection tests; Ruff; web recording
tests; TypeScript, ESLint, Prettier, and generated API verification; and the real Playwright
workflow. The former list-growth test encoded the removed process-history contract. M0 replaced
that check with the new exact row schema. Independent history-family growth and latency evidence
remain for M1. No new persistent contract or source writer was added.

Implement only the finite reader and web owners above. Use the existing selection API to create a
real selected events reference in disposable storage. Read the actual route, load the real web
list, navigate, restart, and repeat. Guard forbidden readers so the test fails if any are called.
Include an empty recording, an unselected saved result, distinct generated/reference choices,
uninitialized experimental HEAD, and a corrupt root/selection row. Keep displayed selection status
truthful and separate from content verification. Use existing folder IDs and source names; do not
invent a game/round merely for a row label.

Checks: targeted recording API/store/selection tests, web recording-client and row tests, one real
persisted browser workflow, affected Ruff/format/type checks, and generated API verification.
Commit: route, concrete metadata reads, row contract, generated API, tests, evidence, and plan/board
updates together. This is implementation, not a measurement-only milestone.

### M1 — Prove the read boundary and latency

Owners: the new M0 tests, `backend/tests/test_recording_catalog_growth_contract.py`, list browser
tests, and a narrow extension of an existing profiling script if needed. Independently grow node
versions, lineage, runs, analyses, packages, and proposal files. Include completed and pending
transaction metadata without triggering reconciliation. Prove atomic concurrent selection reads
separately from restart; no aggregate snapshot promise is added. Measure actual local corpus list
requests and the real browser. Use at most two candidate capture sets. Fix only defects in M0.

Checks: the finite closure matrix above and affected static checks. Commit: regression coverage,
bounded fixes, frozen qualification evidence, and progress update. Qualification stays here; do not
move it after extra prerequisite work. Record an unmet target if this approach fails.

### M2 — Remove replaced list code and close

Inventory callers of list-proof helpers and the experimental list flag. Remove only unused
list-specific code and tests. Keep aggregate recording-state APIs and shared workspace/history
stores for their current consumers until their owning resource cutover. Reuse M1 evidence when
code is unaffected; rerun affected checks after cleanup. Run web type/lint/API checks and relevant
backend/browser regressions. Close Complete only if M0/M1 and the closure matrix pass. Commit:
scoped removal and closure evidence. Update this decision's active links when moving the epic.

## Execution handoff

M0 complete. Baseline: 3 milestones, 2 remain; 1 complete. First complete API/browser workflow:
proved in M0 with persisted selection, browser navigation, and backend restart. Qualification:
M1, not started. New persistent contracts/source writers: zero. Source owners changed: backend
`recordings_api.py`; web `recordings.tsx`, `recordingContracts.ts`, generated `openapi.ts`, and
direct tests. Existing selection files and transaction locator remain the authority. The old
history-growth fixture was replaced because it asserted the list contract that M0 removed; the
independent history growth and latency qualification remain scheduled for M1.

Run 1 of 3 authorized milestones: M0 complete; 2 run slots remain; 0 re-plannings; 1 correction of
2 allowed. The reviewer found that zero and negative selection revisions were accepted. The narrow
fix now marks them unavailable, matching `PipelineNodeSelectionStore`'s positive-revision rule.
Focused backend tests and Ruff pass after this correction. No scope change. No performance or broad
history-growth claim is made. Next: M1's independent history-growth, invalid-metadata,
concurrent-selection, and local latency checks. Stop
if those checks require a new authority, writer protocol, cache, or move of the qualification target.

The 0120 ledger approach is superseded, not accepted. Its M3 correction history remains exhausted
at 2/2; M9 never started. This materially smaller approach changes the list semantics and removes
all five source-publication adapters. It is not another ledger correction. Its own family gets at
most two corrections under the [execution workflow](../../workflows/epic-execution.md#scope-review).
Stop for a proposed new store, writer protocol, or displaced qualification.
