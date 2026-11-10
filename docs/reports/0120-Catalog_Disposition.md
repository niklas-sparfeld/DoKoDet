# 0120: catalog disposition

Date: 2026-11-10. Baseline: `53066a1d`. This is the authorized catalog disposition,
not a list performance delivery or an M3 correction.

## Decision and retained data

Remove the derived catalog index, its publication protocol and processor-run intent,
the writer hooks, startup recovery and test-only list reader. Keep the authoritative
recording, node, selection, processor-run, analysis and package stores. Keep the node
revision-history outbox and its startup reconciliation. Keep selection-only coordinated
transactions and their recovery journal. No retained catalog or source data is deleted.

Before this change, the production list used source stores. The new index did not contain
all source families. Its removal does not remove a production list improvement. The
pending intent defect in M3 is not fixed or accepted. It is superseded with the removed
processor-run intent; the original correction history remains in the epic and M3 report.

The default `data/operations` in the main checkout had no `recording-catalog` directory
when inspected. The secondary checkout has an empty catalog outbox created during this
work's initial test setup. That test initially used the checkout's default operations root
because `storage_root` is a settings alias; it created and removed only its own test
pending file. The test now uses `DOKO_STORAGE_ROOT` and disposable storage. Other storage
roots were not inventoried. No claim is made about their contents or active writers.

A retired catalog outbox that is nonempty, a symlink, or not a directory blocks backend
startup and remains untouched. Do not delete it to clear the error. Stop writers; save a
recovery copy of the catalog and corresponding source stores; inspect each pending record
and the named source and node transaction journals. Reconcile the authoritative source
operation and validate it independently before moving pending evidence out of the active
outbox. The historical code at `53066a1d` can assist inspection on a disposable copy, but
its M3 invalid-path recovery defect means it is not an automatic reconciliation tool.
This procedure needs a case-specific check if pending records exist. Empty or absent
outboxes need no data conversion; old index generations and receipts remain on disk.

## Verification boundary

The retained growth fixture continues to expose the three expected failures for bounded
response and source reads. The standalone selection interruption test now verifies source
journal recovery and identical retry; existing coordinated process-death tests retain
separate locator, journal, head, publication, selection and commit boundaries. Catalog-only
projection and intent tests were removed with those contracts. Processor-run source tests
and real persisted round-analysis API tests remain. No runtime catalog generation or source
file was removed by this change.

The follow-up source-authority list improvement and any history-independent summary remain
unimplemented and require new authorization. The proposed stop decision and cumulative
history are in the [active epic](../plans/5-closed/0120-Recording_Catalog_Performance.md).

Checks on the disposition change: the targeted selection, coordinated transaction,
processor-run store, lineage, growth-contract, round-analysis API and retired-outbox tests
passed; the growth contract retained three strict expected failures. Ruff and format checks
on changed Python sources and tests, and `git diff --check`, passed. The tests used local
fixtures and disposable persisted storage except for the initial test setup noted above.
The only test warning was the existing Starlette/httpx deprecation warning.
