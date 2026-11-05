# Unified pipeline data lineage

## Plan status

- **Summary:** Define named pipeline data nodes, revision-bound provenance and review, automatic
  copies after downstream use, first-class virtual scenes, and a verified data migration.
- **Status:** In Progress
- **Depends on:** Existing revision, run, and review storage from completed Epics 0048, 0049, 0102,
  and 0105. No new completion gate from Epic 0106.
- **Outcome:** M0–M3 are complete; M4–M10 are not started. This epic supplies contracts, services, and migration
  tools. [Epic 0108](../4-blocked/0108-Horizontal_Lineage_Workspace.md) integrates the workspace,
  performs the local cutover, and removes the replaced runtime paths.

## Problem

The workspace treats generated results and reviewed references as different kinds of data. Origin,
human edits, review coverage, and saving are mixed into separate lifecycles. Operators cannot
reliably identify which revisions they inspect or which sources produced a result. Virtual scenes
are stored partly as proposals and partly inside visible-card review work.

Use the terms in the [glossary](../../glossary.md). Existing glossary definitions and closed epics
retain their historical meaning. The new model replaces their runtime use where specified here.

## Agreed contract

### Nodes, revisions, and edits

- A pipeline data node is one named collection of one content type. Tool-created, human-created,
  mixed, reviewed, and unreviewed content use the same content contract.
- A node has stable identity. Saved revisions are immutable. Autosave creates revisions within the
  node; it does not add lineage nodes for each save. A no-op does not create a content revision.
- A processor run remains a separate execution record. Its input and output references identify
  exact revisions, source bytes, implementation, model, configuration, and derivation policies.
- Before downstream use, edits continue within the node. After accepted downstream use, the first
  content change creates an independent copy from the exact source revision and applies the change
  there. Later edits stay in that copy until it too is used downstream. No freeze/unfreeze action.
- Opening an editor or inspecting a historical revision does not copy anything. A failed or
  rejected edit does not leave a copy. Retries do not create duplicate copies. Concurrent writers
  cannot silently overwrite each other.
- Record downstream use when execution is durably accepted, before it can read an input. A failed
  or cancelled accepted run still records that use. Protect accepted inputs against edit/start
  races. Derived-view caching alone does not count as downstream use.
- Explicit copying is also available. Record its exact source, creator, time, and reason when
  known. Automatic copies record downstream use as the reason. Give copies stable, unique names.
- Historical revisions are inspectable. Changes based on an older revision require an explicit
  copy or restore action. A restore creates a new revision and obeys the downstream-use copy rule.

### Provenance and review

- Retain original item creation and subsequent changes by people or processors. Human corrections
  do not replace original tool attribution. Copying unchanged content preserves its provenance.
- Record insertion, deletion, replacement, split, and merge relationships when applicable. Do not
  infer physical-card identity or cross-frame associations from stable editing IDs.
- Use separate metadata for origin, content changes, item review, review coverage, overall review,
  and working-state persistence. Completing review is not a prerequisite for saving or processing.
- Review decisions identify the exact content, evidence, question, reviewer, time, and coverage.
  Overall review is an independent decision. Reviewing all known items does not prove that gaps
  contain no missing items. Preserve reviewed negatives and deleted-item decisions.
- Preserve old review decisions in history. Mark their current applicability explicitly after
  changes. Never make downstream predictions reviewed merely because their inputs were reviewed.
- A copied unchanged item retains applicable review. For a refreshed identity result, carry a human
  decision only when item correspondence, exact crop evidence and policy, and the reviewed content
  prove applicability. Preserve a human-corrected classification on unchanged evidence; a new model
  prediction must not silently overwrite it. Changed, missing, or ambiguous evidence needs review.
- Review-only decisions and display-name changes do not change evidence content and do not trigger
  automatic copies. Retain their audit history separately. A review action that also corrects content
  follows the content-change copy rule. Overall decisions remain tied to their exact revision.
- Moving a virtual card or changing stacking order can change other cards' visible regions. Review
  applicability follows actual affected evidence, not just the edited card ID. A full processor
  rerun is acceptable; resetting all human review is not.

### Lineage and virtual scenes

- Store a directed acyclic graph with typed relationships: copied from, revised within a node, and
  produced using exact inputs. Store all inputs, not only one display parent. Reject cycles.
- Virtual scenes use one common content contract for processor and human work. Retain exact frame
  identity, poses, stacking order, calibration revision, and review coverage. Keep visible-card
  regions, pile regions, and ignore regions distinct. Derived visible regions remain derived views.
- Table observations may depend on several input revisions. Analyses retain exact observations,
  round context, rules, and search settings. Keep failures and valid empty results inspectable.

## Migration and cutover boundary

The user explicitly requests migration of existing data. Do not preserve obsolete runtime formats
through permanent adapters or dual writes. New services can be tested before the application uses
them. Epic 0108 owns the coordinated switch of writers, readers, workspace, and storage.

Inventory processor revisions, runs, maintained references, independent reviews, mutable drafts,
scene proposals, reviewed scenes, calibration records, selections, analysis records, and their
references. Include retained fixtures and active consumers outside the workspace where relevant.
Do not rewrite sealed campaign artifacts or closed epics to make them fit the new vocabulary.
If a reference cannot be changed, retain its exact artifact identity through an explicit mapping.

Preserve source bytes, historical content, decisions, coverage, frame identities, and exact
dependencies. M0 defines deterministic grouping into nodes: do not invent edit ancestry from time
ordering alone. Preserve separate reviews as separate nodes. Existing generated/manual/corrected
labels can supply evidence, but cannot invent per-item authors or review decisions. The old command
ledger contains hashes, not a replayable edit log. Record unavailable history as not recorded.

Produce a read-only inventory and dry-run plan with old-to-new IDs, content and reference checks,
uncertainties, and blocking conflicts. A consistent source snapshot is required. Migrate into a
separate staging location, verify it, then switch atomically at the application boundary. Interrupts
must leave the old active store usable or the new verified store active. Reapplication is safe.
Keep a recovery snapshot; remove old active storage and runtime adapters after verified cutover.
Do not run the real migration as part of planning or foundation development.

## Scope limits

- No new processor-trigger UX, input chooser, actionable empty-state buttons, automatic cascades,
  or execution limited to changed items. Applicability services support a later explicit refresh.
- No automatic rebase of edited content across changed sources. No guessed transfer of reviews.
- No arbitrary output editing for table observations or round analyses; keep current capabilities.
- No iOS UI redesign, model promotion, training, new evaluation campaign, or sealed evaluator run.
- Existing processor-input selection must remain functional until explicitly replaced. Trace all
  consumers before removing selection pointers. Browsing never changes downstream defaults.

## Milestones

Each milestone is one implementation phase. Commit each completed milestone to main, update this
file and the board, and report every milestone's state. Do not start the next milestone implicitly.

### M0 — Specify storage and migration mappings — Complete

Contract: [M0 inventory](../../reports/0107-M0_Lineage_Inventory.md).

Inventory owners and consumers. Define node/revision identifiers, item correspondence, audit events,
review applicability, downstream-use locking, and migration mappings. Record a contract report with
small fixture examples, the removal list, and cutover ownership. Define how a browse path remains
unambiguous when a source has several descendants. Confirm no dependency on unfinished 0106 work.

Acceptance: each old resource has a destination or an explicit exclusion with preserved references.
Every later milestone has concrete contract fixtures. The contract does not reopen agreed UX.

### M1 — Store nodes and immutable revisions — Complete

Implement node manifests, working heads, revision history, source references, and common metadata.
Keep content-type validation. Add listing and exact revision reads. Use optimistic concurrency.

Acceptance: fixtures cover autosave, no-op, restart, immutable historical reads, and write conflicts.

The separate node store validates the existing content contracts, retains exact source references, and
uses immutable revisions with an optimistic working head. It is not connected to processor execution;
M3 must add downstream-use protection before that integration. See the
[M1 result](../../reports/0107-M1_Node_Storage.md).

### M2 — Record item origin and content changes — Complete

Implement item provenance and retained change records with shared human/processor attribution.
Represent deletion and replacement without losing earlier evidence. Include unknown historical data.

Acceptance: tool creation, human correction, tool correction, split/merge, deletion, and unchanged
copy fixtures retain original creation and the available change chain.

The [M2 result](../../reports/0107-M2_Item_Provenance.md) records explicit item operations with
revision-bound evidence and retains creation attribution across copies.

### M3 — Protect downstream uses and create copies — Complete

Implement durable accepted-use records and atomic copy-on-first-change. Provide explicit copy and
historical restore services. Return selected-copy identity and reason to clients.

Acceptance: edit/start races, retries, failed edits, accepted failed runs, repeated edits, and
concurrent copies preserve exact inputs without duplicate or orphan copies.

The [M3 result](../../reports/0107-M3_Accepted_Use_and_Copies.md) records accepted uses,
protected edits, explicit copies, restores, idempotency, and interruption recovery.

### M4 — Record item and overall review decisions — Not started

Implement revision-bound item decisions, negative coverage, and independent overall review records.
Saving does not imply review. Compute applicability when copied content changes.

Acceptance: all items reviewed without overall review, partial coverage, empty inspected coverage,
changed reviewed content, and copied unchanged content have distinct, durable results.

### M5 — Preserve applicable identity review — Not started

Implement the bounded applicability service for refreshed identity results. Use exact evidence and
explicit correspondence. Retain human-corrected classifications when applicable.

Acceptance: correct card 100 in a scene, recompute identity fixtures, retain unaffected decisions,
and require review only for affected/ambiguous results. Include changed occlusion of another card,
changed crop policy, deleted cards, duplicate identities, and unchanged crops after a full rerun.

### M6 — Unify virtual-scene content — Not started

Define and store first-class virtual-scene revisions. Map proposed and human-edited scenes into the
same content contract. Keep exact calibration and frame dependencies and derived-region authority.

Acceptance: mixed origin/review within scenes, stacking changes, fully hidden cards, calibration
changes, and separate pile/ignore regions round-trip without invented geometry or authority.

### M7 — Validate and query the lineage graph — Not started

Implement typed exact-input and copy edges, cycle checks, source/run context, and compact summaries.
Expose deterministic lineage data for the horizontal workspace without selecting processor inputs.

Acceptance: multi-input observations, analyses with context, two copies, alternative runs, empty
outputs, and failures retain all sources. Duplicate display appearances share one node identity.

### M8 — Build migration inventory and dry run — Not started

Implement read-only discovery, deterministic node grouping, ID mapping, uncertainty reporting, and
validation. Inventory active stores and retained consumer references; do not load sealed samples.

Acceptance: mixed old-format fixtures produce reproducible plans, preserve unknown history, and
report dangling or ambiguous references without inventing lineage.

### M9 — Apply migration to fixture stores — Not started

Implement staged conversion, verification, recovery, and safe reapplication. Supply a local command
for the later cutover. Never mutate the active local data during this milestone.

Acceptance: interruption fixtures cover conversion, verification, and activation boundaries. Counts,
semantic content, hashes or explicit hash mappings, review coverage, and all references reconcile.

### M10 — Verify foundation and hand off — Not started

Run contract/store/service/migration checks and applicable lint, type, and format checks. Document
the exact integration points for Epic 0108, verification commands, and remaining old runtime paths.

Acceptance: fixtures demonstrate the complete correction/copy/review/migration contract locally.
Mark this epic Closed only when all milestones pass; unblock 0108 and repair moved links together.

## Source ownership

- `operations/src/doko_operations/pipeline_data.py`: revision and producer contracts.
- `table_evidence_analyzer/src/table_evidence_analyzer/pipeline_data.py`: typed evidence payloads.
- `backend/src/dokodetector_backend/pipeline_store.py`: immutable content and run storage.
- `backend/src/dokodetector_backend/pipeline_reference_store.py`: old maintained drafts.
- `backend/src/dokodetector_backend/visible_card_review_store.py`: independent and legacy reviews.
- `backend/src/dokodetector_backend/pipeline_coordinator.py`: exact execution dependencies.

Use these as inventory entry points, not a requirement to preserve their current module boundaries.
