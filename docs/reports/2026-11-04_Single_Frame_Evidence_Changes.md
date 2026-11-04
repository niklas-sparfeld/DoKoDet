# Single-frame evidence changes

## Scope

This experiment uses detector revision
`visible-cards-visible_cards-run-5f4f8c72-78b-attempt-1` and calibration
`calibration-650baf3fcd4cba31ef04d9a2` for `game-2026-08-20-01-005`. It uses each frame alone.
It does not update the detector revision, calibration, review, or selected revisions.

The initializer keeps source suggestions. It groups near-identical masks and fits one pose per
group. It retains less-identical contained masks as uncertain alternatives. A weak candidate can
use stronger candidates as occluders. It cannot occlude them, change their poses, or choose their
order. The combined evidence score is a heuristic. It is not a calibrated probability.

The detector score threshold of 0.7 and mask thresholds are provisional. A missing detector score
is recorded as missing. The old crop-review revision does not contain detector scores. New
crop-review runs record the selected prediction score. This score is not an independent appearance
classifier. No appearance model was trained or evaluated in this change.

## Local replay

The local diagnostic replay used frames 000000, 000003, 000007, 000021, 000022, 000023, 000026,
000029, 000030, 000031, and 000039. It kept the saved calibration. It did not make review decisions.

- Frame 000003: three highly overlapping top-card masks produce one representative. The other
  suggestions remain in the diagnostics. The two other original card poses remain close to their
  earlier positions.
- Frame 000021: the contained candidate is retained with low confidence. It does not control
  the stronger candidates' occlusion or joint search.
- Frames 000000 and 000031: the background candidate receives a low geometric fit score.
- Frame 000030: isolated refinement retains the earlier partial-card poses in this replay.
- Frame 000039: the tissue-box candidate still has a high geometric fit score. The saved detector
  revision has no detector score. The current change cannot identify it as weak appearance.
- Frames 000022 and 000023: the malformed arm and clipped card are not reliably corrected. The
  source image border is excluded from occlusion-refit edge evidence, but this is not a robust
  partial-card fitting solution.

The source masks and the images have not been independently labeled for this experiment. These
observations do not establish accuracy, score calibration, or general thresholds. Test the proposed
thresholds on independently inspected false positives, partial cards, and overlapping cards before
broad use. Evaluate a separate appearance check and robust fitting of contaminated masks in later
work. Do not use temporal evidence for this experiment.

## Additional review cases

The user reported these cases after the first replay. The observations refer to saved local review
drafts. Card numbers are positions in each saved scene. The detector revisions are:

- `cardeventnet-IMG_0636`: `visible-cards-visible_cards-run-aadd6e6e-36e-attempt-1`.
- `cardeventnet-IMG_0645`: `visible-cards-visible_cards-run-76389fc9-d85-attempt-1`.
- `cardeventnet-IMG_0096`: `visible-cards-visible_cards-run-a7275b98-6fd-attempt-1`.
- `cardeventnet-IMG_0097`: `visible-cards-visible_cards-run-f9b6c6cf-577-attempt-1`.

Masks below were rasterized at approximately half or quarter image resolution. Containment is the
intersection divided by the stated candidate's area. The observations are development evidence,
not reviewed reference labels or an accuracy measurement.

| Frame | Observation |
| --- | --- |
| `IMG_0636-026` | Card 3 is 99.8% inside card 2; mask IoU is 0.747. The initializer retains it as a weak contained alternative. |
| `IMG_0645-006` | Card 2 is offset. Occlusion refit and joint search did not move it. The initial mask fit score is 0.897. The source-polygon vertex median seeds table x at -0.010; the default search reaches -0.660 at its limit. An image-space shift of about -12 pixels gives a 0.965 mask score. A separate run with center search radius 0.6 reaches 0.964. These scores describe detector-mask agreement, not reviewed pose accuracy. |
| `IMG_0645-007` | Card 3 is 97.9% inside card 4, IoU 0.258. Card 5 is 99.6% inside card 1, IoU 0.147. Each has a short, partial shape with a straight boundary. |
| `IMG_0645-036` | Card 3 is 99.8% inside card 2, IoU 0.271. It has a short, partial shape with a straight boundary. |
| `IMG_0096-000` | User identifies card 2 as a non-card. Its RF-DETR score is 0.703613, just above the provisional 0.7 cutoff. Its fit score is 0.940625. It is currently treated as strong. |
| `IMG_0096-043` | Card 6 is 97.3% inside card 2, IoU 0.547, and is a weak contained alternative. The user judges card 3's segment bad but its fitted pose near perfect. |
| `IMG_0097-036` | Card 3 is fully inside card 2 at this raster resolution, IoU 0.412. The partial mask has a long straight edge. |

The current contained-alternative rule also requires IoU at least 0.5. It misses the four small
partial masks in `IMG_0645-007`, `IMG_0645-036`, and `IMG_0097-036`. Test stronger containment and
straight-edge evidence, with positive controls for real partially occluded and disconnected cards.
Do not assume a straight edge proves a crop artifact. Record crop provenance before attributing the
edges to a crop. Preserve original masks and uncertain evidence when testing suppression.

### IMG_0661 additional cases

Review `visible-cards-ad892652db4648768bdb58fd2e6662fe` uses detector revision
`visible-cards-visible_cards-run-c5bbcdaf-6da-attempt-1` and proposal revision
`card-scene-proposals-card-scene-proposal-1793788415833-attempt-1`.

- `IMG_0661-003`, card 3: the user reports a rotated fit. Its mask is a visible part of a card
  under another card. The initial fit and published fit have the same pose in an exact-input probe.
  The initial score is 0.497; the saved occlusion-refit score is 0.812. These scores use different
  evidence and cannot be compared as calibrated confidence. The refit removes 42.4% of the mask
  boundary. The high score does not establish that the rotation is correct.
- `IMG_0661-027`, card 4: its mask is fully contained in card 1 at the measured raster resolution;
  IoU is 0.080. Its fit score is 0.376 and it is already weak. The mask has a long straight edge.
- `IMG_0661-028`, card 6: 99.9% of its mask is inside card 2; IoU is 0.277. Its fit score is
  0.470 and it is already weak. The mask has a long straight edge.
- `IMG_0661-028`, card 3: 85.4% of its mask lies inside card 5, and it also has a long straight
  edge. Its fit score is 0.498, just above the current 0.48 threshold. Its overlap is less complete
  than the other fragment cases; this is a useful ambiguous control.

## Follow-up implementation: v8

The v8 initializer tests highly contained small masks for a long axis-aligned edge inside a
stronger mask. Strong matches use one pose and retain both original suggestions and a decision
record. Less certain contained masks remain as weak alternatives. The thresholds are provisional;
the observed straight edge does not prove crop origin or guarantee that two masks are one card.

When the initial position search reaches its limit and has a low enough mask score, it tries the
mask-area centroid and, if needed, an expanded bounded search. The exact `IMG_0645-006` card 2
fixture uses the area seed and improves its detector-mask score from 0.897 to 0.966. This score
does not establish pose accuracy.

Partial and clipped-card fits can retain two orientation hypotheses, their scores, and a
provisional ambiguity flag. Initial mask-fit and occlusion-refit scores are recorded separately.
These diagnostics are not calibrated confidence. The `IMG_0661-003` rotation is still unresolved;
its competing orientation scores are close enough to mark the fit ambiguous. The user-approved
`game-2026-08-20-01-001` frame 000012 remains covered by its existing pose and order regression.

Local replays with the saved calibrations recognized the reported small fragments in
`IMG_0645-007`, `IMG_0645-036`, `IMG_0097-036`, `IMG_0661-027`, and `IMG_0661-028`. The
less-identical alternatives in `IMG_0636-026` and `IMG_0096-043` remained available. The original
pose for `IMG_0096-043` card 3 was unchanged in this replay. These development frames do not
measure false suppression; independently inspect additional real partial and disconnected cards
before broad use. No sealed evaluator or temporal input was used.
