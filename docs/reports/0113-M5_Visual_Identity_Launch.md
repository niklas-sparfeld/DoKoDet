# 0113 M5 — Visual identity launch

M5 moves visual identity classification into the shared Actions modal in the recording inspector.
The modal collects one exact crop geometry revision, provider and crop policy. It shows processing
configuration and blockers. It displays the model selected by the configured classifier. The
existing visual identity endpoint validates provider and model availability when it accepts the
request. An unavailable choice leaves the modal open with the service error.

## Crop geometry and policy

The form lists generated Gemini polygon and RF-DETR segment revisions, exact proposed virtual-card
revisions, and reviewed virtual-card or visible-card revisions when available. Multiple inputs require
an explicit choice. Each selection retains its exact node ID, revision ID, and current-head or
historical policy. Proposed virtual-card input always selects the local classifier and disables the
provider control.

The crop-policy menu only lists choices supported by the selected geometry. Generated and
proposal-derived visible regions support predicted-visible-region, predicted-region-with-other-card-
exclusion, and raw-rectangular policies. Reviewed regions support oracle-visible-region and
raw-rectangular policies. Changing geometry clears the previous policy choice so an incompatible
choice cannot remain selected. Crop output encoding remains PPM.

Starting classification creates processor outcomes only. The modal states that a person reviews and
accepts or rejects identities separately. It does not call a review or approval route. The visual
identity editor, accept/reject controls, and result history remain available.

## 0112 coordination and API

The browser keeps the existing `POST /api/recordings/{recording_id}/pipeline/visual-identities`
request contract. M5 owns the modal form and request construction. 0112 M8 remains responsible for
the later request-builder extraction from `RunControls`; adapt this caller to that builder when M8
runs. No backend or generated API changes were needed.

The current browser API does not expose an availability list. The modal shows the provider choices
and local default, then the service validates availability before acceptance. It does not silently
switch providers.

## Verification

Checks are recorded after implementation and against the M5 commit below.

- `npm test -- --run src/pipeline/RunControls.test.tsx src/jobs/JobStartActions.test.tsx src/pipeline/RecordingPipelineWorkspace.test.tsx src/api/client.test.ts` — passed, 51 tests.
- `npm run typecheck` — passed.
- `npm run lint -- --no-warn-ignored` — passed.
- `npm run test:e2e -- --grep "job start actions fixture"` — passed, 2 browser checks for keyboard/focus, drawer interaction, desktop/narrow layout, and cancel without submission. Vite reported the existing 500 kB chunk-size advisory.
- Prettier on changed source, epic and report — passed.
- Local Markdown links across board, epic and report — passed; `git diff --check` — passed.

No backend, API schema, generated API contract or review API changed. The report is part of the M5
implementation commit; the commit ID is recorded in the active epic handoff and Git history.
