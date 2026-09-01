# Web recording data workspace

## Plan status

- **Summary:** Make the recording the primary web resource and support complete CardEventNet event
  review plus bounded development-partition assignment.
- **Status:** In Progress
- **Depends on:** Completed plans 0020, 0027, 0032, and 0033
- **Related:** Plan 0038 owns the current visible-card geometry contracts. Plan 0026 owns later
  reconstruction correction.
- **Outcome:** After an iOS recording reaches repository intake, an operator can find it, open it
  without an analysis, complete its CardEvent annotation, and assign its eligible leakage group to
  the active train or validation partition from the web app.
- **Reviewed:** 2026-09-01 against the recording catalog, repository-bundle storage, round-analysis
  timeline, CardEvent annotation V2 contract and CLI, shared data operations, and active visible-card
  work.

## Milestone status

- **M0:** Complete — make recording detail the stable web route and nest optional analyses in it.
- **M1:** Complete — add a source-linked, conflict-safe CardEvent annotation workspace API.
- **M2:** Complete — add the video and timeline event editor with conflict feedback.
- **M3:** Complete — complete and revise a full-recording review with immutable receipt metadata and
  clear eligibility feedback.
- **M4:** Pending — assign eligible development leakage groups to train, validation, or unassigned.

## 1. Purpose

Turn the existing diagnostic frontend into the smallest useful local data workspace for the current
development phase. The recording is the stable resource. A round analysis is one optional derived
artifact of that recording. Annotation and development-partition state are other independent parts
of the same page.

The intended first-run path is:

```text
record with the iOS app
  -> wait for accepted repository intake
  -> open the web app and select the recording
  -> review all CardEvent events in the video
  -> mark the full-recording review complete
  -> assign the eligible source group to train, validation, or unassigned
  -> optionally start or inspect a round analysis
```

The page must explain unavailable actions in plain language. The operator must not need to know a
CLI command, artifact directory, schema name, or identifier to find the next useful action.

## 2. Scope

This epic includes:

- a recording detail page that works with zero, one, or several analyses;
- source video playback plus recording, intake, task-enrollment, and workflow status;
- CardEvent event add, select, change, retime, and remove actions;
- all current event types, confidence values, and notes from the annotation V2 contract;
- distinct device or model proposals that require an accept or dismiss decision;
- autosaved draft work, full-recording review completion, and later explicit revision;
- one active CardEventNet development split with train, validation, and unassigned partitions; and
- leakage-group-safe partition changes with an immutable receipt.

This epic does not include:

- visible-region, derived-box, or identity-usability editing from plan 0038;
- visual card identity classification labels;
- table-observation or reconstruction correction;
- test or system-holdout assignment;
- dataset balancing, coverage optimization, bulk import, search, tagging, deletion, or retention;
- training, evaluation, model promotion, or cloud-job controls;
- accounts, permissions, simultaneous multi-user editing, or remote deployment; or
- a general schema-driven annotation framework.

Add a later annotation section only after its contract and real review workflow are stable. Do not
make M0 through M4 generic in anticipation of those additions.

## 3. Fixed decisions

1. Use `/recordings/{recording_id}` as the stable detail route. Every recording row and card opens
   this route, even when `analyses` is empty or analysis cannot start.
2. Show an analysis inside the recording page. Select it with an `analysis` query parameter. Remove
   the analysis-only frontend route when M0 moves its timeline into the recording page. No deployed
   compatibility requirement exists.
3. Keep the accepted repository bundle and source video immutable. Store draft annotation state
   below a configured operations workspace root, outside the intake bundle.
4. Keep `cardevent-annotation/v2` as the event annotation contract. The web path and the CLI must
   use the same validation rules for event types, confidence, notes, ordering, video duration, and
   duplicate timestamps. Do not create a web-only annotation format.
5. Keep workflow metadata beside, not inside, the annotation. It records source asset and source
   digest, draft revision, proposal decisions, reviewer, review state, and the completed review
   receipt.
6. Save after each event or proposal action with an expected revision or digest. Use atomic file
   replacement. Return a conflict when another browser revision won. Never use last-write-wins.
7. A model or device proposal is not ground truth. Render proposals differently from saved events.
   Accepting a proposal creates or updates a human annotation. Dismissing it records only a review
   decision.
8. Require an explicit **Complete full recording review** action. Completion requires a pass over
   the full video and a decision for each shown proposal. It writes a new immutable reviewed
   annotation version and lifecycle receipt. Editing a completed review starts an explicit new
   draft from that version; it does not replace reviewed bytes.
9. Use the source frame rate for one-frame nudge controls. Persist event time in seconds under the
   existing contract. Show millisecond time and the derived frame number to make timing changes
   understandable.
10. Manage only one configured active CardEventNet development split in M4. Partition assignment
    applies to the complete leakage group, not only the open recording. Show every affected source
    before confirmation.
11. Permit only `train`, `validation`, and `unassigned` changes. Keep `test` and the system holdout
    read-only and unavailable as destinations. Do not rebalance other groups as a side effect.
12. A partition change creates a new versioned split and receipt after group-isolation and source
    permission validation. Never edit a frozen split in place.
13. Keep the current React, TypeScript, Vite, generated OpenAPI types, plain CSS, and browser-test
    stack. Do not add a router, state library, component library, waveform library, or canvas
    annotation framework for this epic.

## 4. Recording detail experience

The recording catalog remains the landing page. Make the complete card or row open the recording.
Keep a visible **Open recording** action. The list summarizes:

- intake time and source state;
- session and round when known;
- CardEvent review state and event count;
- development partition or `Unassigned`;
- latest analysis state; and
- the next blocked or available action.

The detail page uses a small task-oriented layout:

1. **Recording** — playable source video and trusted source metadata.
2. **Card events** — draft or reviewed annotation state and the event editor.
3. **Training use** — task enrollment, eligibility, and development partition.
4. **Round analyses** — start an analysis, inspect status, and open one completed timeline.

At the top, show a compact progress list with direct actions. Example states are `Ready to review
card events`, `Draft saved`, `Full recording review required`, `Eligible and unassigned`, and
`Assigned to validation`. Do not describe these as universal sequential stages: analysis can run
before annotation, and a recording can remain unassigned deliberately.

Show source identifiers in a disclosure for diagnosis. Lead with session, capture date, duration,
task status, and human-readable blockers. An empty analysis list must look normal, not like a load
failure.

## 5. CardEvent editor

Place a native video player above a time-ordered event list. Add a compact timeline rail with saved
event markers, proposal markers, the current playhead, and the visible time range. A full waveform
or thumbnail strip is not required.

Support these actions:

- play and pause;
- seek by approximately 250 ms and 2 s;
- jump to the previous or next saved event or proposal;
- add an event at the playhead;
- select an event from the rail or list;
- move the selected event by one frame or to the current playhead;
- change its event type, confidence, and notes;
- delete it with confirmation or immediate undo;
- accept a proposal as a human event; and
- dismiss a proposal without creating an event.

Use all event types and meanings from the current labeling guide. Default a new manual event to
`card_played` and `confirmed`. Keep keyboard shortcuts for frequent actions, but put visible labels
and a shortcut help disclosure in the page so keyboard knowledge is optional.

Save every successful action immediately and show `Saving`, `Saved`, or `Conflict`. Keep the local
draft when a request fails and offer retry. On a conflict, reload the winning revision and show the
operator which unsaved local action was not applied.

The editor must make the event-time rule visible near the controls: use the first frame where the
card has substantially reached its final position in the trick area. Link to or disclose the short
definitions for the less frequent event types. Show a warning for events less than 100 ms apart and
reject only effective duplicates under the current contract.

## 6. Annotation and review API

Add recording-scoped endpoints with generated frontend types:

```text
GET  /v1/recordings/{recording_id}
GET  /v1/recordings/{recording_id}/card-event-review
PUT  /v1/recordings/{recording_id}/card-event-review/draft
POST /v1/recordings/{recording_id}/card-event-review/complete
POST /v1/recordings/{recording_id}/card-event-review/revisions
```

The detail response joins indexed recording metadata, media facts, task enrollment, review status,
development partition, and analysis summaries. It is a projection, not a new source artifact.

The review response contains the current canonical annotation, source identity and digest, draft
revision, review state, reviewer when complete, and proposal records with stable IDs and decisions.
The draft update accepts the complete next annotation and proposal-decision state plus the expected
revision. The backend validates recording ownership, source digest, duration, event contract, and
proposal references before an atomic save.

Completion records the reviewer, input draft digest, source digest, reviewed annotation digest,
proposal-decision digest, and completion time. An incomplete proposal list or missing full-video
acknowledgement returns a validation error. A new revision copies a named completed version into a
new draft and records the parent digest.

Put the reusable state transitions and storage rules in `doko-operations`. FastAPI owns HTTP and
media delivery. The React app owns only transient interaction state. Do not shell out to
`cardevent annotate` or use subprocess output as workflow state.

## 7. Development partition assignment

M4 adds a small **Training use** panel. It shows:

- CardEvent task enrollment and source permission;
- annotation review and eligibility state;
- the active split version and current partition;
- the leakage group keys that control assignment; and
- other recordings or sources that the requested change affects.

Add a preview-then-apply API:

```text
POST /v1/data/cardevent-development-split/preview
POST /v1/data/cardevent-development-split/apply
```

The preview accepts one recording ID, one destination (`train`, `validation`, or `unassigned`), and
the expected active split digest. It returns the complete affected group, validation results, and
the proposed new counts. The apply request includes the preview digest. It repeats validation and
writes a new split version plus lifecycle receipt atomically.

Reject assignment when the CardEvent task is not selected, source permission does not allow the
use, full-recording review is incomplete, the source is not eligible, group facts are missing, the
active split changed, or the group touches test or the system holdout. Explain the blocker in the
panel. Do not offer a force action.

## 8. Delivery milestones

### M0 — Make recording detail the primary page

- Add a strict recording-detail projection and endpoint.
- Add `/recordings/{recording_id}` to the production frontend fallback.
- Make every catalog entry open, including recordings with no analysis or analysis blocker.
- Move analysis status and the completed timeline into the recording page.
- Add the four recording sections and top-level next-action summary with stable empty states.

Acceptance:

- a fixture recording with no analysis opens and plays its source video;
- a recording with a failed or blocked analysis still opens;
- one recording can select each of several analyses without leaving the recording route;
- a direct browser load of the recording route works in the packaged backend; and
- component and browser tests cover empty, active, complete, and failed analysis states.

### M1 — Add the CardEvent annotation workspace API

- Add the configured operations workspace root and source-linked draft storage.
- Add read, conflict-safe draft update, completion, and revision domain functions.
- Serve current proposals with stable IDs and separate human decisions.
- Add the recording-scoped review endpoints and regenerate OpenAPI types.
- Keep source and accepted bundle bytes unchanged in all success and failure tests.

Acceptance:

- a new recording starts with an empty annotation and its bundled proposals;
- valid add, update, retime, delete, accept, and dismiss transitions survive restart;
- invalid event values, source mismatches, foreign proposal IDs, and stale revisions fail without a
  partial write;
- two stale browser updates cannot silently overwrite each other; and
- contract fixtures remain readable by the existing CardEvent annotation loader.

### M2 — Build the event editor

- Add the player, timeline rail, ordered event list, proposal markers, and selected-event form.
- Add all pointer and keyboard actions in section 5.
- Autosave each action and implement retry, conflict, and validation feedback.
- Add concise in-page timing and event-type guidance.

Acceptance:

- a browser test creates, retimes, changes, adds notes to, and removes events on one fixture video;
- accepting and dismissing proposals have distinct persisted outcomes;
- one-frame nudges use the source frame rate and retain sorted valid events;
- all frequent actions are available without keyboard shortcuts; and
- the editor is usable at `1440 x 900` and `390 x 844` CSS pixels without page-level horizontal
  scrolling.

### M3 — Complete and revise full-recording review

- Add full-video progress and explicit completion controls.
- Require every proposal decision and the full-video acknowledgement.
- Publish an immutable reviewed annotation version and lifecycle receipt.
- Make the page show reviewed version, reviewer, time, digest, and resulting eligibility blocker.
- Add **Start revision** for a later correction without modifying the completed version.

Acceptance:

- proposal-only review cannot complete without the full-video acknowledgement;
- incomplete proposal decisions name the remaining work;
- completion is idempotent for the same draft and conflicts for different content;
- a revision retains parent lineage and leaves the completed bytes unchanged; and
- the normal iOS fixture path ends with an understandable reviewed or blocked status in the web
  page.

### M4 — Add bounded development-partition assignment

- Configure and show one active CardEventNet development split.
- Add group-safe preview and apply operations with immutable version and receipt output.
- Add the Training use panel and affected-group confirmation.
- Keep test and system-holdout records read-only.

Acceptance:

- an eligible unassigned fixture group can move to train and then back to unassigned through new
  split versions;
- a group move includes every connected session, game, table-setup, and source-lineage member;
- stale split digests, incomplete review, disallowed use, missing group data, and holdout contact
  block the change;
- no unrelated group changes partition; and
- `doko data validate` accepts the resulting published artifacts and receipts.

## 9. Verification

For each milestone, run the focused operations, backend, frontend component, generated-API, and
browser checks that cover the changed path. M1 and M3 need restart and write-failure tests. M4 needs
fixture-based lifecycle validation and before/after assertions for every immutable source and prior
split artifact.

Before closing the epic, run one local path with an iOS-style recording bundle:

1. accept the bundle through the normal backend intake;
2. find and open the recording in the web app before any analysis exists;
3. complete a mixed manual and proposal-seeded CardEvent review;
4. assign its eligible group to a development partition; and
5. start and open an optional analysis from the same page.

Record usability gaps. Fix only gaps that block this path or hide the next action. Put broader data
management ideas into a later measured epic.
