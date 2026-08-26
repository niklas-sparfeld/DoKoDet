# DokoDetector iOS Evidence Upload — Production Readiness

## Plan status

- **Summary:** Make evidence capture and upload reliable in field use
- **Status:** Closed
- **Closure reason:** Superseded by [plan 0024](../0-to-specify/0024-System_Production_Readiness.md)
- **Depends on:** Plan 0016 and measured field requirements
- **Disposition:** Keep this document as an iOS hardening reference. Do not implement it as a
  fixed queue. The future system plan will select the required items from measured needs.

## 1. Outcome

Harden the proven local pipeline for long capture sessions, app lifecycle changes, poor networks,
and supported iPhone classes.

This plan does not add card recognition or game rules. It does not move player attribution into
the iOS app.

## 2. Production gates

### M0 — Background transfer and recovery

Use a stable background `URLSessionConfiguration` identifier and file-backed upload tasks.

Implement:

- mapping between package IDs and URLSession task IDs;
- app relaunch reconciliation;
- background-session completion handling;
- prevention of duplicate active tasks;
- cleanup of stale multipart body files after reconciliation;
- preservation of every unacknowledged evidence package.

Test task restoration through protocol and state-machine tests. Use a physical iPhone only for the
final background-transfer checks that the simulator cannot represent.

### M1 — Durable retry policy

Persist retry count, last error category, and next eligible attempt.

Use capped exponential backoff with jitter for transport errors, `408`, `429`, and `5xx`. Respect
`Retry-After` when valid. Do not spin while offline. Limit concurrent uploads to one at first.

Keep permanent conflicts and other permanent failures for inspection. Authentication behavior is
out of scope until the backend defines it.

Acceptance:

- an ambiguous network failure cannot lose or duplicate logical evidence;
- retry state survives relaunch;
- a bad package cannot block later packages forever.

### M2 — Storage limits and retention

Measure queued bytes and free device space.

Add:

- a warning threshold;
- a hard capture guard before the app exhausts storage;
- deletion of acknowledged image payloads after a retained receipt is durable;
- user-visible failed/corrupt package handling;
- bounded diagnostics and temporary multipart storage.

Never delete the oldest unacknowledged package only to make the warning disappear.

Test limits with small injected values and temporary directories.

### M3 — App and camera lifecycle

Define behavior for:

- camera permission denial;
- app background and foreground transitions;
- camera interruption;
- media-services reset;
- session resume or explicit end after process termination;
- inference timestamp discontinuity;
- thermal pressure and encoder overload.

Reset the temporal model and event decoder after a capture discontinuity. Keep already queued
uploads independent from camera availability.

### M4 — Production capture UI and diagnostics

Provide a focused UI for:

- capture state;
- recoverable and fatal capture errors;
- queue and upload state;
- storage pressure;
- explicit session end;
- export of a bounded diagnostic report.

Diagnostics must answer, for each event sequence:

```text
Was an event emitted?
Was a package finalized?
Was evidence complete?
Was the package persisted?
Was upload attempted?
Did the server acknowledge it?
```

Do not add player names, seat selection, turn controls, or game-engine state.

### M5 — Privacy and transport baseline

- Store evidence only in the app container.
- Use normal iOS file protection.
- Exclude queued evidence from device backup if product requirements permit and tests confirm it.
- Use HTTPS for non-local servers.
- Do not log frame data, multipart bodies, stable device identifiers, or sensitive filesystem paths.
- Document retention and user-visible deletion behavior before external trials.

Do not invent an authentication protocol. Add it only after the server contract defines it.

### M6 — Performance and device validation

Report results by iPhone model class and capture conditions. Report 0015 found a device-domain gap,
so one successful phone test is not a production accuracy claim.

Measure at least:

- inference latency and achieved inference rate;
- evidence JPEG encode latency and accepted sample rate;
- dropped inference and evidence samples;
- peak memory;
- thermal state;
- queued storage growth;
- upload throughput and retry behavior;
- event precision and recall on representative supported device classes.

Run:

1. A long game-like capture.
2. Loss and restoration of connectivity.
3. Process termination with queued and active uploads.
4. Backgrounding during upload.
5. Camera interruption.
6. Server throttling and temporary failure.
7. Low-storage behavior.
8. Incomplete-evidence capture.
9. At least one older-device performance trial.

Before external use, write a short support decision. It must name the validated device classes,
known limitations, and evidence for the selected operating point. Do not set an arbitrary metric
threshold in this plan.

## 3. Dependencies

Continue to use Apple frameworks and the project test tools. Add no third-party runtime library
unless a measured requirement cannot be met with the existing stack. Record that decision before
adding the dependency.

Keep the normal automated loop local with fixtures, protocol test doubles, the simulator, and the
local plan 0004 backend. Use physical devices for the final gates that require real camera,
background execution, thermal behavior, or device performance.

## 4. Definition of done

- background uploads and retry state recover after process termination;
- finalized packages are never silently lost;
- storage and temporary files remain bounded;
- camera interruptions cannot corrupt later inference;
- diagnostics expose the full event-to-acknowledgement path;
- privacy and transport behavior is documented and tested;
- long-run tests pass on each declared supported device class;
- the support decision records the remaining CardEventNet device-domain risk;
- no player/turn model, ROI configuration, or unnecessary third-party runtime dependency exists.
