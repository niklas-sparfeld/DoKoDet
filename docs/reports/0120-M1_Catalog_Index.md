# 0120 M1: catalog index and publication contract

Date: 2026-11-10. Baseline revision: `d39b8cddb0acf11e931d43c0815a14e555838c65`.

## Result

M1 adds `RecordingCatalogIndex`, a versioned SQLite projection with per-recording compact
metadata, counters, source-version receipts, and a stable page-order index. Each source publication
stores an atomic pending record that contains the authoritative source value and its compact
projection delta. The index applies one source version at a time in a SQLite transaction. It then
writes the source receipt and clears the pending record. Replays are idempotent. Conflicting source
versions, digests, projections, and recording identities fail visibly.

Recovery reads only the explicit pending-publication directory. A normal metadata read accesses the
catalog database only. It does not inspect source records or history. The explicit offline rebuild
accepts a frozen source snapshot, builds a staged SQLite generation, checks integrity, and replaces
the active index. A missing or corrupt index is an error when source state exists; it does not
trigger reconstruction.

One deterministic fixture adapter in disposable storage proves a source write, metadata read,
restart, replay, pending-publication recovery, and staged rebuild. This adapter validates the common
contract. No production source writer is connected, and `/v1/recordings` remains on its current
reader. M2 remains the first complete API workflow.

## Existing authority and scope

M0 found that node publication receipts and the selection store do not provide list-level recording
metadata, counters, analysis/package counts, or processor-run summaries. Current list readers
enumerate retained source history. The existing job projection index describes Job Manager state,
which is not the source for processor-run status. These authorities cannot meet the bounded-read
requirement. The new catalog remains a derived projection; it does not select pipeline revisions,
replace source authority, or change scheduling.

The catalog contract introduces no source owner beyond the M0 inventory and no second persistent
contract. The planned outbox is one atomic source-plus-projection record. M1 does not perform a
production list cutover or claim that the user-visible growth requirement is complete.

## Checks

The test fixture used disposable `tmp_path` storage. It covers source write/read/restart, identical
replay, conflicting versions and content, crashes after the durable pending record and after index
commit, pending replay, missing/corrupt pending source data, missing/corrupt index, concurrent
readers and writers, explicit rebuild, and a fixed three-row page with ten recordings. The index
uses an exact recording-key read and an ordered SQL `LIMIT` page with a keyset cursor; source history
does not affect the page result size or cursor traversal.

- `mise exec -- uv run --project backend pytest backend/tests/test_recording_catalog_index.py -q`
  — passed, 17 tests after correction 2.
- Combined catalog and M0 growth tests — passed; the M0 test retains 3 strict expected failures for
  list reconstruction scheduled for removal in M6.
- `mise exec -- uv run --project backend ruff check backend/src/dokodetector_backend/recording_catalog_index.py backend/tests/test_recording_catalog_index.py`
  — passed.
- `mise exec -- uv run --project backend ruff format --check backend/src/dokodetector_backend/recording_catalog_index.py backend/tests/test_recording_catalog_index.py`
  — passed.
- `git diff --check` — passed.
- Local Markdown links in the epic, board, glossary, and this report — checked.
- No Python type checker is configured in the backend project or declared in `mise.toml`.

## Progress and next proof

The initial M1 submission was recorded as run progress 2/8. A sanity review found defects in rebuild
from current source versions, switching while readers held a database open, interruption during
the switch, and keyset pagination through `NULL` timestamps. Correction 1/2 changes rebuild to use
the frozen current source version and stages immutable SQLite generations. One atomic active
pointer switch selects the new generation. Old generations remain on disk so open readers can finish;
automatic generation removal is outside M1. Pagination now includes null-timestamp rows after
timestamped rows and continues correctly within the null group.

Correction 1 adds separate regressions for source version 2 rebuild, a reader held open in another
thread during rebuild, failure before the active pointer switch with the prior committed catalog
still readable, and multiple pages containing null timestamps. It also verifies a missing active
generation fails visibly. Existing crash, replay, missing and corrupt source, corrupt index, and
concurrent publication/read tests remain.

Correction 2/2 adds deterministic overlapping reader/writer coverage. A reader holds a SQLite read
transaction while a writer publishes another source contribution. The writer completes during the
reader transaction; the reader retains its original snapshot, and a new read sees the update.

The bounded-page test compares 1x and 10x retained source history for the same one-row catalog.
Both datasets return the same page row, execute the same two catalog SELECTs, and use the ordering
index with `LIMIT`. SQLite virtual-machine instruction counts match. The test confirms that the
source payload contains 1 and 10 history entries respectively; page reads do not read those files.
Existing crash/restart and concurrent-writer coverage remains separate.

Correction 2/2 passed sanity review. Current run progress is 2/8 complete and 6 remaining.
Re-plannings remain 0/10; M0 has one correction and M1 has two. No source owner, persistent
contract, or scope changed. The scope review after the correction limit kept the bounded index
approach: the disposable write/read/restart proof passed, but production list behavior has not
improved. M2 is the exact next proof: real node and selection publication, `/v1/recordings` reads
with old discovery disabled, blocker verification, and restart. Continue only if M2 meets that
acceptance. If it fails, perform scope review before further implementation and add no prerequisite
or contract. The real API workflow is not proved by this report.
