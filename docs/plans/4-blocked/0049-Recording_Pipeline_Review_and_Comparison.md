# Recording pipeline review and comparison

## Plan status

- **Summary:** Make the recording workspace show selected generated results and one maintained
  reference per stage, with simple run, review, and comparison controls.
- **Status:** Blocked
- **Depends on:** 0048 complete
- **Blocker:** The shared run, data revision, reference, coverage, and dataset contracts in 0048
  must exist before the editors switch to them.
- **Builds on:** Completed 0039, 0040, 0042, and 0045 editors; 0033 analysis diagnostics
- **Supersedes:** The recording UI direction of 0047
- **Outcome:** An operator can run the pipeline on generated or reviewed inputs, maintain one
  reference, and compare retained results without managing review batches or evidence packages.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — add recording stage summaries and result/input selection.
- **M1:** Not started — switch event review to the maintained reference.
- **M2:** Not started — switch visible-card review to the maintained reference.
- **M3:** Not started — switch identity review to the maintained reference.
- **M4:** Not started — add run controls and observation/analysis navigation.
- **M5:** Not started — compare retained results against the same reference.
- **M6:** Not started — finish the local workflow and remove obsolete review routes.

## 1. Experience

Keep the recording as the stable owner. Use the existing video player, timeline, polygon editor,
identity controls, keyboard shortcuts, and optimistic ordered save queue. Each visual review stage
has two primary selections: **Generated** and **Reviewed**. Generated shows the selected run result;
Reviewed shows the maintained reference and clearly identifies draft work. These are selections,
not a two-result storage limit.

The default next action is visible beside stage progress: Run, Review, Continue review, or Compare.
Put other runs and completed reference revisions behind secondary controls. Use stable
recording-owned routes for editing. Keep selected item and playback position through reload.
Do not ask the operator to name a review or choose among several human reference branches.

Always display the input used by a result, such as "Used reviewed events" or "Used generated visible
cards". Default a new run to a completed reviewed input when available, otherwise the selected
generated input. Show draft or coverage warnings before the choice. Do not silently change an
explicit selection. Resolve the exact input revision at run creation through 0048.

If an older result used an earlier reference, show that fact without labeling the result invalid.
If the maintained reference needs work on changed evidence, show the affected count and a direct
review action. A model rerun must not discard human work or create a second maintained reference.

## 2. Review behavior

Use a generated result as suggestions over the maintained reference. Accept, correct, reject, and
add change the draft only. New suggestions do not overwrite reviewed items. A rejected suggestion
remains in its original run result, but need not remain a prominent row in the normal review UI.
Completion publishes a new reference revision. Further corrections continue the same reference.

Event completion includes a full-video pass so missed events can be added. Visible-card completion
records the actual frames inspected, including reviewed empty and unusable frames. Identity review
records usable labels and unresolved source problems. Upstream corrections show affected work and
preserve unchanged items. Show incomplete coverage separately from a processor failure.

Keep the fast controls and save guarantees from 0045. Keep the visible-region semantics from 0040
and the identity controls from 0042. Do not add geometry editing to the identity editor. Link source
problems back to the relevant frame and visible-region editor.

Analysis initially uses the existing read-only timeline and counterfactual capabilities. Full
reconstruction correction stays in 0026; this epic does not invent a reviewed gameplay state by
editing visual observations.

## 3. Comparison

Allow selection of two retained runs and an explicit completed reference revision. Default to runs
on identical input revisions. Distinguish changing the processor from changing its inputs. A
comparison using generated versus reviewed upstream input is an upstream-error experiment.

Use existing matching and evaluation functions where possible. Match events by the declared event
type/timing rule; match visible-card results on the same video frame by declared geometry overlap;
compare identity candidates against the same reviewed card identity. Store or display the matching
policy and scope. Never match items merely because their IDs happen to be equal across runs.

Show additions, misses, disagreements, false detections, and failures with source video context.
Missing reference coverage is "Not reviewed", not a false detection or negative label. Different
frame selections must show the common covered scope and unmatched coverage separately. Do not claim
paired model quality for two runs on different evidence. Comparison never changes the reference.

The first UI provides inspection and existing metrics. Formal candidate gates and promotion remain
in 0043, 0044, and 0050. Do not add free-form training configuration or a pipeline graph editor.

## 4. Delivery milestones

### M0 — Stage summaries

Add recording-owned stage summaries and generated/reviewed selectors using 0048 APIs. Show current
input, progress, failures, reference coverage, and the next action. Keep history secondary.

Acceptance: a video-only recording shows all stages without package blockers; empty, running,
failed, generated-only, draft, and completed states render; reload preserves selection; generated
OpenAPI types and component checks pass.

### M1 — Event reference editor

Connect the existing timeline and event commands to the recording's maintained reference. Replace
review creation/list navigation with Review or Continue review. Preserve source-linked suggestions.

Acceptance: keyboard and pointer tests add a missed event, correct a generated event, reject a
suggestion, complete coverage, and continue editing; delayed saves and conflicts preserve commands;
a rerun does not replace the reference. Existing 0045 responsiveness checks remain satisfied.

### M2 — Visible-card reference editor

Connect frame navigation, proposal overlays, polygon editing, and frame outcomes to selected
results and the maintained visible-card reference. Use the video-derived media API.

Acceptance: accept, reshape, remove, add, reviewed-empty, and unusable flows work without a batch
creation step; changing detector selection leaves reviewed geometry intact; a changed event frame
shows missing coverage and preserves unchanged frame work.

### M3 — Identity reference editor

Connect crop review and source context to selected identity results and the maintained identity
reference. Preserve the existing suit/rank controls, usability decisions, and source-problem links.

Acceptance: a missing prediction remains manually labelable; a geometry change shows affected
identity work; unchanged cards retain review; crop retrieval after cache deletion works; completion
and dataset readiness reflect exact covered references.

### M4 — Run and analysis controls

Add bounded run start/status/retry controls for existing configured processors. Offer generated or
reviewed upstream inputs explicitly. Connect selected observations to recording analysis and the
existing diagnostic timeline. Keep configuration details in a secondary panel.

Acceptance: an operator runs detection on both event origins, classification on both geometry
origins, and reconstruction on a selected observation revision; each result displays its actual
inputs; page reload resumes status; missing video fails without package fallback.

### M5 — Compare results

Add two-run comparison with one selected reference revision, source playback, matching policy,
and explicit uncovered cases. Reuse existing event, geometry, and identity comparison functions.

Acceptance: fixtures show matching, missing, extra, changed, failed, and unreviewed items; different
frame coverage is not scored as reviewed truth; changing the reference selection changes only the
comparison; original run results and reference revisions remain unchanged.

### M6 — Workflow proof and cleanup

Exercise one fixture recording from video through review, reruns, comparison, analysis, and dataset
readiness. Remove obsolete review-batch creation routes, duplicate current-state ownership, and
package update controls from this workflow. Retain the app's packaging/upload showcase. Old closed
epics remain historical; do not add compatibility layers or data migrations by default.

Acceptance: browser tests cover fresh video, manual review, generated suggestions, reruns, upstream
correction, cold caches, failed jobs, reload, and save conflicts; relevant frontend/backend tests,
types, formatting, and local link checks pass. Record one bounded real operator exercise when local
recordings are available; report data gaps without making a quality claim. A missing real corpus
is not a reason to leave the fixture-proven implementation open indefinitely.

## 5. Handoff

After M6, mark this epic complete and reassess 0043 and 0050 using the measured data coverage. Start
neither merely because this UI is complete. 0044 remains blocked until 0043 locks a passing candidate.
