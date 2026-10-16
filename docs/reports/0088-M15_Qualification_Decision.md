# 0088 M15 qualification decision

Date: 2026-10-16

## Decision

**The useful-model objective is unmet. No bundle is quality-qualified or recommended for
promotion.** M13 is the sole final comparison and remains sealed against further scoring or tuning.
Its 108 reviewed crops came from one source group, below the frozen three-group minimum. M14 adds
runtime evidence on 495 automatic crops, but none matched reviewed identity targets.

Keep both locked candidates available for diagnostics. Use M6 seed 17 as the primary diagnostic
bundle because it scored higher than M3 on the paired final point estimate (86/108 versus 83/108),
had higher face-up accuracy (79.44% versus 76.64%), and met the 100 ms p95 latency limit. Keep M3
seed 17 as the frozen control and permit direct side-by-side diagnostic use. This is a practical
diagnostic ordering, not a statistical claim that M6 is better. The 1 percentage-point challenger
rule did not exclude either candidate from M13 and does not exclude either from future diagnostics.

| Gate | M3 seed 17 | M6 seed 17 | Decision |
| --- | --- | --- | --- |
| Face-up top-1 at least 98% | 82/107 (76.64%) | 85/107 (79.44%) | Fail for both |
| Confidence error at most 1% and coverage at least 90% at 0.90 | 0/46 errors; 46/108 (42.59%) coverage | 0/41 errors; 41/108 (37.96%) coverage | Fail coverage for both |
| Local p95 latency at most 100 ms | 155.721 ms | 61.842 ms | M3 fails; M6 passes |
| Model load at most 10 seconds | 2.495 s | 0.126 s | Pass for both |
| Usable prediction coverage at least 90% | 100% | 100% | Pass for both |
| Memory at most 75% physical RAM | 810,598,400 bytes peak total process RSS (2.36% RAM) | Same run peak | Pass |
| At least three independent final-test source groups | 1 | 1 | Insufficient evidence for both |
| `FACE_DOWN` quality | 1/1 correct | 1/1 correct | Insufficient evidence; do not claim quality |
| Paired Gemini point deficit no more than 1 point | +4.63 points | +7.41 points | Pass as descriptive point comparison |

The models have no usable-prediction failures. M6's advantage over Gemini is descriptive only and
does not satisfy the accuracy, confidence coverage, or source-group gates. Both models also had
24/44 frames with all supported cards correct.

## Error and disagreement evidence

The main repeated errors are similar across candidates: `HEARTS_ACE` to `DIAMONDS_ACE` (M3 7,
M6 6), `HEARTS_JACK` to `DIAMONDS_KING` (4 each), and `DIAMONDS_KING` to `CLUBS_JACK` (M3 3,
M6 5). M3 also sent four `SPADES_ACE` crops to `CLUBS_ACE`; M6 corrected three of those four.
These are observed in the single final recording and do not establish corpus-wide confusion rates.

Across the same crops, M3 disagreed with Gemini on 36/108 predictions and M6 on 34/108. M3 was
correct where Gemini was wrong on 14 of its disagreements and Gemini was correct where M3 was
wrong on 9. The corresponding M6 counts were 13 and 5. Gemini returned `UNKNOWN` on some crops;
those outputs remain in the paired denominator. These differences do not make Gemini a ground
truth or qualify either local model.

## Exact downstream diagnostic decision

- **Primary diagnostic bundle:** M6 seed 17, bundle
  `a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`, checkpoint
  `ff560c5a4e2fff70f7e6ab0ff0cef6e7fa8cab8bbdfbcd25af4c569ee4bdfb1a`, temperature
  `0.6487642659`.
- **Control bundle:** M3 seed 17, bundle
  `e54952030a1f87aadf4c5c3befb71537e588074cd9959c98c4c51bbbc6ddac87`, checkpoint
  `6d9234b35ab30e881b96dbbaf67cd7e6f71a137478796e4c14af03afe16936a`, temperature
  `0.6080362924`.
- Both use 224-pixel RGB P6 PPM inputs, aspect-preserving Lanczos resize, centered `(128,128,128)`
  letterbox, and the locked 25-output map. Keep pixel-based `FACE_DOWN` ranking; the evidence does
  not qualify it.
- Preserve calibrated probabilities and raw outputs. A calibrated top-1 probability of `0.90`
  may be recorded as a **diagnostic review-routing threshold only**. It is not a safe auto-accept,
  abstention, or production policy. Treat every identity prediction as a proposal requiring human
  review. Do not switch defaults, promote, or silently fall back to Gemini.
- The locked M13 test must not be rerun or used for tuning. Any future quality campaign needs a
  separately bounded plan and new independent reviewed source groups.

0089 may use both exact bundles when reproducing identity-sensitive failures; it can use M6 as its
primary diagnostic run and M3 as the control. Algorithm work must preserve reviewed geometry as
authority. 0090 may use M6 as the declared diagnostic identity bundle and M3 for a paired
diagnostic when useful, but must label the identity stage unqualified and all predictions as
review-required. 0090 remains blocked until 0089 publishes its algorithm handoff. 0044 receives no
promotion recommendation; its quality-qualified promotion gate remains unmet.

## Objective and limits

M15 is complete, but Epic 0088 remains **In Progress** because the useful-model objective is unmet.
The current decision is not a request to train indefinitely. A future campaign requires a new
bounded plan, new independent reviewed groups, and a fresh qualification contract. No NINE or
FACE_DOWN quality claim is made from this campaign.

Evidence: [M12 lock](0088-M12_Final_Evaluation_Lock.md),
[M13 final evaluation](0088-M13_Final_Evaluation.md), and
[M14 development exercise](0088-M14_Development_Exercise.md).
