# 0109 M4 node-step surface integration

Date: 2026-11-07

## Result

M4 is complete. Visible cards and Virtual scenes use the shared still-frame surface. Both editors
keep frame navigation in the Timeline Rail and editing, review, errors, and diagnostics outside the
center. Each step edits only its selected node revision.

Visible cards renders source-frame region, pile, and ignore polygons. Its inspector retains the
region, pile, and ignore editors, review commands, pan and zoom, and copy-on-change save path. Frame
navigation stays available when the URL item is absent from the selected revision, so the operator
can choose an exact item without a list-position fallback.

Virtual scenes now reads one exact published table-plane calibration revision through
`GET /api/recordings/{recording_id}/pipeline/calibrations/{calibration_revision_id}`. The endpoint
uses the existing immutable calibration store and returns the stored homography, card dimensions,
frame dimensions, diagnostics, source revision, and digest. It does not select a calibration or
change stored data. The browser requests the calibration ID already selected by the scene and
checks its recording, revision ID, digest, and frame dimensions. It also checks the scene's
calibration identity and the exact frame's source video SHA, requested time, frame index,
presentation time, dimensions, and image digest. Invalid context suppresses the pose overlays and
disables scene edits and frame review.

The scene editor projects card poses through the stored table-to-image homography. It supports
source and rectified viewpoints. The rectified view warps the exact still image through the stored
inverse mapping. The surface supports pose selection and pointer dragging. Inspector controls edit
pose centers and rotation, and move the selected pose in the stored stacking order. The inspector
retains review, calibration diagnostics, and copy-on-change save. The shared surface supports
keyboard selection of pose outlines.

## Verification

- `cd web && npm run check` passed: TypeScript, ESLint, Prettier, generated API comparison, and all
  189 frontend tests.
- `cd web && npm run build` passed. Vite reports a chunk-size warning for the existing application
  bundle; the build completed.
- `cd web && npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts --reporter=line`
  passed. The browser fixture covers Events at 1440 × 900 and 390 × 844, exact Visible-card and
  Virtual-scene item navigation, source-frame overlays, controls outside the spatial evidence
  surface, rectified image output, pose dragging, source and calibration digest mismatches that
  block overlays, edits, and frame review, review submission, and copy-on-change with the edited
  scene retained in its copy.
- `mise exec -- uv run --project backend pytest backend/tests/test_pipeline_api.py::test_exact_published_calibration_read_returns_authoritative_transform -q`
  passed. The API test checks exact persisted calibration data and a missing-revision 404.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/calibration_refinement_api.py backend/src/dokodetector_backend/calibration_refinement_service.py backend/tests/test_pipeline_api.py`
  passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/calibration_refinement_api.py backend/src/dokodetector_backend/calibration_refinement_service.py backend/tests/test_pipeline_api.py`
  passed.
- A local Markdown link check inspected all links in the plan board, this epic, and this report.
  Every local path exists.

## Decisions and limits

The node-backed revisions stay authoritative. The calibration API reads the selected immutable
revision. It does not choose a newer calibration when a scene asks for another revision. Source
and calibration mismatches remain visible in the inspector and block mutation.

Pose edits use pointer dragging, typed inspector controls, and the scene JSON editor. Rotation has
no center handle; use its typed inspector field.
