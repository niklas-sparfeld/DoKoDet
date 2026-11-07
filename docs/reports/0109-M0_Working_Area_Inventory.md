# 0109 M0 working-area inventory

Date: 2026-11-07

## Result

M0 freezes the current function inventory and the surface contract for later
work. It changes no application behavior. The 0107 and 0108 dependencies are
closed, so epic 0109 is Ready for M1.

The local component tests render the current task surfaces with recorded API
fixtures. The 0108 browser regression also renders the recording workspace with
local route fixtures and checks the navigation, inspector, rail, empty state,
copy-on-edit, review retention, reload, and exact analysis inputs. This is
rendered-fixture verification, not a usability study.

## Function placement inventory

The center is the source-frame surface. The inspector holds commands, state,
descriptions, selected-item details, crop previews, and diagnostics. The
Timeline Rail holds the one workspace time cursor, frame movement, intervals,
and analysis rows. Existing functions stay available when their controls move.

| Step or view              | Existing commands, selection, crops, analysis, and diagnostics                                                                                                                                                                                                                                                                                                                  | Target slot                                                                                                                                                                                                                                                                                               |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Events                    | Select an event; add and delete events; edit start and end times; seek the recording; save edits and retry a failed save; record item decisions, inspected coverage, and overall review. Show load/save errors and review state.                                                                                                                                                | Center: event geometry and focus only. Inspector: add/delete, boundary edit, save/retry, review commands, errors and review state. Rail: event selection, time cursor, scrubber, frame stepping, and intervals.                                                                                           |
| Visible cards             | Select an exact outcome/frame; inspect and edit visible-region, pile-region, ignore-region, and candidate data; save changes; accept/reject a frame; record coverage and overall review. Keep historical revisions read-only and show exact-frame/source errors.                                                                                                                | Center: source pixels, spatial layers, selection, and active edit handles. Inspector: layer/view controls, tools, details, save/review commands, and errors. Rail: frame/outcome navigation and shared time controls.                                                                                     |
| Virtual scenes            | Select a frame; edit card poses and stacking order; inspect calibration and migration facts; mark inspection, save, accept/reject, record coverage, and accept/reject the data set. Historical revisions are read-only; absent geometry and invalid calibration need explicit explanations.                                                                                     | Center: source pixels, calibrated geometry, selection, and active handles. Inspector: camera/rectified view, layers/tools, calibration facts, scene JSON and review commands. Rail: frame navigation and time.                                                                                            |
| Visual identities         | Select an identity outcome; inspect the exact processor crop and its source revision/digest; edit classification fields; save; accept/reject item and data-set review. Keep crop-load, failed, unusable, face-down, and stale-input details.                                                                                                                                    | Center: full source frame and selectable visible regions. Inspector: crop, candidates, classification editor, review commands, provenance, and errors. Rail: synchronized identity/frame selection and time.                                                                                              |
| Table observations        | Select an observation by exact item ID; inspect observed cards, candidates, capability availability, uncertainty, interval, status, and exact source references. Show failed attempts and unavailable data.                                                                                                                                                                     | Center: exact source frame and valid declared spatial evidence. Inspector: observation details, candidates, status, provenance, and errors. Rail: observation intervals, item navigation, and time.                                                                                                       |
| Round analysis            | Select an exact analysis and evidence row; select a hypothesis; open evidence details; seek linked source frames; edit counterfactual observation/card exclusions, identity overrides, and candidate probabilities; run a counterfactual or restore baseline. Show reconstruction warnings, diagnostics, job state, and failures. Untimed inferred actions have no seek target. | Center: exact resolved source frame and valid evidence overlay. Inspector: hypothesis details, counterfactual controls/results, provenance, warnings, diagnostics, and errors. Rail: evidence/reconstruction rows, time cursor, and source-linked selection; untimed actions remain rows without seeking. |
| Comparison                | Select left run, right run, and completed reference; request a comparison; select a difference item; inspect exact source, matching policy, coverage, metrics, and identity crop link. Preserve comparison errors and empty results.                                                                                                                                            | Center: shared exact source frame. Inspector: selectors, summary, policy, metrics, failures, and crop details. Rail: difference-item selection and synchronized time.                                                                                                                                     |
| Shared workspace controls | Select exact processor input revisions and crop geometry input; choose model/provider; run or rerun processing; inspect progress, blockers, processor/analysis history, and diagnostics. The lineage drawer selects an exact node/revision or analysis, exposes sources/history, and offers copy/restore actions.                                                               | Inspector: run inputs, model/provider, execution action, progress, blockers, history, diagnostics. Top navigation/drawer: exact data selection, lineage, history, copy and restore. Rail: the single time cursor, scrubber, previous/next frame, and item selection.                                      |

Shared selection includes exact node and revision, item ID, requested time,
resolved frame identity, comparison side/reference, and analysis/hypothesis IDs.
Selection never falls back by list position, nearby time, or latest revision.
Step changes retain time and viewport where valid; an item clears only when
exact correspondence is absent, with the reason in the inspector. A comparison
is an optional view of a supported step, not a seventh processing step.

## Typed surface input contract

This is a design contract for M1–M7, not an application type or a changed API.
Keep the full source frame separate from the selected item, requested time, and
resolved frame. Make unavailable states explicit. Do not pass arbitrary text or
commands into the central geometry surface.

```ts
type SurfaceStep =
  | "events"
  | "visible_cards"
  | "virtual_scenes"
  | "visual_identities"
  | "table_observations"
  | "round_analyses";

type ExactNodeRevision = { nodeId: string; revisionId: string };
type FrameIdentity = {
  sourceId: string;
  frameId: string;
  width: number;
  height: number;
  contentSha256: string;
  requestedTimeUs: number | null;
  resolvedTimeUs: number | null;
};
type SurfaceFrame =
  | { state: "loading"; requestedTimeUs: number | null }
  | { state: "ready"; identity: FrameIdentity; imageUrl: string }
  | {
      state: "missing" | "failed";
      requestedTimeUs: number | null;
      reason: string;
    };
type SurfaceSelection = {
  node: ExactNodeRevision | null;
  itemId: string | null;
  analysisId: string | null;
  hypothesisRank: number | null;
};
type SurfaceInput = {
  step: SurfaceStep;
  frame: SurfaceFrame;
  selection: SurfaceSelection;
  overlays: readonly {
    id: string;
    frame: FrameIdentity;
    calibration: { revisionId: string; digest: string } | null;
    editable: boolean;
    geometry: unknown;
  }[];
};
```

The renderer draws an overlay only when source, frame identity, dimensions,
coordinate transform, and required calibration match the ready frame. A null or
mismatched calibration suppresses the overlay and disables geometry mutation.
An interval without a frame stays an interval. A representative frame is
allowed only when declared and identified as representative. Late frame/crop
responses cannot replace newer selection state. Historical content is
inspectable and read-only.

## Fixture and render coverage

| Required fixture             | Existing local evidence                                                                                                                                                                                                                                                                                                                                 |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Six processing steps         | `RecordingWorkspaceShell` renders all six navigation entries. `RecordingPipelineWorkspace.test.tsx` renders Events, Visible cards, Virtual scenes, Table observations, and Round analysis; `PipelineNodeVisualIdentityEditor.test.tsx` renders the identity editor with local fixtures. The 0108 Playwright regression checks local-fixture navigation. |
| Comparison                   | `RecordingPipelineWorkspace.test.tsx` renders the shared comparison slots; `ComparisonView.test.tsx` covers valid and failed responses and URL selection/history.                                                                                                                                                                                       |
| Empty and failed results     | `RecordingPipelineWorkspace.test.tsx` covers an empty Virtual scenes step and visible blockers/diagnostics. `ComparisonView.test.tsx` preserves selectors on failure. Observation and analysis components retain missing/failed messages.                                                                                                               |
| Historical/read-only content | `PipelineNodeVisibleCardEditor.test.tsx` checks historical read-only behavior; the virtual-scene editor also derives read-only state from exact head/revision equality.                                                                                                                                                                                 |
| Missing calibration          | `workingAreaFixtures.ts` defines a ready source frame with an overlay requiring calibration while `calibration` is null. The expected result is no overlay or edit affordance and an inspector explanation. The current scene editor assumes calibration is present; handling this case belongs to M4.                                                  |
| Interval-only evidence       | `workingAreaFixtures.ts` defines an interval with no source frame and expects no seek. `RecordingPipelineWorkspace.test.tsx` also selects an observation interval and synchronizes its exact item/time.                                                                                                                                                 |
| Untimed inferred actions     | `workingAreaFixtures.ts` defines an inferred play with no requested time or frame and expects a rail row without a seek.                                                                                                                                                                                                                                |

Relevant component tests are `RecordingPipelineWorkspace.test.tsx`,
`PipelineObservationWorkbench.test.tsx`, `PipelineNodeVirtualSceneEditor.test.tsx`,
`PipelineNodeVisibleCardEditor.test.tsx`, `AnalysisTimelinePresentation.test.tsx`,
and `ComparisonView.test.tsx`. The browser fixture is
`web/tests/e2e/pipeline-lineage-workspace.spec.ts`.
Contract-only cases are asserted by `workingAreaFixtures.test.ts`; they specify
future behavior and do not claim that the current components support it.

## Rendered layout examples

Desktop example: at 1440 px, the top row retains all six aligned step columns;
the main workspace uses the existing center/inspector/rail slots. The center
keeps source aspect ratio. Selection, progress, controls, and errors are outside
the image.

Narrow example: at 390 px, the step row scrolls horizontally and the inspector
and rail reflow below the source surface. Expanded crop/details remain in the
inspector flow and do not cover the image. These examples describe existing
CSS breakpoints and the target contract; the 0108 browser test did not record a
full six-step screenshot sweep at these sizes.

## Limits and next work

No application behavior changed in M0. Existing components still render video
elements and central text/actions in several steps. The missing-calibration
fixture is specified but not accepted as current behavior. M1 extracts the
geometry surface; later milestones connect each step and move its functions to
the agreed slots. The 0107 and 0108 dependencies are complete.

## Execution handoff

- Completed: M0, freeze layout, inventory, typed contract, and fixture matrix.
- Changes: this report and test-only fixtures; epic and board updated to Ready; inbound links repaired after the epic move; no application behavior changed.
- Checks: `npm run check` passed (typecheck, lint, format, generated API comparison, 182 Vitest tests); `npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts` passed; local Markdown links passed. New epic/report formatting passed. The broad Markdown Prettier check warns on the board and three inbound documents at HEAD; the baseline also warns, so those existing styles remain intact.
- Decisions: preserve every current function; source selection remains 0108-owned; calibration mismatch blocks overlay edits; untimed evidence does not seek.
- Limits: no usability study or full six-step screenshot sweep; missing-calibration behavior remains future work.
- Next: M1, extract the common geometry surface.
- Run: requested 11 milestones, completed 1, remaining 10.
