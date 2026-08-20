# DokoDetector — Python Evidence Ingestion Backend Implementation Plan

## Plan status

- **Summary:** Ingest and dispatch evidence
- **Status:** Draft

## 1. Goal

Build the first DokoDetector backend service.

The service receives evidence packages produced by the iOS app, validates and stores them durably, tracks their processing state, and hands each accepted package to a **hypothetical specialist vision detector**.

The specialist detector itself is **not part of this implementation**. This project must define a clean detector boundary and provide a fake implementation so that the complete ingest → store → dispatch → result lifecycle can be exercised before the real detector exists.

The backend should be designed as the beginning of the real system rather than as a disposable PoC.

---

## 2. Context and Inputs

The upstream iOS application already follows this conceptual pipeline:

```text
Camera
  → CardEventNet
  → DetectionEvent
  → EvidenceFrameBuffer
  → EventPackageAssembler
  → durable PackageStore
  → UploadCoordinator
  → backend
```

CardEventNet is only a high-recall **event gate**. It does not recognize cards.

For each likely card-play event, the phone sends a versioned evidence package containing approximately six high-resolution JPEG frames around the event, currently expected around:

```text
-800 ms
-400 ms
-100 ms
+150 ms
+400 ms
+700 ms
```

The backend must preserve all temporal evidence. It must not collapse the package to one image.

Player identity does not need to be inferred visually. Player/game context may be supplied by the client, and later game sequencing can determine who played the card.

---

## 3. Scope

### In scope

Implement:

1. HTTP evidence-package ingestion.
2. Versioned manifest parsing and validation.
3. Idempotent uploads by `package_id`.
4. Integrity verification using client-provided hashes.
5. Durable storage of the original uploaded evidence.
6. Relational metadata and processing state.
7. A detector-job abstraction.
8. A fake detector adapter.
9. An internal asynchronous worker that claims pending detector jobs.
10. Persistence of detector results.
11. Package/status/result read APIs.
12. Structured logging and basic metrics hooks.
13. Local Docker-based development environment.
14. Automated unit and integration tests.
15. OpenAPI documentation generated from the API implementation.

### Explicitly out of scope

Do **not** implement:

- card recognition;
- card localization;
- before/during/after image differencing;
- segmentation;
- perspective/corner recovery;
- rectification;
- 24-card classification;
- multi-frame visual fusion;
- game-rule inference;
- trick sequencing;
- user authentication;
- authorization;
- UI;
- video streaming;
- WebSockets;
- push notifications;
- model training;
- GPU execution;
- a generic workflow platform;
- Redis/Celery/Kafka unless a concrete requirement emerges.

The next implementation phase will provide the specialist vision detector.

---

## 4. Recommended Technology

Use a conventional Python service stack:

- **Python 3.12+**
- **FastAPI** for HTTP APIs
- **Pydantic** for request/domain validation
- **SQLAlchemy 2.x** for persistence
- **Alembic** for schema migrations
- **PostgreSQL** for durable metadata and job state
- **S3-compatible object storage** for evidence files
- **MinIO** in local development
- **boto3** or another thin S3 client for object-store access
- **pytest** for tests
- **httpx** for API tests
- **Docker Compose** for PostgreSQL + MinIO + application

Do not introduce a message broker yet.

A PostgreSQL-backed job table with `SELECT ... FOR UPDATE SKIP LOCKED` is enough for the first implementation and avoids a second distributed subsystem.

---

## 5. Architectural Principles

### 5.1 Preserve the original evidence

The uploaded package is source evidence.

Store the manifest and every submitted frame without modifying or re-encoding them.

Future detector versions must be able to rerun against the exact evidence originally received.

### 5.2 Receipt is separate from interpretation

The ingest request succeeds when:

1. the request is structurally valid;
2. all declared artifacts are present;
3. hashes and sizes validate;
4. evidence is durably stored;
5. metadata is committed;
6. a detector job exists.

The detector does **not** need to finish before the HTTP upload returns.

### 5.3 Idempotency is fundamental

The iOS client uses background uploads and may retry after ambiguous network failures.

Therefore:

```text
PUT /v1/evidence-packages/{package_id}
```

must be idempotent.

Re-uploading exactly the same package returns the existing package.

Reusing a `package_id` for different content is an error.

### 5.4 Detector code is behind a port

The ingestion application must know nothing about the eventual detector implementation.

Use an interface roughly equivalent to:

```python
class VisionDetector(Protocol):
    async def detect(self, evidence: DetectorEvidence) -> DetectorResult:
        ...
```

The actual input/output models should be domain types rather than FastAPI or SQLAlchemy objects.

### 5.5 Detector execution is asynchronous

Do not invoke the detector inline inside the upload transaction.

Persist a job and let a worker claim it.

This gives us:

- bounded upload latency;
- safe retries;
- crash recovery;
- future GPU/remote-detector compatibility;
- reprocessing support.

### 5.6 Keep the first deployment a modular monolith

Use one repository and one application codebase.

Run two processes from it:

```text
api
worker
```

They share PostgreSQL and object storage.

Do not split ingestion and detection dispatch into network microservices yet.

---

## 6. Evidence Package Contract

The backend should accept the package produced by the iOS app as multipart form data.

Canonical endpoint:

```http
PUT /v1/evidence-packages/{package_id}
Content-Type: multipart/form-data
```

Parts:

```text
manifest      application/json
frame_0       image/jpeg
frame_1       image/jpeg
...
frame_5       image/jpeg
```

Do not hard-code exactly six frames into storage/domain internals. Version 1 may require six, but the persisted representation should naturally support another count in future schema versions.

### 6.1 Manifest

Implement a versioned manifest.

Suggested V1 shape:

```json
{
  "schema_version": 1,
  "package_id": "019...",
  "event": {
    "event_id": "019...",
    "captured_at": "2026-08-19T20:30:12.345Z",
    "device_event_monotonic_ns": 1234567890
  },
  "frames": [
    {
      "part_name": "frame_0",
      "relative_time_ms": -800,
      "captured_at": "2026-08-19T20:30:11.545Z",
      "content_type": "image/jpeg",
      "byte_length": 1834217,
      "sha256": "..."
    }
  ],
  "local_model": {
    "name": "CardEventNet",
    "version": "...",
    "event_score": 0.91,
    "threshold": 0.72
  },
  "player_context": {
    "game_id": "optional",
    "player_id": "optional",
    "turn_index": 17
  },
  "score_trace": [
    {
      "relative_time_ms": -900,
      "score": 0.21
    }
  ]
}
```

Match the final field names to the iOS implementation if they already exist. Do not create two competing schemas.

### 6.2 Validation

Validate at minimum:

- path `package_id` equals manifest `package_id`;
- supported `schema_version`;
- package ID is syntactically valid;
- event ID is present;
- frame part names are unique;
- every manifest frame has exactly one multipart part;
- there are no undeclared frame parts;
- each frame MIME type is supported;
- received byte count matches `byte_length`;
- SHA-256 matches;
- relative timestamps are sensible;
- maximum package size is enforced;
- maximum individual frame size is enforced;
- manifest itself has a maximum size.

Make limits configurable.

Do not trust filenames supplied by clients for storage paths.

---

## 7. HTTP API

Implement these endpoints.

### 7.1 Upload package

```http
PUT /v1/evidence-packages/{package_id}
```

Successful new package:

```http
201 Created
```

Example response:

```json
{
  "package_id": "...",
  "state": "queued",
  "created": true
}
```

Successful idempotent replay:

```http
200 OK
```

```json
{
  "package_id": "...",
  "state": "queued",
  "created": false
}
```

If the package ID already exists but the submitted package differs:

```http
409 Conflict
```

### 7.2 Get package

```http
GET /v1/evidence-packages/{package_id}
```

Return metadata, timestamps, current state, processing attempts, and detector result summary if available.

Do not return JPEG bytes inline.

### 7.3 Get detector result

```http
GET /v1/evidence-packages/{package_id}/result
```

Possible responses:

- `200` when completed;
- `202` while queued/processing;
- `404` for unknown package;
- explicit failed state when detector processing exhausted retries.

### 7.4 Health

```http
GET /health/live
GET /health/ready
```

Readiness should verify required infrastructure connectivity.

---

## 8. Persistence Model

Use PostgreSQL.

A reasonable initial schema:

### `evidence_packages`

```text
package_id              PK
schema_version
event_id
captured_at
manifest_json           JSONB
manifest_sha256
package_fingerprint
state
created_at
updated_at
```

Suggested states:

```text
receiving       -- optional/internal only
queued
processing
completed
failed
```

A request that has not yet completed durable ingestion should generally not leave a visible package row.

### `evidence_artifacts`

```text
id                      PK
package_id              FK
part_name
relative_time_ms
captured_at
content_type
byte_length
sha256
object_key
created_at
```

Unique constraint:

```text
(package_id, part_name)
```

### `detector_jobs`

```text
id                      PK
package_id              FK
detector_name
detector_version
state
attempt_count
available_at
claimed_at
claimed_by
last_error
created_at
updated_at
```

Job states:

```text
pending
running
succeeded
retryable_failed
permanent_failed
```

Ensure only one active initial detector job exists per package/detector configuration.

### `detector_results`

```text
id                      PK
job_id                   FK
package_id               FK
detector_name
detector_version
result_schema_version
result_json              JSONB
created_at
```

Store detector output verbatim enough that future processing stages can consume or audit it.

---

## 9. Object Storage Layout

Use an S3-compatible bucket.

Suggested key scheme:

```text
evidence/
  {package_id}/
    manifest.json
    frames/
      frame_0.jpg
      frame_1.jpg
      ...
```

Prefer immutable object keys.

Do not overwrite an already committed package.

Optionally write incoming artifacts under temporary keys first:

```text
incoming/{upload_token}/...
```

and promote/copy them to the final package prefix only after validation.

Clean abandoned temporary uploads using a separate maintenance command or lifecycle rule.

---

## 10. Package Fingerprint and Idempotency

Compute a canonical package fingerprint so the server can distinguish a valid retry from package-ID reuse.

For example, hash:

```text
schema version
canonical manifest JSON
ordered list of:
    part name
    byte length
    SHA-256
```

Store this as `package_fingerprint`.

On a repeated PUT:

```text
existing package_id + same fingerprint
    → return existing resource

existing package_id + different fingerprint
    → 409 Conflict
```

Do not depend on multipart encoding, boundaries, filenames, or part ordering for idempotency.

---

## 11. Durable Ingestion Flow

Implement the upload path explicitly.

```text
HTTP PUT
   │
   ▼
parse manifest
   │
   ▼
validate manifest structure
   │
   ▼
stream each JPEG
   │
   ├── calculate SHA-256 while streaming
   ├── count bytes
   └── store to temporary object key
   │
   ▼
validate all artifacts
   │
   ▼
calculate package fingerprint
   │
   ▼
check idempotency
   │
   ├── identical existing package → cleanup temp + return 200
   ├── conflicting package         → cleanup temp + return 409
   │
   ▼
promote/write immutable evidence objects
   │
   ▼
DB transaction:
   ├── evidence_packages
   ├── evidence_artifacts
   └── detector_jobs(pending)
   │
   ▼
commit
   │
   ▼
return 201
```

Important: do not load all JPEGs into memory simultaneously.

Stream them.

For the initial implementation, it is acceptable to perform object writes before the DB transaction as long as orphaned objects are harmless and cleanup is supported.

Prefer orphaned immutable objects over a DB row that claims evidence exists when it does not.

---

## 12. Detector Boundary

Define detector-facing domain models.

Example:

```python
@dataclass(frozen=True)
class DetectorFrame:
    relative_time_ms: int
    captured_at: datetime
    content_type: str
    sha256: str
    object_key: str

@dataclass(frozen=True)
class DetectorEvidence:
    package_id: UUID
    event_id: UUID
    event_time: datetime
    frames: tuple[DetectorFrame, ...]
    local_model: LocalModelContext | None
    player_context: PlayerContext | None
    score_trace: tuple[ScoreSample, ...]

@dataclass(frozen=True)
class DetectorResult:
    schema_version: int
    payload: dict[str, Any]
```

The detector should receive object references or a storage accessor, not FastAPI `UploadFile` objects.

The real detector may eventually:

1. compare before/during/after frames;
2. locate the newly introduced card;
3. segment it;
4. recover corners;
5. rectify perspective;
6. classify it among the Doppelkopf card classes;
7. fuse evidence across frames.

None of this belongs in the current implementation.

---

## 13. Fake Detector

Implement `FakeVisionDetector`.

It exists to prove the integration boundary.

Requirements:

- deterministic;
- configurable artificial latency;
- configurable success/failure behavior for tests;
- emits a versioned synthetic result;
- must inspect enough of `DetectorEvidence` to catch broken wiring.

Example result:

```json
{
  "schema_version": 1,
  "status": "synthetic",
  "package_id": "...",
  "observed_frame_count": 6,
  "card": null,
  "confidence": null
}
```

Do not make the fake detector pretend to recognize a real card.

The distinction between infrastructure working and recognition working should remain obvious.

---

## 14. Worker

Implement a small worker process in the same codebase.

Pseudo-flow:

```text
loop
  │
  ▼
claim next available job
  │
  ▼
mark running
  │
  ▼
load package metadata + frame references
  │
  ▼
call VisionDetector.detect(...)
  │
  ├── success
  │     ├── persist result
  │     ├── job → succeeded
  │     └── package → completed
  │
  └── exception
        ├── increment attempts
        ├── retryable → schedule retry
        └── exhausted/permanent → failed
```

Use PostgreSQL row locking:

```sql
FOR UPDATE SKIP LOCKED
```

so multiple worker processes can safely coexist later.

### Retry strategy

Keep it simple:

```text
attempt 1 → immediately
attempt 2 → +5 s
attempt 3 → +30 s
attempt 4 → +2 min
attempt 5 → +10 min
```

Make the maximum attempts configurable.

Detector-domain failures that are explicitly permanent should not be retried.

---

## 15. Package State Semantics

The package state should represent the externally meaningful lifecycle.

```text
queued
  ↓
processing
  ↓
completed
```

Failure path:

```text
queued/processing
  ↓
failed
```

The worker job owns detailed retry state.

Avoid exposing infrastructure-specific intermediate states unless they are useful to clients.

A package can later support reprocessing by creating another detector job without modifying the original evidence.

---

## 16. Error Model

Return a consistent JSON error envelope.

Example:

```json
{
  "error": {
    "code": "evidence_hash_mismatch",
    "message": "SHA-256 mismatch for multipart part frame_3",
    "details": {
      "part_name": "frame_3"
    }
  }
}
```

Define stable machine-readable error codes for at least:

```text
invalid_manifest
unsupported_schema_version
package_id_mismatch
missing_artifact
unexpected_artifact
artifact_too_large
package_too_large
artifact_size_mismatch
evidence_hash_mismatch
package_id_conflict
package_not_found
```

Do not leak internal stack traces.

---

## 17. Project Structure

Suggested layout:

```text
dokodetector-backend/
├── pyproject.toml
├── README.md
├── docker-compose.yml
├── alembic.ini
├── alembic/
├── src/
│   └── dokodetector/
│       ├── __init__.py
│       ├── config.py
│       ├── api/
│       │   ├── app.py
│       │   ├── dependencies.py
│       │   ├── errors.py
│       │   └── routes/
│       │       ├── evidence_packages.py
│       │       └── health.py
│       ├── domain/
│       │   ├── evidence.py
│       │   ├── detector.py
│       │   └── errors.py
│       ├── application/
│       │   ├── ingest_evidence.py
│       │   ├── get_package.py
│       │   └── process_detector_job.py
│       ├── persistence/
│       │   ├── database.py
│       │   ├── models.py
│       │   └── repositories.py
│       ├── storage/
│       │   ├── base.py
│       │   └── s3.py
│       ├── detectors/
│       │   ├── base.py
│       │   └── fake.py
│       └── worker/
│           ├── main.py
│           └── job_runner.py
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

Do not create gratuitous abstractions merely to match this tree. The important boundaries are:

```text
HTTP
  → application service
      → package repository
      → object storage
      → job repository

worker
  → job repository
  → evidence repository
  → VisionDetector
  → result repository
```

---

## 18. Configuration

Use environment-based configuration.

At minimum:

```text
DATABASE_URL
S3_ENDPOINT_URL
S3_REGION
S3_BUCKET
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
MAX_MANIFEST_BYTES
MAX_FRAME_BYTES
MAX_PACKAGE_BYTES
DETECTOR_MAX_ATTEMPTS
WORKER_POLL_INTERVAL_MS
FAKE_DETECTOR_LATENCY_MS
```

Secrets must not be committed.

Provide `.env.example`.

---

## 19. Logging and Observability

Use structured logs.

Include these fields where applicable:

```text
package_id
event_id
job_id
detector_name
detector_version
attempt
request_id
duration_ms
```

Log lifecycle events such as:

```text
evidence_upload_started
evidence_upload_committed
evidence_upload_idempotent_replay
evidence_upload_rejected
detector_job_claimed
detector_job_succeeded
detector_job_retry_scheduled
detector_job_failed
```

Never log image contents.

Avoid logging the entire manifest by default.

Add simple counters/timers behind a small metrics abstraction if convenient, but a monitoring stack is out of scope.

---

## 20. Security and Abuse Bounds

Even without authentication, ingestion must be bounded.

Implement:

- request/package size limits;
- manifest size limit;
- per-artifact size limit;
- strict content-type allowlist;
- no client-controlled filesystem paths;
- no shell invocation;
- no image parsing required during ingestion;
- object-storage credentials from environment;
- SQL parameterization through SQLAlchemy;
- reasonable HTTP timeouts.

JPEG validity beyond MIME/hash/size does not need to be deeply decoded at ingestion time. The future detector can reject corrupt image contents.

---

## 21. Testing Strategy

### 21.1 Unit tests

Cover:

- manifest parsing;
- schema-version rejection;
- package ID matching;
- frame declaration validation;
- canonical package fingerprinting;
- hash verification;
- size verification;
- state transitions;
- retry/backoff calculation;
- fake detector;
- detector-domain/result serialization.

### 21.2 API integration tests

Using real PostgreSQL and MinIO containers where practical, test:

#### Happy path

Upload valid evidence package.

Assert:

- `201`;
- manifest object exists;
- all frames exist;
- DB rows exist;
- exactly one detector job exists.

#### Idempotent replay

Upload identical package twice.

Assert:

- first request `201`;
- second request `200`;
- one package;
- one artifact set;
- no duplicate detector job.

#### Conflicting replay

Reuse package ID with one modified frame.

Assert:

- `409`;
- original package unchanged.

#### Missing frame

Manifest declares six frames, multipart request contains five.

Assert rejection.

#### Bad hash

Modify frame bytes without updating manifest.

Assert rejection.

#### Oversized artifact

Assert request rejection and no committed package.

### 21.3 Worker integration tests

Run worker against the fake detector.

Assert:

```text
queued
→ processing
→ completed
```

and result persistence.

Also test:

```text
temporary detector failure
→ retry
→ success
```

and:

```text
repeated detector failure
→ failed
```

### 21.4 Crash-safety tests

At minimum simulate failures:

- after object upload but before DB commit;
- after job claim but before result commit;
- after detector success but before transaction commit.

Verify that retrying or restarting does not corrupt package state or create duplicate logical results.

---

## 22. Local Development Environment

`docker compose up` should provide:

```text
PostgreSQL
MinIO
API
worker
```

Also expose the MinIO console for debugging in development.

Provide commands equivalent to:

```bash
docker compose up --build
docker compose run --rm api alembic upgrade head
pytest
```

Seed no production-like data automatically.

---

## 23. Developer Fixture / Upload CLI

Add a small development command that uploads a fixture package through the real HTTP API.

For example:

```bash
python -m dokodetector.dev.upload_fixture \
  tests/fixtures/evidence/example_001 \
  --server http://localhost:8000
```

The fixture directory can contain:

```text
manifest.json
frame_0.jpg
...
frame_5.jpg
```

This will be valuable for:

- backend development;
- iOS/backend contract debugging;
- future detector development;
- reproducible bug reports.

Do not bypass the HTTP API in this tool.

---

## 24. OpenAPI Contract

FastAPI should generate OpenAPI.

Make the evidence upload API explicit enough that the iOS implementation can use it as a contract.

Document:

- multipart part names;
- manifest JSON schema;
- supported schema versions;
- status codes;
- idempotency semantics;
- maximum sizes;
- error envelope;
- package lifecycle.

Commit a generated OpenAPI snapshot to the repository if convenient so contract changes are visible in code review.

---

## 25. Implementation Order

### Phase 1 — Skeleton

Create:

- Python project;
- FastAPI app;
- settings;
- Dockerfile;
- Docker Compose;
- PostgreSQL;
- MinIO;
- health endpoints;
- pytest setup.

Acceptance:

```text
docker compose up
```

starts a healthy API and dependencies.

### Phase 2 — Domain contract

Implement:

- manifest V1 models;
- evidence domain models;
- error types;
- detector protocol;
- fake detector result schema.

Acceptance:

Valid and invalid manifests are covered by unit tests.

### Phase 3 — Persistence

Implement:

- SQLAlchemy models;
- Alembic migration;
- package repository;
- artifact repository;
- job repository;
- detector-result repository.

Acceptance:

Repository integration tests pass against PostgreSQL.

### Phase 4 — Object storage

Implement:

- object-store interface;
- S3/MinIO implementation;
- streaming writes;
- SHA-256 calculation;
- size validation;
- immutable final keys;
- cleanup of failed temporary uploads.

Acceptance:

Binary round-trip and integrity tests pass.

### Phase 5 — Ingest endpoint

Implement:

```text
PUT /v1/evidence-packages/{package_id}
```

including:

- multipart parsing;
- manifest validation;
- streamed artifact ingestion;
- integrity checks;
- package fingerprinting;
- idempotency;
- durable commit;
- pending detector-job creation.

Acceptance:

All upload integration scenarios pass.

### Phase 6 — Read endpoints

Implement:

```text
GET /v1/evidence-packages/{package_id}
GET /v1/evidence-packages/{package_id}/result
```

Acceptance:

Responses correctly represent queued, processing, completed, and failed packages.

### Phase 7 — Worker

Implement:

- safe PostgreSQL job claiming;
- detector invocation;
- retries;
- result persistence;
- package state transitions;
- graceful shutdown.

Acceptance:

A valid upload is eventually completed by `FakeVisionDetector`.

### Phase 8 — Hardening

Implement:

- structured logs;
- request IDs;
- configuration limits;
- cleanup behavior;
- crash-safety tests;
- README;
- fixture upload CLI;
- OpenAPI documentation.

Acceptance:

A developer can clone the repository, start the stack, upload fixture evidence, observe processing, and retrieve the synthetic detector result.

---

## 26. End-to-End Acceptance Scenario

The implementation is complete when this works reproducibly:

### 1. Start backend

```bash
docker compose up --build
```

### 2. Upload a real-format evidence package

```text
PUT /v1/evidence-packages/{package_id}
```

Server returns:

```json
{
  "package_id": "...",
  "state": "queued",
  "created": true
}
```

### 3. Evidence is durable

Verify:

- manifest exists in object storage;
- six JPEGs exist unchanged;
- recorded hashes match;
- metadata exists in PostgreSQL.

### 4. Worker processes package

State progresses:

```text
queued → processing → completed
```

### 5. Fetch result

```text
GET /v1/evidence-packages/{package_id}/result
```

returns a deterministic synthetic detector result.

### 6. Retry upload

Upload the exact same package again.

Server returns `200` and does not create duplicate evidence or detector jobs.

### 7. Conflict

Upload different evidence with the same `package_id`.

Server returns `409`.

---

## 27. Definition of Done

The backend phase is done when:

- [ ] the iOS evidence-package contract is represented by versioned backend models;
- [ ] uploads are streamed rather than buffered wholesale in memory;
- [ ] every artifact is hash-validated;
- [ ] original evidence is durably preserved;
- [ ] upload retries are idempotent;
- [ ] package-ID/content conflicts are detected;
- [ ] PostgreSQL holds metadata and lifecycle state;
- [ ] S3-compatible storage holds manifests and JPEG evidence;
- [ ] accepted packages atomically produce a pending detector job at the metadata level;
- [ ] a worker can safely claim jobs;
- [ ] the detector is accessed only through the `VisionDetector` boundary;
- [ ] the fake detector proves the integration path;
- [ ] detector results are persisted;
- [ ] package/result APIs expose processing state;
- [ ] worker crashes and retries do not duplicate logical work;
- [ ] tests cover upload integrity, idempotency, dispatch, retries, and recovery;
- [ ] the full stack runs locally through Docker Compose;
- [ ] a fixture evidence package can be uploaded end-to-end;
- [ ] no real card-recognition logic has leaked into this phase.

---

## 28. Guidance for the Implementing Coding Model

Treat this document as the implementation specification.

Prefer straightforward, explicit code over framework-heavy abstractions.

Important constraints:

1. Preserve the iOS manifest contract rather than inventing a parallel one.
2. Do not implement the future computer-vision detector.
3. Do not reduce the evidence package to a single “best” frame.
4. Do not perform detector work in the upload request.
5. Do not acknowledge a new package before its evidence and metadata are durable.
6. Make upload retries safe.
7. Keep original evidence immutable.
8. Keep detector-specific details behind the detector interface.
9. Do not add Redis, Celery, Kafka, Kubernetes, or microservices without a demonstrated requirement.
10. Use real PostgreSQL/object-storage integration tests for persistence-critical behavior.

When an architectural choice is unspecified, optimize for:

```text
correctness
→ debuggability
→ simplicity
→ evolvability
→ throughput
```

not hypothetical scale.

The immediate next phase after this one will replace `FakeVisionDetector` with the real specialist card-recognition pipeline.
