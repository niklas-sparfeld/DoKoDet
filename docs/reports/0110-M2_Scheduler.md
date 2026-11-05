# Epic 0110 M2: scheduler and resource admission

M2 adds `job_scheduler.py` and extends the durable queue in `job_store.py`. It runs registered
fake handlers under one shared scheduler. The application does not yet register real processors.

The default budget is one processing slot and one CPU worker, with one accelerator and one external
service permit. A handler receives its admitted allocation. The scheduler enforces the total claims
and recording-scoped domain locks. It scans queue groups in order, bypasses unavailable inputs, and
reserves a scarce resource for an earlier eligible job. Queued jobs record waiting reasons. The
scheduler claims a job before it runs the handler and releases claims when the handler stops.

Queue moves require the current revision. A conflict returns the current queue. A waiting parent
group keeps its position and ordered child IDs across restart and new child acceptance. A later
child cannot start while an earlier child has not succeeded. This is queue and dependency support;
M11 connects the real parent coordinator. A scheduler refuses to start if an active job needs
restart reconciliation. M3 owns that reconciliation, cancellation, and bounded shutdown.

The focused storage and scheduler tests cover FIFO admission, blocked inputs, resource reservation,
CPU budgets, domain locks, stale queue moves, parent group order, failed children, owner exclusion,
and restart order. They use local fake participants and handlers. Run them with
`cd backend && mise exec -- uv run pytest tests/test_job_store.py tests/test_job_scheduler.py`.
