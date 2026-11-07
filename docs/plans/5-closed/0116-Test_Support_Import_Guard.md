# Test-support import guard

## Plan status

- **Summary:** Complete the remaining import-direction verification from epic 0112.
- **Status:** Closed
- **Depends on:** [0112 cleanup](../5-closed/0112-Active_Pipeline_Module_Cleanup.md) complete.
- **Outcome:** M0 complete. The guard rejects extension-qualified fixture imports and imports from `__tests__` directories. Focused regressions and repository checks pass; see the [0112 cleanup handoff](../../reports/0112-Cleanup_Handoff.md#epic-0116-m0-closeout).
- **Closure reason:** Complete

## Evidence and scope

The [0112 cleanup handoff](../../reports/0112-Cleanup_Handoff.md#open-verification-gap) records
that the TypeScript guard accepts test-fixture imports with explicit `.ts` or `.tsx` extensions and
imports from `__tests__` directories. Keep the existing source-size and import-direction checks.
This work changes the guard and its tests; it does not change runtime behavior.

## M0 — Complete test-support import verification

Observable result: the guard rejects production imports of test-only fixtures with or without source
extensions and imports from `__tests__` directories, including static and dynamic import forms.
It continues to accept legitimate production imports and test-only source files. Inspect current
import detection for equivalent forms and cover any relevant gaps within this boundary.

Required checks: add focused regression tests for both reported gaps and static/dynamic variants,
including legitimate negative cases; run the guard regression suite and the guard against the current
repository; run applicable Ruff lint and format checks. Record exact commands, results, and the
verified revision in the cleanup handoff. Update the board and close this follow-up only when its
acceptance passes. Commit the implementation, tests, and plan updates together.

## M0 result

The guard detects static imports, re-exports, dynamic imports, and `require` references to
test-only fixture modules. It accepts normal production imports and excludes test-only source
files from production violations.

Checks passed: `mise exec -- uv run --project backend pytest -q scripts/test_0112_boundaries.py`
(7 passed), `python scripts/check_0112_boundaries.py`, and Ruff check and format checks for both
guard files. See the [0112 cleanup handoff](../../reports/0112-Cleanup_Handoff.md#epic-0116-m0-closeout)
for exact commands and the verified source revision.
