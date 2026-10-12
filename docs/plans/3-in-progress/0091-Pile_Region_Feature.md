# Pile-region feature

## Plan status

- **Summary:** Review each accumulated card pile as one coarse region, support it as a separate
  RF-DETR target, and retain pile evidence through inference and table observations.
- **Status:** In Progress
- **Depends on:** Completed 0048, 0049, 0065, 0073, 0074, and 0085 foundations. M0 and M1 can
  start now. Later milestone prerequisites are listed below.
- **Outcome:** A usable early pile annotation workflow, reproducible two-class detector views,
  a pile-capable provider contract, and verified downstream evidence preservation.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — persist the pile contract, reversible atomic commands, pile coverage, and API.
- **M1:** Not started — deliver the complete pile annotation and publication workflow.
- **M2:** Not started — materialize reviewed individual-card and pile training targets.
- **M3:** Not started — support two-class trainer, evaluation, and bundle contracts.
- **M4:** Not started — retain pile predictions across providers, proposals, and review.
- **M5:** Not started — exclude piles from identity work and preserve them in table observations.
- **M6:** Not started — preserve pile evidence in reconstruction input and inspection.
- **M7:** Not started — verify the complete local flow and publish the capability handoff.

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
[0087](../4-blocked/0087-Reviewed_Virtual_Card_RF_DETR_Campaign.md). Corpus review remains in
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

Add a Pile regions layer, source-view polygon drawing and editing, an inspector, selected-member
grouping, explicit ignore conversion, deletion and undo, and Copy piles from previous frame.
Reuse workbench tool, viewpoint, selection, and contextual-command boundaries. Show pending and
reviewed states, pile counts, and the individual cards still requiring review. Rectified display
is optional when calibration exists; annotation works in Camera view without it.

Verify frame acceptance, recording-reference completion, reload, revision selection, and
navigation. Keep model training and other unavailable consumers out of the annotation flow.
Supply a short operator guide and an annotation handoff using the named 0662 example. The agent
provides fixtures and controls; the operator makes the real review decisions.

Acceptance: the operator can publish three pile regions plus the isolated card in the example
without reviewing component poses or identities; grouping removes only selected pending work;
reload and undo preserve data; copied regions require new-frame review; old ignore regions remain
editable. Focused interaction, reference-publication, and workbench-boundary checks pass. This
milestone explicitly releases annotation for continued 0086 work.

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
