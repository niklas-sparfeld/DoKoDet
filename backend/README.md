# DokoDetector backend

This is the local backend for the evidence upload proof of concept.

The backend accepts V1 evidence packages, stores their metadata in SQLite, and stores their
original manifest and frame bytes on the local filesystem. M4 adds metadata read-back, readiness
checks, and a shared-fixture upload command.

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
uv run dokodetector-backend
```

The default service listens on port `8000` and advertises `_dokodetector._tcp` with Bonjour for
iOS local discovery. The startup log shows the advertised service type and endpoint. Do not use
the direct `uvicorn` command for device discovery. It starts HTTP but does not advertise Bonjour.

In a second shell, upload the shared complete fixture:

```bash
cd backend
uv run python -m dokodetector_backend.upload_fixture \
  ../fixtures/evidence/v1/example-complete \
  --server http://127.0.0.1:8000
```

The checked-in shared examples contain manifest data but no image files. The command creates
deterministic local frame bytes and updates their transmitted length and hash fields. A fixture
with matching `frames/<part-name>.jpg` files uses those files unchanged.

Then check the health routes:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

Read the stored metadata:

```bash
curl http://127.0.0.1:8000/v1/evidence-packages/550e8400-e29b-41d4-a716-446655440000
```

The default local runtime directory is `.runtime/`. It is ignored by Git. Settings use these
environment variables:

```text
DATABASE_URL=sqlite:///./.runtime/dokodetector.db
EVIDENCE_ROOT=.runtime
MAX_MANIFEST_BYTES=1000000
MAX_FRAME_BYTES=10000000
MAX_PACKAGE_BYTES=100000000
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
BONJOUR_ENABLED=true
BONJOUR_NAME=DokoDetector
BONJOUR_HOSTNAME=
BONJOUR_ADDRESS=
```

Set `BONJOUR_ENABLED=false` when local discovery is not required. Set `BONJOUR_HOSTNAME` only
when the automatic macOS local host name is not correct. By default, the backend advertises the
private IPv4 address of the active network route. Set `BONJOUR_ADDRESS` to use a specific reachable
private IPv4 address instead.

Stored files use this layout:

```text
.runtime/evidence/<package-id>/manifest.json
.runtime/evidence/<package-id>/frames/<part-name>.jpg
```

Readiness runs a SQLite query and checks that the evidence directory can be read and written. The
PoC uses one API process with local SQLite and filesystem state. It does not provide multi-process
locking or distributed coordination.
