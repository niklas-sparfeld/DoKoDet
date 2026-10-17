# Epic 0098 M0 frozen inputs

M0 checked the primary pipeline store, source permissions, protected groups, M6 files,
scene lineage, crop geometry, and existing identity selections. It did not run a
classifier.

## Frozen scope

- Included recordings: 26
- Excluded protected recordings: 3
- Upstream failures: 5
- Included source frames: 1356
- Crop geometry candidates: 2994
- Crop geometry with no visible pixels: 0
- M6 training-overlap crop candidates: 1177

The crop counts describe deterministic visible-region geometry. M1 must still account for
each materialized crop as classified, face-down, unusable, failed, or unprocessed.
The three protected recording groups are excluded before identity inference. M6 training
overlap can supply review proposals but cannot supply quality comparison pairs.

## Pins

- M6 bundle: `a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`
- M6 checkpoint: `ff560c5a4e2fff70f7e6ab0ff0cef6e7fa8cab8bbdfbcd25af4c569ee4bdfb1a`
- Temperature: `0.6487642659`
- Crop: `predicted_visible_region`, RGB P6 PPM, 224-pixel Lanczos letterbox.

## Reproduction

Run from the repository root. The primary pipeline store and ignored M6 bundle remain in
the `main` worktree, so pass that path explicitly:

```sh
mise exec -- uv run --project operations python \
  operations/scripts/build_0098_m0_preflight.py \
  --store-root /Users/niklas.sparfeld/Developer/doko_detector \
  --model-bundle /Users/niklas.sparfeld/Developer/doko_detector/.runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle
```

The manifest stores each included frame and card geometry receipt, source digest, scene,
detector revision, calibration digest, and identity selection pointer state. No upstream
data or selection pointer was changed.

See [the machine-readable manifest](0098-M0_Frozen_Inputs.json).
