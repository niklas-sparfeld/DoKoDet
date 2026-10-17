# Epic 0098 M1 identity batch

M1 completed local identity proposals for all 26 recordings in the frozen M0 manifest. The batch
used the pinned 0088 M6 seed 17 bundle. It ran one backend process at a time and made no cloud
requests.

## Results

- 2,994 frozen crop inputs produced 2,994 stored outcomes.
- 2,913 outcomes were `classified` and 81 were `face_down`.
- No crop was unusable or failed. No crop was unprocessed.
- All 26 runs completed on their first attempt. The five M0 upstream failures remain outside the
  inference batch.
- Active batch time was 1,867.067 seconds (31.1 minutes).
- Peak sampled process RSS was 1,120,511,144 bytes (about 1.04 GiB), below the 32 GiB limit.
- All stored output revision digests match the M1 report. The frozen visible-card and scene
  revision digests, calibration digests, and source video hashes also match. The check rehashed
  4,733,710,147 source-video bytes.
- The 78 included-recording identity selection, draft, and state files match their M0 hashes. No
  identity selection changed.

The classifier reported `local-dinov3`, model `facebook/dinov3-vits16-pretrain-lvd1689m`, version
`dinov3-local-identity-v2`. The runtime used the M0-pinned bundle and checkpoint, MPS, temperature
`0.6487642659`, and one concurrent request. These outputs are proposals. They do not measure
correctness and must receive human review.

## Monitoring deviation

The run requested a 10-second RSS interval. The runner checked RSS on its 2-second status-poll loop.
The measured sample gaps were 10.010 to 16.330 seconds, with a mean of 11.548 seconds. The largest
observed RSS remained far below the cap. The batch was not repeated because M1 permits at most one
run per recording. The runner now samples RSS on an independent 10-second schedule.

## Reproduction

Start a local backend against the primary checkout and frozen M6 bundle. Keep the identity worker
concurrency at one:

```sh
VISIBLE_CARD_IDENTITY_CLASSIFIER=local \
VISIBLE_CARD_IDENTITY_BUNDLE_PATH=/Users/niklas.sparfeld/Developer/doko_detector/.runtime/dinov3-identity-0088/m12-final-lock/m6-candidate-bundle \
VISIBLE_CARD_IDENTITY_DEVICE=mps \
VISIBLE_CARD_IDENTITY_MAX_CONCURRENT_REQUESTS=1 \
SERVER_PORT=8001 SERVER_HOST=127.0.0.1 BONJOUR_ENABLED=false \
mise exec -- uv run --project backend dokodetector-backend
```

Then run the bounded batch from the repository root. Replace the process ID with the PID of that
backend process:

```sh
mise exec -- uv run --project operations python \
  operations/scripts/run_0098_m1_identity_batch.py \
  --manifest docs/reports/0098-M0_Frozen_Inputs.json \
  --output docs/reports/0098-M1_Identity_Batch.json \
  --backend http://127.0.0.1:8001 \
  --backend-pid <backend-pid>
```

The runner uses the frozen recording and revision IDs. It reuses completed runs and does not retry
terminal failures. It records each output revision ID and digest in the
[machine-readable result](0098-M1_Identity_Batch.json). The backend request purpose prevents these
diagnostic runs from changing generated identity selections.

See the [M0 frozen inputs](0098-M0_Frozen_Inputs.md) for source permissions, excluded groups,
upstream failures, and the crop recipe.
