# Recording folders and events

- **Status:** Ready
- **Depends on:** None. Epic 0123 is closed, which stabilizes the list API before its source layout changes.
- **Outcome:** Use the normal app to open a retained recording, inspect/edit/select events, run visible-card detection, and reopen the saved result from simple recording resources.
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
| M3 | Normal app workflow works on one retained recording: open media, edit/select events, run detection, reopen result | Complete |
| M4 | Extend the proved workflow to the retained recording/event corpus through rehearsed conversion | Not started |
| M5 | Remove obsolete event runtime paths and qualify the usable app on activated data | Not started |

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

### Scope review after M2 correction exhaustion

M2 used both correction turns. Its independent review and exact-input workflows now pass. The
corrections removed event-node history reads for folder recordings and kept active runs ahead of
saved-data state. Both changes stayed within the named M2 owners and added no prerequisite or
storage contract. Disposition for M2: keep the approach. M3 is paused at its scope gate because
retained lineage still depends on exact event-node revisions.

Read-only retained-data evidence: the main worktree has 58 source bundles, 1,006 node manifests,
234 event nodes, and 58 exact node event selections. The older pipeline selector also has 58 event
selections. Both selectors have valid targets. Where both select a completed reference, 46 event
contents match; the other 12 have no completed choice. The `.lineage-runs` directory has 599
`pipeline-lineage-run/v1` records. Of these, 281 input entries reference event nodes across the 234
event nodes. They include succeeded and failed runs. Example:
`data/operations/pipeline-nodes/.lineage-runs/e8731b9b-74f1-525c-abde-b1a585724629.json` records
an event node/revision input for `cardeventnet-IMG_0662`.

### User-selected scope decision — 2026-11-10

The user requested a replan after distinguishing jobs from data provenance. Preserve exact direct
parents and producer facts on each retained output. Do not preserve every historical execution as
a domain resource. The 281 lineage input entries are discovery evidence, not 281 independently
required migration targets. Failed runs without retained outputs do not create data ancestry.

Git history supplies additional change and recovery evidence. The user reports that data is tracked
in Git. This plan does not claim that all media, ignored paths, or recovery inputs have been verified
in Git. Verify the named activation inputs and their recovery location. Runtime provenance must be
readable from checked-out saved resources without traversing Git history or execution records.

Disposition: simplify using output-owned provenance. Replace the oversized unfinished M3 with three
bounded milestones, M3–M5. The original baseline was four milestones; M0–M2 stay accepted. The new
baseline is six, with three remaining. This is an explicitly requested replan, not an extension of
the old loop. Qualification moves explicitly from original M3 to new M5 as part of this decision.
No implementation run is authorized by the planning request. Preserve M0/M1/M2 correction history;
M3 has no implementation attempts. Count this revision as M3-family replan 1 and cumulative replan
2 for the previous run history. Do not reset old correction allowances.

Separate [0129](../1-backlog/0129-Execution_History_in_Jobs.md) owns execution-history consolidation
and retention. It is not a dependency of event cutover. Existing job/processor adapters can continue
to execute work during 0124. No historical-run resolver or migration of all lineage attempts is
required for 0124 closure. Do not delete operational records in this epic.

### Usability-first scope decision — 2026-11-10

The user clarified the overriding goals: simplify the domain model and use the app again. The
preceding replan put infrastructure ahead of that outcome. It is superseded by this assignment
sequence. M0–M2 remain accepted at their recorded boundaries; their isolated editor/API tests do
not prove that the normal app works on retained recordings. Do not report the whole app as usable
from those tests.

Keep three remaining milestones, but make M3 deliver the complete user workflow on a real retained
recording. M4 extends that proof to the retained corpus; M5 removes replaced paths and closes.
Qualification starts with M3's pilot, rather than waiting until the final milestone. General
execution-history independence and job-store consolidation are deferred to 0129. The output-owned
provenance model remains the direction; only facts needed to read and use saved outputs belong in
this dependency chain. Do not require universal provenance hardening before restoring the app.

The smaller approach uses the existing recording/event stores and Job Manager. Connect them through
the normal workspace, convert one retained recording with recovery evidence, and remove the
superseded event path for that recording. New authority, transaction, generic resolver, or scheduler
work is not planned. For every proposed prerequisite, identify the exact failed user action and
why a local change to an existing owner cannot fix it. Stop after two attempts without progress
and perform scope review; do not expand into another infrastructure program.

### M3 assignment — restore the normal app workflow

Observable result: from the normal recordings list, open `cardeventnet-IMG_0662`, play its video,
inspect existing events, save and select a corrected alternative, launch visible-card detection
using that exact alternative, inspect the saved detector result, restart the backend, and reopen
both the result and its exact event input. Browse the unselected event alternative. The list,
workspace, editor and launch controls must agree on the selection. No hand-authored API requests,
manual JSON edits, special test-only page, or shell launch can substitute for these user actions.
The existing editor route is allowed when linked from and returned to the normal workspace.

Pilot evidence: the main worktree has this recording's `repository-bundle/v1` and `source-record/v1`
metadata at `data/intake/recordings/cardeventnet-IMG_0662/`. This check confirms source identity, not
media health or complete runtime compatibility. Start implementation by reproducing the workflow
failure and inspecting that recording's media, events, reviews and exact downstream dependencies.
Freeze the pilot input paths/digests and recovery location before conversion. If another recording
is needed, record the concrete input defect and choose one named existing replacement; do not
convert the corpus merely to find a runnable example.

Finite owners: `recording_folder_store.py`, `event_set_store.py`, `event_sets_api.py`,
`recordings_api.py`, `repository_bundle_api.py`, `event_pipeline_service.py` source/output adapters,
`pipeline_stage_api.py` event selection, `pipeline_workspace_service.py`,
`pipeline_workspace_api.py`, `visible_card_pipeline_service.py`, `visible_card_jobs.py`,
`pipeline_lineage_writer.py` output publication, and the concrete workspace/editor/visible-card
launch components and clients already changed by M1/M2. A concrete offline pilot conversion adapter
may stage existing recording/event/review contracts; no new runtime store or transaction contract.
Inspect shared `pipeline_data.py` validation only for a demonstrated pilot input mismatch.

Implementation boundary: adapt these owners to use one recording root and explicit event selection.
Save direct event-parent identity/version/digest on the detector output and the exact base on an
event edit; copy necessary processor/model/configuration facts with the output. Use existing fields
where possible. A job/run link is diagnostic. Do not rebuild all historical execution ancestry or
require all run stores to disappear. For the selected saved result, parent choice must come from
output metadata rather than whichever run record happens to exist. Historical facts that cannot
be recovered remain explicit. Preserve the pilot's source bytes, human reviews and alternatives,
and original saved inputs. Rehearse conversion in disposable storage, verify usability, then
activate only the verified pilot with recovery evidence so the user's normal local app can use it.
Do not leave the only successful workflow in a test server.

Required checks: one automated normal-browser workflow against a real persisted backend on a
representative disposable pilot copy, including edit/select/launch/result/restart/reopen and exact
parent inspection after later selection changes. A deterministic detector stub proves plumbing;
it does not prove a real provider works. Also perform one bounded local app smoke check on the
activated pilot with an already configured available detector. Record provider, result and limit;
if the provider is unavailable, report that exact user-facing gap and do not claim the whole
workflow is ready. No training, new model acquisition or phone is required. Verify media playback,
durable content, source digests and retained review facts. Retain M0–M2 regression boundaries,
active-job priority, stale-selection conflict, and 0123 list-growth checks. Run affected static,
API, web and link checks. One focused implementation/pilot-evidence/plan commit.

The receipt must give the normal app route, recording, working steps, provider used and any
remaining limitation. Record simplification evidence: which duplicate event authority/read/write
path was removed from the pilot and which concrete resource now owns it. New file counts or passing
test counts alone are not success. Stop before a second storage/transaction contract, unrelated
format conversion, or a new prerequisite without a failing user action. Do not postpone this
workflow proof into M4.

### M4 assignment — extend the working flow to retained recordings

Observable result: the normal app lists and opens the retained recording/event corpus through the
same path proved in M3. This is a rollout of a working flow, not an architecture discovery phase.
Specify exact schemas and finite affected paths after the pilot passes, before assignment.

Owners: M3's concrete converter, recording/event stores and their source/selection adapters.
Read-only discovery covers retained bundle manifests, event alternatives and exact revisions,
both event selectors, independent completed/unfinished review records, and retained outputs with
direct event parents. Execution records are optional offline sources for unique missing parent or
producer facts; their 281 input entries are not migration targets by default. Do not convert other
resource formats. Use the actual retained-output dependencies to set the conversion boundary.

Freeze named inputs and recovery evidence. Rehearse conversion in disposable storage; compare source
bytes, usable event content, exact required versions, selection, reviews and unfinished work.
Verify saved outputs resolve their direct event parents after restart. Resolve selector disagreement
from evidence, never by newest timestamp. Missing dependencies remain explicit and visible. Do not
silently discard human work or turn a missing exact input into a usable result. Activate verified
batches only after checking the frozen sources still match; keep the working pilot available.

Checks: replay/conflict-safe conversion, content and review comparisons, normal browser open/edit/
select/reopen on representative generated, corrected and reviewed recordings, exact earlier input
read after a later edit, and M3's workflow regressions. Record all corpus exceptions and which
actually prevent use. Stop before another resource conversion or generic historical resolver.
One focused conversion/evidence/plan commit. Job-history migration and deletion stay deferred.

### M5 assignment — remove replaced paths and close

Observable result: the app keeps the M3/M4 workflows working on activated data, and the replaced
event runtime path is removed. No new storage or transaction contract. Freeze exact removal owners
from the pilot and rollout receipts before assignment; use the original finite event owners and
concrete clients, not a broad repository cleanup.

Remove duplicate event publication, selection and content reads now served by recording/event
resources. Keep unrelated resource authorities and operational job adapters. Archived old files
may remain as recovery/history evidence without a runtime compatibility path. Do not migrate or
remove jobs just to make the architecture look complete. Describe the final ownership and actual
removed runtime paths in the report; a new abstraction layered over all old ones is not closure.

Qualify source import, normal event production and human editing under the same content contract,
two alternatives, selection/review, detector launch and saved result, exact older input after edit,
backend restart and unselected browse through the normal browser. Old event-node reads/writes must
be disabled for this workflow. Test interrupted version save, interrupted HEAD replacement, stale
version, separate concurrent readers/writers, active-job status and 0123 list growth. Run affected
backend/web/static/generated/link checks against named code/data revisions. Verify the activated
pilot still works with the available real detector and retain recovery evidence. Close 0124 only
when these checks pass; move the epic, repair links, and commit implementation and evidence together.

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
cross-store transactions. Final closure check is the normal app workflow, retained rollout and removal of replaced event paths in M5.

Original baseline: four milestones. Original M3 stopped before implementation; no retained data
changed. User-selected baseline on 2026-11-10: six milestones, M0–M2 complete, M3–M5 not started.
The original loop ended at its scope gate after three accepted milestones. This request authorizes
planning only; a later implementation command selects the next run and its limit. First recording
workflow was proved in M0 and event workflow in M1. M2 proves review and exact consumer inputs.
M3 proves normal-app use on the retained pilot, including bounded activation and the configured real
detector smoke. M4 rolls out that working flow; M5 completes removal and qualification.

Correction history: M0 1/2; M1 2/2 and one replan; M2 2/2 and zero replans. Those exhausted
allowances remain exhausted. Original M3 family: zero implementation attempts, replan 2/5. Previous
run history: replan 3/10 including the provenance and usability scope revisions. New assignments do not renew
M1/M2 correction turns. Last scope decision: restore the normal app workflow first; deliver simplification through that
workflow. Output-owned provenance replaces blanket historical-run migration only where the working
flow needs it. Universal history independence and job consolidation are deferred to 0129; it is not
a prerequisite. The preceding provenance-first M3 assignment is superseded, not complete.
Stop before expanding to another resource conversion, scheduler replacement, or generic resolver.

M3 current run: requested 1 milestone, completed 1, remaining 0. M3 implementation attempts: 2;
M3 family re-plans remain 2/5; current-run re-plans are 0/10 and cumulative run history remains
3/10. No new source owners, storage contracts, or transaction contracts were added. The first
implementation attempt found one local defect in the
named `visible_card_pipeline_service.py` owner: folder-backed detector launch still read the retired
recording catalog and its old bundle video path. The service now resolves the accepted media and
digest from the existing recording root through `EventSetStore.recordings`. A normal-route browser
test with a deterministic detector passed edit, generated selection, launch, saved result, changed
HEAD, restart, and exact old input reopen. It also browsed the unselected set and retained review
facts. The browser test uses disposable synthetic media; it does not prove the retained pilot's
provider.

Pilot rehearsal and activation: `cardeventnet-IMG_0662` was rehearsed in disposable storage, then
published under `data/recordings/cardeventnet-IMG_0662`. Source SHA-256 is
`2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7`; the generated and reference
event digests match the frozen source revisions (`66f3770998399b646af198791a64420d8bb8212effc9bf97379948003c985bad`
and `00ce1f56caf862db76601d6e82cd36587d56f2c9fd23de208364559b910832f5`). The existing reviews
for those exact revisions number zero. Both old selector files and node revisions remain unchanged.
Frozen inputs and rollback instructions are in
`data/operations-recovery/0124-m3-20261110/snapshot.json`.

The live normal-app smoke played the activated recording, edited and selected
`manual-efadbf34-2c3c-4fa6-888f-2b9b46128ffe@1`, and browsed the unselected
`retained-generated@1`. After installing only the already declared `inference` dependency group,
the configured local provider `local-rfdetr-fine-frame` v8 on MPS processed all 50 event frames.
Job `7111edd7-9f72-4fdc-9c10-a90d94db172f` froze event digest
`a3c284533668d7b316f65142718262424f62769e85bd19d0f67e177fb6b84c78` and source video digest
`2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7`. Its 1,177,157-byte output
revision digest is `905ecbb65fc9137a15187f9bd0465e8f7923d120bbaff1b7840411250c582e23`. The normal
app opened this exact output and showed 50 outcomes. Publication took about eight minutes after
launch, including 7 minutes 18 seconds after the processor state was complete. The job then reached
`succeeded` and the backend answered again; see the pilot report for the read-only sample.

A direct selection of unedited `retained-generated@1` first returned HTTP 422 because the editor
sent the full set list entry instead of the exact `{set_id, version}` reference. The editor now
normalizes the reference on open and on selection. Its persisted-browser regression asserts HTTP
200 and the updated choice. The normal app also selected this unedited set with HTTP 200.

After the provider job succeeded, the normal app opened the saved result and displayed its 50 event
outcomes. With no active jobs, I restarted the backend using its existing command and configuration.
After restart, the normal app reopened that exact result and the exact unselected parent
`manual-efadbf34-2c3c-4fa6-888f-2b9b46128ffe@1`. The parent still has digest
`a3c284533668d7b316f65142718262424f62769e85bd19d0f67e177fb6b84c78`; the new generated selection
remained `retained-generated@1`. M3's normal-app pilot workflow passed. The configured local provider
smoke is limited to this retained recording and MPS provider. Publication took about eight minutes,
then the saved result was durable and inspectable after restart. This does not claim production
qualification. No transaction, authority, or resolver was added. M4 rolls out the proved flow; M5
still owns removal and qualification.

Final checks: focused backend event-set, recording-folder, visible-card and list-growth tests passed
(57 tests); Ruff check and format passed; recording-folder E2E passed (3 tests); `npm run check`
passed (244 tests, type, lint, format and generated API); and `npm run build` passed. The build keeps
the existing 500 kB chunk-size warning.

See [the M3 pilot report](../../reports/0124-M3_Pilot_Workflow.md) for the provider setup, exact
job data, sample location, and acceptance gap.

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
digest retention. M4 owns retained rehearsal; M5 owns activation and qualification under the user-selected replan.
