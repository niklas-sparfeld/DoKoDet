# Synthetic visible-region training data

## Plan status

- **Summary:** Build a deterministic local generator that composites reviewed card cutouts onto
  real table backgrounds with table-setup-specific perspective, exact visible-region masks, and
  controlled occlusion. Measure whether the added training data reduces visible-card correction
  work on real frames.
- **Status:** In Progress
- **Depends on:** 0048, 0049, 0065, and 0068 complete
- **Outcome:** A reproducible synthetic-data generator, one bounded RF-DETR training comparison,
  and a measured decision about using its candidate as an annotation prefill. Synthetic data does
  not enter validation or the sealed test and does not change a runtime default.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — the deterministic contract and dry-run audit are frozen, but the input gate
  found no reviewed empty background and no eligible face-down card cutout.
- **M1:** Complete with a declared gap — 165 card cutouts, one reviewed 0669 background, and a
  setup-matched one/two-card geometry library are materialized; no face-down cutout is available.
- **M2:** Complete with a declared gap — deterministic rendering uses the measured 0669 card
  templates and exact visible-region targets for face-up and unknown cards; face-down and
  mixed-side buckets are omitted.
- **M3:** Complete with a declared gap — one deterministic scene per supported bucket is merged
  into a disposable train-only COCO view and approved after contact-sheet inspection; face-down
  and mixed-side buckets remain unavailable.
- **M4:** Preflight ready — the paired real-only versus real-plus-synthetic run is prepared; full
  training remains operator-started and was not started here.
- **M5:** Appearance review in progress — the earlier card-bearing-frame/inpainting pools and the
  lighting-first samples are superseded. A bounded three-scene review set uses only the accepted
  full-frame-reviewed empty training table. It estimates one metric table-plane transform from
  several reviewed cards in the same recording, then renders upright supplied deck scans with a
  transparent rounded edge, one table-level card-paper response, reduced saturation, reduced
  card-scale blur, a subtle drop shadow, and exact overlap masks. Do not generate a larger pool or
  add random scene effects until operator inspection approves the samples.
- **M6:** Not started — measure annotation correction effort and publish the decision.

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

Use the frozen 0068 training partition for the real comparison. M1 may add a separately digested,
operator-reviewed, training-only source group to the synthetic card pool. A card cutout,
background, occluder, geometry sample, or measured image distribution from validation or the sealed
test is a data leak and must stop the run.

Synthetic scenes are training samples only. They are not reviewed source frames, maintained
references, independent source groups, validation samples, or sealed-test samples. Every generated
sample records all real source groups that contributed pixels or geometry. It inherits the most
restrictive source permission of those inputs.

The renderer may proceed with available face-up and unknown cards. A reviewed face-down cutout is
required before the face-down or mixed-card-side buckets can render.

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

Use only table backgrounds from explicitly marked frames with no visible physical card. The mark
must cover the complete frame. Missing visible-card annotations do not prove an empty background.
Card-bearing frames can provide measured geometry or lighting references. They must never be used
as rendered backgrounds, and the renderer must not inpaint their card regions.

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

The geometry-review generator uses the complete reviewed rectangles from one recording and table
setup to estimate one metric table-plane homography. It identifies each card's adjacent short and
long sides, constrains their ratio to the known card ratio, averages the accepted measurements,
and rejects geometric outliers. It then lays canonical rectangles out in that plane and projects
them into the explicit reviewed empty frame. This is sufficient for perspective-correct planar
placement and exact card-card occlusion. It does not identify unique camera height, distance, or
intrinsics.

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

Apply geometric changes to images and masks together. First white-balance every card cutout to a
neutral card-paper reference. Then estimate one lighting profile from known card pixels in the
selected reference scene and apply that same profile to every card in the synthetic scene. Apply
scene variation after compositing to the complete image, so exposure, whitepoint, contrast, and
shadow conditions remain consistent across all cards and the table. Apply photometric changes only
after target geometry is fixed. Keep effects within distributions measured from real training
frames. Use a small edge treatment and shadow model so the detector cannot solve the task from
paste seams.

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

#### M1 implementation evidence — 2026-09-19

- Added `synthetic-visible-region-materialize`. It uses fixed OpenCV dark-surface extraction for
  the three 4x5 JPEG grids and the 19 individual HEIC photos. Canny edges select the card-owned
  outer contour, the high-luminance surface mask fills the contour, and a canonical rounded
  corner mask removes table pixels at the four rectified corners. HEIC decoding records the local
  `sips` version. No card identity is inferred.
- The materialization reuses 86 complete reviewed 0068 training cutouts and adds 79 supplied
  deck-photo cutouts. It records 108 source assets, 165 RGBA cutouts, 165 alpha masks, source
  quadrilaterals, source-frame digests, review decisions, and the 13-table-setup 0068 geometry
  examples.
- The supplied 0669 empty frame is accepted as one full-frame reviewed background. Both 0646
  links are retained as explicit exclusions because their source group is `sealed_test`.
- Inventory: 155 `face_up`, 10 `unknown`, 0 `face_down`, 1 background, and 0 human occluders.
  The remaining face-down input gate is explicit; no synthetic rendering or training started.
- The edge-corrected M1 manifest digest was
  `f05bbd0951fbb525dd3f6a3ce6b62b3bcfb64107a3b3b081132388b009b45db4`.
  The materializer records mask recipe `opencv-dark-surface-canny-rounded-v2` with a canonical
  28-pixel corner radius. All rectification round trips are 0.0 pixels, all generated alpha
  masks keep the dark card artwork opaque, and the cold/warm check produced identical manifest
  and representative file digests.
- Added 140 exact-four-corner one- and two-card geometry references from the frozen training
  source manifest. The renderer matches them to the background recording and table setup before
  it uses any legacy geometry example. The 0669 white-table background has 11 matching references
  across single-card and two-card frames; their source event, card count, side, annotation kind,
  and normalized quadrilaterals are retained in the M1 manifest.
- The regenerated default M1 manifest digest is
  `0a55438cf162fb76d1357f3304fe53cb1f43760f2276992fb12be7217e41f0e1`.
- Added 6 focused M1 tests. They pass with the M0 campaign tests: 6 passed. Ruff passes.

### M2 — Implement deterministic synthetic rendering

- Implement projective card placement, z-order compositing, clipping, card-card occlusion, exact
  visible-mask calculation, and tight derived boxes.
- Add the frozen shadow and photometric effects with all random inputs derived from the scene seed.
- Emit one image, complete per-instance masks, COCO-compatible polygons or run-length masks, and a
  complete scene receipt.
- Add fixture scenes for overlap, a split visible region, frame clipping, full occlusion, mixed
  sides, and an empty background. Record unavailable face-down and mixed-side fixtures as explicit
  omissions when the input gate is incomplete.

Acceptance:

- repeated rendering with the same inputs and seed is byte-identical;
- visible masks are disjoint and never contain higher z-order card or occluder pixels;
- derived boxes equal the exact mask bounds;
- a fully hidden or below-threshold card is omitted with an explicit receipt;
- changing one source digest invalidates the affected scene; and
- focused tests, formatting, linting, and type or static checks pass.

#### M2 implementation evidence — 2026-09-19

- Added `synthetic-visible-region-render` with fixed-seed OpenCV projective placement, z-order
  compositing, frame clipping, card-card occlusion, shadows, bounded photometric effects, exact
  binary visible masks, derived boxes, COCO annotations, and per-scene receipts.
- The renderer uses the reviewed 0669 background and the corrected training-only M1 cutouts. It records every
  card and background source group, source digest, placement quadrilateral, z-order, clipping,
  occlusion ratio, output digest, and omitted-instance receipt.
- It now selects geometry references by background recording and table setup. Single-card scenes
  use the measured card quadrilateral. Two-card scenes use the measured pair before applying only
  small bounded jitter. Each receipt records the source event and selection policy. This removes
  the earlier cross-table translation of unrelated card shapes.
- The real smoke set contains 8 scenes, 8 images, and 11 annotations. COCO validation passes.
  It includes fully visible, separated, shallow/medium/heavy overlap, frame clipping, blurred or
  glare-affected, and reviewed-empty-background scenes.
- Face-down and mixed-side buckets are explicitly omitted because M1 has no face-down cutout.
  No face-down pixels or labels are fabricated.
- The current real M2 manifest digest is
  `d1f34c1cfb02b2754c36a16e0246a3db69144c20fdeaadfcb944001fcb20f283`.
- Added a focused geometry-template regression assertion. Ruff and the M2 test module pass.

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

#### M3 implementation evidence — 2026-09-19

- Added `synthetic-visible-region-training-view`. It regenerates the frozen M2 scene set with one
  scene per currently renderable bucket, then merges it into a copy of the 0068 train view. The
  0068 validation and sealed-test directories are copied and verified byte-for-byte; no synthetic
  image or contributor enters either partition.
- The disposable view contains 537 real train images and 1,535 real annotations plus 8 synthetic
  images and 11 synthetic annotations. The merged train view has 545 images and 1,546
  annotations. Synthetic image and annotation IDs are rebased, and each retained row records
  scene bucket, card source, source-group lineage, and the M2 scene manifest digest.
- The report publishes distributions for table setup, source contributor, scene bucket, card
  count, side, scale, position, clipping, and occlusion. It flags 13 average-hash near-duplicate
  pairs, reports no exact duplicate groups, and reports one expected out-of-frame geometry from
  the declared frame-clipping bucket with zero unexpected out-of-envelope geometry.
- The contact sheet contains RGB scenes, colorized instance masks, mask boundaries, and source
  lineage for all eight supported buckets. The local visual inspection is recorded as approved in
  `.runtime/synthetic-visible-region-0070-m3/inspection/approval.json`.
- The M3 manifest digest is
  `c86d210c5910e62017a940f202df755b17639db0f53754e162d2cc70f9fc25d7`. The merged train COCO
  digest is `cffd20504b481981634f34abf79b4f7fff03882b1c16d5f0a4ed66d0225ec1e1`.
- Focused campaign, materialization, rendering, and M3 tests pass: 9 tests. Ruff and
  `git diff --check` pass. No RF-DETR training started.

#### M4 preflight evidence — 2026-09-19

- Added the bounded M4 comparison command and a `--preflight-only` mode. The preflight validates
  the frozen 0070 recipe, the 0068 manifest and checkpoint digest, M3 approval, the merged train
  COCO digest, and the unchanged validation and sealed-test inventories.
- The candidate view is ready at `.runtime/synthetic-visible-region-0070-m4` with materialization
  digest `2c17d026d8acc028957d6363927a5cdba278b89ceb38d57c1127c2c844b6c062`. It contains 545
  train images, 1,546 train annotations, 143 validation images, and 104 sealed-test images. The
  one approved empty-background scene is retained as a train-only negative image.
- Both candidates are pinned to RF-DETR SegMedium 1.9.4, the checkpoint digest
  `3ad325094735f431aee9962a8d204d68eb5bfc393d53e7e836e70998fef5ea58`, seed 7001, 40 epochs,
  effective batch size 4, MPS, no mixed precision, and the frozen 0070 two-candidate budget.
- The training loader now accepts only the declared synthetic `reviewed_empty_background` train
  image without a target. It still rejects empty validation or sealed-test images and all other
  unlabelled images.
- Focused tests pass: 12 tests and Ruff checks. Full RF-DETR training and evaluation were not
  started by operator instruction. M4 acceptance remains pending the two local runs.

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

### M5 — Find table geometry and synthesize every training recording

- Audit all frozen 0068 recordings for corrected exact four-corner one-, two-, and three-card
  frames.
- Rank candidates by human-corrected geometry, interior margin, card shape, and overlap. Keep the
  selected candidate and the complete audit in an immutable manifest.
- Use only explicit full-frame-reviewed empty training tables as rendered backgrounds. Use one
  selected candidate per available card count for each empty table's matched recording and table
  setup. Use card-bearing frames only for measured quadrilaterals and known-card lighting profiles;
  never inpaint them or copy their background pixels.
- White-balance all eligible M1 cutouts before projective placement. Apply one shared card-lighting
  profile per scene, then one scene-level lighting condition to the complete composite. Do not
  randomize photometric effects independently per card.
- Emit exact masks, COCO annotations, per-scene receipts, source lineage, and photometric effects.
- Keep validation and sealed-test recordings in the discovery report only. Do not start RF-DETR
  training in this milestone.

Acceptance:

- all recordings are audited with stable candidate counts and selected one-, two-, and three-card
  geometry where available;
- synthetic scenes use training recordings and training-only M1 card cutouts;
- validation and sealed-test recordings produce no synthetic training image or annotation;
- repeated synthesis produces valid COCO with unique image IDs and exact visible masks; and
- the manifest records the inpainting policy and the declared held-out-data gap.

#### M5 implementation evidence — 2026-09-19

- Added `synthetic-visible-region-all-recordings`. The discovery pass audits all 24 recordings and
  retains 235 eligible corrected-reference candidates: 169 train, 43 validation, and 23 sealed
  test. The selection is deterministic per recording and card count.
- The synthesis pass materializes 38 scenes from all 15 training recordings: 14 one-card, 12
  two-card, and 12 three-card scenes, with 74 annotations. It uses the selected reviewed frame as
  the geometry source, inpaints only its card quadrilaterals with OpenCV, and composites the
  training-only M1 cutouts with exact z-order masks.
- Validation and sealed-test recordings remain `discovery_only`; no held-out image or annotation
  enters the generated COCO view. Face-down cards remain unavailable because M1 has no reviewed
  face-down cutout.
- The generated COCO view passes the repository validator. The focused M5 tests pass, and the
  command does not invoke RF-DETR training.
- Added explicit `--candidate-policy`, `--variants-per-candidate`, `--max-card-count`, and
  `--geometry-reference-frame-count` controls. The original 38 scenes remain the conservative
  baseline. The new ratio-comparison pool uses all 182 strict train geometry candidates with
  three deterministic variants each: 546 images and 999 annotations. It selects three valid
  train-only reference frames for each of 14 table setups and uses their robust card-shape
  estimate to regularize the projective placement. The pool contains 39 four-card scenes.
- The merged view contains 1,083 train images, with 50.42% synthetic images, and keeps the
  validation and sealed-test partitions unchanged. Its materialization digest is
  `1b31edf634996c00c29250abddfd7ab690dd2a77b29680c9579ab22a0ae02e72`.

#### M5 revised empty-table sample evidence — 2026-09-19

- Added `synthetic-visible-region-empty-table`. It rejects every background unless M1 records an
  accepted full-frame review with `contains_visible_card=false` and a training source group.
  Card-bearing source frames are never rendered or inpainted.
- The bounded sample command materialized 165 white-balanced training cutouts and six scenes on
  the single accepted empty `IMG_0669` table. It contains two one-card, two two-card, and two
  three-card scenes. The COCO output validates with exact disjoint masks.
- Each scene uses a known-card lighting reference from the matching reviewed `IMG_0669` frame.
  The reference produces one shared card-lighting profile for all cards in that scene. Exposure,
  color gains, contrast, vignette, shadow opacity, and JPEG quality are sampled once per scene and
  applied consistently to the complete composite.
- The sample output is at
  `.runtime/synthetic-visible-region-0070-empty-table-samples`; no larger synthetic pool or new
  training run was started. The earlier card-bearing-frame/inpainting pools are superseded and
  must not be used for the next training comparison.
- Focused tests pass: the new empty-table synthesis tests and Ruff checks. Operator approval is
  still required before scene-limit 0 or a larger pool is allowed.

#### M5 planar-geometry review evidence — 2026-09-19

- Added `synthetic-visible-region-planar-geometry`. It uses only explicit reviewed empty training
  frames as rendered backgrounds. It never inpaints or renders a card-bearing source frame.
- For `IMG_0669`, the calibration reads 22 complete reviewed card rectangles from the matching
  recording and table setup. It accepts 19 and rejects 3 robust outliers. The accepted rectangles
  give a normalized long-side size of 1.531, median right-angle error of 2.107 degrees, median
  aspect error of 0.0346, and median parallel-edge error of 0.0339.
- The command writes three bounded review scenes: one observed-pose card, two overlapping cards,
  and three overlapping cards. Its source scans use a feathered rounded alpha matte. This removes
  the scan bed and dark perimeter before projection. The mask threshold follows the same alpha
  boundary, so rounded card corners remain in the training targets.
- It resolves eight face-up reviewed card regions from four exact `IMG_0669` frames. Bright,
  low-saturation card-paper pixels give one median table response of BGR `229/238/238`. The same
  response white-balances every scan in the scene. The scan saturation factor is `0.68`. Card-scale
  Gaussian blur uses 42 percent of the earlier strength and is limited to `0.22–0.58` pixels. A
  `0.09` opacity contact shadow has a one-pixel offset and `0.55` pixel blur. Each card is warped
  at two times its local output resolution, then area-downsampled to reduce aliasing on diagonal
  ink and card edges. The renderer does not add glare, random per-card lighting, or a scene-level
  lighting change.
- Geometry review now uses only the supplied upright face scans in
  `data/decks/ass-altenburger-romme-french/source`. It does not use video-derived card cutouts.
  The selected scans include `SPADES_ten` and `HEARTS_jack`; the renderer resizes them to the
  canonical card rectangle without changing their orientation before it applies table placement.
- The current output is at
  `.runtime/synthetic-visible-region-0070-planar-geometry-antialiased-samples`. No larger pool or
  training run was started. Operator approval of the appearance and geometry is required before
  expansion.

### M6 — Measure correction effort and publish the decision

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
