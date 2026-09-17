# Reviewed RF-DETR local visible-card detector decision

Date: 2026-09-17

## Decision

Register the completed RF-DETR SegMedium bundle as the explicit selectable provider
`local-rfdetr-segmentation`. Keep `gemini` as the default visible-card provider. Keep the older
`local` detection-only provider and the epic 0067 PoC artifact unchanged.

This is a local availability decision. It is not a production-readiness decision. The bundle
passes the frozen validation and sealed-test gate, reloads through the segmentation provider, and
returns its bundle identity with each result. A later rollback removes the
`local-rfdetr-segmentation` entry from the local provider registry and leaves `gemini` selected.

The machine-readable decision and registry are retained at:

- `.runtime/rfdetr-visible-card-detector-0068-m4-decision/decision.json`
- `.runtime/rfdetr-visible-card-detector-0068-m4-decision/provider-registry.json`

## Corpus and evidence boundary

The frozen M0 manifest covers 24 completed corrected references, 1,180 reviewed frames, and 2,203
visible-card targets. It retains 784 positive frames, excludes 259 frames with reviewed ignore
regions, and records 137 ineligible outcomes. Side counts are `face_up` 1,620, `unknown` 560,
and `face_down` 23.

The M3 report evaluates 143 validation frames with 376 targets and 104 sealed-test frames with
292 targets. The sealed test contains three source-group-disjoint recordings:
`IMG_0646`, `IMG_0648`, and `IMG_0649`. The M3 report and four retained prediction artifacts are
at `.runtime/rfdetr-visible-card-detector-0068-m3-validation/`.

The corpus has no reviewed empty-background frames. It does not measure background-only precision
or false positives over complete videos. Ignore-region and ineligible frames remain outside the
score and were not converted to negative targets.

## Locked results

| Metric | Validation baseline | Validation candidate | Sealed-test baseline | Sealed-test candidate |
| --- | ---: | ---: | ---: | ---: |
| Mask AP 0.50:0.95 | 0.000000 | 0.831965 | 0.000000 | 0.813391 |
| Mask AP50 | 0.000000 | 0.979096 | 0.000000 | 0.960396 |
| Box AP 0.50:0.95 | 0.000000 | 0.816223 | 0.000000 | 0.772582 |
| Instance recall | 0.000000 | 0.986702 | 0.000000 | 0.969178 |
| False predictions | 90 | 8 | 40 | 1 |
| Duplicate predictions | 0 | 5 | 0 | 1 |
| Empty prediction rate | 0.377622 | 0.000000 | 0.644231 | 0.000000 |

The candidate has nonzero recall in all three sealed-test recordings: `IMG_0646` 0.934783,
`IMG_0648` 1.000000, and `IMG_0649` 1.000000. The candidate bundle digest is
`b3deef701e26d91ebfd9d357b4ff69b45ae9360e3722de340f1044214179df29`; its selected checkpoint
digest is `b72462e9736d16bb975ba9c6999fe1cc4baeab8805830c3116115279170f3d4f`.

## Failure examples

The retained candidate predictions contain one sealed-test overprediction and several
underdetection count mismatches. These are source-linked examples, not a claim that count alone
proves the exact IoU error:

| Partition | Recording and event | Reviewed targets | Candidate predictions |
| --- | --- | ---: | ---: |
| Sealed test | `IMG_0646`, `event-img_0646-033` | 5 | 3 |
| Sealed test | `IMG_0646`, `event-img_0646-024` | 5 | 4 |
| Sealed test | `IMG_0649`, `event-img_0649-000` | 1 | 2 |
| Validation | `IMG_0090`, `event-img_0090-038` | 3 | 5 |

The aggregate sealed-test result still has one false and one duplicate prediction. The candidate
also has lower mask AP on the sealed test than on validation. The face-down slice is small and
weak: its sealed-test recall is 0.666667 and mask AP 0.132673. The side and visible-card-count
slices remain in the retained M3 artifacts.

## Resource cost

The full candidate used explicit MPS with `rfdetr==1.9.4`, RF-DETR SegMedium at 432 × 432,
batch size 1, gradient accumulation 4, and zero data-loader workers. The completed run took
3,038.176 seconds (50.6 minutes) against the frozen 7,200-second budget. The operator resumed it
from `rfdetr/last.ckpt` after stopping the first attempt when the MPS unified-memory footprint
grew above 40 GB. The run retained MPS resource facts and memory-guard telemetry.

## Limits and follow-up

The selection is local and explicit. It does not change the default backend setting, add a
production champion, or claim background precision. Broader held-out coverage and newly reviewed
negative frames are required before any production-readiness decision. Do not start another
training sweep under this epic.
