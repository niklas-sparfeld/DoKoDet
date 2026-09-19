# Synthetic visible-region training data

## Plan status

- **Summary:** Build a deterministic local generator that composites reviewed card cutouts onto
  real table backgrounds with table-setup-specific perspective, exact visible-region masks, and
  controlled occlusion. Measure whether the added training data reduces visible-card correction
  work on real frames.
- **Status:** Blocked
- **Depends on:** 0048, 0049, 0065, and 0068 complete
- **Outcome:** A reproducible synthetic-data generator, one bounded RF-DETR training comparison,
  and a measured decision about using its candidate as an annotation prefill. Synthetic data does
  not enter validation or the sealed test and does not change a runtime default.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — the deterministic contract and dry-run audit are frozen, but the input gate
  found no reviewed empty background and no eligible face-down card cutout.
- **M1:** Not started — blocked until operator-reviewed training-only background and face-down
  cutout inputs are available.
- **M2:** Not started — implement deterministic scene rendering and exact visible-region targets.
- **M3:** Not started — materialize and inspect one bounded synthetic training set.
- **M4:** Not started — run one paired real-only versus real-plus-synthetic training comparison.
- **M5:** Not started — measure annotation correction effort and publish the decision.

## 1. Purpose

The current annotation processor needs too much visible-card correction. Prompt changes alone have
not solved the problem. This epic tests whether synthetic supervision can improve the local
instance-segmentation model enough to make human annotation faster.

This is an annotation-data experiment. It can use reviewed single-card frames, marked empty table
frames, adjacent source frames, offline preprocessing, repeated rendering, and long local jobs.
These inputs do not need to be available during a real game.

The main question is:

> Does one fixed mixture of real reviewed frames and perspective-grounded synthetic frames reduce
> correction effort on new real frames without reducing held-out visible-region quality?

The experiment produces exact synthetic labels from the renderer. Gemini does not label synthetic
scenes. A later annotation run can use the resulting local candidate as a proposal source, but a
person remains the authority for the maintained reference.

## 2. Fixed boundaries

Use only source material from the frozen 0068 training partition. A card cutout, background,
occluder, geometry sample, or measured image distribution from validation or the sealed test is a
data leak and must stop the run.

Synthetic scenes are training samples only. They are not reviewed source frames, maintained
references, independent source groups, validation samples, or sealed-test samples. Every generated
sample records all real source groups that contributed pixels or geometry. It inherits the most
restrictive source permission of those inputs.

Keep these items out of scope:

- another Gemini prompt iteration or Gemini-generated target geometry;
- synthetic-only training or evaluation;
- identity-model training and visual card identity claims;
- a general camera-calibration or 3D scene-reconstruction system;
- diffusion or other generative image models;
- runtime preprocessing, provider promotion, or a default-provider change; and
- a parameter, seed, model-size, resolution, or synthetic-mixture sweep.

Continue to use `visible_card` as the one segmentation class. A generated target is the visible
region after clipping and occlusion. It never contains hidden card pixels. A synthetic card that
becomes too small or too occluded for the frozen eligibility rule is omitted with a receipt; its
pixels must not silently become an uncertain positive target.

## 3. Generator inputs

### 3.1 Card cutouts

Prefer operator-marked single-card frames from the 0068 training groups. An eligible frame has one
reviewed physical card, one complete four-corner visible region, no visible-card ignore region, no
occlusion, and enough pixels for the frozen minimum-size rule. Existing reviewed training frames
can supply additional eligible cards when they meet the same rule.

Rectify each eligible card to one canonical card rectangle with an inverse projective transform.
Store its RGB image, exact alpha mask, card side, source lineage, source quadrilateral, and
materialization digest. Keep face-up, face-down, and unknown source facts. Visual card identity is
optional because this is one-class segmentation.

Do not use a visible polygon as evidence for a complete card when the source card is clipped or
occluded. Do not inpaint a missing card corner.

### 3.2 Backgrounds and occluders

Use table backgrounds from explicitly marked frames with no visible physical card. The mark must
cover the complete frame. Missing visible-card annotations do not prove an empty background.

Start with card-card occlusion because the renderer can label it exactly. Human-hand and arm
occlusion can enter only through reviewed alpha masks from training source material. Do not use a
rectangle, a visible-card ignore region, or an unreviewed model mask as a human occluder.

If the selected training groups contain too few empty backgrounds or reviewed occluders, M1 must
report the gap. The first generator can proceed without human occluders. It cannot fabricate their
quality.

### 3.3 Perspective and placement

Treat reviewed complete card quadrilaterals as measured perspective examples for one table setup.
Normalize each example by source dimensions and retain its centroid, corner order, area, edge
lengths, skew, and rotation.

The first generator uses this empirical geometry directly:

1. Select one table setup and one real perspective example from its training groups.
2. Map a canonical card rectangle to that observed quadrilateral.
3. Apply only the bounded position, scale, rotation, and corner jitter frozen in M0.
4. Reject geometry outside the measured envelope for that table setup.

Single-card frames are valuable because they provide clean cutouts and unambiguous complete
quadrilaterals. They do not, by themselves, identify one unique global table homography. This epic
therefore does not ask a model to describe perspective in text or claim a recovered camera model.

For piles, sample one local anchor quadrilateral and create nearby cards with bounded offsets and
rotations before applying the same local perspective transform. Freeze overlap-depth buckets from
the reviewed training distribution. Include deliberate hard examples, but keep their geometry
inside the measured table-setup envelope.

## 4. Rendering and target rules

Render at the source-frame size, then pass the result through the existing RF-DETR materialization
and resize path. The renderer must use a fixed seed and explicit recipe. The recipe records:

- source asset and materialization digests;
- table setup and background selection;
- card count, side distribution, placement references, and projective transforms;
- z-order, clipping, and occlusion ratio for every card;
- shadow, blur, glare, noise, color, and compression parameters;
- final image, mask, COCO, and recipe digests; and
- the generator code version and local dependency versions.

Build each full-card alpha mask before compositing. For card `i`, calculate its final visible mask
by subtracting the union of all higher z-order opaque masks and any reviewed occluder mask. Clipping
at the frame boundary is part of the same calculation. Preserve disconnected mask components when
an occluder splits one visible region. Derive the tight box from the final mask.

Apply geometric changes to images and masks together. Apply photometric changes only after target
geometry is fixed. Keep effects within distributions measured from real training frames. Use a
small edge treatment and shadow model so the detector cannot solve the task from paste seams.

Generate the following declared scene buckets:

- one fully visible card;
- two to nine separated cards;
- two to nine overlapping cards with shallow, medium, and heavy visible occlusion;
- frame-boundary clipping;
- face-down cards and mixed card sides;
- blurred, glare-affected, dark, and compressed scenes; and
- reviewed empty backgrounds as true negative training frames.

Do not synthesize a visible-card ignore region. Synthetic ordering gives exact instance ownership.
Real ambiguous regions remain governed by the 0065 exclusion policy.

## 5. Comparison design

M0 freezes one bounded scene count and one real-to-synthetic sampling ratio. The generated frame
count must not exceed twice the eligible real training-frame count or 2,000 frames, whichever is
smaller. This keeps the first result diagnostic and locally reproducible.

Train exactly two new candidates from the same pretrained checkpoint:

1. **Control:** the frozen 0068 real training partition only.
2. **Synthetic addition:** the same real samples in the same order and with the same number of real
   exposures, plus the frozen synthetic samples at the fixed sampling ratio.

Keep the RF-DETR class, package, resolution, augmentation, optimizer, seed, threshold, early-stop
rule, and checkpoint-selection rule fixed. The synthetic candidate can use more optimizer steps
only for its declared synthetic batches. Report the added compute separately.

Select by the unchanged real validation partition. Run the 0068 sealed test once only if the
synthetic candidate passes the validation gate frozen in M0. Do not modify the generator from
validation or sealed-test failures inside this epic.

Report mask AP 0.50:0.95, mask AP50, box AP 0.50:0.95, instance recall, false detections, duplicate
detections, and empty prediction rate. Report real-frame slices by recording, card side,
visible-card count, occlusion, blur, glare, and frame-boundary clipping when reviewed support
exists. Synthetic metrics are diagnostics and cannot satisfy a real-data quality gate.

## 6. Delivery milestones

### M0 — Freeze the experiment and generator contract

- Audit the current 0068 manifest, materialization, bundle, and reports without changing them.
- Freeze asset eligibility, source-lineage rules, geometry limits, visible-mask rules, scene
  buckets, a maximum scene count, one sampling ratio, one seed, resource budgets, and stop rules.
- Pin the real-only control recipe and the paired validation gate before generating images.
- Define the annotation-effort pilot and its success threshold before model results are read.
- Write an immutable experiment manifest and a dry-run inventory of eligible training-only assets.

Acceptance:

- the manifest rejects any validation or sealed-test contributor;
- repeated audits over unchanged inputs produce the same digest;
- the dry run reports eligible cards, backgrounds, geometry examples, sides, and table setups;
- the manifest identifies the current proposal baseline and 0068 local detector by digest; and
- no rendering or training starts when a required input, permission, or digest is missing.

#### M0 implementation evidence — 2026-09-19

- Added the read-only `synthetic-visible-region` operations command and an immutable M0 manifest
  writer. The audit verifies the frozen 0068 source manifest, its training materialization, the
  retained local detector bundle, and the locked validation report before it records any input.
- The real audit is reproducible with manifest digest
  `3dc48add8caadd341772c7a15bbe5a208a19dab8debd342ab267eea942540ebc`.
- The dry run covers 15 training source groups, 537 real training frames, 1,535 real targets, 86
  eligible un-clipped four-corner card cutouts across 13 table setups, and 86 geometry examples.
  The eligible cutouts are 76 `face_up`, 10 `unknown`, and 0 `face_down`.
- The frozen inputs contain 0 explicitly reviewed empty backgrounds and 0 reviewed human occluder
  masks. Card-card occlusion remains the planned fallback, but a background and a face-down
  cutout are required for the declared scene buckets.
- The manifest records the current Gemini proposal contract digest and the 0068 local detector
  bundle digest `b3deef701e26d91ebfd9d357b4ff69b45ae9360e3722de340f1044214179df29`.
- Focused tests pass: 3 M0 campaign tests and Ruff checks. No rendering or training started.

### M1 — Materialize the reviewed generator inputs

- Add a small manifest workflow for operator-marked single-card and empty-background frames.
- Reuse complete reviewed visible regions when they meet the frozen cutout rule.
- Rectify card cutouts and materialize alpha masks, source quadrilaterals, and image facts.
- Build the table-setup-specific perspective library from training-only complete quadrilaterals.
- Materialize reviewed occluders only when eligible source masks exist.

Acceptance:

- every materialized asset links to an accepted source asset, exact frame, training source group,
  reviewed decision when required, and content digest;
- no clipped or occluded source card becomes a complete cutout;
- card rectification round-trips to the source quadrilateral within the frozen tolerance;
- empty backgrounds have explicit full-frame review coverage; and
- cold and warm materialization produce identical files and manifest digests.

### M2 — Implement deterministic synthetic rendering

- Implement projective card placement, z-order compositing, clipping, card-card occlusion, exact
  visible-mask calculation, and tight derived boxes.
- Add the frozen shadow and photometric effects with all random inputs derived from the scene seed.
- Emit one image, complete per-instance masks, COCO-compatible polygons or run-length masks, and a
  complete scene receipt.
- Add fixture scenes for overlap, a split visible region, frame clipping, full occlusion, mixed
  sides, and an empty background.

Acceptance:

- repeated rendering with the same inputs and seed is byte-identical;
- visible masks are disjoint and never contain higher z-order card or occluder pixels;
- derived boxes equal the exact mask bounds;
- a fully hidden or below-threshold card is omitted with an explicit receipt;
- changing one source digest invalidates the affected scene; and
- focused tests, formatting, linting, and type or static checks pass.

### M3 — Materialize and inspect the synthetic training set

- Generate the one M0 scene set and a disposable COCO training view.
- Merge it only into a copy of the 0068 train view. Keep validation and sealed-test bytes and
  annotations unchanged.
- Publish counts and distributions by table setup, source contributor, scene bucket, card count,
  side, scale, position, clipping, and occlusion.
- Render contact sheets with RGB scenes, instance colors, mask boundaries, and source lineage.
- Require one operator approval or rejection before training.

Acceptance:

- the merged view records separate real and synthetic counts and provenance;
- no synthetic image or contributor appears in validation or the sealed test;
- COCO validation accepts all images, masks, areas, and derived boxes;
- the report flags out-of-envelope geometry and duplicate or near-duplicate scenes;
- a random sample from every scene bucket is visually inspectable; and
- a rejected inspection closes the epic with evidence or requires a new epic, not an in-place
  recipe sweep.

### M4 — Run the paired RF-DETR comparison

- Train the real-only control and real-plus-synthetic candidate with the M0 recipes.
- Retain environment facts, logs, checkpoints, selected bundles, and item-level real validation
  predictions.
- Compare both candidates on the unchanged real validation partition.
- Run the sealed test once only when the synthetic candidate meets the frozen validation gate.
- Stop after the pair. Do not tune the generator or train another candidate.

Acceptance:

- both runs verify the same pretrained checkpoint, real dataset, real sample order, and recipe
  fields that are declared equal;
- the synthetic run verifies the exact M3 generator and dataset digests;
- all metrics reproduce from retained predictions;
- the report isolates added optimizer steps, duration, and peak resources; and
- the result states whether synthetic data improved, harmed, or did not clearly change real-frame
  visible-region quality.

### M5 — Measure correction effort and publish the decision

- Freeze a small batch of new development frames from source groups that did not contribute to
  training assets, validation, or the sealed test.
- Produce proposals from the current annotation baseline and the synthetic candidate in randomized
  order. Keep processor identity hidden during correction when practical.
- Record active correction time, accepted proposals, reshapes, additions, removals, missed cards,
  extra cards, and cards sent to a visible-card ignore region.
- Publish the model metrics, annotation-effort result, visual failures, domain-gap limits, and one
  decision: use as an optional annotation prefill, retain as an experiment, or discard.

Acceptance:

- both proposal sources use the same exact source frames and review contract;
- final reviewed visible regions remain human-authored maintained-reference data;
- timing excludes model execution and operator idle time;
- the report does not treat synthetic contributors as independent real coverage; and
- no provider is promoted and no runtime default changes in this epic.

## 7. Expected decision value

The generator is useful only if it improves the real annotation loop. High synthetic mask scores,
plausible contact sheets, or better training loss are not sufficient. The strongest positive result
is lower real-frame correction time with equal or better held-out mask quality. A neutral or
negative result is also useful: it stops further renderer work and leaves the reviewed real corpus
and 0068 detector unchanged.
