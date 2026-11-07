# Epic 0109 M10 — All steps verification and closure

## Result

M10 adds a browser regression for the six working-area steps, exact run comparison, and history.
The regression scrubs the time cursor in Events, Visible cards, Virtual scenes, Visual identities,
Table observations, and Round analysis. It delays one frame response while a newer request completes
and checks that the latest requested and resolved frame remains selected.

The browser flow verifies exact frame and overlay identity, frozen crop selection, visible-region
editing through a copied revision, pose editing, keyboard card classification, unknown observation
identity, ambiguous reconstruction hypotheses, immutable comparison selection, and restoration of
an older read-only revision. It checks that the center has no video, text, or command controls.

No hardware or model rerun was needed. M10 changed no API or backend code.

## Verification

- `cd web && npm test -- src/workingArea/workingAreaFrame.test.tsx` — passed, 3 tests.
- `cd web && npm run check` — passed: type check, lint, formatting, generated API comparison, and
  187 frontend tests.
- `cd web && npm run build` — passed. Vite reports the existing 518.09 kB JavaScript chunk warning.
- `cd web && npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts` — passed, 3 tests.
- `mise exec -- uv run --project backend pytest backend/tests/test_visible_card_pipeline_api.py -k exact_event_derived_view_route`
  — passed, 1 test; 15 tests deselected.
- Local Markdown links in the updated epic, board, handoff, and inbound references — passed.

## Limits and baseline notes

The OpenAPI export logged that the temporary processor-run catalog root was unavailable. The
OpenAPI comparison passed and the API contract did not change. The backend test reports the existing
Starlette/httpx deprecation warning. The frontend bundle-size warning is unchanged. No full
assistive-technology audit was run.
