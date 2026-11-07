# 0112 M1 crop-input extraction

## Result

M1 moved visual identity crop-input freezing and source validation out of
`VisualIdentityPipelineService`.

- `visual_identity_crop_sources.py` validates canonical node revisions, source digests, completed
  references, reviewed scene derivation, and reviewed virtual-card items.
- `visual_identity_crop_inputs.py` freezes generated, proposed, and reviewed crop inputs. It returns
  a frozen result with the exact input revision ID, immutable crop-item tuple, and typed provenance.
- The service builds both helpers with explicit stores and accepted recording source. The helpers
  do not import the service or job participant. The service unwraps the crop manifest at its
  existing request boundary.
- The focused reviewed scene and repeated source-validation tests moved to
  `backend/tests/test_visual_identity_crop_sources.py`. Managed-job, all-kind, and same-frame
  proposed pose-to-detector checks remain in `backend/tests/test_visual_identity_pipeline_api.py`.

All five supported crop kinds remain covered: `gemini_polygon`, `rfdetr_segment`,
`proposed_virtual_cards`, `reviewed_virtual_card`, and `reviewed_visible_card`. The existing API
suite checks generated kinds, managed job freezing, and proposed virtual-card lineage across
restart. The focused source suite checks reviewed geometry and repeated source validation.

## Checks

Passed against the M1 working tree:

```sh
mise exec -- uv run --project backend pytest -q backend/tests/test_visual_identity_pipeline_api.py backend/tests/test_visual_identity_crop_sources.py
mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/visual_identity_crop_inputs.py backend/src/dokodetector_backend/visual_identity_crop_sources.py backend/src/dokodetector_backend/visual_identity_pipeline_service.py backend/tests/test_visual_identity_crop_sources.py backend/tests/test_visual_identity_pipeline_api.py
mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/visual_identity_crop_inputs.py backend/src/dokodetector_backend/visual_identity_crop_sources.py backend/src/dokodetector_backend/visual_identity_pipeline_service.py backend/tests/test_visual_identity_crop_sources.py backend/tests/test_visual_identity_pipeline_api.py
```

Result: 9 tests passed; Ruff lint and format checks passed. Pytest reports the installed Starlette
deprecation warning for `httpx` in its test client.

## Limits

The service still owns request acceptance and job lifecycle. Crop resolution and result provenance
remain in the service for M2. The large service root remains above its final 500-line budget until
the planned M2 and M3 extraction work.
