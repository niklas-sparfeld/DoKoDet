# iOS training upload ergonomics

## Plan status

- **Summary:** Show useful preparation and upload progress after an operator stops a training
  recording
- **Status:** Closed
- **Depends on:** Completed plan 0019
- **Priority:** Nice to have
- **Boundary:** This epic changes app upload feedback. It does not change recording capture,
  repository-bundle identity, or backend intake.
- **Closure reason:** Complete
- **Closure note:** Implemented preparation and byte-accurate foreground upload progress in the iOS
  Record view, with queue, retry, and accessibility coverage.

## 1. Outcome

After an operator stops a training recording, the Record view shows which step is active:

```text
Finalizing recording -> Preparing upload -> Uploading 0-100% -> Acknowledged
```

During network transfer, the view shows a determinate progress bar, a percentage, and transferred
bytes. Existing durable queue, retry, failure, and acknowledgement behavior stays unchanged.

Do not upload the video while capture is active in this epic.

## 2. Decision: keep upload after recording

Continuous upload is possible, but it is not a small change to the current system. The app writes
one H.264 QuickTime file with `AVAssetWriter`. That file becomes complete only after the writer
finishes. The app then validates the complete repository bundle and creates its manifest, byte
lengths, and SHA-256 digests. The backend accepts all declared files in one multipart request and
publishes the bundle atomically only after validation.

Uploading during capture would need a different protocol and failure model. A robust design would
need segmented or fragmented media, server-side staging, chunk identity, resumable transfer,
recording finalization, final digest validation, and cleanup of abandoned uploads. It would also
need clear behavior when the app suspends, the network changes, or capture ends unexpectedly.

That cost is not justified for a nice-to-have improvement. Keep the complete local recording as
the retry source and start upload automatically after finalization, as the app does now. Create a
separate epic only if measurements show that post-recording latency or local storage blocks a real
collection workflow.

## 3. Scope

### 3.1 Add an upload progress value

Represent progress for the active training recording with:

- recording identifier;
- phase: `preparing` or `uploading`;
- bytes sent and expected bytes;
- a fraction from `0.0` through `1.0` during network transfer.

The multipart body builder already reports its file size. Use that size as the expected network
byte count. Treat multipart body creation as indeterminate `preparing` work because the current
builder copies the complete video into a temporary body file before the request starts.

Report progress from the `URLSessionUploadTask` byte callbacks. Do not estimate progress with a
timer. Deliver app-state updates on the main actor and limit UI update frequency if callbacks are
too frequent.

### 3.2 Show progress in the Record view

Replace the upload spinner with:

- an indeterminate indicator and `Preparing upload` while the multipart body is built;
- a determinate progress bar during transfer;
- `Uploading 42% · 84 MB of 200 MB` below the bar;
- the existing queue counts and final acknowledgement or failure state.

For a serial queue with several recordings, show progress for the active recording. Keep the
existing queued count visible. Reset the byte counters when the queue advances to another
recording. Accessibility text must state the phase and percentage without depending on color.

### 3.3 Preserve upload behavior

Progress reporting must not change:

- file-backed multipart upload or temporary-file cleanup;
- serial queue order;
- idempotent backend `PUT` behavior;
- retryable and permanent failure classification;
- the move from `queued` to `acknowledged` only after a valid backend response;
- recovery of complete queued recordings after app launch.

## 4. Work items

1. Add a sendable training-recording upload progress model and progress callback.
2. Adapt the upload client to expose real `URLSessionUploadTask` byte progress while retaining its
   async result and current response validation.
3. Forward preparation and transfer progress through the serial upload queue to `AppState`.
4. Add the determinate and indeterminate states to the Record view.
5. Add focused unit tests for progress order, byte values, queue transitions, retry, and reset.
6. Run the iOS test suite and verify one throttled local upload on the simulator.

## 5. Acceptance criteria

- Stopping a valid recording automatically reaches `Preparing upload` and then `Uploading` without
  another operator action.
- Network transfer displays monotonic progress from the task's sent and expected byte counts.
- The final displayed transfer reaches 100% before or when the backend acknowledgement arrives.
- A retry starts fresh progress for the same recording and preserves the durable bundle.
- A second queued recording does not inherit the first recording's byte counts.
- A preparation or upload failure still shows the existing actionable error and queue state.
- Existing recording finalization, upload acknowledgement, and launch-recovery tests continue to
  pass.

## 6. Non-goals

- Upload while capture is active.
- A chunked or resumable backend upload protocol.
- Background upload after the app is suspended or terminated.
- Changes to the repository-bundle contract or source-asset identity.
- Upload speed or remaining-time estimates.
