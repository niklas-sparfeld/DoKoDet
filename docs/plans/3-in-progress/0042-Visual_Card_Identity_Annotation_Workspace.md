# Visual card identity annotation workspace

## Plan status

- **Summary:** Create and review visual card identity labels from completed visible-card reviews in
  the web recording workspace.
- **Status:** In Progress
- **Depends on:** Plan 0040 complete and plan 0041 classifier proposal and bundle contracts
- **Builds on:** Plans 0020, 0027, 0039, and 0040 source, web, review, lineage, and visible-region
  workflows
- **Outcome:** An operator can create one recording-scoped visual card identity review batch,
  label every identity-usable visible card in the web app, publish an immutable completed review,
  and freeze it as source-linked classifier data without using an unreviewed proposal as ground
  truth.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — strict source-linked batch contracts, frozen identity crops, classifier
  proposals, readiness/preview/create/status/retry API, generated frontend client types, and
  fixture and artifact-integrity checks were added on 2026-09-02.
- **M1:** Not started — show crops and classifier proposals in the web app.
- **M2:** Not started — correct labels and complete each item with conflict-safe saves.
- **M3:** Not started — publish the completed review and prove dataset freeze.

## 1. Purpose

Add the missing human label between reviewed visible-card geometry and local classifier training.
Plan 0040 decides which card pixels are visible and whether a crop is usable for identity. This epic
asks a separate question: which visual card identity is present in each identity-usable crop?

Use classifier output only to reduce review effort. A Gemini result or local bundle result is only
a proposal. The person supplies the reviewed label.

## 2. Scope

This epic includes:

- one visual card identity review batch created from one completed plan 0040 visible-card review;
- deterministic `raw_rectangular` identity crops from the frozen source frame and reviewed derived
  box;
- one configured proposal generator: cached Gemini or a named local identity bundle;
- a recording summary and stable identity-review route in the existing web app;
- review actions for accept, correct, mark unusable, and report an invalid source annotation;
- all 24 canonical visual card identities with concise suit and rank controls;
- conflict-safe autosave, completion, revision, immutable publication, and lifecycle receipts; and
- one fixture path that the existing dataset and split foundation can freeze.

This epic does not include:

- geometry changes inside the identity editor;
- accepting a classifier proposal without a human action;
- bulk work across recordings, active learning, queue prioritization, or sampling;
- model training, quality comparison, threshold selection, promotion, or backend cutover;
- test or system-holdout review; or
- tracking a physical card or choosing which visible card was played.

## 3. Fixed decisions

1. Create a visual card identity review batch only from an immutable completed plan 0040 review.
   Record its version, digest, source frames, visible regions, derived boxes, identity usability,
   and the frozen crop-policy version and digest.
2. Include only reviewed cards marked identity-usable. Keep excluded cards and reasons in the batch
   coverage report. Do not turn an identity-unusable card into a training sample.
3. Use the frozen `raw_rectangular` policy for proposal and review crops. This policy matches the
   current runtime derived-box crop and includes every identity-usable reviewed card. Attach the
   reviewed visual card identity to the source card lineage, not only to these crop bytes. Preserve
   the source frame, reviewed visible region, and derived box so plan 0043 can reproduce the
   `oracle_visible_region` and `conservative_box_only` evaluation conditions without changing the
   human label.
4. Freeze the crop bytes when the batch is created. A later geometry or crop-policy revision creates
   a new batch. It does not mutate the current work.
5. Use one configured proposal generator for the complete batch. Record its name, version, bundle
   or request digest, complete result, score, latency, and failure. A proposal failure leaves the
   item reviewable without a suggestion.
6. Require one explicit decision for every crop: accept the proposal, select a different canonical
   identity, mark the crop identity-unusable with a reason, or report a source-review problem.
7. A source-review problem does not edit plan 0040 geometry. It blocks publication for that item and
   links the operator back to an explicit visible-card review revision.
8. Allow two physical cards to have the same visual card identity. Do not enforce deck counts in the
   annotation editor.
9. Save after each complete decision with an expected revision. Use atomic replacement and return a
   conflict instead of last-write-wins.
10. Exclude test and system-holdout source-lineage groups before crop generation or classifier calls.
   Do not expose a force action.
11. Add an **Identities** section to the recording page and a stable
    `/identity-reviews/{batch_id}` route. Reuse the existing React, TypeScript, generated OpenAPI,
    and plain CSS stack.

## 4. Review experience

Show one large crop, its source-frame context, and the reviewed visible-region outline. Show the
proposal separately from the reviewed decision. The operator can choose suit first and rank second,
or choose one identity from a searchable 24-card grid. Keep every action available without a
keyboard shortcut.

The page shows:

- batch and recording progress;
- crop, source frame, geometry, crop-policy, and proposal lineage;
- previous, next, and next-pending actions;
- the proposed identity and score when available;
- accept, correct, identity-unusable, and source-problem actions;
- optional failure tags that already describe blur, glare, occlusion, small card, and contamination;
  and
- save, conflict, retry, and completion state.

## 5. Delivery milestones

### M0 — Create a visual card identity review batch

- Add strict identity-review batch, item, proposal, decision, and status contracts.
- Add recording-scoped readiness, preview, create, status, and retry operations.
- Materialize immutable crops and run the configured proposal generator outside the request thread.
- Add generated frontend API types.

Acceptance:

- one fixture visible-card review produces stable items only for identity-usable reviewed cards;
- every item binds source, geometry, the frozen `raw_rectangular` policy, crop, and proposal
  digests;
- protected lineage, stale review, changed crop bytes, and proposal failure are explicit;
- retry keeps the same frozen inputs and proposal-generator identity; and
- no source or completed visible-card review bytes change.

### M1 — Show and navigate identity work

- Add the recording identity summary and stable batch route.
- Show the crop, source context, proposal, lineage, and progress.
- Add next, previous, and next-pending navigation plus clear empty and failure states.

Acceptance:

- an operator can create a batch from one completed fixture review and reach its first item;
- reload resumes the same batch and item;
- a missing proposal remains manually reviewable;
- source context and crop remain aligned and understandable; and
- the page works at `1440 x 900` and `390 x 844` CSS pixels without page-level horizontal scroll.

### M2 — Add identity correction and completion

- Add accept, canonical identity selection, identity-unusable, and source-problem actions.
- Add revision-aware autosave, validation, retry, and conflict feedback.
- Add batch summary and explicit completion.

Acceptance:

- browser tests accept one proposal, correct one proposal, label one item without a proposal, and
  mark one crop unusable;
- every completed usable item has exactly one of the 24 canonical identities;
- a source-problem item blocks completion and links to a visible-card revision path;
- stale revisions and invalid identities fail without a partial write; and
- completion requires a decision for every item.

### M3 — Publish and prove downstream freeze

- Publish an immutable completed review with complete source and proposal lineage.
- Write a lifecycle receipt and support an explicit later revision.
- Add the smallest dataset adapter needed to consume the completed identity review.
- Show dataset eligibility and blockers on the recording page.

Acceptance:

- the published review records reviewer, time, input revision, source, crop, proposal, decision, and
  output digests;
- completion is idempotent for the same draft and never replaces earlier bytes;
- a fixture review enters a group-safe development dataset and split without translation;
- each dataset sample keeps enough source and geometry lineage to reproduce all three frozen plan
  0038 crop-policy conditions without changing its reviewed visual card identity;
- identity-unusable and source-problem items do not become classifier samples; and
- existing lifecycle validation accepts the new artifacts and receipts.

## 6. Verification

Run focused operations, backend, frontend component, generated-API, browser, lifecycle, and
artifact-integrity checks for every milestone. M0 and M3 need restart and write-failure tests. M1
and M2 need desktop and narrow-viewport browser coverage.
