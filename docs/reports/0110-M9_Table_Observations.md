# Epic 0110 M9: Table observations

## Result

Observation assembly now runs as a Job Manager leaf job. Acceptance freezes the exact event,
visible-card, and visual-identity revisions, validates their shared recording source, and records
each revision digest on the job. The processor run is prepared with the job ID before the job can
dispatch.

The manager owns queueing, retry, cancellation, restart reconciliation, and publication arbitration.
The observation service no longer owns an executor. It reports the event count as job progress,
checks cancellation before and after assembly, and publishes the output revision inside the manager's
publication lock. A valid observation with no cards remains a successful result. Failed visible-card
evidence remains `insufficient_evidence`; an empty visible-card result remains an observed zero-card
result.

Retry creates a new job and processor run. It reuses the original job's immutable three-revision
request and does not change the failed attempt.

## Verification

- Ruff lint and format checks passed for the changed Python files.
- Observation API and table-observation tests passed: 11 tests.
- The managed fixture checked exact input IDs and job digests, source provenance, a valid zero-card
  observation, failed evidence, and a failed attempt followed by an exact-input retry.

## Scope and limit

The assembler is a synchronous call with no bounded progress callback. Cancellation can stop work
before assembly starts or after the call returns, before publication. It cannot stop that call while
it is running. The job reports the known event total without claiming intermediate completion.
