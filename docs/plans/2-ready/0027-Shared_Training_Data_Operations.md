# DokoDetector Shared Training Data Operations

## Plan status

- **Summary:** Capture source material once and process it independently for CardEventNet and the
  TableEvidenceAnalyzer
- **Status:** Ready
- **Depends on:** Plans 0019 and 0020, which are complete
- **Builds on:** Plan 0025 adds optional video snippets to evidence packages
- **Reviewed:** 2026-08-27 against the implemented recording upload, CardEventNet review workflow,
  table-observation data foundation, and project glossary
- **Does not depend on:** Plan 0021 model training; data operations can proceed with existing model
  proposals and fixtures
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Outcome

Create one operator workflow for source intake and two explicit data task workflows:

```text
recording and accepted source bytes
  -> shared immutable intake
      +-> CardEventNet event-data enrollment
      |     -> video-wide event annotation and review
      |     -> CardEventNet dataset version and split
      |
      +-> TableEvidenceAnalyzer data enrollment
            -> proposal and coverage-based evidence selection
            -> table-observation annotation and review
            -> TableEvidenceAnalyzer dataset version and split
```

The source bytes, source identity, session, permission, and capture metadata exist once. Task
enrollment, annotation, review state, eligibility, dataset versions, splits, and derived artifacts
remain separate for each data task.

At the end of this plan, an operator can:

1. select shared collection metadata and initial task enrollments in a dedicated app tab;
2. capture several recordings in one session without entering the same metadata again;
3. upload each complete recording into a repository-backed immutable intake area;
4. commit the unreviewed intake without a manual import or metadata-completion command;
5. run one resumable review command for either data task;
6. finish with validated, task-specific dataset and split artifacts that are ready to commit.

The workflow does not commit or push Git changes.

## 2. Fixed architecture decisions

### 2.1 Share intake, not datasets

Store each accepted source asset once. Do not create separate CardEventNet and
TableEvidenceAnalyzer copies of the same recording.

Keep these facts shared:

- source asset, recording, session, game, and table setup identity;
- original media bytes and content digest;
- source permission and retention state;
- measured device, camera, time, resolution, frame-rate, and duration metadata;
- source lineage and duplicate findings.

Keep these artifacts separate by data task:

- task enrollment and processing state;
- event proposals and selection policies;
- annotations and reviews;
- dataset eligibility and intended use;
- dataset versions and splits;
- caches and other derived artifacts;
- training and evaluation runs.

Changing one task's enrollment or review state must not change the other task.

### 2.2 Select processing explicitly

Add one task enrollment record for each source asset. Support these initial data tasks:

```text
cardevent_event_detection
table_evidence_analysis
```

Each task has an explicit disposition:

```text
selected
deferred
excluded
```

`selected` requests processing. `deferred` preserves the source for later work without creating a
review burden. `excluded` records an operator decision and reason. An operator can create a new
task enrollment version later without modifying the source asset.

Task enrollment is not dataset eligibility. A selected source must still pass metadata, permission,
annotation, review, duplicate, lineage, and split checks.

### 2.3 Treat CardEventNet as an optional proposal generator

Running CardEventNet on a source asset does not enroll that source in the CardEventNet dataset.
CardEventNet can act only as a proposal generator for TableEvidenceAnalyzer review.

Record for every proposal run:

- source asset and recording identifiers;
- model bundle and weights digest;
- decoder, preprocessing, and sampling configuration;
- device or Mac execution environment;
- probability stream and event proposals;
- proposal generator run identifier and output digest.

Table-observation ground truth comes from human review of the source evidence. It does not come
from CardEventNet. Preserve the proposal generator run lineage because it explains how the evidence
was selected.

### 2.4 Use more than CardEventNet proposals

Do not let CardEventNet define all TableEvidenceAnalyzer coverage. Build review candidates from a
declared mixture of:

- on-device CardEventNet event proposals;
- Mac CardEventNet event proposals;
- reviewed events from video-wide annotation;
- deterministic time or coverage sampling;
- motion or other declared proposal generators;
- explicit operator-selected difficult and negative intervals.

The review and coverage reports group samples by selection source. A false event proposal can still
contain useful visible-card evidence. A missed CardEventNet event must remain discoverable through
another selection source.

### 2.5 Use task-specific state

Do not add one universal `done` flag. Record the implemented plan 0020 lifecycle state separately
for each data task:

```text
intake
annotating
review_required
reviewed
eligible
excluded
retired
```

A source asset can be `eligible` for CardEventNet and `deferred` for the TableEvidenceAnalyzer. A
shared permission withdrawal or source retirement affects both tasks and every derived artifact.

### 2.6 Keep component splits separate and reserve a system holdout

Build CardEventNet and TableEvidenceAnalyzer dataset versions and splits independently. Both use the
shared session, game, table-setup, and source-lineage groups from plan 0020.

Add one shared system holdout registry. A source-lineage group in the system holdout cannot enter
training or model selection for any component. Do not automatically add new source assets to it.
Only an explicit, reviewed operation can seal a group for end-to-end evaluation.

New eligible data defaults to `unassigned`. A split policy can propose train or validation
assignment, but the operator approves the change. Never extend or rebalance a sealed test partition
as a side effect of review.

## 3. Operator interface

Add a small repository-operations Python package with one `doko` entry point. It composes existing
data contracts and component commands. It must not create a second source, annotation, dataset, or
split contract.

The intended commands are:

```bash
doko data status
doko data review --task cardevent_event_detection --reviewer <name>
doko data review --task table_evidence_analysis --reviewer <name>
doko data review --task all --reviewer <name>
doko data validate
```

The public command can call stable Python APIs or subprocess component commands. Every state change
must still be available through a deterministic Python function with direct tests.

`doko data status` is read-only. It reports:

- complete and incomplete intake bundles;
- task enrollment and lifecycle state;
- pending and resumable review work;
- validation or permission failures;
- unassigned eligible source groups;
- derived artifacts that are stale relative to their inputs.

## 4. App recording workflow

Add a dedicated **Record** tab beside Live and Replay. Use a collection profile that supplies
session-level defaults for several recordings.

Before capture, require or select:

- an existing or new session;
- real game or staged activity;
- game ID when the activity belongs to a game;
- table setup and deck design;
- camera view, movement, and framing;
- lighting and background;
- source permission;
- expected scenario tags and known limitations;
- initial disposition for both data tasks.

Measure device, camera, source size, orientation, frame rate, duration, timestamps, model version,
decoder version, byte lengths, and hashes automatically.

Let the operator adjust scenario tags and notes after capture but before final upload. Do not ask
the operator to enter measured technical facts. Reuse the collection profile until the operator
changes the session or physical setup.

Keep live inference and evidence-package capture available during a training recording. A task can
be deferred even when the app still runs CardEventNet to create device proposals.

## 5. Repository-backed intake

Add an explicit backend `repository_intake_root`. In local development, point it at a repository
path such as:

```text
data/intake/recordings/<recording-id>/
  manifest.json
  videos/<video-id>.mov
  predictions/<prediction-run-id>.json
  source-record.json
  initial-task-enrollment.json
```

The exact local path is an artifact location, not semantic identity. Keep `source_asset_id`,
`recording_id`, `video_id`, and proposal generator run identity separate.

The backend must:

1. stream uploads into a temporary directory below the configured intake root;
2. validate filenames, schemas, sizes, media, hashes, metadata, and task enrollment;
3. atomically rename only a complete bundle;
4. reject conflicting identifiers without modifying the accepted bundle;
5. create no partial central manifest update;
6. rebuild searchable SQLite state from committed bundles;
7. leave Git staging, commits, and pushes to the operator.

Track nested recording media with Git LFS. Do not keep a second authoritative video copy under
`backend/.runtime` or a component-specific raw directory. Existing source assets can keep their
current artifact locations; do not move all historical media only to normalize paths.

## 6. CardEventNet data task workflow

For each selected source asset:

1. validate the source and task enrollment;
2. create or resume a video-wide annotation seeded by available device or Mac proposals;
3. require a complete video pass so missed event proposals can be found;
4. create and review targeted queues for ambiguity and hard negatives when required;
5. apply complete decisions into a new immutable annotation version;
6. build or refresh only the CardEventNet cache affected by the new annotation version;
7. assemble and validate a CardEventNet dataset version;
8. propose group-safe split changes while leaving new groups unassigned by default;
9. write lifecycle receipts and a review-run report.

Candidate-only device queues never satisfy the complete video-review requirement by themselves.

## 7. TableEvidenceAnalyzer data task workflow

For each selected source asset:

1. validate the source and task enrollment;
2. gather or run the declared proposal generators;
3. add deterministic coverage and negative samples;
4. materialize bounded evidence references without changing source bytes;
5. create or resume table-observation review;
6. apply review into new immutable table-observation annotation versions;
7. assemble the TableEvidenceAnalyzer dataset and coverage reports from reviewed observations;
8. propose a group-safe split while leaving new groups unassigned by default;
9. write lifecycle receipts and a review-run report.

The workflow must support selected frames, evidence-package frames, optional video snippets, and
time ranges in a complete recording. A missing snippet means that motion evidence is unavailable;
it does not make valid selected frames unusable.

## 8. Resumption, failure, and output rules

Each review invocation creates or resumes one versioned review-run state file. It records the exact
inputs, current item, completed human decisions, produced versions, validation results, and
remaining work.

The command must:

- save after every human decision;
- resume without repeating completed decisions;
- be idempotent after successful completion;
- stop before partial dataset or split publication;
- never mark an incomplete review as `reviewed`;
- keep source, proposal, annotation, review, and dataset artifacts immutable;
- print the next required human action when it cannot continue;
- finish with a concise list of files that are ready to commit.

Do not hide large command output in the human report. Store logs beside the review-run state and put
only summaries and actionable failures in Markdown.

## 9. Small implementation milestones

### M0 — Shared intake and task enrollment contracts

1. Freeze task identifiers, dispositions, strict schemas, and typed models.
2. Define the repository bundle and proposal generator run lineage contracts.
3. Add the system holdout registry contract and cross-task leakage checks.
4. Add one fixture selected only for CardEventNet, one selected only for table evidence, and one
   selected for both.
5. Add read-only `doko data status` over the fixtures.

Acceptance:

- one source asset can have independent state for both tasks;
- changing task enrollment does not change source bytes or their digest;
- a proposal generator run does not imply CardEventNet dataset membership;
- a system holdout group is rejected from every component training split;
- status output is deterministic and requires no model, camera, or network.

### M1 — Record tab and complete collection profiles

1. Add the dedicated app tab and collection-profile editor.
2. Persist profiles and reuse session-level defaults across recordings.
3. Add per-recording task-disposition overrides.
4. Populate complete operator-owned metadata before upload.
5. Preserve the current durable capture, finalization, retry, and upload behavior.

Acceptance:

- several recordings can reuse one session without re-entering shared metadata;
- incomplete required metadata prevents final upload with a clear field-level message;
- measured technical fields come from capture and media probing;
- deferred tasks do not create review work;
- Swift unit and UI state tests cover profile reuse and task overrides.

### M2 — Atomic repository intake

1. Add the configured repository intake root.
2. Store one complete fixture bundle atomically in it.
3. Remove the manual metadata-completion and `import-recording` step for new app recordings.
4. Rebuild backend search metadata from accepted bundle files.
5. Add Git LFS coverage for nested recording media.

Acceptance:

- a successful upload leaves one commit-ready bundle and no authoritative duplicate;
- interruption or validation failure leaves no visible final bundle;
- an identical retry succeeds and a conflicting retry fails;
- deleting the rebuildable SQLite database does not lose canonical metadata;
- existing historical source records still resolve without moving their bytes.

### M3 — One-command CardEventNet review

1. Discover selected unreviewed recordings.
2. Create or resume video-wide annotation with proposal seeding.
3. Run required queue review and immutable review application.
4. Refresh affected cache entries and dataset reports.
5. Write a split proposal, validation result, receipts, and review-run report.

Acceptance:

- one command takes a fixture from selected intake to reviewed CardEventNet data;
- quitting and rerunning resumes at the next incomplete decision;
- candidate-only review cannot mark the video-wide pass complete;
- no TableEvidenceAnalyzer enrollment or state changes;
- the resulting source, annotation, dataset, and split lineage validates.

### M4 — One-command TableEvidenceAnalyzer review

1. Discover selected unreviewed recordings and evidence packages.
2. Combine device, Mac, reviewed-event, and deterministic coverage candidates.
3. open or resume table-observation review for each selected item;
4. apply reviewed annotations and assemble dataset coverage;
5. write a split proposal, validation result, receipts, and review-run report.

Acceptance:

- one command takes fixtures from selected intake to a reviewed table-evidence dataset version;
- every sample names its selection source and proposal generator run lineage when applicable;
- deterministic coverage finds an item absent from CardEventNet proposals;
- no CardEventNet dataset enrollment or state changes;
- false event proposals can retain reviewed visible-card evidence.

### M5 — Independent dataset publication and shared holdout

1. Publish separate frozen dataset and split versions for both tasks.
2. Add reviewed approval for proposed split changes.
3. Enforce the shared system holdout in both split validators.
4. Report unassigned eligible groups without failing unrelated intake.
5. Add cross-task source and permission impact reporting.

Acceptance:

- the two datasets can include different source assets and samples;
- the same session cannot cross partitions within one task;
- a system holdout group cannot enter any component's training or validation partition;
- source retirement reports affected artifacts in both tasks;
- split approval never changes source or review artifacts.

### M6 — Clean-room operator exercise

Run a saved-video fixture through:

```text
collection profile
  -> recording and retryable upload
  -> repository intake
  -> independent task enrollment
  -> CardEventNet review
  -> TableEvidenceAnalyzer review
  -> two dataset versions and splits
  -> complete validation and commit-ready report
```

Acceptance:

- the exercise starts from one source asset copy;
- every derived artifact traces to the same source digest;
- each task can be selected, deferred, resumed, or completed independently;
- ordinary automated gates need no phone, camera, external network, GPU, or cloud service;
- the operator invokes no manual import, cache, apply-review, dataset-build, or split command.

## 10. Out of scope

- automatic acceptance of model proposals as ground truth;
- automatic Git commit or push;
- automatic assignment to a sealed test or system holdout;
- model architecture selection or training experiments;
- remote multi-user review and authentication;
- production retention periods and hosted object storage;
- moving all historical raw media only to normalize its local path.

## 11. Verification

Use contract fixtures and temporary repository roots for ordinary tests. Run:

- operations-package unit and integration tests;
- affected CardEventNet tests and static checks;
- backend upload, restart, idempotency, and rebuild tests;
- Swift package tests for collection profiles, state, capture, queue, and upload;
- table-observation review, dataset, split, coverage, and lifecycle tests;
- one local clean-room pipeline test.

Check all local Markdown links after adding or moving plan files.

## 12. Definition of done

- recording capture produces complete, repository-backed, commit-ready unreviewed intake;
- source bytes and shared metadata exist once;
- both data tasks have explicit and independent enrollment and lifecycle state;
- CardEventNet proposals remain candidates with complete generator lineage;
- each task has one resumable review command and separate dataset and split versions;
- proposal-independent sampling protects table-evidence coverage;
- the system holdout is enforced across components;
- source permission and retirement affect all linked data;
- the full local workflow is reproducible without hidden operator commands.
