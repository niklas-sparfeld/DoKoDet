# Epic 0110 M3: cancellation, retry, and recovery

M3 adds cooperative stop tokens to scheduler handlers. A cancel request changes queued work to
`cancelled` and active work to `cancelling`. The scheduler keeps its resource claims until the
handler returns. Repeated cancel requests are safe. Graceful shutdown requests cancellation and
waits for active handlers up to a configured bound. If a handler does not stop, the scheduler keeps
its claims and refuses a second scheduler on the same manager.

`JobManager.publish` serializes publication against cancellation. Cancellation that wins prevents
the commit callback. Publication that wins stores exact result references and succeeds; a later
cancel returns the terminal result. The manager writes a publication receipt before the domain
commit. On restart, a supplied verifier checks the durable output. A verified output completes the
job; otherwise active work becomes `interrupted` and is not dispatched again.

Explicit retry creates a new job ID and idempotency key, links `retry_of`, and keeps the previous
attempt unchanged. Parent attempts are retried as new parent jobs. Children are recreated under the
new parent. M3 declares no partial-work checkpoints, so retries start from the beginning. Result
publication uses an exact attempt identity to prevent overwriting another attempt's output.

Focused fixtures cover queued and active cancellation, cancellation during a held call, claim
retention until stop, cooperative shutdown, restart interruption with progress retention, retry
history, cancellation/publication ordering, and recovery after a crash between domain commit and
the committed receipt. Run them with
`cd backend && mise exec -- uv run pytest tests/test_job_store.py tests/test_job_scheduler.py`.
The focused result was 37 passed. Ruff checks passed for the changed backend files.
