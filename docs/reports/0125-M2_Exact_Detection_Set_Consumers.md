# 0125 M2: Exact detection-set consumers

## Result

M2 converts the named consumers to accept exact saved detection-set versions. Scene proposals,
visual identity, and observation assembly freeze `{set_id, version, content_sha256}` in the processor
request, validate it again when the job runs, and retain it in durable run and output lineage.
Comparison can use an exact saved detection set as its visible-card reference and compare it with two
run alternatives. It requires version-bound geometry decisions for every object. It retains accepted
objects, excludes rejected objects and frames with only rejected objects, rejects unreviewed objects
and unsupported geometry, and keeps explicit empty frames empty. Calibration apply requires the exact
detection-set reference, rechecks it before reflow, includes it in the receipt identity, and writes a
corrected version whose producer facts retain the exact source. The existing calibration node draft
and its decisions remain under their existing authority.

The adapters reject unsupported geometry or coordinate precision. They do not fill missing frame or
event coverage. Exact frame identity, object identifiers, polygons, event references, and empty
coverage remain explicit. Existing node consumers and the 0096 frame-review queue remain available.
M2 adds no selection authority or review store.

## Checks

- `uv run --project operations pytest -q operations/tests/test_pipeline_data.py operations/tests/test_pipeline_comparison.py` — passed, 21 tests.
- `uv run --project backend pytest -q backend/tests/test_pipeline_vision_comparison_api.py backend/tests/test_pipeline_comparison_api.py backend/tests/test_calibration_refinement_service.py backend/tests/test_detection_set_api.py backend/tests/test_detection_set_inputs.py backend/tests/test_observation_pipeline_api.py backend/tests/test_visual_identity_pipeline_api.py backend/tests/test_proposed_card_scene_pipeline.py backend/tests/test_pipeline_lineage_writer.py backend/tests/test_visible_card_pipeline_api.py` — passed, 68 tests.
- Existing node-review, node-selection, and 0096 frame-review suites — passed, 54 tests.
- `uv run --project backend pytest -q backend/tests/test_interactive_ui_residual_write_performance.py::test_calibration_apply_has_timing_and_published_readback` — passed. The historical hard-snapshot fixture has no recording folder; the test supplies a deterministic detection-set store fixture. A separate calibration test writes through `DetectionSetStore` and reopens the corrected version from a fresh recording-folder store.
- `cd web && npm run generate:api` — passed.
- `cd web && npm run check` — passed: typecheck, lint, format, generated API verification, 46 test files, 243 tests.
- `cd web && npm run test:e2e:detection-set` — passed, 1 real-backend browser workflow.
- Ruff checks on changed backend and operations paths — passed.
- `git diff --check` and changed Markdown-link validation — passed.

## Limits and next milestone

M1 remains the first complete detector/browser workflow. This milestone proves exact-input consumer
and comparison paths with deterministic processors. The calibration hard-snapshot test uses a store
fixture because the snapshot has no recording root; the dedicated recording-folder test verifies the
new version and exact parent after reopen. M3 remains responsible for retained-data rehearsal,
default detection cutover, old-path removal, and qualification.

Correction 1 follows independent review. It makes calibration reflow use the caller's exact saved
version, and makes comparison use the existing version-bound object review records. A rejected-only
frame does not enter comparison scope; an explicit empty frame remains present. The real-store
regression reopens a corrected version derived from an edited alternative. M2 corrections: 1/2; no
re-plan.
