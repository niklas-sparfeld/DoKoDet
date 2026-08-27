# DokoDetector backend

This is the local backend for the evidence upload proof of concept.

The backend accepts V1 evidence packages and V1 training recordings. It stores metadata in SQLite
and stores original source bytes on the local filesystem. M4 adds metadata read-back, readiness
checks, and a shared-fixture upload command.

The commands and names below describe the current implemented PoC. The target architecture replaces
the scripted VisionDetector result with a `TableEvidenceAnalyzer` table observation and adds an
optional bounded video snippet. See
[Table Observation and Game Reconstruction](../docs/TableObservationReconstruction.md),
[plan 0006](../docs/plans/3-in-progress/0006-GameEngine_v1.md), and
[plan 0025](../docs/plans/2-ready/0025-Video_Snippet_Evidence.md). The implementation plans rename
the runtime interfaces; this README must continue to match the code until those plans land.

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

Upload a complete training recording from the shared fixture:

```bash
cd backend
curl -X PUT http://127.0.0.1:8000/v1/training-recordings/recording-fixture-001 \
  -F 'manifest=@../fixtures/training-recording/v1/recording-fixture-001/manifest.json;type=application/json' \
  -F 'video=@../fixtures/training-recording/v1/recording-fixture-001/video-fixture-001.mov;type=video/quicktime' \
  -F 'predictions=@../fixtures/training-recording/v1/recording-fixture-001/video-fixture-001.json;type=application/json'
curl http://127.0.0.1:8000/v1/training-recordings/recording-fixture-001
```

Run the local scripted detector once for the first pending package:

```bash
cd backend
uv run python -m dokodetector_backend.run_vision --once
```

Use `--package-id <uuid>` to select a package, or add `--all` to process all pending packages.
Read results at `/v1/vision-results/<result-id>` or
`/v1/evidence-packages/<package-id>/vision-results`.

Run the complete local pipeline gates from `backend/`:

```bash
uv run pytest tests/test_local_pipeline.py
```

The gate starts the real local HTTP API with temporary SQLite and filesystem stores. It uses the
Swift `CardEventProbeLocalPipeline` client to upload complete, incomplete, and metadata-only
packages, then checks idempotent replay, conflict retention, transport retry, queue recovery after
an app restart, scripted detection, and result read-back. The same test module also runs a saved
H.264 video through recording, outage retry, backend intake, CardEventNet import, proposal review
entry, and `cardevent prepare`. It does not require Docker, a phone, or cloud services.

The default local runtime directory is `.runtime/`. It is ignored by Git. Settings use these
environment variables:

```text
DATABASE_URL=sqlite:///./.runtime/dokodetector.db
EVIDENCE_ROOT=.runtime
MAX_MANIFEST_BYTES=1000000
MAX_FRAME_BYTES=10000000
MAX_PACKAGE_BYTES=100000000
MAX_RECORDING_MANIFEST_BYTES=1000000
MAX_RECORDING_PREDICTIONS_BYTES=10000000
MAX_RECORDING_VIDEO_BYTES=1000000000
MAX_RECORDING_BYTES=1100000000
VISION_DETECTOR_NAME=scripted
VISION_DETECTOR_VERSION=scripted-v1
VISION_DETECTOR_MAPPING_PATH=
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

## macOS firewall

When the backend is used by a physical iPhone, the phone opens an incoming connection to the Mac.
The backend listens on `0.0.0.0` and advertises its private LAN address with Bonjour, so the macOS
Application Firewall may need to allow the Python executable. This is not needed when the client
and backend use `127.0.0.1` on the same Mac, such as with a simulator.

macOS can show an approval dialog when an unapproved application first accepts an incoming
connection. A command-line Python process may not show this dialog reliably. For local development,
find the interpreter used by `uv`:

```bash
cd backend
uv run python -c 'import sys; print(sys.executable)'
```

Use the printed path in these commands:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add \
  /path/to/the/python/executable

sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp \
  /path/to/the/python/executable
```

Homebrew versioned Python paths can change after an upgrade, so check the path again if the backend
becomes unreachable. Do not make the backend run these commands itself: changing the firewall
requires administrator authorization and must remain an explicit system security action.

For distribution, package the process that owns the listening socket as a signed and notarized
macOS application or executable. A signed launcher is not sufficient if it starts an unsigned
Python process. macOS uses code signing when it makes Application Firewall decisions. See Apple's
[firewall documentation](https://support.apple.com/en-gb/guide/mac-help/mh34041/mac) and
[Code Signing Guide](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/AboutCS/AboutCS.html).

Stored files use this layout:

```text
.runtime/evidence/<package-id>/manifest.json
.runtime/evidence/<package-id>/frames/<part-name>.jpg
.runtime/vision-results/<result-id>/result.json
.runtime/training-recordings/<recording-id>/manifest.json
.runtime/training-recordings/<recording-id>/videos/<video-id>.mov
.runtime/training-recordings/<recording-id>/predictions/<video-id>.json
.runtime/training-recordings/<recording-id>/intake/dataset-record.yaml
.runtime/training-recordings/<recording-id>/intake/candidate-review-queue.json
```

There is no delete API for recordings. To remove local test data, stop the service, delete the
recording directory, and delete its SQLite row:

```bash
cd backend
rm -rf .runtime/training-recordings/<recording-id>
sqlite3 .runtime/dokodetector.db \
  "DELETE FROM training_recordings WHERE recording_id = '<recording-id>';"
```

Readiness runs a SQLite query and checks that the evidence directory can be read and written. The
PoC uses one API process with local SQLite and filesystem state. It does not provide multi-process
locking or distributed coordination.
