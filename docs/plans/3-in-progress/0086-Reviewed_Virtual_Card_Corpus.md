# Reviewed virtual-card corpus

## Plan status

- **Summary:** Generate current proposed card scenes, complete human correction, and publish
  reviewed geometry and visual card identities for the selected recording corpus.
- **Status:** In Progress
- **Depends on:** Completed 0073, 0074, and 0085; existing local detector and identity providers
- **Outcome:** A recording inventory, completed maintained references, and a reproducible data
  handoff for separate RF-DETR and DINO campaigns.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** In progress — inventory all accepted recordings and select a pilot. Confirm exact
  cross-campaign partitions before freezing development scope.
- **M1:** Not started — generate current proposals for one bounded pilot.
- **M2:** Not started — complete human geometry and identity review for the pilot.
- **M3:** Not started — refresh remaining proposals in resumable recording batches.
- **M4:** Not started — complete geometry review for the selected corpus.
- **M5:** Not started — complete identity review and publish campaign readiness.

## 1. Current evidence and scope

### M0 inventory snapshot — 2026-10-11

The read-only inventory is [versioned manifest 1](../../reports/0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json).
It found 52 complete accepted recordings, 58 proposed-card-scene runs across 36 recordings, and
their current event, visible-card, and identity reference states. The candidate development set has
24 recordings from the CardEventNet train partition. The manifest excludes five sealed system
holdout recordings and three RF-DETR sealed-test recordings. It defers 20 recordings because the
available partition records do not prove development eligibility. It counts completed maintained
references separately from proposal frame coverage. A completed processor run does not count as
human review.

`cardeventnet-IMG_0095` is the pilot candidate. Its selected event revision names 53 frames, and its
latest proposal run completed for those 53 frames. Its source permission allows training. The
manifest does not authorize a refresh or review yet. The checkout does not contain the exact frozen
0043 identity split or full 0068 train and validation manifests. Recover those assignments and
confirm source-group separation before freezing the pilot. The stored proposal used recipe v3 and
geometry v4. M1 must check the current v4 recipe and geometry v5 before it reuses any proposal.

Six recordings also lack a selected completed event revision. Their frame scope remains unknown.
Do not add them to a proposal batch until a completed event revision or explicit exclusion defines
their scope. The manifest uses one recording per batch.

The 2026-10-11 inspection found 52 intake recording directories. Latest stored proposal runs
covered 36 recordings: 24 complete, seven partial, and five failed. The closed 0083 campaign
covered an earlier 30-recording list; it is not the current corpus inventory.

Twelve recordings had card-scene drafts with 583 scene frames. Of those frames, 117 were marked
complete, and 1,685 card states remained pending. Only `game-2026-08-20-01-001` had a selected
completed reference with card scenes, covering 49 frames. Draft scenes included 327 v1, 205 v3,
and 51 v4 fitting recipes. Current fitting uses `fixed-card-pose-grid-search/v4` and the measured
card dimensions in `card-plane-geometry/v5`. These counts are an inspection snapshot, not a freeze.

Audit every accepted recording. Select all eligible development recordings for proposal and
review work, and name every deferred or excluded recording with its reason. Separate task
enrollment, source permission, event readiness, and review readiness. A missing source video or
an unsupported frame must produce a recorded blocker, not silent omission.

Reuse the recording workspace and maintained references. This epic does not train models,
implement general algorithm improvements, promote bundles, or automate reconstruction.

## 2. Data and review rules

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

The current inventory records `IMG_0095` as a candidate, not as an authorized pilot. Complete M0
after exact 0043 and 0068 partition membership is available and the candidate has no source-group
conflict. Keep the inventory exclusions and six missing event scopes explicit.

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

### M2 — Complete the pilot review

An operator reviews the pilot geometry, occlusion exclusions, sides, and identity usability, then
reviews identities from the completed geometry. Inspect derived masks and identity crop previews.
Record correction effort and any workflow blocker. Fix only bounded blockers to this review path.

Acceptance: the pilot publishes completed geometry and identity revisions with matching card and
frame lineage; masks exclude hidden and human-hand pixels; every unusable item has a reason;
campaign preparation can resolve the references without treating proposals as reviewed targets.
An agent must not claim this milestone complete without recorded human review.

### M3 — Refresh the remaining proposal batches

Run the frozen recording list in small resumable batches. Track current recipes, frame coverage,
partial results, and failures. Preserve completed and corrected work as in M1. Do not silently
expand scope when new recordings arrive.

Acceptance: all selected recordings have terminal receipts; unsupported frames remain visible as
review work or exclusions; interruption resumes without duplicate runs or lost corrections.

### M4 — Complete corpus geometry review

An operator completes the frozen geometry work in bounded review sessions. Record each session's
coverage and remaining work. Correct calibration and stacking order, and resolve human-hand
occlusion and ignore regions before reference completion.

Acceptance: every selected frame has a completed reference decision or exact exclusion; all
published derived visible regions pass validation; no pending card is a training target. This
milestone remains open until the recorded human work is complete.

### M5 — Complete identities and publish readiness

Use the completed reviewed virtual-card crop input to propose identities. An operator confirms or
corrects labels and unusable outcomes. Publish a handoff with exact reference revisions, source
groups, class counts, geometry and identity exclusions, recipe versions, and campaign-specific gaps.

Acceptance: repeated readiness reports reproduce counts and digests; each training identity matches
its reviewed geometry; unsupported classes and face-down coverage are explicit; RF-DETR and DINO
can freeze separate views without changing the maintained references. Do not require an invented
identity for an unusable crop. No training or promotion occurs in this epic.

## 4. Handoff and verification

[0087](../4-blocked/0087-Reviewed_Virtual_Card_RF_DETR_Campaign.md) owns segmentation training.
[0088](../4-blocked/0088-Reviewed_Virtual_Card_DINO_Campaign.md) owns identity crop preparation and
training. Each campaign freezes its own eligibility and recipe from this handoff.

Use deterministic inventory, geometry derivation, exclusion, reference completion, and lineage
fixtures. Run relevant operations and backend tests and static checks. Run focused web checks
only for changed review controls. Retain operator review receipts and local reproducibility evidence.
