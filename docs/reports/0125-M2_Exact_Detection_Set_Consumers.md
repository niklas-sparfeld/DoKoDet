# 0125 M2: Exact detection-set consumers

## Review status

M2 is incomplete after two corrections. The actual calibration preview job still uses legacy
proposal scenes, while apply uses the selected detection set. The direct apply test does not prove
the real preview-job-to-apply path. See the epic execution handoff for the scope decision.

## Result

M2 converts the named consumers to accept exact saved detection-set versions. Scene proposals,
visual identity, and observation assembly freeze `{set_id, version, content_sha256}` in the processor
request, validate it again when the job runs, and retain it in durable run and output lineage.
Comparison can use an exact saved detection set as its visible-card reference and compare it with two
run alternatives. It requires version-bound geometry decisions for every object. It retains accepted
objects, excludes rejected objects and frames with only rejected objects, rejects unreviewed objects
and unsupported geometry, and keeps explicit empty frames empty. Calibration preview, apply, and
target proposal generation use the exact saved set's pixel geometry. Apply rechecks its reference,
includes it in the receipt identity, and writes a corrected version whose producer facts retain the
exact source. The existing calibration node draft and its decisions remain under their authority.

The adapters reject unsupported geometry or coordinate precision. They do not fill missing frame or
event coverage. Exact frame identity, object identifiers, polygons, event references, and empty
coverage remain explicit. Existing node consumers and the 0096 frame-review queue remain available.
M2 adds no selection authority or review store.

## Checks

- `uv run --project operations pytest -q operations/tests/test_pipeline_data.py operations/tests/test_pipeline_comparison.py` — passed, 21 tests.
- `uv run --project backend pytest -q backend/tests/test_pipeline_vision_comparison_api.py backend/tests/test_pipeline_comparison_api.py backend/tests/test_calibration_refinement_service.py backend/tests/test_detection_set_api.py backend/tests/test_detection_set_inputs.py backend/tests/test_observation_pipeline_api.py backend/tests/test_visual_identity_pipeline_api.py backend/tests/test_proposed_card_scene_pipeline.py backend/tests/test_pipeline_lineage_writer.py backend/tests/test_visible_card_pipeline_api.py` — passed, 68 tests.
- Existing node-review, node-selection, and 0096 frame-review suites — passed, 54 tests.
- `uv run --project backend pytest -q backend/tests/test_interactive_ui_residual_write_performance.py::test_calibration_apply_has_timing_and_published_readback` — passed. The real apply test uses a visibly edited saved polygon, verifies that the published proposal reflects it, and reopens the corrected detection set through a new `DetectionSetStore`. It also confirms that a separately stored node review decision remains applicable after reflow. The hard-snapshot fixture has no recording root, so the test supplies a recording-folder adapter and event-set fixture.
- `cd web && npm run generate:api` — passed.
- `cd web && npm run check` — passed: typecheck, lint, format, generated API verification, 46 test files, 243 tests.
- `cd web && npm run test:e2e:detection-set` — passed, 1 real-backend browser workflow.
- Ruff checks on changed backend and operations paths — passed.
- `git diff --check` and changed Markdown-link validation — passed.

## Limits and next milestone

M1 remains the first complete detector/browser workflow. This milestone proves exact-input consumer
and comparison paths with deterministic processors. The calibration apply test verifies exact saved
geometry through preview and target proposal generation, along with output lineage and restart.
M3 remains responsible for retained-data rehearsal, default detection cutover, old-path removal, and
qualification.

Correction 1 makes calibration apply validate the exact saved input and makes comparison use the
existing version-bound object review records. A rejected-only frame does not enter comparison scope;
an explicit empty frame remains present. Correction 2 routes apply preview and target proposal
generation through the saved geometry. The real apply regression verifies a changed proposal, exact
lineage after reopen, and retained node review. M2 corrections: 2/2; no re-plan.
