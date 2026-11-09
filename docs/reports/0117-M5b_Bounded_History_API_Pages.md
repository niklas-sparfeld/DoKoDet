# Epic 0117 M5b: bounded history API pages

Date: 2026-11-09

## Superseded first implementation

The first implementation added `GET /api/recordings/{recording_id}/state/history/{collection}`. Review
found that it ordered by insertion sequence, used unsigned base64 cursors, and parsed every metadata
item on each request. These behaviors violate M1's stable-key order, cursor integrity, and bounded
page read requirements.

Commit `475f011f` remains historical evidence and is not accepted as M5b completion. Replan 6 splits
M5b into M5b1, the ordered immutable index contract, and M5b2, the M1-compliant API. The route and
full-scan method are disabled until M5b2. M5c remains responsible for snapshot, revision, candidate,
and lineage source publishers and durable-to-index crash-gap reconciliation.

The initial API tests and checks passed, but they did not test M1 ordering or bounded index reads.
They do not qualify the API. M5b1 records the replacement store checks in its own report.
