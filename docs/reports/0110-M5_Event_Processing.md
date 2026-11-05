# 0110 M5: Event Processing

## Result

Event processing and event import now run as leaf jobs in the shared scheduler. The event service
does not own an executor or a retry queue. The browser submits and retries event work through
`/api/jobs`.

Before acceptance, each job freezes its validated processor request and recording video identity.
An import job also stores the validated artifact bytes and digest in the durable request. A later
change to the source import file does not change accepted work.

The manager creates the linked processor run and accepted-use record before it can dispatch the
job. The handler reports progress, checks cancellation before publication, and commits its output
through the manager's publication arbitration. Recovery reconciles linked processor runs with job
state. Legacy runs without a manager link keep their existing recovery path.

The event start, import, status, and retry routes were removed. Event run listing, selection, and
result routes remain domain APIs. The browser reads active status from the job API and reads
terminal output from the event result API.

## Verification

- Backend focused suite: 62 passed. This covers job storage, scheduling, job APIs, and event
  processing, import, cancellation, retry, and restart flows.
- Ruff format and lint passed for the changed backend files.
- Web TypeScript check passed.
- `RunControls` tests passed: 16 tests.
- Browser API types were regenerated from the updated OpenAPI schema.
