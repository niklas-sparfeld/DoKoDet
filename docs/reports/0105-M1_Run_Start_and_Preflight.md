# Epic 0105 M1: Run Start and Preflight

Date: 2026-11-04

## Result

M1 adds a recording-scoped start and status API:

- `POST /api/recordings/{recording_id}/pipeline/runs` validates and freezes the request.
- `GET /api/recordings/{recording_id}/pipeline/runs/{run_id}` reads the durable run record.

The backend stores the run under
`data/operations/pipeline/automated-runs/`. The record includes the recording video identity,
request digests, frozen round facts and stage settings, resolved provider and model identities, and
one pending row for each of the six stages.

Preflight requires an accepted recording, the matching recording session, explicit round and game
identity, four active players, dealer, first-trick leader, rules version, search limits, all five
processor-stage settings, and available local providers. The backend checks the CardEventNet
checkpoint and stores its digest. It resolves local visible-card and identity providers and stores
their versions and bundle identity when available. Identity settings use the automatic
`predicted_visible_region` crop policy.

The backend does not start a processor before preflight succeeds. An invalid request returns
actionable preflight details and creates no run. A successful request returns `202` with status
`accepted`. The same idempotency key and body return the existing run with `200`. A different start
for a recording with an active run returns `409` and the active run ID. The store uses atomic JSON
replacement and a per-recording process lock.

M1 establishes the boundary and record only. Stage scheduling and execution are M2. A run remains
`accepted` until M2 adds the worker. Restart recovery is also part of M2.

## Verification

- Automated run service and API tests: passed.
- Pipeline workspace and route inventory tests: passed. The focused route inventory now records
  39 stage routes; the previous expected count of 38 was stale.
- Existing coordinator tests: passed.
- Ruff check and format: passed for all changed Python files.
- `git diff --check`: passed.

The tests use local fixtures and fake providers. No model inference ran.

## Limits

The request API is ready for the workspace action in M3. It does not yet schedule or execute stages,
show run status in the workspace, or recover accepted work after a backend restart. M2 and M3 own
those behaviors.
