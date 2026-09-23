# Epic 0075 M5 view-edge distortion decision

## Result

The shared homography passes the frozen view-edge gate on known geometry. The current local data
does not establish lens distortion. It contains high edge residuals, but the source frames have no
independent full-card outlines. The residuals cannot separate camera distortion from detector-mask
error or fit error. No separate lens-correction epic is justified by this evidence.

## Frozen M0 comparison

Reproduce from the repository root:

```sh
mise exec -- uv run --project operations python operations/scripts/card_plane_calibration_baseline.py \
  --output /tmp/0075-m5-baseline.json
```

The comparison used manifest
`dd5509857ef69fbf391700623dea77b9780feeed0f9e77821d67ee9236627132`. It evaluated 24 local result
revisions and ten known-geometry synthetic cases. All 24 local results retain a diagnostic fit
candidate and fail publication. The real-data set still has no independent full-card outlines.

The synthetic `edge-of-view` case has two independent held-out full-card outlines in the view-edge
region. Their p90 boundary distance is 0.419% of card short-side length, below the 3% limit. The
clean case's view-edge p90 is 0.305%; the increase is 0.114 percentage points, below the 1-point
limit. The full edge-of-view case has three independent held-out outlines, and its aggregate
full-card reference metrics pass the frozen boundary and size checks. All three detector-boundary
holdouts also pass their separate fit-consistency gate. This shows that the homography can meet the
frozen view-edge gate when the outlines are known.

The separate held-out detector-boundary metric is 1.053% for the edge region in the edge-of-view
case and 0.983% for the clean case. All three detector-boundary holdouts pass. These values measure
fit consistency against the input polygons; they are not the independent full-card outline gate.

## Local regional residuals

Eleven local result revisions have held-out view-edge predictions, with 38 edge predictions across
nine recording IDs. Ten revision summaries have normalized detector-boundary p90 residuals above
3%. Per-revision edge sample counts range from one to ten. Some edge medians exceed their center
medians; others are lower.
For example, one revision has 17.76 px at the edge and 2.64 px at the center, while another has
2.03 px at the edge and 2.91 px at the center.

These comparisons use held-out detector polygons, not independent card outlines. The 3% comparison
above is descriptive and does not apply the M0 full-card outline gate to detector masks. The
distances are unsigned, and several regional groups have only one or two edge observations. They
cannot show whether the error points radially, whether it belongs to the camera model, or whether a
lens model would improve held-out full-card geometry. Real-data view-edge acceptance remains
pending.

## Decision

The controlled edge-of-view case passes, so the homography meets the measurable M0 view-edge gate.
The local residuals do not justify a separate mapping model without independent outline evidence. If
future full-card references show a consistent regional error that the homography cannot meet on
held-out groups, create a separate epic. That epic must version the mapping contract and cover every
projection consumer named in M5.

## Reproducibility

- Frozen manifest digest matches the M0 baseline.
- All 10 synthetic cases produce matching repeat-run digests.
- Mean and maximum local calibration times are 2.479 s and 7.817 s. The maximum synthetic call is
  0.608 s. These remain below the frozen 10 s and 2 s limits.
