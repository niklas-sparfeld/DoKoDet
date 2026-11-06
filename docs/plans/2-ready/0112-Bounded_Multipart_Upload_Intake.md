# Bounded multipart upload intake

## Plan status

- **Status:** Ready
- **Depends on:** Existing upload routes and filesystem storage. No unmet epic dependency.
- **Outcome:** Oversized upload requests stop before multipart parsing can consume unbounded
  temporary storage. Valid uploads retain their current publication and retry behavior.

## Evidence and priority

Source inspection on 2026-11-06 found three multipart intake paths:

- [Evidence packages](../../../backend/src/dokodetector_backend/api.py) parse the form before
  checking file and aggregate payload sizes.
- [Repository bundles](../../../backend/src/dokodetector_backend/repository_bundle_api.py) parse
  the form before staging files and checking their total size.
- [Pending videos](../../../backend/src/dokodetector_backend/pending_video_api.py) pass
  `max_pending_video_bytes` to `request.form(max_part_size=...)`. The storage writer applies the
  file limit after form parsing.

The installed Starlette multipart parser applies `max_part_size` to non-file fields. File parts
are written to spooled temporary files without that check. Thus the application payload checks
do not bound bytes consumed during multipart parsing. No request-body byte guard was found in
the application factory or these routes. This is source evidence, not a measured disk-exhaustion
incident. M0 must reproduce it against the repository's resolved dependency version.

This matters for normal local development: an accidental large video can fill temporary storage
before the backend rejects it. The existing [server contract](../../../SERVER_CONTRACT.md)
already requires received-byte limits and no publication on rejection.

## Scope and design

Add a shared request-stream byte guard to these three upload routes. Count actual received bytes
before they reach the multipart parser. Do not buffer the complete request or trust
`Content-Length` as the only check. A valid oversized declared length can cause early rejection;
missing or inaccurate length headers must not bypass the streaming limit.

Keep aggregate file-payload limits and whole HTTP-body limits distinct. For each route, derive
the body limit from its existing aggregate payload setting plus an explicit finite multipart
envelope allowance. Pending videos use `max_pending_video_bytes` as their payload budget.
Specify and document the allowance in M0. It must cover the supported part count and normal
headers without giving boundary strings or part headers an unlimited budget. Requests within
the body budget still undergo all current per-file and aggregate payload checks.

Use a small shared helper or route wrapper. Choose the integration point in M0 after checking
FastAPI exception handling and parser cleanup. Do not access private request attributes or fork
the multipart parser. Return a stable HTTP 413 error in the existing error envelope for body
overflow. Preserve existing per-file error codes. An aborted parse must close all temporary
files, leave no staged publication, and preserve an existing upload with the same ID.

This epic does not add upload jobs, change model processing, alter lineage contracts, add cloud
services, or introduce a proxy requirement. Concurrent-upload admission and total disk quotas
are separate work. A per-request limit does not bound aggregate concurrent disk use.

## Milestone status

- **M0:** Not started — reproduce the gap and freeze the body-limit contract.
- **M1:** Not started — implement the guard and connect all three upload routes.
- **M2:** Not started — verify cleanup, retry behavior, and document the limits.

## M0 — Reproduce the gap and define limits

Add small local tests with deliberately low byte limits. Use a direct ASGI receive harness where
the HTTP client would normalize headers or consume the complete request in advance. Record the
resolved Starlette version and the exact file-spooling behavior. Define each route's body budget,
multipart allowance, overflow error code, and malformed-length behavior in a short report.

Acceptance:

- Demonstrate that a file part can pass `max_part_size` during parsing and fail a later payload
  check. Use bytes, not a large real recording or a model invocation.
- Add regression cases for missing length, a declared length smaller than the delivered body,
  exact body limit, one byte above the limit, and an oversized declared length.
- Regression tests expose the missing guard. Existing focused upload tests retain their baseline.
- Resolve the integration point and finite envelope allowance before M1 starts.

## M1 — Bound bytes before multipart parsing

Implement the shared guard and route integration. Retain current storage publication and
validation. Add deterministic tests for all three route budgets.

Acceptance:

- The parser never receives a chunk that would take its input above the body budget.
- Stop receiving after overflow; do not drain or buffer the remaining request body.
- Return HTTP 413 in the standard error envelope. No media probe, decoder, or publication starts
  after overflow. An oversized declared length is rejected before the first body read.
- Missing or understated length headers cannot bypass the guard. Requests exactly at the body
  limit pass the guard and remain subject to ordinary payload validation.
- Non-upload routes retain their behavior. Existing aggregate and per-file limits still apply.
- Focused tests pass; Ruff lint and formatting pass for changed Python files.

## M2 — Verify cleanup and close the epic

Test failures during parsing after a file has rolled to disk, client disconnects, and valid retries
after rejection. Update the server contract and backend README with the three body budgets and
the difference between envelope and payload limits.

Acceptance:

- Instrument spooled files and assert closure after overflow and client disconnect. Assert no
  partial staging directory or published receipt remains. Do not rely only on process cleanup.
- Retrying a rejected ID with a valid upload succeeds. Rejecting an oversized retry leaves an
  existing published upload byte-for-byte intact.
- Run upload coverage in `tests/test_app.py`, `tests/test_pending_videos.py`, and the repository
  bundle route tests identified in M0. Stub media probing where necessary.
- Run `mise exec -- uv run ruff check .` and `mise exec -- uv run ruff format --check .` from
  `backend`. Record unrelated baseline failures separately and resolve in-scope failures.
- Verify local Markdown links. Publish a short result report, update the board, and close the
  epic only when all acceptance criteria pass.

## Execution handoff

Planning only. No implementation milestone has started. The next action is M0. Existing Jobs
drawer work in the web checkout is unrelated and must remain intact. No persistent milestone
run or multi-agent loop is authorized by this plan.
