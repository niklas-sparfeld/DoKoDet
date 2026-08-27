# Shared repository intake contract

The shared intake contract stores one immutable source asset and its recording metadata. It keeps
task enrollment separate from source identity. The contract is frozen as version 1 in these JSON
schemas:

- [`repository-bundle/v1`](../schemas/repository-intake/repository-bundle-v1.schema.json) describes
  the complete commit-ready bundle and hashes every member file.
- [`source-record/v1`](../schemas/repository-intake/source-record-v1.schema.json) records source
  identity, permission, retention, and measured byte identity.
- [`task-enrollment/v1`](../schemas/repository-intake/task-enrollment-v1.schema.json) records one
  disposition for each supported data task: `selected`, `deferred`, or `excluded`.
- [`proposal-generator-run/v1`](../schemas/repository-intake/proposal-generator-run-v1.schema.json)
  records proposal model, configuration, execution, probability, and event-proposal lineage.

The two supported data tasks are `cardevent_event_detection` and `table_evidence_analysis`. Each
initial enrollment starts with its own lifecycle state of `intake`. A selected source still needs
annotation and review before it can become eligible. A deferred source has no review work. An
excluded enrollment records a reason and uses the `excluded` lifecycle state.

Proposal generator output has `purpose: proposal_only`. It records source lineage and an output
digest, but it has no dataset-membership field and cannot make a source eligible for either task.
Changing an enrollment document does not change the source record or its source bytes.

The replacement fixture set in
[`fixtures/repository-bundle/v1/`](../fixtures/repository-bundle/v1/) contains one source selected
only for CardEventNet, one source selected only for TableEvidenceAnalyzer, and one source selected
for both. Swift, backend, and CardEventNet tests decode the same files and reject unknown fields,
legacy aliases, invalid dispositions, and mismatched lineage.
