# Epic 0079 M0 review-first calibration gates

## Result

Spatial coverage and held-out boundary checks now report review warnings. They do not block a calibration with a valid fit and enough evidence. The candidate boundary straightness cutoff changed from 0.65 to 0.55. The review workbench now paints the fitted rounded outline when it has more than four points. Before this fix, it displayed the detector polygon in that case.

## Frozen comparison

The read-only comparison used the same 24 retained real results and ten synthetic cases as epic 0078. Reproduce it with:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py --output /tmp/0079-review-gates.json
```

| Measure | Before M0 | After M0 |
| --- | ---: | ---: |
| Published real calibrations | 4/24 | 24/24 |
| Passing fit quality | 22/24 | 24/24 |
| Passing held-out boundary check | 6/24 | 9/24 |
| Rejected as unstable boundary | 764 | 468 |
| Published synthetic cases | 10/10 | 10/10 |

The checks remain visible. Publication does not imply that every proposed card is accurate. The user can inspect and correct the virtual cards in review.

For `cardeventnet-event-img_0650-016`, the inspected `f678d010` result still rejects card `0004` as `unstable_boundary`: its straightness score is 0.158. Lowering the cutoff enough to admit this mask would admit much noisier boundaries generally. That frame still gets a published calibration and proposed scene from other evidence. Card `0002` is rejected at the frame boundary, and three other predictions lack quadrilateral support.

## Verification

- Focused calibration Python tests pass.
- The rounded outline workbench regression and published warning parser test pass.
- Ruff, Prettier, web typecheck, and lint on changed web files pass.
- Full web lint has two existing `react-hooks/set-state-in-effect` errors in `CardEventFrameSurface.tsx`, outside these changes.
