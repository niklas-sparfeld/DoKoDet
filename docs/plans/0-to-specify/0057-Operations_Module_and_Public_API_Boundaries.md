# Operations module and public API boundaries

## Plan status

- **Summary:** Reduce the context needed to change repository operations by defining smaller module
  responsibilities and an explicit public import surface.
- **Status:** To Specify
- **Depends on:** 0053 discovery complete
- **Outcome:** An operations change uses one responsibility-focused module and focused tests without
  loading unrelated campaign, review, comparison, and reconstruction code.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Not started — one `gpt-5.6-terra` agent maps the import and change graph and specifies
  Luna-sized delivery milestones.

## Problem and candidate paths

The operations package has 37,151 source lines in 33 modules. Fourteen modules exceed 1,000 lines,
and `__init__.py` re-exports 449 names. Candidate paths include the package export surface and large
comparison, reconstruction, model campaign, derived-view, intake, and pipeline-data modules.

## Exclusions and overlap

Do not redesign data, model, comparison, or reconstruction contracts. Do not change persisted
artifacts or behavior. Epic 0056 owns obsolete-interface removal. Epic 0051 owns resilience
behavior. Preserve direct backend imports and public consumers until M0 records them.

## M0 specification questions

- Which public imports have consumers outside operations tests?
- Which two or three common change paths load the most unrelated code?
- Where can contract types, parsing, validation, execution, and publication separate cleanly?
- Which moves avoid circular imports and thin wrapper modules?
- Which operations and backend tests prove each boundary independently?

M0 must replace this outline with small delivery milestones. Each delivery milestone must fit one
`gpt-5.6-luna` phase and name focused operations, backend, and lint checks. Close this epic without
delivery when the import graph does not support a safe context reduction.
