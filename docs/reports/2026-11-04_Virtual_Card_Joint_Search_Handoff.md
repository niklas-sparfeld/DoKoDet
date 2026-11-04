# Virtual-card joint search handoff

## Scope

The user approved the current experimental result for frame `event-000012` and asked to use the
algorithm on `main`. This is an algorithm change. It is not a claim of general model accuracy.
No human decision is required at runtime. Scene scores and ambiguity are evidence for downstream
confidence, not calibrated probabilities.

## Implementation

`card_scene_joint_fit.py` searches alternative card positions, quarter-turn orientations, and local
front-to-back order swaps for overlapping proposed cards. It skips frames with more than eight
cards. The search uses source masks at one-eighth
resolution, a beam of three, and at most two changed cards. It scores the mean visible-mask IoU for
the whole scene. The search considers only overlaps present in the initial fitted scene.

For selected changed cards with a front occluder, the fine search uses quarter-resolution masks,
a 32 source-pixel exclusion margin, 1-degree angle steps from -2 through +9 degrees, and position
steps of 0.025 of the card's respective axis. It gives equal weight to mask IoU and two-way edge alignment, with clipped edge
distances. Its input boundary may still contain detector errors or unmodeled occluders. Area
agreement still contributes near the occlusion. The search retains the original scene when the
final scene's coarse mask score is worse than the baseline.

The initializer records the recipe version `fixed-card-pose-joint-search/v6`, search parameters,
scene score, baseline score, changed poses, order, and a beam score margin. The margin is calculated
before edge refinement; it is not a probability. The fit diagnostic residual for a changed card uses
the joint-scene score, as stated in the run diagnostics. A score or margin is not reviewed truth.
The existing detector and calibration inputs are not modified. Existing proposals are immutable;
new runs use the new recipe.

## Development evidence

The retained local detector revision is `visible-cards-visible_cards-run-crop-review-20261103-attempt-1`.
The source proposal is `card-scene-proposals-card-scene-proposal-1793741954253-attempt-1` for
`game-2026-08-20-01-001`. The saved scene has card 4 rotated and uses order 1 → 3 → 4 → 2.
The exact-lineage fixture at `operations/tests/fixtures/card-scene-event-000012-pose-order.json`
records the source, masks, calibration, and earlier comparison. The runtime regression expects the
new card-4 center near `(1.203976, 1.047226)`, angle `49.366157` degrees, and order
1 → 4 → 3 → 2. The user judged the fine-search frame-12 pose perfect. This is one human observation,
not an accuracy study.

Before integration, a separate exploratory one-eighth-resolution search changed seven of 49 frames.
Its mean per-frame detector-mask IoU rose from 0.924 to 0.930. In frames 000029, 000030 and 000035,
it found translated or rotated alternatives. It searched one selected region of the space and its
score rewards agreement with detector masks. It cannot establish correctness or generalization.
The local visual artifacts are under
`/Users/niklas.sparfeld/.codex/visualizations/2026/11/03/01a1a35f-31ad-7911-bb25-debf4764f2b3/calibration-1793741954253/`.
They are local diagnostics, not versioned source data.

## Next work

1. Run the current implementation on the exact 49-frame recording and inspect changes, especially
   frames 000012, 000029, 000030 and 000035 and all other changed frames. Compare exact detector
   revisions, not regenerated approximations. Record runtime and peak memory.
2. Test additional recordings with reviewed or independently inspected geometry, including correct
   partially occluded cards, disconnected masks, duplicates, image boundaries, and unmodeled hands.
   Report regressions and retain uncertainty. Do not use the 0092 sealed final test.
3. Measure whether the bounded search misses cases where initial poses do not overlap, where more
   than two poses need changes, or where a local order swap cannot reach the correct order. Compare
   the final score and its pre-refinement margin; do not call either calibrated confidence.
4. Inspect edge exclusion and area scoring when detector masks miss visible pixels. Evaluate margin
   scaling across resolutions, edge sample sufficiency, and incomplete segmentation. Make any
   further policy changes from measured evidence, not frame 000012 alone.
5. Verify the downstream consumers of the new recipe and diagnostic schema. Check cache and refresh
   behavior and the cost of long searches before broad batch use. Do not alter closed historical
   audits or previously published proposal revisions.

## Verification

- `uv run --project operations --group dev pytest operations/tests/test_card_plane_initialization.py -q`: 15 passed.
- `uv run --project operations --group dev pytest operations/tests/test_proposed_card_scene_processor.py -q`: 14 passed.
- Ruff checks passed for the initializer, joint-search module, and initializer tests. The new
  joint-search module passed the Ruff format check.
- The exact frame-12 initializer replay took approximately 32 seconds on the development Mac.
  This includes the existing pose fitter. No full-recording production replay has been run with
  the integrated change.
- The exact staged initializer and tests also passed in an isolated package copy: 12 passed. The
  difference is three pre-existing unstaged performance tests, which were not included in this commit.
