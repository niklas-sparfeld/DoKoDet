# M11 Automated Pipelines

## Result

Automated pipeline runs now use the shared Job Manager. The run API accepts a durable parent job
and returns its job ID. The parent schedules one child for each ordered stage. It waits without
holding a scheduler slot, then resumes after the child stops.

The parent stores each child link before it waits. Its child idempotency key is stable for that
parent and stage. A restart reuses that accepted child instead of creating a duplicate. A retry
keeps the old parent and child records. It reuses a completed stage only when the saved inputs match,
the child request and output match, and the manager verifies its publication.

Parent cancellation requests cancellation for all owned children. The parent reaches a terminal
cancelled state only after those children stop. Stage failures keep their child records and appear on
the parent attempt. The scheduler returns the parent group to the end of the queue after a stage so
independent work can run before the next stage.

The previous automated worker is no longer connected to application startup or run submission. Its
source cleanup remains in M15 with the other duplicate execution paths.

## Verification

- Fixture checks cover a six-stage pipeline under one scheduler slot.
- An independent job runs between two pipeline stages.
- Restart after child acceptance resumes the same child.
- Parent cancellation waits for a running child.
- A failed-stage retry retains the failed job and reuses the verified completed first stage.
- Ruff and focused backend tests pass.
- Web type checking passes. `npm run verify:api` reports a pre-existing mismatch: the regenerated
  API output omits the pipeline node routes that remain in `src/api/openapi.ts`. The generated
  automated-pipeline response fields match the new contract. This M11 change does not alter those
  lineage routes.

The wider pipeline API tests currently include concurrent uncommitted lineage changes. Their failures
are recorded in the task summary and were not used to change those files.
