# RF-DETR visible-region PoC decision

Date: 2026-09-15

## Decision

Classify the RF-DETR SegMedium checkpoint as `poc_candidate` for a later visible-region
provider comparison in 0050. Do not promote it, select it as a runtime default, or use it for a
production-quality claim.

The fixed M0 gate passes. The candidate reloads, retained predictions reproduce the reported
metrics, mask AP and recall are higher than the unchanged pretrained baseline, and all three
validation recordings have target recall. This decision uses the frozen RF-DETR 1.9.4 recipe and
the fixed confidence threshold of 0.50. No threshold, seed, model, or augmentation change was
made after validation.

## Corpus boundary

The campaign trained on 219 reviewed positive frames with 703 visible-card targets. It validated
on 85 reviewed positive frames with 213 targets from three separate recordings. It excluded frames
with visible-card ignore regions. The immutable campaign manifest has digest
`8360e361f4e6199a1af74e50878b59239489f6a9ba4be5ce510fa421f358662a`.

This corpus has no reviewed background-only frames and no sealed test partition. Failed and
unusable review outcomes were not converted to background. The result therefore does not measure
background-only precision or generalization quality.

## Locked results

The candidate was trained on MPS in 6,721.232 seconds. The locked validation process used CPU
because MPS was unavailable to that process. The candidate bundle digest is
`f250de15fcea8522efebf9c6b2ac69fdfc967599ab02d75ac294ad6f61898865`; its checkpoint digest is
`1a47791cb381725e5af4673f94e821b02e282bc11f9f16cc66347b59f5bb021c`.

| Metric | Unchanged pretrained baseline | Candidate |
| --- | ---: | ---: |
| Mask AP 0.50:0.95 | 0.000000 | 0.860661 |
| Mask AP50 | 0.000000 | 0.989772 |
| Box AP 0.50:0.95 | 0.000000 | 0.875382 |
| Instance recall | 0.000000 | 0.995305 |
| False predictions | 70 | 5 |
| Duplicate predictions | 0 | 1 |
| Empty prediction rate | 0.176471 | 0.000000 |

The candidate has nonzero target recall in every validation recording: `IMG_0090` (0.99),
`IMG_0091` (1.00), and `IMG_0661` (1.00). The retained report and prediction artifacts are:

- `.runtime/rfdetr-segmentation-0067-m3-validation-cpu/report.json`
- `.runtime/rfdetr-segmentation-0067-m3-validation-cpu/baseline-predictions.json`
- `.runtime/rfdetr-segmentation-0067-m3-validation-cpu/candidate-predictions.json`

Their baseline and candidate prediction digests are respectively
`108f3934c250dc67d74c390220d329f7c3eca78de6e5466be1349466650415d7` and
`c39f24fa862904691049b28136d3fbdc331b7c563ee1e26556f5f6477932d791`.

## Harmful examples

The candidate has five false predictions and one duplicate prediction. Do not hide these errors
behind the aggregate result. The retained candidate predictions show extra predictions on these
source-linked validation events:

| Recording and event | Source frame | Time | Effect |
| --- | ---: | ---: | --- |
| [`IMG_0090`, event 007](../../data/intake/recordings/cardeventnet-IMG_0090/videos/video-cardeventnet-IMG_0090.mov) | 489 | 16.302 s | Four predictions for three reviewed targets. |
| [`IMG_0090`, event 023](../../data/intake/recordings/cardeventnet-IMG_0090/videos/video-cardeventnet-IMG_0090.mov) | 1318 | 43.938 s | Five predictions for four reviewed targets. |
| [`IMG_0090`, event 028](../../data/intake/recordings/cardeventnet-IMG_0090/videos/video-cardeventnet-IMG_0090.mov) | 1580 | 52.672 s | Four predictions for three reviewed targets. |
| [`IMG_0091`, event 023](../../data/intake/recordings/cardeventnet-IMG_0091/videos/video-cardeventnet-IMG_0091.mov) | 1400 | 46.672 s | Five predictions for four reviewed targets. |

The M0 manifest links each event to its source-frame digest and reviewed reference. The original
recordings above and their source records remain the inspection path. These examples do not cause a
new training or tuning run in this epic.

## Handoff to 0050

0050 can include this `poc_candidate` as one visible-region provider in its later frozen paired
comparison. It must compare the candidate with the fixed resilient identity input, reviewed
video-derived evidence, and its own source-group-safe manifest. This PoC does not satisfy 0050's
coverage, composed-observation, latency, or cost requirements, and it does not add a dependency to
0067.
