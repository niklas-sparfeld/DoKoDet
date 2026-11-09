# Epic 0117 M4b: bounded transaction recovery

## Result

M4b adds a durable locator for the only coordinated transaction that can need recovery. Exact
node and selection reads no longer enumerate committed transaction history. Committed journals
stay in place for direct transaction-ID replay checks. Recovery remains idempotent and rolls a
prepared transaction forward before a reader returns.

## Storage and lock contract

The locator is `.coordinated-transactions/pending.json`, schema
`pipeline-node-pending-transaction/v1`. An active record carries the transaction ID and request
digest. An empty record has null values for both fields. The writer holds the root transaction
lock and atomically publishes the active locator before it atomically publishes the prepared
journal. This order means a crash before journal publication leaves an empty target that recovery
can clear. A crash after journal publication leaves a locator that names the prepared journal.

The root lock serializes ordinary node writers, selection writers, coordinated writers, exact
readers, and recovery across threads and processes. Recovery reads the locator, then at most its
named journal. It applies node revisions, node HEADs, publication authority, and selections in the
existing order, marks the journal committed, then atomically clears the locator. Repeating recovery
after a crash at any boundary is safe. A missing locator means no recovery work. A malformed
locator or a digest mismatch fails closed.

Committed transaction lookup remains a direct `transaction_id.json` read. The existing request
digest check returns the committed result for an exact replay and rejects reuse of that ID for
different updates. Old committed journals are not scanned or removed.

## Verification

- `mise exec -- uv run --project backend pytest -q backend/tests/test_pipeline_node_transactions.py` —
  passed, including six process-death points (locator, journal, node HEAD, publication authority,
  selection, and committed journal), restart recovery, same-ID replay and conflicting reuse.
- A growth test with 100 committed journal files observed zero journal reads during exact current
  revision lookup.
- Existing recovery fixtures verify a pending prepared journal is completed before node and
  selection reads. Existing deterministic same-instance and separate-process contention tests
  verify that readers and writers serialize on the root lock.
- Ruff check, Ruff format check, and `git diff --check` — passed.

Retained data and existing readers are unchanged. M12 must rehearse creation of publication
authority and pending locators for retained state before M13 changes reader routing.
