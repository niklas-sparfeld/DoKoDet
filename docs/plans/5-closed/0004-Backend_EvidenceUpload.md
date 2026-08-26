# DokoDetector Backend Evidence Upload — Local End-to-End PoC

## Plan status

- **Summary:** Receive and store one evidence package locally
- **Status:** Closed
- **Closure reason:** Complete
- **Reviewed:** 2026-08-26 against report 0015 and the current repository
- **Implemented through:** Commit `4918b9a` and the current backend tests
- **Next:** Plan 0005 adds the local detector-result handoff. System hardening is deferred until
  after the complete local pipeline is measured.

## 1. Outcome

Build the smallest backend that proves the iOS-to-server handoff.

At the end of this plan, a developer can run one local HTTP service, upload a package made by the
iOS PoC, and verify that:

```text
iOS evidence package
  -> HTTP PUT
  -> contract and hash validation
  -> package metadata in SQLite
  -> original manifest and JPEG files on disk
  -> HTTP read-back of stored metadata
```

This plan ends when that local flow works. It does not make the backend production-ready.

## 2. Scope boundary

### In scope

1. Scaffold a Python backend under `backend/`.
2. Implement the V1 evidence upload endpoint.
3. Parse and validate the shared V1 manifest.
4. Validate multipart parts, sizes, and SHA-256 hashes.
5. Make uploads idempotent by `package_id`.
6. Store package and frame metadata in SQLite.
7. Store the original manifest and JPEG bytes on the local filesystem.
8. Add a package metadata read endpoint and simple health endpoints.
9. Prove the complete flow with shared fixtures and automated tests.

### Out of scope

Do not add:

- a detector interface, fake detector, worker, or job queue;
- detector results or result endpoints;
- PostgreSQL, S3, MinIO, or another remote store;
- Docker, Docker Compose, Kubernetes, or cloud deployment;
- authentication or authorization;
- metrics infrastructure or distributed tracing;
- background cleanup, retention, quotas, or backup automation;
- multiple API or worker processes;
- card recognition, player attribution, or game rules.

Do not add abstractions only to prepare for one of these items. Plan 0018 must reassess them after
the local PoC provides real evidence.

## 3. Inputs and fixed decisions

### 3.1 Contract source

[Plan 0003](0003-iOS_EvidenceUpload.md) creates the source of truth for V1:

```text
SERVER_CONTRACT.md
fixtures/evidence/v1/example-complete/
fixtures/evidence/v1/example-incomplete/
```

Start contract implementation only after plan 0003 completes its shared-contract milestone. Use
the checked-in manifests and files in backend tests. Do not copy the examples into a second backend
fixture format. Do not invent different field names in this plan.

The V1 manifest has these top-level fields:

```text
schema_version
package_id
session
event
model
event_decoder
evidence_capture
camera
frames
missing_frame_targets_ms
score_trace
client
```

The client does not send player or turn context. The backend stores model, decoder, client-build,
and device-model metadata without interpreting it.

### 3.2 Local technology

Use:

- Python 3.13 and uv 0.12 from the root `mise.toml`;
- FastAPI and Pydantic for HTTP and validation;
- SQLAlchemy 2.x with SQLite;
- Alembic with one initial migration;
- the local filesystem for manifest and frame bytes;
- pytest and httpx for tests;
- Ruff for linting and formatting.

The normal loop must work on a Mac after `mise install` and `uv sync`. It must not need Docker, a
cloud service, or a phone.

### 3.3 One-process assumptions

Run one API process for the PoC. SQLite and the filesystem are local to that process.

Do not design multi-process locking or distributed coordination. Record this limit in the backend
README.

## 4. HTTP API

### 4.1 Upload a package

```http
PUT /v1/evidence-packages/{package_id}
Content-Type: multipart/form-data
```

The multipart request contains:

```text
manifest  application/json
frame_00  image/jpeg
frame_01  image/jpeg
...
```

The manifest declares which frame parts are present. V1 permits an incomplete package and a
metadata-only package. Missing targets must be explicit in the manifest.

Return `201 Created` for a new package:

```json
{
  "package_id": "...",
  "state": "stored",
  "created": true,
  "received_at": "2026-08-19T20:11:27.004Z"
}
```

Return `200 OK` when the same package is uploaded again:

```json
{
  "package_id": "...",
  "state": "stored",
  "created": false,
  "received_at": "2026-08-19T20:11:27.004Z"
}
```

Return `409 Conflict` if the `package_id` already exists with different content.

Use the error shape and status codes from `SERVER_CONTRACT.md`. Do not expose stack traces or local
paths.

### 4.2 Read stored package metadata

```http
GET /v1/evidence-packages/{package_id}
```

Return:

- package identity and `stored` state;
- receipt time;
- session and event identity;
- stored manifest metadata;
- frame part names, byte lengths, hashes, and relative paths;
- missing frame targets.

Do not return JPEG bytes inline. Return `404 Not Found` for an unknown package.

### 4.3 Health

```http
GET /health/live
GET /health/ready
```

Liveness reports that the process runs. Readiness performs a small SQLite query and verifies that
the configured evidence directory is readable and writable.

## 5. Validation and idempotency

Validate at least:

- the path and manifest `package_id` values match;
- `schema_version` is supported;
- required session, event, model, decoder, capture, camera, and client fields are present;
- frame part names are unique and safe;
- every declared frame has exactly one multipart part;
- no undeclared frame part is present;
- frame content types are supported;
- byte lengths and SHA-256 hashes match;
- present and missing targets form the configured target set without duplicates;
- `evidence_complete` agrees with the missing-target list;
- configurable manifest, frame, and package size limits are met.

Do not trust multipart filenames. Generate storage paths from validated package IDs and part names.

Compute a deterministic package fingerprint from:

```text
SHA-256 of the received manifest bytes
ordered frame entries:
  part name
  byte length
  SHA-256
```

Sort frame entries by part name. Do not include multipart boundaries, filenames, or received part
order.

The iOS PoC persists immutable manifest bytes and resends them on retry. V1 can therefore treat a
byte-different manifest as different content even when its parsed JSON is equivalent.

## 6. Local persistence

SQLite stores searchable metadata. The filesystem stores the exact uploaded evidence bytes.

### 6.1 SQLite schema

Create one initial Alembic migration with these tables.

`evidence_packages`:

```text
package_id           primary key
schema_version
session_id
event_sequence
event_time_ms
manifest_json        JSON text
manifest_sha256
package_fingerprint
state                always "stored" in this plan
received_at
```

Add a unique constraint on `(session_id, event_sequence)`.

`evidence_frames`:

```text
id                   primary key
package_id           foreign key
part_name
target_offset_ms
actual_offset_ms
session_elapsed_ms
captured_at_utc
content_type
byte_length
sha256
relative_path
```

Add a unique constraint on `(package_id, part_name)`.

Store the parsed manifest in `manifest_json`. Do not normalize every nested field for the PoC.

### 6.2 Filesystem layout

Use one configured evidence root:

```text
<evidence-root>/
  evidence/
    <package-id>/
      manifest.json
      frames/
        frame_00.jpg
        frame_01.jpg
        ...
```

Write the received manifest bytes and frame bytes without reformatting or re-encoding them.

Write a new upload to a temporary directory below the same evidence root. Validate it before a
rename to the final package directory. Never overwrite an existing final directory.

For this PoC, clean up ordinary request failures. Crash recovery and orphan cleanup are follow-up
work.

## 7. Ingestion flow

Keep the request path explicit:

```text
receive multipart request
  -> parse and validate manifest
  -> copy each declared frame to a temporary file in bounded chunks
  -> calculate byte count and SHA-256 during the copy
  -> validate the complete package
  -> calculate the package fingerprint
  -> return the existing row for an identical replay
  -> reject a conflicting replay
  -> rename the temporary directory to its final path
  -> insert package and frame rows in one SQLite transaction
  -> return 201
```

If the database insert fails during a normal request, remove the newly renamed directory. A hard
process crash can leave an orphan. Do not build a reconciliation system in this plan.

FastAPI `UploadFile` may spool an incoming part. Do not read the complete multipart package into
one in-memory byte string.

## 8. Project shape

Use a small layout. Add files only when a phase needs them.

```text
backend/
  pyproject.toml
  README.md
  alembic.ini
  alembic/
  src/dokodetector_backend/
    app.py
    config.py
    api.py
    contract.py
    models.py
    repository.py
    storage.py
  tests/
```

Keep FastAPI, Pydantic, and SQLAlchemy types at their boundaries. Plain functions or small domain
types are sufficient between them. Do not create generic repository or storage frameworks.

Use environment settings for:

```text
DATABASE_URL
EVIDENCE_ROOT
MAX_MANIFEST_BYTES
MAX_FRAME_BYTES
MAX_PACKAGE_BYTES
```

Defaults use a repository-local ignored runtime directory. Tests use temporary directories.

## 9. Implementation phases

Each phase must leave the backend runnable and its tests passing. Use a small test-first cycle when
practical.

### M0 — Scaffold the local service

Implement:

- `backend/pyproject.toml` and the source package;
- settings with local defaults;
- the FastAPI application factory;
- liveness and placeholder readiness routes;
- pytest and Ruff configuration;
- ignored runtime files;
- a short README with exact local commands.

Acceptance:

```text
mise install
cd backend
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

All commands pass without Docker.

### M1 — Implement the shared contract

First add tests that load both shared V1 manifest fixtures. Then implement:

- Pydantic request and response models;
- manifest consistency checks;
- package fingerprint calculation;
- stable API error responses.

Acceptance:

- complete, incomplete, and metadata-only manifests are accepted;
- malformed identities, target sets, and frame declarations are rejected;
- fingerprint tests do not depend on multipart order;
- the backend uses the repository fixtures directly.

### M2 — Add SQLite and filesystem storage

First add repository and storage tests with temporary paths. Then implement:

- the initial SQLite migration;
- package and frame inserts and reads;
- the unique logical-event constraint;
- temporary evidence directories and final rename;
- exact-byte manifest and frame persistence.

Acceptance:

- a stored package survives application restart;
- database rows point to existing relative paths;
- saved bytes have the expected SHA-256 hashes;
- a failed normal write leaves no accepted package row or final directory.

### M3 — Implement the upload endpoint

First add HTTP tests around the shared fixtures. Then implement the complete `PUT` flow.

Acceptance tests cover:

- a new complete package returns `201`;
- a new incomplete package returns `201`;
- a metadata-only package returns `201`;
- an identical replay returns `200` and creates no duplicate rows or files;
- different content with the same package ID returns `409`;
- a reused logical event with a different package ID returns `409`;
- a missing, extra, oversized, or hash-mismatched part is rejected;
- rejected content is not visible as a stored package.

### M4 — Prove the local end-to-end flow

Implement:

- the package metadata `GET` endpoint;
- the real readiness check;
- a small development command that uploads a shared fixture;
- one subprocess or in-process end-to-end test;
- final README instructions.

Use a command equivalent to:

```bash
cd backend
uv run alembic upgrade head
uv run uvicorn dokodetector_backend.app:create_app --factory
uv run python -m dokodetector_backend.upload_fixture \
  ../fixtures/evidence/v1/example-complete \
  --server http://127.0.0.1:8000
```

Acceptance:

- one command uploads the shared fixture through the real HTTP route;
- the read endpoint reports the stored metadata;
- SQLite contains the package and frame rows;
- the manifest and every submitted JPEG exist unchanged on disk;
- the full automated test and Ruff checks pass.

This completes plan 0004.

## 10. Definition of done

Plan 0004 is complete when:

- [x] the backend starts locally with the toolchain declared by `mise`;
- [x] the shared V1 fixtures drive the backend contract tests;
- [x] complete, incomplete, and metadata-only packages upload successfully;
- [x] bad declarations, sizes, and hashes are rejected;
- [x] identical retries are idempotent and conflicting retries return `409`;
- [x] package metadata is stored in SQLite;
- [x] original manifest and frame bytes are stored on disk;
- [x] stored metadata can be read through HTTP;
- [x] the local end-to-end fixture upload is reproducible;
- [x] relevant tests, linting, and formatting checks pass;
- [x] no production infrastructure or detector workflow was added.
