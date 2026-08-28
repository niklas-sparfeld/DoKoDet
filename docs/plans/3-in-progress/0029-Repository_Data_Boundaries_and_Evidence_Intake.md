# DokoDetector Repository Data Boundaries and Evidence Intake

## Plan status

- **Summary:** Keep shared source intake at the repository root, stage incomplete video uploads
  before intake, and make accepted evidence packages durable pipeline inputs
- **Status:** In Progress
- **Depends on:** Completed plan 0027
- **Builds on:** Plans 0020 and 0027 provide source identity, lineage, task enrollment, lifecycle,
  repository intake, and review operations
- **Reviewed:** 2026-08-28 against plan 0027 and the current backend, operations, CardEventNet, and
  evidence-package storage paths
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Outcome

Create clear storage boundaries based on ownership and completeness:

```text
data/
  incoming/videos/<upload-id>/
  intake/recordings/<recording-id>/
  intake/evidence-packages/<package-id>/
  operations/

card_event_net/data/             task-specific data and derived artifacts
table_evidence_analyzer/data/    task-specific data and derived artifacts
backend/.runtime/                disposable and rebuildable backend state
```

The repository-root `data/intake` directory is the only writable local authority for shared,
complete source bundles. Component data directories can keep task-specific annotations, datasets,
splits, caches, and runs. The backend does not own a second intake directory.

A video with incomplete operator metadata stays under `data/incoming`. It is not intake and no data
task can discover it. A completion operation creates one validated recording bundle without
changing the source digest.

An accepted evidence package must not exist only under `backend/.runtime`. A complete package
becomes an immutable repository intake bundle. It can then enter either data task through explicit
task enrollment and human review.

## 2. Fixed decisions

### 2.1 Resolve shared paths from the repository root

Backend defaults must not depend on the process working directory. Use the same explicit
repository-root resolution as the operations package, or require an absolute configured path.

In local development, these two commands must address the same intake:

```text
backend repository upload -> <repository-root>/data/intake
doko data status          -> <repository-root>/data/intake
```

Do not move historical component data only to make directory names uniform. Remove any active
`backend/data/intake` path after its accepted bundles are moved or verified elsewhere.

### 2.2 Keep incomplete uploads outside intake

Add a durable, Git-ignored pending-video area at `data/incoming/videos`. Each upload records an
upload identifier, original filename, byte length, SHA-256 digest, measured media facts, receive
time, and completion state. It does not invent session, permission, scenario, or task-enrollment
metadata.

Provide one operator operation that supplies the missing metadata and task enrollments. It must
publish a normal plan 0027 recording bundle atomically. A failure leaves the pending upload intact.
A success leaves one authoritative source copy and preserves its digest.

Pending uploads appear in `doko data status` and `doko data validate`, but never in review,
dataset, split, or model inputs.

### 2.3 Store complete evidence packages as shared source bundles

Add a strict evidence-package repository bundle. It contains:

- a repository manifest with the digest of every member;
- the original evidence manifest, selected frames, and optional video snippet;
- source permission and retention metadata;
- independent initial enrollment for both data tasks;
- lineage to the parent recording and source asset when known.

Store the bundle at `data/intake/evidence-packages/<package-id>`. Keep identifier and digest
identity independent from the local path. If a package lacks required operator metadata, store it
as pending input until an operator completes that metadata.

Capture does not label a package as positive or negative. CardEventNet event truth and visible-card
evidence come only from their respective reviews. A rejected event proposal can still contain
useful table evidence.

### 2.4 Keep runtime state disposable

After this epic, deleting `backend/.runtime` can remove SQLite indexes, temporary uploads, caches,
and reproducible analyzer outputs. It must not remove the only copy of an accepted source.

Provide one explicit adoption command for valuable evidence packages stored by the old runtime
path. The command validates bytes, requests missing metadata, writes new intake bundles, and
reports conflicts. Do not retain a permanent dual-reader or a second writable evidence authority.

## 3. Implementation work

### M0 — Paths and contracts

1. Add repository-root-aware backend path configuration and tests that start the service from the
   repository root and from `backend/`.
2. Freeze strict pending-video and repository evidence-package bundle schemas.
3. Add matching typed models and conformance fixtures in Swift, backend, operations, and relevant
   component packages.
4. Extend Git ignore and Git LFS rules for pending and accepted media at every required depth.

### M0 implementation evidence — 2026-08-28

- Backend settings resolve SQLite, runtime, and repository intake paths from the nearest repository
  root, whether the service starts from the repository root or `backend/`.
- Strict pending-video and evidence-package schemas are frozen under
  `schemas/repository-intake/`.
- Backend, operations, CardEventNet, TableEvidenceAnalyzer, and Swift decode shared conformance
  fixtures. The backend and Swift validators also verify package member digests and exact layout.
- Git ignore and Git LFS rules cover pending upload media and accepted evidence-package media.
- Verification passed: backend 94 tests, operations 29 tests, TableEvidenceAnalyzer 23 tests,
  CardEventNet 231 tests with one skip, and Swift repository-intake conformance tests.

### M1 — Pending video completion

1. Add bounded, atomic raw-video upload storage under `data/incoming/videos`.
2. Probe technical media facts and store the pending-upload receipt.
3. Add the operator completion operation and atomic promotion into recording intake.
4. Extend status and validation with pending, invalid, and ready-to-complete results.

### M1 implementation evidence — 2026-08-28

- Added `PUT /v1/pending-videos/{upload_id}`. The route streams one bounded video below
  `data/incoming/videos`, probes H.264/MP4 facts with FFprobe, writes a strict receipt, and
  publishes the upload directory by atomic rename.
- Added idempotent pending-video retries and conflict protection. A failed probe, size check, or
  interrupted write leaves no final pending directory.
- Added `doko data complete-video`. It validates strict operator metadata and both task enrollments,
  copies the source bytes into a private recording bundle, validates the bundle, and promotes it by
  atomic rename. It removes the pending upload only after successful promotion.
- Extended `doko data status` and `doko data validate` with pending-video receipt, byte-integrity,
  invalid, and ready-to-complete results.
- Verification passed: backend 100 tests, operations 34 tests, backend and operations Ruff check and
  format checks, and JSON parsing for the new completion schema.

### M2 — Evidence-package intake

1. Change accepted evidence-package storage from runtime-only storage to the repository bundle.
2. Include collection metadata, task enrollment, permission, and lineage in the producer and upload
   contract.
3. Rebuild searchable backend state from accepted package bundles.
4. Extend the operations and both task adapters created by plan 0027 to discover selected evidence
   packages.
5. Add the one-time runtime adoption command. Remove the active runtime-only authority afterward.

### M2 implementation evidence — 2026-08-28

- Accepted evidence packages now use immutable repository bundles under
  `data/intake/evidence-packages/<package-id>`. Backend writes are atomic and include member
  digests for the manifest, operator metadata, frames, and optional video snippet.
- The iOS producer and multipart upload contract include package record, initial task enrollment,
  and lineage documents. Both task enrollments are explicit and independent.
- Backend startup rebuilds the searchable package and frame state from canonical intake bundles.
  Runtime deletion does not remove accepted package source bytes.
- `doko data status` and `doko data validate` inspect canonical evidence packages. The table and
  CardEventNet adapters discover only packages that select their respective task.
- Added `doko data adopt-evidence` (and `adopt-evidence-package`) for one-time migration from the
  old runtime evidence path. The command preserves the old package until the operator verifies
  the new bundle.
- Verification passed: backend tests, operations tests, TableEvidenceAnalyzer tests, CardEventNet
  tests, Python compile checks, Ruff checks and formatting, and Swift package build. The full Swift
  test command remains blocked by pre-existing strict-concurrency errors in
  `TrainingRecordingUploadQueueTests.swift`.

### M3 — Documentation and clean-room verification

1. Define the canonical term for a pre-intake upload in `docs/glossary.md` before using it in other
   public documentation.
2. Update `README.md`, `backend/README.md`, `DATA_CONTRACT.md`, `SERVER_CONTRACT.md`,
   `docs/Repository_Intake_Contract.md`, `docs/Data_Lifecycle.md`, and affected component guides.
3. Do not rewrite closed epic 0027. Record the new architecture in current guides and this epic.
4. Run one clean-room test for raw video completion and one for live evidence-package capture,
   backend restart, review discovery, and runtime deletion.

## 4. Acceptance

- Backend startup location cannot create `backend/data/intake` accidentally.
- A raw video can survive restart, report its incomplete state, and later become one valid recording
  bundle without a digest change.
- No incomplete upload is visible to review or dataset assembly.
- An accepted evidence package survives backend runtime deletion and SQLite rebuild.
- Evidence packages have explicit, independent task enrollments and complete source lineage.
- Human review, not capture or a model proposal, determines task-specific labels.
- CardEventNet and TableEvidenceAnalyzer read shared source bytes without copying them into their
  component data directories.
- Status, validation, adoption, retry, conflict, interruption, and malformed-input tests pass.
- All affected formatting, linting, type, schema-conformance, Swift, Python, and Markdown-link checks
  pass locally.

## 5. Out of scope

- moving historical task-specific datasets, caches, or model runs to the repository root;
- automatic ground-truth labels or dataset eligibility;
- remote object storage, retention schedules, authentication, or multi-user upload;
- preserving the old runtime evidence layout as a supported input after adoption.
