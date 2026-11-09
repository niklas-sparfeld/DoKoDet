# 0117 M5c1: node revision history publisher

## Result

M5c1 connects recording-owned `PipelineNodeStore` revisions to the M5a history authority. Each
writer records a pending outbox entry before it commits a revision. It includes the recording,
node, revision, schema, and content digest. Node creation, ordinary save, and coordinated
transactions use this entry. History publication is idempotent. The outbox clears only after the
M5a item is durable.

The history API first recovers the named coordinated transaction, then replays pending revision
entries. Reconciliation reads only the outbox, node manifest and HEAD, and revision publication
authority. It does not parse revision content. It does not scan all revisions on each page. Missing
revision data alone does not prove that a write stopped before source commit. If HEAD or publication
authority identifies the revision as committed, reconciliation fails closed and retains the intent.
It drops a missing source only when there is no commit evidence. If HEAD advanced before publication
authority was written, recovery restores that authority from the exact outbox record before it
publishes history.

Corrections 1/2 and 2/2 harden failure paths. Reconciliation drops an intent for a missing node or
revision only when no commit evidence exists. It also drops a complete revision that has neither
publication authority nor the node HEAD. An existing unreadable node now fails closed and keeps the
outbox for repair. An ordinary save rejects an occupied revision or publication path before it
writes a new outbox intent, so a failed duplicate-ID save cannot poison later reconciliation. A
missing or malformed revision path with HEAD or publication evidence fails closed. Tests cover both
committed-evidence cases and safe removal of an uncommitted missing revision.

## Source and meaning

The authoritative source for this collection is the durable, published pipeline node revision. A
revision becomes eligible when its publication authority exists, or when its HEAD commit is durable
and its outbox record can complete that authority. Each history item points to the exact node and
revision, content schema, and digest.

The separate `candidates` collection remains unresolved. The web UI has no consumer for its
endpoint. Current UI uses of “candidate” refer to embedded card or identity proposals and comparison
values. These are not independent exact persisted resources. The possible meanings are all
pipeline revisions, which duplicates `/revisions`; successful or partial lineage run outputs; or
embedded proposals, which do not fit the exact-resource contract. This milestone does not select a
meaning or populate the candidates collection. M5 discovery remains incomplete.

## Verification

- `uv run --project backend pytest -q backend/tests/test_pipeline_node_uses.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_recording_history_api.py backend/tests/test_recording_history_store.py` — passed.
- Tests cover idempotent replay after history commit, recovery after node HEAD commit but before history publication, a coordinated two-node transaction, concurrent writers, and real history API recovery. The API regression rejects revision-content reads during reconciliation. Correction regressions verify corrupt-node outbox retention, duplicate-ID rejection before intent creation, committed-revision retention when source content is missing, and safe removal of uncommitted missing revisions.
- `uv run --project backend ruff check backend/src/dokodetector_backend/pipeline_node_store.py backend/src/dokodetector_backend/pipeline_node_transactions.py backend/src/dokodetector_backend/recording_state_api.py backend/tests/test_pipeline_node_uses.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_recording_history_api.py` — passed.
- `uv run --project backend ruff format --check backend/src/dokodetector_backend/pipeline_node_store.py backend/src/dokodetector_backend/pipeline_node_transactions.py backend/src/dokodetector_backend/recording_state_api.py backend/tests/test_pipeline_node_uses.py backend/tests/test_pipeline_node_transactions.py backend/tests/test_recording_history_api.py` — passed.
- `git diff --check` — passed.
- OpenAPI generation and browser checks do not apply. The history route schema did not change and no web consumer uses it.

## Limits and next work

This publisher covers pipeline node revisions only. M5c2 must connect immutable recording snapshots.
M5c3 must connect terminal lineage records and edges. Candidate semantics require an explicit
product decision before M5 discovery or the candidates endpoint can be called complete. The run
still has 10 milestones remaining under its 14-milestone cap. Replan 7 moves M14 and M15 outside
this run; M16 was already outside it.
