# 0101 cleanup handoff

Date: 2026-10-31. Source: completed epic [0101](../plans/5-closed/0101-Repository_Spring_Cleanup.md)
and its [M0 inventory](0101-M0_Cleanup_Inventory.md).

## Delivered

- Removed the obsolete old-runtime evidence adoption command and its private implementation.
  Canonical upload, validation, and package readers remain.
- Moved source lifecycle command execution and human rendering into a focused operations module.
- Moved visible-card frame coverage parsing and lookup keys into a focused backend module.
- Moved identity editor data conversion and proposal matching into a focused web module.
- Rejected duplicate visible-card coverage keys before publication. Regression tests cover both
  decision orders and confirm that a rejected completion preserves the draft, selection, and
  published revision list.

The M1–M5 implementation commits are `4fbc1b6b7`, `68d4162b3`, `bf22f93d9`, `834c4546f`, and
`3b9884dbc`, respectively. The epic and board were closed after M6 verification.

## Deferred and rejected candidates

The [M0 inventory](0101-M0_Cleanup_Inventory.md) retains the evidence in detail. Storage
consolidation, migration tools, canonicalization, and historical CLI families remain because
recovery, reproduction, receipt, or campaign use was not ruled out. The CardEventNet importer has
an agent-script dependency. Broad handler/editor splits, size-only rewrites, generated API cleanup,
and commented UI removal were rejected or deferred because no bounded defect or sufficient benefit
was established. External legacy archives were not inventoried.

No additional candidate met the evidence gate for this epic. The inventory does not prove that all
dead code or bugs have been found.

## Combined verification

- Operations selected command, source lifecycle, import-isolation, and intake-contract checks:
  19 passed, 15 deselected. An unfiltered run was stopped after it entered the retained-artifact
  scan; one test had passed before interruption. This was not a completed suite or a test failure.
- Backend intake, API, coverage parser, reference service, and frame-review API checks: 91 passed.
- Identity editor data and component tests: 35 passed.
- Web TypeScript typecheck: passed.
- Generated API verification: passed; generated types matched the committed API file.
- Ruff checks for the changed operations and backend paths: passed.
- ESLint and Prettier checks for the changed identity editor paths: passed.
- The visible-card boundary check still reports the existing
  `PipelineVisibleCardEditor.integration.test.tsx` at 876 nonblank lines against an 800-line
  limit. M4 recorded this same issue.
- M4's earlier full Playwright run had 6 passing and 9 failing checks in workspace route,
  accessible-name, and frame-announcement assertions. Full web lint and format runs also reported
  existing issues in unrelated files. The focused checks above passed.
- Local Markdown links in the board, epic, M0 inventory, and this report resolve. `git diff
  --check` passed.

No source data, retained evidence, drafts, selections, frozen queues, or model artifacts were
changed. The pre-existing edit to `docs/reports/0096-M3_Exact_Reference_Evaluation.json` remains
untouched.
