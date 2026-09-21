# Production proposed card scenes and calibration refinement

## Plan status

- **Summary:** Create proposed card scenes from a selected local visible-card result, review cards
  in a source or rectified table view, and refine the recording-wide table-plane calibration with
  explicit operator-confirmed anchors.
- **Status:** In Progress
- **Depends on:** Completed 0048 pipeline data and execution, completed 0049 recording pipeline
  review, completed 0072 pose-based visible-card review, and the selectable cascade provider from
  0071 M6
- **Outcome:** An operator can create proposed card scenes from a real cascade result, correct them
  with the existing maintained-reference workflow, preview a calibration refinement across the
  recording, and apply it without silently changing reviewed history.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — proposal, anchor, calibration-preview, and draft-reflow contracts are frozen
  and covered by deterministic contract and pipeline-data tests.
- **M1:** Not started — publish proposed card scenes from one selected local generated result.
- **M2:** Not started — seed and validate a maintained reference from proposed card scenes.
- **M3:** Not started — add proposal controls and the source/rectified editor toggle.
- **M4:** Not started — add the card and calibration-anchor manipulation handles.
- **M5:** Not started — implement weighted calibration refinement and a recording-wide preview.
- **M6:** Not started — apply a calibration revision and reflow the maintained draft safely.
- **M7:** Not started — verify the complete real-result review loop and operator guidance.

## 1. Problem

The pose editor, scene geometry, calibration solver, and maintained-reference command path exist.
The application does not connect them for real processor results. A generated cascade result has
visible-region polygons but no proposed card scene. The virtual-table editor appears only when a
visible-card item already contains a `card_scene` envelope. Current scene-bearing data exists only
in the 0072 end-to-end fixture.

The missing production path is:

```text
selected local visible-card revision
  -> recording-wide table-plane calibration
  -> proposed card scenes
  -> maintained-reference review
  -> reviewed card scenes and derived visible regions
```

Calibration refinement adds a second concern. A card pose and a table-plane calibration can both
change a projected card outline. One pointer gesture must not change both without making that
choice explicit. The editor therefore separates card review from calibration refinement.

## 2. Authority and revision model

Keep these authorities separate:

1. The selected detector data revision stays immutable. Its polygons, scores, model identity, and
   source-frame lineage remain the original suggestions.
2. A proposal processor run creates one immutable table-plane calibration revision and one
   proposed card scene for each supported source frame. A proposed card scene is not reviewed
   evidence.
3. The maintained visible-card reference owns operator decisions. Accepting or correcting a
   proposed card scene creates a reviewed card scene and the backend derives its visible regions.
4. A calibration refinement stays in a mutable calibration draft until the operator applies it.
   Apply creates a new immutable calibration revision. It never changes an earlier calibration,
   generated data revision, or completed maintained-reference revision.

Split the current editor envelope into explicit proposal and reviewed values. Do not use a
`ReviewedCardScene` value as the authority for a pending processor proposal. Preserve exact
lineage from each reviewed scene to the proposal, detector revision, calibration revision, source
frame, initializer recipe, and fit diagnostics.

The mutable draft also records one review state for each proposed card: pending, accepted,
adjusted, or rejected. A frame is ready for acceptance only after the operator resolves every
proposed card and any manually added card. The final reviewed card scene does not retain rejected
cards or treat the draft review states as geometry.

One maintained-reference draft selects one active table-plane calibration revision. Completed
references can continue to cite older revisions.

## 3. Workspace flow

### 3.1 Create proposals

For a selected local visible-card result, show **Create proposed card scenes** beside the existing
visible-card run controls. The action starts one resumable processor run. It:

1. mines eligible complete-card evidence across the stable recording;
2. fits and validates one recording-wide table-plane calibration;
3. initializes card poses and card stacking order for each supported frame; and
4. publishes the calibration and proposed card scenes with diagnostics.

Show queued, running, complete, partial, and failed states in the existing run presentation. A
calibration failure is actionable and distinct from a frame that cannot initialize. A partial run
can retain supported proposed scenes, but unsupported frames remain explicit and cannot appear as
empty reviewed frames.

After completion, **Start review** seeds the maintained reference from the proposed scenes. The
selected detector result remains available as the immutable suggestion source.

### 3.2 Source and rectified views

Use one editor surface with a persistent two-way toggle:

- **Source** shows the exact source frame, dim detector polygons, projected full-card outlines,
  derived visible regions, and calibration-anchor diagnostics.
- **Rectified table** shows the same selected cards in the top-down table coordinate system.

Keep card selection, zoom target, active tool, undo state, and pending-save state synchronized when
the operator changes views. Switching views never changes geometry.

Use the rectified table as the default when a proposed card scene is available. Keep Source one
click away because it is the evidence view and the only place where the operator can verify that a
projected outline follows the recorded card.

### 3.3 Two explicit editing modes

The editor has two modes:

- **Review cards** changes card count, center, rotation, and card stacking order for the selected
  frame. These edits do not change the table-plane calibration.
- **Refine mapping** changes calibration anchors and computes a candidate table-plane calibration.
  These edits can affect proposed cards in other frames.

Show the active mode next to the Source/Rectified toggle. Use different handle colors and pointer
cursors. Entering Refine mapping shows a short warning that changes have recording-wide scope.
The operator can leave the mode without applying the candidate calibration.

## 4. Card manipulation

In Review cards mode, the selected card has:

- a body drag for translation in the rectified table plane;
- one handle centered beyond the card's top edge for rotation;
- keyboard and numeric controls for precise center and angle changes;
- existing add, remove, restore, and card-stacking-order controls; and
- a visible source-frame projection that updates during the gesture.

Card dimensions remain shared calibration values. The operator cannot save a wider, narrower,
longer, skewed, or non-rectangular individual card.

In Refine mapping mode, an eligible complete card shows four corner handles. A corner edit changes
the card's calibration-anchor observation, not its stored card dimensions. Support three explicit
constraint choices in a small handle toolbar and through keyboard shortcuts:

- **Diagonal:** move along the card-local diagonal and preserve the canonical aspect ratio.
- **Card X:** constrain the gesture to the card's local long axis.
- **Card Y:** constrain the gesture to the card's local short axis.

Show the handles in both views. Source is the primary alignment view. A gesture in Rectified table
is mapped through the current calibration and shows the corresponding source-frame ghost before
commit.

The coupled corners move deterministically so the temporary anchor remains rectangular and keeps
the canonical card aspect ratio. M0 must freeze the opposite-corner rule, modifier keys, minimum
size, snapping tolerance, and keyboard equivalent before implementation. Pointer movement updates
only a local preview. Pointer release writes one ordered anchor command.

## 5. Calibration evidence and weighting

Each eligible complete-card observation has one calibration state:

- **Candidate:** automatic evidence from the selected detector revision;
- **Accepted anchor:** an operator accepted the card without changing its anchor geometry;
- **Adjusted anchor:** an operator corrected its anchor geometry;
- **Pinned anchor:** an operator requires the robust fit to retain the anchor as an inlier; or
- **Excluded:** the observation cannot influence calibration.

Only complete cards with four defensible corners can become anchors. A clipped, partly occluded,
blurred, or ambiguous card can still be reviewed as a visible card but cannot silently constrain
the calibration. Show the eligibility reason beside the anchor control.

Use a deterministic robust fit with bounded influence:

- automatic candidates have base weight `1`;
- accepted anchors have base weight `4`;
- adjusted anchors have base weight `12`;
- excluded observations have weight `0`; and
- pinned anchors use their normal weight but cannot be discarded as outliers.

Apply temporal and spatial de-duplication before weighting. Cap each source frame and table region's
total contribution so repeated detections of one stationary card cannot dominate the fit. Conflicting
pinned anchors block the candidate calibration and identify the anchors that need attention.

Accepting a card promotes it to an accepted anchor only when it is eligible. Correcting its corner
geometry promotes it to an adjusted anchor. Rejection excludes it. Undo restores the preceding
state and fit inputs.

## 6. Calibration preview and draft reflow

Recompute a candidate calibration after a completed anchor gesture or anchor-state change. Do not
run the recording-wide fit on every pointer-move event.

Before apply, show:

- the current and candidate projected outlines as distinct solid and ghost overlays;
- fit residual, accepted-anchor count, rejected-candidate count, and held-out alignment change;
- the number of draft frames and cards that would change;
- the largest source-pixel displacement and links to the most affected frames; and
- an explicit pass or blocked result for every calibration gate.

The Timeline Rail marks frames changed by the preview. In each affected frame:

- unreviewed proposed cards are reinitialized from the immutable detector suggestions under the
  candidate calibration;
- accepted or corrected cards retain their source-frame intent by fitting a new card pose under the
  candidate calibration;
- calibration anchors retain their operator-confirmed source geometry; and
- any retained card that exceeds the frozen displacement or residual tolerance becomes
  **affected** and requires another operator confirmation.

Preview reflow is reversible and local to the draft. **Discard preview** restores the current
calibration and all draft poses. **Apply calibration** performs one atomic backend operation that:

1. stores the new immutable calibration revision;
2. rebases the complete maintained-reference draft;
3. regenerates the unreviewed proposed scenes and fit diagnostics;
4. marks affected reviewed items without accepting them; and
5. records the source calibration, anchor commands, proposal revision, and reflow receipt.

If any write or validation fails, keep the current calibration and draft unchanged. Existing
completed references, downstream data revisions, datasets, and processor runs remain immutable.

## 7. Failure and recovery behavior

- A recording with camera movement, zoom, stabilization drift, resolution changes, or more than one
  table setup fails calibration. Tell the operator to split the recording scope; do not fit one
  plausible compromise.
- A frame with no initialized poses stays unsupported. The operator can add a card only after a
  valid recording calibration exists, or mark the frame unusable.
- A stale detector revision, calibration revision, or source-frame digest blocks proposal creation
  and apply.
- Network retry, duplicate commands, revision conflict, reload, and navigation use the existing
  ordered maintained-reference behavior. A reload restores the calibration draft and preview.
- The operator can freeze the current calibration revision and continue card review without an
  unapplied candidate calibration.

## 8. Fixed scope

This epic includes:

- production proposal creation from the selected local segmentation or cascade provider;
- immutable calibration and proposed-scene revisions with complete lineage;
- the Source/Rectified table toggle and Review cards/Refine mapping modes;
- body, rotation, and constrained calibration-corner handles;
- operator-confirmed calibration anchors and deterministic bounded weighting;
- recording-wide calibration preview, affected-frame navigation, apply, discard, and recovery;
- maintained-reference integration and reviewed visible-region derivation; and
- local automated and bounded operator verification.

This epic excludes:

- per-card stored dimensions or free-form card quadrilaterals;
- manual camera intrinsics, lens correction, a 3D camera model, or per-frame homographies;
- support for camera movement or several table setups inside one calibration scope;
- model retraining, provider promotion, or default-provider changes;
- automatic acceptance of proposed card scenes;
- changes to visual card identity, table observation, or game reconstruction semantics; and
- rewriting completed revisions or closed epic 0072.

## 9. Delivery milestones

### M0 — Freeze proposal and calibration-refinement contracts

- Add versioned proposed-card-scene, calibration-draft, anchor-command, preview, and reflow-receipt
  contracts.
- Separate processor proposals from reviewed card-scene authority in pipeline data.
- Define per-card pending, accepted, adjusted, and rejected draft states plus frame-completion rules.
- Freeze anchor eligibility, weights, de-duplication caps, handle constraint mathematics,
  calibration gates, displacement tolerances, failure states, and revision invalidation rules.
- Add deterministic fixtures for accepted, adjusted, pinned, excluded, repeated, conflicting, and
  stale anchor evidence.

Acceptance:

- no pending processor proposal can pass as a reviewed card scene;
- the same inputs and ordered commands produce byte-equivalent calibration and preview results;
- conflicting pins and invalid source lineage fail with actionable diagnostics; and
- the contracts state exactly which draft items reinitialize, rebase, or become affected.

#### M0 implementation evidence — 2026-09-21

- Added strict versioned contracts for proposed card scenes, reviewed scene records, card-scene
  drafts, calibration drafts, anchor observations and commands, calibration previews, calibration
  failures, and atomic reflow receipts.
- Separated processor proposal lineage from reviewed scene authority in visible-card pipeline data.
  Pending, accepted, adjusted, and rejected card states now have explicit frame-completion rules;
  rejected cards cannot enter a reviewed scene.
- Froze accepted, adjusted, and pinned anchor weights (`1`, `4`, and `12` by weight class), the
  temporal and table-region de-duplication buckets, per-frame and per-region contribution caps,
  pin-conflict tolerance, handle modifier and keyboard policies, minimum handle size, calibration
  gates, displacement tolerances, failure codes, and revision invalidation rules.
- Added deterministic fixtures for accepted, adjusted, pinned, excluded, repeated, conflicting,
  and stale anchor evidence. Ordered commands, preview values, and reflow receipts round-trip to
  byte-equivalent digests.
- Verification passed for the full table-evidence-analyzer suite (217 passed, 3 skipped), focused
  backend pipeline-reference and pose-review suites, and focused operations geometry, calibration,
  initialization, and lint checks.

### M1 — Publish proposed card scenes from a real generated result

- Add a resumable proposal processor that consumes one selected local visible-card revision.
- Reuse the 0072 calibration and scene initialization implementations.
- Store one immutable calibration revision, per-frame proposed scenes, unsupported-frame results,
  fit diagnostics, and complete detector and source lineage.
- Expose run creation, status, retry, and result reads through the backend API.

Acceptance:

- a real cascade result can produce loadable proposed card scenes without fixture injection;
- rerunning identical inputs reuses or reproduces the same immutable outputs;
- partial and failed results never turn unsupported frames into empty scenes; and
- generated detector data remains unchanged.

### M2 — Seed maintained-reference review from proposals

- Seed a visible-card maintained reference from a completed proposal result.
- Preserve the immutable proposed scene beside the mutable reviewed draft value.
- Convert a proposal into a reviewed card scene only through an explicit accept or correction.
- Add selected-card acceptance and rejection while retaining frame-level review completion.
- Validate scene derivation, completion coverage, conflict recovery, and downstream impact against
  the selected calibration revision.

Acceptance:

- starting review retains proposal, detector, calibration, and source-frame lineage;
- pending proposals are not dataset-eligible;
- accepting or correcting one scene derives its visible regions on the backend; and
- reload and revision conflicts do not duplicate or lose scene commands.

### M3 — Add proposal controls and synchronized view toggle

- Add Create proposed card scenes, run status, diagnostics, retry, and Start review controls to the
  visible-card workspace.
- Add the Source/Rectified table toggle to the existing pose editor.
- Show selected-card review state and Accept card, Reject card, and resolve-remaining actions.
- Keep selection, overlays, view state, Timeline Rail navigation, and inspector context synchronized.
- Show unsupported frames and calibration failures with direct recovery guidance.

Acceptance:

- an operator can go from a selected cascade result to the first proposed scene without using a
  command line or editing JSON;
- view switching never changes stored geometry;
- both views distinguish detector suggestions, proposals, reviewed geometry, and derived regions;
  and
- desktop and narrow layouts remain usable by pointer and keyboard.

### M4 — Add card and calibration-anchor handles

- Keep body translation and add the top rotation handle in Review cards mode.
- Add constrained corner handles and Diagonal/Card X/Card Y choices in Refine mapping mode.
- Add numeric and keyboard equivalents, focus behavior, pointer capture, cancel, and one-command-per-
  gesture semantics.
- Show local source and rectified previews during each gesture.

Acceptance:

- a card can move and rotate without changing calibration;
- a corner gesture creates an anchor edit without storing per-card size or skew;
- every constraint mode preserves the canonical aspect ratio deterministically; and
- cancel, Escape, lost pointer capture, and reload cannot save a partial gesture.

### M5 — Compute and inspect candidate calibration

- Implement anchor eligibility, weighting, de-duplication, bounded contribution, robust fitting, and
  pinned-inlier rules.
- Persist the calibration draft and ordered anchor commands.
- Compute the recording-wide candidate preview after completed commands.
- Show fit gates, before/after overlays, affected counts, maximum displacement, and links to the most
  affected frames.

Acceptance:

- accepting eligible cards measurably changes their declared fit influence;
- repeated views of one card cannot dominate the calibration;
- adjusted and pinned anchors behave as declared, and conflicting pins block apply; and
- discard restores the current calibration and draft byte-for-byte.

### M6 — Apply calibration and reflow the draft

- Add the atomic calibration-apply backend operation and reflow receipt.
- Reinitialize unreviewed proposed cards and refit accepted or corrected card poses under the new
  calibration.
- Preserve anchor geometry, mark tolerance failures as affected, and keep completed revisions
  immutable.
- Integrate apply with autosave, retry, duplicate-command handling, conflict recovery, and reload.

Acceptance:

- applying a calibration creates a new revision and never mutates an old one;
- unreviewed cards update visibly across the Timeline Rail;
- reviewed cards never change silently and require confirmation when a tolerance gate fails; and
- an interrupted or rejected apply leaves the selected calibration and maintained draft unchanged.

### M7 — Verify the production review loop

- Run the complete flow on the retained real cascade result and a small stable-camera recording.
- Cover isolated, distant, overlapping, clipped, rejected, manually adjusted, and conflicting-anchor
  cases.
- Record proposal runtime, calibration gates, anchor states, affected-frame counts, operator actions,
  and final review coverage.
- Publish concise in-product guidance for view modes, handles, anchor eligibility, preview, apply,
  discard, and failure recovery.

Acceptance:

- an operator completes a bounded real review without fixture injection or manual JSON changes;
- the final reviewed scenes and derived regions retain complete source and revision lineage;
- unsupported recording or frame conditions fail explicitly; and
- backend, web, contract, persistence, accessibility, type, lint, formatting, build, and focused
  browser checks pass.

## 10. Verification strategy

Use fixture polygons and recorded local results for the normal development loop. Do not require
cloud services, phones, or new recordings.

Automated verification must cover:

- deterministic calibration, proposal, preview, and reflow digests;
- proposal-versus-reviewed authority and dataset rejection;
- anchor eligibility, relative weight, de-duplication, caps, pins, and conflicts;
- source/rectified coordinate parity for all handle modes;
- draft apply atomicity, retry, conflict, reload, undo, and immutable history;
- responsive pointer and keyboard editor behavior; and
- the existing visible-card, comparison, identity-crop, and dataset consumers.
