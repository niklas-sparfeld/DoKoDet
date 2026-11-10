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
| M1 | Independent history-growth, invalid-metadata, and concurrent-selection checks; local latency qualification | Complete |
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

**State: Complete.** Six independent history families each grew from 10 to 100 entries. For one
recording, list reads stayed at ten open attempts (three root metadata files, one locator, six
selection files), three root metadata files read, one directory visit, and identical response
bytes. A separate concurrent test ran 20 exact-selection updates with 30 list requests and kept
pending transaction status unavailable across all six indicators. M0 corrupt metadata and
selection cases passed again.

The local corpus in the main worktree contains 58 recordings. Its three root metadata files per
recording and all existing exact-selection files total 310 files and 214,150 bytes. The frozen
digest is `834c532851e12f44087044839ed7ca66c9bd2d6606d9181f7939f55d1e762ed8`. Across three
uncontended sessions on one frozen snapshot, fresh-process API medians were 20.485, 20.225, and
20.065 ms; warm API medians were 16.715, 17.171, and 17.089 ms. The corrected browser test waited
for all 58 row links to be visible in the document. Its medians were 331.790, 330.474, and
332.594 ms. Each session used ten fresh API processes, 30 warm requests, and ten fresh Chromium
contexts. See the [M1 local corpus qualification](../../reports/0123-M1_Local_Corpus_Qualification.md)
and its [raw browser samples](../../reports/0123-M1_Local_Corpus_Browser.json).

### M2 — Remove replaced list code and close

Inventory callers of list-proof helpers and the experimental list flag. Remove only unused
list-specific code and tests. Keep aggregate recording-state APIs and shared workspace/history
stores for their current consumers until their owning resource cutover. Reuse M1 evidence when
code is unaffected; rerun affected checks after cleanup. Run web type/lint/API checks and relevant
backend/browser regressions. Close Complete only if M0/M1 and the closure matrix pass. Commit:
scoped removal and closure evidence. Update this decision's active links when moving the epic.

## Execution handoff

M0 and M1 complete. Baseline: 3 milestones, 1 remains; 2 complete. First complete API/browser
workflow: proved in M0 with persisted selection, browser navigation, and backend restart. M1
proved independent history growth, invalid metadata, concurrent selection reads, and sub-second
fresh-process, warm, and browser list medians on the frozen 58-recording local corpus. New
persistent contracts/source writers: zero. Source owners changed for this milestone: the growth
contract tests, local-corpus profile runner, browser visibility test, and existing browser
performance runner. Existing selection files and transaction locator remain the authority. M0's
removed history-growth contract remains replaced by the independent six-family read-boundary check.

Run 2 of 3 authorized milestones: M0 and M1 complete; 1 run slot remains; 0 re-plannings; M0's
correction family remains exhausted at 2/2; M1 corrections 2/2. Correction 1 rejects zero and
negative selection revisions, matching
`PipelineNodeSelectionStore`'s positive-revision rule. Correction 2 restores the valid revision-1
saved-but-unselected case, and tests revision zero and a negative revision on separate content
types. It retains the corrupt selection-file check. Focused backend tests and Ruff pass after this
correction. No scope change. M0's correction allowance is exhausted; its scope review is recorded
above.

M1 evidence: six history families each grew 10x without changing file opens, bytes, directory
visits, or response bytes. Invalid root and selection metadata cases passed. Concurrent list reads
observed only current exact pointers, no selection, or unavailable while the locator was pending.
The 58-recording local corpus passed fresh-process API, warm API, and actual browser list timing in
three sessions. Correction 1/2 replaces the initial browser workspace-navigation timing with a
reproducible visible-row measurement. The browser test asserts all 58 links have visible CSS and
nonzero bounds before timing ends. It records one list request and zero per-recording detail
requests per page. Correction 2/2 found that the intermediate digest `628211...eca57d` used a new
dictionary serialization. Recomputing the original tuple-based digest gives `834c532...762ed8`,
matching the initial M1 digest for the same 310 files and 214,150 bytes. The profile runner now
freezes one metadata and selection snapshot before measurement and verifies the same digest before,
between, and after sessions. All three session records contain that digest. Both corrections reused
capture set 2; capture set 1 was the generated fixture. No scope change or re-planning. M1
corrections 2/2. Next: M2 removes only unused list code, reruns affected checks, and closes. Stop if
cleanup changes an active reader or any closure check fails.

Scope review after M0 correction exhaustion: the real list, navigation, and restart workflow now
works. The failed requirement was local selection metadata validation and preservation of its
saved-but-unselected regression. Both are fixed and reviewed. Keep the existing direct-read
approach; no prerequisite or scope was added. M1 must prove the independent read boundary,
concurrent selection behavior, and local latency; M2 removes only unused list code and closes.
Stop if qualification fails or requires a new authority, writer protocol, cache, or displacement.

The 0120 ledger approach is superseded, not accepted. Its M3 correction history remains exhausted
at 2/2; M9 never started. This materially smaller approach changes the list semantics and removes
all five source-publication adapters. It is not another ledger correction. Its own family gets at
most two corrections under the [execution workflow](../../workflows/epic-execution.md#scope-review).
Stop for a proposed new store, writer protocol, or displaced qualification.
