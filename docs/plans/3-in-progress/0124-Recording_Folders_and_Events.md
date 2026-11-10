# Recording folders and events

- **Status:** In Progress
- **Depends on:** None. Epic 0123 is closed, which stabilizes the list API before its source layout changes.
- **Outcome:** Import a recording, create/select/edit alternative event sets, and reopen them from a simple recording folder.
- **Origin:** [Recording data storage](../../RecordingDataStorage.md).

## Problem and success

Source bundles, event nodes, review work, and selections currently have separate roots. A recording
and its events must become directly readable domain resources. Preserve original source bytes,
human event corrections, independent reviews, generated/reference choices, exact historical inputs,
without modifying any saved input version. Do not infer selection from newest-by-time.

Use `data/recordings/<recording-id>/recording.json` and the event-set layout in the storage decision.
The root owns recording/source facts and an inline HEAD with an optimistic recording version.
Saved event-set versions contain typed event files and exact provenance. Keep small review records
beside the event set. Share field/path conventions, not a base model or generic store.

First compare this with leaving event nodes in place: that would not deliver the requested visible
recording folder or remove event-envelope/process coupling. Faster listing alone does not require
this conversion; 0123 has already delivered it independently.

Non-goals: detection/scene/classification/observation format conversion, scheduler work, model
changes, universal review/provenance infrastructure, and performance work on unrelated APIs.
Untouched types retain their existing authority. Convert event selection readers/writers together;
do not keep dual event authority or rebuild the aggregate recording-state snapshot framework.

## Finite source owners

- Intake/media: `config.py`, `recording_bundle_store.py`, `repository_bundle_storage.py`,
  `repository_bundle_api.py`, `recordings_api.py`, and `operator_corpus_import.py` where
  it publishes accepted recordings. Existing bundle transport can remain at the import boundary.
- Events: `event_pipeline_service.py`, `pipeline_api.py`, the event branches in
  `pipeline_node_edits.py`, `pipeline_node_edit_api.py`, `pipeline_node_reviews.py`,
  `pipeline_node_selection_store.py`, and `pipeline_lineage_writer.py`.
- Consumers: event reads in `visible_card_pipeline_service.py`, `observation_pipeline_service.py`,
  and `pipeline_workspace_service.py`; event/source references in `round_analysis_service.py`.
- Web: event selection/editor portions of `RecordingPipelineWorkspace.tsx`,
  `useRecordingPipelineData.ts`, `useRecordingPipelineSelection.ts`, `recordings.tsx`, and their
  concrete API clients. Add typed recording/event files; do not replace the whole workspace.

Paths above are under backend `src/dokodetector_backend` and web `src/pipeline` unless qualified.
Confirm exact call sites and representative schemas before each assignment. This is a finite
boundary, not permission to convert other resource types through these shared files.

## Closure check

In disposable persistence, import source media; save two event alternatives; select one; edit and
review it; preserve the exact earlier input of a stubbed detector; reopen after restart; and browse
the unselected alternative. Demonstrate one normal event producer and one human editor using the
same content contract. Run the actual browser workflow with old event-node reads disabled.

Rehearse one-time retained conversion before activation. Freeze named bundle/event/review inputs,
map old exact references, compare source digests, usable event content, coverage, review decisions,
unfinished work, and selection. Keep recovery data. Verify interrupted version save, interrupted
HEAD replacement, stale expected version, and separate overlapping reader/writer behavior. No
referenced saved version may change. Keep 0123's no-history-growth list regression passing.

## Milestones

| Milestone | Observable result and commit boundary | State |
| --- | --- | --- |
| M0 | Concrete recording-root contract; import/list/media-open/restart from one new recording folder | Complete |
| M1 | Concrete event-set contract; real API and browser save/select/edit/reopen of two alternatives under one event-selection authority | Complete |
| M2 | Review and the named exact-input consumers use event resources | Complete |
| M3 | Retained-data rehearsal, default cutover, event-only old-path removal, and qualification | Not started |

### Next assignment after dependency closure

M0 owns only the intake/media and list owners above plus one concrete recording store and its
tests. Existing bundle transport is input, not a second mutable authority. Specify root fields,
source-media paths, the root write/version boundary, and finite retained intake schemas before
assignment. Introduce at most this one persistent contract; event-set persistence belongs to M1.
Prove import/list/media-open through actual services/APIs and restart with the old recording catalog
disabled. Update the glossary's target recording HEAD meaning explicitly when root selection starts
in M1. Do not rewrite closed plans.

Required checks: focused intake/recording/media tests, real persisted API/browser list navigation,
root replacement/conflict tests, affected static/API checks, and 0123 list-growth protection.
Commit: root implementation, finite adapters, tests, evidence, and plan/board updates.

M1's event layout and exact editor call sites follow. Specify M2/M3 after the event workflow
passes. Each assignment must name the result, exact source owners, checks, and one focused commit.
M2 must not defer review or downstream exact-input failures to M3 cleanup.

## M1 event-set contract and workflow

Store each saved version under
`event-sets/<set-id>/versions/<version>/event-set.json`. Store each member at
`events/<event-id>/event.json`. The set document uses `event-set/v1` and records recording, set,
and version identity; ordered event membership and relative paths; exact source and provenance;
creation time; and origin. Each event file uses `event/v1` and contains the existing typed event
identity, type, start/end times, and model scores when present. The event set keeps the existing
`event-data/v1` fields when an API caller opens it. A version is complete before its staged directory
is renamed into place. Existing versions cannot be replaced. An edit saves another version; it does
not change the earlier files.

`recording.json` owns `head.events.generated` and `head.events.reference`. Each is null or an exact
`set_id` and `version` reference. Selection validates the referenced files, checks the expected
recording version, and atomically replaces the root under its existing recording-local lock. Saving
does not select the version. For recording-folder recordings, the processor saves each completed
output as an unselected event-set alternative. The stage API, workspace, inspector, and recording
list read event choices from `recording.json` HEAD; event selection writes update only that HEAD.
These root-backed paths do not read or write `.pipeline-node-selections/events.json`. They do not
select the newest output by time. The dedicated browser route reads and writes only event-set
resources. Review files and named downstream exact-input consumers stay in M2. Legacy non-folder
pipeline records keep their existing path until the M3 event-only cutover.

M1 verification: `test_event_set_store.py` covers separate alternatives, immutable versions,
versioned edits, exact open, selection, stale root conflicts, and persisted API reopen. The pipeline
API test proves a processor output is saved as an unselected alternative and exact selection updates
HEAD. Root-backed stage, workspace, and list tests prove those readers use the same references and
ignore legacy event selection state. The workspace response marks event selection authority as
`recording-head` or `pipeline-node`; the inspector hides the node selector only for `recording-head`.
The recording-folder Playwright test saves two alternatives,
selects both choices, edits version 2, recreates the backend against the same files, then reopens and
checks both alternatives and their HEAD choices. The test forbids legacy event selection reads and
writes and checks that the browser makes no legacy pipeline or node requests. The M0 store/restart
and 0123 list-growth regressions pass; the list test now expects seven file opens because it no
longer opens the retired event-selection file. API generation, web tests/build, Ruff, and browser
checks pass.

### M1 correction 1: one event-selection authority

The first M1 submission proved the dedicated editor, but inspection found that the pipeline stage
API and readers still used `.pipeline-node-selections/events.json` while the event-set editor used
`recording.json`. Node/revision references cannot name an event-set/version. This leaves two live
selection authorities and makes the pipeline and list disagree with the editor.

Bounded replan: move only the planned event producer adapter and event selection adapters from M2
into M1. Owners are `event_pipeline_service.py`, the event selection routes in
`pipeline_stage_api.py`, event selection assembly in `pipeline_workspace_service.py`, and event
selection summaries in `recordings_api.py`, plus the event-stage inspector and selector client.
Processor outputs become unselected event-set alternatives. Explicit selection reads and writes
only `recording.json` HEAD. No automatic newest-by-time selection is allowed. Keep review layout
and conversion, and named visible-card, observation, and round-analysis exact-input consumers in
M2. Do not convert other resources.

Proof: API tests use a real processor stub to create an unselected event-set alternative and verify
that stage selection, workspace choices, and list summaries use exact references from recording
HEAD. The browser saves two manual alternatives, selects exact references, edits the first version,
recreates the backend against the same persisted files, reopens both versions, and confirms both
HEAD choices and event content. The backend forbids legacy event selection reads and writes during
this workflow, and the browser confirms it makes no legacy pipeline or node requests. Required
regressions remain M0 restart and 0123 list growth. Stop and report if producer publication needs a
second persistent contract/transaction or if downstream exact-input conversion is required before
the event editor can satisfy this proof.

### M1 correction 2: preserve the legacy event selector

The first selector fix hid the event-node selector when the event-set reference field existed.
However, the workspace response includes that nullable field for all recordings, including retained
non-folder recordings whose event selection still uses pipeline-node references until M3. The fix
adds the explicit `event_selection_authority` field to workspace stages. Root-backed event stages report
`recording-head`, including an invalid or empty HEAD; legacy event stages report `pipeline-node`.
The inspector hides the node selector only for `recording-head` and keeps it for `pipeline-node`.

Coverage: API response asserts both root-backed and legacy authority; the workspace UI test asserts
that a legacy `pipeline-node` event stage keeps its selector and that a `recording-head` stage hides
it. Re-run the previous M1 event workflow, restart, stale/conflict, and M0/0123 regressions. This is
a response discriminator and UI condition only; it adds no persistent contract or selection writer.

### M2 assignment after the first workflow

#### Scope review after M1 correction exhaustion

M1 used both correction turns. The first complete recording-folder event workflow now passes,
including processor publication, exact selection, edit, restart, and a legacy-read/write guard.
The remaining M2 work is independently planned review persistence and exact-input consumption.
The observed M1 defects were local authority mismatch and a nullable response discriminator; the
bounded fixes removed them without a new prerequisite or storage contract. Disposition: keep the
approach and proceed with the separately planned M2 work. M2 has its own bounded implementation
scope; it does not reopen M1 correction allowance.

Proof: save and reopen independent item, coverage, and overall reviews beside an immutable
event-set version. The event editor saves and reloads reviews after backend restart. The visible-card
UI uses the selected event-set reference and fetches its content digest before launch. The
observation workspace lists compatible event-set plus visible-card and visual-identity inputs with
the exact digest. API workflows launch both consumers while event-node reads are disabled; exact
set/version/digest references remain in requests and lineage. Round analysis consumes the resulting
observation with its exact event-set source. M0/M1 and 0123 list-growth regressions, generated API,
web tests/build, browser workflow, and Ruff checks pass.

Observable result: event review and the named exact-input consumers read and write the same event-set
files and root HEAD. Disable their old event-node reads and selection writes in the integration
workflow. Keep the existing behavior for all other resource types.

Source owners: `event_set_store.py` and `event_sets_api.py` for exact review records and endpoints;
`RecordingEventSetEditor.tsx` for review save and reopen; event branches in
`pipeline_workspace_service.py`; the visible-card launch UI and event client for selected-set digest
lookup; event reads in `visible_card_pipeline_service.py`, `observation_pipeline_service.py`, and
`round_analysis_service.py`; and their finite request/job adapters.

Contract changes: carry `input_event_set_ref` (`set_id`, `version`, `content_sha256`) through the
existing `ProcessorRunRequest`, lineage artifact inputs, and observation source. Observation
assembly keeps the two node references for visible cards and visual identities. These changes are
required because the current visible-card and observation requests name events only by pipeline-node
revision, and a recording-folder event set is not a pipeline node. The existing observation source
also requires three pipeline revision IDs, so it now records the exact event-set reference and the
two node revision IDs. Do not convert other node types, the scheduler, or general lineage/review
infrastructure. Do not introduce a generic review store.

Required checks: API and editor save/select/restart tests; independent review persistence and reopen;
visible-card UI launch from selected event set; observation compatible-input selection; exact event
inputs for visible-card, observation, and round-analysis reads; an integration test that forbids
legacy event-node reads and selection writes; affected generated API and web checks; and the M0/M1
plus 0123 list-growth regressions. Commit the finite adapter conversion, tests, layout, and plan
update together. Specify M3 retained-data rehearsal and qualification after M2 passes.

### M2 correction 1: skip event-node history on folder-backed workspaces

The first M2 implementation resolved folder event authority after building pipeline-node revision
history. A folder-backed workspace therefore still enumerated legacy event-node histories. Resolve
selection authority first, then exclude event nodes from workspace history for recording-folder
recordings. Keep their event-run summaries and state available from processor-run records and root
event sets. Retain the node-backed path for non-folder recordings.

Proof: the event-set visible-card and observation workflows guard event-node history during the
workspace fetch and guard event-node revision reads through both named consumers. The persisted
observation source contains the full selected set ID, version, and digest plus exactly the visible
card and identity revision IDs before round analysis starts. The legacy node-selection workspace
tests and 0123 list-growth regression still pass. This correction stays within the M2 workspace
owner and adds no contract or prerequisite.

### M2 correction 2: keep active runs visible

The first correction retained event-set data state after removing event nodes from workspace
history. Its state override could replace `active-run` with `data-available` when a selected event
set already existed. Keep active and running states ahead of the saved-data state. Regression
coverage selects an existing event set, changes its processor-run projection to running,
and verifies that workspace reports `active-run`; the same test verifies `data-available` after the
run completes.

## M0 recording-root contract

`Settings.recordings_root` resolves to `data/recordings/`. With `DOKO_STORAGE_ROOT`, it resolves
to `<storage-root>/data/recordings/`. Each folder has `recording.json`, `source/`, and
`proposal-inputs/`.

`recording.json` uses `recording/v1`. It has an optimistic integer `version`, recording, source,
video, and session IDs, UTC `received_at`, the validated `source-record/v1` facts in `source`, the
validated `task-enrollment/v1` document in `task_enrollment`, and a `media` object with safe
`source/<original-filename>` path, SHA-256, byte length, media type, and filename. `media_facts` is
null when the accepted intake has no measured facts. It also has `proposal_generator_runs`, with
each `proposal-generator-run/v1` ID, saved path, digest, and length, and an initially empty `head`.
The `repository-bundle/v1` manifest is transport input. Its validated proposal inputs are copied
to `proposal-inputs/`; the bundle is not retained as a second recording authority.

The store stages a complete folder under `data/recordings/` and renames it into place. A duplicate
import is accepted only when its source, task enrollment, media digest, and proposal inputs match.
Root replacement holds a recording-local file lock, checks the expected version, rejects changes
to source facts, writes and syncs a temporary JSON file, then atomically replaces `recording.json`.
Source media bytes stay under `source/`. The list reads this root and exact existing selection
files; it does not call the old recording catalog.

M0 evidence: `test_recording_folder_store.py` covers root publication, source/intake facts, version
replacement, stale-version conflict, persisted list/media API reads after app restart, and exact
source bytes. `test_operator_corpus_import.py` verifies import without changing the operator source.
`test_recording_catalog_growth_contract.py` retains the 0123 history-growth and concurrent-read
regressions. A backend test forbids the old recording metadata readers while it opens detail and
workspace APIs. The recording-folder Playwright proof opens the recording from the list, verifies
loaded workspace and accepted-video content after reload, then opens playable media in the browser.
It uses a disposable generated video. Checks passed with Python focused tests and Ruff, web build,
and the recording-folder Playwright test. A broader `test_app.py` run also reproduced the known unrelated
`test_factory_converts_interrupted_round_analysis_to_failed` failure. The round-analysis lifecycle
owns that follow-up; it does not block M0.

## Execution handoff

Original outcome: import a recording, create/select/edit alternative event sets, and reopen them
from a simple recording folder. Non-goals remain other resource conversions, scheduler work, and
cross-store transactions. Final closure check remains the disposable retained-data rehearsal and
event-only old-path cutover in M3.

Baseline: 4 milestones; M0, M1, and M2 are complete; 1 remains. M0 proves the recording-folder
import/list/media-open/restart workflow, including root-backed detail and workspace reads. M1 proves
save/select/edit/reopen for two alternatives, with processor output, stage selection, workspace
choices, and list summaries all using exact event-set references from recording HEAD. M2 proves
independent review persistence and normal exact-input launch for visible-card detection and
observation assembly; round analysis uses the exact observation derived from that event set. The
browser test recreates the backend against the same persisted files and forbids legacy event-selection
reads and writes. Qualification remains in M3. The run limit is 4 milestones; 3 are complete and 1
remains. M0 used 0 replans and 1
correction of 2; M1 used 1 replan and 2 corrections of 2; the run used 1 replan. The bounded replan
transferred only the event producer and event selection adapters from M2 to M1. No new storage or
transaction contract was added. M2 introduced one event-review storage contract and evolved the
existing request, lineage, and observation source contracts. M3 owns retained-data rehearsal and
qualification. Stop if M3 needs another resource conversion, a cross-store transaction, or a second
event-selection authority. M2 used 2 corrections of 2 and 0 replans; the run replan count remains 1.

M2 contract detail: store `event-review/v1` under
`event-sets/<set-id>/reviews/<review-id>.json`. Each immutable record identifies `set_id`,
`version`, the digest of canonical `event-data/v1` content, `kind` (`item`, `coverage`, or
`overall`), `question`, `decision` (null only for coverage), `reviewer`, `evidence`, and review
time. Item records also identify `item_id` and the event content digest; coverage records identify
their scope. Reviews are siblings of saved versions so unfinished and completed reviews remain
independent of later edits. M2 evolved the existing persisted `ProcessorRunRequest` and lineage input
fields to carry the exact event-set/version/content digest for event inputs. It kept existing node
references for other inputs. The existing observation source contract now also carries that exact
event-set reference and the two actual node revision IDs. This is required because visible-card and
observation consumers previously required event node references; no second store or transaction was
added.

M1 first submission commit: `7238a483`. M1 corrections 2/2: correction 1 unified root-backed event
selection across producer, stage API, workspace, and list; correction 2 made the workspace authority
explicit so legacy event-node selectors remain available until M3. M1 re-plans: 1/5; run re-plans:
1/10.
Checks passed: event-set, pipeline, recording-folder, list-growth, visible-card, and observation
backend tests (61 tests); Ruff check/format; `npm run verify:api`; `npm run typecheck`, `npm run
lint`, `npm run format`; `npm test -- --run` (244 tests); `npm run build`; and
`npx playwright test --config playwright.recording-folder.config.ts` (2 tests). The backend workflow
reads the event set selected from workspace HEAD, disables event-node reads, and confirms exact
digest retention. M3 remains the retained-data rehearsal and qualification milestone.
