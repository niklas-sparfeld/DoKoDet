# Filesystem storage engine

## Plan status

- **Summary:** Make validated filesystem resources the only backend storage and remove SQLite,
  SQLAlchemy, and Alembic without changing current domain or API behavior.
- **Status:** In Progress
- **Depends on:** None
- **Builds on:** Plans 0029, 0032, 0039, 0040, 0042, and 0045
- **Outcome:** The backend reads every durable resource from its canonical files and writes every
  API mutation to those files. Restart, rebuild, inspection, backup, and repair need no database.
- **M0 inventory:** [Filesystem storage inventory](../../Filesystem_Storage_Inventory.md)
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)
- **Reviewed:** 2026-09-02 against the current recording, evidence-package, table-observation,
  round-analysis, annotation, and review stores.

## Milestone status

- **M0:** Complete — freeze the filesystem ownership and store rules.
- **M1:** Not started — replace the recording-bundle SQL index with filesystem reads.
- **M2:** Not started — replace evidence-package and table-observation SQL metadata.
- **M3:** Not started — replace round-analysis SQL lifecycle state.
- **M4:** Not started — remove the SQL stack and prove filesystem-only recovery.

## 1. Purpose

The backend currently has two storage systems for the same resources. Media and canonical JSON
documents are files. SQLite stores searchable copies of recording, evidence-package,
table-observation, and round-analysis metadata. Some startup paths rebuild SQL rows from files,
while other paths depend on SQL as the only lifecycle record.

Use one rule instead:

> The filesystem is the durable store. The backend API is a validated representation of the
> filesystem. An API write changes the filesystem through the same store that local tools use.

Do not synchronize two authorities. A resource exists when its complete validated filesystem
representation exists. A database, durable index, or hidden metadata copy must not be required to
find, read, update, recover, or delete that resource.

This epic changes the storage engine only. It preserves the current domain contracts, resource
identities, API responses, state machines, uniqueness rules, and user flows. Plan 0047 changes the
event, annotation, and evidence-package data model after this epic is complete.

## 2. Scope

This epic includes:

- one canonical filesystem location and document set for each backend resource;
- typed filesystem stores for recording bundles, evidence packages, table observations, round
  analyses, pending videos, and current operations data;
- atomic creation and replacement of mutable JSON documents;
- current optimistic revision, idempotency, conflict, and restart behavior;
- deterministic list and lookup behavior without SQL queries;
- optional in-memory indexes that can be discarded and rebuilt from canonical files;
- startup validation and recovery from incomplete work;
- removal of SQLite, SQLAlchemy, Alembic, database settings, and database health checks; and
- tests that operate only on temporary filesystem roots.

This epic does not include:

- the event and evidence simplification from plan 0047;
- API route, generated-client, or user-interface changes;
- new annotation contracts or removal of review versions;
- a general object database, query language, event log, or filesystem watcher;
- support for shared network filesystems or several backend processes writing the same root;
- preservation of obsolete SQL-only development rows; or
- cloud storage, remote deployment, accounts, or permissions.

## 3. Fixed decisions

### 3.1 Authority and representation

1. Canonical files and media bytes are the only durable state. An in-memory object is a parsed
   representation. An API response is a serialized representation. Neither is a second authority.
2. API writes and local operation commands use the same filesystem store methods. Do not let API
   code write resource files directly.
3. Keep source assets and completed immutable artifacts immutable. Store mutable lifecycle or draft
   state in an explicit mutable JSON document outside the immutable artifact directory.
4. Each resource directory has one manifest or state document that declares its identity, schema
   version, required members, digests where applicable, and lifecycle state.
5. A resource becomes visible only after all required members validate and its final manifest or
   state document is atomically committed.
6. Treat directories with a staging prefix, missing members, invalid JSON, failed digests, or an
   unsupported schema as incomplete or invalid. Do not return them as valid API resources.
7. Return or log a concise validation problem for an invalid resource. Do not silently repair,
   rename, delete, or partially import it.

### 3.2 Reads, indexes, and direct file changes

8. Direct valid filesystem changes are visible on the next resource read or catalog refresh. The
   backend does not require a restart or database rebuild command.
9. Lookup by a resource ID resolves its canonical path and validates the resource. Catalog reads
   enumerate canonical resource directories, validate their summary documents, and return a stable
   sort order.
10. An optional process-local index can improve repeated catalog reads. It stores only derived
    paths and summary values. It is never written as durable authority and can be rebuilt from an
    empty process at any time.
11. Invalidate a cached entry when the canonical summary document identity changes. Tests must also
    prove correct reads with the cache disabled.
12. Do not add a second persistent index file that must be transactionally synchronized with each
    resource. A generated report is allowed only when consumers can delete and recreate it.

### 3.3 Writes and concurrency

13. Create a resource in a temporary sibling directory. Validate its complete contents, sync files
    needed for durability, and rename the directory to its final identity once.
14. Replace one mutable JSON document through a temporary sibling file, validation, file sync, and
    atomic replacement. Keep media bytes and completed artifact directories unchanged.
15. Preserve expected revisions, command IDs, replay results, and resource-level locks for mutable
    annotation and operation stores.
16. One local backend process owns mutable writes. Cross-process coordination and network
    filesystem semantics are out of scope. Fail startup when another local backend owns the same
    mutable root if an existing store needs this protection.
17. A failed write leaves either the prior valid resource or the complete next resource. It does
    not expose a mixed state.

### 3.4 Recovery and deletion

18. On startup, remove no source or completed artifact. Ignore abandoned staging paths and report
    them for local cleanup.
19. Preserve the current round-analysis restart rule. Change every non-terminal analysis state to
    failed with the existing restart reason through an atomic state-document update.
20. Preserve current explicit deletion behavior. Delete or retire only the exact resource that the
    current API already authorizes. This epic does not add cascade deletion.
21. Existing recording bundles and evidence-package bundles are already canonical filesystem
    inputs. Read them in place. Do not copy their metadata into a new authority.
22. Do not import obsolete SQL-only state. Fixture and development workflows can recreate it. This
    epic has no deployed compatibility requirement.

## 4. Filesystem ownership

Keep the configured roots and make their ownership explicit:

```text
data/incoming/videos/
  <upload_id>/                         mutable pending-upload resource

data/intake/recordings/
  <recording_id>/                      immutable accepted recording bundle

data/intake/evidence-packages/
  <package_id>/                        immutable accepted evidence package

data/operations/
  ...                                  mutable reviews, annotations, splits, and operations

.runtime/table-observations/
  <observation_id>/                    immutable table observation

.runtime/round-analyses/
  <analysis_id>/
    state.json                         mutable lifecycle state
    input/                             immutable after creation
    result/                            immutable after completion
```

The exact existing member names remain unchanged unless a missing round-analysis state document is
needed to replace its SQL row. Use paths from validated manifests. Do not derive authority from a
filename when the canonical contract already declares the path.

## 5. Store boundary

Keep small concrete stores for the resource families:

```text
RecordingBundleStore
EvidencePackageStore
TableObservationStore
RoundAnalysisStore
PendingVideoStorage
existing operations stores
```

Each store owns:

- path resolution and containment;
- parse and validation;
- complete-resource creation;
- mutable state replacement where allowed;
- deterministic lookup and listing;
- conflict and replay behavior; and
- recovery rules for its own staging paths.

API services consume typed store results. They must not know whether a catalog used a directory
scan or an in-memory index. Do not introduce a generic repository framework or a universal resource
schema. Share only small atomic-file and path-safety helpers.

## 6. Delivery milestones

### M0 — Freeze filesystem store rules

- Inventory every SQL table, query, API consumer, and canonical file counterpart.
- Record the canonical directory and summary document for each resource.
- Add shared tested helpers for contained paths, staged directory commits, atomic JSON replacement,
  and deterministic enumeration.
- Add contract tests that run with no database file or database environment setting.

Acceptance:

- the inventory maps every SQL field to a canonical file value or to one new filesystem state
  field;
- no domain value has two proposed filesystem owners;
- interrupted create and replace tests expose only the old state or the complete new state;
- invalid and staging directories stay out of resource lists with a clear diagnostic; and
- the helpers do not define a generic resource or repository abstraction.

### M1 — Read recording bundles from the filesystem

- Replace `RepositoryBundleRepository` with recording-bundle lookup and catalog reads over the
  accepted bundle directories.
- Preserve bundle validation, fingerprint checks, conflict behavior, recording ordering, and all
  current recording API responses.
- Make accepted upload commit the bundle directory directly without inserting an index row.
- Remove recording-index rebuild behavior.

Acceptance:

- recording GET and list responses match the current API fixtures;
- a valid bundle added directly to the intake root appears on the next catalog refresh;
- an invalid or incomplete bundle does not appear;
- duplicate recording IDs with different complete contents fail before final commit; and
- restart needs no recording index rebuild.

### M2 — Read evidence and observations from the filesystem

- Replace evidence-package and evidence-frame SQL reads with validated accepted package bundles.
- Replace table-observation SQL reads and uniqueness checks with immutable observation directories.
- Preserve the current logical-event uniqueness rule until plan 0047 changes it.
- Move pending-package selection and analyzer lookup to deterministic filesystem-derived queries.
- Replace database compensation logic with staged filesystem commits.

Acceptance:

- package, frame, pending-analysis, observation, and timeline API fixtures remain unchanged;
- package and observation replay is idempotent and conflicting content fails;
- current package and analyzer uniqueness rules still hold;
- a complete valid package plus observation survives restart with no rebuild step; and
- a write failure leaves no visible package or observation with missing members.

### M3 — Store round-analysis lifecycle state in files

- Add one validated mutable `state.json` for each round analysis.
- Move create, progress, complete, fail, list-by-recording, and restart recovery to the
  `RoundAnalysisStore`.
- Keep immutable input and result artifacts in their current analysis directory.
- Commit terminal state only after required immutable artifacts validate.

Acceptance:

- all current round-analysis state-transition and idempotency tests pass without SQL;
- a direct process restart changes non-terminal state to the current restart failure;
- completed analysis state and artifact digests remain readable after restart;
- concurrent updates cannot regress state or progress; and
- recording detail and timeline responses remain unchanged.

### M4 — Remove SQL and prove recovery

- Remove SQLAlchemy models and repositories, Alembic configuration and migrations, database setup,
  database settings, and SQL health checks.
- Make readiness validate required filesystem roots and a safe temporary write-and-replace probe in
  the mutable runtime root.
- Remove database dependencies and regenerate dependency locks.
- Replace SQL-focused tests with store, API, restart, and failure-injection tests.
- Update active documentation. Do not rewrite closed epics.

Acceptance:

- repository search finds no runtime import of SQLAlchemy or Alembic and no database URL setting;
- the backend starts and serves all current APIs when no database file exists;
- a fresh process reconstructs every catalog from canonical files alone;
- focused backend, operations, frontend integration, restart, and write-failure checks pass; and
- one local fixture flow uploads a recording and evidence package, creates an observation and round
  analysis, restarts the backend, and reads the same durable results.

## 7. Verification

Use a lightweight test-driven workflow. Compare API fixture responses before and after each store
cutover. Run failure injection at every staged commit and mutable state replacement. Run all checks
with temporary filesystem roots and no database service or file. Measure catalog reads with the
current development corpus. Add an in-memory cache only if the uncached measurements need it.
