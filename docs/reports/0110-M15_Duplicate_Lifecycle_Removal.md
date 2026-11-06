# 0110 M15 — Remove duplicate UI and execution contracts

Feature pages now send job management to the shared `/jobs/{id}` route. They do not poll
processor, analysis, counterfactual, automated-pipeline, or recording-list status on their own.
The Jobs provider owns active-job polling. Domain history remains in the pipeline workspace and
result routes.

The pipeline stage API no longer exposes per-run status and retry routes or hidden `/runs` and
`generated-selection` aliases. It keeps run lists, selection updates, and exact result routes. The
browser client no longer defines methods or path helpers for removed status and retry operations.
Generated OpenAPI types reflect the route set.

The obsolete `AutomatedPipelineWorker`, standalone coordinator, HTTP coordinator executor, and
coordinator CLI are removed. The durable parent and child job implementation remains. Pure stage
request construction and the frozen stage plan now live in `automated_pipeline_contracts.py`.
Bounded inner worker pools for visible-card and visual-identity jobs remain under scheduler resource
claims.

New processor launch responses include the manager job ID. Legacy run history has a null job ID;
the UI does not create a job link for it. Counterfactual submissions return a shared job link.
Round-analysis acceptance returns the manager job ID separately from its domain analysis ID. The
app uses the manager ID for job navigation. Existing output bytes, review decisions, and sealed
artifacts were not changed.

## Verification

- Focused backend route, proposed-scene, stage-plan, and round-analysis tests passed (57 tests).
- Focused browser API and feature tests passed (31 tests).
- Web typecheck, focused ESLint, Prettier, and generated API verification passed.
- Focused `ruff check` passed.
- A broader backend run also exercised `test_automated_pipeline_run.py`; one existing
  `test_start_rejects_invalid_preflight_without_persisting_a_run` test failed because its fixture
  no longer raises for a session mismatch. This failure is outside M15's touched preflight logic.
- The search for feature-owned poll loops found no remaining status polling outside the shared job
  provider and job detail view. The only remaining executor pools are the shared job scheduler and
  the bounded inner worker pools noted above.

## Limits and next work

Automated-pipeline GET remains a saved history read for retained run records; it does not schedule,
change, or poll work. M16 must exercise parent and child jobs after restart and verify history and
exact result navigation across the full workflow.
