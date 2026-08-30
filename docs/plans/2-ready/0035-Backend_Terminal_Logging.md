# Backend terminal logging

## Plan status

- **Summary:** Make the local backend emit concise, structured terminal logs for business events, warnings, failures, and opt-in technical business-process traces.
- **Status:** Ready
- **Depends on:** None.
- **Reviewed:** 2026-08-30 against the current backend entry point, FastAPI application factory, HTTP routes, round-analysis worker, and error handlers.

## Milestone status

- **M0:** Pending — define the logging contract and make server startup configure it reliably.
- **M1:** Pending — log the request and storage business lifecycle at `INFO` and rejections at `WARNING`.
- **M2:** Pending — log the round-analysis lifecycle at `INFO` and its technical trace at `DEBUG`.
- **M3:** Pending — document local log control and verify normal and debug runs end to end.

## 1. Outcome

An operator who starts the backend locally can see useful terminal output without extra setup.

The normal `INFO` output shows startup, service availability, accepted uploads, stored repository bundles and pending videos, created and completed round analyses, and failed work. It includes the stable identifiers that connect related events. It does not include request bytes, media content, Gemini credentials, authorization values, or full untrusted request payloads.

An operator can enable `DEBUG` with one documented environment setting before startup. Debug output then shows the technical path through a business process, such as validation, storage, queueing, worker state changes, analyzer execution, artifact publication, and database recovery. `DEBUG` is off by default.

Warnings identify expected but actionable degraded behavior, rejected requests, and recoverable operational conditions. Errors include an exception traceback only when a backend operation fails. The backend must not write business lifecycle events at `ERROR` merely because an HTTP client sent invalid input.

## 2. Fixed decisions

1. Use the Python standard-library `logging` package. Do not add a logging framework or an external log collector in this epic.
2. Configure logging once from the backend process entry point, before application construction. The configuration must take effect when the normal `dokodetector-backend` command starts Uvicorn. It must not replace logging handlers supplied by a test, embedding process, or Uvicorn.
3. Add `DOKO_LOG_LEVEL` as the backend log-level setting. Accept the standard case-insensitive levels `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`; default to `INFO`; reject other values with a clear startup error. Keep third-party library loggers at `WARNING` unless the operator explicitly configures them outside this contract.
4. Write one line per event to standard error. Use UTC ISO-8601 timestamps, level, logger name, event name, and stable `key=value` fields. Keep field names consistent across event types.
5. Use lower-case, underscore-separated event names. Include the applicable stable IDs, such as `request_id`, `upload_id`, `package_id`, `recording_id`, `analysis_id`, and `session_id`. Generate a request ID when the client does not supply one. Do not change any existing HTTP request or response contract in this epic.
6. Keep Uvicorn access logs enabled at `INFO`. Do not duplicate their method, path, and status output as a separate successful-request event. Domain routes log business transitions instead.
7. Do not log secrets, media bytes, multipart values, complete manifests, request bodies, raw model prompts or responses, SQL statements with values, file-system paths outside configured runtime roots, or unbounded exception text. Error logs must use the existing safe rejection policy for invalid input.
8. Preserve current `INFO`, `WARNING`, and exception events only when they meet this contract. Rename inconsistent messages to canonical event names in the same change. Do not retain duplicate legacy log lines for compatibility.

## 3. Logging levels and event contract

| Level | Use | Examples |
| --- | --- | --- |
| `DEBUG` | Technical trace for a business process; disabled by default | multipart validation completed, database rebuild count, worker queue transition, analyzer invocation, artifact digest published |
| `INFO` | Completed or started business event that an operator normally needs | backend started, upload accepted, repository bundle stored, pending video stored, round analysis created or complete |
| `WARNING` | Rejected input, retryable dependency problem, or degraded but recoverable behavior | request rejected, Bonjour unavailable or disabled, stale analysis marked failed during recovery |
| `ERROR` | Backend work failed and needs attention | round analysis failed, failure state could not be persisted |

Every route-owned business event must include `request_id`. Upload events also include `upload_id` when present. A lifecycle sequence must reuse the originating business ID rather than create a second identifier. For example, a round-analysis sequence uses the same `analysis_id` from creation through completion or failure.

At `INFO`, an event states what happened and its compact outcome. At `DEBUG`, related events state how it happened. Use counts, byte lengths, bounded durations, status names, and digests only where they help diagnosis and do not disclose protected content.

## 4. Milestones

### M0 — Logging configuration and contract

Create one backend logging module that owns level parsing, one-line formatting, request-ID helpers, and logger policy. Configure it from the server entry point before Uvicorn starts. Make the default process output visible at `INFO`, and make `DOKO_LOG_LEVEL=DEBUG` enable backend debug records.

Add focused tests for level parsing, default output, debug filtering, invalid configuration, and handler preservation. Update existing server-start tests as needed.

Completion condition: a minimal local server start emits a backend-started `INFO` event, while a debug event is absent at the default level and present at `DEBUG`.

### M1 — HTTP and intake lifecycle events

Apply the contract to evidence-package upload, repository-bundle intake, pending-video intake, readiness checks, and API error handlers. Log each accepted durable business object once at `INFO`. Log validation and contract rejection once at `WARNING`, using only safe metadata. Add `DEBUG` trace events around validation and durable publication where they help identify the completed stage.

Add tests that capture records for one successful intake and one rejected request. Assert event name, level, required IDs, and that a known secret-like header or body value is absent.

Completion condition: a terminal operator can follow one accepted or rejected intake without reading a request payload or inspecting the database.

### M2 — Round-analysis lifecycle and technical trace

Apply the contract to application startup recovery, queueing, worker start and stop, analysis state changes, analyzer execution, reconstruction, artifact publication, completion, and failure. Keep one concise `INFO` event for each user-meaningful state transition. Add `DEBUG` events for per-package progress and technical boundaries. Preserve exception tracebacks for unhandled worker failures.

Add lifecycle tests for a successful synchronous fixture analysis, an asynchronous queued analysis, and a failed analysis. Assert that normal-level records give the state sequence and debug-only records expose the per-package trace.

Completion condition: an operator can correlate a round-analysis request with its final state and failure reason from terminal output alone.

### M3 — Local operation guide and end-to-end verification

Update the backend README with the default level, `DOKO_LOG_LEVEL` examples, event-level rules, and a short safe troubleshooting example. Do not publish sample identifiers from real recordings or intake data.

Run the backend test suite, lint checks, and a reproducible local smoke run at `INFO` and `DEBUG`. Capture no runtime logs in git. Confirm that the normal log stream is concise and that debug output adds trace detail without changing API behavior.

Completion condition: a new local operator can enable debug tracing and distinguish normal business events from warnings and failures by reading the README.

## 5. Out of scope

- JSON log output, log files, rotation, shipping, metrics, tracing backends, dashboards, alerts, or cloud observability.
- Authentication, authorization, audit retention, and production deployment policy.
- Changing API schemas, upload payloads, database schemas, or artifact formats.
- Per-request timing targets or performance profiling beyond bounded durations useful in debug events.

## 6. Completion condition

This epic is complete when the normal local backend command reliably shows its business lifecycle at `INFO`, diagnostic business-process detail remains off until `DOKO_LOG_LEVEL=DEBUG` is selected, and tests prove the level routing, identifiers, safe fields, and round-analysis lifecycle output.
