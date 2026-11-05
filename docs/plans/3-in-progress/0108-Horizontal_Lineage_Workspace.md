# Horizontal lineage workspace

## Plan status

- **Summary:** Replace competing data selectors with a horizontal lineage drawer beneath the
  processing steps. Integrate unified data nodes, migrate local data, and delete replaced flows.
- **Status:** In Progress
- **Depends on:** [Epic 0107](../5-closed/0107-Unified_Pipeline_Data_Lineage.md), including tested
  migration tools and provenance/review contracts.
- **Outcome:** M0–M3 are complete; M4–M12 are not started. The workspace exposes exact graph data,
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

### M4 — Move event editing to data nodes — Not started

Unify generated and maintained event loading, editing, item review, and overall review. Remove
event-specific review seeding and old view branches once replaced.

Acceptance: tool events, human additions/corrections/deletions, negative coverage, autosave, and
automatic copy work through one content contract with retained provenance.

### M5 — Move visible-card editing to data nodes — Not started

Integrate visible regions, pile regions, ignore regions, and independent copies. Replace the review
dropdown and separate maintained-reference path. Preserve exact source-frame validation.

Acceptance: independent migrated reviews remain separate; region and pile edits retain semantics,
coverage, provenance, and copy behavior. No scene editor is implicitly selected as visible cards.

### M6 — Expose first-class virtual-scene editing — Not started

Move scene inspection, pose/stacking edits, and scene review into Virtual scenes. Retain exact
calibration context and validation; keep visible-region derivation explicit.

Acceptance: processor and human scene content use one editor. Editing a used scene creates a copy,
keeps the old identity branch intact, and leaves the copy's missing downstream steps empty.

### M7 — Move visual identity review to data nodes — Not started

Unify prediction and annotation viewing while preserving human classifications, item/overall review,
and exact crop sources. Remove the old generated/reference view split and review-start gate.

Acceptance: history retains original predictions and corrections. Fixture results passed through the
0107 applicability service keep unaffected review and expose affected review without a blanket reset.

### M8 — Integrate observation, analysis, and comparison views — Not started

Use drawer selection for existing observation/analysis inspection. Show multi-input provenance,
round context, failed attempts, and empty content. Keep comparison and processor input controls.

Acceptance: exact analysis and observation selection survives tab switches and deep links. The
comparison pair remains explicit. Browsing never starts work or changes input defaults.

### M9 — Connect processor writers and accepted input use — Not started

Adapt event, detector, scene, identity, observation, and analysis outputs to nodes/revisions. Register
accepted inputs before execution, including automated runs. Keep existing execution semantics and
input controls. Do not silently append to human-edited nodes or overwrite their decisions.

Acceptance: fixture processors produce a complete graph, stop on existing failure gates, retain
valid empty outputs and analysis context, and protect inputs during concurrent first edits.

### M10 — Execute the verified local migration and cutover — Not started

Run the inventory/dry run against current local stores. Resolve blocking mappings, stop writers for
a consistent snapshot, stage and verify migration, then switch runtime readers and writers. Use
the user's explicit migration authorization. Retain a recovery snapshot and publish reconciliation.

Acceptance: migrated processor results, drafts, independent reviews, scenes, and analyses open with
correct content, coverage, and exact inputs. Restart does not restore an old default or adapter.
If source data has drifted, regenerate the plan; do not use an outdated inventory.

### M11 — Delete replaced architecture — Not started

Complete the removal table. Trace selection consumers and keep only required execution semantics.
Delete old active storage after recovery evidence, legacy readers, view/review-specific runtime
contracts, obsolete endpoints/URLs, CSS, generated types, and superseded tests. Repair active links.

Acceptance: no active workspace path depends on Generated/Reviewed or privileged maintained drafts.
Migration input parsing is isolated from runtime. No permanent adapter, dual write, or duplicate
selector remains. Domain uses of "reviewed" that express actual authority remain valid.

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
- `web/src/visibleCards/PipelineVisibleCardEditorView.tsx` and its controller/inspector.
- `web/src/cardEvents/PipelineCardEventEditor.tsx`.
- `web/src/visualIdentities/PipelineVisualIdentityEditor.tsx` and its inspector.
- `backend/src/dokodetector_backend/pipeline_workspace_service.py` and workspace API.

This plan records the accepted concept. Exact spacing, line routing, and branch collapsing remain
implementation choices, subject to the behavior above.
