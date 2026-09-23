# Epic 0077 M0 rounded physical card outlines

## Radius and geometry

The 57 local PNG cards in `data/decks/ass-altenburger-romme-french` are 787 pixels wide. At alpha
128, a circle fitted to each upper-left edge gives a median radius of 68.25 pixels. The 10th and
90th percentiles are 66.05 and 70.35 pixels. The shared model rounds this to a radius of `0.087`
times the short side.

The card pose still has four virtual corner intersections. A sampled full-card outline sits inside
those corners. The calibration fit and held-out check compare observed boundaries with that outline.
Frame and peer-occlusion checks, review overlays, and pose-derived visible-region masks also use
it. The geometry and boundary-fit method versions are v3, the calibration processor version is v7,
and the region derivation recipe version is v2. The radius is part of the geometry contract manifest.

The local deck images are not in Git. The measured ratio is frozen in the geometry contract so
normal development and processing do not depend on those files.

## Frozen calibration comparison

Reproduce the comparison from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py \
  --output /tmp/0077-m0-rounded-baseline.json
```

Both runs used frozen manifest digest
`dd5509857ef69fbf391700623dea77b9780feeed0f9e77821d67ee9236627132`.

| Measure | Before M0 | After M0 |
| --- | ---: | ---: |
| Retained local results | 24 | 24 |
| Selected local candidates | 622 | 614 |
| Results passing held-out boundary gate | 5/24 | 6/24 |
| Results passing spatial coverage gate | 9/24 | 9/24 |
| Results passing fit quality gate | 22/24 | 22/24 |
| Mean fit median boundary error | 1.150 px | 1.145 px |
| Mean fit P90 boundary error | 2.060 px | 2.112 px |
| Mean held-out median boundary error | 2.203 px | 2.184 px |
| Mean held-out P90 / short side | 0.05862 | 0.05749 |
| Mean / maximum local call time | 3.417 s / 11.678 s | 3.776 s / 13.071 s |
| Published local results | 0 | 0 |

The held-out gate improves on one result and loses none. Mean held-out error improves slightly,
while fit P90 and runtime worsen slightly. All ten frozen synthetic cases keep their prior outcome.
The inspected `f678d010` revision selects 27 candidates instead of 28; its worst held-out error
falls from 14.59 px to 12.61 px. Its held-out and spatial coverage gates still fail.

All 24 real results remain unpublished because independent full-card outlines are unavailable for
the frozen frames. The local metrics compare against detector boundaries rather than those
independent outlines.

## Verification

- Geometry checks cover the rounded edge, its virtual corner gap, and the derived region mask.
- Relevant calibration, geometry, initialization, refinement, and proposal tests pass.
- Ruff lint and formatting checks pass for the changed Python files.
- The frozen comparison completed for 24 local revisions and ten synthetic cases.
