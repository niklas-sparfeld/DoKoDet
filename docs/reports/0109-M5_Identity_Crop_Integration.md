# 0109 M5 identity crop integration

Date: 2026-11-07

## Result

Visual identities now uses the common exact-frame geometry surface. The center shows the full source
frame and the selected outcome geometry. It has no video, text, or controls. The inspector owns the
selected item list, crop preview, identity candidates, classification fields, review actions, and
provenance.

The crop preview uses the identity output revision and item ID. The existing endpoint verifies the
stored processor run, frozen crop input manifest, source revision, and crop digest before it serves
the image. The inspector shows the policy, input kind, source revision and digest, and source node
references. It does not create a new crop from the source frame.

Crop visibility is tied to the exact selected item and crop digest. The previous image stays hidden
until the new response loads. Missing provenance, missing crops, unusable crops, failed processing,
face-down outcomes, and stale/unavailable crop responses have explicit inspector messages. The
inspector supports crop zoom, fit, and vertical resizing. Accessible candidate buttons and 1–9
shortcuts update the classification draft. Identity edits keep frame, geometry, crop identity, and
crop input provenance fixed.

Frame polygon selection, inspector list selection, and Timeline Rail selection share the exact item
ID and requested time. Source frame overlays require an exact source SHA, frame index, presentation
time, dimensions, and image digest match. The identity proposal list no longer occupies a separate
left column.

## Verification

- `cd web && npm run check` passed: TypeScript, ESLint, Prettier, generated API comparison, and 191
  frontend tests.
- `cd web && npm run build` passed. Vite reported the existing bundle-size warning.
- `cd web && CI=1 npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts --reporter=line`
  passed. The browser fixture checked the frozen crop and provenance, exact source frame overlay,
  keyboard candidate selection, and absence of central video, text, and controls at desktop size.
  It also passed the responsive Events regression at desktop and narrow sizes, plus the Visible cards
  and Virtual scenes checks.
- No API contract changed. The generated API comparison passed.
- The epic and report pass Prettier. The board still has the existing Prettier warning. Local links
  in the board, epic, and report resolve.

## Decisions and limits

The existing frozen crop endpoint accepts the identity output revision and item ID. Its server-side
validation is the authority for crop input lineage and digest. The inspector displays the output's
stored provenance; it does not infer a newer source or regenerate pixels.

Keyboard shortcuts act only while focus is within the identity-choice section. They change the
editable classification draft. The operator must still save the correction to create a new data
revision.

## Next

M6 connects Table observations to the shared frame and Timeline Rail.
