# Independent visible-card reviews

## Plan status

- **Summary:** Create, resume, and switch independent visible-card reviews seeded from visible regions or proposed card scenes.
- **Status:** In Progress
- **Depends on:** None. The existing visible-card reference, proposal, and review workspace provide the starting implementation.
- **Outcome:** Starting a review creates a new draft with exact input lineage. An operator can switch between reviews without replacing another draft or transferring its decisions.

## Milestone status

- **M0:** Complete — trace the existing lifecycle and freeze the independent-review contract.
- **M1:** Complete — persist isolated review records, list and retrieve them by review ID, and expose the legacy draft without rewriting it.
- **M2:** Not started — create and edit reviews through review-scoped APIs.
- **M3:** Not started — publish, select, and consume completed reviews safely.
- **M4:** Not started — integrate both review entry points and switching in the workspace.
- **M5:** Not started — verify existing data, concurrent edits, restart, and the reported workflow.

## Problem and desired behavior

A detector run and a proposed card scene run each create an immutable result. The current
visible-card reference has one mutable draft per recording. Starting a review from proposed scenes
can rebase that draft. It can fail when reviewed regions belong to frames with different image
digests. It can also replace the draft's review inputs when the operator intended a new review.

Both the visible-region and proposed-scene entry points must use the same review lifecycle. The
current visible-region entry point also uses the single maintained draft; do not assume it already
supports independent drafts. Keep the appropriate editor and input behavior for each entry point.

- Starting a new review creates a distinct draft, even when another review exists or uses the same
  inputs. It does not rebase, copy human decisions, or change another draft.
- A visible-region review freezes its selected detector revision. A scene review freezes its selected
  proposal, detector revision, calibration, frame identities, and applicable digests. Keep empty,
  unsupported, and no-card outcomes explicit.
- List reviews for a recording and let the operator select, resume, and distinguish them by source,
  status, and time. Switching restores each draft and its edits after restart.
- Keep one explicit selected completed visible-card reference for downstream use. Creating or
  switching drafts must not silently change that selection. Completion and selection must be
  explicit and independent of the selected draft.
- Preserve existing human work, including ignore regions, pile regions, card scenes, review states,
  completed revisions, and downstream selection. Preserve the frozen 0096 review queue and its
  exact inputs. Do not change the scene algorithm or detector outputs.
- The reported run `card-scene-proposal-1793741954253` for `game-2026-08-20-01-001` is a
  development acceptance case. Its existing review must remain accessible and unchanged. A fresh
  scene review must not transfer its ignore regions or require identical image hashes.

## M0 — Freeze the lifecycle and contract

- Current path: the visible-region editor loads `/pipeline/references/visible_cards`, creates one
  reference from the selected generated (or completed) revision, and saves optimistic operations to
  its single draft. The proposal entry point uses the same reference; its current rebase operation
  changes that draft's source and proposal lineage. Calibration refinement has a separate
  proposal-scoped draft and currently has no visible-card review ID.
- Current storage: `PipelineReferenceStore` keeps one `state.json`, `draft.json`, and `commands.json`
  under `pipeline-references/<recording>/visible_cards`. The state contains one draft revision,
  status, source, and selected completed revision. Reads validate canonical files; commands use a
  resource lock, command digest, and expected revision.
- Current API and selection: `POST .../references/visible_cards` conflicts when a reference already
  exists; `PUT .../draft` edits it; `POST .../complete` publishes an immutable revision and also
  selects it through the selection store and reference state. The workspace returns the single
  reference plus the separate selected-generated and selected-completed revision IDs. Identity
  annotation and other downstream consumers resolve the selected completed visible-card revision.
- Current lineage: a detector-seeded draft names its source data revision. A proposal-seeded draft
  also names the proposal revision; proposal inputs retain the detector revision and calibration
  used by that processor run. Scene review items carry frame identity and image digest. Digests are
  per frame and can differ within one review; they are not a recording-wide equality constraint.
- New contract: each review has a server-generated stable `review_id`, one status (`draft` or
  `completed`), one mutable draft revision, one command ledger, and immutable input lineage. A
  visible-region review freezes its selected detector revision. A scene review freezes the proposal
  revision, its detector input, calibration revision, frame IDs, and each frame's image digest.
  Empty, unsupported, and no-card outcomes stay explicit in the source result and review lineage.
- Review output: create and read return `review_id`, recording ID, status, draft revision, source
  summary, exact input lineage, and timestamps. List returns those summaries newest-updated first,
  then by `review_id` ascending for ties. Draft commands return the review identity, committed
  revision, and command receipt. Completed data revisions carry the review ID and the same frozen
  lineage.
- New request and concurrency contract: a fresh create without a prior idempotency key always makes
  a new review, including for the same inputs. A retry with the same key and identical request
  returns the same review; reuse with different request bytes conflicts. Serialize review creation
  per recording and publish the review record before exposing it in the list. An interrupted write
  must leave the prior reviews and pointers readable. Commands and calibration refinement include
  `review_id`, `command_id`, and expected revision. Same-key/same-command retries are idempotent;
  key reuse with different bytes and stale revisions conflict without mutation. Two editors may edit
  one review, but only the first command at a revision can commit.
- New selection contract: the active review is client/workspace state addressed by `review_id`; it
  is restored from the review URL after restart and is never a shared recording pointer. The
  downstream maintained reference is a separate, explicit selected completed revision. Completion
  publishes a revision and marks that review complete but does not change the downstream selection.
  Only an explicit select-completed command changes that pointer.
- Preservation and recovery: expose the current single draft as one legacy review with its exact
  IDs, decisions, state, source, command ledger, and lineage. Preserve the selected completed
  revision independently. Reads and list operations do not rewrite legacy files. Migration is
  atomic or safely repeatable; a failure cannot lose either the old address or the new review record.
  Missing or digest-mismatched source inputs return an explicit unavailable/conflict result and do
  not create, rebase, or alter another review. Per-frame digest differences are valid when each
  digest matches its own frozen input.
- Contract examples are in
  [`backend/tests/fixtures/visible_card_reviews/m0_lifecycle_contract.json`](../../../backend/tests/fixtures/visible_card_reviews/m0_lifecycle_contract.json).
  Later acceptance checks: M1 verifies migration, isolation, restart, atomic creation, and list
  ordering; M2 verifies same-input creation, idempotent retries, per-review edits and calibration,
  stale/wrong-review rejection, differing frame digests, and unavailable-input behavior; M3 verifies
  independent completion, explicit downstream selection, unchanged selection on completion, and
  consumer lineage; M4 verifies both entry points, URL-based switching, pending-save isolation, and
  restart; M5 verifies the existing 0096 queue and reported proposal without accepting frames or
  changing downstream selection.

## M1 — Persist and select reviews

- **Status:** Complete.
- `VisibleCardReviewStore` writes each new review to its own directory. The directory contains the
  manifest, state, draft, command ledger, and exact input lineage. It publishes the directory with
  one atomic rename while holding a recording-scoped creation lock.
- The store lists reviews by update time, then review ID. A review is selected by its ID. The
  active review remains client URL state; the store does not add a shared active-review pointer.
- The existing maintained draft is exposed as `legacy-visible-cards`. Reads include its exact
  state, draft, command ledger, and selected completed revision. They do not write or migrate the
  legacy files.
- Store tests cover two isolated reviews, restart, ID lookup, concurrent creation, duplicate IDs,
  legacy preservation, and interrupted publication.

- Implement review-scoped durable storage and a list of reviews for visible cards. Store each
  draft, command ledger, state, and input lineage independently. Define selection separately from
  the downstream completed-reference pointer.
- Make the existing visible-card draft accessible as a review under the M0 preservation contract.
  Preserve its exact decisions and its selected completed revision. Keep unrelated review stages
  working.
- Test creation of two reviews for one recording, restart, selection, concurrent creation, and
  preservation of an existing draft. Check that a partial write cannot silently replace a review.

## M2 — Scope review creation and commands

- Add review-scoped create, list, read, and draft-command operations. Seed a fresh visible-region
  draft from the selected detector revision or a fresh scene draft directly from the selected
  proposal and its validated inputs. Do not invoke the existing rebase operation for creation.
- Bind every edit, command ID, optimistic revision, and calibration-refinement action to the
  intended review ID. Reject stale or wrong-review requests without changing any draft.
- Test independent edits, duplicate request retries, two reviews from the same proposal, changed
  frame digests, and preservation of ignore and pile regions in the existing review. A new review
  must start with its own unreviewed decisions.

## M3 — Completion and downstream selection

- Publish immutable completed data revisions with the review ID and exact input lineage. Make
  selecting a completed revision explicit. Ensure a later completion does not silently change the
  downstream selection unless the operator explicitly selects it.
- Update consumers that currently infer authority from the single maintained draft, including
  identity annotation, calibration reflow, workspace state, and reference selection. Preserve
  exact lineage and reject stale selection or calibration commands.
- Test two completed reviews, explicit selection and switching, existing selected references,
  downstream input resolution, and isolation of calibration changes to the intended review.

## M4 — Workspace review lifecycle

- Provide the same create, list, select, and resume interaction for visible-region and scene reviews.
  Show the input revision, status, and last update so the operator can distinguish reviews.
- Make “Start review from proposed scenes” create and open a fresh review. A missing optional
  calibration-refinement draft must not prevent opening it. Do not silently rebase another review.
- Scope editor state, queued saves, navigation, and calibration actions to the selected review.
  Prevent pending commands from landing in another review when the operator switches.
- Test both entry points, two drafts from the same input, switching with unsaved or pending work,
  restart, and clear error feedback.

## M5 — End-to-end acceptance and handoff

- Use deterministic local fixtures to exercise creation, edits, switching, restart, completion, and
  downstream selection for both review types. Verify unchanged existing review content and queue
  references. Run relevant backend and frontend tests and applicable static checks.
- Verify the reported recording and proposal with read-only inspection first. When their inputs are
  locally available, create a fresh scene review through the normal interface and confirm that the
  existing review is still selectable and unchanged. Do not accept frames or select a completed
  reference as part of this check.
- Record validation, any unavailable real-input check, and remaining limitations. Do not claim
  detector or scene quality from this workflow change.
