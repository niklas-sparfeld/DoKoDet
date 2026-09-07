# Backend pipeline service boundaries

## Plan status

- **Summary:** Separate clear backend pipeline responsibilities so one stage, reference, or
  workspace change does not require the complete pipeline service and API surface.
- **Status:** To Specify
- **Depends on:** 0053 discovery complete
- **Outcome:** Backend pipeline code has explicit service, contract, route, and store ownership with
  focused verification.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Not started — one `gpt-5.6-terra` agent traces backend wiring and specifies Luna-sized
  delivery milestones.

## Problem and candidate paths

Eight pipeline-named backend files contain 7,450 lines. `pipeline_service.py` combines event runs,
comparison, and workspace assembly. `pipeline_reference_service.py` combines command handling,
content-specific edits, coverage, impact, and publication. `pipeline_api.py` contains all pipeline
HTTP models and routes. Candidate paths also include their stores, app wiring, and focused tests.

## Exclusions and overlap

Do not change HTTP, OpenAPI, persistence, processor, review, or failure semantics. Do not move
analyzer or game rules into the backend. Preserve 0051 visual identity and derived-view behavior.
Coordinate generated web API changes with the web verification boundary.

## M0 specification questions

- Which services own state and which only translate or compose it?
- Which stage and reference seams already have focused tests?
- How can API models and routes split without changing generated OpenAPI?
- Which imports and constructor wiring can change without cycles or duplicate validation?
- Which backend, local pipeline, and web API checks cover each proposed milestone?

M0 must replace this outline with small delivery milestones. Each delivery milestone must fit one
`gpt-5.6-luna` phase and name focused backend, lint, and OpenAPI checks. Close this epic without
delivery when a proposed split adds indirection without a measured navigation gain.
