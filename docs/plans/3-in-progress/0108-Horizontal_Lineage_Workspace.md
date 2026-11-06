# Horizontal lineage workspace

## Plan status

- **Summary:** Replace competing data selectors with a horizontal lineage drawer beneath the
  processing steps. Integrate unified data nodes, migrate local data, and delete replaced flows.
- **Status:** In Progress
- **Depends on:** [Epic 0107](../5-closed/0107-Unified_Pipeline_Data_Lineage.md), including tested
  migration tools and provenance/review contracts.
- **Outcome:** M0–M10 are complete; M11 is in progress and M12 is not started. The workspace
  exposes exact graph data,
  preserves validated lineage URLs, and has aligned step and data rows. The horizontal drawer
  selects exact revisions and shows copy and processor sources with collapsed revision history.
  Shared node edit, copy, and restore transactions are available through the workspace API.
  Processor input and trigger UX remains later work.

## Agreed layout

The processing-step navigation is one expanding component with two persistent rows:

1. Events, Visible cards, Virtual scenes, Visual identities, Table observations, Round analysis.
2. The current lineage's data-set name, exact revision, and compact status beneath each step.

Expanding the component reveals a left-to-right lineage graph directly beneath these rows. Keep
steps and their data nodes in aligned columns. Show copies and alternative runs as branches. It is
an extension of navigation, not a separate vertical tree, inspector selector, or detached dialog.

```text
Events          Visible cards    Virtual scenes    Identities       Observations    Analysis
Timing r4       Detector r1      Scene A r7        Identity r3      Assembly r1     Analysis 123
--------------------------------------------------------------------------------------------
First pass
  : copy
Timing -------- Detector -------- Scene A --------- Identity ------- Assembly ------ Analysis 123
                                    : copy
                                  Scene B
Threshold ----- Alternative
```

The sketch is a layout example, not a single-parent storage contract. Observation and analysis
details expose every exact source. Distinguish copy relationships from processing relationships.
Do not imply creation or review authority through column position or connecting lines.

Use restrained condensed nodes: meaningful name, revision, saved date, human/tool contribution,
and relevant review/use status. Reveal exact IDs, sources, coverage, history, and actor details on
selection. Never label mixed content as wholly human-authored or wholly reviewed.

[Epic 0109 — Working area interface unification](../4-blocked/0109-Working_Area_Interface_Unification.md)
owns the subsequent shared still-frame surface, crop placement, and removal of central controls
and descriptions. This epic can complete with integrated existing renderers. It retains ownership
of lineage navigation, separate Virtual scenes, and the runtime cutover.

## Selection and copy behavior

- Selecting a node changes inspection only. Preserve selection in URLs and browser history so
  reload, back/forward, and deep links restore the same lineage and exact revision.
- Switching steps preserves the lineage. Each step has a clear empty state when that branch has no
  result. Do not fall back to an unrelated latest, default generated, or maintained result.
- A source can have several children. Keep the chosen descendant path explicit; a new empty branch
  must not borrow another branch's results. For an initial recording entry without a saved choice,
  use a deterministic documented default. Never substitute for an invalid explicit selection.
- Autosaves stay in node history. They do not create extra graph nodes. Historical inspection must
  remain visibly different from editing current work.
- Opening an editor does not copy. The first committed content change after downstream use
  automatically creates a copy and selects it. Do not ask for confirmation. Explain the new name,
  source, and reason with a visible notice and a route to the original.
- Preserve frame, time, and item position where exact correspondence permits. If the item no longer
  exists, explain the change rather than silently selecting another item. Avoid duplicate copies on
  autosave retry, navigation, or reload. Use the same interaction for explicit and automatic copies.
- Browsing does not change processor-input defaults, maintained references, or training eligibility.
- Handle branch growth by collapsing unrelated history while retaining the selected path and a
  way to reveal alternatives. Never hide a node's additional sources. Keep ordinary graph browsing
  keyboard accessible. Narrow layouts must retain selection and source information without tiny
  labels or clipped controls.

## Scope and cleanup

Integrate the 0107 contracts with existing local processor services, run records, and review tools.
Give virtual scenes their own inspection/editing step. Keep visible cards, piles, ignore regions,
calibration validation, and derived geometry distinct.

Remove the following after equivalent behavior is available:

| Existing mechanism | Replacement |
| --- | --- |
| Generated/Reviewed top-bar toggle and view type | One selected node/revision with independent metadata |
| Displayed revision dropdown | Drawer selection and node history |
| Visible-card review dropdown and special maintained option | Independent nodes in the graph |
| Start review solely to create editable content | Common editing and copy-on-first-change |
| Privileged maintained draft and separate review lifecycle | Node working state and revision-bound review decisions |
| Overall completion as a separate reviewed content format | Overall review decision about exact content and coverage |
| Visible-region/proposed-scene navigation inside one step | Separate Visible cards and Virtual scenes steps |
| Silent generated/reviewed selection fallback | Explicit branch-preserving empty/error states |
| Competing current-data facts in local toolbars | Persistent navigation row and selected-node details |
| Separate generated/reference load and render paths | Content-specific editors with common node access |
| Old view/review/result route dimensions | Coherent lineage identity with historical revision context |
| Legacy review adapters and old active storage | Verified migration and one canonical runtime model |

Delete dead handlers, props, selectors, CSS, API models, endpoints, generated client types, and tests
that require the retired architecture. Do not keep permanent compatibility URLs or dual writes.
Update active documentation and glossary usage. Closed epics remain immutable historical records.

Preserve processor input and trigger controls for later UX work. Audit the persistent "Default
generated revision" and selected-completed-reference pointers before removing them: they have
consumers beyond display. Retire display-only default behavior now; retain necessary explicit
execution choices without allowing drawer navigation to mutate them. This is not permission to
design a new input picker or automatic source-refresh workflow.

Keep comparison of exact revisions, processor failures/progress/configuration, immutable run
history, review negatives and coverage, exact frame/calibration checks, concurrency protection,
and the Timeline Rail. Comparison pair controls serve a separate purpose from primary browsing.

Out of scope: new processor launch or input-selection UX, actionable processing buttons in empty
tabs, automatic cascading reruns, partial execution, automatic rebase of changed human content,
iOS UI redesign, model changes, training, and new evaluation campaigns. The later explicit refresh
workflow must use 0107 review-applicability services; this epic does not add a new refresh button.

## Milestones

Each milestone is one implementation phase. Commit each completed milestone to main, update the
epic and board, and report every milestone. Foundation services may remain unconnected until the
coordinated cutover; temporary old paths have a named removal owner in M11, not an indefinite life.

### M0 — Integrate lineage projection and URL selection — Complete

Expose the exact graph to the workspace. Implement stage-preserving lineage selection, ancestor
and descendant disambiguation, historical revision URLs, and invalid-selection behavior.

Acceptance: graph fixtures cover branches, multi-input results, empty steps, reload, back/forward,
and stale/deleted links without selecting another branch or writing processor preferences.

Result: the workspace exposes a recording-scoped graph endpoint. URLs store exact node and revision
IDs. The workspace validates those IDs and keeps stale selections visible without a fallback. The
resolver reports unique, empty, or ambiguous ancestors and descendants. Local legacy data has no
node graph until the later migration milestone.

### M1 — Build the two-row processing navigation — Complete

Replace the split top bar with aligned step and data rows. Add Virtual scenes and meaningful empty
states. The drawer toggle belongs to this component. Remove the Generated/Reviewed switch.

Acceptance: stage switches retain exact lineage; missing results stay empty. No new run buttons.

Result: the top navigation has six aligned step columns and a data row under each step. It shows
the exact selected node name and revision from the lineage URL, or a clear empty state. Virtual
scenes has its own route and empty state. The Generated/Reviewed top-bar switch is removed. Stage
navigation preserves lineage and does not add processor controls.

### M2 — Build the horizontal lineage drawer — Complete

Render step-aligned nodes, typed copy/process connections, selected path, compact metadata, and
all-source details. Support collapsed branches, history inspection, and accessible navigation.

Acceptance: select alternatives and copies without ambiguity; show all inputs of observations and
analyses. Verify desktop layout and narrow-screen reflow. No separate display dropdown remains.

Result: the two-row navigation can expand a keyboard-accessible drawer with six aligned step
columns. It lists data sets and their current revisions, labels copy and processor input sources,
and shows every exact source and role for multi-input results and analysis runs. Revision history
stays collapsed until opened. Selecting a revision updates the exact lineage URL and preserves
selections in other steps. The layout reflows to three, two, then one column on narrower screens.
Processor input controls remain separate from lineage browsing.

### M3 — Integrate shared editing and copy UX — Complete

Use atomic 0107 copy services. Select the copy after the first actual change. Add automatic names,
reason/source notice, original navigation, save/conflict states, and explicit copy/history actions.

Acceptance: editor open creates nothing; first protected edit creates/selects one copy; continued
edits and retries use it. Preserve exact inspection position and explain missing correspondence.

Result: the workspace API exposes idempotent node edit, explicit copy, and historical restore
operations through the atomic 0107 service. A changed edit after accepted downstream use creates a
uniquely named copy; retries return the same result. The lineage drawer can create a copy of the
exact displayed revision, selects the returned copy, and reports its source while keeping the
original available in lineage. Editor-specific save adapters will connect during M4–M7 as each
legacy editor moves to node content.

### M4 — Move event editing to data nodes — Complete

Unify generated and maintained event loading, editing, item review, and overall review. Remove
event-specific review seeding and old view branches once replaced.

Acceptance: tool events, human additions/corrections/deletions, negative coverage, autosave, and
automatic copy work through one content contract with retained provenance.

Result: selecting an event node opens one editor for generated and human content. It loads one exact
revision, keeps historical revisions read-only, and saves event additions, corrections, and
deletions through the atomic node edit service with item provenance. Autosave retries reuse the same
idempotency key. A protected edit selects its new copy and preserves the inspected event and time.
Item decisions, full-recording coverage, and overall decisions use separate revision-bound reviews.
Event lineage selection hides the legacy generated/reference selectors. Records that do not yet have
an event node keep the old workspace path until M10 migrates them; M11 owns its removal.

### M5 — Move visible-card editing to data nodes — Complete

Integrate visible regions, pile regions, ignore regions, and independent copies. Replace the review
dropdown and separate maintained-reference path. Preserve exact source-frame validation.

Acceptance: independent migrated reviews remain separate; region and pile edits retain semantics,
coverage, provenance, and copy behavior. No scene editor is implicitly selected as visible cards.

Result: selecting a visible-card lineage node opens its exact revision in a node-backed editor. The
editor shows the source video at each outcome's requested frame time and exposes visible, pile, and
ignore region data for editing while keeping frame identity fixed. Saves use atomic node edits with
outcome-level provenance and select protected copies in the lineage URL while preserving the frame
selection. Item, full-recording coverage, and overall decisions use separate revision-bound reviews;
existing decisions load with the selected revision. Full coverage requires an explicit inspection
mark for every outcome. Node validation rejects a frame identity from a different source video.
Recordings without a visible-card node retain the legacy editor until M10 migrates them; M11 owns
legacy-path removal.

### M6 — Expose first-class virtual-scene editing — Complete

Move scene inspection, pose/stacking edits, and scene review into Virtual scenes. Retain exact
calibration context and validation; keep visible-region derivation explicit.

Acceptance: processor and human scene content use one editor. Editing a used scene creates a copy,
keeps the old identity branch intact, and leaves the copy's missing downstream steps empty.

Result: the Virtual scenes step opens an exact selected `virtual_scenes` node revision. It shows the
source video frame, frame identity, and exact calibration revision and digest. Operators can edit
the scene pose and stacking data, save through the atomic node edit contract, and record separate
frame and data-set review decisions bound to the selected revision. A protected edit selects the
copy in the Virtual scenes lineage field and keeps the source node available. Historical revisions
are read-only. The drawer and lineage resolver accept both processor proposal nodes and unified
virtual-scene nodes; proposal nodes remain visibly read-only. The editor changes only scene content,
so node validation checks the saved scene against its fixed frame and calibration context. Visible
region derivation remains separate.

### M7 — Move visual identity review to data nodes — Complete

Unify prediction and annotation viewing while preserving human classifications, item/overall review,
and exact crop sources. Remove the old generated/reference view split and review-start gate.

Acceptance: history retains original predictions and corrections. Fixture results passed through the
0107 applicability service keep unaffected review and expose affected review without a blanket reset.

Result: selecting a `visual_identities` node in lineage opens its exact revision in the identity
workspace. The editor shows each outcome's exact frame and crop digest, allows classification edits
while keeping card, frame, geometry, and crop source fields fixed, and saves through the atomic node
edit contract. Protected edits select the returned copy. Item and overall decisions use revision-bound
node reviews and load with the selected revision. The node editor has no generated/reference split or
review-start gate. The existing editor remains the fallback until the M10 reader cutover.

### M8 — Integrate observation, analysis, and comparison views — Complete

Use drawer selection for existing observation/analysis inspection. Show multi-input provenance,
round context, failed attempts, and empty content. Keep comparison and processor input controls.

Acceptance: exact analysis and observation selection survives tab switches and deep links. The
comparison pair remains explicit. Browsing never starts work or changes input defaults.

Result: selecting an observation node in lineage opens that exact revision. Its observation list,
full selected observation, and exact processor-input edges are visible. Empty content and invalid
deep-linked item IDs remain explicit; the editor does not select a substitute. Failed and partial
assembly attempts remain visible. The lineage drawer selects exact analysis IDs, and analysis
selection remains in the URL when operators move between steps. The analysis view shows exact input
revisions, session and round context, status, and attempt history. These browsing paths do not call
processor controls or change their input selection. Comparison continues to use its explicit left,
right, and reference URL fields.

### M9 — Connect processor writers and accepted input use — Complete

Adapt event, detector, scene, identity, observation, and analysis outputs to nodes/revisions. Register
accepted inputs before execution, including automated runs. Keep existing execution semantics and
input controls. Do not silently append to human-edited nodes or overwrite their decisions.

Acceptance: fixture processors produce a complete graph, stop on existing failure gates, retain
valid empty outputs and analysis context, and protect inputs during concurrent first edits.

Result: processor run creation now registers exact input revisions before a worker starts. Terminal
processor outputs, empty results, partial results, failures, and retries publish immutable lineage
records. Retained revision content appears as its own node revision, so a later processor result
does not overwrite a human edit. Round analysis records exact observation and package inputs,
round context, search settings, and input/result artifact digests. Managed automated runs use the
same job acceptance path for analysis. Recording graph queries retain artifact-only analysis runs.
Fixture checks cover empty event output, accepted-input protection, retry acceptance, multi-stage
observation inputs, and analysis artifacts. Existing processor execution and selection controls stay
in place.

### M10 — Execute the verified local migration and cutover — Complete

Run the inventory/dry run against current local stores. Resolve blocking mappings, stop writers for
a consistent snapshot, stage and verify migration, then switch runtime readers and writers. Use
the user's explicit migration authorization. Retain a recovery snapshot and publish reconciliation.

Acceptance: migrated processor results, drafts, independent reviews, scenes, and analyses open with
correct content, coverage, and exact inputs. Restart does not restore an old default or adapter.
If source data has drifted, regenerate the plan; do not use an outdated inventory.

Progress: the stopped stores have a consistent recovery snapshot. The inventory covers 2,086
resources and 34,414 files with no blocking conflicts. The user declared three detector revision
inputs lost. Their IDs remain on the calibration references with explicit lost status. The IMG_0096
calibration is preserved in an exact embedded scene copy. The verified package is active at
`data/operations/pipeline-nodes`. It contains 835 processor data nodes, 594 processor runs, and
five analysis runs. The processor writer resolves imported revision IDs to these nodes. The importer
also writes 136 selections with exact node and revision pointers. It preserves 126 maintained
drafts, 13 calibration drafts, and 11 independent review packages in the graph store. Workspace
revision options, compatible inputs, and terminal run lineage now use exact graph revisions.
Processor progress and failure details and analysis summaries retain their live store readers.
Active-store checks opened scene, review, draft, calibration, and analysis data and confirmed their
content and coverage after rebuilding the runtime. See the
[M10 migration reconciliation](../../reports/0108-M10_Migration_Reconciliation.md).

### M11 — Delete replaced architecture — In progress

Complete the removal table. Trace selection consumers and keep only required execution semantics.
Delete old active storage after recovery evidence, legacy readers, view/review-specific runtime
contracts, obsolete endpoints/URLs, CSS, generated types, and superseded tests. Repair active links.

Acceptance: no active workspace path depends on Generated/Reviewed or privileged maintained drafts.
Migration input parsing is isolated from runtime. No permanent adapter, dual write, or duplicate
selector remains. Domain uses of "reviewed" that express actual authority remain valid.

Progress: the active task surface no longer opens the legacy Generated/Reviewed editors when no
lineage node is selected. It shows an explicit empty state. The shared event-rail type no longer
depends on the legacy event editor module. The unmounted Generated/Reviewed event editor and its
view-specific inspector, presentation, and tests are removed. The workspace URL no longer carries
view, review, or displayed-revision fields. The lineage selection supplies the exact revision.
The processor input selector remains because it controls execution defaults. The review-start
action is removed. Focused URL, presentation, workspace, and event-rail tests pass. The remaining
work is to remove backend adapters/storage, then verify selection consumers and the migrated active
data. The unmounted visible-card and visual-identity editors, their isolated helpers and tests, and
the obsolete editor boundary check are removed. The workspace still reads the legacy reference
store and translates migrated revision IDs at runtime. These dependencies must move to canonical
nodes before the old storage and mapping can be removed.
The inspector no longer repeats legacy generated and reference facts. The frame review no longer
compares its node revision ID with the unrelated legacy maintained-draft revision ID. The migrated
draft and review records still need conversion to editable nodes before their old routes can close.
An isolated staged conversion now creates 137 draft nodes and 34 virtual-scene nodes. It retains
8,778 item, coverage, and completion records, 94 completed and 43 draft states, and exact source
links. It keeps 326 scene-only frames separate from visible-region data. Six scene frames have
unavailable geometry; their original facts remain in node metadata. The guarded import is active
and its content, exact sources, and reviews passed independent verification. Processor services
still use the old revision store, so imported drafts are not yet offered
as execution inputs. Frame queue links now select exact lineage nodes. Queue receipts use exact
node review IDs and check the original source and current review applicability. Item reviews can
also bind directly to an unedited processor revision. Virtual-scene and identity review requests
now include the policy required by the node review service.
An activation guard checked 415 retained files and rejected changes or conflicting nodes. The
backend was stopped for activation. The frame queue has 165 exact node bindings and no longer reads
the legacy revision store. The retired maintained-reference and independent-review HTTP routes and
browser client methods are removed. Internal legacy stores and processor adapters still need removal.
After restart, the queue returned 165 available items. The IMG_0096 workspace and recording graph
opened with no workspace diagnostics. Startup recovery reads compact run statuses before loading
interrupted runs, so it does not load every completed run at startup.

The workspace now includes imported draft node revisions in its exact input options. Imported draft
options use an explicit label. A fixture confirms that a migrated event draft can start visible-card
processing with its exact node and revision IDs. The unused maintained identity-crop route and
client path are removed. The active old reference and review stores still match the M10 recovery
snapshot byte for byte. A separate recovery copy now preserves all 136 active node-selection files.
An additive exact node-selection API now reads and writes node/revision pointers without converting
them through the legacy revision map. A coordinated transaction foundation journals multiple node
revisions and exact selections. Node and selection reads recover a prepared transaction before
they return. Fixture tests cover pointer validation, competing selection writers, publication of
visible-card and virtual-scene revisions, and recovery after the first node head changes.
Calibration apply now publishes the reflowed visible-card draft and virtual-scene draft through one
journaled node transaction. It leaves exact selections unchanged, as the prior apply path did. It
retains the established calibration gates, forced affected-frame decisions, and correction-impact
calculation. Immutable item reviews remain applicable only when the item digest is unchanged through
the revision parent chain. Changed item decisions and exact-revision overall and coverage decisions
remain in the review history but are inapplicable to the new revision. A fixture interrupts after
the visible-card head update and confirms restart recovery publishes both heads before reads.

### Execution handoff — 2026-11-06

- **Completed:** M11 work remains incomplete (0/1 complete, 1/1 remaining in this run).
- **Changes:** Imported draft revisions appear in workspace options and use an Imported draft label.
  A fixture runs visible-card processing from an exact migrated event node. The maintained identity
  crop route and client path are removed. This run adds an exact node-selection API and a journaled
  multi-node transaction foundation. Production callers still use the legacy selection projection.
- **Recovery evidence:** The 511 files under `data/operations/pipeline-references` and the 53 files
  under `data/operations/pipeline-reviews` match the M10 recovery snapshot with no missing, extra,
  or changed files. `verify_active_draft_snapshot` confirmed 415 retained draft and review files
  against the verified M10 migration package. Before selection cutover, all 136 active selection
  documents were copied and hash-verified at
  `data/operations-recovery/0108-m11-20261106/migrated-selections-before-cutover`; see
  `data/operations-recovery/0108-m11-20261106/selection-recovery.json`.
- **Checks:** The imported-event fixture, route inventory, focused Ruff checks, `git diff --check`,
  and generated OpenAPI verification passed. The full web check stops at two lint errors in
  `CardEventFrameSurface.tsx`. The full web test run has nine failures in three CardEvent cache and
  frame-surface test files; 164 tests passed. A prior focused backend run had one retry-race failure;
  its isolated rerun passed. The new node store, edit, accepted-use, exact-selection, and coordinated
  transaction fixtures pass (22 tests); focused Ruff, formatting, and `git diff --check` pass.
- **Known limit:** `PipelineNodeSelectionStore`, `PipelineLineageWriter`, and the workspace still
  read `.legacy-revision-map.json`. Runtime composition still loads `.migrated-readers`. Calibration
  refinement still uses reference-service validation and correction-impact helpers, with the exact
  detector source cached from its canonical node. Runtime calibration reads and old reference storage
  remain until the remaining M11 removal audit and recovery checks pass.
- **Latest package:** Proposal creation can consume an exact canonical visible-card node revision.
  The node reference is frozen in the processor request, validated again before execution, and read
  by the worker. Fixture checks confirm the request retains exact node and revision IDs and does not
  call the legacy revision store during freeze or validation. Calibration proposal lookup and target
  publication now use canonical proposal and detector nodes. The reflow planner reads the current
  visible-card node revision and its retained review facts, then runs the established seed and reflow
  functions with a cached canonical detector source. It stores the receipt before the journaled node
  transaction so a retry can finish or return the same published result. Focused calibration,
  proposal, and transaction tests pass, along with operation data-contract tests and Ruff,
  formatting, and `git diff --check`. M11 remains incomplete.
- **Remaining M11 work:** Runtime selection adapters, migrated readers, and old reference/review
  storage remain. Keep these stores until the remaining runtime cutover and recovery checks pass. The
  imported-draft expectation and retry test race were
  resolved: the workspace test
  now asserts imported drafts are offered, and its polling waits for the managed job's terminal
  state. `uv run --project backend pytest
  backend/tests/test_visible_card_pipeline_api.py::test_migrated_event_draft_is_selectable_as_exact_visible_card_input
  backend/tests/test_visible_card_pipeline_api.py::test_visible_card_pipeline_retry_creates_a_linked_managed_job
  backend/tests/test_lineage_draft_projection.py::test_workspace_offers_an_imported_draft_as_processor_output
  -q --tb=short` passed all three.
- **Additional changes:** Calibration apply now publishes migrated visible-card and virtual-scene
  draft revisions in one journaled transaction. Node revision IDs are deterministic from the
  reflow receipt. The transaction has no selection updates because legacy apply did not change
  selection pointers. The no-selection transaction path no longer instantiates the legacy selection
  adapter. A retry after node publication returns the exact published draft projection.
- **Review rules:** Old immutable review records remain stored. Item decisions apply through the
  revision parent chain only when the item digest is unchanged. Changed item decisions and
  exact-revision overall or coverage decisions are inapplicable. The focused fixture checks both
  unchanged and changed item decisions and exact-revision overall decisions.
- **Checks:** `uv run --project backend ruff check` on the calibration service, composition,
  transaction service, and calibration tests passed. Ruff formatting passed. Focused pytest for
  calibration refinement, node transactions, node reviews, and lineage draft projection passed
  (24 tests). `git diff --check` passed. The transaction fixture interrupts after the visible-card
  head update, restarts the node store, and verifies both heads before further reads.
- **Next:** Verify the full reflow path against a richer calibration fixture, including anchor
  state and affected frame behavior. Then remove the legacy map reader, migrated readers, duplicate
  selection fields, and old reference storage only after verified recovery evidence. Run the
  complete M11 removal audit before commit.
- **Run count:** Requested 1 milestone; completed 0; remaining 1.

- **Latest package — map-free runtime selection:** `PipelineNodeSelectionStore` and
  `PipelineLineageWriter` no longer load `.legacy-revision-map.json`. Selection projection resolves
  retained legacy execution IDs from the selected node revision metadata. The workspace builds its
  revision lookup from node history. The migration map remains an input to offline migration and
  verification functions only. Exact pointer validation still rejects a wrong recording/content
  type and an absent node revision. A fixture writes malformed map bytes and confirms runtime
  selection reads still succeed from canonical node metadata. This preserves execution request
  fields while removing the migration map from runtime selection reads and writes.
- **Checks:** Focused selection, lineage writer, pipeline API, draft projection, proposed-scene, and
  migrated-event processor-input fixtures passed (35 tests). Ruff check, Ruff format check, and
  `git diff --check` passed. The source audit found no migration-map reference in the selection,
  lineage writer, workspace, or composition modules. A wider exploratory run also exercised
  observation and identity APIs; it had 9 failures caused by existing removed-endpoint/input
  expectations recorded above and 64 passing tests. No real processor ran.
- **Remaining:** Runtime consumers still use the `PipelineSelection` projection for legacy
  execution request fields. Convert those consumers to explicit node/revision references before
  removing that projection. Migrated reader and old reference/review storage cutover remains unsafe
  until its review and calibration consumers move to canonical nodes. M11 is incomplete.
- **Run count:** Requested up to 10 Luna loops; completed 1; remaining 9.
- **Follow-up check:** A correction pass began migrating fixture helpers to enqueue event jobs
  through the current Job API and to pass the selected event node/revision from workspace options.
  The focused rerun did not pass. It exposed stale test assumptions beyond the original nine: the
  observation retry test compares different output revision IDs; the analysis counterfactual POST
  returns 404; and visual-card tests still poll job IDs as if they were processor run IDs. The
  modified fixture helpers are incomplete and must be reconciled before they can serve as evidence.
  No backend contract ambiguity is established yet. Do not treat these failures as baseline. Next,
  align each fixture with the response IDs and current routes, rerun the nine cases, then continue
  exact-reference cutover for visual identity and observation consumers.
- **Reconciliation attempt:** Ran the three affected backend API modules again. Nine tests fail.
  The visual-identity fixtures post a managed job, then use the requested run ID with the old
  stage-result route. The response has a different run ID, and the old route returns 404. One
  observation fixture expects a legacy compatible-input set that the current workspace does not
  return. Two parameter cases post a counterfactual to a removed direct-create route. These are
  fixture/API gaps; this run did not establish that the runtime lineage contracts are wrong. The
  observation retry also still compares different output revision IDs. Do not commit the package
  until the fixtures use current job results and canonical node references, and the counterfactual
  case uses the current job API.
- **Checks:** Selection, transaction, and calibration-refinement fixtures passed (14 tests).
  Ruff check, Ruff format check, generated OpenAPI verification, and `git diff --check` passed on
  the current files. The three API modules remain red (9 failures), so the M11 package is not safe
  to commit. No processor ran.
- **Next:** Reconcile managed-job IDs and result reads in the affected fixtures. Replace stale
  compatible-input assertions with exact node-reference expectations. Route counterfactual
  fixtures through the job API. Then rerun the three modules and continue the remaining M11
  selection and storage removal audit. Preserve active reference/review storage until all
  consumers and recovery checks pass.
- **Commit decision:** No intermediate commit. Existing M11 source and fixture changes remain
  uncommitted because affected API fixtures do not yet provide verified evidence.

- **Latest reconciliation:** Fixed the nine failures in the observation, visual-identity, and
  visible-card API modules. Fixtures now use managed job IDs and results. The observation fixture
  writes its changed visible-card revision and generated identity revision to canonical node
  storage. The counterfactual fixture now submits through `/api/jobs`. It also waits for the
  observation selection pointer to catch up after the run reaches its terminal state. This was a
  fixture timing issue; no observation service change was needed. The visual-identity retry fixture
  now seeds a real failed job before it calls the retry route.
- **Checks:** All modified backend test modules passed, including the three formerly failing API
  modules. Ruff check and format passed. TypeScript typecheck, lint and format on changed web files,
  OpenAPI verification, and `git diff --check` passed. Full web checks still report two lint errors
  in unchanged `CardEventFrameSurface.tsx`, seven formatting warnings in unchanged CardEvent files
  and `AutomatedPipelineControls.test.tsx`, and nine failures in three unchanged CardEvent cache and
  frame-surface test files. The remaining selection and storage cutover is not complete. No
  processor ran.
- **Commit:** An intermediate M11 commit is safe after these focused checks. Keep M11 in progress.
  Runtime selection adapters, migrated readers, and old reference/review storage remain for the
  next package.
- **Latest package — ordered processor node references:** `ProcessorRunRequest` now accepts an
  ordered `input_node_refs` list for visual identity and observation assembly, while retaining the
  existing single-reference contract for visible-card execution. The contract validates reference
  shape, processor support, unique nodes, and count against ordered input revision IDs. The lineage
  writer records each exact node revision and role, then protects the referenced nodes for the
  accepted run. Output validation treats these inputs as canonical node lineage.
- **Checks:** Operation pipeline-data tests passed (15 tests). Backend pipeline-store and lineage
  writer tests passed (21 tests). Ruff check and format checks passed for changed Python files;
  `git diff --check` passed.
- **Known limit:** Observation and visual-identity services do not yet populate or validate the
  ordered references. Their workers still load input content from the legacy revision store. No
  storage or reader deletion is safe until these consumers move to canonical node content and
  recovery checks pass. No real processor ran.
- **Next:** Update the two services to freeze exact ordered node references, validate the referenced
  revisions again before execution, and read input content from those node revisions. Add API and
  worker fixtures for historical and current-head inputs. Then remove the old projection only when
  all selection consumers and storage recovery evidence pass.
- **Run count:** Requested up to 10 Luna loops; completed 1 bounded package; remaining 9.
- **Latest package — observation and identity execution:** Observation requests now freeze three
  ordered node/revision references. They resolve exact node pointers from the selected node records
  or from revision lineage. The observation worker parses event, visible-card, and identity content
  from those node revisions. Visual-identity requests now freeze one exact node reference. The job
  participant validates it before execution, and the classifier reads visible-card or proposal
  content from the node revision. Legacy revision IDs remain in the processor request and manifest
  for current provenance and result contracts. They provide manifest metadata during identity crop
  validation; node content supplies the processed data.
- **Checks:** The observation and visual-identity API modules passed (15 tests). Ruff check and
  formatting passed for changed Python files. `git diff --check` passed. The tests use fixtures and
  mocks; no processor model ran.
- **Known limit:** The input freeze still uses legacy revision metadata to resolve an old revision
  ID when no canonical node matches. Identity crop validation still reads legacy manifests. Other
  runtime consumers and the migrated reader/reference/review storage remain. No old storage was
  deleted. M11 is incomplete.
- **Next:** Remove legacy identity from the two services' execution request and crop validation by
  using canonical revision metadata throughout. Then audit all selection consumers, update exact
  selection writers, and prove recovery before retiring `.migrated-readers` and old storage.
- **Run count:** Requested up to 10 Luna loops; completed 2 bounded packages; remaining 8.
- **Latest package — canonical identity input manifest:** `canonical_input_revision` now reads and
  validates content from the exact node and revision reference, then rebuilds the legacy execution
  manifest from validated node metadata. The identity worker no longer needs a legacy revision
  manifest to materialize that input. A fixture makes legacy manifest reads fail and confirms the
  exact node revision still loads with the expected execution revision ID.
- **Checks:** The visual-identity API module passed (9 tests). Ruff check, Ruff format check, and
  `git diff --check` passed. An initial focused invocation named a nonexistent test module; the
  corrected command passed. No processor model ran.
- **Known limit:** Crop descriptor digest validation and stored crop provenance still depend on the
  legacy manifest contract. This package did not change the crop schema or remove other legacy
  readers/storage. M11 remains incomplete.
- **Next:** Cut over crop descriptor and outcome provenance together. Bind each descriptor to the
  exact node and revision identity, validate canonical metadata and content, and preserve retry and
  historical-input behavior. Then continue the runtime consumer and storage removal audit.
- **Run count:** Requested up to 10 Luna workers; completed 3 bounded packages; remaining 7.
- **Latest package — canonical crop descriptor and provenance:** New crop descriptors use
  `visual-identity-crop-input/v4` and bind the exact source node and revision. Their revision digest
  covers the canonical node revision record. Each outcome carries the same node identity in
  `visual-identity-crop-input-provenance/v3`. Validation checks node content, source, legacy
  execution revision, and revision digest. The v3 crop descriptor and v2 provenance formats remain
  readable for accepted historical runs, so retries retain their frozen request semantics.
- **Checks:** Visual identity API, crop input, and pipeline data tests passed (44 tests). Ruff check
  and format passed. `git diff --check` passed. API fixtures cover new exact node references;
  existing retry and legacy contract tests passed. No processor model ran.
- **Known limit:** This package changes the visual identity crop contract only. Other runtime
  consumers and legacy reference/review storage remain. M11 is incomplete.
- **Next:** Continue the runtime selection and storage removal audit. Verify no caller depends on
  legacy crop digest fields before removing legacy manifest readers.
- **Run count:** Requested up to 10 Luna workers; completed 4 bounded packages; remaining 6.
- **Latest package — canonical identity completion selection:** Visual identity crop validation no
  longer reads `PipelineReferenceStore`. It checks the exact completed-node pointer in
  `PipelineNodeSelectionStore` and requires an exact overall `complete` decision in
  `PipelineNodeReviews`. Runtime composition no longer passes the legacy reference store to the
  identity service. The fixture now creates a canonical node, its review, and its exact execution
  pointer, then confirms that removing the pointer rejects the input.
- **Checks:** The full visual-identity API test module passed. Focused Ruff checks, format checks,
  and `git diff --check` passed. No processor model ran.
- **Known limit:** Calibration refinement still reads retained legacy review facts and calls the
  legacy proposal seeding helper. `PipelineReferenceService` and `VisibleCardReviewService` remain
  in runtime composition for calibration routes. Other execution services still project exact node
  pointers to legacy revision IDs for processor input contracts. No old storage was deleted.
- **Next:** Move calibration review validation and draft reflow to canonical node content and
  revision-bound review records. Then audit the remaining selection projections and remove legacy
  stores only after recovery and reconciliation checks pass.
- **Run count:** This request allows up to 20 worker loops. Worker 1 is active; 0 milestones are
  complete. M11 remains in progress. Up to 19 worker loops remain if needed.
- **Latest package — retire review-scoped calibration routes:** Removed the calibration API routes
  that used `/reviews/{review_id}` and removed the optional review route branch from the browser
  client. The generated OpenAPI client no longer exposes those routes. The recording-scoped
  calibration refinement endpoints remain.
- **Checks:** Calibration service and pipeline API tests passed (25 tests). OpenAPI generation and
  verification, TypeScript typecheck, focused ESLint, Prettier, Ruff, and Ruff formatting checks
  passed.
- **Known limit:** Calibration refinement still reconstructs legacy review facts from migrated
  node metadata and calls the legacy proposal seed helper. The runtime reference and review stores
  remain loaded. Removing those stores is still unsafe until calibration uses canonical review
  records and exact node inputs.
- **Next:** Convert calibration reflow to canonical node review records and exact proposal and
  detector node references. Continue the full runtime reader and storage audit.
- **Run count:** This request allows up to 20 worker loops. Worker 1 is active; 0 milestones are
  complete. M11 remains in progress. Up to 19 worker loops remain if needed.
- **Latest package — remove reference and review stores from runtime composition:** Calibration
  proposal seeding and correction-impact validation now use a pure helper over exact proposal and
  detector content. Runtime composition no longer creates or exposes the legacy reference and
  visible-card review services or stores. The standalone calibration refinement routes remain.
- **Checks:** Pipeline API, calibration refinement service, and reference-service test modules passed
  (77 tests). Ruff checks, format checks, and `git diff --check` passed.
- **Known limit:** Calibration draft state still uses
  `pipeline-nodes/.migrated-readers/calibration-drafts` (26 files). Calibration reflow still reads
  retained `legacy_review` metadata from canonical node revisions. The old reference and review
  files remain on disk as recovery data. Runtime selection projection still supplies legacy
  revision IDs to processor execution choices.
- **Next:** Move calibration draft storage out of `.migrated-readers` with verified copy and restart
  checks. Then make calibration reflow consume canonical node review records and exact proposal and
  detector references. Keep the recovery copies until the final removal audit passes.
- **Run count:** This request allows up to 20 worker loops. Worker 1 is active; 0 milestones are
  complete. M11 remains in progress. Up to 19 worker loops remain if needed.

### M12 — Verify the complete workflow and close — Not started

Run focused automated tests, web build/type/lint/format/API checks, relevant backend checks, and
Markdown link checks. Use recorded fixtures and mocks; no hardware or model-quality run is needed.
Document commands, migration reconciliation, removal evidence, and any unrelated baseline failures.

Acceptance: a browser regression covers the two-row drawer, exact branch switching, empty tab,
copy-on-edit notice and selection, source/history navigation, review preservation fixtures, reload,
and all-source analysis inspection. Local migrated data is inspectable. All removal obligations
are complete before closure. Update the board and repair links when moving this epic.

## Implementation entry points

- `web/src/pipeline/RecordingWorkspaceShell.tsx` and `RecordingWorkspaceInspector.tsx`.
- `web/src/pipeline/recordingPipelineUrl.ts` and `recordingWorkspacePresentation.ts`.
- `web/src/visibleCards/PipelineNodeVisibleCardEditor.tsx` and `PipelineNodeVirtualSceneEditor.tsx`.
- `web/src/cardEvents/PipelineNodeEventEditor.tsx`.
- `web/src/visualIdentities/PipelineNodeVisualIdentityEditor.tsx`.
- `backend/src/dokodetector_backend/pipeline_workspace_service.py` and workspace API.

This plan records the accepted concept. Exact spacing, line routing, and branch collapsing remain
implementation choices, subject to the behavior above.
