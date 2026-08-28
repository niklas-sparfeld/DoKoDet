# DokoDetector Model Improvement and Promotion

## Plan status

- **Summary:** Run bounded component experiments, compare them reproducibly, and promote a new
  champion model bundle through one operator command
- **Status:** Ready
- **Depends on:** Completed plans 0021 and 0027
- **Can start with:** Existing CardEventNet training, evaluation, export, and historical experiment
  reports while the dependent TableEvidenceAnalyzer path is completed
- **Builds on:** Plans 0012, 0015, and 0020 provide experiment, comparison, and lifecycle patterns
- **Reviewed:** 2026-08-27 against the current CardEventNet commands and plan 0021 run contracts
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## 1. Outcome

Provide one deterministic improvement workflow per model component:

```bash
doko model improve card-event-net --recipe <recipe>
doko model improve table-evidence-analyzer --recipe <recipe>
```

Each command:

1. validates and freezes its dataset, split, source, annotation, and review versions;
2. evaluates the current champion model bundle on the same current validation data;
3. runs a bounded set of declared candidate experiments;
4. evaluates and compares every successful candidate;
5. writes machine-readable results and a concise recommendation report;
6. locks one candidate or recommends keeping the champion;
7. uses the sealed test partition only after candidate selection is complete;
8. asks for explicit confirmation before model promotion;
9. exports, validates, records, and smoke-tests a promoted bundle.

The Python workflow owns experiment execution, gates, state, and model promotion. An optional Codex
skill can prepare recipes and explain reports. The skill must use the same public commands and must
not be the only implementation of any state change.

## 2. Fixed architecture decisions

### 2.1 Keep one champion per component

Maintain separate champion model bundles for:

```text
card-event-net
table-evidence-analyzer
```

A component registry entry records:

- component and capability identifier;
- champion bundle identifier and digest;
- runtime and input-contract versions;
- dataset, split, annotation, and review versions used for training;
- validation and sealed-test report identifiers;
- export environment and compatibility;
- model promotion receipt and decision note.

Do not use one global “best model.” A TableEvidenceAnalyzer identity classifier cannot replace a
CardEventNet event detector. Later analyzer capabilities can have separate champion entries when
their inputs, outputs, or gates differ.

### 2.2 Use checked-in experiment recipes

Every improvement campaign consumes one strict, versioned recipe. The recipe declares:

- component, task, and capability;
- baseline champion model bundle;
- frozen dataset and split versions;
- source annotation and reviewed-hard-negative versions when applicable;
- allowed experiment axes and candidate configurations;
- seeds and repeat policy;
- maximum candidate count, compute time, and failure budget;
- requested device and precision;
- validation metrics and promotion-gate profile;
- export and runtime compatibility checks;
- whether a sealed-test evaluation is authorized after candidate lock.

Resolve the full recipe before training starts. Write its digest to every run. Do not let an agent
or executor add undeclared candidates after seeing sealed-test results.

### 2.3 Compare on identical current data

When training data or annotations change, old recorded metrics are not a valid direct comparison.
Evaluate the champion model bundle on the candidate's frozen validation version before comparing it
with candidates.

Reject or report an explicit incompatibility when the champion cannot consume the new data
contract. Do not silently compare metrics from different dataset, split, target, preprocessing, or
decoder versions.

Use validation for model, threshold, decoder, and configuration selection. Do not use test or
system holdout results to choose another candidate.

### 2.4 Keep experiments bounded and attributable

Each candidate changes one declared experiment family unless the recipe explicitly defines a
factorial comparison. Record code revision and dirty state. Preserve failed and interrupted runs.

The runner stops when:

- the candidate or time budget is exhausted;
- required data or compatibility validation fails;
- no candidate passes minimum validity gates;
- a human review condition is detected;
- the next candidate depends on sealed-test feedback;
- the operator cancels the campaign.

Routine deterministic failures can be reported and skipped when the recipe permits it. Do not hide
failed candidates from the final report.

### 2.5 Separate selection, test, and promotion

Use three explicit phases:

```text
validation comparison -> candidate lock -> sealed test -> model promotion
```

Candidate lock records the chosen configuration, checkpoint, threshold or decoder settings,
dataset, split, code revision, and validation reports. No further candidate can enter that campaign
after lock.

Run the component test partition once when the recipe authorizes it. Run the shared system holdout
only for a locked end-to-end system evaluation, not for routine component selection.

Model promotion requires explicit operator confirmation. A poor sealed-test result produces a
`human_review_required` recommendation and ends the campaign. It never starts another experiment.

### 2.6 Keep deployment separate

Model promotion updates the repository champion registry and approved local bundle. It can update a
checked-in app model only after export and app compatibility checks pass. It does not deploy to a
production service, change remote infrastructure, or remove the previous champion bundle.

Keep the prior champion available for rollback until a separate retention decision removes it.

## 3. Operator interface

Extend the plan 0027 `doko` operations CLI:

```bash
doko model status
doko model improve card-event-net --recipe experiments/cardevent/<name>.yaml
doko model improve table-evidence-analyzer --recipe experiments/table-analyzer/<name>.yaml
doko model resume <campaign-id>
doko model compare <campaign-id>
doko model promote <campaign-id> --candidate <candidate-id>
```

`model status` and `model compare` are read-only. `model improve` can prompt for model promotion
only after all required reports and gates exist. The non-interactive form ends after the
recommendation unless the operator separately invokes `model promote`.

Every command supports stable JSON output in addition to concise human output.

## 4. Campaign state and artifacts

Create one campaign directory:

```text
data/model-campaigns/<campaign-id>/
  campaign.json
  resolved-recipe.yaml
  champion-evaluation.json
  candidates/<candidate-id>/run-reference.json
  comparison.json
  report.md
  lock.json
  test-evaluation.json
  promotion-receipt.json
  logs/
```

Large checkpoints, caches, plots, and transient logs can remain in ignored output locations. The
campaign record references them by identifier and digest. Keep the resolved recipe, comparison,
recommendation, lock, final test result, and promotion receipt as reviewable artifacts.

Campaign state is explicit and resumable:

```text
created
validated
running
compared
candidate_locked
tested
promotion_recommended
keep_champion_recommended
human_review_required
promoted
failed
cancelled
```

An interrupted process resumes from the last complete artifact. It does not repeat a successful
training run or sealed-test evaluation.

## 5. Promotion gates

Define task-specific gate profiles as checked-in configuration. Each profile contains hard failures,
non-inferiority limits, and ranked selection metrics.

Initial CardEventNet gates cover:

- event recall, precision, and F1 at the validation-selected operating point;
- false events per hour;
- worst-video and important scenario-group results;
- timestamp and causal confirmation delay;
- reviewed hard-negative behavior;
- model size, inference latency, Core ML export, and device parity;
- regression fixtures and decoder compatibility.

Initial TableEvidenceAnalyzer identity-capability gates cover:

- top-1 and top-k visual card identity accuracy;
- per-identity counts and confusion;
- worst deck-design, device, table-setup, visibility, glare, blur, perspective, and occlusion groups
  when they have declared minimum support;
- high-confidence errors and unusable-sample handling;
- model size, inference latency, bundle integrity, and runtime loading;
- stable `table-observation/v1` adapter output for the plan 0006 fixture.

Later analyzer capabilities add their own gates. Do not average unrelated capability metrics into
one score.

The report shows every failed, passed, and non-applicable gate. A recommendation cannot hide a
hard-gate failure behind a better aggregate metric.

## 6. Recommendation rules

The deterministic comparator produces one of:

```text
promote_candidate
keep_champion
human_review_required
no_valid_candidate
```

The Markdown report explains:

- what data and code changed;
- which candidates ran, failed, or were skipped;
- champion and candidate metrics on identical validation data;
- per-group improvements and regressions;
- resource, export, and runtime differences;
- passed and failed promotion gates;
- whether sealed test was run and why;
- the recommended action and remaining uncertainty.

The recommendation must be reproducible from `comparison.json`. Narrative text cannot override the
machine-readable result.

## 7. Model-promotion operation

After explicit confirmation, model promotion:

1. validates the locked candidate and all referenced digests again;
2. validates the sealed-test authorization and result;
3. exports the component bundle from the locked checkpoint;
4. loads the exported bundle through the runtime-only interface;
5. runs component contract and fixture smoke tests;
6. runs app export parity when the component is embedded in the app;
7. writes the model promotion receipt;
8. atomically updates the component champion registry entry;
9. retains the former champion for rollback;
10. prints the exact files ready to commit.

If any step fails, the registry and app bundle remain unchanged. Do not partially promote a model.

## 8. End-to-end system evaluation

Add a separate composed evaluation after both component bundles and the reconstruction configuration
are locked. Use only the system holdout from plan 0027.

The evaluation runs:

```text
source evidence
  -> CardEventNet event proposals
  -> evidence selection
  -> TableEvidenceAnalyzer observations
  -> game reconstruction
  -> system report
```

Record failures at each boundary. Do not attribute a missed event to the TableEvidenceAnalyzer or a
wrong card identity to CardEventNet. A system holdout failure can block release or request human
review, but it cannot start another candidate within the completed promotion campaign.

End-to-end product gates remain part of future production-readiness work in plan 0024. This epic
provides the reproducible local evaluation and report mechanics.

## 9. Optional Codex skill

After the Python workflow passes its clean-room exercise, add a project-local model-improvement
skill. The skill can:

- inspect dataset coverage, past campaigns, and failure reports;
- propose a bounded experiment recipe;
- explain why each experiment axis is useful;
- invoke `doko model improve`, resume, status, and compare;
- summarize the deterministic report for the operator;
- prepare a proposed follow-up epic when human research is required.

The skill must not:

- edit resolved recipes after a campaign starts;
- accept model proposals as labels;
- choose candidates from test or system holdout results;
- change champion registry files directly;
- bypass promotion gates or confirmation;
- hide commands needed to reproduce its work without the skill.

The normal model workflow must remain fully usable when Codex is unavailable.

## 10. Small implementation milestones

### M0 — Registry, recipe, campaign, and report contracts

1. Add strict typed contracts for the champion registry, recipes, campaign state, comparison,
   candidate lock, and promotion receipt.
2. Add task-specific promotion-gate profiles with fixture thresholds.
3. Add deterministic human and JSON renderers.
4. Add `doko model status` and `doko model compare` over fixtures.
5. Add corrupted, stale, incompatible, interrupted, and partially promoted fixtures.

Acceptance:

- identical inputs produce identical comparison and recommendation results;
- different dataset or split digests cannot be compared silently;
- one registry can hold independent component champions;
- a hard-gate failure prevents `promote_candidate`;
- read-only commands do not change campaign or registry state.

### M1 — CardEventNet campaign runner

1. Adapt existing CardEventNet train, evaluate, diagnose, hard-negative, and export commands.
2. Re-evaluate the champion on the campaign validation version.
3. Run bounded candidates and preserve every result or failure.
4. Lock the validation-selected checkpoint, threshold, and decoder settings.
5. Write a complete comparison and recommendation report.

Acceptance:

- one small fixture campaign runs locally with a bounded sample count;
- resumption does not repeat completed candidates;
- champion and candidates use identical validation inputs;
- candidate selection reads no test metrics;
- the current manual command sequence is reproducible from campaign artifacts.

### M2 — CardEventNet promotion path

1. Add authorized one-time test evaluation after candidate lock.
2. Add Core ML export, runtime load, parity, and iOS fixture checks.
3. Add atomic registry and checked-in bundle update.
4. Retain and identify the former champion.
5. Add failure compensation at every promotion step.

Acceptance:

- a passing fixture campaign can promote after explicit confirmation;
- a poor test result stops with `human_review_required`;
- promotion failure leaves registry and app bundle unchanged;
- repeated promotion of the same campaign is idempotent;
- the receipt traces the bundle to source, data, split, code, run, and test versions.

### M3 — TableEvidenceAnalyzer campaign adapter

Start after plan 0021 provides stable train, evaluate, checkpoint, and export contracts.

1. Adapt the plan 0021 run and capability-bundle artifacts.
2. Add identity-capability validation and group metrics.
3. Re-evaluate the analyzer champion on the campaign validation version.
4. Run and compare bounded candidates.
5. Lock and report one candidate without claiming unsupported capabilities.

Acceptance:

- the adapter uses plan 0020 dataset and split versions without directory scans;
- the campaign records the analyzer capability and runtime contract;
- missing group support is reported, not converted to a passing metric;
- a crop classifier is never reported as complete table analysis;
- candidate selection uses validation only.

### M4 — TableEvidenceAnalyzer promotion path

1. Add one-time test evaluation for a locked analyzer candidate.
2. Export and validate the versioned capability bundle.
3. Load it through the runtime-only package interface.
4. Run the plan 0006 observation-fixture integration.
5. Atomically update the analyzer champion registry entry.

Acceptance:

- bundle hashes and compatibility validate before registry change;
- a promoted bundle loads without training data or modules;
- the declared capability output remains schema-valid;
- the former analyzer champion remains available for rollback;
- no CardEventNet registry entry changes.

### M5 — Shared system holdout evaluation

1. Load the system holdout registry from plan 0027.
2. Reject any group used in component training or model selection.
3. Run the locked composed pipeline with fixtures.
4. Attribute failures to component boundaries and write a system report.
5. Prevent the report from starting another candidate in a locked campaign.

Acceptance:

- every system holdout source group is unseen by all trained components;
- repeated evaluation uses identical locked artifacts;
- failure attribution distinguishes event, observation, and reconstruction failures;
- no component champion changes as a side effect;
- the local fixture needs no cloud service or physical device.

### M6 — Optional skill and clean-room exercise

1. Add the project-local skill with explicit triggers and workflow instructions.
2. Make it create a proposed recipe, not a resolved campaign mutation.
3. Run one fixture campaign with the skill and one without it.
4. Compare artifacts and deterministic recommendations.
5. Document the human confirmation and blocked-work handoff.

Acceptance:

- both paths use the same `doko` commands and contracts;
- the Python-only workflow reaches the same deterministic recommendation;
- the skill cannot access test results before candidate lock;
- the skill cannot update the champion registry directly;
- a contributor can reproduce the campaign from checked-in artifacts.

## 11. Out of scope

- accepting automatic labels without human review;
- unbounded autonomous architecture search;
- choosing experiments from test or system holdout results;
- cloud experiment tracking or a hosted model registry;
- production deployment, traffic shifting, or monitoring;
- deleting former champions automatically;
- making Codex required for routine experiments or promotion.

## 12. Verification

Use generated data and tiny model fixtures for ordinary tests. Run:

- operations-package contract, comparison, resumption, and atomic-promotion tests;
- CardEventNet train, evaluate, export, and Core ML parity tests;
- plan 0021 TableEvidenceAnalyzer train, evaluate, export, and runtime-load tests;
- registry corruption and rollback tests;
- cross-component system holdout leakage tests;
- one CPU clean-room campaign for each component;
- one composed fixture evaluation.

Run optional MPS or CUDA campaigns only as accelerator verification. Do not make a cloud service or
physical phone part of the normal gate.

## 13. Definition of done

- each component has one versioned champion model bundle and independent registry entry;
- checked-in recipes define bounded, reproducible campaigns;
- champion and candidates are compared on identical current validation data;
- candidate lock separates model selection from test evaluation;
- model promotion is explicit, atomic, traceable, and reversible;
- task-specific gates include quality, group, runtime, export, and compatibility checks;
- the system holdout remains unseen by every trained component;
- every campaign writes machine-readable results and a concise recommendation;
- both workflows work without an agent, and the optional skill uses the same commands.
