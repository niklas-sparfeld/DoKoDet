# Epic 0093 M4 crop fidelity audit

Date: 2026-10-14. This is a read-only development audit. It did not edit maintained references,
train a model, access protected evaluation inputs, or change runtime crop behavior.

## Sample and inputs

The audit used 24 exact reviewed crops: eight each from IMG_0095, IMG_0097, and IMG_0654. These
recordings are in the eligible 0086 M2 handoff. The permanently excluded IMG_0092 and deferred
IMG_0096 were not used. The sample uses reviewed visible-card revisions and exact frame identities.
It includes incomplete visible support, 16 fitted pose proposals, and eight IMG_0654 crops without
completed reviewed-scene authority. Four fits have high residuals. Visual inspection rejected one
as incorrect for full-card rectification. A high residual alone is an audit warning, not a
correctness label.

The source video digests, visible-card revision digests, card-scene digests, exact requested and
presentation timestamps, frame indices, frame-pixel and geometry digests, and per-sample timings are
in the [machine-readable receipt](0093-M4_Crop_Fidelity_Audit.json). The receipt records 6.13 seconds
total for the 24 application JPEG frame-resolution calls. This does not include startup, probing, or
the direct PNG decode calls.

## Method

For each exact frame, the audit compared the application's FFmpeg JPEG output with a direct PNG
decode of the same presentation frame. The source video is already lossy; the PNG path removes only
the additional JPEG encoding step. Pixel error was measured inside the reviewed visible-support
mask.

The reviewed mask set pixels outside visible support to neutral RGB `[128, 128, 128]`. Each native
crop was reduced with aspect ratio preserved and placed on a 224 by 224 neutral canvas. The three
filters were Pillow Lanczos, OpenCV `INTER_AREA`, and Pillow bicubic. All filters used the same
resized dimensions. The sample includes cards with small rank and suit marks.

The [crop contact sheet](assets/0093-M4_Crop_Sample_Contact.png) shows the bounded sample. The
[filter comparison](assets/0093-M4_Filter_Comparison.png) enlarges one 224-pixel sample with nearest
neighbor display so the source pixels remain visible.

## Results

| Measure | Result |
| --- | ---: |
| JPEG versus direct PNG decode, visible-support RGB MAE | median 2.31; range 1.01–3.36 / 255 |
| JPEG versus direct PNG decode, visible-support PSNR | median 38.72 dB; range 34.26–45.32 dB |
| Visible mask area as a share of crop bounds | median 56.7%; range 50.4–88.8% |
| Non-neutral pixels on the Lanczos 224 canvas | median 26.8% |
| Lanczos versus area, full-canvas RGB MAE | median 0.67; range 0.06–1.32 / 255 |
| Lanczos versus bicubic, full-canvas RGB MAE | median 0.34; range 0.03–0.77 / 255 |
| Area versus bicubic, full-canvas RGB MAE | median 0.39; range 0.04–0.72 / 255 |

In the inspected 10-of-spades example, all three filters preserve the same rank and suit marks.
This appearance check does not establish which filter is better. The pixel differences and this
sample give no reason to replace Lanczos. The occupancy measures describe pixels, not useful card
information.

## Offline rectification

The [positive comparison](assets/0093-M4_Rectified_Visible_Card.png) uses a low-residual accepted
fitted pose proposal from IMG_0095. It is not a completed human-reviewed scene. The diagnostic
composes the saved table-to-image transform with the card pose, samples the original decoded frame,
and applies the exact reviewed visible-support mask. The output keeps the physical card ratio and
fills outside the mask with neutral gray. The calibration and pose fit receipt are in the JSON
report. This is an offline comparison, not evidence for a runtime policy. The projection does not
resolve the 180-degree orientation ambiguity.

The [failure comparison](assets/0093-M4_Rectification_Failure_Case.png) uses an IMG_0097 candidate
with fit residual `0.723753`. Its reviewed source support is a narrow strip, 412 by 85 pixels. The
rectification stretches that strip into a full card-shaped image. The result is not a valid identity
input. The audit keeps the failure visible and does not infer the hidden card content. It shows why
fit acceptance or a pose value alone must not make incomplete geometry a successful rectification.

## Decision

Retain native source-image crops, exact visible-support masks, and Lanczos as the default. The
sample does not justify a decoder or filter change. Keep rectification offline. A runtime
rectification policy needs a separate implementation and verification decision; do not add a
mandatory geometry gate based on this appearance audit.

This small development sample makes no classifier-quality claim and does not represent corpus-wide
crop quality.
