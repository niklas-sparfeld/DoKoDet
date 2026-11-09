# Epic 0117 M5b1: ordered history index

Date: 2026-11-09

## Result

M5b1 adds a persistent immutable AVL index under each `RecordingHistoryStore` generation. It stores
a separate total order for snapshots, revisions, candidates, and lineage edges. The keys follow M1:
snapshot ID, exact resource kind and ID, and the full lineage source/target identities, edge kind,
role, and item key. Artifact IDs retain namespaced slashes. Resource item keys break duplicate stable
identities into a total order.

Each authority sequence has a small root record. A page at sequence N can therefore use the exact
ordered membership published at N. Later items have a different root and cannot enter an older
cursor traversal, even when their stable key sorts before the continuation key. Index nodes use
content-derived IDs. Publication writes the metadata item, immutable AVL path and sequence root, then
advances the authority as the commit point. The existing publication journal lets restart complete
an interrupted update. Rebuild creates a root for every sequence in a new generation, validates the
items and final order, then switches the active pointer.

The previously committed M5b page route and its full-scan method are removed. M5b2 owns signed
cursors, API continuation, HTTP corruption mapping, and generated response types. M5c still owns
source publication adapters and durable-to-index gap recovery. No source coverage or history API is
claimed here.

## Historical-root validation correction

Rebuild now simulates each ordered publication in an in-memory node overlay and requires each
stored sequence root to equal the exact expected prefix. It then validates every node reachable
from any historical root, including nodes that later rotations no longer use. This prevents a
missing historical-only node or a checksum-valid root with incorrect historical membership from
passing generation validation. Both regressions verify that rebuild leaves the prior active
generation unchanged when validation fails.

A temporary 256-item local probe produced 2,296 immutable AVL nodes, 257 sequence-root files, and
816,428 index bytes. This is an observed fixture cost, not a production storage estimate.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_recording_history_order_index.py backend/tests/test_recording_history_store.py backend/tests/test_recording_state_contract.py backend/tests/test_recording_state_workflow.py` — passed, 51 tests.
- Tests cover every collection order, complete lineage-key continuation, frozen membership with a later earlier-sorting insertion, bounded AVL-node and item-metadata reads at 256 entries, order corruption, exact-prefix rebuild validation, missing historical-only node rejection, checksum-valid wrong-prefix rejection before activation, publication and rebuild, actual child-process death after item, index-root, and authority publication, restart, and disabled API route.
- Ruff check and format check passed for changed Python files.
- `cd web && npm run generate:api && npm run verify:api` — passed; generated types contain no history page route.
- `git diff --check` and local Markdown link checks passed.
- Source adapters and durable-to-index gap recovery remain with M5c.
