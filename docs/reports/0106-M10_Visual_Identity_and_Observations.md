# 0106 M10 — Visual identity and table observations

## Result

The iOS pipeline now applies the predicted-visible-region crop policy to each complete visible-card
proposal and runs the frozen DINOv3 Core ML model. It retains the frame and crop digests, crop path,
input tensor digest, logits, raw and calibrated probabilities, ranked class map, review-threshold
decision, timing, and per-card status or error. Face-down results have no identity candidates.
Unusable crops and inference failures keep their visible-card proposals.

The stage writes `visual-identities/revision.json`, one crop image per usable card, and
`table-observations.json` under `.device/stages/visual-identities`. Each observation records the
event, visible-card, and identity revision IDs. Empty visible-card events produce valid empty
observations. Failed visible-card events produce insufficient-evidence observations.

The local build preparation script verifies package digest
`5e3af365eb1d0e7dd3543011a17189f68741dae926c3ec25e09c0fef358b1c25` and copies the ignored
package to the app's runtime resources. The build phase runs this check with the existing frozen
device model checks. The runtime uses CPU-only Core ML to match the 0104 comparison configuration.

## Frozen DINOv3 comparison

The Swift letterbox transform uses the two frozen 0103 PPM crops. It differs from the Python tensor
in a small number of resized byte values. The tensor digests differ. The output comparison reports
the maximum differences below. Both complete class rankings and decisions match the frozen 0104
results.

| Frozen crop | Changed RGB values | Max logit difference | Max raw probability difference | Max calibrated probability difference | Top class |
| --- | ---: | ---: | ---: | ---: | --- |
| Face-up, 08 s | 36 | 0.000822 | 0.0000199 | 0.00000444 | `SPADES_QUEEN` |
| Face-down, 40 s | 43 | 0.003296 | 0.000614 | 0.000296 | `FACE_DOWN` |

The largest input difference is one RGB value before normalization. The changed values did not
change any class rank, top class, face-down result, or review-threshold decision. This comparison
does not assess model quality.

## Verification and limits

- The full Release Swift package suite passed 155 tests, with the frozen reference root set. The
  six M10 tests cover Core ML comparison on both frozen crops, crop-bound handling, unusable items,
  partial candidate probabilities, empty observations, and revision lineage.
- The iPhone 18 Pro Simulator app build passed on iOS 27.2. The frozen model comparison ran on the
  local Mac package test target; this phase does not claim Simulator inference time or memory.
- Strict Swift formatting, Python lint and format checks, and `git diff --check` passed.

This phase adds a callable device stage. It does not add the end-to-end controls or export flow from
M12, nor does it claim iPhone model performance or identity accuracy.
