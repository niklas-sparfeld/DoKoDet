# Auto-accept identities

## Plan status

- **Summary:** Let an operator accept Gemini visual card identity suggestions when the latest
  comparable local identity result agrees, and navigate unfinished review work with Cmd+Left and
  Cmd+Right.
- **Status:** Closed
- **Closure reason:** Complete
- **Depends on:** Plans 0043 and 0049 complete
- **Builds on:** Plans 0041, 0042, 0043, 0048, 0049, 0059, and 0062
- **Outcome:** An operator can use one explicit auto-approve action in reviewed visual identity
  work. It uses retained Gemini and local visual identity outcomes for the same card, runs the
  configured local identity processor when no comparable local result exists, and accepts only
  matching Gemini suggestions. Every review editor supports Cmd+Left and Cmd+Right to move to the
  previous or next item that still needs review.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — retained Gemini/local comparison selects matching frozen visible-card and
  crop lineage, reuses one deterministic local run, accepts only eligible pending items through a
  revision-guarded command, and persists an immutable comparison receipt across restart.
- **M1:** Complete — reviewed identity work can plan, monitor, and apply guarded matching
  Gemini/local decisions, with result lineage and reason counts visible to the operator.
- **M2:** Complete — Cmd+Left and Cmd+Right move to the nearest unfinished item in reviewed
  CardEvent, visible-card, and visual identity work. The shortcut does not wrap and ignores text,
  selection, and timeline controls.

## 1. Purpose

Visual card identity review already retains generated processor results and uses explicit human
acceptance. Gemini suggestions that agree with the local identity model are useful, but the
operator must now compare them manually. Add one review-mode action that makes this comparison
explicit and accepts only the safe intersection.

The action is an operator command. It does not change model selection, promote a local bundle, or
turn a local result into a human label by itself. A mismatch, an abstention, a face-down result, a
processor failure, or missing comparable evidence remains to be reviewed.

Review editors also need one fast way to return to unfinished work. Use the Mac shortcut stated in
this epic. Do not replace the existing unmodified arrow navigation or Alt+Arrow timeline seeking.

## 2. Scope

This epic includes:

- an explicit comparison of the latest retained Gemini and local visual identity outcomes for each
  reviewed visual identity item;
- an idempotent request that starts or reuses a local visual identity processor run when the chosen
  Gemini result has no comparable local result;
- one review-mode **Auto-approve** button that accepts each eligible matching Gemini suggestion;
- clear counts and item-level reasons for accepted, mismatched, unavailable, abstained,
  face-down, and failed outcomes; and
- Cmd+Left and Cmd+Right navigation among items that still need review in the event, visible-card,
  and visual identity review editors.

This epic does not include:

- automatic model promotion, a local-default change, or a Gemini fallback;
- acceptance of a local-only outcome, a non-Gemini suggestion, or a different visual card identity;
- batch changes to completed data revisions;
- a new maintained reference, review lifecycle, or processor-result store;
- new model training, quality gates, or local classifier selection; or
- changes to geometry, visible-card ignore regions, card-side semantics, or reconstruction.

## 3. Fixed decisions

1. **Auto-approve** is available only in the Reviewed visual identity editor with an editable
   maintained-reference draft. It acts on the current draft items and saves through the existing
   ordered, revision-guarded command queue.
2. A Gemini result and a local result are comparable only when they classify the same source visual
   card, use the same frozen visible-card input revision and crop policy, and have valid retained
   lineage. Run-local item IDs alone are not sufficient.
3. For every target item, select the latest completed retained Gemini result and the latest
   completed retained local result that are comparable under rule 2. Define "latest" by completed
   timestamp, with opaque result ID as the deterministic tie-breaker. Record both selected result
   IDs and model provenance in the response and resulting review command receipt.
4. When a Gemini result has no comparable local result, the action must start or reuse one local
   visual identity run with the exact Gemini input revision and the configured local identity
   classifier. Reuse an in-progress or completed run with the same frozen request. Do not issue one
   local run per card.
5. The action accepts an item only when all conditions hold: the draft item is still pending; the
   Gemini outcome is `classified` with one suggested visual card identity; the comparable local
   outcome is `classified` with the same top visual card identity; and neither outcome is stale,
   failed, unusable, or face-down. The accepted human decision preserves the existing Gemini
   suggestion path and records the comparison provenance.
6. A mismatch or non-classified outcome changes nothing. It has an explicit reason in the result so
   the operator can review it manually. A completed local run can be compared again without another
   run.
7. The request is idempotent. A retry after a conflict, reload, or partial local run must not accept
   a changed item, duplicate a local run, or overwrite a human decision. Refresh the maintained
   reference and report the current counts after conflict recovery.
8. In each review editor, Cmd+Right selects the next item that still needs review and Cmd+Left
   selects the previous one. The stage owner defines its existing unfinished state; in visual
   identity review it is `pending`. Do not wrap at either end. If nothing is selected, choose the
   first or last unfinished item in the requested direction.
9. Keyboard handlers ignore editable controls and timeline seeking controls. Keep existing plain
   Arrow and Alt+Arrow behavior. The shortcut must use `metaKey`, so it is Cmd on macOS; do not
   assign Ctrl+Arrow as an undocumented second shortcut.

## 4. Delivery milestones

### M0 — Compare retained identity results and run local work when needed

- Add strict request and response contracts for auto-approval planning, local-run state, selected
  result lineage, and per-item eligibility reason.
- Add a recording-pipeline service operation that resolves comparable retained Gemini and local
  results against the exact visual identity input revision.
- Reuse existing visual identity run creation, request identity, persistence, and retry behavior to
  start or reuse one configured local run when required.
- Add a revision-guarded reference operation or command metadata needed to retain Gemini/local
  comparison provenance with accepted decisions.

Acceptance:

- fixtures prove that equal classified Gemini and local outcomes for one source card are eligible;
- different top identities, different crop or input lineage, face-down, unusable, failed, and
  missing outcomes are not eligible and return distinct reasons;
- one invocation starts at most one local run for one exact frozen request, and retries reuse it;
- a completed compatible local run is reused without execution;
- stale drafts and concurrent human decisions cannot be overwritten; and
- API and persisted artifacts validate after restart.

### M1 — Add reviewed visual identity auto-approval

- Add **Auto-approve** to the reviewed visual identity controls, with disabled and progress states.
- Show the local-run state while it is pending. When it completes, refresh the comparison and offer
  the resulting eligible decisions without a page reload.
- Submit only eligible accept commands through the existing ordered save queue, then report the
  accepted count and the count for every non-accept reason.
- Keep the item selection, current draft, source crop, and normal manual actions usable throughout.

Acceptance:

- the button is absent from generated view and unavailable without an editable maintained draft;
- an eligible matching Gemini/local pair becomes an accepted human decision with both result
  lineages visible in diagnostics;
- unmatched and non-classified pairs remain pending and are selectable for manual review;
- local-run, API, save, conflict, and retry failures give an actionable message and preserve the
  draft; and
- focused frontend, backend, generated-client, and browser tests cover the full flow at desktop and
  narrow widths.

### M2 — Navigate unfinished review work with Cmd+Arrow

- Extract or add small stage-local unfinished-item selectors for the CardEvent, visible-card, and
  visual identity editors.
- Add Cmd+Left and Cmd+Right handling to each editor without changing its current plain Arrow,
  Alt+Arrow, edit-mode, focus, or media controls.
- Make selection, URL state, rail state, and accessible selected-item indication update through the
  existing editor navigation paths.

Acceptance:

- each editor moves in the requested direction to the nearest unfinished item and does not wrap;
- reviewed, rejected, empty, unusable, source-problem, or otherwise completed items are skipped as
  defined by that editor's existing review state;
- no movement occurs when no unfinished item exists in that direction;
- text entry, select controls, polygon editing, and timeline seeking keep their current keyboard
  behavior; and
- focused component and browser tests cover forward, backward, boundaries, focus guards, and the
  existing keyboard shortcuts.

## 5. Verification

For each milestone, run the relevant backend unit and API tests, frontend component tests,
generated-client validation, and formatter, linter, and type checks. M0 also requires restart and
idempotency coverage. M1 and M2 require desktop and narrow browser coverage with keyboard use.
Use fixtures and local classifier fakes for normal verification. A real Gemini request or a real
local model run is not required for the development loop.
