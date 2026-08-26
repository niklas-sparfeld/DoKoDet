# DokoDetector backend

This is the local backend for the evidence upload proof of concept.

M0 provides the FastAPI service scaffold and placeholder health routes. It does not store
evidence yet. SQLite, filesystem storage, and upload routes are added in later milestones.

## Setup

Run these commands from the repository root:

```bash
mise install
cd backend
uv sync
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
EVIDENCE_ROOT=.runtime/evidence
MAX_MANIFEST_BYTES=1000000
MAX_FRAME_BYTES=10000000
MAX_PACKAGE_BYTES=100000000
```

The M0 readiness route is a placeholder. The complete SQLite and filesystem checks are part of
M4. The PoC uses one API process with local SQLite and filesystem state. It does not provide
multi-process locking or distributed coordination.
