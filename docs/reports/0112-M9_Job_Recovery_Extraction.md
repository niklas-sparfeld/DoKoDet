# 0112 M9 job recovery extraction

## Result

Complete at the implementation commit. `JobManager` is a 499-line lifecycle composition root. Job
records and errors live in `job_models.py`; persisted record operations live in
`job_persistence.py`; acceptance replay and restart reconciliation live in `job_recovery.py`.
`FakeParticipant` now lives in `backend/tests/support/job_participants.py`. Production code does not
import test support.

The durable job, intent, queue, and publication schema versions remain `backend-job/v1`,
`backend-job-intent/v1`, `backend-job-queue/v1`, and `backend-job-publication/v1`. Recovery receives
named persistence callbacks. The manager checks its process ownership lock before it exposes those
operations. `JobRecovery.recover` and `reconcile` also call the ownership guard before any read or
write. The manager invokes recovery after acquiring the filesystem lock.

## Owners and budgets

| Owner | Lines | Responsibility |
| --- | ---: | --- |
| `backend/src/dokodetector_backend/job_store.py` | 499 | Manager ownership, lifecycle, state transitions, acceptance, cancellation, retry, and publication arbitration |
| `backend/src/dokodetector_backend/job_models.py` | 232 | Errors, cancellation token, Pydantic request/state/queue/log/publication records, digest and ID helpers |
| `backend/src/dokodetector_backend/job_persistence.py` | 268 | Intent/job/queue/log/publication encoding and explicit durable operations |
| `backend/src/dokodetector_backend/job_recovery.py` | 205 | Intent replay, restart repair, publication recovery, parent/child and queue reconciliation |
| `backend/tests/test_job_store.py` | 81 | Lifecycle transitions and manager ownership |
| `backend/tests/test_job_recovery.py` | 97 | Partial acceptance writes, restart recovery, and lock enforcement |
| `backend/tests/test_job_publication.py` | 72 | Cancellation/publication arbitration and crash recovery |
| `backend/tests/test_job_scheduler.py` | 406 | Queue order, scheduler claims, cancellation, retries, and parent/child scheduling |

All listed files meet the M0 budgets: roots at most 500 lines, new production modules at most 700,
and focused tests at most 800.

## Behavior coverage

The focused suites cover idempotent acceptance and conflict handling; every acceptance write point;
queue ordering and repair; cancellation and concurrent cancellation; retry linkage; parent/child
queue recovery; interruption and preserved progress; damaged participant protection; and both
outcomes of the publication/cancellation race. The recovery suite also verifies that neither the
manager entry point nor the extracted recovery component can mutate storage before manager ownership.

## Checks

Passed on the M9 implementation revision:

- `mise exec -- uv run --project backend pytest -q backend/tests/test_job_store.py backend/tests/test_job_recovery.py backend/tests/test_job_publication.py backend/tests/test_job_scheduler.py backend/tests/test_jobs_api.py` — 44 passed.
- `mise exec -- uv run --project backend pytest -q backend/tests/test_visual_identity_job.py backend/tests/test_calculation_jobs.py backend/tests/test_automated_pipeline_jobs.py backend/tests/test_proposed_card_scene_pipeline.py backend/tests/test_round_analysis_logging.py backend/tests/test_pipeline_api.py` — 45 passed.
- Changed-file Ruff lint and format checks — passed.
- `python -m compileall -q backend/src backend/tests/support backend/tests/test_job*.py` — passed.
- `git diff --check` — passed.

Both pytest runs report the existing Starlette `httpx` deprecation warning from the test client.
