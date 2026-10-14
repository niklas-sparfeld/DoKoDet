# 0092 M1 reviewed mask materialization

Date: 2026-10-14

## Result

M1 is complete. The frozen M0 manifest digest is
`bd452cc3f904007ed481af1f13b56e3910374c0d9392dfbf42de900379e741fa`. The materialized COCO view
contains the same 20 recordings and 20 source groups.

| Partition | Recordings | Frames | Visible-card masks | Pile masks | Total masks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Train | 16 | 684 | 1,835 | 170 | 2,005 |
| Validation | 2 | 98 | 270 | 87 | 357 |
| Sealed test | 2 | 92 | 247 | 105 | 352 |
| Total | 20 | 874 | 2,352 | 362 | 2,714 |

The materialization digest is
`9fa0992bccab325a8fbadecb9bf375fbb783ea3b943a10e56b52cca92248e942`; the split digest is
`d1532977c0ef6526b0b355fffc97097985e1881d1fa347a069d4d99455c44fee`. Cold and warm rebuilds
produced the same digest and identical generated-file receipts.

The view retains the M0 source-video, event, source-group, and reference-revision lineage. The
materializer omitted 35 reviewed frame exclusions and 92 ineligible outcomes. The view has 874
explicitly pile-reviewed frames. All 2,714 COCO segmentation masks decoded at their source frame
dimensions and were non-empty. The materializer and COCO validators accepted the same-frame targets,
category IDs, splits, and exclusion receipts.

## Visual and package inspection

The read-only [inspection receipt](0092-M1_Overlay_Inspection_Receipt.json) records a mask overlay
sheet for each of the 20 recordings. Each local sheet shows representative frames,
the densest frame, and the frame with the most pile masks where available. The pass also selects the
smallest card box in each recording and frame-edge examples where a card box touches the image edge.
These samples cover dense overlapping cards, pile regions, small cards, frame edges, and visible
human hands. The card and pile overlays follow their reviewed regions in the inspected frames.

RF-DETR 1.9.4 loaded the train, validation, and sealed-test COCO views at the frozen 432-pixel
resolution. This checked dataset and mask loading only. No candidate or baseline inference ran, and
no training started. The sealed-test data was viewed only for M1 ground-truth materialization QA; its
predictions and metrics remain unused.

The generated view and overlay sheets are local runtime artifacts under `.runtime`; model weights
and generated datasets are not committed.

## Reproduction

```sh
mise exec -- uv run --project operations python operations/scripts/materialize_0087_m1.py \
  --repository-root . \
  --manifest docs/reports/0092-M0_Expanded_Reviewed_RF_DETR_Campaign_Manifest.json \
  --output-root .runtime/rfdetr-segmentation-0092-m1

mise exec -- uv run --project operations python operations/scripts/inspect_0092_m1.py \
  --repository-root . \
  --view-root .runtime/rfdetr-segmentation-0092-m1 \
  --overlay-root .runtime/rfdetr-segmentation-0092-m1-overlays
```

Run the materialization command a second time with the same output root. It must report the same
materialization digest and generated-file hashes.
