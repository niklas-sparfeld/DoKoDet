# DokoDetector iOS Evidence Upload — Local Backend Integration

## Plan status

- **Summary:** Prove the complete local iOS-to-backend pipeline
- **Status:** In Progress
- **Reviewed:** 2026-08-27 after plan 0005 reached M4 and the current iOS integration work
- **Depends on:** Completed plans 0003 and 0004, plus the result API from plan 0005
- **Next:** Plan 0019 can add deliberate training-recording intake after this local path works

## 1. Outcome

Connect the plan 0003 evidence client to the local backend from plan 0004.

At the end of this plan, a saved replay or camera session can:

```text
detect event
  -> persist evidence package
  -> upload to local backend
  -> receive an idempotent acknowledgement
  -> run the fake detector
  -> read the stored fake result
```

The normal development loop works on a MacBook. A phone, Docker, and cloud services are not
required.

## 2. Fixed decisions

- Use the V1 contract and fixtures from plan 0003.
- Use Foundation `URLSession`. Add no generic networking library.
- Keep the filesystem as the local queue source of truth.
- Do not add player or turn context. The game engine owns retrospective attribution.
- Do not add ROI configuration. Inference and evidence use complete frames.
- Keep capture, inference, persistence, and networking independent.

## 3. Scope

### In scope

1. A minimal capture-session identity and persistent event sequence.
2. An atomic package store with queue state.
3. Startup recovery of complete staged and queued packages.
4. A foreground `URLSession` uploader for the local backend.
5. Idempotent replay and conflict handling.
6. A small retry state that the user or test can trigger.
7. A basic capture and queue status UI.
8. Read-back of the scripted result created by plan 0005.
9. End-to-end tests against the local backend and one-shot detector runner.

### Out of scope

- background `URLSession` and relaunch task reconciliation;
- automatic network-aware retry scheduling;
- storage quotas and retention policy;
- polished production UI;
- authentication;
- remote deployment;
- App Store work;
- broad physical-device support.

## 4. Work packages

### M0 — Capture session identity

Persist only the data needed to order evidence:

```text
session_id
started_at_utc
next_event_sequence
```

Use one monotonic session-relative clock for event and frame alignment. Assign each emitted event
a sequence before package assembly. Do not reuse a sequence after restart.

Do not model players, seats, turns, trick leaders, or game rules.

Acceptance:

- session IDs and positive event sequences survive restart;
- wall-clock changes cannot change frame-to-event alignment.

### M1 — Durable filesystem queue

Use Application Support with a small explicit state layout:

```text
DokoDetector/
  sessions/
  packages/
    staging/
    queued/
    acknowledged/
    failed/
    corrupt/
```

Write and validate all artifacts in `staging`, then atomically move the package to `queued`.
Networking starts only after that move.

On startup:

1. Enumerate staged and queued packages.
2. Validate manifest/file agreement and hashes.
3. Recover complete staged packages.
4. Move unexplained invalid data to `corrupt`.
5. Expose the result in diagnostics.

Do not add Core Data, SwiftData, SQLite, or a queue database.

Acceptance:

- termination after finalization does not lose a package;
- the queue reconstructs from files;
- corrupt content is retained for inspection.

### M2 — Local HTTP integration

Use the plan 0003 multipart writer and a foreground `URLSessionUploadTask` with a file body.

Map responses as follows:

```text
201 or 200 with matching package_id -> acknowledged
409                                 -> permanent conflict; retain package
408, 429, 5xx, transport failure    -> retryable
other 4xx                           -> permanent client/package failure
```

An identical replay is success. It is not a conflict. Preserve the backend's current state from
the response.

Keep the base URL in typed configuration. The simulator can use the local Mac backend address.
Do not weaken transport security globally for a future remote service.

Acceptance:

- complete, incomplete, and metadata-only packages upload;
- identical replay returns the existing package;
- conflicting content is retained and visible;
- request creation does not load the full multipart body into memory.

Add a small read client for the plan 0005 result endpoint. Keep result display in developer UI for
this plan. The app must not interpret candidate cards with game rules.

### M3 — Basic operator UI

Keep this UI functional and small:

- start and end a capture session;
- show camera/replay state;
- show the latest event sequence;
- show queued, acknowledged, retryable, and permanent-failure counts;
- allow a retryable package to be retried;
- keep replay and detailed diagnostics in Debug/developer mode.

Do not ask the user for player names, seats, turn order, or a current player.

Acceptance:

- a developer can understand whether capture, package creation, or upload failed;
- views do not mutate package files directly.

### M4 — Complete local pipeline test

Run these processes with the repository's normal commands:

```text
iOS replay/test client
plan 0004 local API
plan 0005 one-shot scripted detector runner
```

Test:

1. A valid complete package.
2. An incomplete package.
3. A metadata-only package.
4. An identical retry.
5. Conflicting reuse of a package ID.
6. A temporary server failure followed by retry.
7. App restart with queued content.
8. Fake-detector result retrieval.

Use temporary SQLite and filesystem stores on the backend. Docker is not part of this gate.

## 5. Concurrency boundaries

- The camera callback only normalizes timestamps and offers frames.
- Inference has at most one operation in flight.
- Evidence encoding has at most one operation in flight at first.
- One serial owner manages the compressed ring and pending packages.
- One serial owner manages package state and upload mapping.
- SwiftUI views receive state. They do not own pipeline work.

Drop bounded sampling work instead of building a stale queue. Never drop a finalized,
unacknowledged package silently.

## 6. Verification

Run:

```text
cd ios
swift test

cd backend
uv run pytest
```

Run the local integration test with the exact shared fixtures. A short camera test on one iPhone
is useful after the replay path passes, but it is not required for the normal loop.

## 7. Definition of done

- the full local pipeline reaches a fake detector result;
- the app and backend use one V1 contract and the same fixtures;
- queued packages survive app restart;
- all accepted package variants upload;
- idempotent replay and conflict behavior match the contract;
- a developer can operate and diagnose the pipeline on a MacBook;
- no player/turn model, ROI configuration, or third-party iOS runtime dependency exists.
