# Unified job start UX

## Plan status

- **Summary:** Give all long-running actions one start flow: a consistent button in the right
  sidebar opens a modal that explains the work and collects its required inputs.
- **Status:** In Progress
- **Depends on:** [0110 — Global Job Manager](../5-closed/0110-Global_Job_Manager.md), complete,
  and [0108 — Horizontal lineage workspace](../5-closed/0108-Horizontal_Lineage_Workspace.md),
  including runtime cleanup and final verification. The lineage foundation in
  [0107](../5-closed/0107-Unified_Pipeline_Data_Lineage.md) is complete.
- **Outcome:** M0–M7 complete. M8–M10 remain.
- **Readiness gate:** Passed on 2026-11-07 at `2cf915b83`. 0108 M11–M12 and 0110
  M15–M16 are complete; both epics are closed. Current processor, observation, analysis and
  pipeline launch controls remain in `RecordingWorkspaceInspector`; counterfactual controls are
  in `web/src/analysis/CounterfactualWorkbench.tsx`. M0 inventoried registry types and callers.

## User outcome

An operator can start work from the same place in each workspace. Before submission, the operator
can understand what will happen, select all required inputs, and see what the job will produce.
The modal contains the complete launch form. The operator does not have to configure a separate
toolbar first or infer an execution input from the data currently shown in the center.

Use the terms in the [glossary](../../glossary.md). A backend job manages execution. A processor
run records processing. A pipeline data node and its data revisions represent content. The launch
flow must preserve these distinctions.

## Scope and existing owners

Cover every existing browser action that starts long-running backend work. Use the registered
job types and browser call sites as the inventory, rather than a duration threshold. This includes:

| Action family               | Inputs the modal must expose or explain                                                                                               |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Event processing            | Accepted source video, processor/model and configuration. `event_import` has no browser entry point and remains agent/import tooling. |
| Visible-card processing     | Exact event/frame inputs, detector/model, extraction and processing options                                                           |
| Proposed card scenes        | Exact visible-card and calibration inputs, processor and fitting options                                                              |
| Visual identities           | Exact crop geometry inputs, model/provider, crop policy and processing options                                                        |
| Table observations          | All exact input revisions and assembly options                                                                                        |
| Round analysis              | Exact observations, required round facts, rules and search limits                                                                     |
| Complete recording pipeline | Required source inputs, stage models/configuration, round facts and stage/output summary                                              |
| Calibration preview         | Exact working-state/evidence snapshot and calculation options                                                                         |
| Counterfactual calculation  | Exact analysis result, correction constraints and calculation options                                                                 |

M0 must reconcile this list against the completed prerequisites. Include any surviving browser
command that starts classification as part of an approval workflow. Keep its human decision
separate from starting computation. A registered job type without a browser entry point needs an
explicit inventory disposition; this epic does not create a UI for agent-only tools.

0110 owns scheduling, admission, status, progress, cancellation, recovery, retry and result links.
0107/0108 own data lineage, revisions, copy rules and review applicability. Reuse those contracts.
This epic owns launch placement, explanations, forms, input selection and obsolete-launch cleanup.

[0109](../5-closed/0109-Working_Area_Interface_Unification.md) owns the shared working area and inspector
layout. Reuse its sidebar slots if available. It is not a completion dependency: add the smallest
right-sidebar slot needed in the current layout if it has not started. Do not redesign the center.
[Active module cleanup](0112-Active_Pipeline_Module_Cleanup.md) owns code extraction, including
launch request construction. M3 and M4 integrate 0113 callers first; 0112 M8 later extracts the
request builders and callers adapt to them. Keep modal form state and shared submission in each
caller. Neither epic blocks the other. Do not restore removed modules.

## Launch interaction

1. Show an **Actions** group in the right sidebar for the current workspace. Use one shared
   button style, size, spacing and label pattern. Labels name the work, such as **Detect visible
   cards…** or **Calculate calibration preview…**. The ellipsis indicates that a dialog follows.
   Keep the complete-pipeline action distinct from an individual-stage action.
2. A button opens a modal. Opening it starts no backend job and creates no domain output. Show
   the action name, a short explanation, required inputs, relevant options and expected outputs.
   Explain whether the action creates fresh output or performs a calculation for later application.
3. Collect all required launch inputs in this modal. Show fixed inputs as readable context and
   editable inputs as labeled fields. Show provider/model availability and prerequisite problems.
   Optional advanced settings can collapse; required fields and validation errors remain visible.
4. Show a final summary in the same modal, with a clear **Start <work>** action and **Cancel**.
   A separate confirmation dialog is not required. Use the established pipeline preflight where
   applicable. Explain queued execution without promising immediate processing or an invented ETA.
5. Validate before acceptance. Keep values and actionable errors on failure. During submission,
   prevent duplicate clicks. Reconcile uncertain responses through the existing acceptance contract
   before permitting another submission. Do not invent a second job submission lifecycle.
6. On confirmed acceptance, close the modal and show a persistent link to the accepted job through
   the shared Jobs UI. Keep the inspected branch and frame position. Output inspection remains an
   explicit result-navigation action. Closing the modal must never cancel accepted work.

The right-sidebar action group remains reachable when a step has no output. Keep actions visible
when a prerequisite is missing. The dialog explains what is missing and links to the relevant
workspace. A narrow layout uses an accessible right-sidebar drawer with the same actions. Define
focus behavior when the launch modal opens from that drawer; avoid competing focus traps.

## Input and authority rules

- Input fields identify the pipeline data node, exact immutable revision and relevant coverage.
  Show readable names and provenance, with full IDs available for disambiguation. Multi-input
  actions show every required role. Do not use a bare label such as “latest” as an accepted input.
- The inspected lineage can provide initial choices when correspondence is unambiguous. Show
  these choices in the modal. Missing or ambiguous inputs require an explicit choice. Browsing the
  lineage drawer must not write execution preferences or silently change an open form.
- Model and provider defaults must be visible. Select only compatible installed/available options.
  Do not silently fall back to a different model, provider, crop source or data branch.
- On source or model changes, refresh dependent choices and invalidate incompatible selections.
  Reject late responses for earlier choices. A dialog opened for one recording cannot submit work
  for another recording after navigation.
- Resolve any required save before accepting a working-state input. Freeze exact revisions,
  evidence snapshots, model/configuration and constraints through existing server contracts.
  Concurrent changes must produce a clear conflict or retain the exact selected immutable input;
  never silently replace it with newer content. Calibration results retain their apply-validity gate.
- Required round facts come from confirmed stored values or explicit input. Never invent missing
  facts to permit submission. Complete-pipeline preflight must collect them before starting work.
- Starting work does not grant review authority, apply a calibration result, approve an identity,
  select a downstream reference or overwrite human edits. Keep these domain commands explicit.
- New runs create fresh stage results under the existing contracts. Job retry retains the manager's
  frozen-input and history semantics. Shared retry management stays in Jobs; do not turn it into a
  model/input editor. Changed inputs require a new launch through this modal.

## Superseded UI

Move launch-only processor, provider, model, revision and parameter controls into the modal.
Remove their replaced inline forms, “run again” launch variants, complete-pipeline preflight
dialogs and feature-specific start dialogs once the corresponding action is integrated.

Keep lineage browsing and exact-revision comparison in their existing owners. Keep inspection,
editing, save, review and apply controls where their workflows require them. If a field currently
serves both inspection and launch, split the responsibilities before removing it. Keep useful
immutable run configuration available from result/job details. Use the shared Jobs components for
execution feedback; do not add per-feature polling, progress panels or cancel/retry controls.

Delete obsolete state, props, handlers, CSS, tests, client methods and endpoints only when they
have no surviving caller. Do not keep duplicate launch paths or compatibility facades.

## Milestone status

| Milestone | Work                                                  | State       |
| --------- | ----------------------------------------------------- | ----------- |
| M0        | Freeze launch inventory and interaction contract      | Complete    |
| M1        | Build shared sidebar action and modal shell           | Complete    |
| M2        | Add exact input selection and submission handling     | Complete    |
| M3        | Integrate event processing                            | Complete    |
| M4        | Integrate visible-card processing                     | Complete    |
| M5        | Integrate visual identities                           | Complete    |
| M6        | Integrate observations and round analysis             | Complete    |
| M7        | Integrate complete-pipeline launch                    | Complete    |
| M8        | Integrate calibration and counterfactual calculations | Not started |
| M9        | Remove replaced launch controls                       | Not started |
| M10       | Verify the complete workflow and close                | Not started |

## M0 — Freeze launch inventory and interaction contract

Complete: [M0 launch inventory](../../reports/0113-M0_Launch_Inventory.md). The report records all ten
production registry types, active browser submission and retry callers, request inputs, current
defaults and validation, replacement/removal owners, the sidebar/modal contract and its states, and
the M1 desktop/narrow fixture checks.

## Execution handoff

- M7 completed. Its result and checks are in
  [`0113-M7_Complete_Pipeline_Launch.md`](../../reports/0113-M7_Complete_Pipeline_Launch.md).
- Changes: the complete-pipeline action now uses the shared modal and the existing preflight API.
  It shows the exact accepted video context, all six stage model/configuration objects, required
  round facts, fixed rules/search limits, and expected outputs. It submits one fresh run request,
  retains values after rejection, retries uncertain acceptance with the same key and payload, and
  links the parent job through Jobs. The backend validates explicit round facts and rejects a
  recording/session mismatch before it writes a run or accepts a parent job. The page no longer
  restores a prior run or polls the pipeline endpoint; Jobs owns polling. Parent stage records
  retain exact child job and revision lineage.
- Checks: backend preflight, API, and job tests: 16 passed; modal fixture tests: 2 passed; frontend
  typecheck, generated API verification, changed-file Ruff check and format passed. Playwright
  launch check and the existing pipeline-cutover smoke test did not reach the rendered app; see the
  M7 report. Browser acceptance remains part of M10.
- Limits: model and configuration objects use JSON editors because the current API provides no
  browser inventory of supported per-stage models. Existing preflight validates availability.
- Next: M8, integrate calibration and counterfactual calculations.
- Run counts: requested 11 milestones, completed 8, remaining 3.

Acceptance: every current browser job start has an owner and migration milestone. All required
request fields have a visible input or explained fixed context. No unresolved product decision
prevents the remaining milestones. This inventory does not count as UI integration.

## M1 — Build shared sidebar action and modal shell

Add the reusable action group, button and accessible modal shell. Support action-specific form
content without building a generic schema-driven form engine. Add labeled sections, validation
summary, loading/submitting states, Escape, focus containment and focus return.

Acceptance: component tests and local browser fixtures cover keyboard use, scrollable long forms,
desktop/narrow layouts and interaction with both the lineage and Jobs drawers. No job starts on open
or cancel. The center remains available after dismissal.

## M2 — Add exact input selection and submission handling

Add reusable revision/model field behavior and a shared submission owner. Keep request construction
with each action. Handle dependent choice loading, compatibility, stale responses, context changes,
conflicts, uncertain acceptance and shared job receipts. Add server validation only where the
existing contracts cannot enforce the frozen-input rules; update generated types when required.

Acceptance: fixture tests cover ambiguous branches, multi-input revisions, unavailable models,
changed inputs during loading, recording navigation, double click, rejected requests and a lost
acceptance response. Accepted work links to one job without a second polling owner.

## M3 — Integrate event processing

Move event launch configuration into the shared modal. Place its action in the right sidebar and
remove the replaced event launch fields and button in the same milestone. The M0 audit found no
browser prediction-import entry point: retain `event_import` as agent/import tooling and add no import
UI. M9 repeats this caller audit before removing any unused facade.

Acceptance: fixtures submit the expected frozen processing request. Missing or invalid accepted video
stays visible in the form and blocks submission. Existing results and review decisions remain
inspectable.

Complete: [M3 event processing launch](../../reports/0113-M3_Event_Processing_Launch.md).

## M4 — Integrate visible-card processing

Move the active Visible cards detector action into the shared modal. Collect the exact selected event
revision and detector/model there. Show the request's implementation, configuration, extraction policy,
and current blockers. Keep the action visible if inputs are missing or incompatible. Remove the old
inline launch controls. Keep Virtual scenes review and edit controls in place. M0 found no browser
caller for scene creation, so do not add a scene launch action. The scene API and client facade remain
agent/API capability until M9 repeats the caller audit.

Acceptance: fixtures cover a valid exact event branch, missing and incompatible input blockers,
stage-specific detector/model configuration, and a shared job link. A launch never substitutes another
branch to satisfy prerequisites. Calibration is not an input to visible-card detection; proposal-scene
calibration remains an agent/API concern without a browser launch caller.

Complete: [M4 visible-card launch](../../reports/0113-M4_Visible_Card_Launch.md).

## M5 — Integrate visual identities

Move exact crop geometry, provider/model, crop policy and processing context into the shared modal.
Keep proposal-derived inputs on the local classifier. Provider/model availability is checked by the
existing visual identity service. Classification produces processor outcomes and does not accept or
reject identities. Keep the editor and review controls in place.

Acceptance: component fixtures distinguish generated polygon, generated RF-DETR, proposed virtual
card and reviewed geometry sources; invalidate crop-policy choices when geometry changes; retain exact
node and revision references; and make no review API call. Keep the current visual identity route and
request contract.

Complete: [M5 visual identity launch](../../reports/0113-M5_Visual_Identity_Launch.md).

## M6 — Integrate observations and round analysis

Move assembly input roles and reconstruction configuration into their respective modals. Collect
required round facts and expose exact observations, rules and search limits. Remove replaced forms.

Acceptance: multi-input fixtures cannot submit incomplete/incompatible roles. Missing round facts
prevent submission. Requests retain all selected revisions and explicit facts.

Complete: [M6 observation and analysis launch](../../reports/0113-M6_Observation_and_Analysis_Launch.md).

## M7 — Integrate complete-pipeline launch

Use the shared dialog for pipeline explanation, required facts, per-stage models/options, preflight
and output summary. Expose existing supported configuration; do not add new execution modes.
Replace its old launch/preflight flow and link the accepted parent through Jobs.

Acceptance: a local fake pipeline starts once with the displayed settings and facts. Invalid
preflight starts nothing and preserves entered values. Parent/child results retain exact lineage;
a new launch does not resume an earlier completed run.

Complete: [M7 complete-pipeline launch](../../reports/0113-M7_Complete_Pipeline_Launch.md).

## M8 — Integrate calibration and counterfactual calculations

Put calculation launch buttons in their workspace's right sidebar. Collect or summarize exact draft
evidence and correction constraints in the modal. Remove replaced calculation start controls.
Keep editing evidence/constraints and applying results as separate domain operations.

Acceptance: stale calibration evidence cannot be applied as current. Counterfactual requests retain
their exact analysis and constraints. Opening/cancelling either dialog creates no calculation job.

## M9 — Remove replaced launch controls

Reconcile the M0 inventory against source and rendered routes. Delete residual obsolete launch-only
selectors, forms, dialogs, props, styles and tests. Repair active documentation and ensure job status
still has one owner. Preserve closed epics as historical records.

Acceptance: every inventoried browser start uses the sidebar/modal flow, with documented Jobs retry
semantics. No duplicate active launch path or separate feature job poller remains. Inspection and
editing controls do not accidentally become launch defaults.

## M10 — Verify the complete workflow and close

Run a local fixture workflow across all action families. Verify keyboard/focus behavior, desktop
and narrow layouts, empty stages, missing prerequisites, multi-input branches, navigation races,
submission errors, accepted job links, reload and exact result navigation. Retain browser evidence.

Acceptance: relevant component/API tests, applicable lint/format/type checks, generated API
verification and focused browser checks pass. Run backend checks for any changed server contracts.
Publish the launch/removal inventory and operator handoff. Close only when all action families and
cleanup gates pass. No cloud, phone, training run or sealed evaluation is required.

## Scope limits

No new scheduler, job lifecycle, model algorithm, training UI, automatic cascading execution,
automatic source refresh, automatic human review, or iOS launch redesign. Small shared components
and feature-owned forms are sufficient. Do not turn this work into a generic workflow builder.
