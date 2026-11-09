# Epic 0118 M1: managed-job log audit

Date: 2026-11-09

## Result

No new expiry or size policy is justified. Keep every existing `logs.json` file and do not add a
cleanup action. This does not remove the existing append-time rolling limit: the writer retains at
most the latest 1,000 entries for each job. The implementation has no per-entry byte bound, so
the 1,000-entry limit is not a size ceiling. This corrects the M0 report's statement that keep-all
is the current behavior. The M0 recommendation to preserve files remains in force.

## Exact family and authority

- The default configured operations root resolves to this checkout's `data/operations`. The
  managed-job root is `<operations_root>/jobs`; one log is
  `<operations_root>/jobs/<job-id>/logs.json`.
- `JobPersistence.append_log` is the only file writer. It runs at acceptance and for job-state
  transitions. It reads all retained entries, assigns the next sequence, and atomically replaces
  the JSON file with the latest 1,000 entries.
- `JobPersistence.logs`, exposed through `JobManager.logs` and `GET /api/jobs/{job_id}/logs`, is the
  reader. The API returns pages of at most 500 entries and reports `truncated_before`.
- `JobRecovery` reads and repairs intents, jobs, queue records, and publications. It neither reads,
  recreates, nor restores `logs.json`.
- The operations-root owner is the only plausible retention authority found. No expiry authority,
  independent backup, or tested restore source for these logs was found.

## Lifecycle and access evidence

The job states are `queued`, `running`, `waiting`, and `cancelling` while non-terminal;
`succeeded`, `failed`, `cancelled`, and `interrupted` are terminal. The writer applies the same
1,000-entry rolling limit in every state. There is no age expiry. Log fields have no maximum byte
length. Restart recovery does not change log files; it may change a running job's state while
leaving its log in place.

Append calls use the manager's in-process reentrant lock and publish with atomic JSON replacement.
Readers do not take that lock. The manager's exclusive root lock prevents a second manager process
from writing concurrently. A reader can observe an old or new complete file while an append runs.
No cross-process reader behavior or external direct file reader was found.

The current checkout's configured `<operations_root>/jobs` directory is absent. Therefore the
active jobs, exact log sizes, active pins, and any live process's operations root are unknown. The
deterministic test uses a disposable root and verifies log reads during active work, terminal-state
logs, concurrent appends and reads, and persisted logs after restart. It does not qualify retained
live logs or establish a recovery source.

## Frozen decision and limits

Do not add age expiry, terminal-job expiry, a byte limit, or a changed entry-count limit. The
existing 1,000-entry rolling window is implemented behavior, not evidence that older diagnostics
are disposable or that active-job logs are sufficient. Without an independent recovery source,
deleting a log would be irreversible. Preserve files and retain the current writer behavior until
the operations-root owner and exact recovery path are verified. M4 may implement only contracts
that M1–M3 can safely establish.

## Checks

- `mise exec -- uv run --project backend pytest -q backend/tests/test_job_recovery.py` — passed,
  13 tests, including the new deterministic managed-job log lifecycle case.
- Exact source cross-reference: `config.py`, `job_store.py`, `job_persistence.py`,
  `job_models.py`, `job_recovery.py`, `jobs_api.py`, and the backend job tests.
- Root check: runtime `Settings()` resolved to this checkout's `data/operations`; its `jobs`
  directory is absent. No data was changed or removed.
