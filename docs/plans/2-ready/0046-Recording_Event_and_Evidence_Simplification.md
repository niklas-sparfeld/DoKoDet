# Recording event and evidence simplification

## Plan status

- **Summary:** Replace CardEvent review history with one current event annotation per recording and
  make evidence-package status and re-creation explicit.
- **Status:** Ready
- **Depends on:** Plan 0045 complete
- **Builds on:** Plans 0029, 0032, 0039, 0040, 0042, and 0045
- **Outcome:** An operator can upload or open one recording, review one current event timeline,
  optionally replace unreviewed proposals, and explicitly update missing or out-of-date evidence
  packages. The system keeps old evidence packages as source material but does not expose review
  versions, proposal sets, or model-run history.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — replace review resources with one current recording event annotation.
- **M1:** Not started — simplify the recording-owned event review experience.
- **M2:** Not started — add initial and repeat backend proposal generation.
- **M3:** Not started — link live evidence packages to stable events and show package status.
- **M4:** Not started — extract and explicitly update evidence packages from reviewed events.
- **M5:** Not started — move downstream consumers to current annotation snapshots and remove the
  obsolete review-version path.
- **M6:** Not started — apply the same current-annotation rule to visible-card and visual card
  identity review without adding a generic framework.

## 1. Purpose

Plan 0045 proved a fast event editor. It also added multiple review resources, parent revisions,
immutable completed event versions, dismissed-event history, and full proposal lineage. Those
features are more complex than the expected use warrants.

Use the recording as the stable owner. Keep one editable event collection. A person reviews the
current collection, not a review version. A later correction edits the same collection. A later
model run replaces unreviewed proposals in that collection. The product can lose proposal and edit
history.

Keep evidence packages immutable because they contain media. Treat a package made during live
capture and a package extracted later as the same domain type. Record how the package was made and
the event facts used at creation. When those facts no longer match, show that the package is out of
date. An explicit update creates a new package and makes it current. It does not rewrite or delete
the old package.

The intended flows are:

```text
app recording
  -> upload recording, device proposals, and live evidence packages
  -> review the current events
  -> complete the event annotation
  -> optionally update missing or out-of-date evidence packages

web video
  -> upload recording
  -> generate proposals
  -> review the current events
  -> complete the event annotation
  -> optionally create evidence packages

old recording
  -> open the current completed events
  -> optionally generate fresh proposals
  -> correct or add events
  -> complete the event annotation again
  -> explicitly update evidence packages
```

## 2. Scope

This epic includes:

- one current CardEvent annotation per recording;
- stable event identity, editable event facts, simple review state, broad origin, and current
  reviewer;
- a one-time conversion from the current plan 0045 review workspace;
- initial device proposals and repeat backend proposal generation in the same event collection;
- one evidence-package domain type with live-capture or extracted creation mode;
- event snapshots and a current evidence-package link;
- derived missing, current, out-of-date, and retained package status;
- explicit package extraction and update after event completion;
- current-annotation snapshots at dataset and downstream review boundaries;
- removal of CardEvent review lists, parents, completed versions, dismissed-event history, and
  proposal-run lineage from the product path; and
- the same current-annotation behavior for visible-card and visual card identity work.

This epic does not include:

- concurrent multi-user editing, audit history, review comparison, or review restoration;
- proposal sets, model-run history, model quality comparison, or model promotion;
- automatic evidence-package updates on every event edit;
- mutation or deletion of old evidence-package media;
- a generic annotation framework or base class shared by all tasks;
- changes to event types, CardEvent timing definitions, or evidence capture offsets; or
- reconstruction review and correction constraints.

## 3. Fixed decisions

### 3.1 Current event annotation

1. A recording owns zero or one current CardEvent annotation. The annotation has `draft` or
   `completed` state. It has no review ID, parent, version list, or revision history.
2. Keep an integer storage revision for optimistic saves and idempotent commands. This is a write
   safety value, not a user-visible annotation version.
3. Each current event has:
   - a stable event ID;
   - effective time and event type;
   - `proposed` or `reviewed` state;
   - `device_model`, `backend_model`, or `human` origin;
   - an optional proposal probability;
   - the current reviewer when reviewed;
   - optional notes; and
   - an optional current evidence-package ID.
4. Do not retain proposal generator run, model bundle, execution platform, original proposal time,
   parent review, or prior field values on the current event.
5. **Yes** changes a proposed event to reviewed. Editing a proposed event also changes it to
   reviewed. A manual add starts as reviewed with human origin. Deleting any event removes it from
   the current annotation. There is no dismissed state or undo history after the save queue drains.
6. Keep broad origin as the origin of the event. Human confirmation does not change a device or
   backend origin to human. The current reviewer shows the human decision. A later edit overwrites
   the current reviewer.
7. Completing the annotation requires a reviewer, full-video acknowledgement, and no proposed
   events. Any later event edit or proposal generation changes the annotation back to draft. The
   operator completes the same annotation again.
8. Preserve the optimistic command queue, retry behavior, conflict recovery, keyboard controls,
   source-context cache, and latency budget from plan 0045.

### 3.2 Proposal generation

9. Initial intake creates proposed events from device output when no current annotation exists.
   It does not create a proposal set or a review resource.
10. **Generate proposals** and **Generate proposals again** preserve reviewed events, remove current
    proposed events, and add fresh backend proposals. Suppress a fresh proposal within the existing
    fixed duplicate tolerance of a reviewed event of the same type. Do not create lineage between
    the two events.
11. Keep at most one current proposal-generation operation for a recording. It can report queued,
    running, failed, or complete so that the browser can recover after navigation. A new operation
    replaces its status. Do not keep an operator-facing run list.
12. A failed generation leaves reviewed events and the prior proposed events unchanged. Replace
    proposals only after generation finishes successfully.

### 3.3 Evidence packages

13. An evidence package remains an immutable source asset. Live capture and later extraction are
    creation modes of the same domain type, not separate evidence types.
14. A new package records its recording ID, creation mode, and an immutable event snapshot with
    event ID, effective time, event type, state, and origin. Device proposal and live package use
    the same event ID.
15. An event points to at most one current evidence package. Several retained packages can contain
    snapshots of that event. Deleting an event does not delete its packages.
16. Compare the current event time and type with the current package snapshot:
    - `missing`: the event has no current package;
    - `current`: time and type match;
    - `out_of_date`: time or type differs; and
    - `retained`: the package is not current for an existing event, or its event was deleted.
    State, reviewer, and notes do not make recorded media out of date.
17. Completing or editing events never changes package bytes. After completion, show one explicit
    action for the reviewed events whose packages are missing or out of date. The action creates
    replacement packages from the recording. Validate and update each event pointer independently
    so that one failed extraction does not discard other valid packages.
18. Keep old live and extracted packages discoverable for training and diagnosis. Their event
    snapshots preserve useful false-positive material after a device proposal is deleted. Do not
    show package history in the normal review loop.

### 3.4 Other annotation tasks

19. Visible-card and visual card identity work use the same simple interaction rule: proposals and
    reviewed items share one current collection; confirmation or correction edits the item;
    dismissal deletes it; and a rerun replaces only proposed items.
20. Keep visible region and visual card identity as separate domain facts. Do not combine detector
    geometry and classifier identity into one label or one model result.
21. Freeze a value copy and digest of current reviewed inputs only when a downstream batch, dataset,
    evaluation, or model run starts. Reproducibility belongs at that consumption boundary. It does
    not require user-visible annotation history.
22. Implement the three concrete stores separately. Do not introduce a generic annotation schema,
    repository, command bus, or review framework.

## 4. Current contracts and routes

Replace the CardEvent review collection and review-resource routes with recording-owned routes:

```text
GET   /v1/recordings/{recording_id}/events
POST  /v1/recordings/{recording_id}/events
PATCH /v1/recordings/{recording_id}/events/{event_id}
POST  /v1/recordings/{recording_id}/events/complete
POST  /v1/recordings/{recording_id}/event-proposals
GET   /v1/recordings/{recording_id}/event-proposals/status
POST  /v1/recordings/{recording_id}/evidence-packages/update
```

Use one recording event document similar to:

```text
recording_id
state: draft | completed
revision
events[]
full_video_acknowledged
completed_by?
completed_at?
updated_at
```

Keep command IDs and expected revisions on event mutations. Return the changed event, next
revision, aggregate counts, annotation state, and evidence status. Generate the frontend client
from the changed OpenAPI contract.

Use `/recordings/{recording_id}/events` as the stable browser route. Remove
`/card-event-reviews/{review_id}` and the recording review list after conversion.

## 5. Existing-data conversion

Provide one idempotent local conversion command. For each recording:

1. use its draft review when one exists; otherwise use its latest completed review;
2. copy proposed and reviewed events into the current annotation;
3. drop dismissed events and all proposal, parent, version, and command-receipt lineage;
4. map manual, model, and device origins to human, backend model, and device model;
5. keep current event IDs, effective time, type, reviewer when available, and notes;
6. preserve draft or completed state when its requirements still hold; and
7. leave old evidence-package bytes unchanged and leave packages without a reliable event ID as
   retained recording evidence.

When a recording has no plan 0045 review, create its current annotation once from its accepted
device proposals. Never seed it again after a person deletes or reviews those proposals.

The conversion is the only compatibility work. New runtime code reads and writes only the new
contracts after M5.

## 6. Delivery milestones

### M0 — Add the current recording event annotation

- Update the glossary so that an evidence package can result from a proposed or reviewed event.
- Add the recording event document and recording-owned store.
- Add stable event commands, completion, optimistic revision checks, and idempotency.
- Add the one-time plan 0045 conversion command and fixtures.
- Keep the plan 0045 source cache and measured command path.

Acceptance:

- one recording resolves to at most one current event annotation;
- accept, edit, add, delete, complete, reopen-on-edit, retry, and conflict tests pass;
- a deleted proposal leaves no dismissed row or proposal decision record;
- conversion chooses the draft before the latest completion, is idempotent, and does not change
  source video or evidence-package bytes; and
- warm event-command p95 remains at most 250 ms over at least 30 fixture commands.

### M1 — Simplify the event review experience

- Replace the review list with one event summary and **Review events** or **Edit events** action.
- Move the existing fast editor to `/recordings/{recording_id}/events`.
- Remove review names, parent lineage, completed-version details, dismissed rows, and revision
  actions.
- Keep the video-first layout, timeline, shortcuts, optimistic queue, save state, and accessible
  controls from plan 0045.
- Show the current operator decision and concise evidence status on each reviewed event.

Acceptance:

- an app or web recording reaches the same stable event page;
- the normal loop is next, Yes or delete, correct when needed, add missing events, and complete;
- editing a completed annotation starts no new review and changes the same annotation to draft;
- page reload and transient save failure preserve current work; and
- desktop, German-keyboard, pointer-only, and narrow-screen browser tests pass.

### M2 — Generate and replace proposals

- Add the current proposal-generation operation and backend CardEventNet adapter.
- Seed device proposals only during initial annotation creation.
- Preserve reviewed events and atomically replace proposed events after a successful backend run.
- Suppress same-type proposals within the fixed duplicate tolerance of reviewed events.
- Add **Generate proposals** and **Generate proposals again** with concise current status.

Acceptance:

- a web-uploaded video with no proposals can generate them and enter the normal review loop;
- rerun keeps every reviewed and manual event unchanged and replaces all prior proposed events;
- a failed or interrupted run changes no event;
- repeated status reads show only the current operation and page reload can resume it; and
- no proposal-set, generator-run, bundle-lineage, or run-history field enters the event contract.

### M3 — Link live packages and show evidence status

- Add a stable event ID to the device proposal and live evidence-package creation path.
- Add recording ID, creation mode, and event snapshot to the canonical evidence-package envelope.
- Associate uploaded live packages with their matching current events.
- Add current package ID and derived evidence status to event responses.
- List retained packages only in recording details and data tooling.

Acceptance:

- one device event uses the same ID in the proposal, current event, and live package snapshot;
- confirming an unchanged device proposal keeps its live package current;
- correcting its time or type makes the package out of date;
- deleting it leaves the package retained and available to training-data discovery; and
- an old package without a reliable event ID remains valid retained evidence.

### M4 — Explicitly update evidence packages

- Extract the existing frame set and optional video snippet from the source recording around each
  selected reviewed event.
- Preview missing and out-of-date events before extraction.
- Add one explicit **Update evidence packages** action after event completion.
- Validate each new package before changing its event pointer.
- Report per-event extraction blockers without changing the completed event annotation.

Acceptance:

- completing events does not start extraction without operator confirmation;
- update creates packages only for reviewed events that are missing or out of date;
- successful update makes each created package current and retains every prior package;
- a failed event keeps its prior pointer and clear blocker without undoing other successful events;
  and
- repeating update with no event changes creates no package.

### M5 — Move consumers and remove review versions

- Make CardEvent dataset, development split, visible-card preparation, and recording summaries read
  the current completed event annotation.
- At each downstream creation boundary, copy the selected reviewed events and their digest into the
  created immutable artifact.
- Remove CardEvent review-resource APIs, stores, pages, completed-version files, parent lineage,
  legacy generated client types, and obsolete fixtures after conversion.
- Update active plans and documentation that describe the current runtime path. Do not rewrite
  closed epics.

Acceptance:

- visible-card preparation freezes the events it selected and is unchanged by later event edits;
- existing dataset and split reproducibility comes from their frozen input copy and digest;
- no runtime consumer needs a CardEvent review ID or completed-version path;
- one search finds no active review-resource route, parent-review field, or dismissed-event state;
  and
- converted real development recordings remain discoverable through the normal data tools.

### M6 — Simplify visible-card and identity annotations

- Replace per-recording visible-card review history with one current visible-card annotation.
- Replace per-recording visual card identity review history with one current identity annotation.
- Use proposed or reviewed item state, broad origin, current reviewer, delete-on-dismiss, and
  replace-proposals-on-rerun behavior in each store and UI.
- Keep visible regions separate from identity decisions and keep the existing focused editors.
- Freeze current reviewed items only when a dataset, evaluation, or multi-recording work unit is
  created.

Acceptance:

- each recording has at most one current annotation for events, visible regions, and identities;
- correcting completed work edits the current annotation without creating a parent or revision;
- detector and classifier reruns preserve reviewed items and replace only proposed items;
- dataset creation freezes a value copy and digest that later edits cannot change; and
- the implementation contains three concrete task stores and no new generic review framework.

## 7. Verification

Use a lightweight test-driven workflow for each milestone. Run focused operations, backend,
generated-client, frontend, Swift, browser, intake, evidence, dataset, and split checks. Include
conversion, restart, idempotency, conflict, write-failure, partial-extraction, and immutable-media
coverage. Exercise all three user flows with local fixtures. Finish M4 with one real development
recording that has a corrected event, a retained old live package, and a new current extracted
package.
