# 0125 M1: Detection-set editing and review

## Result

M1 proves the first complete detector and browser workflow with disposable recording data. The
existing detector receives the exact event-set reference and saves each examined frame into an
immutable M0 detection-set version. It keeps the current visible-card node output for active
readers. A failed outcome remains in the processor run and does not create detection coverage. An
examined empty frame is saved with no detections.

The visible-card workspace links the latest detector result to its exact set and version. The
segment editor reads that version, resolves its exact source frame, edits one object's segment
list, and saves a new immutable version. A separate geometry review can accept or reject the
selected object's geometry. Old versions remain readable.

Correction 1 constrains each geometry review to one explicit frame/object pair. Object IDs remain
frame-local, so a review cannot cover two frames and ambiguously refer to the same ID in both.
Backend validation checks the object in the exact covered frame. A regression saves two frames
with the same object ID, rejects a review that names both frames, confirms no review was saved,
then accepts a review for one exact pair. The browser proof now fetches version 1 again after the
backend restart and compares its persisted content with the original version.

The only new M1 persistent contract is a recording-local geometry review. The API writes
`detection-review/v1` to
`data/recordings/<recording-id>/detection-sets/<set-id>/reviews/<review-id>.json`. Each record
stores a safe review ID, exact set/version and content digest, reviewer, question, decision,
covered frame and object IDs, and timestamp. Save validates its targets against the immutable
version. The review list validates the saved record against the same version.

## API and owners

- `POST /api/recordings/{recording_id}/pipeline/visible-cards` and its result route continue to
  use the existing detector and job service. A completed result includes `detection_set_ref` when
  the exact event-backed set was saved.
- M0 remains the detection-set API owner:
  `POST /api/recordings/{recording_id}/detection-sets` and
  `GET /api/recordings/{recording_id}/detection-sets/{set_id}/versions/{version}`.
- Geometry review routes are
  `POST /api/recordings/{recording_id}/detection-sets/{set_id}/versions/{version}/reviews` and
  `GET` on the same route ending in `/reviews`.
- Backend owners are `visible_card_pipeline_service.py`, app/composition wiring,
  `detection_set_store.py`, `detection_sets_api.py`, and `pipeline_stage_api.py`.
- Web owners are `RecordingWorkspaceShell.tsx`,
  `PipelineNodeVisibleCardEditor.tsx`, `detectionSetClient.ts`, the existing pipeline processing
  client, and exact-version URL state `detection_set` plus `detection_version`. The existing node
  editor and 0096 review path remain available.

## Verification

The backend API test runs the deterministic detector against an exact event-set version. It
checks pixel-coordinate conversion, exact event ancestry, empty examined coverage, failed-frame
exclusion, and detection-set reopen after constructing a new app. The review API test validates
frame/object targets, the recording-local path, and independent review reopen after app restart.

The real-backend Playwright workflow uses a deterministic detector stub and disposable persisted
data. It opens the detector's exact set link, edits one object's segment, saves version 2, reviews
that version, restarts the backend process, then reopens the same URL and verifies the segment and
review. It also verifies that version 1 remains unchanged and that failed work is absent from
detection coverage.

- `mise exec -- uv run --project backend pytest backend/tests/test_detection_set_api.py backend/tests/test_visible_card_pipeline_api.py -q` — passed, 16 tests.
- `mise exec -- uv run --project backend ruff check` on changed backend files — passed.
- `mise exec -- uv run --project backend ruff format --check` on changed backend files — passed.
- `cd web && npm run generate:api` — passed.
- `cd web && npm run check` — passed: typecheck, lint, format, generated API verification, 46 test files and 243 tests.
- `cd web && npm run test:e2e:detection-set` — passed, 1 real-backend browser workflow.
- `cd web && npx vitest run src/visibleCards/PipelineNodeVisibleCardEditor.test.tsx` — passed, 6 tests.
- `mise exec -- uv run --project backend pytest backend/tests/test_detection_set_api.py backend/tests/test_visible_card_pipeline_api.py backend/tests/test_pipeline_node_reviews.py backend/tests/test_frame_review_bindings.py backend/tests/test_frame_review_lineage_target.py backend/tests/test_frame_review_queue.py backend/tests/test_frame_review_api.py backend/tests/test_visible_card_review_frontend.py -q -k 'not test_save_review_receipt_requires_exact_applicable_node_review'` — passed, 36 tests.
- `git diff --check` and local Markdown link checks — passed.

One existing 0096 regression remains failing:
`backend/tests/test_frame_review_api.py::test_save_review_receipt_requires_exact_applicable_node_review`
returns HTTP 409 where the test expects 200. The same failure was reproduced in the clean main
worktree at baseline `dac0caba`, before this correction. `frame_review_api.py` owns this receipt
applicability path; M1 does not change it. This is a known baseline gap, not evidence that the
acceptance criterion passed.

## Limits and next milestone

M1 does not change `Recording HEAD`, remove visible-card node readers or writers, change
downstream input formats, convert retained data, or qualify detection quality. M2 must specify the
exact consumer conversions, calibration reflow writer, comparison path, and bounded 0096 frame
review bridge before implementation. M3 retains retained-data rehearsal, cutover, path removal,
and qualification.
