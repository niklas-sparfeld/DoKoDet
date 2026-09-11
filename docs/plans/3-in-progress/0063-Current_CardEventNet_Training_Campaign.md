# Current CardEventNet training campaign

## Plan status

- **Summary:** Move the remaining legacy CardEventNet corpus into shared repository data, expose
  human-review gaps, freeze a current train/validation/test dataset, and run one bounded campaign
  that produces a new CardEventNet model.
- **Status:** In Progress
- **Depends on:** 0020, 0028, 0048, and 0049 complete; 0062 M0 and M1 complete
- **Readiness:** The shared recording intake, maintained event references, group-safe development
  split, model campaign runner, and canonical `card_state_changed` event contract exist. The legacy
  importer and campaign defaults still read `card_event_net/data`, so the implementation must join
  these paths before training.
- **Outcome:** Root `data/` is the only active CardEventNet data authority. An operator can see and
  finish every human event-review gap, freeze one leakage-safe train/validation/test dataset, run a
  reproducible campaign, and retain a new `best.pt` and model bundle with complete lineage.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete (2026-09-11) — the read-only `doko data cardevent audit` inventories legacy
  files, records dispositions and digests, separates annotation presence from maintained-reference
  completion, and reconciles shared data and model-operation artifacts.
- **M1:** Complete (2026-09-11) — migrate the complete readable legacy source corpus into current
  bundles, preserve annotation evidence and lineage, seed unreviewed draft references, and write a
  source-digest parity receipt. Legacy removal remains an explicit post-parity operator action.
- **M2:** In progress (2026-09-11) — the readiness report, per-recording human action queue,
  workspace routes, durable progress summary, blocker report, and digest-backed receipt are
  available. The imported recordings still need human full-recording review before this
  milestone can complete.
- **M3:** Not started — freeze a current CardEventNet dataset and leakage-safe train, validation,
  and sealed test partitions.
- **M4:** Not started — make training and evaluation consume a materialized view of the frozen
  shared dataset and prove the path with a smoke run.
- **M5:** Not started — prepare and run one bounded validation campaign, then lock one candidate or
  record why no candidate is suitable.
- **M6:** Not started — evaluate the locked candidate once on test, export it, and retain the new
  model and campaign handoff.

## 1. Current evidence

The tracked legacy corpus contains 43 source videos and 43 matching annotation files under
`card_event_net/data`. The annotation files are useful human evidence, but the current dataset
index states that they are a metadata baseline and not proof of complete full-recording review.
Five kitchen recordings are unassigned pending review. Historical diagnostics also identify
possible missed annotations. Do not equate “annotation file exists” with “human review is
complete.”

The local shared store currently contains 12 recording directories. Eleven use legacy
`cardeventnet-<video-id>` identities and one is a newer recording. The legacy import is incomplete:
32 of the 43 legacy videos are not yet present in shared intake. Some imported older recordings
also fail the shared bundle validator because their stored video descriptors do not use the current
path contract. Treat these counts as M0 observations. Recalculate them from the selected repository
root during implementation.

The previous full-frame development split has train and validation partitions but no test
partition. `IMG_2781` was already exposed to the earlier ROI evaluation and is now development
data. It is not a valid new final test. A new independent, reviewed source-lineage group is required
if the current shared data has no eligible sealed test group.

The model campaign runner exists, but its CardEventNet defaults still resolve split, cache, and
annotations below `card_event_net/data`. A new campaign must not restore that directory as a second
data authority.

## 2. Decisions and boundaries

### 2.1 Root data is authoritative

Use these current owners:

```text
data/intake/recordings/                         immutable source recording bundles
data/operations/pipeline/revisions/             immutable event-data revisions
data/operations/pipeline-references/            human-maintained event references
data/operations/cardevent-development-split/    approved development assignments
data/operations/cardevent-datasets/             frozen CardEventNet dataset versions and splits
data/model-campaigns/                            campaign state, reports, and candidate lineage
.runtime/cardevent/                              disposable caches and materialized run inputs
```

Exact existing pipeline revision subpaths remain owned by the current stores. Do not create a
parallel revision contract to match this diagram.

Classify every path below `card_event_net/data` as one of:

- canonical source or metadata to import;
- human annotation or review evidence to preserve with its digest;
- immutable historical evidence to archive under operations;
- a derived cache or output that can be regenerated; or
- obsolete data to remove after parity verification.

The migration is complete only when the audit has no unexplained legacy path. After M1, active
commands and documentation must not read or write `card_event_net/data`. Keep small deterministic
test fixtures outside production data paths.

### 2.2 Migration does not certify review

Preserve source bytes, source metadata, original annotation bytes, event times, event count,
canonical event type, and digests. Import a legacy annotation as evidence for a draft maintained
event reference. Do not automatically complete the reference or claim full-recording coverage
unless a durable human-review record supports that claim.

The importer must be idempotent and resumable. It must detect an existing bundle by semantic
identity and source digest. It must stop on conflicting bytes or ambiguous identity. It must not
replace a completed maintained reference or immutable revision.

### 2.3 Human gaps are explicit and actionable

Add one CardEventNet readiness report in human-readable and JSON forms. Report each selected
recording under exactly one primary state:

```text
source_missing
metadata_or_permission_missing
annotation_missing
annotation_imported_review_required
review_in_progress
review_complete
excluded
```

Also report secondary blockers such as invalid bundle structure, source-digest conflict, retired
event values in an active artifact, incomplete full-recording coverage, unresolved uncertain
events, missing group metadata, and stale split membership. For every human action, show the
recording ID, source video, reason, current review progress, and the recording-workspace route or
command that continues the work.

The report must distinguish a missing annotation from an annotation that exists but still needs
human review. Empty reviewed event data is valid when a person reviewed the complete recording and
confirmed that it contains no card-state changes.

### 2.4 Freeze data before the campaign

The campaign consumes an immutable CardEventNet dataset version, not a directory scan. Each sample
resolves to one validated recording bundle and one completed maintained event reference. Record the
source digest, event revision and digest, review coverage, task enrollment, permission, retention
state, group keys, and partition.

Use `train` and `validation` for development. Use validation for candidate, threshold, decoder, and
configuration selection. Seal `test` before the campaign starts, and evaluate it only after a
candidate lock. Never infer independent groups from file names or recording IDs. Apply session,
game, source-lineage, and table-setup isolation plus the system holdout registry.

If no eligible independent test group exists, M3 stops with an exact collection and review
requirement. Collecting and reviewing that group is part of this epic. Do not fill the partition
with an exposed legacy recording.

### 2.5 Training gets a disposable materialized view

Keep the CardEventNet model, full-frame preprocessing, causal sample construction, evaluation
metrics, and Core ML export unless a campaign candidate explicitly changes a declared experiment
axis. Add an adapter that materializes the frozen dataset into the paths required by the trainer:

```text
.runtime/cardevent/datasets/<dataset-version-id>/
  videos/
  annotations/
  cache/
  split.yaml
  materialization.json
```

The view can use links where safe. Its manifest records every canonical input and generated file
digest. It is rebuildable and is never a source or annotation authority. Update the campaign runner
to require the frozen dataset and split, and remove defaults that silently select
`card_event_net/data`.

### 2.6 The epic creates a model but does not force promotion

The successful delivery artifact is a new candidate `best.pt`, its evaluation reports, resolved
recipe, dataset lineage, and exportable model bundle. Follow the existing campaign phases:

```text
validation comparison -> candidate lock -> one sealed test -> export -> explicit promotion
```

The operator can keep the current champion when no candidate passes. Do not tune after reading the
test result. Do not overwrite the prior champion or call a candidate `best.pt` the repository
champion without a promotion receipt.

## 3. Operator workflow

Extend the existing `doko` command surface. Final option names can follow the current CLI style,
but the workflow must provide these capabilities:

```bash
mise exec -- uv run --project operations doko data cardevent audit \
  --repository-root . --legacy-root card_event_net/data

mise exec -- uv run --project operations doko data cardevent migrate \
  --repository-root . --legacy-root card_event_net/data --operator <name>

mise exec -- uv run --project operations doko data cardevent readiness \
  --repository-root .

mise exec -- uv run --project operations doko data cardevent freeze \
  --repository-root . --operator <name>

mise exec -- uv run --project operations doko model improve card-event-net \
  --repository-root . --recipe experiments/cardevent/<campaign>.yaml

mise exec -- uv run --project operations doko model compare <campaign-id>

mise exec -- uv run --project operations doko model promote <campaign-id> \
  --candidate <candidate-id> --confirm
```

`audit`, `readiness`, and `compare` are read-only. `migrate` writes canonical intake, revisions,
draft references, and receipts. `freeze` refuses incomplete review or unsafe partitions. Campaign
resume keeps the existing idempotent behavior.

The concise readiness output must answer:

- Which source recordings are not migrated?
- Which recordings have no human event annotation?
- Which imported annotations still need complete human review?
- Which metadata, permission, validation, or grouping issue blocks eligibility?
- Which recordings are eligible for train, validation, and test?
- What exact human action comes next?

## 4. Delivery milestones

### M0 — Inventory and preflight

- Add a read-only inventory over every legacy raw video, annotation, review artifact, split,
  manifest, cache, and output path.
- Reconcile it with shared recording bundles, event revisions, maintained references, development
  assignments, holdout groups, and existing campaign artifacts.
- Produce deterministic JSON and concise terminal reports with counts and item-level discrepancies.
- Record the intended disposition and destination for every legacy path.
- Add fixture coverage for complete, partial, conflicting, missing-annotation, and already-migrated
  corpora.

Acceptance:

- all 43 tracked source videos and all legacy non-source artifacts have one recorded disposition;
- the report identifies the currently remaining imports without changing data;
- annotation presence and completed human review are separate fields; and
- repeated audits are byte-stable for unchanged inputs.

### M1 — Complete shared-data migration

- Replace the bounded importer with the M0 inventory-driven, resumable migration.
- Publish missing recording bundles with current descriptors and task enrollment.
- Preserve annotation and review evidence under operations with source digests and import receipts.
- Create or rebase draft maintained event references without certifying unsupported coverage.
- Repair imported bundle descriptors through new immutable or atomic current artifacts as allowed
  by the existing store. Do not edit immutable source bytes.
- Validate source count, byte length, digest, metadata, events, and lineage before retiring legacy
  active paths.
- Remove active code and documentation dependencies on `card_event_net/data`; remove or archive the
  legacy data only after the parity receipt passes.

Acceptance:

- every accepted legacy source exists once in shared intake with the same byte digest;
- all current bundles pass the shared validator;
- no completed maintained reference was overwritten or falsely created;
- the migration resumes after interruption and is a no-op after completion; and
- the legacy tree has no active consumer and no unexplained artifact.

### M2 — Human annotation readiness

- Add the readiness report and focused CardEventNet human-action queue.
- Seed review drafts from preserved human annotations while retaining uncertainty and provenance.
- Route the operator to the existing recording event workspace for complete video review.
- Keep progress durable and resumable. Require explicit completion with full-recording coverage.
- Run the report after human work and retain a signed readiness receipt.

Acceptance:

- the operator can identify every missing or incomplete human annotation without inspecting JSON;
- each action opens or names the correct recording and reason;
- every training-eligible recording has a completed canonical maintained event reference; and
- the readiness receipt lists excluded recordings and their reasons.

### M3 — Current dataset and split

- Freeze one immutable dataset version from eligible recordings and maintained event references.
- Propose group-safe train and validation assignments without changing approved assignments
  silently.
- Identify or collect, migrate, annotate, and seal at least one independent test source-lineage
  group that has not influenced development.
- Validate session, game, source-lineage, table-setup, duplicate-source, permission, retention, and
  system-holdout boundaries.
- Publish machine-readable dataset and split artifacts plus a concise coverage report by partition,
  event count, duration, capture context, and group.

Acceptance:

- train, validation, and test are non-empty and have no connected leakage group;
- every member resolves to immutable source and completed human event evidence;
- validation and test satisfy declared minimum coverage or the freeze fails with exact gaps;
- test is sealed before the campaign recipe is resolved; and
- `doko data validate` accepts the complete frozen inputs.

### M4 — Current trainer input and smoke proof

- Add the deterministic materializer from the frozen dataset to a disposable CardEventNet run
  view.
- Update prepare, train, evaluate, diagnose, and campaign execution to use the same frozen data
  identity.
- Remove implicit legacy split, annotation, and cache defaults from the campaign runner.
- Record source, event-reference, dataset, split, materializer, preprocessing, code, and environment
  versions in every run.
- Run a small local CPU or Apple Silicon smoke train and validation evaluation.

Acceptance:

- deleting the materialized view and rebuilding it yields the same manifest;
- the trainer reads no production input below `card_event_net/data`;
- a smoke run writes a loadable `best.pt` and evaluation report; and
- CardEventNet tests, operations tests, lint, format, and data validation pass.

### M5 — Validation campaign

- Add one checked-in bounded recipe with the current champion as baseline and the M3 frozen data.
- Declare the candidate count, seeds, experiment axes, time and failure budgets, device, precision,
  decoder settings, metrics, gates, and Core ML requirement before execution.
- Run the champion and candidates on the same validation partition.
- Resume interrupted work, retain failures, and publish comparison plus diagnostic reports.
- Lock one passing candidate or record `keep_champion_recommended` or
  `human_review_required` with exact reasons.

Acceptance:

- the campaign is reproducible from its recipe and immutable inputs;
- no command reads test or the system holdout during selection;
- at least one candidate run produces a new loadable `best.pt`, unless a recorded execution failure
  exhausts the bounded campaign; and
- the comparison reports overall and worst-recording recall, precision, F1, false events per hour,
  timing delay, and hard-negative behavior.

### M6 — Test, export, and handoff

- With explicit operator confirmation, evaluate only the locked candidate on the sealed test once.
- Apply the existing promotion gates without starting another candidate or changing a threshold.
- Export and validate the Core ML bundle, preprocessing fixture, runtime load, and parity.
- Retain the new `best.pt`, resolved decoder settings, model bundle, reports, digests, and prior
  champion rollback information under campaign-owned paths.
- Promote only when the operator confirms and every hard gate passes. Otherwise retain the new
  candidate and finish with a clear human-review or keep-champion result.
- Update the CardEventNet operator documentation with the exact normal campaign and resume flow.

Acceptance:

- the test evaluation is tied to the locked checkpoint and frozen test partition;
- the new checkpoint and bundle can be loaded locally and traced to source and annotation digests;
- promotion is atomic, explicit, and recoverable; and
- the final report names the new model artifact, campaign outcome, remaining data gaps, and the
  command needed for the next campaign.

## 5. Out of scope

- changing event semantics beyond the completed canonical `card_state_changed` contract;
- semantic classification of plays, moves, removals, or trick clears;
- changing table-observation, visual-identity, or reconstruction behavior;
- using generated proposals as human ground truth;
- selecting a model or threshold with test or system-holdout results;
- cloud infrastructure or phone-only development requirements; and
- deleting the prior champion model bundle.
