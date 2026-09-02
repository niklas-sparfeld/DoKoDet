# Card event review workflow improvements

## Plan status

- **Summary:** Make CardEvent review wide, fast, keyboard-efficient, and explicit about proposal
  lineage and review history.
- **Status:** Ready
- **Depends on:** Plan 0039 M0 through M4 complete
- **Builds on:** Plan 0039 recording, CardEvent annotation, review, and development-partition
  contracts
- **Related:** Plans 0040 and 0042 consume immutable completed CardEvent annotation versions.
- **Outcome:** An operator can start or continue a named CardEvent review from a recording, process
  one time-ordered event stream with a fast next-and-accept loop, publish it, and see every draft
  and completed review on the recording page.
- **Reviewed:** 2026-09-02 against the current React editor, generated API client, FastAPI review
  routes, `doko-operations` review store, and recording detail layout.

## Milestone status

- **M0:** Not started — make the layout video-first and repair frame and keyboard controls.
- **M1:** Not started — make each CardEvent review a recording-owned resource.
- **M2:** Not started — unify proposals and human events with stable lineage.
- **M3:** Not started — measure and remove local review-path latency.
- **M4:** Not started — add the recording review list and dedicated review page.
- **M5:** Not started — deliver the optimistic, unified, shortcut-driven review loop.

## 1. Purpose

The current CardEvent editor proves the complete review lifecycle, but it does not yet support a
fast annotation session. The recording page limits the editor to `72rem`. The editor shows saved
events and proposals in separate lists. Accepting a proposal creates a human event by timestamp
proximity, so a later time correction does not retain an explicit relation to the proposal. Every
action also disables controls while a full-draft request validates the complete immutable source
bundle and probes the video again.

Make a CardEvent review a first-class resource, similar to a round analysis. Keep the recording page
as the index and status surface. Put the editing session on its own stable route. Present event
proposals, reviewed events, and dismissed proposals as states in one time-ordered event collection.
Preserve model lineage without presenting model output as reviewed truth.

The intended interaction is:

```text
open recording
  -> see no reviews, drafts, and completed reviews
  -> add or continue one review
  -> Alt+Right selects the next event marker
  -> A accepts it, or D dismisses it
  -> comma/period correct its time by one frame when needed
  -> repeat without waiting for each local save
  -> complete the review
  -> return to a recording page that shows who reviewed it and when
```

## 2. Scope

This epic includes:

- a wider centered recording and review layout;
- a wide video-first workspace with secondary recording metadata in a dialog;
- reliable one-frame controls and keyboard shortcuts that work on a German keyboard;
- one recording-owned CardEvent review resource per annotation attempt or revision;
- a recording-level list of draft and completed CardEvent reviews;
- a dedicated CardEvent review page;
- one time-ordered event table for manual events and model or device proposals;
- durable proposal-to-reviewed-event lineage across acceptance and time correction;
- keyboard actions for previous, next, accept, dismiss, add, nudge, and remove;
- local performance measurements, backend source-context reuse, and responsive optimistic saves;
  and
- focused component, contract, performance, and browser regression coverage.

This epic does not include:

- changes to CardEvent event types or their timing definition;
- visible-card, identity, table-observation, or reconstruction review;
- model execution, proposal threshold selection, or model quality work;
- multi-recording bulk review, queue prioritization, accounts, or concurrent multi-user editing;
- train, validation, test, or system-holdout assignment changes; or
- a generic review framework for all annotation tasks.

## 3. Fixed decisions

1. Keep `Event`, `Event proposal`, and `Reviewed event` meanings from the project glossary. Model
   them in one review event collection with `proposed`, `reviewed`, or `dismissed` state. The common
   collection does not make an unreviewed model result ground truth.
2. Give every event in the review collection a stable `event_id`. A proposal-backed event also
   keeps its immutable proposal ID, generator run, source time, probability, model bundle, and
   execution platform. Its editable event time is separate from its immutable proposal time.
3. Accepting a proposal changes that same event from `proposed` to `reviewed`. It does not create an
   unrelated timestamp-matched event. Retiming, changing the type, changing confidence, or adding
   notes to a proposed event is a human correction and changes it to `reviewed` in the same saved
   command. A later nudge retains the proposal lineage.
4. Dismissing a proposal changes it to `dismissed`. Keep it in review history and show it as a dim
   row by default. Exclude it from the published CardEvent annotation. Permit an explicit undo
   before review completion.
5. A manual add creates a `reviewed` event with manual origin and no proposal lineage. Do not infer
   proposal linkage from timestamp distance.
6. Continue to publish `cardevent-annotation/v2` plus the immutable completed-review artifact and
   lifecycle receipt consumed by plans 0040 and 0042. The draft HTTP and workspace formats can
   change without a compatibility endpoint or migration because they are development-only.
7. One recording can have several review resources over time, but at most one draft review. The
   latest completed review is current. **Add review** creates an empty initial review when none
   exists. After completion, it creates a revision seeded from the latest completed version and
   records its parent. If a draft exists, the recording page offers **Continue review** instead.
8. Use `/card-event-reviews/{review_id}` as the stable editor route. A review ID, not the recording
   ID, owns draft revision, progress, reviewer, decisions, completion, and parent lineage.
9. Use these non-text-input shortcuts:
   - `Left` and `Right`: seek by 250 ms;
   - `Shift+Left` and `Shift+Right`: seek by 2 s;
   - `Alt+Left` and `Alt+Right`: select and seek to the previous or next event marker;
   - comma and period: nudge the selected event by minus or plus one source frame;
   - `A`: accept the selected proposed event;
   - `D`: dismiss the selected proposed event;
   - `N`: add a manual event at the playhead; and
   - `Delete` or `Backspace`: remove a selected manual or reviewed event with undo.
10. Keep every action available through a visible control. Show shortcut labels beside the frequent
    actions and keep a concise help disclosure.
11. A marker jump selects the row as well as moving the playhead. The normal proposal cycle is
    `Alt+Right`, then `A` or `D`.
12. Do not disable the complete editor while a save is in flight. Apply valid commands locally,
    send them through one ordered save queue, and show `Saving`, `Saved`, `Retrying`, or `Conflict`.
    Preserve unsaved commands across a transient failure.
13. Coalesce superseded time, type, confidence, and note edits for the same event. Preserve ordered
    add, accept, dismiss, undo, and remove commands. Never hide or reorder a conflict.
14. Cache only verified immutable source context. Key it by recording ID and accepted source digest.
    Invalidate it when the repository index or source digest changes. Do not hash the complete
    bundle or run the video probe for each draft command.
15. Target a local fixture p95 of at most 250 ms for a saved event command and at most 500 ms for
    initial review data after the recording metadata is available. Show local interaction feedback
    within one animation frame. Record measurements before and after the changes.
16. Let recording and CardEvent review content grow to a centered `96rem` maximum on wide screens.
    Keep readable text blocks narrower. Preserve the current narrow-screen behavior without
    page-level horizontal scrolling.
17. Make the source video the primary visual element on both the recording and CardEvent review
    pages. Do not reserve a permanent side column for recording metadata. Let the video use the
    available content width, subject only to its aspect ratio and viewport height.
18. Keep the small context needed during review visible beside the video controls: recording date,
    duration, and frame rate. Move session, round, source identifiers, acquisition, permission,
    retention, evidence-package count, and other diagnostic metadata into an accessible
    **Recording details** dialog. The dialog must trap focus, close with Escape, restore focus to
    its opener, and remain usable without a pointer.

## 4. Review resources and API

Replace the recording-keyed singleton draft API with review resources:

```text
GET   /v1/recordings/{recording_id}/card-event-reviews
POST  /v1/recordings/{recording_id}/card-event-reviews
GET   /v1/card-event-reviews/{review_id}
PATCH /v1/card-event-reviews/{review_id}/events/{event_id}
POST  /v1/card-event-reviews/{review_id}/events
POST  /v1/card-event-reviews/{review_id}/complete
```

The collection response lists review ID, state, event counts, reviewer, created time, updated time,
completed time, completed version, and parent review when present. Sort drafts first and completed
reviews newest first. The create request accepts an operator and an optional named parent completed
review. Reject a second draft for the same recording.

The item command endpoints use the expected review revision and a client command ID. Replaying the
same command ID is idempotent. A response returns the new revision, the changed event, aggregate
counts, and completion blockers. Keep one full review read for load and conflict recovery. Do not
send the complete annotation and all proposal decisions after each small edit.

Completion requires no proposed events, the existing full-video acknowledgement, and a named
reviewer. It publishes only `reviewed` events, sorted by effective event time, through the existing
immutable annotation-version and lifecycle-receipt boundary.

## 5. Recording and review experience

The recording **Card events** section is a summary, not an embedded editor. Its initial state shows
an empty list and **Add review**. Each row shows one of these concise forms:

- `Draft by Niklas · updated 2026-09-02 14:32`;
- `✓ Annotated by Niklas on 2026-09-02 14:45`; or
- `Revision of <review> · draft by Niklas`.

The row also shows reviewed, proposed, and dismissed counts. A draft opens as **Continue review**.
A completed review opens read-only. **Add review** after completion starts a revision from the
current completed review. Keep technical IDs and digests in a disclosure.

The dedicated review page starts with a wide source video and compact transport and context row.
The timeline rail and unified event table follow below it. Selected-event details, save state,
full-video progress, and completion controls remain close to the table. The table is the primary
work queue. Sort it by effective time. Give proposed, reviewed, dismissed, and manual-origin rows
distinct but related state and origin labels. Keep the selected row visible when its time changes
and its sorted position moves. Open secondary source metadata from the **Recording details** dialog
instead of shrinking the video with a permanent metadata column.

The one-frame buttons are enabled when the review is editable, an event is selected, and a positive
source frame rate is available. They do not depend on an unrelated request being in flight. If the
frame rate is unavailable, show that exact reason next to the disabled controls. Use the verified
recording media facts as the initial frame-rate source and the loaded video metadata only as a
consistency check.

## 6. Delivery milestones

### M0 — Make the layout video-first and repair keyboard ergonomics

- Raise the centered recording-page maximum width from `72rem` to `96rem` and keep readable prose
  constrained inside it.
- Remove the permanent recording-metadata column and let the source video use the main content
  width.
- Keep date, duration, and frame rate in a compact visible context row. Move the remaining recording
  metadata into the accessible **Recording details** dialog.
- Replace `J` and `K` marker navigation with `Alt+Left` and `Alt+Right`.
- Replace bracket frame nudges with comma and period.
- Make marker navigation select the destination row.
- Correct the one-frame enable conditions and show a reason when source frame rate is unavailable.
- Update the visible shortcut guide and keyboard tests.

Acceptance:

- frame nudge is available for a selected event in an editable fixture with a positive source frame
  rate;
- the disabled state names missing selection, completed review, or missing frame rate as applicable;
- shortcuts use `KeyboardEvent.key` and work with German keyboard layout input;
- `Alt+Right`, then period, selects the next marker and moves it one frame later; and
- the video is the widest primary panel at `1440 x 900` and `1920 x 1080` and is not narrowed by a
  recording-details column;
- the details dialog supports focus trap, Escape close, focus restoration, and keyboard-only use;
  and
- the page remains centered, while `390 x 844` has no page-level horizontal scroll or clipped
  dialog content.

### M1 — Add recording-owned review resources

- Add review identity, operator, created time, updated time, state, parent, and recording ownership
  to `doko-operations` storage.
- Add collection, create, detail, and completion operations with optimistic revision checks.
- Enforce at most one draft and select the latest completed review as current.
- Replace development fixtures and generate the new frontend API types.
- Keep completed annotation versions and lifecycle receipts immutable and consumable downstream.

Acceptance:

- a fixture recording starts with an empty review collection;
- create returns a stable review ID and a direct review URL;
- a second create while a draft exists fails without a partial write;
- completing a review adds one immutable completed list entry; and
- a new review from that entry records parent review and completed-version lineage without changing
  the parent bytes.

### M2 — Unify proposals and reviewed events

- Replace separate draft annotation and proposal-decision state with one event collection.
- Add stable event identity, effective time, state, origin, and optional immutable proposal lineage.
- Add idempotent event command operations for manual add, accept, dismiss, undo, edit, retime, and
  remove.
- Project only reviewed events into the completed `cardevent-annotation/v2` output.
- Remove timestamp-proximity proposal application.

Acceptance:

- accepting a proposal changes one stable event from proposed to reviewed and does not add a second
  unrelated event;
- nudging or editing a proposed event reviews it and retains its proposal ID and original proposal
  time;
- a nearby manual event does not auto-accept or link to a proposal;
- dismiss and undo keep the same event identity and lineage; and
- completion rejects proposed events and publishes reviewed events only.

### M3 — Meet the local latency budget

- Add repeatable timing coverage for review load, event command, draft write, and completion.
- Separate immutable source-context validation from per-command draft validation.
- Cache verified source context and media facts by source digest.
- Avoid full-bundle reads, hashes, video probes, and full-annotation transfers on event commands.
- Record before-and-after fixture measurements in the epic.

Acceptance:

- the timing test proves which stages caused the baseline delay;
- warm event-command p95 is at most 250 ms over at least 30 fixture commands;
- initial review-data p95 is at most 500 ms after recording metadata is available;
- source replacement invalidates the cache and fails safely; and
- restart, write-failure, stale revision, and immutable-source tests still pass.

### M4 — Move review work to its own page

- Replace the embedded recording editor with the review collection and add-or-continue action.
- Add `/card-event-reviews/{review_id}` with direct-load frontend fallback.
- Reuse the wide video, compact source context, and recording-details dialog on the dedicated page.
- Show review status, parent lineage, and a read-only completed view.
- Keep recording progress and training-use summaries synchronized with the current completed review.

Acceptance:

- a recording with no reviews shows an empty list and **Add review**;
- creating a review navigates to its stable page, and reload resumes it;
- the recording page shows draft and completed rows with operator and time;
- a completed review opens read-only and a revision opens as a distinct draft row; and
- recording, review, and direct browser routes work at desktop and narrow viewports.

### M5 — Deliver the fast unified review loop

- Add the single time-ordered event table and shared timeline markers.
- Add visible accept, dismiss, undo, nudge, add, and remove controls plus the fixed shortcuts.
- Apply commands optimistically through one ordered queue and coalesce superseded field edits.
- Preserve queued commands across transient failure and stop on an explicit revision conflict.
- Keep selection and playhead synchronized while accepted or retimed rows move.

Acceptance:

- a browser test completes at least 20 alternating next-and-accept or next-and-dismiss actions
  without waiting for each response before the next input;
- every command persists once and in user order after the queue drains;
- the UI reacts immediately while save state remains visible;
- a failed request retries without losing later queued commands, while a stale revision shows the
  first unapplied command and requires conflict recovery; and
- keyboard-only and pointer-only tests can finish the same fixture review.

## 7. Verification

Use a lightweight test-driven workflow for each milestone. Run focused `doko-operations`, backend,
generated-API, frontend component, and browser tests. M1 and M2 need restart, idempotency,
write-failure, and immutable-artifact checks. M3 needs a repeatable local timing harness with raw
stage timings, not one manual observation. M0, M4, and M5 need desktop, wide-desktop, narrow-screen,
and keyboard coverage.

After route or plan-file changes, check direct frontend fallback and all local Markdown links.
