# Epic 0097 M3 frame review handoff

The frame review workflow now stores defer and resume state outside maintained references. Opening a
queue frame records its resume position. The editor records saved-review progress only after its
draft queue is clear. The API checks the queue digest, pinned detector revision, current draft
revision, and an explicit decision for the frame. A failed write leaves the queue item pending. The
queue refreshes saved counts and offers the next pending frame.

The read-only check covered all 165 frozen queue items. All 165 were unavailable in this worktree
because the local revision catalog rejected the retained revision manifests: `content_type` and
`content_schema` did not match. No queue item was edited, deferred, or marked saved during this
check. The queue UI keeps these items visible with their unavailable reason. Repair the local
revision catalog before using this worktree to review those results.

Focused backend workflow tests passed (9 tests). Focused web queue and URL tests passed (21 tests),
and TypeScript, ESLint, Prettier, and generated API checks passed. The frozen queue remains unchanged.
