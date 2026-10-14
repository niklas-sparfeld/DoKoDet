# Reviewed virtual-card corpus

## Plan status

- **Summary:** Publish a detection-only handoff from current reviewed geometry, then finish proposal
  refresh and geometry review. Complete visual identity review last.
- **Status:** In Progress
- **Depends on:** Completed 0073, 0074, and 0085; existing local detector provider. Pile annotation
  uses 0091 M0–M1; individual-card review can continue before that handoff. M5 uses 0093 M2
  prediction-independent annotation and M3 all-class readiness reporting; M4 does not wait for them.
- **Outcome:** A recording inventory, completed maintained references, and a reproducible data
  handoff for separate RF-DETR and DINO campaigns.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete (2026-10-11) — inventory all accepted recordings, reconcile frozen partitions,
  exclude protected sources, and select the `IMG_0095` pilot.
- **M1:** Complete (2026-10-11) — generate current proposals for all 53 `IMG_0095` event frames.
- **M2:** Complete (2026-10-13) — audit completed references and publish the digest-backed
  detection-only handoff for 0087. Three references qualify; all other candidate gaps are recorded.
- **M3:** Complete (2026-10-13) — audit terminal receipts for the frozen 22-recording proposal
  refresh. Twenty recordings published current proposals; two retain explicit calibration failures.
- **M4:** Complete (2026-10-14) — 20 current-schema references qualify. `IMG_0092` is permanently
  excluded; `IMG_0096` is deferred for calibration repair. The active scope has no review gaps.
- **M5:** Not started — use 0093 to complete all-class visual review, including FACE_DOWN, and
  publish the separate 0088 handoff.

## 1. Current evidence and scope

### M0 inventory snapshot — 2026-10-11

The read-only inventory is [versioned manifest 1](../../reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json).
It found 52 complete accepted recordings and 58 proposed-card-scene runs across 36 recordings. It
reconciles the frozen CardEventNet, 0068 RF-DETR, and 0043 DINO splits. The source-group check found
no partition conflicts. The inventory has 22 candidate development recordings. It excludes five
system holdout recordings, three RF-DETR sealed-test recordings, and five legacy-device diagnostic
recordings. It defers 17 recordings, including eight assigned to a validation partition and nine
without a development assignment or event scope.

The report counts completed event, visible-card, and identity references separately from proposal
coverage. A completed processor run does not count as human review. It records exact source and
split digests so the inventory can be repeated against the same local stores.

`cardeventnet-IMG_0095` is the selected pilot. It is in the train partition for CardEventNet and
0068 RF-DETR. The 0043 DINO split does not assign it to a partition. Its source permission allows
training. Its selected event revision names 53 frames, and its latest proposal run completed for
those frames. The stored proposal used recipe v3 and geometry v4. M1 must refresh it with the current
recipe v4 and geometry v5.

Six recordings lack a selected completed event revision. Their frame scope remains unknown. Keep
them out of proposal batches until a completed event revision or explicit exclusion defines their
scope. The manifest uses one recording per batch.

The 2026-10-11 inspection found 52 intake recording directories. Latest stored proposal runs
covered 36 recordings: 24 complete, seven partial, and five failed. The closed 0083 campaign
covered an earlier 30-recording list; it is not the current corpus inventory.

Twelve recordings had card-scene drafts with 583 scene frames. Of those frames, 117 were marked
complete, and 1,685 card states remained pending. Only `game-2026-08-20-01-001` had a selected
completed reference with card scenes, covering 49 frames. Draft scenes included 327 v1, 205 v3,
and 51 v4 fitting recipes. Current fitting uses `fixed-card-pose-grid-search/v5` and the corrected
59 mm by 91 mm dimensions in `card-plane-geometry/v6`. These counts are an inspection snapshot,
not a freeze.

Audit every accepted recording. Select all eligible development recordings for proposal and
review work, and name every deferred or excluded recording with its reason. Separate task
enrollment, source permission, event readiness, and review readiness. A missing source video or
an unsupported frame must produce a recorded blocker, not silent omission.

Reuse the recording workspace and maintained references. This epic does not train models,
implement general algorithm improvements, promote bundles, or automate reconstruction.

## 2. Data and review rules

- [0091](../5-closed/0091-Pile_Region_Feature.md) owns pile feature implementation. Its M7
  handoff is complete; continue using the delivered workflow to review each accumulated pile as
  one coarse source-frame region. Do not require its component-card poses, stacking order, count,
  or identities. Keep normal trick overlap under
  individual-card review. Preserve genuine ignore regions for ambiguous evidence. Do not
  automatically relabel existing ignores or treat pile membership as proof of a prior play.
  Use the `visible-card-data/v2` pile annotation workflow in
  [the capability report](../../reports/0091-Pile_Region_Capability_Handoff.md).
- Grouped proposals become provenance for the pile, not pending individual review or card targets.
  Retain exact remaining individual-card and pile coverage. Publish pile-only frames as detected
  evidence. Older card-only references do not establish reviewed pile coverage.
- Freeze source-group assignments before crop extraction or synthetic generation. Reconcile the
  existing detector, identity, CardEventNet, and system-holdout assignments. Related sessions,
  source assets, and table setups must not cross protected boundaries. Record conflicts and resolve
  them explicitly; do not repartition from measured model errors.
- Keep sealed-test and system-holdout inputs out of development work lists. If new evaluation
  references need annotation, specify a separate blind reference process before accessing them.
- Generate proposals with exact event, detector, calibration, model, and recipe lineage. A terminal
  processor run does not establish reviewed quality.
- Refresh pending proposals under current geometry. Preserve accepted and adjusted cards,
  completed references, identity labels, and prior revisions. If current calibration invalidates
  a correction, show the affected items and require explicit human re-review.
- Review card poses, stacking order, card side, identity usability, and human-hand occlusion.
  Card-card occlusion alone does not produce a valid visible region where a human hand covers it.
  Use supported reviewed exclusions or exclude the exact frame. Ignore regions must be masked
  from loss or cause complete-frame exclusion, never ordinary background labels.
- Publish geometry and identity decisions through the existing completion path. Machine
  classification can prefill review; it cannot replace human confirmation of training targets.
- Review only declared coverage. Missing frames are not reviewed negatives. Each selected frame
  must finish with a reviewed decision or a recorded exclusion.

## 3. Delivery milestones

### M0 — Freeze the work inventory

Add or reuse a read-only inventory over accepted recordings, selected event revisions, proposal
runs, recipe versions, reference state, and source-group assignments. Write one versioned work
manifest with exact recording and frame scope, pilot selection, batch size, exclusions, and blockers.
Prefer `IMG_0095` for the pilot only if the live partition and prerequisites permit it; the snapshot
had 42 of 53 scene frames complete there.

The frozen inventory selects `IMG_0095` for M1. Keep its exact event, detector, calibration, and
recipe lineage. Keep validation groups and six missing event scopes outside the pilot batch.

Acceptance: repeated inventory is deterministic; all intake recordings have a disposition; protected
groups are excluded; existing reviewed work is counted separately from pending proposals; no
processor, review mutation, crop materialization, or training starts during inventory.

### M1 — Generate the pilot proposals

Use the existing proposed-card-scene preflight and batch commands. Fill missing prerequisites only
for the frozen pilot. Verify current model and geometry lineage. Add only the small changes needed
to resume the pilot and preserve corrected items.

Acceptance: every pilot frame has an inspectable current proposal or an exact failure receipt;
unchanged completed inputs are reused; source bytes and human corrections remain intact; fixtures
cover interrupted execution and refreshing a draft with accepted and adjusted cards.

### M1 implementation evidence — 2026-10-11

- See [pilot proposal report](../../reports/0086-M1_Pilot_Proposal_Generation.md) for the exact
  detector, calibration, proposal, frame, and source lineage.
- This report records the original pilot output with the previous 9.09 cm by 5.93 cm dimensions.
  The M3 report records the later proposal refresh under the v5 pose recipe and v6 geometry.
- Reused the selected `IMG_0095` event revision and the completed local RF-DETR result from the
  current 0068 bundle. The new `fixed-card-pose-grid-search/v4` proposals use
  `card-plane-geometry/v5`.
- All 53 frames have supported proposals. The processor run and proposal revision are stored in
  the existing pipeline stores. The prior v4 calibration and maintained visible-card draft remain
  intact.
- A first run found that the v5 calibration reused the v4 revision ID. Calibration revision IDs
  now include the geometry algorithm version. A regression test covers this collision. The
  calibration reflow fixture also checks accepted and adjusted card states, and the backend test
  covers interrupted proposal-run recovery.
- Focused checks passed: 52 operations tests, three backend proposed-scene pipeline tests, Ruff,
  and formatting. No review mutation or training started.

### M2 — Publish the detection-only handoff

Audit the already completed references against the current `visible-card-data/v2` contract. Select
only eligible completed geometry; validate source and frame lineage, visible masks, ignore regions,
frame exclusions, pile coverage, and source-group assignments. Publish an immutable detection-only
manifest for 0087. Do not run the historical 0068 fixed-corpus validator as the acceptance gate.
Record precise gaps if current references need correction. Do not wait for new proposal generation,
unfinished pilot review, or visual identity labels when eligible reviewed references already meet
the contract.

Acceptance: 0087 can independently audit and freeze an eligible detection view from this handoff;
all included masks and exclusions pass current-schema checks; source groups and prior evaluation use
are explicit; any excluded or unresolved references have exact reasons. No identity labels or
identity-processor runs are required.

### M2 implementation evidence — 2026-10-13

- The read-only builder is `operations/scripts/build_0086_detection_handoff.py`. It reads the
  frozen M0 inventory, verifies selected event and visible-card revision lineage, and applies the
  current v2 geometry, ignore-region, frame-exclusion, human-review, and explicit pile-coverage
  checks. It does not change references, extract crops, or run a model.
- The immutable handoff is
  [0086-M2 detection-only handoff](../../reports/0086-M2_Detection_Only_Handoff.json). Its digest
  is `57e63ce72236f9b8585c1787df84e7f6a4704b236230522d6ec8303de3e19a92`.
- Three of 22 candidate recordings qualify: `cardeventnet-IMG_0095`, `cardeventnet-IMG_0097`, and
  `cardeventnet-IMG_0654`. Together they contain 154 reviewed frames, 130 retained frames, 338
  visible-card targets, and 74 coarse pile targets. The handoff includes exact source-group,
  selected event, and reference digests, frame-level masks and exclusions, and prior partition and
  evaluation-use records. It assigns no training, validation, or test partitions.
- The other 19 candidates remain excluded from this handoff with exact reasons, including stale
  draft/reference mismatches, missing or invalid review completion, absent explicit pile coverage,
  or no retained detection samples. Protected groups remain listed from the frozen inventory.
- Focused validation passed: three handoff contract tests, Ruff, and deterministic report
  regeneration. The handoff is ready for 0087's independent M0 audit; it does not itself freeze an
  RF-DETR dataset or authorize training.

### Prior pilot review handoff — 2026-10-11

This is the earlier operator handoff, before the milestone order changed. It is not the M2
detection-only handoff and does not establish current-schema readiness.

- The pilot workbench is open on `cardeventnet-IMG_0095` with the M1 proposal revision selected.
- The workbench shows all 53 frames and 194 card proposals. The `Start review from proposed
scenes` control is ready. It will rebase the maintained draft to the M1 proposal and preserve
  existing corrections.
- The operator must set a profile name before starting the review. No geometry or identity
  decisions have been recorded. Do not count the proposal output as reviewed work.
- The local review service and browser are running for the operator handoff. The review URL is
  `http://127.0.0.1:5173/recordings/cardeventnet-IMG_0095/pipeline/visible_cards?item=cardeventnet-event-img_0095-000`.

### M3 — Refresh the remaining proposal batches

Run the frozen recording list, including the pilot refresh, in small resumable batches. Track current
recipes, frame coverage, partial results, and failures. Preserve completed and corrected work as in
M1. Do not silently expand scope when new recordings arrive. This work can continue after the M2
detection-only handoff has unblocked 0087.

Acceptance: all selected recordings have terminal receipts; unsupported frames remain visible as
review work or exclusions; interruption resumes without duplicate runs or lost corrections.

### M3 implementation evidence — 2026-10-13

- See [M3 proposal refresh report](../../reports/0086-M3_Proposal_Refresh.json) for each selected
  event revision, detector revision and model, processor run, output revision, frame coverage, and
  terminal failure. Its digest is
  `0abbd3ab7af16d9991cc250eef53e3b171c7b5847523eea99ebcbcc360de407e`.
- The read-only report builder is
  `operations/scripts/build_0086_proposal_refresh_report.py`. It checks the frozen inventory
  digest, exact event-frame scope, local RF-DETR detector lineage, proposal content digests, and
  `card-plane-geometry/v6` plus `fixed-card-pose-grid-search/v5` before it writes the report.
- All 22 frozen recordings have terminal proposal receipts. Eighteen runs completed; two produced
  partial proposals; two failed before publishing proposals. The 20 published revisions cover 991
  supported and 10 unsupported frames. The unsupported frame IDs and reasons remain in the report.
- The 20 published results retain three exact local RF-DETR model lineages: 18 segmentation, three
  cascade, and one fine-frame revision. The report records each detector revision and digest.
- `cardeventnet-IMG_0092` failed with `inconsistent_card_geometry`; `cardeventnet-IMG_0096` failed
  with `unstable_table_transform`. Their 101 event frames remain unresolved for geometry review.
  The partial runs for `IMG_0641` and `IMG_0662` retain one and nine unsupported frames, respectively.
- The runs were already terminal in durable storage. The backend health route responded, but
  provider and recording-catalog checks timed out while the service process was CPU-bound. No
  duplicate runs were started.
- Focused report tests, Ruff, report regeneration, frame-count reconciliation, and digest checks
  passed. No references, crops, or training inputs changed.

### M4 — Complete corpus geometry review

An operator completes the frozen geometry work in bounded review sessions. Record each session's
coverage and remaining work. Correct calibration and stacking order, and resolve human-hand
occlusion and ignore regions before reference completion.
After 0091 M1, review piles as coarse regions and complete only the remaining individual poses.
Measure effort by pile regions and remaining cards, not by hidden component cards.

Acceptance: every selected frame has a completed reference decision or exact exclusion; all
published derived visible regions pass validation; no pending card is a training target. Publish an
updated detection-only handoff as eligible reviewed references are added. The expanded RF-DETR
campaign in [0092](0092-Expanded_Reviewed_Virtual_Card_RF_DETR_Campaign.md) requires
completed current-schema references and source groups for at least 18 recordings. Its M0 must
confirm the handoff and freeze the partitions before materialization or training. This milestone
remains open until the recorded human work is complete.

### M4 saved-decision audit — 2026-10-14

The [M4 audit](../../reports/0086-M4_Geometry_Review_Audit.json) reconciles the frozen 22 recordings
with the current maintained references. All 1,102 draft items have terminal review states. Twenty
references are completed; `IMG_0641` and `IMG_0660` remain drafts. This confirms that the broad
frame review has been done. It does not establish current-schema eligibility for every recording.

The audit found a comparison defect: publication adds the optional `pile_detection_status` field
with its contract default, `unsupported`. Eleven completed references differed from their drafts
only by that default field. The comparison now normalizes it. Explicit pile coverage still requires
the `pile_regions` field; a missing field is not converted into a reviewed negative. Regression
tests cover default equivalence and rejection of a real supported/unsupported difference.

The corrected detection handoff has 14 eligible recordings, 697 reviewed frames, 626 retained
frames, 1,671 visible-card targets, and 257 pile targets. Its digest is
`2313806c0aaffa05e173bafed2eda50ebcf78fc0f91965b30067534ac6d1c01e`. The original M2 snapshot
remains unchanged because 0087 used it. The expanded handoff is stored locally at
`.runtime/0086-m4/detection-handoff.json`. Rebuild it from the repository root with:

```sh
mise exec -- uv run --project operations python operations/scripts/build_0086_detection_handoff.py \
  --repository-root . --output .runtime/0086-m4/detection-handoff.json
mise exec -- uv run --project operations python operations/scripts/build_0086_geometry_review_report.py \
  --repository-root .
```

Remaining work:

| Recording                                                              | Saved state                                            | Required next action                                                                                                                         |
| ---------------------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `IMG_0092`, `IMG_0096`, `IMG_0639`, `IMG_0640`, `IMG_0643`, `IMG_0653` | Completed v1 card-only references                      | Confirm pile presence or absence on 271 accepted frames, then complete v2 references. Preserve existing card decisions and exact exclusions. |
| `IMG_0641`                                                             | Draft; 46 accepted, seven unusable frames              | Confirm missing pile coverage on 44 accepted frames, then complete the 53-frame reference. The selected revision still contains older work.  |
| `IMG_0660`                                                             | Draft; 42 accepted, one corrected, six unusable frames | Confirm pile coverage on event frames `000`, `001`, and `002`, then complete the 49-frame reference. No completed revision is selected.      |

The audit lists exact item IDs and input digests. Missing pile coverage is separate from missing
card review. Do not ask the operator to redo all card poses. The recorded M3 calibration failures
for `IMG_0092` and `IMG_0096` remain proposal limitations; they do not erase saved review decisions.
No references or human decisions changed in this audit. Source video bytes were not rehashed.
Focused validation passed: 27 operations tests, Ruff, formatting, and deterministic audit rebuild.
M4 remains open. The 14-recording handoff is below 0092's minimum of 18 recordings. M5 identity
review remains separate.

### M4 completion — 2026-10-14

The operator confirmed that `IMG_0639`, `IMG_0640`, `IMG_0641`, `IMG_0643`, `IMG_0653`, and
`IMG_0660` have no unannotated piles. The newly published `IMG_0641` and `IMG_0660` references
pass the audit. Four other recordings still selected v1 revisions. They were republished through
normal reference completion using this explicit operator confirmation. Their card geometry, card
scenes, ignore regions, frame identities, and review states remain identical. The only content
addition is explicit empty pile coverage. See the
[publication receipts](../../reports/0086-M4_Publication_Receipts.json).

The [recording dispositions](../../reports/0086-M4_Recording_Dispositions.json) supersede the
original M0 selection for two recordings:

- Permanently exclude `IMG_0092` from all future consideration. The staged round was recorded on a
  non-flat surface. The shared source-selection guard rejects its recording ID, source asset ID,
  and source digest, including renamed copies. Existing evidence is retained.
- Defer `IMG_0096` from this handoff while the operator repairs calibration. It does not block M4
  completion for the remaining scope. Repair and re-audit its reference before removing the deferral.

The final [audit](../../reports/0086-M4_Geometry_Review_Audit.json) has 20 eligible recordings,
1,001 reviewed frames, 874 retained frames, 2,352 visible-card targets, and 362 pile targets. Every
active recording has a completed v2 reference. No active frame lacks a saved decision or explicit
pile coverage. All published target geometry passes the detection-handoff checks. The full handoff
is `.runtime/0086-m4/detection-handoff.json`; use the commands above to reproduce it. Its digest is
`503408822bc123b2ebb0f8388f8aed7d9378479b196b9f2e1cd244dbae89c1e6`. The handoff also records
0087's validation use of `IMG_0097` and opened sealed-test use of `IMG_0654`.

Fifty focused operations tests, Ruff, Python formatting, local Markdown links, and deterministic
report regeneration passed. Source video bytes were not rehashed. M4 is complete for the revised
scope. The 0092 recording-count prerequisite is met. 0092 M0 has since frozen the eligible pool
and fresh unopened test. M5 identity review is not part of this completion.

### M5 — Complete identities and publish the 0088 handoff

Use completed reviewed geometry and
[0093 M2–M5](../5-closed/0093-Visual_Classification_Annotation_and_Crop_Inputs.md) to prepare crops
and pending annotation items without requiring a successful classifier prediction. Consume the
`reviewed-visual-identity-materialization/v1` manifest for class, recording, back-design, duplicate,
and exclusion support. Existing model
suggestions remain optional review evidence. An operator confirms or corrects all 24 face-up
identities, positive FACE_DOWN classifications, unusable outcomes, and source problems. A missing
identity prediction must not prevent annotation. Publish a separate 0088 handoff with exact
reference revisions, source groups, class counts, geometry and identity exclusions, recipe versions,
and campaign-specific gaps. Include reviewed pile counts, footprint policy, grouping provenance,
and explicit pile-review coverage. Piles have no identity work. This milestone does not gate 0087.

Acceptance: repeated identity-readiness reports reproduce counts and digests; each training identity
matches its reviewed geometry; independent class/recording support, back-design coverage and all
exclusions are explicit. Face-down crops are positive visual-class training evidence where usable,
not silently excluded or credited as pixel-based classifier success. 0088 can freeze its view
without changing maintained references. Do not invent an identity for an unusable crop. The 0093
software work has no dependency on this M5 handoff, and 0094/0088 training does not gate review.
No training or promotion occurs in this epic.

## 4. Handoff and verification

[0087](../5-closed/0087-Reviewed_Virtual_Card_RF_DETR_Campaign.md) owns segmentation training.
[0093](../5-closed/0093-Visual_Classification_Annotation_and_Crop_Inputs.md) owns reusable annotation
and native crop preparation. [0094](0094-DINO_Training_and_Runtime_Recipes.md) owns
training/runtime recipe implementation. [0088](../4-blocked/0088-Reviewed_Virtual_Card_DINO_Campaign.md)
owns the measured identity quality campaign. Each campaign freezes its own eligibility and recipe
from this handoff.

Use deterministic inventory, geometry derivation, exclusion, reference completion, and lineage
fixtures. Run relevant operations and backend tests and static checks. Run focused web checks
only for changed review controls. Retain operator review receipts and local reproducibility evidence.
