# Visible-card annotation review workspace

## Plan status

- **Summary:** Seed visible-card review queues with the configured local finder and let an operator
  accept or correct the proposals in the web recording workspace.
- **Status:** In Progress
- **Depends on:** Plan 0038 visible-region and review contracts, and plan 0039 M0 through M4 web
  recording workspace
- **Builds on:** Plans 0020 and 0027 source, task, review, dataset, and lifecycle contracts
- **Related:** Plan 0022 uses reviewed visible-card evidence to select later analyzer work.
- **Outcome:** From an eligible recording with a completed CardEvent review, an operator can create
  a local-finder-seeded visible-card review queue, review every selected exact-event frame in the
  web app, publish an immutable completed review, and prove that the existing visible-card freeze
  path accepts it.
- **Reviewed:** 2026-09-01 against the completed plan 0038 queue contracts, local visible-card
  provider, exact-event extraction path, plan 0039 recording APIs and UI, and current repository
  data boundaries.

## Milestone status

- **M0:** Complete — build a deterministic source-linked batch preparation boundary with immutable
  batch state, exact-event frames, local finder artifacts, and a v2 queue.
- **M1:** Complete — add recording-scoped readiness, preview-bound asynchronous batch creation,
  persisted progress, retry of failed items, and recording-page controls.
- **M2:** Not started — show the queue, source frames, and finder proposals in the web app.
- **M3:** Not started — accept, correct, add, and remove visible-card annotations.
- **M4:** Not started — complete and publish review with immutable lineage and downstream proof.

## 1. Purpose

Turn the local visible-card finder into an annotation assistant. The finder supplies proposals. A
person decides which visible cards and visible regions are correct. Only the completed human review
can become training or evaluation data.

The normal path is:

```text
complete CardEvent review for a recording
  -> create a visible-card review batch from reviewed card_played events
  -> extract each exact-event frame at 0 ms
  -> run the configured local visible-card finder on each frame
  -> review every frame and finder proposal in the web app
  -> publish an immutable completed review and lifecycle receipt
  -> use the existing visible-card freeze path
```

This is the sensible next step after plan 0039. The recording page, source video, CardEvent review,
development partition, generated frontend API types, and conflict-safe web write pattern already
exist. Plan 0038 already provides the visible-region, derived-box, identity-usability, review-queue,
and freeze contracts. This epic connects those parts and adds the missing human geometry editor.

## 2. Scope

This epic includes:

- one recording-scoped action that creates a review batch from its completed reviewed
  `card_played` events;
- exact-event `0 ms` frame extraction with source and annotation lineage;
- proposal generation with one configured local visible-card detector bundle;
- a resumable batch status and review queue in the operations workspace;
- source-frame display with distinct finder proposals and reviewed geometry;
- frame decisions for usable, reviewed empty, and unusable frames;
- visible-card accept, reshape, add, and remove actions;
- one or more polygons for one visible region;
- derived boxes, side, identity usability, unusable reason, and failure tags;
- conflict-safe save after each review action;
- explicit batch completion, immutable completed output, and a lifecycle receipt; and
- one fixture and one local operator path that the existing visible-card freeze command accepts.

This epic does not include:

- CardEvent annotation changes;
- automatic use of an unreviewed finder proposal as ground truth;
- visual card identity labels or identity-model changes;
- tracking one physical card across frames;
- table-observation or reconstruction correction;
- bulk selection across many recordings, queue prioritization, active learning, or review sampling;
- test or system-holdout review;
- dataset balancing or automatic partition assignment for this data task;
- detector training, evaluation, comparison, promotion, or deployment;
- Gemini proposal generation in the web app;
- accounts, permissions, simultaneous multi-user editing, or remote deployment; or
- a general annotation framework.

## 3. Fixed decisions

1. Start from completed human CardEvent annotations. Select only reviewed `card_played` events and
   use their exact event time at offset `0 ms`. Do not create a visible-card queue from raw device
   or model event proposals.
2. Require a selected `table_evidence_analysis` task enrollment and allowed source permission.
   Show either condition as a blocker before batch creation. Do not change enrollment or permission
   as a side effect.
3. Create one batch for one recording in this epic. Record the reviewed CardEvent annotation
   version and digest used for selection. A later epic can add bulk selection after this path is
   measured.
4. Run only the configured local visible-card provider. Record its bundle, request, preprocessing,
   threshold, result, and digest for every frame. A detector failure is a visible batch error; it
   is not a reviewed empty frame.
5. Keep the accepted source bundle, video, reviewed CardEvent annotation, extracted source frame,
   and finder result immutable. Store batch and draft review state below the configured operations
   workspace root.
6. Use the existing `visible-card-review-queue/v2` and `visible-card-review/v2` contracts. Do not
   create web-only annotation data. Extend workflow metadata only when the web lifecycle needs a
   revision, state, or receipt field that does not belong in the annotation.
7. Treat a finder result as a proposal. Render it differently from reviewed geometry. Accepting a
   proposal preserves its geometry. Any geometry change is a reshape action. Removing a proposal
   records a decision without creating a reviewed card.
8. Keep the visible region as the geometry source of truth. Derive the detector box after every
   geometry change. Do not let the operator edit the derived box separately or infer hidden card
   pixels.
9. Present three clear frame outcomes in the UI: **Usable with visible cards**, **Reviewed empty
   frame**, and **Unusable frame**. Map them to the existing frame decision and `empty_frame`
   fields. Do not describe an unusable frame as a negative example.
10. Save after every frame or card action with the expected review revision or digest. Use atomic
   replacement. Return a conflict when the stored revision changed. Never use last-write-wins.
11. Require an action for every finder proposal before a usable frame can complete. A usable frame
    must contain at least one reviewed visible card. A reviewed empty frame must contain none.
12. Publish a completed batch as a new immutable artifact with a lifecycle receipt. A later
    correction starts a new revision from the completed artifact. It does not replace completed
    bytes.
13. Exclude test and system-holdout source-lineage groups before extraction and proposal
    generation. Do not expose a force action.
14. Add a **Visible cards** section to the plan 0039 recording page. Use a dedicated
    `/visible-card-reviews/{batch_id}` route for the frame editor so direct load, reload, and resume
    are stable.
15. Use React, TypeScript, generated OpenAPI types, plain CSS, and an SVG overlay. Do not add a
    canvas annotation framework or component library for this epic.

## 4. Batch creation and lifecycle

The recording page shows visible-card review state and the next available action. It can show:

- `Not ready — complete CardEvent review`;
- `Not eligible — source group is protected`;
- `Finder is not configured`;
- `Ready — N reviewed card-played events`;
- `Preparing frames`;
- `Running finder — X of N`;
- `Ready to review — X of N complete`;
- `Batch failed — retry unavailable items`;
- `Review complete`; and
- `Published — version and receipt`.

Before creation, show a preview with the recording, table-evidence task enrollment, source
permission, reviewed CardEvent version, selected event count, source-lineage group, development
partition, and detector bundle. Creation records this preview digest so a changed annotation or
detector configuration cannot silently change the batch.

Batch preparation must:

1. load the named completed CardEvent annotation version;
2. select all reviewed `card_played` events in stable time order;
3. reject an empty selection, protected source group, missing source, or stale digest;
4. extract one source frame for each event at exact offset `0 ms`;
5. record source video, annotation, event, frame index, timestamp, and frame digests;
6. call the configured local visible-card provider for each frame;
7. preserve each complete provider request and result; and
8. build the v2 review queue only from successful immutable results.

Run preparation outside the request thread. The API creates a batch and returns its state. The
recording page polls while extraction and finder work continue. Retrying a failed batch item must
reuse the same frozen inputs and detector identity. A configuration change requires a new batch.

## 5. Review experience

The batch page shows one frame at a time. It includes:

- completed, in-progress, failed, and total counts;
- previous pending, previous, next, and next pending navigation;
- the source frame at its natural aspect ratio;
- a zoom control and fit-to-view action;
- finder proposal outlines, reviewed visible regions, and derived boxes with distinct styles;
- one card list linked to the overlay;
- frame outcome, card metadata, failure tags, and save state; and
- source and finder lineage in a diagnostic disclosure.

Frequent proposal actions must be one click or tap:

- **Accept** keeps the proposed visible region and side;
- **Correct** opens the geometry editor;
- **Remove** records that the proposal is not a visible card; and
- **Add missed card** starts a new reviewed visible region.

The SVG geometry editor supports:

- create a polygon by placing points;
- select, move, add, and remove a point;
- add or remove a second polygon for a disconnected visible region;
- cancel the current edit without saving; and
- show the derived box while geometry changes.

Coordinates use the existing normalized integer convention. Pointer conversion must use the
rendered image bounds and remain correct after resize or zoom. The editor must reject fewer than
three points, zero-area polygons, out-of-range coordinates, and a derived box that does not match
the visible region.

For every retained or added card, require side and identity usability. Require an unusable reason
when identity is not usable. Allow the existing failure tags. Keep card IDs stable across draft
saves. The UI must explain that the reviewer marks only visible pixels and must exclude hidden
pixels, an occluding card, a hand, and background.

Autosave each complete action. Keep an unfinished polygon only in browser state. On a failed save,
retain it and offer retry. On a conflict, load the winning revision and show which local action was
not applied.

## 6. API and application boundary

Add strict generated API types for these operations:

```text
GET  /v1/recordings/{recording_id}/visible-card-review
POST /v1/recordings/{recording_id}/visible-card-review/preview
POST /v1/recordings/{recording_id}/visible-card-review/batches
GET  /v1/visible-card-reviews/{batch_id}
GET  /v1/visible-card-reviews/{batch_id}/items/{item_id}/image
PUT  /v1/visible-card-reviews/{batch_id}/items/{item_id}
POST /v1/visible-card-reviews/{batch_id}/retry
POST /v1/visible-card-reviews/{batch_id}/complete
POST /v1/visible-card-reviews/{batch_id}/revisions
```

The recording response is a projection of the current batch and completed review state. The batch
response contains stable item IDs, counts, item summaries, current item review data, finder
proposals, revision, and source and finder digests. It does not embed image bytes.

The item update accepts the complete next frame review and expected revision. Shared domain code
validates actions, geometry, metadata, source ownership, proposal references, and completion. The
backend owns HTTP, image delivery, and background execution. The operations package owns batch
state transitions, conflict checks, immutable publication, and lifecycle receipts. The table
analyzer package remains the owner of visible-card provider and review contracts.

Do not shell out to a CLI. Call the existing Python application boundaries directly.

## 7. Completion and downstream boundary

The **Complete review** action is available only when every batch item is reviewed and no item
failed. It must show the frame, retained-card, removed-proposal, added-card, empty-frame, and
unusable-frame counts before confirmation.

Completion validates the full v2 queue again and records:

- batch, recording, source asset, and source-lineage group;
- reviewed CardEvent annotation path, version, and digest;
- exact selected event IDs and times;
- source-frame paths and digests;
- detector bundle, request, result, and prediction digests;
- input draft revision and digest;
- completed review artifact version and digest;
- reviewer and completion time; and
- lifecycle receipt ID and digest.

Completion is idempotent for the same completed draft. Different content requires a new draft
revision. The recording page links to the published review and shows whether the existing freeze
path accepts it. This is a readiness check, not automatic dataset publication.

The epic is complete when the existing `freeze-visible-card-review` application path can consume
the published fixture review without translation. A local real-data run can report a coverage gap;
it does not need to meet the plan 0038 100-frame target in this epic.

## 8. Delivery milestones

### M0 — Build the visible-card batch preparation boundary

- Add the versioned batch request, status, progress, item-failure, and frozen-input contracts.
- Add immutable batch identity and operations-workspace storage.
- Extract exact-event frames from one completed CardEvent review.
- Call one injected local provider for the extracted frames.
- Build the existing v2 review queue with complete source and finder lineage.

Acceptance:

- one direct application call on a fixture recording with two reviewed `card_played` events
  produces two stable queue items;
- extracted frame indices, event times, image digests, source lineage, and annotation digest match
  the fixture;
- every item records the configured detector bundle and complete provider request and result;
- stale annotation, protected source group, missing frame, and provider error produce explicit
  states without a partial completed queue;
- repeated execution with the same frozen inputs has the same batch and item identity; and
- source, accepted bundle, completed CardEvent annotation, and prior artifacts stay unchanged.

### M1 — Run the batch from the recording page

- Add recording-scoped readiness and preview domain functions.
- Run M0 preparation outside the request thread with persisted progress.
- Add preview, create, status, and retry endpoints with generated frontend types.
- Add the Visible cards section, creation preview, progress, and retry controls to the recording
  page.
- Freeze detector identity at preview and reject stale creation input.

Acceptance:

- the operator can preview and create one fixture batch without a CLI command;
- the request returns before extraction and finder execution complete;
- the page shows preparation and finder progress after reload;
- stale preview, unavailable detector, protected source group, missing task enrollment, disallowed
  source use, and item failure produce a plain-language blocker;
- retry keeps the frozen input and detector identity and changes only failed items; and
- two create requests with the same preview cannot create duplicate work.

### M2 — Show and navigate the review queue

- Add the stable batch editor route and direct-load backend fallback.
- Show progress, source frames, proposal overlays, card list, and diagnostic lineage.
- Add frame and pending-item navigation, fit, and zoom controls.
- Keep failed items visible with a retry action and plain-language error.

Acceptance:

- the operator can create a batch and reach its first pending item from one fixture recording;
- reload resumes the same batch and selected item;
- proposal coordinates remain aligned at fit and zoom sizes;
- empty predictions and multiple overlapping proposals have clear, stable states;
- keyboard knowledge is not required; and
- the page has no page-level horizontal scroll at `1440 x 900` and `390 x 844` CSS pixels.

### M3 — Add visible-region annotation and correction

- Add the three frame outcomes and proposal accept, correct, and remove actions.
- Add missed-card creation and the SVG polygon editor.
- Add side, identity usability, unusable reason, and failure-tag controls.
- Derive boxes in shared code after every geometry change.
- Add revision-aware autosave, retry, validation, and conflict feedback.

Acceptance:

- browser tests accept one proposal, reshape one proposal, remove one proposal, and add one missed
  card;
- overlapping and occluded fixtures support disconnected polygons without including the occluder;
- reviewed empty and unusable frames remain distinct and neither becomes a usable positive frame;
- every finder proposal has exactly one action before a usable frame completes;
- invalid polygons and stale revisions fail without a partial write; and
- saved queue artifacts load through the existing v2 review loader after restart.

### M4 — Complete, publish, and prove downstream use

- Add batch summary, completion validation, reviewer input, and confirmation.
- Publish an immutable completed queue and lifecycle receipt.
- Add explicit revision from one completed review.
- Show completed version, digest, receipt, and downstream readiness on the recording page.
- Consume the published fixture with the existing visible-card freeze path.
- Run one local operator path on an eligible real recording when one is available.

Acceptance:

- incomplete or failed items block completion and name the remaining work;
- completion is idempotent for the same draft and conflicts for different content;
- a revision keeps parent lineage and leaves the completed artifact unchanged;
- the lifecycle receipt names every source, CardEvent annotation, frame, finder, proposal, and review
  digest;
- the existing freeze path accepts the fixture output without a schema adapter; and
- the local operator run records duration per frame, correction counts, usability gaps, and corpus
  coverage without starting training or reading protected groups.

## 9. Verification

For each milestone, run the focused table-analyzer, operations, backend, generated-API, frontend
component, and browser checks. M0 needs deterministic generated-video fixtures. M1 needs restart
and retry tests. M3 needs geometry property tests for image-to-normalized coordinate conversion and
derived boxes. M4 needs write-failure, immutable-byte, lifecycle-validation, and downstream-loader
tests.

Before closing the epic, run this complete local path:

1. open an eligible recording with a completed CardEvent review;
2. preview and create its visible-card batch;
3. wait for exact-event extraction and local finder completion;
4. review a mix of accepted, corrected, removed, added, empty, and unusable cases;
5. reload during review and resume without repeated work;
6. complete and publish the batch; and
7. validate the published review with the existing freeze path.

Record the measured review time, proposal acceptance rate, correction rate, missed-card additions,
false-proposal removals, unusable frames, and identity-unusable cards. Use these measurements to
decide whether a later epic needs bulk queues, sampling, active learning, or faster geometry tools.
