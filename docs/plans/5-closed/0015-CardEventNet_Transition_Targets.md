# CardEventNet transition target plan

## Plan status

- Summary: Train CardEventNet to detect visible table-state changes instead of persistent states
- Status: Closed
- Closure reason: Complete
- Closure note: Experimental design not promoted to the default configuration
- Depends on: plans 0011, 0013, and 0014

## Outcome

The transition labels and full-clip V2 head passed the validation acceptance gate. The final test
run used the frozen validation threshold and showed a large device-domain gap on the old iPhone SE
videos. Therefore this work adds the implementation and preserves the experiment configurations,
but it does not change `configs/base.yaml` or the direct-call label defaults.

See report 0015 for the run identifiers, metrics, and follow-up split policy. Do not tune the
model or threshold from this final test result. Use a new, device-aware experiment for that work.

## Problem

Run `run-20260825-162656` met the validation recall target, but it produced too many false
events:

- 98.04% event recall;
- 67.20% event precision;
- 122 false events in 474.15 seconds;
- 926.28 false events per hour.

The validation plots show long regions with probabilities near 1 while cards remain on the
table. The model learned persistent table states instead of short visible transitions.

The current labels make this behavior likely. For an event at time `e`, they produce these
states:

```text
positive: e through e + 0.45 s
ignore:   e + 0.45 s through e + 1.80 s
ignore:   e - 0.80 s through e
negative: all other eligible times
```

The training partition contains 1,199 events in 37.25 minutes, or about 32.19 events per minute.
The long ignore intervals leave too few clean negative samples. The baseline run selected 5,467
positive samples and 3,400 ordinary negative samples. Its effective positive fraction was
61.66%, although a 1:3 ratio implies a 25% positive fraction.

The current temporal head also has a limited receptive field. The input contains eight frames
over 1.4 seconds. However, the final value from its two padded kernel-size 3 convolutions depends
on only the last three projected frame features. Those features cover about 0.4 seconds. This is
a secondary hypothesis. Test the label change before changing the architecture.

## Corrections to the earlier draft

- The repository already has a root `mise.toml`. Do not add `card_event_net/mise.toml` and do not
  change the toolchain in this work.
- `data/outputs/hard-negatives.json` contains 319 automatically mined candidates. They are not
  human-confirmed hard negatives. Do not use them in the label-only experiment.
- The 131 items in
  `data/annotations-val-reviewed/validation-hard-negatives.json` are reviewed validation hard
  negatives and declare `training_input: false`. Use them only for targeted validation analysis.
- The six `confirmed_positive` validation review decisions confirmed existing annotations. The
  review application added no events and corrected no timestamps.
- Validation hard-negative timestamps do not change event metrics by themselves. Any unmatched
  decoded prediction is already a false event. The reviewed timestamps provide a focused score
  diagnostic.
- The repository has historical test evaluation artifacts. The test partition can remain hidden
  during this model-selection cycle, but it is not globally untouched. Treat its final result as
  confirmation, not as a new unbiased estimate if old test results influenced a decision.

## Goal

Make the model output a short probability pulse after each visible table-state change. Make the
probability return toward zero while the resulting table state remains unchanged.

Preserve these properties:

- causal inference;
- local training and evaluation on a MacBook;
- loading of old checkpoints;
- validation and test split isolation during this model-selection cycle;
- Core ML export with a fixed eight-frame input.

## Experiment rules

Use one controlled change per experiment.

The first full experiment must use:

- split `data/splits/batch-2026-08-24.yaml`;
- annotations `data/annotations-val-reviewed`;
- cache `data/cache`;
- the model, optimizer, augmentation, decoder, metric, and seed settings from `configs/base.yaml`;
- ImageNet initialization and no `--resume` option;
- no hard-negative manifest.

The reviewed annotation directory does not change the validation event timestamps used by the
baseline. Its two unrelated V1-to-V2 annotation migrations also do not change event semantics.
The existing full-frame cache remains valid because this plan does not change source videos,
preprocessing, frame size, or cache rate. Do not rebuild it as `data/cache-next`.

Do not change the event decoder, event-match tolerance, backbone, or training schedule in the
label-only experiment.

## Target label semantics

Start with these settings:

```yaml
labels:
  positive_window_s: 0.25
  negative_past_exclusion_s: 0.35
  negative_future_exclusion_s: 0.10
  negative_to_positive_ratio: 3
```

For one event at time `e`, classify a decision time `d` as follows. These boundaries match the
current inclusive window implementation:

```text
d < e - 0.10                  negative
e - 0.10 <= d < e             ignore
e <= d <= e + 0.25            positive
e + 0.25 < d <= e + 0.35      ignore
d > e + 0.35                  negative
```

The pre-event ignore interval absorbs timestamp uncertainty. The post-event ignore interval
separates the positive pulse from explicit negative samples. An unchanged card state becomes a
negative again after `e + 0.35 s`.

Keep the current configuration field names. Renaming them would add compatibility work without
changing behavior. Document their event-relative meaning:

- `positive_window_s` is the positive interval after an event;
- `negative_past_exclusion_s` is the end of the post-event exclusion interval;
- `negative_future_exclusion_s` is the pre-event exclusion duration.

Require:

```text
positive_window_s <= negative_past_exclusion_s
```

When two positive windows overlap, their labels form one continuous positive interval. Do not
claim that labels can represent two separate pulses in that case. Event decoding still applies
its configured minimum event gap.

## Implementation phases

### Phase 0: Verify the fixed inputs

Use the existing root toolchain declaration. From the repository root, run `mise install` only if
the declared tools are not installed. Run project commands from `card_event_net/`.

Before changing code, record these checks in the experiment report:

- the split and annotation directory;
- the cache preprocessing identifier;
- the baseline checkpoint and validation metrics;
- the current Git commit;
- confirmation that no hard-negative manifest will be used.

Do not add or edit a `mise.toml` in this plan.

#### Acceptance gate

The baseline artifacts are readable, all split videos have annotations and compatible cache
metadata, and the experiment inputs are explicit.

### Phase 1: Add transition-label regression tests

Update `card_event_net/tests/test_sampling.py`. Add deterministic tests for an event at time `e`
that cover every boundary in the table above. Also test:

- an unchanged state between well-separated events becomes negative;
- overlapping positive windows form their documented union.

Keep the existing regression test that proves selected clip frames never occur after the
decision time.

Update `card_event_net/tests/test_config.py`. Add tests that accept equal positive and post-event
exclusion boundaries and reject a positive window that exceeds the post-event exclusion.

Use cached timestamp fixtures. Do not decode video or open a display.

#### Acceptance gate

The tests describe the exact boundary behavior. The configuration test fails before the
relationship check is implemented and passes after it is added to `LabelConfig`.

### Phase 2: Add the label-only experiment configuration

Add `card_event_net/configs/transition-label-v1.yaml`. The config format has no inheritance, so
copy `configs/base.yaml` and change only these values:

```text
positive_window_s: 0.45 -> 0.25
negative_past_exclusion_s: 1.80 -> 0.35
negative_future_exclusion_s: 0.80 -> 0.10
```

Do not change `configs/base.yaml` yet. Add the label relationship check to `LabelConfig` in
`card_event_net/src/cardevent/config.py`.

#### Acceptance gate

The experiment config loads and round-trips. A config diff shows only the three intended label
values.

### Phase 3: Write a sampling report before training

Write `sampling.json` in the run directory before the first epoch. Separate all eligible label
states from selected training samples. Include:

- configured label windows and requested negative-to-positive ratio;
- available positive, clean-negative, and ignored counts;
- selected positive and ordinary-negative counts;
- raw and repeated confirmed-hard-negative counts when a manifest is supplied;
- total selected samples and effective positive fraction;
- the same counts for each training video;
- videos where the requested ratio cannot be reached;
- the hard-negative manifest path, or `null`.

Use one count helper for the initial report and the final summary. Keep the current summary keys
compatible, but make their selected-sample meaning explicit. Add a fixture-based unit test. Do
not run model training in that test.

The current cache and proposed windows produce these measured counts without hard negatives:

| Population | Positive | Ordinary negative | Ignore | Total |
|---|---:|---:|---:|---:|
| All eligible timestamps | 3,078 | 17,080 | 2,198 | 22,356 |
| Selected training samples | 3,078 | 9,205 | 0 | 12,283 |

The selected effective positive fraction is 25.06%. Only `IMG_0095` and `IMG_0096` cannot reach
the full per-video 1:3 ratio. Assert these dataset values in the preflight report, not in a unit
test that depends on local data.

#### Acceptance gate

The sample balance is visible before a long run starts, and the initial and final counts cannot
disagree.

### Phase 4: Run the label-only experiment

Before training, add a pure, fixture-tested transition diagnostic that reads a saved validation
stream. Write `transition-diagnostics.json` beside the normal evaluation output. It must report:

- the post-event tail definition, eligible sample count, and threshold-exceedance count;
- nearest-stream scores for a supplied reviewed validation hard-negative manifest;
- aggregate and per-video results.

Reject a training-scoped manifest in this diagnostic. Do not feed these labels into loss or
threshold selection. Run the diagnostic on the saved baseline validation stream before the new
experiment so both runs use the same calculation.

Run a local smoke job first:

```bash
uv run cardevent train \
  --config configs/transition-label-v1.yaml \
  --split data/splits/batch-2026-08-24.yaml \
  --annotations-dir data/annotations-val-reviewed \
  --cache-dir data/cache \
  --max-samples 32
```

Then run the full job on MPS by using the same command without `--max-samples` and with
`--device mps`. Do not pass `--hard-negative-manifest`.

Evaluate only validation data. Compare the result with `run-20260825-162656`. Report:

- event recall, precision, F1, and false events per hour;
- per-video event metrics;
- median and p95 emission latency;
- train and validation loss;
- the selected threshold and selection reason;
- event-aligned probability plots;
- the proportion of eligible post-event tail samples above the selected threshold;
- scores at the 131 reviewed validation hard-negative timestamps.

Define a post-event tail sample as a validation decision time from `e + 0.50 s` through
`e + 1.00 s`, excluding times within `0.10 s` before the next event. Save the definition and
counts with the diagnostic so dense events do not silently distort it.

Use this acceptance gate:

- validation event recall is at least 98%;
- false events per hour is at most 648.4, a reduction of at least 30%;
- at least 90% of eligible post-event tail samples are below the selected threshold;
- the count of reviewed validation hard-negative timestamps at or above the selected threshold
  is lower than the baseline count.

The first two conditions protect event-level behavior. The last two test the transition-target
hypothesis directly.

#### Decision gate

- If all conditions pass, keep the current temporal head and continue to Phase 6.
- If event-level metrics fail but the tail diagnostic passes, do not change the architecture
  without evidence. Record the failure and plan one-variable validation experiments.
- If probabilities still remain high after events, continue to Phase 5.

Do not inspect the test partition in this phase.

### Phase 5: Conditionally add a versioned full-clip temporal head

Run this phase only when the label-only result still shows persistent post-event scores.

Add an optional model setting:

```yaml
model:
  temporal_head: full_clip_v2
```

Support these values:

```text
padded_tail_v1
full_clip_v2
```

Treat a missing value as `padded_tail_v1`. This preserves reconstruction of old checkpoint
configurations and their existing parameter shapes.

Implement `full_clip_v2` in `card_event_net/src/cardevent/model.py` with valid temporal
convolutions:

1. Apply a kernel-size 5 convolution to the eight projected frame features.
2. Apply a kernel-size 4 convolution to the four remaining positions.
3. Classify the resulting single temporal position.

This head uses all eight input frames. It remains causal because every selected frame is at or
before the decision time.

Extract one method that classifies projected frame features. Call it from both
`CardEventNet.forward` and `CoreMLExportModel.forward`. Do not duplicate temporal-output indexing
in the Core ML wrapper.

Add tests in `card_event_net/tests/test_model.py` that prove:

- V2 returns one logit per clip;
- deterministic non-zero gradients reach every temporal input position;
- V1 remains available and retains its state-dict shapes.

Update config, checkpoint, and Core ML export tests to cover:

- V1 fallback for a config without `temporal_head`;
- V2 config round-trip;
- V1 and V2 checkpoint reconstruction;
- fixed-shape tracing;
- equality between the normal PyTorch model and the export wrapper.

Train V2 from scratch with the Phase 2 labels and the same data. Do not add feature differences,
hard negatives, or another architecture change in the same experiment.

#### Acceptance gate

Old checkpoints still load, V2 uses the complete eight-frame history, the export wrapper matches
the normal model, and the V2 validation run passes the Phase 4 acceptance gate. If it does not
pass, do not promote it. Record the result and create a separate follow-up plan.

### Phase 6: Promote the selected design

Select the final design with validation data only. Promote the chosen label values to
`configs/base.yaml` and to the direct-call defaults in:

- `card_event_net/src/cardevent/sampling.py`;
- `card_event_net/src/cardevent/dataset.py`;
- relevant test fixtures and documentation.

If V2 passed and was selected, also set `model.temporal_head: full_clip_v2` in `configs/base.yaml`.
Keep the missing-field V1 fallback for old checkpoints.

Write a versioned report in `docs/reports/`. Include the controlled config diff, sampling report,
baseline comparison, validation diagnostics, and the selection decision. Do not promote a design
that did not pass its gate.

#### Acceptance gate

The default config represents the selected design, old checkpoints still load, and the report
contains enough provenance to reproduce the result locally.

### Phase 7: Final test evaluation and Core ML export

After all labels, architecture, decoder settings, and the validation-selected threshold are
fixed, evaluate the test partition once for this cycle. Do not tune after reading the result.

```bash
uv run cardevent evaluate \
  --checkpoint data/outputs/run-.../best.pt \
  --split data/splits/batch-2026-08-24.yaml \
  --partition test \
  --annotations-dir data/annotations-val-reviewed \
  --cache-dir data/cache
```

Report validation and test recall, precision, F1, false events per hour, median and p95 emission
latency, and per-video results. State the historical-test caveat from this plan.

Export the final checkpoint on macOS and keep the default deterministic parity check enabled:

```bash
uv run cardevent export-coreml \
  --checkpoint data/outputs/run-.../best.pt \
  --out CardEventNet.mlpackage
```

#### Acceptance gate

The final report is complete, the exported package passes parity, and the workflow runs locally
without cloud infrastructure or an iPhone.

## Hard-negative policy

Hard-negative training is outside the controlled label and temporal-head experiments in this
plan.

Do not train from `data/outputs/hard-negatives.json` without human review. If reviewed training
hard negatives become available later, test them in a separate ablation. That work must also
make the training loader accept `cardevent-review-hard-negatives-v1` only when
`training_input: true`, validate timestamps against the current annotations and cache duration,
and preserve manifest provenance. It must continue to reject validation-scoped input.

## Verification

Run relevant focused tests after each phase. Before a code phase is complete, run these commands
from `card_event_net/`:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

For model or export changes, also run:

```bash
uv run pytest tests/test_model.py tests/test_export_coreml.py
```

Use a local smoke run before full training. Keep fixtures, recorded inputs, saved validation
streams, and local Core ML parity as the normal development loop.

## Focused commit sequence

Work directly on `main`. Use focused commits in this order:

1. Add transition-label tests, config validation, and the experiment config.
2. Add the pre-training sampling report.
3. Record the label-only experiment and decision.
4. Add the versioned full-clip head only if the decision gate requires it.
5. Promote the selected defaults and add the final report.

Do not commit generated checkpoints, frame caches, review working directories, or smoke-run
artifacts unless the repository already defines them as tracked evidence.

## Non-goals

This plan does not:

- add or change a `mise.toml`;
- train with automatically mined or validation hard negatives;
- merge hard-negative manifests;
- rebuild an unchanged full-frame cache;
- change the event decoder or event-match tolerance during the controlled experiments;
- add feature differences, a new backbone, or cloud training;
- require an iPhone for development or verification;
- inspect the test partition during model selection.
