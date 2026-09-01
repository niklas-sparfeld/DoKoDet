# DokoDetector backend

This is the local backend for the evidence upload proof of concept.

The backend accepts V2 evidence packages and V1 repository bundles. It stores searchable metadata
in SQLite and stores every accepted source bundle on the repository intake root. SQLite, temporary
uploads, caches, and analyzer output are disposable runtime state.

The backend stores table observations produced by a `TableEvidenceAnalyzer` and adds an optional
bounded video snippet. See
[Table Observation and Game Reconstruction](../docs/TableObservationReconstruction.md),
[plan 0006](../docs/plans/5-closed/0006-GameEngine_v1.md), and
[plan 0025](../docs/plans/5-closed/0025-Video_Snippet_Evidence.md). The runtime stores the
canonical `table-observation/v1` contract and does not import training modules.

## Setup

Run these commands from the repository root:

```bash
mise install
cd backend
uv sync
uv run alembic upgrade head
```

For the local visible-card provider, install its pinned native inference dependency as well:

```bash
uv sync --group inference
```

Build the browser package once before starting the backend:

```bash
cd ../web
npm ci
npm run build
```

The build writes hashed assets to `web/dist`. The backend serves that package at
`/round-analyses/` and does not need a Node.js process after the build. For frontend development,
run `npm run dev` in `web/`; its `/v1` requests use the local backend proxy.

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
The normal server uses Gemini for both visible-card detection and visual card identity by default.
Set `VISIBLE_CARD_PROVIDER=local`, `VISIBLE_CARD_BUNDLE_PATH`, and `VISIBLE_CARD_DEVICE=cpu` or
`mps` to use a validated native detector bundle. Set
`VISIBLE_CARD_IDENTITY_CLASSIFIER=local`, `VISIBLE_CARD_IDENTITY_BUNDLE_PATH`, and
`VISIBLE_CARD_IDENTITY_DEVICE=cpu` or `mps` to use the validated local DINOv3 identity bundle.
The detector and identity settings are independent. A Gemini API key is required only when either
selected component uses Gemini.

## Terminal logs

The backend writes one structured event per line to standard error. The default level is `INFO`.
At this level, the terminal shows startup, service availability, accepted intake, round-analysis
state changes, completion, warnings, and backend failures. Uvicorn access logs remain enabled.

Set `DOKO_LOG_LEVEL=DEBUG` before startup to add the technical path: validation, queue transitions,
per-package analyzer progress, reconstruction, artifact publication, and readiness checks. The
accepted values are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`, without regard to case.

```bash
# Normal local operation. INFO is also used when DOKO_LOG_LEVEL is unset.
unset DOKO_LOG_LEVEL
uv run dokodetector-backend

# Troubleshoot one local run with the technical trace enabled.
DOKO_LOG_LEVEL=DEBUG uv run dokodetector-backend
```

Use `INFO` events to follow business outcomes. `WARNING` events identify rejected input or
recoverable local problems. `ERROR` events identify failed backend work and include its traceback.
`DEBUG` events explain how the backend reached an outcome and are off by default. Events use stable
fields such as `request_id`, `upload_id`, `package_id`, `recording_id`, `analysis_id`, and
`session_id` when they apply.

For a short troubleshooting view, filter the terminal stream by event name. This keeps the
operator view focused on analysis outcomes; it does not save logs in the repository:

```bash
DOKO_LOG_LEVEL=DEBUG uv run dokodetector-backend 2>&1 | \
  rg 'round_analysis_(created|state_changed|completed|failed)|http_request_(rejected|failed)'
```

Logs do not contain request bodies, media bytes, authorization values, complete manifests, raw
model prompts or responses, SQL values, or paths outside configured runtime roots. Do not paste an
`ERROR` traceback into a public issue without checking it for local environment details first.

Start it with the required runtime credential:

```bash
export GEMINI_API_KEY='your-key'
export GEMINI_MODEL='gemini-3.6-flash'
export GEMINI_TIMEOUT_SECONDS=120
export GEMINI_MAX_RETRIES=2
uv run dokodetector-backend
```

In a second shell, upload the shared complete fixture:

```bash
cd backend
uv run python -m dokodetector_backend.upload_fixture \
  ../fixtures/evidence/v2/example-complete \
  --server http://127.0.0.1:8000
```

The checked-in complete example contains a small H.264/MP4 snippet and six JPEG frames. A fixture
with matching media files uses those files unchanged.

Then check the health routes:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

Read the stored metadata:

```bash
curl http://127.0.0.1:8000/v1/evidence-packages/550e8400-e29b-41d4-a716-446655440000
```

Read the original bounded snippet bytes:

```bash
curl http://127.0.0.1:8000/v1/evidence-packages/550e8400-e29b-41d4-a716-446655440000/video-snippet \
  --output snippet.mp4
```

Upload a complete repository bundle from the shared fixture:

```bash
cd backend
curl -X PUT http://127.0.0.1:8000/v1/repository-bundles/recording-both \
  -F 'manifest=@../fixtures/repository-bundle/v1/both/manifest.json;type=application/json' \
  -F 'source_record=@../fixtures/repository-bundle/v1/both/source-record.json;type=application/json' \
  -F 'task_enrollment=@../fixtures/repository-bundle/v1/both/initial-task-enrollment.json;type=application/json' \
  -F 'video=@../fixtures/repository-bundle/v1/both/videos/video-both.mov;type=video/quicktime' \
  -F 'proposal=@../fixtures/repository-bundle/v1/both/predictions/proposal-both.json;type=application/json'
curl http://127.0.0.1:8000/v1/repository-bundles/recording-both
```

Run the complete local pipeline gates from `backend/`:

```bash
uv run pytest tests/test_local_pipeline.py
```

The gate starts the real local HTTP API with temporary SQLite and filesystem stores. It uses the
Swift `CardEventProbeLocalPipeline` client to upload complete, incomplete, and metadata-only
packages, then checks idempotent replay, conflict retention, transport retry, and queue recovery
after an app restart. The saved-video test also submits one linked round analysis and checks the
terminal deterministic result, the replacement repository bundle, and its canonical member
hashes. It does not require Docker, a phone, or cloud services.

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
REPOSITORY_INTAKE_ROOT=data/intake/recordings
EVIDENCE_PACKAGE_INTAKE_ROOT=data/intake/evidence-packages
PENDING_VIDEO_ROOT=data/incoming/videos
FRONTEND_DIST=web/dist
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
BONJOUR_ENABLED=true
BONJOUR_NAME=DokoDetector
BONJOUR_HOSTNAME=
BONJOUR_ADDRESS=
GEMINI_API_KEY=<required at runtime>
GEMINI_MODEL=gemini-3.6-flash
GEMINI_TIMEOUT_SECONDS=120
GEMINI_MAX_RETRIES=2
VISIBLE_CARD_PROVIDER=gemini
VISIBLE_CARD_BUNDLE_PATH=
VISIBLE_CARD_DEVICE=
VISIBLE_CARD_IDENTITY_CLASSIFIER=gemini
VISIBLE_CARD_IDENTITY_BUNDLE_PATH=
VISIBLE_CARD_IDENTITY_DEVICE=
```

## Round recording analysis

The round-recording PoC uses the Record view and one local backend process:

1. Select a complete real-game collection profile. Set the dealer and first trick leader.
2. Start and stop one round recording. The app gives the recording and all evidence packages the
   same recording and session identity.
3. The app uploads the complete recording bundle and its evidence packages. It submits analysis
   only after every upload has a successful backend acknowledgement.
4. The app stores the client-generated analysis ID beside the recording queue metadata. It can
   retry a lost create response after relaunch without creating a second analysis.
5. While Record is visible and the app is active, the app polls the analysis once per second. It
   shows "Waiting for uploads", "Queued", "Analyzing evidence", "Reconstructing", "Complete", or
   a safe failure message. A complete result shows a short reconstruction summary. It does not
   show the full result JSON.

The analysis API has two JSON endpoints:

    POST /v1/round-analyses
    GET  /v1/round-analyses/{analysis_id}

The create request contains the recording ID, recording-derived round ID, UUID session ID, fixed
four-seat setup, ordered evidence package UUIDs, and the three explicit Plan 0031 search limits.
The create response is 202 and the status endpoint returns 200. The backend rejects an empty
package list, duplicate or unknown packages, mixed sessions, mismatched recording lineage, and a
recording bundle that is not stored.

The normal backend analyzer is the existing `VisibleCardTableAnalyzer`. It uses the configured
visible-card provider for proposals and the independently configured identity classifier for visual
card identity. Gemini uses the model and runtime settings above and caches successful and
unavailable responses below the runtime root. A provider or classifier failure produces an
insufficient-evidence observation and the round analysis continues with the existing uncertain
reconstruction semantics. Local identity observations include the bundle identity, selected
device, load time, and one-frame inference time. These are measurements for the proof only, not
latency or quality claims.
The local one-frame run record contains detector load and inference times. These values are a smoke
measurement, not a latency or quality evaluation.

The worker is process-local and does not resume interrupted analysis. On backend restart, each
non-terminal analysis row becomes failed with "The analysis did not finish before the backend
restarted." The app displays that terminal failure. Start a new recording to run a new analysis.
The client does resume a pending upload or a lost create response after an app relaunch; this does
not resume work that the backend already interrupted.

Deterministic status documents for the UI and contract tests are in
../fixtures/round-analysis/v1/statuses.json. They cover every progress state and all four
successful reconstruction statuses: resolved, ambiguous, incomplete, and impossible.

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
.runtime/table-observations/<observation-id>/observation.json
data/intake/recordings/<recording-id>/manifest.json
data/intake/recordings/<recording-id>/source-record.json
data/intake/recordings/<recording-id>/initial-task-enrollment.json
data/intake/recordings/<recording-id>/videos/<video-id>.mov
data/intake/recordings/<recording-id>/predictions/<proposal-run-id>.json
data/intake/evidence-packages/<package-id>/manifest.json
data/intake/evidence-packages/<package-id>/evidence-manifest.json
data/intake/evidence-packages/<package-id>/package-record.json
data/intake/evidence-packages/<package-id>/initial-task-enrollment.json
data/intake/evidence-packages/<package-id>/lineage.json
data/intake/evidence-packages/<package-id>/frames/<part-name>.jpg
data/intake/evidence-packages/<package-id>/video/<part-name>.mp4
data/incoming/videos/<upload-id>/manifest.json
data/incoming/videos/<upload-id>/<original-filename>
```

The repository intake is the source authority. The backend rebuilds searchable package state from
accepted evidence-package bundles at startup. A pending upload is not a recording or an evidence
package. It stays outside intake until an operator supplies valid metadata and both task
enrollments with the operations command:

```bash
cd ..
mise exec -- uv run --project operations doko data status --repository-root .
mise exec -- uv run --project operations doko data complete-video \
  --repository-root . --upload-id <upload-id> --metadata completion.json
```

For a package written by an older backend, use the one-time adoption command. It validates the old
bytes, writes the canonical package, and keeps the old runtime directory until verification:

```bash
mise exec -- uv run --project operations doko data adopt-evidence \
  --repository-root . --runtime-root backend/.runtime \
  --package-id <package-id> --metadata package-metadata.json
```

Deleting `.runtime/` removes only disposable backend state. It does not remove accepted source
bundles. There is no delete API for recordings or evidence packages. To remove local test data,
stop the service and remove the complete test intake bundle together with its SQLite row:

```bash
cd backend
rm -rf ../data/intake/recordings/<recording-id>
sqlite3 .runtime/dokodetector.db \
  "DELETE FROM repository_bundles WHERE recording_id = '<recording-id>';"
```

Readiness runs a SQLite query and checks that the runtime table-observation directory, both intake
roots, and the pending-upload root can be read and written. The PoC uses one API process with local
SQLite and filesystem state. It does not provide multi-process locking or distributed coordination.
