# Visible-card training-data improvement

## Plan status

- **Summary:** Correct Gemini visible-card geometry, review visible regions, and measure detector
  labels and classifier crops with the frozen local-detector recipe.
- **Status:** In Progress
- **Depends on:** Plan 0037 frozen dataset, recipe, bundle, and provider contracts. M3 requires its
  first real pseudo-label dataset and native bundle.
- **Builds on:** Plans 0020, 0022, and 0027 review, dataset, and lineage contracts
- **Outcome:** Produce the first reviewed visible-card geometry dataset and measured evidence about
  Gemini proposal instructions, RF-DETR box labels, classifier crop policy, and one targeted data
  addition.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete for the local contract path — the versioned v2 request, strict geometry and
  identity-usability contracts, and development-only paired pilot command are implemented. A real
  Gemini pilot waits for an approved credential and an exact-event development manifest.
- **M1:** Complete for the local review contract path — resumable geometry correction, source and
  teacher lineage, and review fixtures are implemented. A real review pass waits for the exact
  event corpus and approved source-lineage manifest.
- **M2:** Complete for the local freeze contract path — immutable reviewed manifests, source-group
  partition checks, coverage reporting, and fixed crop transforms are implemented. A real freeze
  waits for the exact-event review corpus and approved pilot report.
- **M3:** Pending real plan 0037 pseudo-label and native bundle artifacts
- **M4:** Pending

## 1. Purpose

Improve proposal geometry and training data before changing the detector architecture. Keep the
plan 0037 RF-DETR Large variant, pretrained checkpoint, preprocessing, training recipe, confidence
threshold, and seed fixed for the first comparison. Run full training on the declared RunPod CUDA
environment. Training wall time is not a selection metric.

Use a new version of the plan 0037 Gemini request to propose visible regions for reviewed
`card_played` events at exact offset `0 ms`. The instructions must distinguish the visible region
from the inferred full-card extent. They must require the box to be the tight axis-aligned extent of
the returned visible region. Do not overwrite or reinterpret an existing cached result. The request
version and complete instructions are cache inputs.

A person must review each proposal before it becomes a reference or training label. The reviewed
visible region is the geometry source of truth. Derive the RF-DETR box from that region. Never use an
inferred full-card extent as the detector target or classifier crop.

This plan measures visible-card localization and the quality of crops supplied to the existing
identity classifier. It does not change the identity model, select a played card, add tracking, or
change game reconstruction. Instance segmentation is not part of this plan. This plan can provide
the evidence for one later bounded segmentation experiment.

## 2. Dataset design

Build three distinct sets with source-lineage-safe partitions:

1. **Teacher set:** immutable Gemini proposals for the reviewed seed frames. Preserve the frozen
   plan 0037 subset. Keep the old and improved request versions distinct.
2. **Reviewed seed set:** corrected visible regions and derived boxes on usable `0 ms` frames from
   reviewed events.
3. **Reviewed challenge set:** false proposals, empty frames, occlusion, human-hand overlap, glare,
   blur, small-card cases, and classifier-crop contamination. Keep this set out of training until
   its evaluation role is frozen.

Exclude the sealed system holdout. Split by session or stricter source-lineage group. Do not split
nearby frames from one recording across train and validation.

Target the first reviewed seed set at 100 usable frames from at least five sessions, with no session
supplying more than 40%. If the repository cannot meet this target, publish the measured coverage
gap and continue with a smaller explicitly limited experiment.

## 3. Review contract

For each exact-event frame, the reviewer must decide frame usability and then review every
separately visible physical card:

- `GOOD`: the frame can supply visible-card localization labels;
- `BAD`: the frame is not usable for this task;
- accepted, corrected, added, and removed visible regions;
- face-up, face-down, or unknown side when it can be reviewed;
- usable or unusable for identity classification, with one declared reason;
- failure tags for small card, occlusion, human hand, blur, glare, crop boundary, and duplicate.

One visible region can contain one or more polygons when an occluder splits the visible pixels. Do
not include the pixels of the covering card, a human hand, or the background. Do not infer the
hidden part of an occluded card. Derive one tight axis-aligned RF-DETR box from the complete visible
region. A derived box can contain an occluder when the visible region is disconnected; the region
remains the source of truth for crop evaluation.

Mark a card unusable for identity when the visible pixels do not contain sufficient identity
evidence or when a box-only crop is materially contaminated by another card. An unusable identity
crop remains a valid visible-card detection target. A `BAD` frame is not an empty negative. An empty
negative requires an explicit review that no physical card is visible.

Each decision records reviewer, source-frame digest, Gemini request and result digests, geometry
version, derived box, identity usability, review time, and source-lineage group. Save each decision
immediately and resume without repetition. Preserve the original Gemini result beside the reviewed
artifact.

## 4. Evaluation

Use corrected visible regions and derived boxes in the frozen validation and challenge sets.
Report:

- box average precision at IoU 0.50 and from 0.50 through 0.95;
- instance recall at declared score and IoU thresholds;
- false and duplicate proposals per frame;
- empty-frame false-positive rate;
- usable-crop recall;
- identity accuracy conditional on a usable crop;
- end-to-end correct-identity recall;
- results by session, table setup, side, visible-card count, and failure tag;
- median and p95 local inference latency.

Measure Gemini request versions on the same reviewed pilot frames. Report inferred-full-card errors,
visible-region overlap, false and duplicate proposals, and usable-crop recall. Select at most one
improved request version before the main review. Do not tune the request on validation or challenge
frames.

Compare three crop conditions with the same frozen identity classifier and source frames:

1. the current raw rectangular crop;
2. an oracle crop that keeps reviewed visible-region pixels and replaces other pixels with one
   declared neutral value; and
3. a conservative box-only policy that rejects contaminated or insufficient crops.

The oracle crop measures the possible value of masks. It is not a deployable local-detector result.
If it materially improves end-to-end identity on occluded cards, propose RF-DETR instance
segmentation or one mask-refinement stage as a separate bounded epic. Do not add it here.

Latency is descriptive in this data experiment. The comparison must not prefer worse detection
only because it trains faster. If inference becomes an operational problem, evaluate speed and
quality as separate axes in a later bounded model experiment.

Compare paired predictions from the same frozen validation frames. Do not use validation metrics to
edit labels or thresholds after the comparison begins.

## 5. Delivery milestones

### M0 — Freeze the geometry and Gemini request contracts

- Add one versioned Gemini request that says visible pixels and inferred full-card extent are
  different, permits non-rectangular visible regions, and requires a tight derived box.
- Add reviewed visible-region, derived-box, and identity-usability contracts.
- Keep existing requests, cached results, and plan 0037 artifacts immutable.
- Run both Gemini request versions on the same 20 development frames and select at most one request
  for new teacher proposals.

Acceptance:

- the request version and complete instructions participate in cache identity;
- a box inconsistent with its visible region is rejected;
- the pilot report records the paired request results and selection reason;
- validation, challenge, test, and system-holdout frames do not select the request.

#### M0 implementation evidence — 2026-08-31

- Added opt-in `visible-card-request/v2` with explicit visible-region and inferred-full-card
  semantics, support for non-rectangular polygons, and a tight derived box requirement. The
  existing v1 request, cached results, and plan 0037 artifacts remain readable and unchanged.
- Added `VisibleRegion`, `DerivedBox`, `ReviewedVisibleCard`, and `IdentityUsability` contracts.
  Disconnected visible polygons are supported. A reviewed card rejects a derived box that does not
  equal the tight bounds of its visible region.
- Added `table-analyzer visible-card-prompt-pilot`. It runs v1 and v2 on the same development
  frames, stores both request and result records, requires a selection reason, and rejects
  non-development partitions. The output is immutable.
- Verification: all 80 TableEvidenceAnalyzer tests, Ruff checks, CLI help, and the backend visible
  card integration test pass. A real Gemini call was not started because the available workspace
  has no approved runtime credential and no exact-event development manifest.

### M1 — Add visible-region correction review

- Extend the existing review path with visible-region accept, reshape, add, and remove actions.
- Support more than one polygon for one physical card.
- Derive the RF-DETR box instead of asking the reviewer to maintain duplicate geometry.
- Record identity usability and an unusable reason.
- Add fixtures for overlapping cards, disconnected visible regions, an empty frame, an occluded
  card, and a bad frame.

Acceptance:

- the queue resumes after every saved decision;
- corrected artifacts keep full source and teacher lineage;
- visible regions exclude covering-card pixels in the overlap fixtures;
- `BAD`, reviewed empty, and identity-unusable decisions remain distinct;
- malformed or incomplete reviews cannot enter a dataset.

#### M1 implementation evidence — 2026-08-31

- Added `visible-card-review-queue/v2` with immutable source-frame and teacher-request/result
  lineage. The original run artifact is retained by path and digest, and its normalized provider
  result is stored beside the review state.
- Added resumable frame decisions and atomic per-card actions: `accepted`, `reshaped`, `added`,
  and `removed`. A GOOD review remains in progress until every teacher proposal has an action;
  BAD reviews require an explicit empty-frame decision and cannot contain card actions.
- Added face-side, identity-usability, failure-tag, multi-polygon, tight-derived-box, and source
  lineage validation. Accepted actions must preserve teacher geometry and side.
- Added local JSON fixtures and tests for overlapping cards, disconnected regions, occlusion,
  explicit empty frames, bad frames, add/remove corrections, lineage, resume, and incomplete
  review rejection. The CLI now exposes the queue, frame review, action, and completion commands.
- Verification: all 89 TableEvidenceAnalyzer tests and Ruff checks pass. No real source review or
  model campaign was started.

### M2 implementation evidence — 2026-09-01

- Added `visible-card-freeze/v1` output with immutable teacher, reviewed train, reviewed validation,
  challenge, coverage, review-policy, crop-policy, and freeze manifests. The freeze consumes only a
  completed v2 review queue, a 20-frame development pilot with a selected request version, and an
  explicit partition manifest.
- Added source-lineage-safe partition validation. Every queue item must be assigned exactly once to
  train, validation, or challenge. A source-lineage group cannot cross partitions, and a listed
  system-holdout group cannot enter the freeze. Train and validation frames must be GOOD reviews
  with reviewed labels.
- Added coverage by source-lineage group and failure tag. The report records the usable seed-frame
  and five-source-group targets, the 40% maximum group share, and a measured coverage gap when the
  available corpus is smaller than the target.
- Froze review wording and three crop conditions before evaluation: raw derived-box crop, oracle
  visible-region masking with neutral RGB `(128, 128, 128)`, and conservative box-only rejection
  for unusable or failure-tagged cards. Crop transforms are metric-independent and deterministic.
- Added loader and fixture tests for provenance, source-group overlap, system-holdout exclusion,
  target-gap reporting, and distinct crop outputs. Added `table-analyzer
  freeze-visible-card-review` and documented the partition input and generated artifacts.
- Verification: all 95 TableEvidenceAnalyzer tests, Ruff checks, CLI help, formatting, and
  whitespace checks pass. The workspace still has no exact-event review corpus for a real freeze;
  no model campaign, candidate lock, sealed test, or promotion was started.

### M2 — Freeze the reviewed seed, challenge set, and crop policy

- Review the 20-frame pilot and freeze the review wording and crop-policy rules before the main
  pass.
- Review the available exact-event corpus and publish coverage by source group and failure tag.
- Freeze train, validation, and challenge manifests before model comparison.
- Freeze the raw, oracle visible-region, and conservative box-only crop transforms.

Acceptance:

- all labels in the reviewed manifests have complete review provenance;
- partitions have no source-lineage overlap;
- the system holdout is absent;
- the report states whether the 100-frame and five-session targets were met;
- no crop rule is selected from validation or challenge results.

### M3 — Measure corrected detector labels and crop behavior

Train two candidates with the exact plan 0037 recipe and seed. Use the same training-frame
membership for both candidates:

1. Gemini pseudo-labels for those frames;
2. corrected reviewed boxes for those frames.

Evaluate both on the same reviewed validation and challenge sets. Evaluate the three frozen crop
conditions with the same identity classifier. Do not change architecture, augmentation, resolution,
epochs, detector thresholds, identity classifier, or seed in this comparison.

Acceptance:

- both candidates consume frozen dataset and split digests;
- one machine-readable comparison contains paired sample predictions and all declared metrics;
- the result states whether correction improved, harmed, or did not clearly change localization;
- the result states whether masking or conservative rejection improves end-to-end identity;
- the result states whether a separate segmentation experiment is justified;
- no candidate is promoted.

### M4 — Add one targeted data round

- Select one failure category from the M3 report, not from test or system-holdout results.
- Add a bounded review batch for that category. Prefer unused source groups.
- Retrain with the reviewed seed set plus this one addition and compare on the unchanged validation
  and challenge sets.

Acceptance:

- the selection reason names one measured failure and a fixed item budget;
- new samples have complete review and lineage records;
- the report isolates the effect of the added data;
- further work is proposed as a new bounded recipe rather than an open-ended loop.

## 6. Start and completion

M0 can start from the completed plan 0037 request, dataset, recipe, and provider contracts. M3 must
wait for plan 0037 to record its first real pseudo-label dataset, native bundle, and end-to-end
result. Do not substitute fixture artifacts for the real comparison.

Complete this epic after M4 publishes the reviewed datasets, crop evidence, and detector
comparison. A quality improvement is desirable but is not required. Clear evidence that the prompt,
label, crop, or targeted data change did not help is also a valid outcome.
