# Epic 0105 M2: Execution and Lineage

Date: 2026-11-04

## Result

The recording-scoped run now executes the frozen six-stage graph in a backend worker. The start
request returns without waiting for inference or analysis. The worker does not depend on the
browser connection.

The existing processor services create and retain the stage runs and revisions. The coordinator
records each stage request, processor run ID, input revision IDs, output revision IDs, and failure.
The overall run status API reads these records from disk. Each downstream stage receives the exact
output revision IDs from this run. Round analysis uses the retained table-observation revision and
the frozen round context, rules version, and search limits.

## Restart and failure behavior

The worker scans durable run records at startup. It queues accepted and running runs. The
coordinator manifest skips completed stages whose request and input revisions still match. An
interrupted processor run is retried with its original request and run ID. A restarted round
analysis uses a new immutable analysis ID if the previous attempt is terminally failed. Previous
analyses and stage outputs remain stored.

A failed or partial stage stops dependent work. The overall run retains the stage and its failure.
The worker does not write review selections, references, or drafts. Complete empty outputs continue
when the processor retains a revision ID for the empty result.

## Verification

The local fixture tests verify all six stage links, a complete empty event revision, blocking stage
failure, worker startup from an accepted run, and restart after a simulated interruption. The
restart test confirms that the completed event stage runs once and later stages resume from the
stored coordinator manifest. Existing coordinator tests also cover reuse of complete stages and
input-change handling.

Checks passed:

- `ruff check` on changed Python files.
- Focused tests for automated runs, worker execution, pipeline coordination, run API, and app
  lifecycle.
- `git diff --check`.

The stage adapter calls the existing retained services, so their outputs remain available through
the existing stage and workspace reads. This milestone does not add the recording workspace start
action or browser progress display; M3 owns that UI work. The fixture does not claim model quality
or verify a real-model run.
