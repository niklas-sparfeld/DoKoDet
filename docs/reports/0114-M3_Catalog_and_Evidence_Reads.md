# Epic 0114 M3: catalog and evidence JSON reads

Date: 2026-11-07

Scope: catalog, recording, repository-bundle, round-analysis, counterfactual, timeline,
table-observation, and evidence-package JSON reads. No media routes.

## Coverage

Added `backend/scripts/run_interactive_ui_catalog_read_performance.py`. It derives its expected
route set from the M0 inventory and fails if a route is missing or extra. It defines 11 named
speed and correctness cases for the 9 in-scope GET route templates. Checks include HTTP status,
recording identity, empty catalog contents, and API error codes. Every measured response body is
read in full. The generated-empty profile needs no local hard assets. Use `--profile hard` to
include the frozen hard snapshot, or the default `both` profile to run both tiers.

The hard snapshot supplies four valid recording bundles, including `cardeventnet-IMG_0650`.
The generated-empty profile checks the empty catalog and missing-resource responses. The frozen
snapshot has no round-analysis, counterfactual, table-observation, or evidence-package records;
those read routes therefore use correct not-found cases. The successful populated cases cover the
catalog, recording detail, and repository bundle. M3 does not time media.

## Preliminary samples

The committed sample run used one warmup and one measured request per case in one batch. It is
preliminary data, not a baseline. The run produced 36 samples with no correctness failures. The
raw JSON records status, body size, digest, duration, profile, and warmup state.

| Case | Profile | Measured time |
| --- | --- | ---: |
| Catalog, empty | Generated empty | 0.606 ms |
| Catalog, hard | Frozen hard snapshot | 11.066 s |
| Recording detail, hard | Frozen hard snapshot | 52.840 ms |
| Missing recording | Frozen hard snapshot | 4.807 ms |
| Repository bundle | Frozen hard snapshot | 112.173 ms |
| Missing analysis, counterfactual, timeline, observation, and evidence package | Both | 0.415–0.910 ms |

The hard catalog response contains all four expected recording IDs. The 11-second sample is a
measurement to investigate in M10, not a performance verdict. The single sample does not establish
a stable distribution.

## Checks

- `mise exec -- uv run --project backend pytest backend/tests/test_interactive_ui_catalog_read_performance.py` — PASS, 2 tests.
- Ruff check and format check for the runner and its tests — PASS.
- `mise exec -- uv run --project backend python backend/scripts/run_interactive_ui_catalog_read_performance.py --warmups 1 --repeats 1 --batches 1 --output docs/reports/0114-M3_Catalog_Evidence_Read_Samples.json` — PASS, 36/36 samples correct.
- The sample export has one sample per scenario and is not the M2 repeated timing protocol or a baseline.
- The generated-only command was also run without local hard assets: 16/16 samples passed.
- The full M0 route inventory check currently fails on the unlisted GET
  `/api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}`. This route is in
  M4's calibration-read scope; M4 owns adding its inventory classification and case. M3's local
  catalog/evidence coverage check passes its nine-route set.

Raw samples: [catalog and evidence JSON](0114-M3_Catalog_Evidence_Read_Samples.json).
