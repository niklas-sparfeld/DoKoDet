# 0103 M0: Freeze the experiment

## Status

M0 is complete. The exact model artifacts, fixed development inputs, Python outputs, comparison
rules, and comparison checks are recorded. The inputs use one permitted staged recording. They do
not use reviewed crops, reviewed labels, sealed tests, or final evaluation material.

The [input manifest](0103-M0_Input_Manifest.json) records every extracted input digest and source
timestamp. The [Python references](0103-M0_Python_References.json) contain raw and postprocessed
outputs for the three selected models. Their SHA-256 digests are:

- Input manifest: `dbcba9d8ff7aa32b438c70572eec76047b154b8796db030acad2a950414355e5`.
- Python references: `8a9b48dce3a1e108a75a496008cdede140a11a339fa9114279d47819a0375423`.

Run the input extraction and Python inference again from the repository root with:

```sh
PYTHONPATH=card_event_net/src:table_evidence_analyzer/src:operations/src \
  backend/.venv/bin/python scripts/0103_m0_reference.py
```

This command writes the fixed inputs and full reference output to the ignored
`.runtime/0103-m0/` directory. It does not modify source media, model bundles, reviewed data, or
selection pointers. The manifest and reference files checked into `docs/reports` are the frozen
results used by M1–M3.

## Model artifacts

| Stage | Frozen artifact and SHA-256 | Frozen execution contract |
| --- | --- | --- |
| Events | `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/runs/candidate-hard-negative-v1/best.pt` — `258f4541142afc68df1c300476112a6bc1d0afffd2e44323706b8559e64971e4` | CardEventNet; eight RGB frames at 224×224; full-frame letterbox v1; offsets −1.4 to 0.0 seconds; causal peak threshold `0.4271905720233917`; confirmation `0.125 s`; minimum event gap `0.625 s`. |
| Visible cards and piles | `.runtime/rfdetr-segmentation-0092-m4/bundle/checkpoint_best_total.pth` — `80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`; bundle digest `05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c` | RF-DETR SegMedium; 432×432; classes `visible_card` and `card_pile`; confidence threshold 0.5. |
| Visual identity | `.runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle`; encoder digest `6fc86f473ceec4c8612c1c7341d878e3ecf96b1d182dbae7d47b02cf83a5fa24`; head digest `baeae9d97b971cdfa60fa3f8c92e62c47cb5d7eb7074478322abda6ffca19979`; bundle digest `a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79` | DINOv3 ViT-S/16 frozen encoder and 25-class linear head; 224-pixel PPM; `cls_mean_patch`; calibrated probabilities. Bundle quality is marked `unusable_smoke_artifact`. |

The artifact digests match the retained 0090 freeze. The RF-DETR and DINOv3 files are local runtime
artifacts and are not in Git. The DINOv3 bundle contains an accepted license record for the DINOv3
License dated 2025-08-19. Do not redistribute the DINOv3 weights or any model package until the
license terms are reviewed for the intended distribution. The RF-DETR bundle has no license text;
its redistribution terms remain unverified. No model package is included in this change.

## Fixed inputs

The source is `cardeventnet-IMG_0657` at
`data/intake/recordings/cardeventnet-IMG_0657/videos/video-cardeventnet-IMG_0657.mov`, SHA-256
`23df5b4dbf0d0d80c79161ba32c1f4c4db8473f053fdd9b63508c66e38d3658b`. Its recorded permission is
`project_use`. Its duration is 89.42 seconds. The source itself is not changed.

Six full RGB frames at 1920×1080 are frozen for RF-DETR: 2 s (empty scene), 8 s and 70 s (multiple
face-up cards), 12 s (cards held in a hand), 20 s (partly covered cards), and 40 s (one face-down
card). The manifest records the exact SHA-256 digest of each extracted PNG.

Two DINOv3 PPM crops are direct crops from the same frozen full frames. The 8 s crop uses pixel box
`[900,740,1420,1070]` and contains a face-up card. The 40 s crop uses `[1200,560,1660,810]` and
contains a face-down card. These boxes are fixed operator-selected execution inputs. They are not
review labels or previously reviewed identity crops.

The CardEventNet input uses eight cached RGB frames at 224×224, selected by the model's causal
offsets for decision time 8.0 s. The manifest records the selected cache index, decoded timestamp,
and byte digest for every JPEG. Its window spans approximately 6.606–7.908 s because the source
video frame timestamps do not land exactly on every 0.2-second offset. The model receives the same
frame selection as the Python cache inference path.

## Python references

The frozen reference run used CPU inference on Python 3.13.18, macOS 27.2 arm64, PyTorch 2.7.0,
torchvision 0.22.0, Transformers 5.22.1, RF-DETR 1.9.4, Pillow 12.3.0, and OpenCV 5.0.0.93. The
complete package record is in the Python reference JSON. Reference generation took 10.562 s; this
timing is context only.

- CardEventNet returned logit `-7.1549272537231445` and probability `0.0007803968619555235` at
  8.0 s, below its frozen threshold. This single score does not measure event accuracy.
- RF-DETR ran on all six frames. It returned 200 threshold-free candidates per frame, with packed
  segmentation masks, classes, scores, and boxes. At the 0.5 confidence threshold it returned 0, 4,
  2, 3, 1, and 4 visible-card detections, in timestamp order, and no pile detections. These are
  model proposals, not reviewed truth.
- DINOv3 returned `SPADES_QUEEN` as the top candidate for the selected face-up crop, with calibrated
  score `0.9744869902219441`. It returned `FACE_DOWN` for the face-down crop, with score
  `0.9364343189263622`. The bundle marks itself unusable as a smoke artifact; these values show
  inference only and make no quality claim.

The installed runtime package versions differ from the versions recorded when the RF-DETR and
DINOv3 artifacts were built. The RF-DETR manifest records PyTorch 2.13.0 and torchvision 0.28.0.
The DINOv3 bundle records PyTorch 2.13.0, torchvision 0.28.0, and Transformers 5.16.1. The current
Python references use the package versions listed above. `backend/uv.lock` has SHA-256
`a48d17fc6884534d07b26d3e42eddde924cbc6f4aff06ff7b430bf9a854c2d0c`; the reference script has
SHA-256 `4d489db7707c307a92494ad31bf448eaaf419ee5c4d51e0fa37f20ba70ca806d`. M1–M3 must export
and compare against this frozen Python runtime, and must report this runtime-versus-build
difference. They must not silently change the reference environment.

## Comparison rules

- Compare the exact input bytes, dimensions, and RGB channel order first. Use the model's frozen
  preprocessing contract for each input.
- Compare float32 event logits and probabilities with absolute and relative tolerance `1e-4`.
  Report threshold decision changes independently. A score comparison does not assert event-time
  accuracy.
- Match RF-DETR masks by class and maximum polygon mask IoU. Report unmatched masks, scores,
  normalized box coordinates, and decisions at confidence threshold 0.5. Use score tolerance
  `atol=1e-4`, `rtol=1e-4`; use normalized box-coordinate absolute tolerance `1e-4`.
- Compare all 25 DINOv3 raw and calibrated class scores with `atol=1e-4`, `rtol=1e-4`. Report top
  rank changes and ties. Preserve the bundle class map and calibration.
- Do not interpret any conversion parity result as model accuracy or model selection evidence.

The deterministic comparison helpers are in
`table_evidence_analyzer/src/table_evidence_analyzer/model_parity.py`. The focused tests cover exact
values, values inside and outside tolerance, rank changes, threshold decisions, mask matching, and
an unmatched detection.

## Verification and limits

The reference generation completed for CardEventNet, RF-DETR, and DINOv3. The input manifest SHA-256
is `dbcba9d8ff7aa32b438c70572eec76047b154b8796db030acad2a950414355e5`. The focused comparison
tests passed (4 tests). Ruff lint and format checks passed for the new reference script, comparison
helpers, and focused tests. Reference timings are not iPhone predictions.

No sealed test or evaluator was accessed. No model was trained, promoted, or installed as a runtime
default. Export packages, device measurements, iPhone availability, and redistribution terms remain
for later milestones.
