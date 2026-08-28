# Model-improvement contract fixtures

These fixtures document the M0 failure cases used by the operations tests:

- `corrupted-registry.json` has an unknown field.
- `incompatible-data.json` records a candidate on a different split digest.
- `interrupted-candidate-run.json` preserves an interrupted candidate without a checkpoint.
- `partially-promoted-receipt.json` attempts to report promotion without a registry update.
- `stale-campaign.json` points at a champion that is no longer current.
- `recipe-table-analyzer.json` is the checked-in recipe shape for the M3 analyzer adapter. Its
  data paths and digests are replaced by tests that build the plan 0020 smoke fixture.

The fixture payloads are intentionally invalid or incomplete. They must be rejected or reported by
the strict contracts. The passing campaign inputs are built in temporary directories by the tests
so the tests can verify that read-only commands leave every byte unchanged.
