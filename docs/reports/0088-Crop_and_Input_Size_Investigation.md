# Identity crop and input-size investigation

Date: 2026-10-14. Read-only development diagnostics for the revised
[0088 campaign](../plans/4-blocked/0088-Reviewed_Virtual_Card_DINO_Campaign.md).
No training, Gemini requests, annotation changes or final-test access occurred.

## Sample and implementation

Sample: the 105 usable individual-card crops in IMG_0095 identity revision
`visual-identities-visual-identities-0086-img0095-v6-retry2-attempt-1`, with their cached exact frames.
The source video is `cardeventnet-IMG_0095`, 2160 by 3840 pixels, SDR BT.709, SHA-256
`34610c528a17117cf60dafd4137cf3531836c2bfdf422d391060249ce8da7bc7`.
This is development evidence from one recording, not a representative quality benchmark.

The exact-frame resolver uses full-resolution FFmpeg JPEG extraction with `-q:v 2`.
The visible-region resolver extracts the tight source-image rectangle, neutralizes pixels outside
the visible support, and emits PPM. It does not deskew or resize. The model transform uses Pillow
Lanczos, aspect-ratio preservation, RGB 128 padding and a 224 by 224 canvas. The browser separately
re-encodes native crops as quality-90 JPEG and sizes them to its panel.

Relevant implementations are in
[derived_view.py](../../operations/src/doko_operations/derived_view.py),
[local_identity.py](../../table_evidence_analyzer/src/table_evidence_analyzer/local_identity.py),
and the [identity presentation](../../web/src/visualIdentities/PipelineVisualIdentityPresentation.tsx).

## Pixel and encoding diagnostics

| Measurement                                                      |                 Result |
| ---------------------------------------------------------------- | ---------------------: |
| Usable crops inspected                                           |                    105 |
| Native crop long side, minimum / median / maximum                | 316 / 554 / 777 pixels |
| Non-neutral crop pixels equal corresponding decoded-frame pixels |   All inspected pixels |
| Model resized rectangle, median short side / minimum short side  |         99 / 59 pixels |
| Model canvas non-neutral area, median                            |                  26.4% |
| Quality-90 preview JPEG mean absolute RGB error, median          | 1.06 levels out of 255 |
| Quality-90 preview JPEG PSNR, median                             |                42.7 dB |
| Encoded crop size, median: JPEG 4:2:0 / JPEG 4:4:4 / PNG         | 22.7 / 26.4 / 102.2 KB |

The encoding comparison re-created the current preview encoder settings. It did not reproduce
the operator's browser zoom, screen pixel density, or exact complaint example. PNG adds no loss
relative to canonical PPM; that PPM already comes from a JPEG-encoded source frame. Aggregate
encoding errors include neutral mask area and do not measure rank/suit legibility. Non-neutral
area is a pixel-occupancy proxy, includes resampling effects, and is not useful-information coverage.

## Larger-input feasibility

Loaded the existing materialized `dinov3-vits16-pretrain-lvd1689m` weights locally with Transformers.
Ran one actual development crop with aspect-preserving Lanczos letterboxing and the current RGB
normalization. All four sizes returned finite 384-dimensional pooled features on MPS.

| Input      | Patch tokens, excluding CLS/registers | Resized example crop |
| ---------- | ------------------------------------: | -------------------- |
| 224 by 224 |                                   196 | 224 by 96            |
| 336 by 336 |                                   441 | 336 by 144           |
| 384 by 384 |                                   576 | 384 by 165           |
| 448 by 448 |                                   784 | 448 by 192           |

Three warm-up and ten measured forwards per size were sufficient for feasibility, not for a
production latency comparison. No head was trained and no classification accuracy was measured.
Patch counts are not latency multipliers. The application still hard-codes 224 in its transform
and bundle contract; 0094 must implement explicit size support and runtime parity.

## Planning decision

Use 224 as a fresh matched control and 384 as the first larger-input challenger. Permit 448 only
under a frozen data/resource gate. Retain source-image visible-region crops and Lanczos initially.
0093 owns a bounded decoder/filter and offline rectification audit; appearance cannot select a
model. Full runtime rectification needs a separate verified implementation decision and must not
become a mandatory geometry dependency without end-to-end evidence.

The annotation Face down/F action exists, but campaign preparation excludes those targets and
rejects FACE_DOWN materialization. The adapter marks known backs identity-unusable, and the
pipeline can bypass the classifier when side is supplied. The model has a 25-class contract, but
the PoC did not train/evaluate backs. These gaps inform 0093's positive-class data path and 0094's
pixel-based all-class evaluation. They do not establish current class support in the reviewed corpus.

## Reproduction boundary

For the named immutable revision, read each crop's native size, frame identity, pixel bounds and
cache digest. Compare all RGB pixels unequal to `[128,128,128]` with the corresponding rectangle
of the decoded frame. Re-create quality-90 JPEG, JPEG with `subsampling=0`, and PNG from each crop.
Calculate RGB absolute error and PSNR against the PPM and report medians with neutral-area caveats.
Run the exact aspect-preserving resize and letterbox to measure model pixel occupancy.

For size feasibility, load the existing pretrained encoder with `local_files_only=True` and use
the same source crop at each listed size under inference mode. Record output shapes, finite
features, device, dependency versions and local asset digests. Do not interpret forwards with the
old head as a fair comparison of newly trained representations. Use eligible development inputs
only; do not expand this diagnostic into a protected evaluation.
