# Epic 0114 M7: Interactive writes and controls

M7 adds a disposable-storage HTTP timing runner for durable interactive write and control
families. Each sample measures one complete synchronous ASGI response. The samples are preliminary;
they do not establish a baseline or a performance budget.

## Coverage

The runner retains 36 passing samples. It measures pipeline node edit, copy, restore, and item,
coverage, and overall review writes; exact readback verifies content, revision identity, and review
kinds. It measures selection writes and readback for events, observations, visible cards, and visual
identities. It measures pipeline-run submission and durable parent-job readback, job submit, queue
move, cancel, retry, and retry-lineage readback, frame-review defer and durable workflow state, and
calibration draft start, update, readback, and discard. The fixtures use temporary storage and do
not modify repository data.

The `/api/recordings/{recording_id}/video` URL appears in the UI inventory but has no registered
FastAPI route or web request constructor. The runner measures the loopback 404 response. This is an
inventory boundary case and does not define an API contract.

## Residual UI route coverage

The M0 inventory has write routes that M7 does not claim. M8 must add named real-backend API
timing and durable-effect scenarios for event, visible-card, proposed-card-scene, visual-identity,
and observation stage submissions; both round-analysis intake routes; and calibration apply. M8
also owns frame/crop/thumbnail/video-range timing, media identity, cache invalidation, bounded
polling/background work, and browser workflows. The combined M7 and M8 checks must cover every
inventoried UI write and media route. A route is covered only when a named executable scenario
measures it and checks correctness.

## Implementation note

The restore request handler read `base_pointers` although its request model did not declare the
field. The production request model now accepts this optional mapping, matching the restore service
input. `web/src/api/openapi.ts` was regenerated from the updated contract.

## Checks and result

- Write sample runner: 36/36 cases passed; all 14 durable-effect comparisons matched.
- Focused pytest: `backend/tests/test_interactive_ui_write_performance.py` passed.
- Ruff check and format check passed for the runner, focused test, and changed API module.
- Inventory check passed: 76 registered operations classified, one documented unregistered UI URL,
  and 70 planned UI cases.
- API generation and `npm run verify:api` passed.
- The response-duration samples range from under 1 ms to about 2.02 s. The longest case is
  calibration draft setup/start with a hard fixture. These single samples describe this machine
  and fixture only; M9 will establish repeated measurements and budgets.

Sample data: [M7 write samples](0114-M7_Interactive_Writes_and_Controls_Samples.json).
