# Epic 0076 M2 occluded calibration candidates

## Result

The processor now rejects a card when another detected card covers more than 18% of its projected
full-card boundary and the target mask gives no support at that boundary. It checks the boundary
after the first fit and repeats the fit if a fit card is removed. It also rejects a mask with a
deep, localized inward notch. The notch check uses both defect depth (more than 12% of the card's
short side) and missing area (more than 6% of the convex hull). The processor schema is now v6.

The peer check uses the projected full-card outline, not the visible mask edge. A peer detection
counts as an occluder only where its mask covers the projected edge and the target mask has no
nearby support. This avoids treating duplicate or uncertain overlapping masks as proof that a
card is hidden. Each rejected card keeps its reason and measurements in the candidate evidence.

This change excludes incomplete observations from the fit. It does not infer hidden corners or
change the held-out error formula. A trial that ignored a detected peer's covered edge on the
worst example reduced the visible-edge median residual from 7.93 px to 2.28 px, but it still
failed the 2 px held-out median gate. The hidden part has too little evidence for a reliable fit
in this case.

## Inspected cards

The failed candidate `1b758231a51fc214188c77fcdf8a46998127a6a8dc65bb291b383881b813b78b`
comes from local revision `visible-cards-visible_cards-run-f678d010-5a3-attempt-1`.

| Source frame | Finding | Selection |
| --- | --- | --- |
| `cardeventnet-event-img_0650-014&t_us=25024023` | A peer card covers part of the projected edge. About 31% of perimeter samples have peer support without target-mask support. | Rejected as `occluded_by_card`. |
| `cardeventnet-event-img_0650-020&t_us=34783872` | The mask is imperfect, but the card has no projected peer overlap and passes its numerical held-out check. | Kept. |
| `cardeventnet-event-img_0650-035&t_us=71068705` | A thumb makes a concentrated inward notch. Its deepest defect is about 12.9% of the short side. | Rejected as `localized_inward_notch`. |

For this revision, selected candidates fell from 31 to 28. The worst held-out boundary distance
fell from 44.47 px to 14.59 px; held-out P90 fell from 9.97 px to 6.52 px. The held-out pass count
changed from 4/9 to 3/7. Spatial coverage changed from 0.24275 to 0.23725 on the x axis. The
held-out and spatial coverage gates still fail.

## Frozen comparison

Reproduce the comparison from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py \
  --output /tmp/0076-m2-baseline.json
```

Both runs used frozen manifest digest
`dd5509857ef69fbf391700623dea77b9780feeed0f9e77821d67ee9236627132`.

| Measure | Before M2 | After M2 |
| --- | ---: | ---: |
| Retained local results | 24 | 24 |
| Selected local candidates | 708 | 622 |
| Results passing held-out boundary gate | 5/24 | 5/24 |
| Results passing spatial coverage gate | 9/24 | 9/24 |
| Results passing fit quality gate | 22/24 | 22/24 |
| Mean fit median boundary error | 1.229 px | 1.150 px |
| Mean fit P90 boundary error | 2.263 px | 2.060 px |
| Mean held-out median boundary error | 2.431 px | 2.203 px |
| Mean held-out P90 / short side | 0.1164 | 0.0586 |
| Mean / maximum local call time | 3.391 s / 8.209 s | 3.417 s / 11.678 s |
| Published local results | 0 | 0 |

All ten frozen synthetic cases retain their prior outcome, including the expected failure for
10% shrink. The slowest local result needs a second full fit after occluded cards are removed.
The maximum call time now exceeds the prior 10-second frozen limit. No real result can publish
until independent full-card outlines are available for the frozen source frames. These boundary
metrics compare the fit against detector output, not against independent card outlines.

## Verification

- The two new regression cases cover a masked edge under another card and a deep inward notch.
- Calibration and refinement tests: 37 passed.
- Ruff lint and formatting checks pass for the changed Python files.
- The frozen comparison completed for 24 local revisions and ten synthetic cases.
