# iOS recording workspace simplification

## Plan status

- **Summary:** Replace the separate Live and Record flows with one profile-based recording
  workspace.
- **Status:** Closed
- **Depends on:** 0032 (complete)
- **Closure reason:** Complete
- **Priority:** High
- **Boundary:** This epic changes the iOS recording UI, its local recording-profile contract, and
  the adapters that create existing recording and analysis inputs. It keeps the evidence-package,
  upload, repository-intake, and round-analysis HTTP contracts. It does not integrate the future
  seating and dealer app.

## Milestone status

- **M0:** Complete — freeze the recording profile, purpose mapping, operator settings, app-run
  context, fixed metadata, and default round-analysis setup contracts.
- **M1:** Complete — replace profile storage and snapshots.
- **M2:** Complete — create one recording-workspace lifecycle.
- **M3:** Complete — build the focused operator surface.
- **M4:** Complete — connect default analysis and verify the complete flow.

## 1. Outcome

The app has one normal recording workspace. An operator selects a saved recording profile, checks
the camera frame and event count, and uses one prominent Start or Stop control.

The workspace has this priority order:

1. Start or Stop recording.
2. Live camera frame.
3. Event count for a quick detection smoke test.
4. Upload and analysis status.
5. Recording profile and operational details.

There is no normal **Live** tab, separate capture control, or choice between capture, training
recording, and round recording. The camera preview and live event detection are workspace services,
not operator modes. One recording can contain a round or staged activity. The selected recording
profile declares its purpose.

## 2. User flow and layout

The normal tab opens directly to the recording workspace. It has no large `Record` or `Live`
navigation heading.

```text
Profile: Kitchen overhead                         Change

                 live camera frame

                  12 events detected

                [ Start recording ]

Upload and analysis: Complete — 12 packages analyzed
More details: profile, camera/model/backend diagnostics, retry
```

- Start the camera preview and live event detection while the workspace is visible. Start a new
  preview count at zero when this preview session starts. Do not reset it when recording starts or
  stops.
- Use the same decoded event stream for the visible count and for evidence-package creation during
  an active recording. Preview events outside a recording increment the count but do not become
  members of a recording.
- Use one full-width primary control. It reads `Start recording` when idle and `Stop recording`
  while recording. The active state shows an unambiguous recording indicator and elapsed time.
- Keep Start unavailable until a valid profile is selected, the operator identity is configured,
  the camera and model are ready, the backend is connected, and the existing disk-space and queue
  gates permit a recording. Show the blocking reason near the control.
- Stop closes the evidence membership boundary once, finalizes the complete-video recording, and
  starts the existing upload and analysis lifecycle. Repeated Stop requests have no additional
  effect.
- Show a compact status line or card below the control. It covers finalization, upload progress,
  queued or active analysis, completion, and actionable failure. Put queue counts, byte details,
  analysis results, and retry controls behind `More details`, except when detail is needed to
  explain or recover from a failure.
- Put profile selection in the compact top row. Put profile editing and operational diagnostics in
  secondary sheets or disclosure sections. Do not allow profile selection or editing while a
  recording is active.
- Keep the debug-only Replay tab separate. Disable entry to replay while a recording is active.

## 3. Recording profile contract

Rename the operator-facing collection profile to **Recording profile**. Replace
`collection-profile/v1` with `recording-profile/v1`. A recording profile stores only these
operator-selected values:

- name;
- recording purpose;
- tags; and
- one task-enrollment setting for each repository data task.

Task-enrollment settings contain the existing disposition and the required reason for an excluded
task. Starting a recording snapshots the selected profile and creates the enrollment records. The
workspace has no per-recording tag, note, or task-enrollment overrides.

Use these stable purpose values and labels:

| Machine value | UI label | Existing source `content_type` | Source game ID |
| --- | --- | --- | --- |
| `weird_test_stuff` | Weird test stuff | `staged_scenario` | None |
| `approximate_forty_card_setup` | Roughly forty cards in a roughly real-world camera setup | `staged_scenario` | None |
| `plausible_staged_round` | Plausible round, but not real | `staged_scenario` | None |
| `real_game` | Real game | `real_game` | Temporary app-run game ID |

Add the purpose machine value to the existing scenario tags at the metadata adapter boundary. Do
not add a field to an upload or intake schema.

Every editable value has a persistent visible text label. Do not use placeholder text as the only
label. Use grouped form sections and short helper text only where it adds meaning.

### Operator identity

Task-enrollment records still require the person who made the decision. Store one required
**Operator name** in app settings, outside the recording profile. Ask for it only when it is absent
or when the operator opens settings. Do not put it in the primary workspace. Start is unavailable
while it is blank. Snapshot it into collection metadata and task-enrollment records at Start.

### App-run identity and fixed metadata

Create one lowercase UUID session ID when `AppState` is created. Keep it only in memory for new
recordings. Every recording started during that app run snapshots the same session ID. A recovered
recording keeps the session ID in its durable state; a relaunch does not rewrite it. Do not expose
session ID as a profile field, recording-form field, or validation error.

Use a small metadata adapter to provide fields that the existing upload and repository-intake
contracts still require:

| Existing field | Adapter value |
| --- | --- |
| `operator` | Saved Operator name snapshot |
| `session_id` | App-run session UUID |
| `table_setup` | `default_table_setup` |
| `card_deck` | `french_common_back_v1` |
| `camera_view` | `overhead` |
| `camera_motion` | `fixed` |
| `camera_framing` | `table_with_context` |
| `lighting` | `not_recorded` |
| `background` | `not_recorded` |
| `source_permission` | `project_use` |
| `known_limitations` | Empty |
| `notes` | None |

These values describe the current single recording setup. Change this adapter, not the recording
profile contract, when the hardware setup changes. This epic intentionally replaces the earlier
operator-entered session and setup metadata with one app-run grouping and fixed setup metadata.
Later data work can replace this temporary grouping with an explicit session source.

Remove these concepts from the normal profile and recording UI:

- `Live` as a tab or capture state exposed to the operator;
- operator, session ID, and game ID entry;
- table setup, deck design, camera angle, movement, framing, lighting, background, limitation,
  permission, and notes input;
- per-recording tags and task-enrollment overrides; and
- round-setup controls for dealer and first trick leader.

The profile JSON change is a breaking local format. Do not add a migration or compatibility
decoder. Decode each saved profile independently. Load all valid `recording-profile/v1` files,
ignore obsolete files, and report one clear non-blocking message that obsolete profiles must be
recreated. One obsolete or corrupt file must not hide valid profiles.

## 4. Recording and analysis behavior

One Start operation allocates the existing recording identity and starts the complete-video
recorder, inference, and evidence-package capture as one transaction. It snapshots the app-run
session ID, operator name, selected profile, fixed metadata, and task enrollments. If setup fails,
release every resource allocated by that Start and return to an idle, retryable state.

One Stop operation closes evidence membership before finalization. Keep the existing durable
queues, acknowledgement gates, retry behavior, relaunch recovery, and analysis polling. These are
workflow states, not separate recording modes.

The round-analysis service still requires a game ID and round setup. Isolate these temporary values
in a `DefaultRoundAnalysisSetup` adapter:

- seats are `seat-1` through `seat-4`;
- dealer and first trick leader are `seat-1`;
- round ID continues to derive from the recording ID;
- a real-game recording uses `game-<app-run-session-uuid>` in both collection metadata and the
  analysis request; and
- a staged recording keeps source `game_id` empty but uses `analysis-game-<app-run-session-uuid>`
  only in the analysis request.

Do not display or edit these temporary values. Keep them outside `RecordingProfile` so the future
seating integration can replace the adapter without another profile-format change.

## 5. Current implementation map

The implementation starts at these existing boundaries:

- `RootView` owns the separate Live and Record tabs.
- `LiveDetectionView` and `RecordView` each own a `CameraSession` and duplicate preview lifecycle
  work.
- `RecordView` exposes profile, task, capture, round-setup, recording, upload, analysis, and
  diagnostic controls in one scroll view.
- `CollectionProfile`, `CollectionProfileStore`, and `RecordTabState` own the old local profile and
  tab contracts.
- `AppState.startLiveInference`, `startTrainingRecording`, and `stopTrainingRecording` already own
  most inference, evidence, complete-video, upload, recovery, and analysis behavior.

Preserve those proven services. Replace their operator-facing mode split with one workspace state
and narrow adapters.

## 6. Delivery milestones

### M0 — Freeze the new local contracts

- Add `RecordingPurpose`, `RecordingProfile`, operator settings, app-run context, fixed metadata,
  and default round-analysis setup contracts.
- Define the purpose-to-source mapping and the different real-game and staged analysis game IDs.
- Replace profile validation with validation for name, purpose, tags, and complete task settings.
- Add focused model and adapter tests before replacing existing UI call sites.

#### M0 implementation evidence — 2026-08-31

- Added the strict `recording-profile/v1` model with the four stable purposes, profile tags, and
  one validated task setting for each repository data task.
- Added in-memory operator settings and app-run context contracts. The app-run context exposes one
  lower-case UUID string for purpose-derived game IDs.
- Added purpose mapping, fixed intake metadata, purpose tagging, operator enrollment snapshots,
  and the default round-analysis setup. Staged recordings keep source `game_id` empty and use an
  `analysis-game-<app-run-session-uuid>` analysis ID; real recordings use `game-<app-run-session-uuid>`
  for both.
- Added six focused model and adapter tests. The focused suite passes. The simulator app build
  succeeds. The full Swift package suite runs 102 tests with 98 passing; four existing evidence
  manifest/video timing tests fail outside this milestone.

### M1 — Replace profile storage and snapshots

- Replace `CollectionProfileStore` with per-file `recording-profile/v1` loading and saving.
- Reject the obsolete format without migration. Continue loading other valid profiles and expose a
  non-blocking obsolete-file notice.
- Snapshot operator identity, app-run identity, profile values, fixed metadata, and task
  enrollments at Start. Remove recording-level overrides.
- Update storage, validation, metadata, enrollment, and relaunch-recovery tests.

#### M1 implementation evidence — 2026-08-31

- Replaced `CollectionProfileStore` with per-file `RecordingProfileStore` for strict
  `recording-profile/v1` files. The store ignores corrupt files, rejects obsolete
  `collection-profile/v1` files without migration, scans the previous profile directory for an
  obsolete-file notice, and keeps other valid profiles available.
- Moved operator identity to a separate `OperatorSettingsStore`. The app loads one app-run UUID in
  memory and uses the selected recording profile plus operator settings at Start.
- Added a durable `RecordingStartSnapshot` and store. The snapshot keeps the profile, operator
  identity, app-run identity, fixed metadata, derived collection metadata, and task enrollments
  together until complete-video finalization. Stop uses this snapshot and does not accept
  recording-level tags, notes, task overrides, dealer input, or first-trick-leader input.
- Updated the app start path, recording UI call sites, local pipeline fixture, and tests. The
  focused profile, storage, snapshot, round, and coordinator tests pass. The iOS Simulator build
  succeeds. The full Swift package suite runs 103 tests with 99 passing; four existing evidence
  manifest/video timing tests fail outside this milestone.

### M2 — Create one recording-workspace lifecycle

- Give one camera session and one preview/inference lifecycle to the recording workspace.
- Replace the operator-facing capture and round-recording distinctions with preview, starting,
  recording, stopping, and post-recording workflow states.
- Make Start and Stop own the existing recording, inference, evidence, and finalization services as
  one idempotent lifecycle.
- Add regression tests for Start gates, partial-start cleanup, one-time Stop finalization, event
  count behavior, profile locking, and appearance transitions.

#### M2 implementation evidence — 2026-08-31

- Added the `RecordingWorkspaceState` lifecycle with starting, preview, recording, stopping,
  post-recording, and failure states. Start and Stop transitions are idempotent and support retry
  and relaunch recovery.
- Moved the camera session and preview inference coordinator into `AppState`. The root workspace
  owns their appearance lifecycle, while Live and Record views use the shared preview and event
  stream. Preview event counts are not reset when recording starts or stops.
- Routed recording start, evidence membership closure, complete-video finalization, durable upload,
  and analysis handoff through the workspace lifecycle. Profile editing stays locked during
  recording and finalization, and replay is blocked during recording.
- Added five focused lifecycle tests. The focused suite passes. The iOS Simulator app build
  succeeds. The full Swift package suite runs 108 tests with 104 passing; four existing evidence
  manifest/video timing tests fail outside this milestone.

### M3 — Build the focused operator surface

- Replace the normal Live and Record tabs with the recording workspace. Keep Replay debug-only.
- Add the compact profile row, camera frame, event-count smoke test, primary Start or Stop control,
  elapsed time, and concise lifecycle status in the specified order.
- Move recording-profile editing, operator settings, diagnostics, queue details, retry controls,
  and result details to secondary presentation.
- Add SwiftUI state and accessibility tests for information order, persistent labels, Start
  blockers, locked controls, status states, and failure recovery.

#### M3 implementation evidence — 2026-08-31

- Replaced the normal Live and Record tabs with one recording workspace. Replay remains available
  only in debug builds.
- Put the selected recording profile, live camera frame, event count, full-width Start or Stop
  control, recording elapsed time, and concise upload or analysis status on the workspace.
- Moved profile editing, operator settings, queue retry controls, analysis details, and diagnostics
  into sheets or the More details view. The profile and settings forms use visible labels for every
  editable value.
- Added four presentation tests for information order, accessibility labels, Start blockers,
  locked controls, elapsed recording state, upload and analysis states, and failures. The focused
  suite passes. The iOS Simulator build succeeds. The full Swift package suite runs 110 tests with
  106 passing; four existing evidence manifest and video timing tests fail outside this milestone.

### M4 — Connect default analysis and verify the complete flow

- Remove dealer, first-trick-leader, and game-ID input from the recording-start API.
- Generate collection and analysis inputs through the fixed metadata and
  `DefaultRoundAnalysisSetup` adapters.
- Verify profile snapshots, upload acknowledgement gating, automatic analysis submission, retry,
  relaunch recovery, and staged and real-game fixtures under the unified flow.
- Run the focused iOS tests, the complete iOS test suite, and an iOS Simulator build.

#### M4 implementation evidence — 2026-08-31

- Removed the public raw game ID, dealer, and first-trick-leader inputs from round setup. The
  default analysis adapter now provides the fixed values.
- Added unified staged and real-game flow coverage. The tests verify recording snapshots, fixed
  collection metadata, adapter-created analysis setup, acknowledgement gating, and automatic
  analysis-request creation. Existing queue and submission tests cover retry and relaunch
  recovery.
- The focused suite passes. The iOS Simulator build succeeds. The full Swift package suite runs
  111 tests with 107 passing; four existing evidence manifest and video timing tests fail outside
  this epic.

## 7. Acceptance criteria

- A normal operator records with a saved profile through only the workspace Start and Stop control.
- The first screen shows the Start or Stop control, camera framing, event count, and upload or
  analysis status without configuration fields.
- No normal UI distinguishes Live, capture, training recording, or round recording.
- A recording profile contains only name, one of the four stable purposes, tags, and task settings.
- Every editable profile or operator setting has a persistent visible label.
- A new app run creates one in-memory session UUID. New recordings in that run use it, while
  recovered recordings retain their stored UUID.
- Existing intake metadata remains valid through the explicit fixed-metadata adapter. Staged source
  records have no game ID. Real-game source records use the temporary app-run game ID.
- The UI contains no session, game, dealer, seat, or first-trick-leader input.
- The event count and recording evidence packages use one decoded event stream.
- Stopping a recording retains the existing durable upload, retry, acknowledgement, analysis, and
  relaunch behavior.
- Obsolete or corrupt profile files do not prevent valid new profiles from loading.
- The normal workspace has no `Record` or `Live` page header.

## 8. Non-goals

- Integrating the external app that provides session, game, dealer, or seating data.
- Changing backend HTTP contracts, repository-intake schemas, reconstruction rules, model
  detection behavior, or the evidence-package format.
- Migrating obsolete profile files.
- Building recording history, profile sync, or background uploads.
- Supporting several table, deck, camera, or permission configurations in the same app build.
