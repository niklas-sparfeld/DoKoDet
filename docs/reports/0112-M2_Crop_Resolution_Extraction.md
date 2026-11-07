# 0112 M2 crop resolution extraction

## Result

M2 moved crop provenance checks and crop byte resolution out of
`VisualIdentityPipelineService`.

- `visual_identity_crop_provenance.py` owns validated crop context, dependency fingerprints,
  run/input provenance checks, and frozen outcome validation. It consumes the exact crop input
  frozen by M1.
- `visual_identity_crop_resolution.py` owns exact-frame crop resolution, crop identity mapping,
  validated outcome lookup, browser preview resolution, and reviewed annotation crop lookup. The
  service retains reviewed input-context validation and API orchestration.
- Canonical identity crop resolution, browser preview, and reviewed annotation lookup use the same
  exact-frame and geometry resolver. The resolver checks the resolved frame identity before it
  returns crop bytes.
- HTTP error conversion remains at the existing service and API boundary.
- `test_visual_identity_crop_resolution.py` verifies fixture bytes and crop identity, rejects stale
  provenance and geometry, and runs without starting jobs.
- The API suite continues to verify crop bytes, digest identity, preview, restart, and changed
  dependencies. It also covers proposed virtual-card identity and exact frame lineage.

## Checks

Passed against the M2 working tree:

```sh
mise exec -- uv run --project backend pytest -q backend/tests/test_visual_identity_pipeline_api.py backend/tests/test_visual_identity_crop_sources.py backend/tests/test_visual_identity_crop_resolution.py
mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/visual_identity_crop_provenance.py backend/src/dokodetector_backend/visual_identity_crop_resolution.py backend/src/dokodetector_backend/visual_identity_pipeline_service.py backend/tests/test_visual_identity_crop_resolution.py
mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/visual_identity_crop_provenance.py backend/src/dokodetector_backend/visual_identity_crop_resolution.py backend/src/dokodetector_backend/visual_identity_pipeline_service.py backend/tests/test_visual_identity_crop_resolution.py
```

Result: 13 tests passed. Ruff lint and format checks passed. Pytest reports the existing Starlette
`httpx` deprecation warning.

The direct reviewed-context cache test found that the timestamp freshness check used the tuple's
SHA-256 field. It now uses `ctime_ns`, the same field used by the validated identity lookup. Direct
tests cover this cache path and the extracted reviewed annotation lookup without starting jobs.

## Limits

The service retains API-facing methods and error conversion. M3 owns classification and job
execution. Geometry refinement remains limited to the crop input kinds accepted by the frozen M1
input policy.
