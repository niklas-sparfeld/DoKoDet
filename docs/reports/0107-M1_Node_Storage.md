# 0107 M1: node storage

The new `PipelineNodeStore` stores named nodes with exact source references and validated content.
Each node has an immutable manifest, immutable revisions, and an atomic working-head pointer.
A save compares the expected head under an interprocess lock. A content no-op returns the current
revision. Historical reads follow the committed parent chain; an interrupted head update cannot
expose an unpublished revision. Each revision records its content digest, metadata, and timestamp.

The store accepts the existing events, visible-card, visual-identity, table-observation, and proposed
scene content contracts. It validates the source and uses the source duration for event validation.
It is separate from existing runtime stores and does not change processor input selection.

M1 does not implement accepted-use protection, automatic copies, review decisions, graph queries, or
migration. In particular, do not connect this store to production processing before M3 provides the
shared edit and accepted-use transaction boundary. Interrupted writes can leave unreachable revision
directories; they are not visible through history or exact reads. Later recovery work must account for
them.

Verification: `backend/.venv/bin/python -m pytest backend/tests/test_pipeline_node_store.py
backend/tests/test_pipeline_store.py` passed 23 tests. The focused node tests cover restart, no-op,
content validation, historical reads, stale and concurrent writers, and interrupted head publication.
Ruff check and format passed for the new implementation and tests.
