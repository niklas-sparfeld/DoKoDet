# Operations module and public API boundaries

## Plan status

- **Summary:** Remove the eager operations package facade. Split stable comparison and
  reconstruction responsibilities into direct contract and execution modules.
- **Status:** Blocked
- **Depends on:** 0053 discovery complete; 0056 must complete before M2 or M3
- **Outcome:** A pipeline comparison or round reconstruction change uses a direct,
  responsibility-focused import and focused tests without loading unrelated campaigns, review
  batches, or model operations.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Complete — recorded public consumers, import costs, safe seams, exclusions, and focused
  verification.
- **M1:** Complete — removed the eager package facade, converted its consumers to direct module
  imports, and added import-isolation coverage.
- **M2:** Blocked — waits for epic 0056 to remove its owned obsolete interfaces.
- **M3:** Blocked — waits for epic 0056 to remove its owned obsolete interfaces.

## Evidence and selected scope

The operations package has 37,151 source lines in 33 modules. Fourteen modules exceed 1,000 lines.
Its 945-line `__init__.py` imports 28 modules and re-exports 439 imported names. Therefore, an
import of `doko_operations.pipeline_data` first executes the full facade. A cold import measured
264 ms on the local baseline; a cold `derived_view` import measured 175 ms. Both imports load
unrelated review-batch and model-operation modules.

Only three tracked consumers use the package facade: backend `pipeline_service.py` and two
operations tests. The backend consumer needs pipeline-data symbols. The test consumers need
symbols from the development-split, system-holdout, and visual-identity review-batch modules. All
other backend consumers already import direct modules. The supported backend contract modules are
`pipeline_data`, `pipeline_comparison`, `derived_view`, `pipeline_reference`, `counterfactual`,
and `round_reconstruction`.

The high-value safe seams are:

- `pipeline_comparison.py` has separate schema and immutable contract records, parsers and
  serialization, event matching, and visible-card and visual-identity comparison execution.
- `round_reconstruction.py` has separate request and result contracts, input loading and assembly,
  game-engine translation, and artifact publication.

`pipeline_data.py` is a direct, shared contract module already. Splitting it does not have a
demonstrated context benefit. Do not split it in this epic.

## Exclusions and overlap

Do not redesign data, model, comparison, or reconstruction contracts. Do not change persisted
artifacts, command behavior, or import semantics outside the removed package facade. Epic 0056
owns obsolete-interface removal. Complete it before M2 or M3 so this epic does not split code that
0056 removes. Epic 0051 owns resilience behavior; do not change `derived_view.py`, resilience
modules, crop policies, or visible-region exclusion. Do not change review batches, campaigns,
intake, or model-improvement modules in this epic.

## Delivery milestones

### M1 — Explicit direct import surface

Replace the aggregate package facade with a minimal `doko_operations.__init__` that does not import
operations modules. Convert the one backend and two test facade consumers to direct module imports.
Declare direct module paths, rather than package-level re-exports, as the operations public Python
API. Add a focused import-isolation regression test that proves a direct pipeline-data import does
not load unrelated review-batch, campaign, comparison, or reconstruction modules. Update only the
operations documentation that names the removed facade.

Run `uv run pytest` and `uv run ruff check .` from `operations/`. Run
`uv run pytest tests/test_pipeline_service.py` and `uv run ruff check .` from `backend/`.

#### M1 implementation evidence — 2026-09-07

- Replaced the aggregate `doko_operations.__init__` exports with a documentation-only package
  initializer.
- Converted `pipeline_service.py` and the two operations tests that used package-level exports to
  direct module imports. The operations README now names the direct reconstruction module.
- Added `tests/test_import_isolation.py`, which checks a clean `pipeline_data` import does not load
  review, campaign, comparison, or reconstruction modules.
- Focused operations coverage passed with 19 tests, and the backend `test_pipeline_service.py`
  coverage passed. The full operations run reached 186 passed tests and two unrelated failures
  because the repository-local `.codex/skills/model-improvement` fixture is absent.
- Ruff passed for the operations and backend components after import-order fixes.

#### Dependency update — 2026-09-07

- Epic 0056 remains `Backlog`, with its removal milestones not started. M2 and M3 cannot begin
  until 0056 completes because they would otherwise split code that 0056 owns removing.

### M2 — Pipeline comparison contract and execution boundary

After 0056 completes, replace `pipeline_comparison.py` with direct, non-wrapper modules for its
immutable comparison contract and its matching and comparison execution. Keep schemas, canonical
bytes, parsing, and immutable request/result records on the contract side. Keep event, visible-card,
and visual-identity matching and comparison on the execution side. Update operations and backend
consumers to import the responsibility they use. Preserve JSON bytes, matching results, error
types, and API output exactly.

Extend focused comparison regression coverage before the move. Run
`uv run pytest tests/test_pipeline_comparison.py` and `uv run ruff check .` from `operations/`,
then `uv run pytest tests/test_pipeline_comparison_api.py` and `uv run ruff check .` from
`backend/`.

### M3 — Round reconstruction contract and execution boundary

After 0056 completes, replace `round_reconstruction.py` with direct, non-wrapper modules for
request and result contracts, input loading and assembly, game-engine execution, and artifact
publication. The backend imports contract errors and records directly. The command entry point
imports the execution function directly. Keep request and result bytes, result status, published
paths, and game-engine behavior unchanged.

Extend focused reconstruction regression coverage before the move. Run
`uv run pytest tests/test_round_reconstruction.py` and `uv run ruff check .` from `operations/`,
then `uv run pytest tests/test_round_analysis_contract.py tests/test_table_observation_pipeline.py`
and `uv run ruff check .` from `backend/`.

Each delivery milestone fits one `gpt-5.6-luna` phase. Do not add compatibility re-exports, module
aliases, or forwarding wrappers. Close this epic after M3 when the direct imports, focused tests,
and import-isolation regression prove the stated outcome.
