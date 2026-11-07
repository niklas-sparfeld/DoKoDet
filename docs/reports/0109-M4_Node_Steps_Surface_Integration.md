# 0109 M4 node-step surface integration

Date: 2026-11-07

## Result

M4 is incomplete. The visible-card and virtual-scene editors now use the common
exact still-frame loader. Their controls render in the inspector. Frame lists
render in the Timeline Rail. The center contains the still source image and
visible-card region, pile, and ignore overlays.

The visible-card editor keeps its region, pile, and ignore JSON editing, review
commands, and copy-on-change save path. The virtual-scene editor keeps its pose
and stacking-order JSON editing, review commands, and copy-on-change save path.
Both editors check the accepted video SHA and exact requested time before they
allow changes. Virtual-scene edits also require a matching calibration identity.
Both editors have pan and zoom controls. They report unavailable exact frames
and calibration facts outside the center.

## Blocker

The current virtual-scene node contract contains a calibration revision ID and
digest. It does not contain the table-to-image homography or card dimensions.
The browser API has no read endpoint for the exact published calibration
revision. The editor therefore cannot project table-plane poses onto source
pixels or offer a rectified viewpoint. It disables the rectified option and
keeps pose and stacking edits in the inspector JSON field. It does not draw
pose outlines or provide direct pose handles.

M4 acceptance requires the pose and stacking operations and viewpoint controls
to remain available. The available contract cannot support those operations
safely on the common surface. Do not mark M4 complete until the workspace can
load an exact calibration transform with its revision and digest, and tests
prove projection mismatch blocks edits.

## Checks

- `npm run check` passed: typecheck, ESLint, Prettier, generated API comparison,
  and 189 frontend tests.
- `npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts --reporter=line`
  passed. It verifies Events at 1440 × 900 and 390 × 844. It does not verify
  Visible cards or Virtual scenes in a browser.
- No backend or API changes were made.

## Next work

Add or select an exact calibration-read contract that returns the published
homography and card dimensions. Then complete calibrated pose overlays,
viewpoint switching, and pose/stacking editing with exact-frame browser tests.
