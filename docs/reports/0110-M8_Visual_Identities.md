# Epic 0110 M8: Visual identities

## Result

Visual identity classification now runs as a Job Manager leaf job. The service freezes one exact
visible-card or proposed-scene revision and its crop-input manifest before it accepts work. The job
record includes both input digests and the classifier configuration.

The manager owns queueing, execution, progress, cancellation, retry, and restart recovery. The
service no longer owns a background executor. It keeps bounded card workers inside the job's CPU
claim. It checks cancellation between cards and before publication. The manager serializes result
publication against cancellation.

Failed or unusable crops remain item outcomes in the domain result. Job execution success does not
claim that every card has an identity. The generated result pointer advances only for normal
classification runs. Auto-approval can request a local classification job, but it does not change
review decisions.

## Verification

- Ruff lint and format checks passed for the changed Python files.
- The managed identity fixture passed. It ran event, visible-card, and identity work through jobs,
  then checked the exact visible-card input and published domain result.
- Job API, scheduler, and storage tests passed with the managed identity fixture: 44 tests.
- The full older visual-identity API test file has seven failures during setup because those tests
  submit events through the retired `POST /pipeline/events` route. Their requests receive 405 before
  visual identity work starts. The new managed-flow fixture uses `/api/jobs`.
- `mise exec -- ruff` could not find Ruff in the declared environment. `uv run --project backend`
  provided the repository environment and passed the checks above.

## Scope

This milestone does not change the classifier, crop derivation, review policy, or generated data
contract. The existing uncommitted crop-lineage changes in the identity service and API tests remain
outside this milestone commit.
