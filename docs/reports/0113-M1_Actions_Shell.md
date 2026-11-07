# 0113 M1 shared Actions and modal shell

M1 adds the reusable `JobStartActions` component. It renders a labeled Actions group and
action-specific forms in an accessible modal. Each form has named sections, expected output,
validation summary, loading and submitting states, Escape handling, Tab containment, and focus return.
The modal body scrolls independently. At narrow widths it uses a full-width bottom sheet.

No feature launch was integrated. No job API or request contract changed. Opening and cancelling
the fixture form call no submission handler. The shared component is ready for M2 and later action
integration.

## Verification

- `npx vitest run src/jobs/JobStartActions.test.tsx` — passed, 3 tests. Covers keyboard opening,
  focus containment and return, long form content, validation/loading states, cancel without submit,
  and workspace/drawer availability after dismissal.
- `npm run typecheck` — passed.
- `npm run lint -- --no-warn-ignored` — passed.
- `npm run test:e2e -- --grep "job start actions fixture"` — passed, 2 browser tests. The local
  fixture checks the desktop layout, narrow sheet width, keyboard interaction, long content, and
  return to the workspace alongside lineage and Jobs drawer controls.
- Production build passed. Vite reported the existing 500 kB chunk-size advisory; it did not fail
  the build.
- Prettier check and `git diff --check` passed.

The browser fixture uses drawer controls to test coexistence and focus return. It does not mount the
production lineage or Jobs drawer implementations. Feature actions are not mounted in the real
inspector yet; those integrations belong to later milestones.

## Handoff

M1 is complete. Continue with M2 exact input selection and submission handling. This run requested
11 milestones; M0 and M1 are complete, so 9 remain. The 0112 M8 extraction remains unstarted and
does not overlap the M1 shell. Coordinate its surviving request owner before 0113 M4/M5 cross that
launch boundary.
