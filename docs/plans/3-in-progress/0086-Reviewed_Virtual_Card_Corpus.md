# Reviewed virtual-card corpus

## Plan status

- **Summary:** Publish a detection-only handoff from current reviewed geometry, then finish proposal
  refresh and geometry review. Complete visual identity review last.
- **Status:** In Progress
- **Depends on:** Completed 0073, 0074, and 0085; existing local detector provider. Pile annotation
  uses 0091 M0–M1; individual-card review can continue before that handoff.
- **Outcome:** A recording inventory, completed maintained references, and a reproducible data
  handoff for separate RF-DETR and DINO campaigns.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete (2026-10-11) — inventory all accepted recordings, reconcile frozen partitions,
  exclude protected sources, and select the `IMG_0095` pilot.
- **M1:** Complete (2026-10-11) — generate current proposals for all 53 `IMG_0095` event frames.
- **M2:** Not started — audit completed current-schema references and publish the immutable
  detection-only handoff needed to start 0087. Record any exact data correction that remains.
- **M3:** Not started — refresh remaining proposals in resumable recording batches, including the
  `IMG_0095` pilot, with corrected 59 mm by 91 mm geometry.
- **M4:** Not started — complete geometry review for the selected corpus and update the
  detection-only handoff as eligible references are added.
- **M5:** Not started — complete visual identity review and publish the separate 0088 handoff.

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
- The pilot output in this report uses the previous 9.09 cm by 5.93 cm dimensions. Refresh it with
  the current v5 pose recipe and v6 geometry before starting M2 operator review.
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

### M4 — Complete corpus geometry review

An operator completes the frozen geometry work in bounded review sessions. Record each session's
coverage and remaining work. Correct calibration and stacking order, and resolve human-hand
occlusion and ignore regions before reference completion.
After 0091 M1, review piles as coarse regions and complete only the remaining individual poses.
Measure effort by pile regions and remaining cards, not by hidden component cards.

Acceptance: every selected frame has a completed reference decision or exact exclusion; all
published derived visible regions pass validation; no pending card is a training target. Publish an
updated detection-only handoff as eligible reviewed references are added. This milestone remains
open until the recorded human work is complete.

### M5 — Complete identities and publish the 0088 handoff

Use completed reviewed geometry to prepare virtual-card crops and propose identities. An operator
confirms or corrects labels and unusable outcomes. Publish a separate 0088 handoff with exact
reference revisions, source groups, class counts, geometry and identity exclusions, recipe versions,
and campaign-specific gaps. Include reviewed pile counts, footprint policy, grouping provenance,
and explicit pile-review coverage. Piles have no identity work. This milestone does not gate 0087.

Acceptance: repeated identity-readiness reports reproduce counts and digests; each training identity
matches its reviewed geometry; unsupported classes and face-down coverage are explicit; 0088 can
freeze its view without changing the maintained references. Do not require an invented identity for
an unusable crop. No training or promotion occurs in this epic.

## 4. Handoff and verification

[0087](../4-blocked/0087-Reviewed_Virtual_Card_RF_DETR_Campaign.md) owns segmentation training.
[0088](../4-blocked/0088-Reviewed_Virtual_Card_DINO_Campaign.md) owns identity crop preparation and
training. Each campaign freezes its own eligibility and recipe from this handoff.

Use deterministic inventory, geometry derivation, exclusion, reference completion, and lineage
fixtures. Run relevant operations and backend tests and static checks. Run focused web checks
only for changed review controls. Retain operator review receipts and local reproducibility evidence.
