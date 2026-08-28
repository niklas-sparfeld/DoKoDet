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

## Pending uploads

A pending upload is a source upload that has not yet become a complete repository intake bundle.
Store it below:

```text
data/incoming/videos/<upload-id>/manifest.json
data/incoming/videos/<upload-id>/<original-filename>
```

The receipt uses [`pending-video/v1`](../schemas/repository-intake/pending-video-v1.schema.json).
It records the upload identifier, original filename, byte length, SHA-256 digest, measured media
facts, receive time, and completion state. It does not invent a session, permission, scenario, or
task enrollment. A pending upload is not visible to review or dataset assembly.

Complete one pending upload with strict operator metadata and both independent task enrollments:

```bash
mise exec -- uv run --project operations doko data complete-video \
  --repository-root . --upload-id <upload-id> --metadata completion.json
```

The operation copies the source bytes into a private recording bundle, validates the full bundle,
and publishes it by atomic rename. A failure leaves the pending upload unchanged. A success leaves
one recording source copy and keeps its digest unchanged.

## Evidence-package intake

An accepted evidence package is a complete source bundle at:

```text
data/intake/evidence-packages/<package-id>/
```

The bundle uses
[`evidence-package-bundle/v1`](../schemas/repository-intake/evidence-package-bundle-v1.schema.json)
and has this fixed layout:

```text
manifest.json
evidence-manifest.json
package-record.json
initial-task-enrollment.json
lineage.json
frames/<part-name>.jpg
video/<part-name>.mp4                  optional
```

`manifest.json` hashes every member. The evidence manifest is the original
`cardevent-evidence/v2` document. The package record supplies permission, allowed uses, retention,
and source identity. The enrollment document has one independent entry for each supported data
task. Lineage links the package to its parent recording and source asset when known. The source
files remain in this shared bundle; task adapters read them in place.

The backend rebuilds its searchable package index from these bundles at startup. Removing backend
runtime state cannot remove an accepted source package. Use the operations command below only for
one-time adoption of a package from the old runtime path:

```bash
mise exec -- uv run --project operations doko data adopt-evidence \
  --repository-root . --runtime-root backend/.runtime \
  --package-id <package-id> --metadata package-metadata.json
```

The adoption operation validates all source bytes and metadata, publishes one canonical bundle, and
keeps the old runtime package until the operator verifies the result. It is not a permanent
second intake path.
