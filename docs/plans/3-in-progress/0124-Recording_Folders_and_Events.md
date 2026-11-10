# Recording folders and events

- **Status:** In Progress
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
| M4 | Rehearse reviewed alternatives and exact parents for three named recordings in disposable storage | Complete |
| M5 | Roll out verified recordings and qualify representative normal app workflows | Complete |
| M6 | Remove obsolete event runtime paths and complete closure checks | Not started |

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

### M4 replan — reviewed retained-data rehearsal

The 2026-11-10 investigation found 104 event review records on other event revisions of the
activated `cardeventnet-IMG_0662` pilot. Its two selected source revisions have no reviews; those
104 records remain in the old store and are not in its recording folder. The pilot proof did not
establish that the normal folder workflow can browse that review work. The investigation found
108 and 102 event review records on sampled revisions of `cardeventnet-IMG_0648` and
`game-2026-08-20-01-001`, respectively. These are inventory counts, not conversion proof.
The checked-in pilot work contains no reusable conversion adapter. Retained outputs have exact
event-node parents in lineage records. These facts justify a small three-recording rehearsal
before corpus activation. 0129 changes event job history and does not solve this reviewed-data
requirement. Keep it independent. The M3 publication delay needs separate measurement; it is not
a prerequisite or an assumed 0129 fix.

The previous M4 combined discovery, adapter, corpus activation and verification. Split it into the
bounded proof below and M5 rollout. M5 retains the promised qualification checkpoint; M6 removes
replaced paths and completes final closure. This changes the baseline from six to seven milestones:
M0–M3 complete, M4–M6 remain. It does not remove any original acceptance criterion. No broader
activation is authorized by M4.

### M4 assignment — rehearse reviewed alternatives

Observable result: in disposable persistence, convert the exact retained recording and event inputs
for `cardeventnet-IMG_0662`, `cardeventnet-IMG_0648`, and `game-2026-08-20-01-001`. In the normal
browser open a reviewed unselected alternative, inspect its retained decisions, select and edit an
event set, restart, and reopen both the reviewed alternative and a saved output's exact earlier
event parent. Preserve the current pilot and all retained input files. Use recorded media and a
stubbed detector where required. This is a rehearsal, not activation of the three recordings.

Finite owners: a concrete offline conversion adapter under `backend/src/dokodetector_backend`,
`recording_folder_store.py`, `event_set_store.py`, the event review adapter in
`pipeline_node_reviews.py`, and only the event-specific workspace/editor clients required to browse
the converted review and exact parent. Read existing `repository-bundle/v1`, `source-record/v1`,
`pipeline-node/v1`, `pipeline-node-revision/v1`, `pipeline-node-selection/v1`, existing legacy
selection records, and `pipeline-review/v1` through their concrete owners. Read retained output
metadata and lineage only offline to map actual direct parents. Save recording, event and review
resources using their existing contracts. Do not add a runtime store, authority, transaction,
generic resolver, job migration or unrelated format conversion. Never mutate an existing saved
output or event version to make the rehearsal pass.

Freeze input paths and digests, source bytes, selection references, exact event versions, review
records and unfinished work, and named retained outputs with direct event parents. Record recovery
location. Reconcile both selectors from evidence without newest-by-time inference. Map old exact
node/revision/content digests to saved set/version/content digests. Preserve independent item,
coverage and overall decisions with identity, facts and provenance; expose missing or ambiguous
facts explicitly. Compare every in-scope review and version in each named recording, including the
pilot's unselected reviewed revisions. Preserve existing pilot manual edits and selections. Prove
at least one existing retained output's exact earlier event parent after restart without changing
that output. If this needs a new contract or unrelated output conversion, stop and report the exact
failed user action and smallest alternative.

Checks: deterministic replay and conflict rejection; source and exact content digests; compare all
in-scope decisions and unfinished work; generated and reference selection including an absent
selection; exact output parent after selection change; persisted normal-browser review, edit, select
and restart on disposable data; M0–M3 affected regressions including active-job priority, stale
selection and 0123 list growth; affected static, API, web and local Markdown link checks. Record
input snapshot, discrepancies and limitations. One focused adapter, evidence and plan commit.

### M5 assignment — rollout and qualification

Observable result: activate the verified retained recording/event corpus for normal app use, and
qualify reviewed alternatives and direct earlier event parents through the normal browser. Freeze
the finite corpus from existing `data/intake/recordings/*/manifest.json` and its matching event
nodes, selectors and reviews; record every recording with no usable inputs as an explicit exception.
The initial discovery is the current 58 retained bundles; do not assume that each has a usable
selection. Rehearse the entire selected snapshot in disposable storage before activating verified
batches. The activated 0662 pilot, its manual alternatives and current HEAD must remain intact.

M4 proved an offline mapping but the app cannot discover the old parent from a saved output. The
old visible-card output's `coverage.event_revision_id` names its legacy event revision. M4 saved
the old event node/revision and `source_metadata.legacy_revision_id` in each converted event-set's
existing provenance, with the same canonical content digest. Use these existing saved facts for a
recording-local exact match in the visible-card output/inspector path: validate recording, unique
legacy revision identity and content digest against the converted event set; expose an explicit
missing or ambiguous result and never select by time or run history. Open that exact set/version
from the normal output view. Prefer direct event-set refs already present on newer outputs. Do not
mutate any saved output or event version, introduce a new persistent mapping authority, generic
history resolver, or depend on processor-run/lineage records at runtime. Offline lineage may discover
and verify inputs during conversion. If the stated fields cannot establish a unique and trustworthy
match for a saved output, record it as an explicit exception; do not silently claim it is usable.

Finite owners: `event_conversion_rehearsal.py` and a bounded activation entry point; existing
`recording_folder_store.py`, `event_set_store.py`, `event_sets_api.py`, the exact visible-card
revision response and `pipeline_workspace_service.py` where needed to expose its direct parent;
`RecordingWorkspaceInspector.tsx`, `RecordingPipelineWorkspace.tsx`, `RecordingEventSetEditor.tsx`
and their concrete clients for opening the exact parent. Existing recording HEAD and event-set files
remain authorities. Event conversion provenance already records source revision metadata; no new
persistent contract or output format is planned. Inspect the actual output and callers before each
change. Do not convert other resource formats, rewrite the scheduler, or migrate jobs. If a new
contract or unrelated owner becomes necessary, stop and present the failed action and dependency.

Freeze the named source manifests, media digests, event node versions, both selectors, reviews,
unfinished work and actual direct parents of retained outputs; retain a durable recovery snapshot.
Rehearse replay/conflict checks, compare every exact content digest, decision and unfinished item,
and preserve all immutable original inputs. Resolve selector disagreements from evidence, never by
newest time. Activate only after verifying the live sources still match their frozen snapshots;
keep pre-existing roots and user edits. Record successes, exception identities and recovery steps.
No absent or ambiguous parent becomes a usable result by inference.

Required checks: on disposable real persisted data use normal browser to open the pre-M3 visible-card
output `8bfa825d-94af-5ac6-877d-a1381e662d65@d9c461ee-c7f9-5a2c-be60-36da3ea9a169`, navigate from
it to the converted exact event parent, change event selection, restart, reopen the output and parent,
and compare digests with output bytes unchanged. Disable processor-run and lineage reads for this
parent lookup; test missing and duplicate provenance fail visibly. Qualify generated, corrected and
reviewed examples through normal browser open/edit/select/restart, and the M3 real-provider pilot
without a new detector run if its saved result still opens. Verify replay, conflicts, exact media,
reviews and source snapshots, durable restart, M0–M4 regression boundaries, active-job priority,
stale selection, 0123 list-growth, affected backend/static/generated API/web/browser/link checks.
Record exact corpus, activated batches, exceptions, observed behavior and limits. One focused M5
implementation, activation evidence, plan and board commit. M6 retains runtime removal and final
closure. No changes to 0129 or unrelated publication performance work.

### M5 replan 2 — folder-backed visual-identity input

The M0–M4 regression run found a failing M2 workflow. The event-set visible-card run completed, but
the next visual-identity request returned 422: `VisualIdentityRequestBuilder.build` compared the
selected visible-card revision with `VisualIdentityRecordingAccess.accepted_source`, which still
read only the old bundle store. The visible-card revision used the accepted source from the
recording folder, so the source values differed. This blocked the exact event-set → visible-card →
visual-identity → observation workflow already required by M2.

Bounded replan: add `visual_identity_recording_access.py`, its service wiring in
`visual_identity_pipeline_service.py` and `pipeline_composition.py`, to M5's finite owners. Read the
existing `RecordingFolderStore` for recording-root recordings; keep the old bundle path for legacy
recordings. Resolve the same source bytes, digest, duration and path already owned by the recording
root. Add no storage or transaction contract. The existing persisted M2 observation test is the
required check. This owner is necessary because M2's accepted observation inputs include an exact
visual-identity revision. It does not add another outcome or convert another resource type.

A stale round-analysis list test also wrote the retired event-node selector for a recording-folder
recording. Keep its original check for exact event selection without loading the saved event set by
writing a missing exact pointer in `recording.json` HEAD. Keep the node-transaction pending test for
other pipeline selections; the recording-owned event HEAD remains readable during that transaction.

### M6 assignment — remove replaced paths and close

Freeze exact removal owners from the pilot and rollout receipts before assignment. Remove duplicate
event publication, selection and content reads now served by recording/event resources. Keep
unrelated resource authorities and operational job adapters. Archived old files may remain as
recovery evidence without a runtime compatibility path. Complete the original closure checks,
including real browser producer/editor workflow, exact earlier input, restart, old event-node reads
and writes disabled, crash and concurrency boundaries, active-job priority, list growth, static,
API, web and link checks, real detector evidence and recovery. Close only when all pass.

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

Current run: requested 1 milestone, completed 1, remaining 0. M5 is complete. M5 family re-plans
2/5, run re-plans 2/10, corrections 0/2. The current baseline is seven: M0–M5 complete and M6
remains. The browser opened the pre-M3 output's exact converted parent after selection change and
backend restart with processor-run and lineage reads blocked. The saved M3 provider result also
opened after restart without a detector run. The 58-root corpus snapshot and full disposable
rehearsal passed. Activation added 283 versions to 58 recording roots and changed no HEAD. Recovery
data is retained. Post-activation checks matched all frozen source digests, reviews, selectors,
event revisions and saved output bytes. Seven recordings have no event nodes; 203 outputs have no
saved parent facts and remain unavailable. The required persisted M2 observation regression also
passed after the bounded visual-identity adapter began reading the existing recording-root
authority. No new persistent contract or authority was added. See the M5 report for exact evidence
and limits. M6 owns replaced runtime path removal and final closure; 0129 remains independent.

See [M5 rollout and qualification report](../../reports/0124-M5_Rollout_Qualification.md) for
implemented changes, checks, and evidence limits. The following handoff is the historical M4
handoff and preserves its run counts.

Current run: requested 1 milestone, completed 1, remaining 0. M4 family re-plans 1/5; run
re-plans 1/10; M4 corrections 1/2. Original baseline four milestones; user-selected baseline six;
current baseline seven. M0–M4 are complete; M5–M6 remain. M4 separates retained-data rehearsal from
rollout; M5 keeps qualification and M6 retains removal and closure. The existing recording and
event stores remain the authorities. One concrete offline converter was added because no reusable
pilot converter existed. It adds no persistent contract. The first pilot workflow passed in M3;
M4 now proves its previously unselected reviewed versions through the normal app. 0129 and the
separate publication performance investigation remain independent. No activation occurred.

Original outcome: import a recording, create/select/edit alternative event sets, and reopen them
from a simple recording folder. Non-goals remain other resource conversions, scheduler work, and
cross-store transactions. Final closure check is the normal app workflow, retained rollout and removal of replaced event paths in M6.

Original baseline: four milestones. Original M3 stopped before implementation; no retained data
changed. The user-selected baseline on 2026-11-10 had six milestones. The reviewed-data replan
increased it to seven: M0–M4 are now complete, M5–M6 remain. The original loop ended at its scope
gate after three accepted milestones. First recording workflow was proved in M0 and event workflow
in M1. M2 proved review and exact consumer inputs. M3 proved normal-app use on the retained pilot,
including bounded activation and the configured real detector smoke. M4 rehearsed the retained
reviewed alternatives and exact parents for three recordings without activation. M5 rolls out and
qualifies; M6 removes replaced paths and completes closure.

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
qualification. No transaction, authority, or resolver was added. M4 rehearsed reviewed retained
alternatives; M5 owns rollout and qualification.

Final checks: focused backend event-set, recording-folder, visible-card and list-growth tests passed
(57 tests); Ruff check and format passed; recording-folder E2E passed (3 tests); `npm run check`
passed (244 tests, type, lint, format and generated API); and `npm run build` passed. The build keeps
the existing 500 kB chunk-size warning.

See [the M3 pilot report](../../reports/0124-M3_Pilot_Workflow.md) for the provider setup, exact
job data, sample location, and acceptance gap.

### M4 rehearsal report

Detailed input, conversion, browser, and check evidence is in the
[M4 rehearsal report](../../reports/0124-M4_Reviewed_Alternative_Rehearsal.md).

M4 used the bounded offline adapter in
`backend/src/dokodetector_backend/event_conversion_rehearsal.py`. It reads only event nodes, their
exact revisions and reviews, and both event selectors for the three named recordings. The
disposable output uses the existing recording and event-set stores. No persistent contract,
transaction, or authority was added. The adapter preserves review time in the existing
`event-review/v1` field and keeps the original policy and evidence fields. It reads exact review
records for unpublished source revisions because the normal user-facing review listing only
returns published revisions.

Correction 1/2 adds an explicit offline map for pre-M3 output
`6e2f3f6f-b5c3-5bb0-8056-47a34bf54327`: its retained output node/revision and content digest map
through the direct old event revision to the converted exact event-set/version/content digest. The
first M4 browser check used only M3 output `7111edd7-9f72-4fdc-9c10-a90d94db172f`, whose parent was
already folder-backed; that evidence was insufficient for the legacy-output requirement. The
correction freezes and compares the pre-M3 output revision, request, and state, and the normal
browser reopened its mapped exact parent after changing selection and restarting the backend. The
existing UI opens the exact mapped version from the event-set list; it does not add an automatic
output-to-parent link. No runtime resolver, output format conversion, or new authority was added.

The frozen-input manifest is
`/var/folders/gv/yr_91p3x2_vctbq99586hjm80000gn/T/0124-m4-final-39juxq3w/frozen-input-manifest.json`
with SHA-256 `a806ca35d95f2424adfa9c14a063f0d33aeadaff2dcc41af25b9ef32b014f03f`. It records 14
source event nodes, 314 review records, both selectors for each recording, the source bundles and
the retained output parent. All 373 compared input files matched their frozen copies. Source video
digests are `2372698c009dedd0a3c19ffbecf55d6eb2fa2768c01b787604f747f46a035be7` for 0662,
`6ae4bba4c7901ec016d9684661c01ac5fa18932f3da1e79502b43ba2ff2fb33c` for 0648, and
`2464d0e65547b2db31ea5ca49f4d57cefcb999e34cbacec7e7cca8ee9d549faa` for the game recording.
All conversion and browser writes stayed in the disposable root. The retained folders, selectors,
old event nodes, reviews, and saved output stayed unchanged.

The replay converted 17 event versions: six for 0662, five for 0648, and six for the game
recording. Every canonical event digest matched. It preserved 104, 108, and 102 reviews, including
identity, decision, timestamp, item digest, policy, evidence, and source provenance. It compared
pending item IDs per exact version. The legacy and node selectors agreed by exact node/revision
and legacy revision metadata. The 0648 and game roots use those exact choices. The 0662 rehearsal
preserved the pilot's existing HEAD while recording the old selector mapping. Replay did not
overwrite versions or reviews.

The normal browser opened reviewed, unselected versions on all three recordings and showed 52,
54, and 51 decisions for the chosen exact versions. On disposable 0662 data, it edited and saved an
alternative, selected it, restarted the backend, and reopened the reviewed alternative and the
M3 saved output's exact event parent. Output `7111edd7-9f72-4fdc-9c10-a90d94db172f` still references
`manual-efadbf34-2c3c-4fa6-888f-2b9b46128ffe@1`, with content digest
`a3c284533668d7b316f65142718262424f62769e85bd19d0f67e177fb6b84c78`. Its output content digest
is `905ecbb65fc9137a15187f9bd0465e8f7923d120bbaff1b7840411250c582e23`. No saved output was
rewritten. M4 authorizes no activation; M5 must define and rehearse the rollout batch.

Correction 1/2 also reopened the exact parent of pre-M3 run
`6e2f3f6f-b5c3-5bb0-8056-47a34bf54327`; see the report for its direct lineage, digests, copy hashes,
and browser evidence. Its original output bytes and run records were unchanged.

Checks: the named backend regressions passed (53 tests); Ruff check and format passed;
`npm run check` passed (244 tests, type, lint, format and generated API); the recording-folder
Playwright suite passed (3 tests); the retained-data browser rehearsal passed for all three
recordings through restart. Next: M5 rollout and qualification.

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
digest retention. M4 rehearsed retained data; M5 owns rollout and qualification; M6 owns runtime
removal and closure.
