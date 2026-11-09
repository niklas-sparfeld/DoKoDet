# Epic 0117 M4a: node revision publication authority

**Review status:** M4a is incomplete. Final review found that the root lock is released between recovery and reads, and selection writes can take locks in the inverse order from recovery. The epic handoff records the required interleaving tests.

Date: 2026-11-09

## Result and review status

M4a is complete for direct node authority lookup and serialized writers. It does not claim bounded
total read work. `read_authorized_revision` calls `recover_transactions`, which enumerates and
validates every committed transaction journal. M4b owns bounded journal recovery. The exact-read
test measures revision reads only; it does not prove bounded total read work.

Added durable publication records for pipeline node revisions. Each record uses schema
`pipeline-node-publication/v1` and stores the node ID, revision ID, and content digest at
`<node>/publications/<revision_id>/authority.json`.

`PipelineNodeStore.create` publishes the initial revision, HEAD, and authority record in one
staged node directory. `save` writes the immutable revision, confirms authority for the previous
HEAD, atomically replaces HEAD, and then publishes authority for the new revision. The per-node
process lock serializes node publication. The root transaction lock serializes saves, coordinated
transactions, recovery, and other store writers across threads and processes. The HEAD replacement is the commit
point. If a process stops before that replacement, the new revision is an orphan and direct
authority reads reject it. If a process stops after that replacement but before the new authority
record, the exact current HEAD and validated revision remain sufficient authority. The next writer
records authority for that HEAD before it advances the pointer.

Coordinated node transactions apply the same publication order during journal recovery. Readers
recover prepared transactions under the root transaction lock before the direct read. Recovery rolls a prepared transaction forward
and publishes the authority records before it marks the journal committed. A direct authority read
validates one receipt and one revision, or validates the exact current HEAD and one revision when a
receipt is absent after a process stop. It does not read parent revisions.

Public exact reads reject unpublished orphans. The private edit-recovery helper can inspect a raw
revision to decide whether a failed edit can be retried safely; it does not publish or accept that
revision.

## Reader and writer inventory

The updated node row in the [M0 inventory](0117-M0_Post_Cleanup_Baseline.md) lists current paths,
schemas, readers, writers, and checks. The storage writers are `PipelineNodeStore.create` and
`save`, plus `PipelineNodeTransactions` recovery. Processor, calibration, edit, copy, restore, and
migration writers use these store paths. The new `read_authorized_revision` method is the bounded
authority-lookup reader; M4b must bound the transaction recovery that runs before it.

The focused calibration service check also exposed a missing-revision probe that raised `KeyError`
instead of continuing to the next node. The scan now handles that missing result.

Existing runtime readers still use `read_published_revision`, which follows parent links. This
milestone does not switch those readers or convert retained data. M4c will prove the replacement
workflow with the direct read and M4b bounded recovery. M12 must rehearse authority records for
retained revisions and keep review and accepted-use dependencies. It must report revisions whose
publication cannot be proven.
M13 can switch existing readers only after that rehearsal passes.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_pipeline_node_edits.py backend/tests/test_pipeline_node_uses.py backend/tests/test_pipeline_node_reviews.py backend/tests/test_pipeline_node_edit_api.py backend/tests/test_recording_state_workflow.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_store.py backend/tests/test_recording_state_publication.py backend/tests/test_0117_workspace_growth_fixture.py backend/tests/test_pipeline_lineage_writer.py backend/tests/test_calibration_refinement_service.py` — 96 passed.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/pipeline_node_store.py backend/src/dokodetector_backend/pipeline_node_transactions.py backend/src/dokodetector_backend/pipeline_node_edits.py backend/src/dokodetector_backend/calibration_refinement_service.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_transactions.py` — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/pipeline_node_store.py backend/src/dokodetector_backend/pipeline_node_transactions.py backend/src/dokodetector_backend/pipeline_node_edits.py backend/src/dokodetector_backend/calibration_refinement_service.py backend/tests/test_pipeline_node_store.py backend/tests/test_pipeline_node_transactions.py` — passed.
- Exact-authority lookup growth test reads one revision record after revision history grows to 11 entries. It does not count transaction journal reads; M4b must add that proof. Separate-process reader/writer test reads committed HEAD revisions while the writer publishes 20 more revisions. A separate two-writer process test confirms one stale HEAD update fails.
- Separate-process crash tests stop after revision creation, previous-revision authority, HEAD replacement, and new authority publication. They confirm orphans remain unreadable and committed HEAD revisions remain readable after restart. Coordinated transaction crash tests stop after HEAD and authority publication; a new store recovers both nodes and their authorities from the prepared journal.
- Two deterministic separate-process interleavings pause coordinated commit after plan validation
  and after prepared-journal publication. An ordinary save signals its attempt to acquire the same
  store transaction lock and remains blocked. After release, the transaction commits, the save
  rejects its stale expected HEAD, and subsequent reads succeed. The lock order is store transaction
  lock, recovery or transaction preparation, then per-node lock.
- Recovery takes the same reentrant root transaction lock. The lock uses a per-root thread lock and
  one cross-process file lock per outer entry. Nested operations reuse the held lock. Recovery
  reentrancy is thread-local, so another thread cannot skip recovery while a prepared transaction
  is only partly applied.
- A same-instance thread test pauses recovery after the first node HEAD update and proves a second
  thread cannot read the second node until recovery completes. A separate-process test proves the
  same behavior across processes. Both readers return the second node's committed revision.
- The interleaving test ran three additional times; both pause points passed on every run.
- Correction 2/2: `uv run --project backend pytest backend/tests/test_pipeline_node_*.py -q` — 50 passed.
  This includes a same-instance thread test and a separate-process test that pause prepared-journal
  recovery after the first node HEAD update. In both cases, a reader of the second node waits and
  returns only after the complete transaction recovers. Ruff check, Ruff format check, and
  `git diff --check` passed for all changed backend paths.
- Local Markdown links and anchors for changed documentation — passed. `git diff --check` — passed.

One existing Starlette `httpx` deprecation warning appears in the API test. M4a changes no API schema, web consumer, or UI; API generation and browser checks do not apply. No type-check command is configured in the backend toolchain.

## Limits

The direct authority method is implemented and tested, but existing production readers are not
switched in M4a. Authority creation for retained data is not rehearsed here. Process-death tests
cover each atomic boundary, but do not simulate termination inside the filesystem's atomic rename.
