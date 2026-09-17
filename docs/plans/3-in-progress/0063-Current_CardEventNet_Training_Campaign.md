# Current CardEventNet training campaign

## Plan status

- **Summary:** Move the remaining legacy CardEventNet corpus into shared repository data, use
  reviewed card-state change intervals, resolve the measured stable-end timing errors, and run a
  bounded manual training campaign that produces a new CardEventNet model.
- **Status:** In Progress
- **Depends on:** 0020, 0028, 0048, and 0049 complete; 0062 M0 and M1 complete
- **Readiness:** M0–M11 and the operator-run hard-negative ablation are complete. The ablation
  confirms that event presence is strong but stable-end timing remains the dominant validation
  error. M11 reconciled the six-recording prose review, froze a successor validation dataset,
  and replayed three decoder responses. No decoder is selected yet. The sealed test remains
  unread. Long training, test, export, and optional diagnostic commands are operator-run and are
  never started or monitored by an implementation agent.
- **Outcome:** Root `data/` is the only active CardEventNet data authority. An operator can see and
  finish every human event-review gap, freeze a leakage-safe train/validation/test dataset, run a
  reproducible manual campaign, and retain a new `best.pt` and model bundle with complete lineage.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete (2026-09-11) — the read-only `doko data cardevent audit` inventories legacy
  files, records dispositions and digests, separates annotation presence from maintained-reference
  completion, and reconciles shared data and model-operation artifacts.
- **M1:** Complete (2026-09-11) — migrate the complete readable legacy source corpus into current
  bundles, preserve annotation evidence and lineage, seed unreviewed draft references, and write a
  source-digest parity receipt. Legacy removal remains an explicit post-parity operator action.
- **M2:** Complete (2026-09-11) — the readiness report, per-recording human action queue,
  workspace routes, durable progress summary, blocker report, and digest-backed receipt are
  available. All 32 imported annotation references were accepted and completed with full-recording
  coverage. One separate unannotated source remains explicitly blocked in the readiness queue.
- **M3:** Complete (2026-09-13) — freeze `cardeventnet-dataset-babc3dca31acd0c3631c` has 28 train,
  10 validation, and five sealed test recordings with complete reviewed coverage. The policy uses
  recorded capture sessions as source-lineage groups, restores real-game IDs from preserved legacy
  metadata, respects current source permissions, and keeps the previously unassigned kitchen
  session as independent test. The separate unannotated recording remains outside this migrated
  CardEventNet campaign corpus.
- **M4:** Complete (2026-09-13) — materialize the frozen shared dataset into a deterministic
  disposable run view, route CardEventNet prepare/train/evaluate/diagnose and campaign execution
  through that view, retain complete run lineage, and prove the path with a CPU smoke run.
- **M5:** Complete (2026-09-15) — campaign
  `cardeventnet-0063-m5-validation-20260915` used the frozen dataset and validation partition only.
  Candidate `candidate-transition-label-v2` produced a loadable `best.pt`, comparison, and
  diagnostics. Validation was recall 0.811, precision 0.846, F1 0.828, 149.316 false events per
  hour, worst-recording F1 0.591, and 86.6 ms median timing delay. The current app champion is a
  Core ML bundle, not a loadable PyTorch checkpoint, so the champion comparison was unavailable.
  The candidate failed the declared recall, precision, F1, false-event, worst-recording, latency,
  Core ML export, and device-parity gates. The campaign recorded `human_review_required` and did
  not create a candidate lock or read the sealed test partition.
- **M6:** Complete (2026-09-16) — the deterministic interval-readiness report records 1,778 point
  events and 368 interval events across 43 historical recordings. It marks 38 recordings eligible
  for future work, five old-phone recordings diagnostic-only, and no recordings blocked. The
  repository-wide exclusion receipt is bound to source digests and the report digest is
  `267c384dda2579bda8953fca581520ed40f52b0601b8a5090c4f7b0d2fc01cf2`.
- **M7:** Complete (2026-09-16) — freeze
  `cardeventnet-interval-dataset-2e00fe87f08e25c51aa4` contains 27 train, six validation, and
  five sealed-test recordings. It excludes the five old-phone diagnostics, retains 38 eligible
  recording entries, and publishes the stable-end sampling report with 1,537 point targets, 368
  interval targets, 3,391 train positives, and 11,244 train eligible clean negatives. The dataset
  digest is `2e00fe87f08e25c51aa40d68ec2a212001bdff9a4586f86affd72703d04813ca`.
- **M8:** Complete (2026-09-16) — the bounded recipe
  `cardeventnet-0063-m8-interval-validation` keeps the M5 full causal architecture, decoder,
  seed 42, MPS/FP32 execution, and 120-minute budget fixed. Its preflight validates the M7
  dataset, split, stable-end materialization, M5 checkpoint digest, and sampling policy, then
  writes the operator handoff for campaign
  `cardeventnet-0063-m8-interval-validation-df1dddc98bbb`. The handoff estimates 12,878 train and
  3,017 validation samples, uses ordinary negatives only, and records test and system-holdout
  inputs as unread. The implementation agent did not start the command; the operator later
  completed the training and validation run without reading test or system-holdout inputs.
- **M9:** Complete (2026-09-16) — review campaign
  `cardeventnet-0063-m8-interval-validation-df1dddc98bbb` validates the M8 handoff, M5 baseline,
  M7 dataset and split, checkpoint digests, validation streams, and diagnostic lineage before
  reading metrics. The candidate improves validation F1 from 0.883 to 0.917 and reduces false
  events per hour from 167.1 to 136.2. Interval-aware diagnostics report 50 stable-end matches,
  232 point matches, 29 in-progress detections, 30 misses, and 22 confirmed false triggers. The
  candidate remains `human_review_required` because the false-event, inference-latency, Core ML,
  device-parity, and regression-fixture gates are not all satisfied. No candidate lock or sealed
  test read was created. The operator reviewed all 68 hard-negative candidates: 63 are
  `no_event` and five are `missed_event`. A separate 63-item, `training_input: true` manifest and
  operator-only hard-negative ablation handoff were prepared; the original M9 manifest remains
  unchanged. The operator later completed that ablation. It reached validation recall 0.910,
  precision 0.934, F1 0.922, 20 confirmed false triggers, 22 in-progress detections, 49 stable-end
  matches, and 235 point matches. It did not create a candidate lock or read sealed test.
- **M10:** Complete (2026-09-17) — the read-only timing-review command validates the M9 ablation
  handoff, selected checkpoint, threshold, decoder settings, saved validation stream, M7 dataset,
  and six current reference revisions. It publishes 70 raw items (28 misses, 20 confirmed false
  triggers, and 22 in-progress detections) in 47 deterministic review regions, the ordered
  operator checklist, local startup commands, six workspace routes, and a pending completion
  artifact. Packet digest: `eb47261ca4236c59c9dbab4565c77a4f8cec66804b9413e8c956a54f8444bc12`.
  It did not change maintained references, tune the decoder, start training, or read sealed test.
- **M11:** Complete (2026-09-17) — the six recording decisions and prose notes are reconciled
  into 70 immutable item decisions: 27 `reference_corrected`, 25 `reference_confirmed`, and 18
  `no_event_confirmed`. The successor dataset
  `cardeventnet-interval-dataset-00a59b5fcd210d23c569` preserves the M7 groups and sealed-test
  membership. Its validation replay reports 228 point matches and 49 stable-end matches with
  the current decoder; longer peak confirmation reports 228 point matches and 51 stable-end
  matches. No decoder is selected. The report, decision lineage, dataset, materialized view, and
  decoder grid are under `data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/`
  and the successor dataset path. M11 did not train, export, promote, or read sealed test.
- **M12:** Not started — select one timing response from M11 evidence and prepare its exact manual
  campaign command. Prefer a decoder-only response when it satisfies the declared stable-end
  gates. Otherwise prepare one interval-aware temporal-model response. Stop before training.
- **M13:** Not started — after the operator runs the M12 command, compare the candidate on the
  successor validation partition and either lock it or retain `human_review_required`.
- **M14:** Not started — blocked until M13 creates a candidate lock. Prepare and validate the
  one-time sealed-test, export, parity, and promotion handoffs without running operator-only
  commands.

## 1. Current evidence

M0 found 43 legacy source videos and 43 matching annotation files. M1 migrated the accepted corpus,
and M2 completed its original full-recording review. M3 froze 43 recordings as 28 train, 10
validation, and five test recordings. Keep these historical artifacts immutable.

The later interval pass now has completed maintained references for `IMG_0635`, `IMG_0652`,
`IMG_0671`, and `IMG_0674`. Their current interval counts are 10, 10, six, and six. The operator
does not require interval completion for `IMG_2777` through `IMG_2781`: these five recordings came
from an old phone and are excluded from every future CardEventNet dataset. Their source assets and
existing evidence remain available for optional legacy-device diagnostics.

The M3 split placed `IMG_2781` in train and `IMG_2777` through `IMG_2780` in validation. A new split
and dataset must remove all five. Based on the unchanged assignments, the expected eligible counts
become 27 train, six validation, and five test recordings. M7 must recalculate the counts and stop
if group safety or minimum validation coverage does not hold.

M6 records the interval-readiness audit at
`data/operations/cardeventnet-interval-readiness/reports/interval-readiness.json` and publishes the
diagnostic-only exclusion at
`data/operations/source-exclusions/legacy-device-diagnostic.json`. The report uses the M3 frozen
dataset as its population and partition authority while binding each result to the currently
selected maintained event revision. A zero-interval result is eligible only with an immutable
attestation bound to that revision's manifest and content digests.

M7 freezes the interval-aware dataset at
`data/operations/cardevent-datasets/cardeventnet-interval-dataset-2e00fe87f08e25c51aa4/`. Its
split is 27 train, six validation, and five sealed test recordings. The five diagnostic recordings
have no dataset entries. The materialized view retains every event start and end bound and uses
`stable-end-anchor-v1`. The sampling report is
`data/operations/cardeventnet-interval-readiness/reports/cardeventnet-interval-dataset-2e00fe87f08e25c51aa4-sampling.json`;
the combined report is beside it. The sampling report includes the M3 comparison and explains all
43 recording changes with old and new revision, manifest, content, and target-count values. The
combined report records the resulting dataset, materialization, lineage, and partition summary.
The sampling digest is `bdc754fe144f5b78752f650eac08ec293f331f92a1423c0520ca85d8bb0931f8`.

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

### 2.7 Interval labels do not make transitions negative

Use one target and three non-target regions for every reviewed event:

```text
reviewed interval interior [start_us, end_us)       ignore
stable end and its configured positive window      positive
configured exclusion buffers around point targets ignore
other fully reviewed times                         clean negative
```

The model gets no negative loss from a trick-taking transition. It learns the stable state at the
interval end as the positive target. Evaluation reports a prediction inside the interval as an
in-progress detection, not as a false event. Keep in-progress detections visible as a separate
metric because an early runtime trigger can still produce a poor table observation.

Use the new annotations as the only experiment axis in the next validation campaign. Keep the
architecture, clip construction, configuration, seed, decoder, and partition groups fixed. Score
the M5 checkpoint and the new checkpoint against the same new validation references. This makes
the effect of the reviewed intervals measurable.

The completed full-recording review also defines a larger clean-negative pool. A time is eligible
only when it is inside reviewed coverage and outside every event interval, positive window, and
exclusion buffer. The first interval-aware run uses ordinary negative sampling only. After that
run, mine high-scoring unmatched predictions from the training partition into a separate candidate
manifest. Never mine from validation or test. Never place an interval-interior prediction in that
manifest. Do not train from the candidate manifest until an operator confirms it and a later
single-axis hard-negative ablation is declared.

### 2.8 The operator runs long commands

Implementation agents can run unit tests, data validation, deterministic materialization, dry
runs, and short smoke checks. They must not start, wait for, poll, or monitor full training, full
validation inference, sealed-test inference, or export commands. Each execution milestone writes
one exact copy-and-paste command and the expected output paths, then stops. The operator runs the
command and starts the next phase after it exits.

### 2.9 Old-phone recordings are diagnostic only

Retain `IMG_2777`, `IMG_2778`, `IMG_2779`, `IMG_2780`, and `IMG_2781` as source and historical
review evidence. Publish one repository-wide diagnostic-only exclusion that names their source
asset IDs, digests, common reason, and operator decision. Future dataset builders for every task
must honor it. Do not rewrite immutable source records, old splits, old frozen datasets, or old
campaign results.

Future freezes, training, validation selection, clean-negative pools, hard-negative mining, sealed
tests, metric gates, and promotion decisions must exclude all five recordings. They can be
evaluated only after a relevant campaign decision as a separately named
`legacy_device_diagnostic`. Its result is informational. It cannot change a candidate, threshold,
gate result, or promotion decision.

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

mise exec -- uv run --project operations doko data cardevent interval-readiness \
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
resume keeps the existing idempotent behavior. `interval-readiness` reports point and interval
counts, incomplete drafts, zero-interval decisions, selected revision IDs, and revision digests.
It does not infer that a recording must contain a trick clear from its event count alone.

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

Result: `doko data cardevent materialize` now builds
`.runtime/cardevent/datasets/<dataset-version-id>/` with source links, V2 annotations, a trainer
split, derived-file digests, and a manifest digest. CardEventNet commands accept the view through
`--dataset-view`; the campaign runner requires the frozen dataset for real execution and no longer
selects `card_event_net/data` as its implicit input. Training checkpoints and evaluation reports
retain dataset, split, source, event-reference, materializer, preprocessing, code, and environment
identity. A local CPU smoke run wrote and loaded `best.pt` and wrote a validation report.

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

### M6 — Complete the interval review set

- Add a deterministic `interval-readiness` report over the current maintained event references.
- Report recording ID, partition, content type, reference state, selected revision, point count,
  interval count, reviewed duration, and revision digest.
- Fail readiness while any future-eligible recording has a draft reference. Do not publish a new
  revision or complete a human draft automatically.
- Require an explicit operator decision for each zero-interval recording: complete another interval
  review or attest that no card-state change interval is present. Bind each attestation to the
  selected revision digest so a later revision invalidates it.
- Publish a repository-wide diagnostic-only exclusion receipt for `IMG_2777` through `IMG_2781`.
  Record `legacy_device_diagnostic` as their only future role. Make shared dataset eligibility
  checks reject the five source assets for train, validation, test, and promotion-gate datasets. A
  draft or zero-interval reference in this excluded set is not an interval-readiness blocker.
- Seed focused tests from the completed changes to `IMG_0635`, `IMG_0652`, `IMG_0671`, and
  `IMG_0674`, plus the five-recording exclusion.

Acceptance:

- all 43 historical campaign recordings appear exactly once as eligible or diagnostic-only;
- the report cannot mistake a completed point-only reference for an interval review decision;
- every eligible draft and zero-interval decision has one exact operator action;
- the diagnostic-only receipt is bound to all five source digests and blocks their future dataset
  eligibility across tasks; and
- M6 stops for the operator when human review is still required.

### M7 — Freeze the interval-aware dataset

- Freeze a new immutable dataset from the completed maintained references. Preserve the M3 group
  and partition assignments for eligible recordings unless a validator finds a leakage violation.
- Exclude `IMG_2777` through `IMG_2781` before split validation and record their exclusion receipt
  in dataset lineage. Expect 27 train, six validation, and five test recordings before validation.
- Seal the new test partition before any new model output is read. Do not modify the M3 dataset.
- Materialize the disposable trainer view and verify the `stable-end-anchor-v1` policy.
- Publish per-recording and per-partition counts for point targets, interval targets, positive
  samples, ignored interval samples, other ignored samples, and eligible clean negatives.
- Compare the counts with the M3 materialization. Explain every changed recording and digest.

Acceptance:

- every dataset entry resolves to the completed revision or zero-interval attestation accepted in
  M6, and no diagnostic-only recording has an entry;
- the materialized annotations retain all `start_us` and `end_us` values;
- no interval-interior sample is an ordinary or confirmed hard negative;
- train, validation, and sealed test remain group-safe; and
- rebuilding the view yields the same manifest and sampling report.

Result: M7 is complete. The new dataset, split, coverage, freeze receipt, materialized view, and
sampling reports were written as new artifacts. The historical M3 dataset remains unchanged. A
data-only preparation pass created the five disposable sealed-test caches required for deterministic
sampling; no training, validation inference, export, or model output was started.

M8 publishes the operator-only handoff at
`data/model-campaigns/cardeventnet-0063-m8-interval-validation-df1dddc98bbb/handoff.json` with
digest `7f8e66fbeff0be4ab42fbf70f7d322e38f1c384db2003d0e21dd4e60c6eeda8c`. Prepare it with:

```bash
mise exec -- uv run --project operations doko model improve card-event-net \
  --repository-root . \
  --recipe experiments/cardevent/0063-m8-interval-validation.yaml \
  --preflight
```

The preflight is read-only apart from the handoff file. The handoff command is the only next
operator action. Repeat that same command to resume after an interrupted run. Do not run it from
an implementation agent.

### M8 — Prepare the manual interval-only validation campaign

- Add one bounded recipe that uses the M7 dataset and the M5 checkpoint as the loadable comparison
  baseline.
- Keep the M5 architecture, full causal clip, training configuration, seed, decoder, and budgets
  fixed. The reviewed interval dataset is the only experiment axis.
- Add fixture tests that prove the recipe cannot read test, system holdout, or a hard-negative
  manifest during selection.
- Add a read-only preflight that validates inputs, estimates sample counts and command outputs, and
  writes the exact manual command to a campaign handoff file.
- Stop after the preflight. Do not start or monitor the training command.

Acceptance:

- the handoff names the recipe, dataset and split digests, checkpoint baseline, expected campaign
  directory, resume command, and completion artifacts;
- the command runs one candidate with one seed and ordinary negatives only;
- the command can resume without creating a second campaign identity; and
- no implementation agent starts the command.

Result: M8 is complete. The recipe, preflight, fixture guards, and operator handoff are checked
in. The handoff fixes the M7 dataset and split digests, the M5 checkpoint digest, one candidate,
seed 42, ordinary negatives, and the expected campaign outputs. The operator remains responsible
for the long training and validation run.

### M9 — Compare the manual run and harvest negative candidates

- After the operator finishes the M8 command, validate artifact completeness and lineage before
  reading metrics.
- Compare the M5 checkpoint and new checkpoint on the same M7 validation references. Report stable
  end matches, point matches, in-progress detections, misses, confirmed false triggers, overall and
  worst-recording metrics, false events per hour, and timing delay.
- Apply the declared gates and lock one candidate or retain `human_review_required`. Do not tune a
  threshold or recipe after this decision.
- From the locked recipe's training partition only, write a ranked, deduplicated hard-negative
  candidate manifest from unmatched high-score predictions in clean-negative regions.
- Exclude interval interiors, positive windows, point-event exclusion buffers, validation, test,
  system holdout, and the legacy-device diagnostic set. Mark the manifest `training_input: false`
  until a later human review and separate ablation.

Acceptance:

- comparison inputs have exact dataset, checkpoint, decoder, and code lineage;
- an in-progress interval detection never counts as a confirmed false trigger;
- every negative candidate resolves to full review coverage and a clean-negative sample; and
- the campaign decision does not use sealed-test output.

Result: M9 is complete. The review command consumed only completed M8 artifacts and
then wrote `m9-review.json`, `m9-report.md`, and `m9-hard-negative-candidates.json` below the
campaign directory. It promoted the mechanical `no_valid_candidate` result to the final
`human_review_required` campaign state without changing the threshold, decoder, recipe, or
sealed-test state. The candidate manifest contains only clean-negative samples from the frozen
training partition and remained outside training until the operator reviewed it. The completed
review produced 63 approved `no_event` samples and excluded five `missed_event` samples. The
separate ablation manifest and operator handoff are under
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/`; no long command was started.
The operator later ran the handoff. The completed result improved F1 from 0.917 to 0.922 and reduced
confirmed false triggers from 22 to 20, but stable-end matches changed from 50 to 49. This marginal
change confirms that another hard-negative pass is not the next campaign axis.

### M10 — Publish the validation timing-review handoff

M10 is Luna work. Luna must derive one deterministic review packet from the completed hard-negative
ablation evaluation, the M7 validation references, and the saved validation streams. The packet
must contain the selected checkpoint, threshold, decoder settings, dataset and revision digests,
and one item for every reported miss, confirmed false trigger, and in-progress interval detection.
Group adjacent items into one review region so the operator does not review the same action twice.

The packet must separate three questions:

1. Is there a reviewed card-state change that is absent or timed incorrectly?
2. Is the prediction inside one continuous reviewed interval?
3. Is the prediction a real no-event trigger after the reference is confirmed?

Do not show a model outcome as ground truth. Do not change a maintained reference, create a new
dataset, tune the decoder, or run training in M10.

#### Operator review order

Luna must give the operator this ordered list after it publishes the packet:

1. **Review `cardeventnet-IMG_0090` first.** It contains eight of the 20 confirmed false triggers,
   four reported misses, and three in-progress detections. Inspect the miss anchors at 29.743,
   32.103, 50.044, and 110.871 seconds. Inspect predictions at 36.750, 48.500, 54.625, 61.000,
   62.375, 64.125, 64.875, and 71.125 seconds. Treat 61.000–64.875 seconds as one review region.
   This recording can reveal missing events or repeated decoder triggers.
2. **Review `cardeventnet-IMG_0644` second.** It contains nine confirmed false triggers, one
   reported miss, and three in-progress detections. Inspect the miss anchor at 17.510 seconds.
   Inspect predictions at 19.375, 20.375, 21.250, 54.125, 68.500, 77.250, 88.000, 90.000, and
   97.500 seconds. Treat 17.510–21.250 seconds as one review region. Together with `IMG_0090`, this
   recording accounts for 17 of the 20 confirmed false triggers.
3. **Review `cardeventnet-IMG_0635` for possible missing or shifted point events.** Inspect miss
   anchors at 46.529, 49.781, 56.286, 58.037, and 67.292 seconds, and predictions at 65.750 and
   94.125 seconds. The first four misses have low nearby scores. The 65.750 prediction and 67.292
   miss can be one timing disagreement.
4. **Review `cardeventnet-IMG_0652` for the only trick clear without a decoded trigger.** Inspect
   the reviewed interval from 21.021 to 23.021 seconds. Also inspect miss anchors at 9.509, 12.262,
   34.283, 69.066, and 73.819 seconds. Some are merged or in-progress detections; do not split one
   continuous change only to match the model.
5. **Inspect `cardeventnet-IMG_0091` as a timing-only case.** It has no confirmed false triggers.
   Inspect miss anchors at 9.217, 22.269, 60.139, 90.442, and 99.526 seconds. Four have strong
   nearby scores. Re-annotate only when the current interval start or stable end is wrong.
6. **Inspect `cardeventnet-IMG_0661` as a merge and timing case.** Inspect miss anchors at 15.013,
   25.775, 37.537, 61.308, 66.315, 74.573, and 84.833 seconds, plus the prediction at 89.250
   seconds. All seven misses have strong nearby scores. Prefer keeping valid close events over
   moving them to satisfy the current decoder gap.

The operator must inspect the complete action around each listed region, not only one frame. The
operator must keep a correct point or interval unchanged. When the reference is wrong, the operator
must start a new event-reference draft, correct the event, record full-source coverage, and publish
a new completed revision. A completed review with no changes is a valid result.

#### Commands that M10 must print for the operator

From the repository root, start the local backend in one terminal:

```bash
mise exec -- uv run --project backend dokodetector-backend
```

Start the web workspace in a second terminal:

```bash
cd web
mise exec -- npm run dev
```

Then open these routes in the printed order:

```text
http://127.0.0.1:5173/recordings/cardeventnet-IMG_0090/pipeline/events
http://127.0.0.1:5173/recordings/cardeventnet-IMG_0644/pipeline/events
http://127.0.0.1:5173/recordings/cardeventnet-IMG_0635/pipeline/events
http://127.0.0.1:5173/recordings/cardeventnet-IMG_0652/pipeline/events
http://127.0.0.1:5173/recordings/cardeventnet-IMG_0091/pipeline/events
http://127.0.0.1:5173/recordings/cardeventnet-IMG_0661/pipeline/events
```

These are interactive review commands, not long-running model tasks. Luna can prepare the packet
and verify the local commands, but only the operator can make and complete the review decisions.

Acceptance:

- the review packet is reproducible from immutable M7 and ablation artifacts;
- every review item links to one recording, exact time range, current reference revision, source
  frame evidence, model outcome, and review reason;
- adjacent outcomes from one action are grouped without hiding their original timestamps;
- the generated report prints the ordered operator checklist, both startup commands, all six
  workspace routes, and the exact artifact the operator must complete; and
- M10 stops for the operator without changing reference data or starting training.

M10 result — 2026-09-17: the packet is
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m10-timing-review.json`; the
operator completion checklist is
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m10-operator-review.json`; and
the human handoff is
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m10-report.md`. The operator
must complete the checklist before M11 validates any new reference revision.

M11 result — 2026-09-17: the operator entries contain prose region decisions in the six
recording notes, so M11 records that evidence and applies a deterministic item-level mapping. The
decision report is
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m11-reference-decisions.json`;
the successor dataset is
`data/operations/cardevent-datasets/cardeventnet-interval-dataset-00a59b5fcd210d23c569/`; the
decoder replay is
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m11-decoder-grid.json`; and
the human summary is
`data/model-campaigns/cardeventnet-0063-m9-hard-negative-ablation/m11-report.md`. The current
decoder gives 228 point matches, 49 stable-end matches, 24 detections inside intervals, 32
duplicate detections per reviewed change, 25 confirmed no-event triggers, 0.111182 seconds
median signed timestamp error, and 0.236182 seconds median causal emission delay. A longer
0.375-second peak confirmation gives 51 stable-end matches but 0.487339 seconds median causal
emission delay. M11 selects no decoder and keeps sealed-test output unread.

### M11 — Reconcile review decisions and measure decoder timing

- Start only after the operator confirms that the M10 review is complete.
- Validate each changed or confirmed maintained reference and publish a decision report that maps
  every M10 item to `reference_corrected`, `reference_confirmed`, or `no_event_confirmed`.
- Freeze and materialize a successor development dataset when any selected event revision changed.
  Preserve source groups and the sealed-test membership. Create a new immutable dataset instead of
  changing M7.
- Re-evaluate the saved checkpoint against the successor validation references. Report separately:
  point matches, stable-end matches, detections inside intervals, duplicate detections per reviewed
  change, confirmed no-event triggers, signed timestamp error, and causal emission delay.
- Replay a small declared decoder grid over the saved probability streams. Include the current
  decoder, longer peak confirmation, and one bounded burst or quiet-window decoder. Select no
  decoder after reading sealed-test output.

Acceptance:

- all human decisions have immutable revision and source lineage;
- unchanged references remain byte-identical;
- the report distinguishes event presence from stable-end readiness and never calls an interval
  interior a negative;
- the decoder grid, thresholds, timing windows, and selection rule are declared before comparison;
  and
- M11 does not train, export, promote, or read sealed test.

### M12 — Prepare one timing-response campaign

- If a decoder-only candidate meets the declared stable-end, false-trigger, duplicate-trigger, and
  latency gates, keep the checkpoint fixed and prepare that bounded decoder-only campaign.
- Otherwise implement one interval-aware temporal response. Prefer an explicit
  `transition_in_progress` signal or equivalent endpoint objective. Do not relabel interval
  interiors as ordinary or hard negatives.
- Add tests for point events, long intervals, close valid events, causal emission, and deterministic
  offline replay.
- Write one exact operator handoff command with fixed inputs, seed, device, precision, time budget,
  output paths, and resume behavior. The command may prepare data, train, evaluate validation, and
  write diagnostics. It must not read sealed test or system holdout.
- Stop before running the command. The operator runs and resumes every long training command.

Acceptance:

- the M11 decision rule selects exactly one response;
- the response changes only the declared timing axis;
- the operator handoff contains the exact long-running command and expected completion artifacts;
  and
- Luna does not start or monitor the long-running command.

### M13 — Compare and lock the timing candidate

- Start only after the operator reports that the M12 command completed.
- Validate output completeness and lineage before reading metrics.
- Compare the candidate with the M9 hard-negative checkpoint on the same successor validation
  references and declared decoder contract.
- Lock one candidate only when every validation gate passes. Otherwise retain
  `human_review_required` with exact failure reasons.
- Do not change annotations, threshold, decoder, or training recipe after reading this comparison.
- Do not read sealed test.

Acceptance:

- the report includes strict stable-end metrics and separate interval-presence diagnostics;
- the candidate decision is reproducible and uses no sealed-test or system-holdout output; and
- a lock binds the checkpoint, threshold, decoder, dataset, split, reference revisions, code, and
  environment.

### M14 — Manual sealed test, export, and handoff

- With explicit operator confirmation, write the exact one-time sealed-test command for the locked
  candidate and stop. Do not start or monitor it.
- After the operator finishes the test command, validate the result and apply the existing gates
  without changing the candidate or threshold.
- If the gates permit export, write the exact Core ML export and parity command and stop again. Do
  not start or monitor it.
- Validate the operator-produced bundle, preprocessing fixture, runtime load, parity, reports, and
  digests. Retain the checkpoint, decoder settings, model bundle, and prior champion rollback
  information under campaign-owned paths.
- Promote only when the operator confirms and every hard gate passes.
- After the campaign decision is immutable, optionally write one separate manual
  `legacy_device_diagnostic` command for `IMG_2777` through `IMG_2781`. Do not run it by default and
  do not merge its result into the campaign comparison or gate report.

Acceptance:

- test evaluation is tied to the locked checkpoint and new sealed test partition;
- each long-running action has an explicit operator handoff and no agent polling;
- the checkpoint and bundle load locally and trace to source and annotation digests;
- promotion is atomic, explicit, and recoverable; and
- an optional old-phone diagnostic is visibly non-gating and runs only after the decision; and
- the final report names the retained model, campaign outcome, remaining gaps, and the next manual
  command when one remains.

## 5. Out of scope

- changing event semantics beyond the completed canonical `card_state_changed` contract;
- semantic classification of plays, moves, removals, or trick clears;
- changing table-observation, visual-identity, or reconstruction behavior;
- using generated proposals as human ground truth;
- selecting a model or threshold with test or system-holdout results;
- cloud infrastructure or phone-only development requirements; and
- deleting the prior champion model bundle.
