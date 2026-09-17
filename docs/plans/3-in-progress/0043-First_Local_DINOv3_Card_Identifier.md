# First local DINOv3 card identifier

## Plan status

- **Summary:** Train one local DINOv3 visual card classifier from the latest completed human
  references and prove that its exported bundle runs locally.
- **Status:** In Progress
- **Depends on:** Plans 0041, 0042, 0048, 0049, and 0062 complete
- **Builds on:** The DINOv3 training and bundle capability from 0041, the maintained references and
  dataset boundary from 0048/0049, and the 25-class visual-classification contract from 0062
- **Outcome:** Freeze the completed annotations available when training starts, train one bounded
  frozen-encoder DINOv3 candidate on MPS, export a verified bundle, and run it through the local
  classifier boundary. Keep the bundle unpromoted and keep Gemini as the backend default.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — add a read-only current-corpus readiness and prerequisite preflight.
- **M1:** Complete — freeze and materialize the latest eligible reviewed corpus.
- **M2:** Ready for operator — validate one frozen campaign and run one bounded local training command.
- **M3:** Not started — export, evaluate, and run the first local bundle.

## Planning decision — 2026-09-17

Make the first locally running reviewed model the immediate goal. Do not wait for the live 0051
resilience comparison or a possible 0052 response. Those epics can later supply another crop policy
or augmentation condition. They do not prevent a first candidate from using the current reviewed
`predicted_visible_region` crops.

The data selection stays open while review continues. M0 reports current coverage but does not
freeze membership. M1 resolves the current selected completed references once, immediately before
training, and writes their exact revision and content digests. A reference completed after that
freeze belongs to a later dataset version. It never changes this run.

This epic trains one candidate. It does not compare architectures, partially fine-tune the encoder,
calibrate rejection, use the system holdout, promote a model, or change a backend default. Later
quality and productive-operation work must use the retained M3 report instead of treating this
first candidate as production-ready.

## 1. Current evidence

### M0 progress — 2026-09-17

M0 is complete. The operations CLI now provides the read-only
`data dinov3-identity-preflight` command. It discovers the selected split, current completed
references, source bundles, revision digests, paired visible-card lineage, source groups, holdout
exclusions, DINOv3 package and license prerequisites, and the memory-only MPS batch probe. It prints
the exact revision IDs that would be frozen and blocks when a required input is missing. It does not
write crops, datasets, checkpoints, or model bundles. Generated tests cover deterministic read-only
reports, repository-relative split resolution, and FACE_DOWN exclusion with retained revision IDs.

### M1 progress — 2026-09-17

M1 is complete. The operations CLI now provides the bounded
`data dinov3-identity-prepare` command. It repeats the M0 gate, freezes the selected revision and
source digests, resolves exact reviewed frames, reproduces the approved visible-region PPM crops,
and verifies every crop digest before publishing one immutable campaign directory. The directory
contains the manifest, coverage, dataset, split, artifact index, frame and crop inventory, resolved
recipe, and training preflight. The manifest records the full M2 command but preparation never
starts training. Generated tests verify atomic publication and byte-identical repeated preparation
from the same inputs.

The 2026-09-17 read-only scan found nine selected completed visual-identity references with 1,093
review outcomes:

| Current partition | Recordings | Classified | `FACE_DOWN` | Unusable or failed |
| --- | ---: | ---: | ---: | ---: |
| Train | 5 | 554 | 122 excluded | 11 |
| Validation | 3 | 301 | 0 | 0 |
| Unassigned (`IMG_0661`) | 1 | 100 | 4 excluded | 1 |

The five training recordings have 20 to 38 reviewed examples for each of the 20 suit-and-rank
classes in `doko-40-v1`. The three separate validation recordings have 11 to 20 examples for each
of those classes. The largest training recording supplies 129 of 554 included targets, or 23.3%.
The corpus therefore meets the first-run face-up gate: at least 20 train and 5 validation examples
per `doko-40-v1` identity, at least five training recordings, at least two validation recordings,
and no training recording above 40%.

The strict classifier vocabulary remains the 24 canonical suit-and-rank identities plus
`FACE_DOWN`, as required by 0062. The current recordings use `doko-40-v1`, so they have no `NINE`
examples. Exclude all 126 current `FACE_DOWN` outcomes from the first campaign. Most come from
untidy stacks that have not received trustworthy ignore-region treatment, so their crop and
instance lineage is not suitable for classifier training. Do not materialize their crops or use
them in coverage, fitting, checkpoint selection, or metrics. The first candidate therefore has no
measured `FACE_DOWN` capability. M0 and M1 must show the exclusion and the five unsupported classes.
Do not move `IMG_0661` into validation implicitly. A partition change must be explicit and
group-safe.

### M2 progress — 2026-09-17

The M2 training boundary is implemented. The short
`data dinov3-identity-train-preflight` command verifies the frozen campaign manifest, dataset,
split, artifact index, crop bytes, and training preflight before it prints one concrete operator
command. The training command now accepts the M1 manifest, consumes its verified crop cache without
re-materializing samples, rejects recipe or input drift, and records the campaign ID, revision
content digests, recipe digest, code revision, environment, pretrained-file digests, and resumable
checkpoint state in `run.json`. It does not download weights or start a long run during this
implementation phase.

The current checkout has no ready real-data M1 campaign, so no operator training command was
issued. A real M2 run remains pending after the operator prepares the campaign and completes the
short handoff check.

## 2. Fixed first-run recipe

Use the existing official `facebook/dinov3-vits16-pretrain-lvd1689m` ViT-S/16 revision, verified
local pretrained files, 224 x 224 letterbox transform, deterministic identity-preserving
augmentation, and 25-class target map. Freeze the encoder and train only one linear head.
Retain the 25-class output contract, but fit this candidate only with reviewed face-up card
identities. A later campaign needs a separately reviewed face-down corpus before it can claim or
select `FACE_DOWN` behavior.

Use these fixed training values unless M0 proves that one is not locally executable:

- seed `17`;
- MPS with FP32 and no silent CPU fallback;
- AdamW, learning rate `0.001`, and weight decay `0`;
- batch size selected by a short M0 memory preflight, then frozen in the campaign manifest;
- at most 20 epochs; and
- best checkpoint selected by validation top-1 accuracy.

M0 can reduce the batch size after an explicit out-of-memory preflight. It cannot change the model,
head, optimizer, input transform, target map, or candidate count. An interrupted run resumes only
from a checkpoint with identical frozen inputs and semantic configuration.

## 3. Operator boundary

The agent must not run the real weight download or M2 training process. Before either long-running
operation, the agent must finish all short preflight checks and give the operator one exact command
with concrete repository-relative paths and frozen arguments. The agent must not give placeholders,
shell variables, globs, or an open-ended command template.

After the operator reports completion, the agent validates the recorded run and continues. If the
command fails, the operator supplies the terminal output and retained run path. The agent diagnoses
the failure and gives one exact resume or replacement command. It does not start the command itself.

## 4. Delivery milestones

### M0 — Preflight current data and local prerequisites

- Add one read-only campaign preflight over current selected completed visual-card and
  visual-identity references.
- Report counts by partition, recording, class, outcome, crop policy, and source-lineage group.
- Validate source permissions, active retention, video and revision digests, paired visible-card
  lineage, group separation, and exclusion of test and system-holdout sources.
- Validate the pinned DINOv3 license record, local pretrained files, package lock, MPS availability,
  and a small memory-only batch-size probe.
- Print the exact revision IDs that would be frozen, but do not publish the dataset.

Acceptance:

- the report discovers newly completed eligible references without a checked-in recording list;
- train and validation membership come from the selected split version, not identifier order;
- the report enforces the first-run face-up gate, reports absent `NINE` support, and reports every
  excluded `FACE_DOWN` outcome with its source revision;
- no crop, dataset, checkpoint, or model bundle is written; and
- tests use generated revisions and model doubles without gated weights or network access.

### M1 — Freeze and materialize the training corpus

- Add one bounded campaign-preparation command that repeats M0 and atomically freezes the currently
  eligible completed revisions.
- Aggregate the per-recording pipeline dataset projections into the existing DINOv3 dataset,
  split, artifact-index, and crop inputs. Do not add a second label or split contract.
- Reproduce crop bytes from original recording video, exact frame identity, reviewed geometry, and
  the frozen `predicted_visible_region` crop policy. Verify every recorded crop digest.
- Write one immutable campaign manifest, coverage report, dataset, split, artifact index, crop
  inventory, resolved recipe, and training preflight below
  `data/operations/dinov3-identity-campaigns/<campaign_id>/`.
- Reject later input drift, protected sources, unassigned sources, incomplete references,
  misaligned visible-card inputs, unusable results, failures, digest mismatches, and any attempt to
  include a `FACE_DOWN` outcome.

Acceptance:

- the freeze includes every eligible reference completed before the command resolves selection
  pointers and none completed later;
- repeated preparation with the same inputs returns the same campaign identity and bytes;
- train and validation have no protected source-group overlap;
- every training item resolves to one verified PPM crop and one reviewed face-up identity in the
  strict 25-class target map;
- no `FACE_DOWN` crop is materialized or included in the dataset, split, or artifact index;
- coverage reproduces from item rows and names all unsupported classes; and
- the manifest records the complete M2 command arguments without starting training.

### M2 — Train one frozen-encoder candidate

- Run only the frozen-encoder plus linear-head recipe from the M1 campaign.
- The agent performs short validation first, then gives the operator the exact
  `mise exec -- uv run --project table_evidence_analyzer --group training table-analyzer
  train-dinov3-identity ...` command with all concrete paths and arguments.
- Retain running, completed, interrupted, and failed records plus resumable checkpoints.
- Do not start a second seed, partial fine-tune, hyperparameter search, or automatic retry.

Acceptance:

- the operator, not the agent, runs the long training command;
- the run binds the campaign, revisions, dataset, split, crops, recipe, code, environment, and
  pretrained-file digests;
- MPS is used without silent fallback and losses and predictions remain finite;
- the best checkpoint reloads and reproduces its recorded validation rows; and
- a failure leaves enough state for the agent to provide one exact resume command.

### M3 — Export and run the local bundle

- Export the best checkpoint as the existing self-contained digest-checked DINOv3 bundle.
- Re-run prediction from the exported bundle over every validation crop and publish top-1, top-3,
  macro F1, per-class support, confusion, latency, and unsupported-class coverage.
- Run one retained reviewed crop and one newly materialized eligible crop through the local
  `CardIdentityClassifier` boundary on MPS.
- Run one fixture recording through the local backend identity mode without changing the default.
- Publish a concise report and retain the bundle as an unpromoted development candidate.

Acceptance:

- the exported bundle reloads and verifies every file digest;
- exported-bundle predictions reproduce the checkpoint predictions within a declared tolerance;
- the report does not score absent `NINE` or intentionally excluded `FACE_DOWN` classes as if
  measured;
- the normal local classifier and backend boundaries return schema-valid results with bundle
  lineage; and
- Gemini remains the backend default and no champion or promotion record is changed.

## 5. Verification

Run focused operations and TableEvidenceAnalyzer tests, Ruff, format checks, lock checks, CLI help,
dataset and split validation, bundle reload, deterministic prediction, and backend local-mode tests.
Use generated model doubles for automated tests. Only the operator runs gated weight acquisition and
the real M2 training command.
