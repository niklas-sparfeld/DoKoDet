# Execution history in jobs

- **Status:** Backlog
- **Depends on:** No delivery prerequisite for 0124. Deferred until the normal app workflow is usable and a concrete duplicate-state problem justifies this work.
- **Outcome:** Inspect and recover an event-processing execution through the existing Job Manager, with one operational execution history and independently readable saved results.
- **Origin:** User discussion on 2026-11-10; [recording storage decision](../../RecordingDataStorage.md).

## Problem and observable success

Jobs already store requests, execution state, progress, cancellation, logs and result links.
`ProcessorRunStore` stores another request/state pair. `PipelineLineage` stores execution inputs,
outputs, status and request context again. The saved result should own its direct parents and
producer facts. A job should own execution. A processor run remains a useful concept but does not
require a separately retained domain resource.

The first delivery boundary is event processing only. Submit an event job, inspect its frozen inputs
and processor configuration, observe progress, cancel or recover it after restart, and open its
result through job result links. Result content and provenance remain usable when terminal job
history is absent. Existing adapters for other processors remain until separately scoped conversion.
Do not create another universal execution envelope or scheduler.

Non-goals: migrating all historical attempts, preserving every failed run forever, changing model
behavior, replacing the scheduler, converting other resource formats, deleting historical files or
rewriting Git history. Historical job retention is a policy for operational usefulness; selected
experiments or diagnostic evidence may be retained explicitly. No blanket deletion is authorized.
Git history can preserve earlier records without requiring live runtime support for their format.

## Evidence and smallest approach

Inspect `job_models.py`, `job_store.py`, `job_persistence.py`, `event_jobs.py`,
`event_pipeline_service.py`, `processor_run_store.py`, `processor_run_reader.py`,
`pipeline_lineage.py`, and `pipeline_lineage_writer.py` before assignment. Current event execution
uses durable processor request/state plus lineage start/finish alongside the Job Manager. Reuse
existing job requests/results and participant recovery. Prefer participant payloads for exact
processor inputs and output references. Do not migrate all processors to prove one event job.

Removing duplicate execution state cannot precede the saved-data independence proof: some current
output producer metadata contains only a run ID, and the workspace scans execution records for
relationships. 0124 M3 restores the normal app workflow and fixes only the data dependencies that block it.
It does not promise universal execution-history independence. Verify this independence for the
selected path here before removing duplicate execution records. 0129 is not a dependency of 0124
cutover. Do not turn historical run counts into required migration scope.

## Deferral decision — 2026-11-10

App usability and simplification through a complete workflow take priority. This epic is independent
and deferred. Start it only after the normal app works and a concrete duplicate-state failure or
maintenance cost justifies the selected boundary. Do not add it as a prerequisite to 0124 or
automatically start it after 0124. Revalidate the assignments against the then-current code.

## Milestones

| Milestone | Observable result and commit boundary | State |
| --- | --- | --- |
| M0 | Event job executes and exposes frozen processor inputs and result links using job-owned state; recovery/cancel proof through real APIs | Deferred |
| M1 | Event job detail and workspace use job history; remove duplicate event processor-run and lineage-run lifecycle writers/readers | Deferred |
| M2 | Qualify restart, failure and terminal-history independence; document retention and archive boundary for historical event execution records | Deferred |

### M0 assignment boundary

Before implementation, trace event participant validation, durable acceptance, execution, publication
and recovery. Name the exact call sites and freeze the request/result fields using existing job
payloads. Owners: `event_jobs.py`, event execution branches in `event_pipeline_service.py`,
`job_models.py`/participant payload validation only, `job_store.py`/`job_persistence.py` only if a
specific missing lifecycle guarantee is demonstrated, and the event output publisher. No new store
or transaction contract is planned. Preserve the global manager's queue, child-wait and publication
recovery guarantees; do not rewrite them.

Checks: real persisted event job submit/progress/result, exact inputs and processor configuration,
cancellation, restart before and after output publication, no duplicate publication, and saved result
inspection with operational history unavailable. A processor stub is sufficient. Keep existing job
recovery regressions. Commit implementation, tests, and plan/board evidence together. Stop and
perform scope review if this requires scheduler changes or conversion of unrelated participants.

Specify M1's concrete UI/API adapters after M0 proves the workflow. Specify M2's finite record
retention boundary before starting it. No automatic sweep, data deletion, or Git history rewrite.

## Closure check

A real API/UI event job runs, reports progress and exact result references, cancels correctly and
recovers through the existing Job Manager. New event jobs do not create separate processor-run or
lineage-run lifecycle authorities. Saved results contain exact direct parents and producer facts
and open after terminal job history is removed in disposable storage. Other participants and job
recovery regressions pass. Document which historical records are diagnostic archives, not runtime
authorities; keep actual cleanup separate from this delivery.

## Execution handoff

Planning only; deferred. Baseline three milestones, three remain, none implemented. First complete job workflow is M0;
qualification is M2. No implementation run authorized. No automatic continuation from 0124.
