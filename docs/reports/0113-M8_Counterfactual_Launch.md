# 0113 M8 — Counterfactual launch

## Result

The round-analysis inspector now shows a **Calculate counterfactual…** action. It opens the shared
start dialog. The dialog shows the exact analysis ID and input/result hashes, the correction
constraints, and the search settings frozen in the source analysis. It submits the existing
`counterfactual` job request through shared idempotent submission. The accepted job appears in the
shared Jobs state and has a persistent job link.

The old inline launch buttons are removed. Operators still edit correction constraints in the
analysis workbench and can restore the baseline. A calculation does not accept or reject a
correction, apply calibration, or change the selected analysis. Opening and cancelling the dialog
does not submit a job. A rejected request keeps the current draft. An uncertain response keeps the
same frozen payload and idempotency key; it also locks draft editing until the operator retries.
This feature does not poll for counterfactual results.

The M0 inventory found no browser submitter for `calibration_preview`. This milestone adds no
calibration launch UI. The job type remains registered for agent tooling. Calibration evidence
editing and the existing stale-evidence/apply-validity gate are unchanged. M9 must re-audit current
callers before it removes any unused client facade.

No backend or API contract changed. The concurrent 0114 M8 change affects calculation snapshot
internals and is present in this checkout.

## Checks

- `npx vitest run src/analysis/CounterfactualWorkbench.test.tsx src/analysis/AnalysisTimelinePresentation.test.tsx src/jobs/JobStartActions.test.tsx` — 12 passed. Tests cover no job on open/cancel, exact analysis and correction request values, shared job receipt, and retry with the same frozen request and idempotency key after uncertain acceptance.
- `npx playwright test tests/e2e/pipeline-lineage-workspace.spec.ts -g 'round analysis uses the shared frame, rail, inspector, and saved selection'` — 1 passed. The browser flow verifies the right-side Actions group, exact analysis and correction summary, no submission on cancel, accepted job link, and unchanged analysis selection.
- `npm run typecheck` — passed.
- ESLint on the changed TypeScript files — passed.
- Prettier check on the changed TypeScript files — passed.
- `npm run verify:api` — passed. No generated API changes.
- `git diff --check` — passed.
- Local Markdown links added by this milestone resolve to the M8 report.

## Handoff

Requested milestones: 11. Completed: 9 (M0–M8). Remaining: 2 (M9–M10). Next, M9 re-audits browser
callers and removes obsolete launch paths only after confirming they remain unused.
