# DokoDetector Shared Training Data Operations

## Plan status

- **Summary:** Capture source material once and process it independently for CardEventNet and the
  TableEvidenceAnalyzer
- **Status:** Ready
- **Depends on:** Plans 0019 and 0020, which are complete
- **Builds on:** Plan 0025 adds optional video snippets to evidence packages
- **Reviewed:** 2026-08-28 against repository baseline `e392f929d`, the implemented recording
  upload and CardEventNet review workflow, the plan 0020 data foundation, the completed plan 0025
  evidence path, and active plans 0021, 0022, and 0028
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

### 1.1 Current repository baseline

The repository already contains these parts of the workflow:

- the app records immutable `cardevent-recording/v1` bundles, queues uploads, retries failures, and
  keeps live inference and evidence-package capture active;
- the backend streams each recording into atomic local storage and stores searchable recording
  metadata in SQLite, but it cannot rebuild that metadata from the accepted bundle;
- `cardevent import-recording` copies accepted recording bytes into a component-specific raw-data
  directory and needs separate operator metadata;
- CardEventNet provides video-wide annotation, proposal queues, immutable review application,
  cache preparation, and its existing dataset tools;
- plan 0020 provides shared source, lineage, eligibility, table-observation review, dataset, split,
  coverage, and lifecycle-receipt contracts;
- the app has Live and Replay tabs. Training-recording controls are part of Live and do not have a
  reusable collection profile;
- no repository-operations package, task enrollment, repository intake root, system holdout, or
  cross-task review-run state exists.

Replace the component-specific writable recording intake with the shared repository bundle. Update
the app, backend, and cross-component fixture together. Do not keep two writable upload paths.
Historical source records can continue to resolve their current immutable artifact locations. Do
not copy or move their bytes only to match the new layout.

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

Add one task enrollment record for each source asset and data task. Support these initial data
tasks:

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

Do not add one universal `done` flag. Keep task enrollment disposition separate from the plan 0020
lifecycle state. Record lifecycle state separately for each selected data task:

```text
intake
annotating
review_required
reviewed
eligible
excluded
retired
```

A source asset can be `eligible` for CardEventNet while its TableEvidenceAnalyzer enrollment is
`deferred`. A shared permission withdrawal or source retirement affects both tasks and every
derived artifact.

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

Use this initial project shape:

```text
operations/
  pyproject.toml
  uv.lock
  src/doko_operations/
  tests/
```

Declare its Python and uv versions through the root `mise.toml`. Keep component adapters behind
typed Python interfaces so deterministic state changes have direct tests. A subprocess adapter can
call an interactive component UI, but subprocess output is not the workflow state contract.

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

Publication is atomic for each data task. With `--task all`, a failure in one task does not roll
back an already completed task. Never publish only one part of a task's dataset-and-split result.

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
3. Add one fixture selected only for CardEventNet, one selected only for table evidence, and one
   selected for both.
4. Add replacement-fixture conformance tests in Swift, the backend, and Python. Do not add optional
   aliases for fields from the old bundle.

Acceptance:

- one source asset has independent enrollment and lifecycle state for both tasks;
- changing task enrollment does not change source bytes or their digest;
- a proposal generator run does not imply CardEventNet dataset membership;
- strict round-trip and malformed-fixture tests pass in Swift, the backend, and Python;
- the replacement contract is frozen before an active producer or consumer switches to it.

### M1 — Operations package and read-only inspection

1. Add the `operations/` package and `doko` entry point.
2. Add explicit repository-root configuration and deterministic fixture discovery.
3. Implement read-only `doko data status` and `doko data validate`.
4. Report bundle completeness, task state, pending work, failures, unassigned eligible groups, and
   stale derived artifacts.

Acceptance:

- status output is stable in human and JSON forms;
- status and validation do not change repository artifacts or SQLite state;
- complete, incomplete, invalid, deferred, and independently selected fixture cases are covered;
- the commands require no model, camera, display, or network.

### M2 — Record tab and collection profiles

1. Add the dedicated app tab and collection-profile editor.
2. Persist profiles and reuse session-level defaults across recordings.
3. Add per-recording task-disposition overrides.
4. Populate complete operator-owned metadata and task enrollments before finalization.
5. Preserve the current bounded capture, live inference, evidence capture, durable queue, retry, and
   upload behavior.

Acceptance:

- several recordings reuse one session without re-entering shared metadata;
- incomplete required metadata prevents final upload with a field-level message;
- measured technical fields come only from capture and media probing;
- a per-recording override changes the emitted enrollment without changing the saved profile;
- Swift core tests cover profile persistence and overrides, and app UI-state tests cover Record-tab
  navigation and validation.

### M3 — Atomic repository bundle storage

1. Add the configured repository intake root.
2. Switch the app and backend to the replacement bundle in one change. Remove the superseded active
   upload contract and fixture.
3. Stream all upload parts into a temporary directory below the configured root.
4. Validate media, source, collection metadata, proposal lineage, and initial task enrollments before
   one atomic rename.
5. Make identical retries idempotent and reject conflicting identifiers without changing the
   accepted bundle.
6. Keep SQLite writes outside canonical bundle identity and prevent partial central metadata.

Acceptance:

- a successful upload leaves one complete, commit-ready bundle;
- interruption or validation failure leaves no visible final bundle or database row;
- an identical retry succeeds and a conflicting retry leaves the accepted bytes unchanged;
- the accepted source, manifest, proposal, source record, and enrollment hashes validate;
- no active upload producer, consumer, or fixture uses the superseded bundle contract;
- the current upload, restart, size-limit, and retry behavior remains covered.

### M4 — Rebuildable intake index and component access

1. Rebuild backend search metadata only from accepted bundle files.
2. Resolve CardEventNet source and proposal inputs directly from repository intake.
3. Remove the manual metadata-completion and `cardevent import-recording` path for new app
   recordings. Do not retain it as a second writable intake path.
4. Add Git LFS coverage for recording media at every nested intake depth.
5. Resolve historical source records at their declared artifact locations without moving or copying
   their bytes.

Acceptance:

- deleting and rebuilding SQLite does not lose or change canonical metadata;
- CardEventNet opens the accepted source and proposals without a component-specific source copy;
- a new app recording needs no metadata-completion or import command;
- Git LFS checks cover nested `.mov`, `.mp4`, and `.m4v` recording media;
- historical source-record fixtures still resolve without a legacy upload path.

### M5 — Resumable review-run orchestration

1. Define the strict review-run state and report contracts.
2. Implement `doko data review` task selection, discovery, dispatch, and atomic state updates.
3. Save after every human decision and resume at the first incomplete decision.
4. Stage task outputs until validation and any required split approval complete.
5. Print the exact next human action and the final commit-ready file list.

Acceptance:

- deterministic Python tests cover new, interrupted, resumed, complete, and failed runs;
- a completed rerun is idempotent and does not repeat decisions or overwrite immutable artifacts;
- failure before publication leaves no partial dataset or split version;
- `--task all` retains separate progress and failure state for both tasks;
- component log volume stays in run logs while the Markdown report stays concise.

### M6 — CardEventNet review adapter

1. Discover selected, unreviewed recordings from task enrollment.
2. Create or resume video-wide annotation with device or Mac proposal seeding.
3. Run required ambiguity and hard-negative queues, then apply a complete immutable review.
4. Refresh only affected cache entries and stage dataset, split-proposal, validation, receipt, and
   report artifacts for publication.

Acceptance:

- one command takes a selected fixture to staged, reviewed CardEventNet data;
- quitting and rerunning resumes at the next incomplete human decision;
- candidate-only review cannot satisfy the video-wide pass;
- deferred or excluded CardEventNet enrollment creates no review work;
- no TableEvidenceAnalyzer enrollment, lifecycle state, or artifact changes.

### M7 — Table-evidence candidate selection

1. Discover selected recordings and evidence packages.
2. Gather declared device, Mac, and reviewed-event proposal sources.
3. Add deterministic coverage, negative, and explicit operator-selected intervals.
4. Materialize immutable evidence references for frames, optional snippets, and recording ranges.
5. Write selection-source coverage and proposal generator run lineage.

Acceptance:

- every selected item names its selection source;
- proposal-selected items name the complete generator run when applicable;
- deterministic coverage finds an item absent from CardEventNet proposals;
- missing optional snippets do not invalidate selected frames;
- repeated selection with the same inputs has the same order and digest.

### M8 — Table-observation review adapter

1. Open or resume review for each selected table-evidence item.
2. Apply human decisions into new immutable table-observation annotation versions.
3. Stage dataset, coverage, split-proposal, validation, receipt, and report artifacts for
   publication.
4. Keep review progress independent from CardEventNet progress.

Acceptance:

- one command takes selected fixtures to staged, reviewed table-evidence data;
- false event proposals can retain reviewed visible-card evidence;
- incomplete review never receives `reviewed` or `eligible` lifecycle state;
- deferred or excluded table-evidence enrollment creates no review work;
- no CardEventNet dataset membership, review state, or artifact changes.

### M9 — Independent publication and system holdout

1. Define the shared system holdout registry and reviewed seal operation.
2. Validate the registry in both component split validators.
3. Publish separate frozen dataset and split versions only after explicit split approval.
4. Keep new eligible groups `unassigned` unless the approved proposal names a partition.
5. Publish both tasks independently when `--task all` has one task still incomplete or invalid.

Acceptance:

- the two datasets can include different source assets and samples;
- the same session, game, table setup, or source-lineage group cannot cross partitions within one
  task;
- a system holdout group cannot enter any component training or validation partition;
- sealing a group is explicit, reviewed, versioned, and never a review side effect;
- split approval changes no source, enrollment, annotation, or review artifact.

### M10 — Cross-task permission and retirement impact

1. Extend source permission and retirement impact analysis across both data tasks.
2. Report affected annotations, datasets, splits, caches, runs, and model bundles.
3. Mark derived artifacts stale through new versioned state or receipts. Do not edit immutable
   artifacts in place.
4. Include cross-task failures and stale artifacts in status and validation output.

Acceptance:

- permission withdrawal or source retirement reports affected artifacts in both tasks;
- changing one task enrollment does not change the other task;
- source retirement does not modify source bytes or historical artifacts;
- unrelated valid intake and unassigned groups remain usable;
- repeated impact analysis is deterministic.

### M11 — Clean-room workflow and operator exercise

Run a saved-video fixture through:

```text
collection profile
  -> recording and retryable upload
  -> repository intake and rebuilt index
  -> independent task enrollment
  -> CardEventNet review
  -> TableEvidenceAnalyzer review
  -> approved independent dataset versions and splits
  -> complete validation and commit-ready report
```

Use a scripted decision provider only in the automated test. It exercises resumption and
publication but does not create ground truth for non-fixture input. Then run the same saved source
through the app and interactive review interfaces as the required human exercise. Record the human
result in `docs/reports/0027-Shared_Training_Data_Operations_Exercise.md`.

Acceptance:

- both exercises start from one source asset copy;
- every derived artifact traces to the same source digest;
- each task can be selected, deferred, resumed, or completed independently;
- the automated gate needs no phone, camera, display, external network, GPU, or cloud service;
- the human exercise needs only the local app or simulator, local backend, saved fixture, and review
  interfaces;
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

### Automated verification

Use contract fixtures and temporary repository roots. Run:

- `mise install` after toolchain or package setup changes;
- operations-package unit, integration, formatting, lint, and type or static checks;
- affected CardEventNet tests, formatting, lint, and static checks;
- backend upload, restart, idempotency, rebuild, formatting, lint, and migration checks;
- Swift package tests for collection profiles, state, capture, queue, and upload;
- app UI-state tests for Record-tab navigation, validation, and task overrides;
- table-observation selection, review, dataset, split, coverage, and lifecycle tests;
- one headless local clean-room pipeline test with the fixture-only decision provider.

Check all local Markdown links after adding or moving plan files.

### Required human verification

Use a saved video in the local app or simulator. Reuse one collection profile for two recordings,
change one task override, confirm the field-level validation, retry one upload, and resume one
decision in each interactive review path. The exercise passes when `doko data validate` succeeds
and the generated report lists only commit-ready artifacts. Record the app and command versions,
actions, observations, and result in
`docs/reports/0027-Shared_Training_Data_Operations_Exercise.md`.

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
