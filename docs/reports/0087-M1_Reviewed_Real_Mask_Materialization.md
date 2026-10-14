# 0087 M1 reviewed real-mask materialization

Date: 2026-10-14

## Result

M1 materialized the frozen 0087 train, validation, and sealed-test groups as a two-class COCO
segmentation view. The view uses the corrected M0 permission audit and the exact references in the
0086 handoff. It does not read mutable review drafts or proposed scenes.

| Split | Recording | Frames | Visible-card targets | Pile targets |
| --- | --- | ---: | ---: | ---: |
| Train | `cardeventnet-IMG_0095` | 42 | 105 | 38 |
| Validation | `cardeventnet-IMG_0097` | 40 | 103 | 36 |
| Sealed test | `cardeventnet-IMG_0654` | 48 | 130 | 0 |
| **Total** | 3 recordings | **130** | **338** | **74** |

The COCO view contains 412 annotations. Cards use reviewed polygon masks. Piles use uncompressed,
column-major RLE masks with reviewed-card pixels assigned to the card targets. The sealed test has
no pile targets. Do not claim pile-class test quality.

## Lineage and verification

- 0087 M0 digest: `a14ae7c3b96408c652ee7e1d78fc1bc209c9771bf5a70ef26432114a2acd2114`.
- 0086 handoff digest: `57e63ce72236f9b8585c1787df84e7f6a4704b236230522d6ec8303de3e19a92`.
- Materialization digest: `cc0891f04f8e9e4a59790e9f3eac52d91bdaeaf85b43a5a84a7aa563de119e29`.
- Repeated materialization produced the same split and materialization digests. The loader verified
  all generated file digests, COCO polygons, pile RLE dimensions and areas, split lineage, and the
  exclusion receipt. No frame was excluded; 24 ineligible outcomes remain in the receipt.
- Eleven overlays covered the first, middle, last, and pile-dense frames across all three
  recordings. Full-resolution overlays were also inspected for one frame per recording. Card masks
  followed reviewed card boundaries; pile masks covered the face-down pile regions; visible hand
  pixels were not assigned to card masks.
- RF-DETR 1.9.4 loaded the pinned 90-class checkpoint with the frozen two-class, 432-pixel model
  configuration. The detection head was reinitialized for two classes, as expected. No training or
  inference ran.

The materializer now accepts the frozen 0087 manifest and verifies its selected recording,
source-group, source-permission, reference, event, and handoff lineage before extracting frames.
The reproducible command is:

```sh
mise exec -- uv run --project operations --group inference \
  python operations/scripts/materialize_0087_m1.py
```

The generated view is local and disposable at `.runtime/rfdetr-segmentation-0087`.

## Corpus limit

All 22 development candidates have `project_use` permission, but only these three have completed
references in the current 0086 handoff. The other candidates still need refreshed or completed
reviewed references. M1 does not turn their drafts into targets. If 0086 adds eligible references,
review the 0087 split and freeze a new M0 manifest before rematerialization or training.
