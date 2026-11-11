# 0124 M6 runtime removal

## Result

M6 removed event-node publication and runtime consumption from the converted recording workflow.
Event processing writes immutable event sets and completes the existing processor run with no node
revision IDs. Lineage records the exact saved event-set artifact and digest. Recording HEAD and the
event-set store remain the authorities. Visible-card and visual-identity outputs remain generic
pipeline nodes.

The normal browser workflow passed with event-node reads disabled. It edits and selects event sets,
runs visible-card detection from the exact selected event-set reference, and reopens the saved output
and parent after backend restart. Event comparison remains available through exact event-set
references and digests. No parent links were inferred.

## Runtime reader and writer audit

| Path | M6 result | Replacement and evidence |
| --- | --- | --- |
| `event_pipeline_service.py` | Removed duplicate event-node publication and node-based event selection. Event runs complete with no node revision IDs. | Existing `EventSetStore`; event run and job lifecycle regressions, exact lineage artifact regression, and persisted browser workflow. |
| `visible_card_pipeline_service.py` | Requires an exact selected event-set reference. Removed event-node execution fallback and legacy event-node fields from accepted-use records. | Existing HEAD and event-set APIs; backend event-set input tests and normal browser detection/reopen. |
| `observation_pipeline_service.py` | Requires an exact event-set reference and reads only visible-card and identity node inputs. | Backend observation regressions forbid event-node reads and verify exact saved event-set lineage. |
| `pipeline_workspace_service.py`, workspace/stage APIs | Hide event-node history and selectors. Expose event-set comparison choices from the existing store. | Recording folder workspace API and browser comparison workflow. |
| `pipeline_node_selection_store.py`, `pipeline_node_edit_api.py` | Reject event-node selection writes, revision reads, edits, and review routes. | API returns not-found for legacy event-node editor/read routes; selection-store regression rejects event selection writes. |
| `pipeline_comparison_api.py`, `pipeline_comparison_service.py`, web comparison client/view | Compare event run output and reference by exact event-set ID, version, and digest. Require the existing manual/corrected review state and preserve coverage decisions. | Exact set digest rejection and restart response checks; visible-card and identity comparison checks remain unchanged. |
| `ProcessorRunState`, run store and lineage writer | Event-detection runs may complete without node revisions. Other processors retain their output validation. Lineage outputs identify the existing event-set artifact and digest. | Event-only completion, non-event output validation, restart, and lineage regressions. |

The audit found no active workflow caller for `EventReferenceHandler` or the event parsing branches
in `PipelineRevisionStore`. The reference handler is used by offline lineage-draft migration; the
revision store is used by offline migration inventory and legacy recovery readers. Those paths
remain for conversion and recovery evidence. `PipelineNodeEdits` and `PipelineNodeReviews` remain
generic services for non-event types; their event HTTP routes now reject event nodes. The web
`PipelineNodeEventEditor` had no production import or route consumer and is deleted.

## Regression mapping

- Removed the old standalone event-node editor and its UI tests. The recording-folder workspace
  tests cover alternative listing, event edits, selection, reopen, and exact event-set references.
  The backend node edit API tests now prove event node reads, edits, and reviews return not-found;
  generic visible-card node behavior remains covered.
- Adapted visible-card and observation fixtures to folder-backed event-set inputs. Their tests retain
  exact source and digest validation, restart, retry, item outcomes, and processor lifecycle
  boundaries. Event nodes are forbidden during converted workflow reads.
- Added event-set-only processor completion and exact artifact lineage regressions. Non-event
  processor output validation and publication remain covered.
- Adapted event comparison request and response tests to exact event-set references. Invalid digests
  fail. A restarted backend returns the same exact comparison response. Other resource comparison
  tests still use node revision inputs.
- Kept the 0123 no-history-growth and concurrent-read test in
  `test_recording_catalog_growth_contract.py`.
- Kept the prior event-set interrupted-save, recording HEAD conflict, stale-version, and
  concurrent-reader/writer tests. M4 conversion/replay and M5 frozen activation/recovery evidence
  remain unchanged.

## Checks

Checks ran against the M6 changeset based on `0a5a0ceb`:

- Backend: 11 focused test files passed: pipeline/run and lineage, event-set workspace and
  selection, node edit and selection, event comparison and vision comparison, visible-card,
  observation, event-set store, recording-folder store, and 0123 list growth.
- Operations comparison contract: 5 tests passed.
- Ruff check and format check passed for changed backend and operations owners and tests.
- `web/npm run check` passed: 46 Vitest files, 242 tests, TypeScript, ESLint, Prettier, generated
  OpenAPI verification, and API type generation.
- `web/npx playwright test --config playwright.recording-folder.config.ts` passed: 5 browser tests,
  including event editing/detection/reopen and the frozen M5 pre-M3 exact-parent digest proof after
  selection change and restart.
- Event comparison passed backend API exact-reference and restart checks plus the workspace
  component request/response test. This preserves the active comparison consumer using event sets.
- M5 frozen payload verification passed in the browser test. The output file, output content, and
  parent content digests matched the committed fixture in
  `backend/tests/fixtures/0124-m5/fixture.json`. The browser blocked processor-run and lineage
  routes for that proof.
- `git diff --check` and the changed Markdown local-link check passed.

## Limits

M5 added 283 immutable versions to 58 recording roots without changing HEAD. Recovery data and
source artifacts remain. Seven recordings have no event nodes; 203 saved outputs have no parent
facts and remain unavailable. M6 did not infer parent links, delete retained data, claim user review,
or qualify another resource type.
