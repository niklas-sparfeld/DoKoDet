# 0110 M6: Visible-Card Processing

## Result

Visible-card detection now runs as a leaf job in the shared Job Manager. Acceptance freezes the
validated request, exact event revision, and recording video identity. The manager creates the
processor run and accepted-use record before dispatch.

The handler reports frame progress, checks cooperative cancellation between frames and before
publication, and commits the output revision through manager publication arbitration. It uses no
more frame workers than its CPU claim, provider limit, and configured request limit. The scheduler
still runs one job at a time. Valid empty detections and per-frame failures remain in the result.
Piles, frame identity, coverage, and failure details keep their existing domain meaning.

The browser now submits and retries visible-card jobs through `/api/jobs`. It reads active state
from the job API and reads terminal output from the visible-card result API. The older feature
launch and retry routes remain as manager-backed endpoints until the API cleanup in M15. The
service no longer owns an executor, retry queue, or worker lifecycle.

## Verification

- Backend focused suite: 54 passed. This covers visible-card execution, output semantics,
  concurrency limits, queued admission, cancellation before publication, managed retry, and the
  shared job API, scheduler, and storage.
- Ruff lint and format checks passed for changed backend files.
- `RunControls` tests passed: 16 tests.
- Web TypeScript check passed.
