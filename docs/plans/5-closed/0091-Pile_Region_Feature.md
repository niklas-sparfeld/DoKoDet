# Pile-region feature

## Plan status

- **Summary:** Review each accumulated card pile as one coarse region, support it as a separate
  RF-DETR target, and retain pile evidence through inference and table observations.
- **Status:** Closed
- **Closure reason:** Complete
- **Closure note:** M0–M7 delivered. Fixture-backed software and annotation support are ready;
  no trained pile model is selected, and real training remains in 0087.
- **Depends on:** Completed 0048, 0049, 0065, 0073, 0074, and 0085 foundations. M0 and M1 can
  start now. Later milestone prerequisites are listed below.
- **Outcome:** A usable early pile annotation workflow, reproducible two-class detector views,
  a pile-capable provider contract, and verified downstream evidence preservation.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — persist the pile contract, reversible atomic commands, pile coverage, and API.
- **M1:** Complete — source-frame pile annotation, reversible grouping, explicit conversion,
  frame copying, pile-only completion, and the operator handoff are available.
- **M2:** Complete — freeze explicit pile-review readiness and export deterministic two-class
  COCO views with card-priority pixel ownership, pile RLE masks, and lineage receipts.
- **M3:** Complete — the pinned trainer, class-aware evaluator, and digest-checked bundle contract
  support both visible cards and piles.
- **M4:** Complete — retain pile predictions through two-class inference, durable outcomes, and
  the proposal editor, with explicit provider capability and model lineage.
- **M5:** Complete — identity crops include only cards; observations retain separate pile geometry
  and lineage.
- **M6:** Complete — preserve pile evidence in reconstruction input and inspection.
- **M7:** Complete (2026-10-12) — verify the complete fixture flow and publish the capability
  handoff. The software is ready; a selected trained pile model is not available.

## 1. Problem and selected scope

During 0086 review, accumulated piles can contain dozens of physical cards and about 15 exposed
overlapping surfaces. Reviewing their individual poses, order, and identities is not practical.
The existing RF-DETR export excludes a whole frame when it has any reviewed ignore region. This
also removes otherwise useful individual cards from that frame.

The development example is `cardeventnet-event-img_0662-039`, requested at `81078337` microseconds,
in revision `visible-cards-visible_cards-run-58a11cf2-2d0-attempt-1`. Its exact source frame is
index 4861 at `81095000` microseconds. The inspected image has three accumulated piles, one clear
ten of spades, and hand-held evidence near the upper-left edge. The stored result has 14 card
proposals. This is an annotation example, not an evaluation gate or proof of model quality.

The selected representation is one pile region per physical pile, beside the individual cards.
Pile annotation does not require component-card poses, stacking order, count, identity, or
table-plane calibration. Keep normal trick overlap under individual-card review. Keep an ignore
region when neither an individual target nor a reliable pile footprint can be reviewed.

This epic owns feature implementation from annotation through reconstruction input. It does not
run a new model campaign, train DINO, change model defaults, implement temporal pile association,
infer played-card counts, or redesign reconstruction search. Real RF-DETR training, candidate
selection, synthetic-mixture measurement, and bundle decisions remain in
[0087](../2-ready/0087-Reviewed_Virtual_Card_RF_DETR_Campaign.md). Corpus review remains in
[0086](../3-in-progress/0086-Reviewed_Virtual_Card_Corpus.md).

## 2. Delivery order and independent annotation

M0 and M1 are the first delivery priority. After M1, the operator can draw, edit, copy, group,
accept, reload, and publish pile annotations while M2 through M7 are implemented. Do not wait for
the complete corpus, a detector checkpoint, an identity campaign, or observation integration to
make this workflow usable. No later milestone may require the operator to redraw M1 annotations.

| Milestone | Prerequisite          | Usable result                                                                           |
| --------- | --------------------- | --------------------------------------------------------------------------------------- |
| M0        | Completed foundations | Durable contract, commands, coverage, completion, and API                               |
| M1        | M0                    | Operator annotation and immutable publication; 0086 review can continue                 |
| M2        | M1                    | Deterministic two-class export and readiness; fixtures do not require corpus completion |
| M3        | M2                    | Trainer, evaluator, and bundle support; 0087 can run after its own corpus gate          |
| M4        | M0 and M3             | Pile-capable inference and proposal handling, verified with fixture predictions         |
| M5        | M4                    | Identity isolation and assembled table-observation pile evidence                        |
| M6        | M5                    | Engine input and inspection retain pile evidence without inventing gameplay facts       |
| M7        | M1 through M6         | Complete fixture flow and reproducible real-bundle smoke handoff                        |

0087 depends on M0 through M3, not completion of this epic. This epic's software verification uses
fixtures and does not depend on 0087 training. Real pile-model quality and availability remain
separate campaign results. 0087's later pile-capable inference checks require M4. This avoids a
circular prerequisite.

## 3. Annotation and data contract

### Pile geometry and authority

Use a separate `pile_regions` collection in visible-card outcomes. Keep it distinct from
individual-card `candidates`, `card_scene`, and `ignored_regions`. M0 freezes the exact schema
versions, field names, normalized coordinate contract, and API before M1 starts.

The stored content schema is `visible-card-data/v2`. Each outcome has `pile_regions`, including an
empty list when there are no piles. A v1 revision remains v1 when parsed and serialized. New writes
use v2. Do not rewrite old drafts or immutable revisions to add empty pile lists.

A pile region has exactly these fields: `pile_id`, `geometry`, `normalization`,
`source_candidates`, `grouped_candidates`, `grouped_card_states`, and `grouped_scene_decision`.
`pile_id` is unique in its
outcome. Geometry has kind `pile-region/v1` and one or more polygons. Each polygon has at least
three integer points. Each x and y coordinate is from 0 through 1000 in the full-frame
normalization `full-frame-0-1000/v1`. The containing outcome carries the exact source-frame
identity and dimensions. `source_candidates` stores revision and card IDs. The two grouped-member
fields retain candidate payloads and proposal-card review states so delete restores the prior
individual-card work. Review-state records have `card_id`, `source`, `proposal_id`, and `state`;
source is `proposal` or `manual`, and state is `pending`, `accepted`, `adjusted`, or `rejected`.
`grouped_scene_decision` stores the prior `accepted`, `adjusted`, or `manual` scene decision, or
null when the group came from an unreviewed proposal. Grouped-member fields are empty for a
hand-drawn pile.

A detected frame can contain cards, piles, or both. It can complete as pile-only without a
calibration or card scene. `visible_frames` coverage uses `piles`, `cards_and_piles`,
`piles_and_ignored`, or `cards_piles_and_ignored` when those evidence types apply. Existing card,
ignore, empty, and unusable decisions remain unchanged.

The reference API accepts `create_pile_region`, `replace_pile_region`, `delete_pile_region`,
`group_cards_into_pile`, and `convert_ignore_region_to_pile`. Each command uses the existing
expected-revision and idempotency checks. Grouping removes selected proposal candidates or marks
selected proposal-scene cards as grouped in the same transaction. Deleting a grouped pile restores
the saved candidate payloads and proposal-card review states. Rebase preserves pile geometry and
lineage for an unchanged exact frame. A proposal refresh that would reintroduce grouped members
fails with an actionable review error.

The current identity and table-observation processors reject pile-bearing inputs with actionable
errors. They do not silently publish partial identity or observation results. Two-class export,
pile predictions, and observation preservation remain later milestones.

Each region has a stable pile ID, source-frame footprint polygon, normalization, exact frame
lineage, and source proposal references where available. Origin, confidence, reviewer, commands,
and acceptance belong to the existing provenance and maintained-reference lifecycle. A predicted
pile is not a reviewed target. A pile is not an `ObservedCard` with a special identity.

The footprint is a coarse source-image envelope around one visible physical pile. Small internal
gaps may be included. Do not reconstruct hidden cards or trace each exposed fragment. Clip the
footprint to the source frame. Do not include a separate card, another pile, or a large unrelated
background area. A pile geometry does not use measured card dimensions or a planar card pose.
If a human hand prevents a reliable coarse footprint, keep an explicit exclusion rather than
inventing the boundary or labeling the hand as pile evidence.

The detector class is `card_pile`, beside `visible_card`. It describes a visual group. It does
not assert collected status, trick ownership, winner, contents, or count. Those facts require
separate temporal or gameplay evidence. A card back by itself is still an individual card, not
a pile. Annotation guidance must include accumulated piles, ordinary overlapping tricks,
isolated face-down cards, and ambiguous cases.

### Grouping and completion

Support explicit drawing and atomic conversion of selected card proposals or scene cards into
one pile. Preserve their revision and candidate IDs as grouping provenance. Remove those members
from individual targets and the unresolved pose-review list in the same transaction. The number
of consumed proposals is a diagnostic, never a physical card count.

Offer containment-based selection as a preview. Require an explicit command to consume members;
intersection alone must not swallow a newly played card touching the pile. Grouping accepted or
adjusted cards must be visible in the preview and command receipt. Deletion, undo, restore, and
regrouping must have explicit member-restoration semantics, including prior pose-review states.

A mixed frame can complete when its remaining individual cards and pile regions are reviewed.
A pile-only frame can complete without calibration or a virtual-card scene. It is detected
evidence, not an empty frame. Unresolved individual cards outside piles still block completion.
Missing detector proposals do not block manually drawn piles. Add explicit pile review coverage;
an older card-only reference is not proof that the frame was reviewed for piles.

Retain existing completed revisions and active operator corrections. M0 must inventory the live
draft and immutable formats before choosing a minimal, explicit schema evolution. Do not run a
bulk rewrite of references or silently convert existing ignore regions. An operator can convert
one reviewed ignore region to a pile after checking its footprint and meaning.

Commands use existing concurrency checks and atomic persistence. Editing a footprint invalidates
the affected frame decision. Copying from a previous frame creates pending review for the new
exact frame. Rerun, proposal refresh, calibration reflow, and rebasing must preserve reviewed piles
and grouping lineage; they must not resurrect their member cards as reviewed individual targets.

### Pixel ownership and safe consumers

Individual visible-card masks remain precise reviewed visible evidence. Pile targets use the
declared coarse footprint policy. Where the coarse envelope overlaps an independently reviewed
individual visible mask, individual pixels take priority: subtract their union from the pile
target and retain a deterministic receipt. Disjoint visible pieces and holes use lossless RLE.
Intersecting pile targets require correction; reject empty effective footprints.

This priority rule does not establish which object is in front. A partly hidden individual card
still needs a reliable visible mask. Do not generate its hidden pixels from a full-card outline
or subtract a coarse pile footprint as if it were a precise occlusion mask. If the existing
review path cannot establish the visible mask, record an explicit unsupported-card or frame
decision. The pilot must include a newly played card touching or overlapping a pile.

Genuine ignore regions keep their loss-safe policy. In the pinned unmodified RF-DETR trainer,
exclude the exact frame or use a fully reviewed crop outside the ignore region. Do not treat a
pile as an ignore region, omit it from a retained full frame, or assume `iscrowd=1` masks training
loss. Piles are ordinary positive targets with `iscrowd=0`.

Before M2 through M6 are available, existing consumers must reject unsupported pile-bearing
input with an actionable reason. They must not drop piles, expand them into cards, publish a
pile-only frame as empty, or require fabricated identities. Keep the editor and completion path
usable even when a downstream capability is unavailable.

## 4. Delivery milestones

### M0 — Persist the pile contract and commands

Implemented shared pile geometry and outcome parsing, canonical serialization, pile review
coverage, and completion semantics. Added atomic create, replace, delete, selected-member grouping,
and explicit ignore-to-pile conversion commands to the maintained-reference service and API.
Specified reversible member restoration and proposal lineage. Regenerated the Web API types.
Inventoried affected consumers and added fail-closed capability checks before exposing pile data.
The live inventory contained 41 visible-card drafts and 204 immutable v1 revisions. No existing
draft contained a pile. The change did not rewrite these drafts or revisions.

Primary boundaries: `table_evidence_analyzer/pipeline_data.py`, the shared scene contract,
`operations/pipeline_reference.py`, and backend reference handlers, store, service, and API.
Keep geometry, command validation, and grouping transitions in focused modules.

Acceptance met: mixed and pile-only frames persist and complete through the existing lifecycle;
pending outside cards remain pending; stale commands fail atomically; round-trip digests and
grouping provenance reproduce; current drafts and old immutable revisions remain intact;
unsupported downstream consumers return actionable errors instead of lossy success. No UI or
real training is required to complete M0.

### M1 — Make pile annotation available to the operator

Implemented the Pile regions layer, Camera-view polygon drawing and editing, pile inspector
counts, explicit selected-member grouping, ignore-region conversion, deletion with grouped-member
restoration, and Copy piles from previous frame. Pile commands use the maintained-reference
queue. Copied regions start pending and require a new-frame review. The workbench reports pending
individual-card work and frame review state. Rectified view remains optional.

Pile-only frame acceptance and recording-reference completion use explicit pile coverage. The
editor reads pile data after reload and revision selection. Existing ignore regions remain
editable. Added interaction checks for drawing and grouping, and a completion check for pile-only
coverage. The operator guide and 0662 handoff are in
[`docs/guides/Pile_Region_Annotation.md`](../../guides/Pile_Region_Annotation.md).

The 0662 annotation itself remains an operator decision. The agent supplies the workflow and
handoff; it does not create reviewed labels. This releases the pile annotation feature for
continued 0086 review.

### M2 — Export reviewed two-class targets

Extend inventory, readiness, frame coverage, dataset projection, and materialization for reviewed
individual cards and piles. Freeze category IDs, precise-card and coarse-pile target policies,
pixel ownership, derived boxes, mask encoding, exclusions, and source-group lineage. Export
mixed, card-only, pile-only, and reviewed empty samples with exact coverage and receipts.
Adapt applicable crop views so a retained crop contains only fully reviewed target scope.

Acceptance: deterministic cold and warm views; both categories decode exactly; group members
never appear as duplicate card targets; pile-only images are positive samples; ignore treatment
is explicit; stale or unreviewed geometry cannot enter training. M1 annotations load without
redrawing. Readiness separates pile coverage from individual-card and identity support.

#### M2 implementation evidence — 2026-10-12

Added `--include-piles` to `doko data rfdetr-segmentation`. This writes a separate M2 manifest
with category IDs 1=`visible_card` and 2=`card_pile`. The audit accepts only human-maintained v2
outcomes with an explicit `pile_regions` field and matching frame coverage. Legacy card-only
outcomes remain visible as pile-review gaps and cannot become two-class negatives. Reviewed empty
frames remain background samples. Unusable frames remain in the exclusion receipt. This export
does not require a checkpoint or an RF-DETR trainer probe; those are M3 or campaign inputs.

Pile polygons use pixel-center even-odd rasterization. The exporter removes the union of reviewed
individual-card pixels from each pile mask, rejects intersecting pile masks and empty effective
masks, derives a tight box from occupied pixels, and stores uncompressed column-major COCO RLE.
Each pile annotation retains its source candidate references, grouped candidates, and a
deterministic pixel-ownership receipt. The materialization reports card and pile counts separately;
identity support remains explicitly unassessed. The existing 0068 cluster-crop exporter remains
bound to its 0068 input contract; this M2 output is a full-frame view and is not passed to that
crop path.

The fixture covers mixed, card-only, pile-only, and reviewed empty images,
including cold/warm digest parity and exact RLE decoding. A legacy card-only fixture is blocked
from M2 export. No live annotation data or real training campaign was changed.

### M3 — Support training, evaluation, and bundles

Extend the existing RF-DETR trainer configuration, class mapping, staging validators, evaluator,
and bundle metadata for both categories. Pin the package, checkpoint, mask policy, and class
mapping; do not rely on implicit category order. Smoke-load the M2 fixture view and verify finite
losses through the pinned trainer without starting a real campaign.

Report individual-card AP and recall separately from pile localization and classification.
Include pile/card confusion, fragments emitted inside piles, and individual-card recall near
piles. Evaluation uses the same grouped ground truth: consumed members are not missing instance
labels. Handle ordinary trick overlap, pile edges, face-down cards, and human hands as named
slices. Aggregate AP alone cannot establish acceptance.

Record that existing individual-card synthetic scenes have no pile positives. They may enter
a two-class mixture only under an explicit compatible annotation and exposure policy in 0087.
Do not add pile synthesis or infer pile labels for old synthetic overlaps in this epic.

Acceptance: decoded masks and label indices match the frozen view; finite trainer smoke;
reproducible per-class metrics; checkpoint save/load and bundle class-map parity; missing pile
support blocks a pile-model claim. Publish the implementation handoff to 0087. Real training
budgets, numerical quality gates, candidate selection, and promotion stay outside this milestone.

#### M3 implementation evidence — 2026-10-12

Extended the `rfdetr==1.9.4` SegMedium trainer to read the frozen M2 category map explicitly:
COCO category 1 is `visible_card`; category 2 is `card_pile`. Training arguments carry both class
names and `num_classes=2`. Staging rejects unsupported category maps, missing M2 pile-review
readiness, or a changed mask policy. The checkpoint bundle records the exact class map, package,
pretrained checkpoint digest, M2 materialization digest, and pile mask policy. Bundle loading
rejects a two-class model without the 0091 capability receipt or with mismatched class count,
recipe map, or mask policy.

The evaluator decodes the M2 uncompressed column-major RLE masks and reports card and pile mask
AP, box AP, recall, class confusion, and card predictions inside pile masks. It reports individual
card recall near piles using a fixed gap of 5% of the shorter image dimension, with a 4-pixel
minimum. It also names face-down, ordinary-trick-overlap, pile-edge, and human-hand slices. M2
does not tag ordinary trick overlaps, pile edges separately, or human hands, so those slice results
are marked unavailable. Consumed grouped candidates do not become individual-card ground truth.
The evaluator records metrics without applying 0087 quality gates; M2 does not provide a sealed
test partition.

Validation: focused training and evaluator tests passed (21 tests); Ruff passed. A CPU smoke run
with the pinned trainer used a tiny two-class M2 fixture, completed one epoch, verified finite
losses, saved and reloaded a checkpoint, and wrote a bundle with matching class and mask maps.
This checks software compatibility only. It is not a training candidate or quality result. The
existing one-class trainer and bundle remain supported for 0067 and 0068.

### M4 — Preserve piles through inference and proposals

Extend provider results, native RF-DETR adapters, fine-frame refinement, pipeline revision
publication, and generated overlays to retain card and pile predictions separately. Validate the
bundle class map before inference. Piles retain origin, confidence, geometry, and model lineage.
They do not enter card-pose fitting, calibration-anchor selection, or individual-card refinement.

Specify reconciliation for duplicate pile predictions, overlapping pile/card outputs, and crop
coordinate transforms. Do not suppress a touching card by coarse-envelope intersection alone.
Older card-only providers declare that they do not detect piles; absent predictions from those
providers must not count as reviewed pile negatives.

Acceptance: fixture logits for both classes survive inference, normalization, storage, reload,
proposal refresh, and UI rendering; mismatched bundles fail; reviewed pile corrections survive
reruns; pile IDs do not appear in pose or calibration work. No default provider change.

#### M4 implementation evidence — 2026-10-12

The local segmentation provider validates the M3 bundle before loading the model and maps its
class-0 outputs to individual-card proposals and class-1 outputs to separate pile proposals. It
retains confidence, full-frame normalized geometry, provider version, bundle/checkpoint identity,
and the frozen class map and mask policy in pile lineage. Duplicate pile boxes with IoU at least
0.9 are suppressed in detector order; card and pile outputs are never suppressed against each
other, including when they touch or overlap. Fine-frame crop routing
remains card-only; pile geometry is produced on the full frame and is not transformed through a
card crop. Existing card-only providers persist `pile_detection_status=unsupported`, so an empty
pile list is not a reviewed negative.

Pipeline outcomes store pile polygons in the existing full-frame 0–1000 coordinate contract,
with origin, confidence, bundle lineage, and capability status. The result API and editor reader
preserve those fields; the existing pile layer renders the generated geometry while keeping it
separate from individual-card candidates. Generated revisions remain separate from maintained
references, so reruns do not replace reviewed pile corrections. No default provider was changed.

Validation: focused Python tests passed across provider serialization and pipeline-data
contracts; 23 backend visible-card pipeline and provider-integration tests passed; the pile editor
suite passed (3 tests), Web TypeScript checks passed, and API types were regenerated. Ruff checks
passed. Fixtures verified two-class inference separation, durable pile lineage and capability,
round-trip parsing, API publication, and overlay/editor compatibility. No real two-class model
quality claim was made.

### M5 — Isolate identity work and assemble pile evidence

Filter piles before DINO crop extraction, identity suggestion generation, review coverage,
auto-accept, and training preparation. Preserve existing individual-card identity lineage.
Extend the table-observation publisher with a separate pile collection, geometry, source and
model lineage, and optional confidence. Count and contents remain unknown and are not derived
from consumed proposal counts or the observation timestamp.

Acceptance: a mixed fixture issues identity work only for the individual card; a pile-only
fixture issues none and still publishes nonempty pile evidence; identity failure cannot remove
piles; no pile becomes FACE_DOWN, UNKNOWN, or an anonymous individual card. Exact pile evidence
survives observation publication and reload. Run focused 0085 crop and assembly regressions.

#### M5 implementation evidence — 2026-10-12

Identity runs now accept pile-bearing visible-card revisions. Crop manifests still iterate only
individual-card candidates, so pile geometry and grouped members do not create identity work.
Reviewed virtual-card crop lineage remains unchanged. Identity outcomes for individual cards do
not control whether pile evidence is published.

Observation assembly copies every pile into a separate `piles` collection. It retains the pile ID,
normalized polygons, frame normalization, source candidate references, grouped-member lineage,
origin, optional confidence, and model lineage. A pile-bearing observation uses
`table-observation/v2`; card-only observations remain `table-observation/v1`. Pile-only frames have
status `observed` with no cards. They are not empty-table claims.

Validation: 9 observation-assembly tests and 9 backend identity/observation API tests passed. The
API fixture submitted mixed and pile-only revisions through identity processing. The mixed crop
manifest named only its card candidates; the pile-only manifest had zero items and produced no
identity outcomes. Observation publication retained the mixed pile through backend restart. The
pile-only assembly fixture retained a nonempty pile collection. Engine parsing and inspection
remain M6.

### M6 — Retain pile evidence in engine input and inspection

Update the mirrored engine observation parser, canonical serialization, input validation,
replay, and relevant observation inspectors to preserve the pile collection. Expose its spatial
evidence separately from individual cards. Version and test the changed observation boundary.

Keep the current search behavior explicit: pile evidence is retained but does not create plays,
legal card assignments, winners, or counts. A frame with only piles must not become a claim of
an empty table. Temporal association and gameplay use need a later measured reconstruction epic.

Acceptance: publisher-to-engine round-trip parity; mixed and pile-only inputs parse and inspect
correctly; individual-card fixtures retain their behavior; a pile cannot add a phantom play or
identity. Reconstruction output and diagnostics state when pile evidence is not yet used by
the search, rather than claiming inferred pile contents.

#### M6 implementation evidence — 2026-10-12

The mirrored game-engine parser accepts `table-observation/v1` and `table-observation/v2`. Its v2
pile contract retains normalized polygons, source dimensions, source candidate references, grouped
member lineage, origin, confidence, and model lineage in canonical serialization. The
`round-reconstruction-input/v1` wrapper keeps the nested observation versions unchanged.

Reconstruction diagnostics now report pile-bearing observation and pile-region counts, with
`pile_search_status=retained_not_used`. The operations result contract is
`round-reconstruction-result/v3`. Piles remain outside card proposals and replay actions. The
timeline inspector shows each footprint in its full-frame aspect ratio beside individual cards. It
states that contents and card count are not inferred. A pile-only observation remains
`observed`; with no card proposals, reconstruction is `incomplete`, not an empty-table result.

Validation: three publisher-to-engine boundary tests passed for mixed and pile-only parity,
canonical round-input reload, explicit pile diagnostics, and unchanged plays/actions on the
unambiguous card fixture. All 76 game-engine tests passed. All 36 focused operations reconstruction
and pile-boundary tests passed with an OpenCV 4.11 test overlay; the synced OpenCV 5 distribution did
not expose its `cv2` module. The focused timeline inspector suite passed (6 tests), TypeScript checks
passed, and generated API types matched OpenAPI. The full Web suite reported 19 failures in unrelated
recording pipeline, frame cache, and visible-card workbench tests; its typecheck passed.

### M7 — Verify the feature and publish the handoff

Run a local fixture from reference editing and publication through two-class materialization,
trainer smoke and bundle reload, provider predictions, identity filtering, observation assembly,
engine input, and inspection. Include restart, stale inputs, unsupported consumers, grouping
undo, pile-only frames, and a card touching a pile. Record source and artifact digests and the
annotation-ready versus software-ready versus trained-model-ready states separately.

Provide one bounded real inference smoke procedure for the exact pile-capable bundle selected
by 0087 when one exists. Execute it only when its campaign decision and inputs permit it. A
missing or rejected real candidate does not block fixture-backed software completion; record
that no validated real pile detector is available and retain the annotation workflow.

Acceptance: one reproducible fixture command proves all feature boundaries; no pile or member
silently disappears; the operator guide and retained annotations remain valid; real model
availability and limits are explicit. Hand the exact feature/capability versions to 0086, 0087,
0088, 0089, and 0090. No campaign, temporal search, or model promotion is added at closure.

#### M7 implementation evidence — 2026-10-12

Published [the pile-region capability handoff](../../reports/0091-Pile_Region_Capability_Handoff.md)
with separate annotation-ready, software-ready, and trained-model-ready states. It records the
feature contracts, handoffs to 0086–0090, a reproducible local fixture verification command, and
a one-frame smoke procedure gated on an exact 0087-selected bundle. No such candidate is selected;
trained-model readiness remains unavailable. The handoff does not alter reviewed annotations or
run a model campaign.

## 5. Verification and implementation discipline

Implement one small milestone at a time. Use focused shared-contract, operations, backend,
provider, identity, observation, and engine tests for the changed boundary. For M1, include
interaction tests for drawing, grouping, copy, undo, navigation, reload, and publication. Run
API-generation parity, relevant Python static checks, Web type checks, formatting, and the
existing visible-card module-size check when applicable.

Use synthetic fixtures for routine verification. Keep the named development frame as an
operator example, preserve current uncommitted review work, and do not read protected evaluation
images to select the feature. The 0086 source-group manifest remains the development allowlist.
Document unrelated baseline failures separately from new regressions.
