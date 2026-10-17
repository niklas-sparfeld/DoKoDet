# Frame review mode

## Plan status

- **Status:** In Progress
- **Depends on:** 0096 M4 frozen queue and existing 0049/0074 maintained-reference editor.
- **Outcome:** An operator can resume a cross-recording list of frames to review and save decisions
  through the existing editor. Implementation does not require new human review.

## Milestone status

- **M0:** Complete — validated frozen queue projection and explicit saved-review receipt rules.
- **M1:** Complete — expose bounded queue pages, counts, exact editor targets, unavailable reasons,
  receipt status, and persisted queue-only deferral and resume position through the backend API.
- **M2:** Complete — add the frame list, filters, progress, and exact-result editor navigation.
- **M3:** Not started — add resume, defer, and saved-review progress; verify the complete workflow.

## Scope and boundaries

The [0096 queue](../../reports/0096-M4_Human_Review_Queue.md) already freezes 165 frames across
33 reviewable recordings and one recording with a dependency failure. Reuse its selection and
reasons. This epic makes that queue usable in the web app; it does not select more review work.
0096 M4 remains awaiting human review until actual review evidence exists.

Use the existing maintained references as the only authority for human decisions. Queue membership,
navigation, and deferral are operator workflow state. They must not create another reference,
accept a proposal, mark a viewed frame reviewed, or replace an existing draft. No model execution,
training, identification, or reconstruction belongs here. Later identity queues can use the same
queue boundary without adding identity controls in this epic.

This delivers the reusable navigation part of 0044 M0. Coverage-based identity prioritization,
datasets, campaign UI, promotion, and rollback remain in 0044. Do not implement a second priority
engine or require 0044 to start this epic.

## M0 — Define queue items and progress

Adapt the frozen 0096 manifest into a small versioned queue contract. Each item records queue ID
and digest, recording, stage, source/frame identity, exact generated revision, scene run/revision
when available, comparison reference, selection reasons, and eligibility. Keep the frozen queue
immutable. Validate digests, duplicate frame keys, protected comparison sources, and missing results.

Define pending, deferred, saved review, and unavailable presentations. A saved-review state requires
existing explicit review coverage and a receipt that applies to the exact item and result lineage.
An old completed reference used as an M3 comparison does not establish review of a new proposal.
If existing receipts cannot express that distinction, add only the minimum workflow receipt that
links to canonical saved decisions; do not duplicate their geometry or acceptance state.

M0 defines `frame-review-queue/v1` as a projection of the immutable 0096 M4 manifest. The queue
digest is the manifest's `selection_sha256`. Each projected item uses `(recording_id, item_id)` as
its unique frame key because event IDs can repeat across recordings. It pins the visible-card
revision and digest, optional scene run and revision, comparison reference, reasons, and separate
review and comparison eligibility. A calibration failure can still be reviewed when its detector
revision exists. Training-overlap frames remain reviewable but cannot contribute comparison
evidence.

An item is **saved review** only when a `frame-review-receipt/v1` links the queue digest and item to
the exact result lineage, a current maintained-reference draft revision, and one or more decision
item IDs in that draft. This records partial saved decisions; it does not claim full-frame coverage
or published-reference completion. A comparison reference alone, including an old completed
reference, leaves the item pending. A stale receipt or missing pinned result is unavailable.
Deferral changes only queue workflow state.

Acceptance: fixture tests cover partial-frame review, old reference versus new proposal, stale
result lineage, missing artifacts, and unrelated live drafts. Opening or deferring an item never
changes canonical review state. Define when a saved draft counts as saved review and distinguish
it from a published completed reference.

## M1 — Expose queue and progress

Add a backend projection over the manifest and existing review receipts, with generated API types.
Return bounded pages, counts by state and reason, exact editor targets, and actionable unavailable
reasons. Record only queue-specific deferral and resume position outside the maintained reference.
Resolve protected-source eligibility before media access. Avoid per-item full artifact decoding
when a recording-level projection can serve the page.

Acceptance: deterministic ordering and counts survive restart; unavailable items remain visible;
mutations validate item and queue identity. Tests show that queue requests cannot seed, reset, or
overwrite an existing draft. Unknown or changed lineage becomes actionable unavailable state.

M1 adds `GET /api/frame-reviews/0096-M4` and a queue workflow update endpoint. The GET response
uses the frozen selection digest, pages items in manifest order, counts every state and selection
reason, and returns pinned editor targets. It checks revision manifests before returning a target.
Missing, changed, or unrelated revisions remain visible as unavailable with an action. Valid saved
receipts count only when their result lineage, current maintained draft revision, and decision IDs
still match. Queue deferral and resume position are stored under `data/operations` outside the
maintained reference. The projection reads revision manifests once per request and loads each
referenced draft at most once.

## M2 — Add list and editor navigation

Add a Review mode with a To review frame list, thumbnails, recording names, selection reasons,
pending/deferred/saved/unavailable filters, and progress. Open the pinned generated result and
frame in the existing editor. Show a calibration failure when only detector output exists.
Add previous/next navigation across recordings and a clear return to the list.

Do not automatically execute the queue's `start_review=proposal` links. Opening an item must be
read-only until the existing review action applies. If a live draft targets another revision,
explain the conflict and preserve it. Do not silently rebase the draft. Distinguish review of the
pinned result from a newer selected result.

Acceptance: component fixtures cover navigation across recordings, selection changes, missing
scene output, and draft conflicts. Thumbnails and list actions are keyboard accessible.

M2 adds the `/frame-reviews/0096-M4` page. It shows frame rows, recording thumbnails, selection
reasons, state filters, and queue progress. Available items open their pinned generated revision in
the maintained-reference editor. The editor shows previous/next queue navigation and a direct return
to the list. It labels detector-only results, identifies when the current generated selection has
moved past the pinned result, and warns when the maintained draft targets another revision. Opening
an item does not start a proposal review or change the maintained draft.

## M3 — Resume and verify the workflow

Add explicit defer and resume controls. After the existing editor confirms a saved review, refresh
progress from its authoritative receipt and offer the next pending frame. Wait for pending writes;
failed saves retain the item as pending. Reload and restart preserve resume position and deferral.

Acceptance: automated integration tests exercise open, edit, save, failure, defer, reload, and next
across two fixture recordings. Counts distinguish saved draft decisions from published reference
completion. Verify the 165-item real queue read-only without making human decisions. Publish a
short handoff; 0096 review completion remains unchanged. No user availability is required to close
this software epic after fixture and read-only verification.

## Verification

Run focused backend, frontend, generated-type, and queue/progress tests, applicable formatting and
static checks, local Markdown link checks, and `git diff --check`. Include save-race and reference
preservation regressions. Do not require a manual review session for implementation acceptance.
