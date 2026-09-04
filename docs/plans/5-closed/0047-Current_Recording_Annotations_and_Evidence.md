# Current recording annotations and evidence

## Plan status

- **Summary:** Replace review history with current recording annotations, replace unreviewed
  proposals in place, and explicitly update immutable evidence packages.
- **Status:** Closed
- **Closure reason:** Superseded
- **Closure note:** Replaced by 0048 and 0049 before implementation. Keep one maintained reference,
  but retain processor results and completed reference revisions. Derive visual inputs from
  recording video. Proposal replacement and evidence-package management from this proposal are not
  the target design.
- **Depends on:** Plan 0046 complete and plan 0045 complete
- **Builds on:** Plans 0029, 0032, 0039, 0040, 0042, 0045, and 0046
- **Outcome:** An operator can open one recording, review one current event timeline, rerun
  proposals, and explicitly create missing or updated evidence. Visible-card and identity work use
  aligned current annotations. Reproducibility starts when a consumer freezes an input snapshot.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)
- **Former blocker:** The storage prerequisite is complete. This proposal is closed because the
  product decisions changed before implementation.

## Milestone status

- **M0:** Blocked — add the current recording event annotation filesystem contract.
- **M1:** Blocked — simplify the recording event review experience.
- **M2:** Blocked — add safe initial and repeat backend proposal generation.
- **M3:** Blocked — add one mode-aware evidence-package contract and stable event links.
- **M4:** Blocked — explicitly create and update evidence packages from reviewed events.
- **M5:** Blocked — move CardEvent consumers and remove CardEvent review versions.
- **M6:** Blocked — add the current visible-card annotation store and dependency status.
- **M7:** Blocked — simplify visible-card review and proposal reruns.
- **M8:** Blocked — add the current identity annotation and aligned identity review.
- **M9:** Blocked — freeze aligned downstream inputs and remove obsolete review paths.

## 1. Purpose

Plan 0045 proved a fast event editor. Plans 0040 and 0042 proved focused visible-card and visual
card identity editors. Their immutable review resources, parent revisions, completed versions,
dismissed history, and proposal lineage are more complex than expected use warrants.

Use the recording as the stable owner. Keep one current annotation for each concrete data task.
Edit that annotation in place. A successful model rerun preserves reviewed items and replaces
unreviewed proposals. A dismissal deletes the proposal. The product can lose proposal and edit
history.

Keep evidence packages immutable because they contain media. Live capture and backend extraction
use one mode-aware evidence-package contract. Each package contains the event snapshot that created
its media. An event points to at most one current package, but the filesystem can retain several
packages for the same stable event. An explicit update creates a new package and changes the
pointer only after validation.

Current annotations can depend on other current annotations. A visible-card annotation depends on
the event facts and exact-event frames that seeded it. An identity annotation depends on the
visible-region facts and crops that seeded it. The backend must show stale dependencies and prevent
misaligned data from entering a dataset.

## 2. Scope

This epic includes:

- one current CardEvent annotation per recording;
- stable event identity, editable event facts, simple review state, origin, and current reviewer;
- safe initial device proposals and repeat backend proposal generation;
- one mode-aware evidence-package contract for live capture and extraction;
- immutable event snapshots, several retained packages, and one current package pointer;
- explicit package extraction and update after event completion;
- one current visible-card annotation per recording;
- one current visual card identity annotation per recording;
- dependency snapshots and current or stale status between the three annotation tasks;
- aligned value copies and digests at dataset, evaluation, batch, and model-run boundaries;
- one-time conversion from the current review workspaces; and
- removal of user-visible review, parent, version, dismissed-item, and proposal-run history.

This epic does not include:

- a storage database or durable secondary index;
- concurrent multi-user editing, audit history, comparison, or restoration;
- model-run history, quality comparison, or model promotion;
- automatic evidence-package updates after every event edit;
- mutation or deletion of old evidence-package media;
- a generic annotation schema, store, repository, or command bus;
- changes to event types, CardEvent timing definitions, evidence offsets, visible-region meaning,
  or visual card identity meaning; or
- reconstruction review and correction constraints.

## 3. Fixed decisions

### 3.1 Current event annotation

1. A recording owns zero or one current CardEvent annotation filesystem resource. It has `draft`
   or `completed` state, an integer storage revision, and no review ID, parent, or version list.
2. Each current event has a stable event ID, effective time, event type, `proposed` or `reviewed`
   state, `device_model`, `backend_model`, or `human` origin, optional proposal probability,
   current reviewer when reviewed, optional notes, and optional current evidence-package ID.
3. Do not retain generator run, model bundle, execution platform, original proposal time, prior
   values, or dismissed decisions on a current event.
4. Confirming or editing a proposal makes it reviewed. A manual add starts reviewed with human
   origin. Deleting any event removes it from the annotation after the command commits.
5. Human confirmation does not change device or backend origin. The latest human action replaces
   the current reviewer.
6. Completion requires a reviewer, full-video acknowledgement, and no proposed events. An event
   fact change or successful proposal replacement changes the same annotation back to draft.
7. Evidence pointer updates do not change reviewed event facts and do not reopen the annotation.
   They still use the annotation revision and atomic compare-and-replace.
8. Preserve command IDs, optimistic revisions, replay results, ordered retry, conflict recovery,
   keyboard controls, source-context cache, and the warm 250 ms command budget from plan 0045.

### 3.2 Proposal generation

9. Initial intake creates proposed events from device output only when the current annotation does
   not exist. A stable device event ID travels with the proposal and any live evidence package.
10. A backend rerun preserves reviewed events, replaces proposed events only after success, and
    suppresses a same-type proposal within the existing duplicate tolerance of a reviewed event.
11. Keep one current proposal operation document per recording. It has an internal operation ID,
    state, request revision, and concise error. The event contract does not contain this lineage.
12. Reject a second start while an operation is queued or running. A terminal operation can be
    replaced by a later operation.
13. Before commit, the worker verifies that its operation ID is still current and its source event
    revision still matches. A stale worker result cannot replace proposals or status.
14. A failed, interrupted, or stale operation changes no event and does not reopen a completed
    annotation.

### 3.3 Evidence packages

15. Use one evidence-package schema with a common envelope and a mode-specific creation section:
    `live_capture` records device model, decoder, camera, client, and capture facts;
    `recording_extraction` records source recording, extractor, media transform, and requested
    offsets. Do not fabricate live-capture facts for extracted media.
16. Every new package records package ID, recording ID, creation mode, immutable event snapshot,
    media members, digests, permission, retention state, and creation time.
17. The event snapshot contains event ID, effective time, event type, state, and origin. Device
    proposal and live package use the same event ID.
18. The package ID is the filesystem identity. Remove the old one-package-per-session-event rule.
    Several immutable packages can contain snapshots of one event.
19. An event points to at most one current package. Deleting an event does not delete its packages.
20. Event evidence status is `missing`, `current`, or `out_of_date`. It is current only when the
    package recording ID and snapshot event ID match and snapshot time and type equal current event
    facts.
21. Package retention status is separate. A package is `current` when an existing event points to
    it and the snapshot matches. Otherwise it is `retained`. A package for a deleted event remains
    retained source evidence.
22. Validate each extracted package completely before atomically updating its event pointer. Check
    the event ID, time, type, and expected annotation revision again at pointer commit.
23. One event extraction failure does not discard successful packages for other events. Repeating
    an update with no missing or out-of-date events creates no package.

### 3.4 Annotation dependencies

24. A visible-card annotation records the selected reviewed CardEvent IDs, event fact digest,
    exact-event frame digest, and source recording digest used to seed its current items.
25. An event deletion, time change, type change, or recording change makes affected visible-card
    input stale. Completion and dataset use are blocked until the operator refreshes those inputs.
26. Refreshing visible-card inputs preserves reviewed items only when their stable event ID and
    exact source-frame digest still match. It removes obsolete proposed items and reruns proposals
    for changed inputs. It changes the annotation to draft.
27. An identity annotation links every item to a stable reviewed visible-region ID and records the
    visible-region, derived-box, identity-usability, source-frame, crop-policy, and crop-byte
    digests used for that item.
28. A visible-region deletion or change to geometry, usability, frame, or crop policy makes the
    linked identity input stale. Completion and dataset use are blocked until refresh.
29. Refreshing identity inputs preserves a reviewed identity only when the stable visible-region
    ID, source-frame digest, crop policy, and crop bytes still match. It removes obsolete proposed
    items, creates new items for new usable regions, reruns proposals for changed inputs, and makes
    the annotation draft.
30. Stale is a dependency state, not annotation history. Keep only the current dependency snapshot
    after a successful refresh.

### 3.5 Consumption and concrete stores

31. A downstream dataset, evaluation, multi-recording work unit, or model run accepts only aligned
    completed annotations. It freezes a value copy and digest of every selected current input.
32. Later current-annotation edits do not mutate a frozen downstream artifact.
33. Implement separate event, visible-card, and identity stores and contracts. Share atomic
    filesystem helpers from plan 0046, but do not add a generic annotation framework.

## 4. Filesystem resources and routes

Use recording-owned mutable resources below the operations root:

```text
recordings/<recording_id>/events/annotation.json
recordings/<recording_id>/events/proposal-operation.json
recordings/<recording_id>/visible-cards/annotation.json
recordings/<recording_id>/identities/annotation.json
```

Keep immutable evidence packages below:

```text
data/intake/evidence-packages/<package_id>/
```

Use recording-owned API routes:

```text
GET    /v1/recordings/{recording_id}/events
POST   /v1/recordings/{recording_id}/events
PATCH  /v1/recordings/{recording_id}/events/{event_id}
PATCH  /v1/recordings/{recording_id}/events
POST   /v1/recordings/{recording_id}/events/complete
POST   /v1/recordings/{recording_id}/event-proposals
GET    /v1/recordings/{recording_id}/event-proposals/status
POST   /v1/recordings/{recording_id}/evidence-packages/update
```

`PATCH /events/{event_id}` accepts confirm, edit, and remove commands. `PATCH /events` updates
document-level draft fields such as full-video acknowledgement. Every mutation carries a command
ID and expected revision. The response returns the changed resource, next revision, counts,
annotation state, dependency status where applicable, and event evidence status.

Use `/recordings/{recording_id}/events` as the stable browser route. The visible-card and identity
editors keep focused recording-owned routes defined in their delivery milestones.

## 5. Existing-data conversion

Provide idempotent local conversion commands after each new concrete store exists.

For CardEvent data:

1. use the existing draft review when present; otherwise use the latest completed review;
2. copy proposed and reviewed events and preserve stable event IDs;
3. drop dismissed events, parents, versions, proposal lineage, and command receipts;
4. map manual, model, and device origin to human, backend model, and device model;
5. preserve completed state only when current completion requirements hold; and
6. leave all evidence-package bytes unchanged.

For visible-card and identity data, choose the current draft when present; otherwise choose the
latest completion. Copy reviewed and proposed current items, stable source-item IDs, and the source
facts needed to calculate dependency status. If reliable source facts are unavailable, create a
draft annotation with stale dependency status. Drop review and proposal history.

When no current CardEvent source exists, seed device proposals once. Never seed them again after a
person changes the annotation. Old packages without a reliable stable event ID remain retained
recording evidence.

After M9, runtime code reads and writes only the new current contracts. The conversion commands are
the only compatibility path.

## 6. Delivery milestones

### M0 — Add the current event annotation store

- Add the event annotation filesystem contract and concrete store.
- Add document and event commands, completion, revisions, replay, and conflict behavior.
- Add the CardEvent conversion command and fixtures.
- Keep the plan 0045 source cache and measured command path.

Acceptance:

- one recording resolves to at most one current event annotation;
- confirm, edit, add, remove, acknowledge, complete, reopen, retry, and conflict tests pass;
- conversion selection is deterministic and idempotent;
- removal leaves no dismissed row or decision record; and
- warm event-command p95 is at most 250 ms over at least 30 fixture commands.

### M1 — Simplify the event review experience

- Replace review lists with one event summary and **Review events** or **Edit events** action.
- Move the fast editor to `/recordings/{recording_id}/events`.
- Remove review names, parents, completed-version details, dismissed rows, and revision actions.
- Keep video-first layout, timeline, shortcuts, save queue, save state, and accessible controls.
- Show the current operator decision and event evidence status.

Acceptance:

- app and web recordings reach the same stable event page;
- editing completed event facts changes the same annotation to draft;
- page reload and transient save failure preserve events and full-video acknowledgement; and
- desktop, German-keyboard, pointer-only, and narrow-screen browser tests pass.

### M2 — Generate and safely replace proposals

- Add the current proposal-operation document and backend CardEventNet adapter.
- Seed device proposals only during initial annotation creation.
- Preserve reviewed events and atomically replace proposed events after a successful current run.
- Add **Generate proposals** and **Generate proposals again** with concise status.

Acceptance:

- a web video with no proposals can enter the normal review loop;
- rerun preserves reviewed events and replaces prior proposals;
- a failed, interrupted, concurrent, or superseded run changes no event;
- restart and page reload recover the current operation status; and
- no operation or model lineage enters an event.

### M3 — Add mode-aware evidence packages

- Replace the live-only evidence manifest with the common, live-capture, and extraction sections.
- Remove logical-event uniqueness from the filesystem store and validation rules.
- Add stable event ID creation to device proposals and live packages.
- Add recording ID, creation mode, event snapshot, and package retention status.
- Add current package ID and event evidence status to event responses.

Acceptance:

- live and extracted packages both validate without invented metadata;
- two packages for one stable event coexist and remain independently addressable;
- one device event ID matches its proposal, annotation event, and live package snapshot;
- a corrected event makes its old package out of date; and
- packages without a reliable event ID remain valid retained evidence.

### M4 — Explicitly update evidence packages

- Preview reviewed events with missing or out-of-date evidence.
- Extract the current frame set and optional snippet from the source recording.
- Add one explicit **Update evidence packages** action after event completion.
- Validate each package and compare event facts again before pointer commit.
- Report blockers per event.

Acceptance:

- completion never starts extraction automatically;
- update creates packages only for reviewed missing or out-of-date events;
- each success changes only its event pointer and retains prior packages;
- a stale revision or failed event keeps its prior pointer without undoing other successes; and
- a no-op repeat creates no package.

### M5 — Move CardEvent consumers and remove versions

- Make CardEvent dataset, development split, visible-card preparation, and recording summaries read
  the current completed annotation.
- Freeze selected reviewed events and their digest at each downstream creation boundary.
- Remove CardEvent review APIs, stores, pages, completed versions, parents, and obsolete fixtures.
- Update active documentation without changing closed epics.

Acceptance:

- visible-card preparation freezes its selected event facts;
- later event edits cannot change existing datasets or splits;
- no runtime consumer needs a CardEvent review ID or completed-version path; and
- converted development recordings remain discoverable through normal data tools.

### M6 — Add the current visible-card annotation store

- Add the concrete recording-owned visible-card annotation contract and store.
- Add stable visible-region IDs, proposed or reviewed state, origin, reviewer, and revisions.
- Add event dependency snapshots, current or stale calculation, and refresh commands.
- Convert the selected existing visible-card review for each recording.

Acceptance:

- each recording has at most one current visible-card annotation;
- event changes make only affected inputs stale;
- refresh preserves reviewed regions only when event and frame facts match;
- stale or incomplete visible-card annotations cannot enter a dataset; and
- conversion is deterministic and idempotent.

### M7 — Simplify visible-card review and reruns

- Move the focused visible-card editor to the current recording annotation.
- Replace confirm and correction with reviewed-item edits and dismissal with removal.
- Preserve reviewed items and replace proposed items on a detector rerun.
- Add clear stale-input navigation back to current events and an explicit refresh action.

Acceptance:

- correcting completed work edits the same annotation and makes it draft;
- detector rerun preserves reviewed items and replaces only proposals;
- refresh and rerun cannot hide stale event inputs;
- autosave, retry, conflicts, pointer-only use, and narrow-screen tests pass; and
- no visible-card parent, version list, or dismissed history remains in the normal path.

### M8 — Add aligned current identity annotation

- Add the concrete recording-owned identity contract and store.
- Convert the selected existing identity review for each recording.
- Add visible-region dependency snapshots, stale calculation, and refresh behavior.
- Move the focused identity editor to the current annotation.
- Preserve reviewed identities and replace proposals on a classifier rerun.

Acceptance:

- each recording has at most one current identity annotation;
- changed geometry, usability, frame, crop policy, or crop bytes makes the linked input stale;
- refresh preserves a reviewed identity only when all identity input facts still match;
- classifier rerun preserves reviewed identities and replaces only proposals; and
- stale or incomplete identity annotations cannot enter a dataset.

### M9 — Freeze aligned inputs and remove obsolete paths

- Make visible-card and identity datasets, evaluations, and model runs read aligned completed
  current annotations.
- Freeze value copies and digests of every selected upstream and current annotation input.
- Remove visible-card and identity review lists, parents, completed versions, old batch lifecycle
  paths, legacy clients, and obsolete fixtures.
- Update active plans and the recording summaries.

Acceptance:

- frozen artifacts are unchanged by later event, geometry, or identity edits;
- a single consistency check proves that all frozen identities match their frozen crops, regions,
  frames, and event inputs;
- runtime search finds no user-visible parent, revision, dismissed-item, or review-list path for
  the three current annotation tasks;
- the implementation contains three concrete stores and no generic annotation framework; and
- plan 0043 can consume the new aligned current identity snapshot.

## 7. Verification

Use a lightweight test-driven workflow for each milestone. Run focused operations, backend,
generated-client, frontend, Swift, browser, intake, evidence, dataset, and split checks. Include
conversion, restart, replay, conflict, concurrent proposal start, stale worker, write failure,
partial extraction, dependency invalidation, refresh, and immutable-media coverage. Exercise app,
web, and old-recording flows with local fixtures. Finish M4 with one real development recording
that has a corrected event, a retained old live package, and a new current extracted package.
