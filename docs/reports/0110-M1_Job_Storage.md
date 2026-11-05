# Epic 0110 M1: job storage and recovery

M1 adds a standalone job storage foundation in `backend/src/dokodetector_backend/job_store.py`.
It does not register a real processor, start a scheduler, or expose an HTTP API.

A manager owns one operations root through a nonblocking process lock. It validates a fake request,
records an acceptance intent, writes a fake domain run and accepted-use record, writes the job and
queue, and commits the intent. Each write uses atomic JSON replacement. Restart replays incomplete
intents in sequence. The same key and request returns the same job; a different request conflicts.
Dispatch candidates require a committed intent, a valid queued job, and verified participant
records. Missing or damaged committed records are not recreated as executable work.

The job and queue use validated versioned records. The state machine rejects invalid transitions
and keeps terminal states terminal. Reconciliation restores missing queued entries and removes
entries that do not identify committed queued jobs. Invalid intents and queue documents block use;
other invalid or unknown records produce diagnostics. The fake queue has standalone groups only;
M2 owns group membership, scheduling, and resource admission. M3 owns active-job restart and
cancellation behavior.

`backend/tests/test_job_store.py` covers crashes after each acceptance write, replay and conflict,
input protection, missing and damaged records, queue recovery, terminal transitions, and ownership
from a second process. Run it with `cd backend && mise exec -- uv run pytest tests/test_job_store.py`.
