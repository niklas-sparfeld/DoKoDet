# Test-support import guard

## Plan status

- **Summary:** Complete the remaining import-direction verification from epic 0112.
- **Status:** Ready
- **Depends on:** [0112 cleanup](../5-closed/0112-Active_Pipeline_Module_Cleanup.md) complete.
- **Outcome:** M0 remains. Fix and verify the identified test-support import guard gaps.

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

## Execution handoff

- Next: M0. This run requests one milestone; completed 0, remaining 1.
- Preserve the closed 0112 plan. Update its cleanup handoff to report the actual verification.
