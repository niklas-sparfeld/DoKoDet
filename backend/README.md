# DokoDetector backend

This is the local backend for the evidence upload proof of concept.

M2 adds SQLite metadata storage, Alembic migrations, and atomic local evidence storage. The
upload route is added in M3.

## Setup

Run these commands from the repository root:

```bash
mise install
cd backend
uv sync
uv run alembic upgrade head
```

## Checks

Run the local checks from `backend/`:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Run the service

Start the service from `backend/`:

```bash
uv run uvicorn dokodetector_backend.app:create_app --factory
```

Then check the health routes:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

The default local runtime directory is `.runtime/`. It is ignored by Git. Settings use these
environment variables:

```text
DATABASE_URL=sqlite:///./.runtime/dokodetector.db
EVIDENCE_ROOT=.runtime
MAX_MANIFEST_BYTES=1000000
MAX_FRAME_BYTES=10000000
MAX_PACKAGE_BYTES=100000000
```

Stored files use this layout:

```text
.runtime/evidence/<package-id>/manifest.json
.runtime/evidence/<package-id>/frames/<part-name>.jpg
```

The health readiness route is still a placeholder. The upload and readiness routes are part of
later milestones. The PoC uses one API process with local SQLite and filesystem state. It does
not provide multi-process locking or distributed coordination.
