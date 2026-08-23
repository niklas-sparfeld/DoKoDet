# CardEventNet Unattended Improvement Loop

## Plan status

- Summary: Run a small, evidence-led loop to improve CardEventNet
- Status: Done; stopped for human review after two iterations
- Starting run: `card_event_net/data/outputs/run-20260822-190415`
- Maximum iterations: 4
- Hard token limit: 10% of the total weekly token allowance

## Outcome

The loop stopped after two accepted iterations. The locked result is commit `bd6fd48` and local
run `card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02`.

| Metric | Starting validation | Locked validation | One-time test |
| --- | ---: | ---: | ---: |
| Recall | 0.98125 | 0.98750 | 0.89506 |
| False events | 144 | 44 | 34 |
| False events/hour | 1427.77 | 436.26 | 335.40 |
| Worst-video recall | 0.925 | 0.950 | 0.825 |

The validation result improved materially. The test result did not meet the 0.98 recall target.
Do not tune another model from the test failures. Human annotation and session review are the next
steps.

Codex did not expose the shared weekly token allowance. The user authorized a soft budget for the
completed execution. The local final report records this exception and the full commands.

## Goal

Improve CardEventNet at the target validation recall of 0.98. Reduce false events per hour without hiding missed events or using test data to steer changes.

The loop has three steps:

1. Make one small code change and commit it.
2. Train a new model, then evaluate and diagnose it.
3. Analyze the diagnostics and select the next action.

Run the loop without routine human input. Stop when human judgment would meaningfully improve the next step.

## Starting evidence

Use the starting run as the baseline:

| Metric | Baseline |
| --- | ---: |
| Validation videos | 4 |
| Validation duration | 363.08 s |
| Real events | 160 |
| Detected events | 157 |
| Missed events | 3 |
| False events | 144 |
| Event recall | 0.98125 |
| Event precision | 0.52159 |
| Event F1 | 0.68113 |
| False events/hour | 1427.77 |
| Selected threshold | 0.03095 |

Known problems:

- Early stopping ended training at warm-up epoch 4. Fine-tuning did not start.
- Training loss fell while validation loss rose.
- The requested 3:1 negative-to-positive ratio was not reached.
- No hard-negative manifest was used.
- Many false events occur in ignored timeline regions.
- Many false events have high confidence. Threshold tuning alone cannot remove them.
- The test partition has not been evaluated.
- Reported emission latency does not include the configured peak-confirmation delay.

## Agent roles

### Supervisor

Use `gpt-5.6-sol` with `reasoning_effort: high`.

The supervisor owns:

- the token ledger,
- iteration selection,
- executor instructions,
- review of code, tests, commits, and commands,
- comparison of diagnostics,
- accept, revert, continue, and stop decisions,
- the final report.

The supervisor must not make routine implementation changes. It can make a small corrective change only if executor delegation is unavailable and the change is required to leave the repository in a valid state.

### Executor

Use `gpt-5.6-luna` with `reasoning_effort: xhigh`.

Use one executor at a time. Give it one bounded hypothesis and explicit acceptance criteria. The executor owns:

- regression tests,
- implementation,
- local checks,
- one focused commit,
- training,
- evaluation,
- diagnostics generation,
- a compact result package for the supervisor.

Do not let the executor choose the next experiment. It can report alternatives and blockers.

## Token budget

The complete unattended run, including all supervisor and executor work, must use no more than 10% of the total weekly token allowance.

At startup:

1. Read the total weekly token allowance and current usage from available Codex telemetry.
2. Compute `loop_token_limit = floor(total_weekly_allowance * 0.10)`.
3. Start a shared token ledger before spawning the executor.
4. Reserve 15% of `loop_token_limit` for supervisor review, cleanup, and the final report.
5. Make the remaining 85% available to iterations.

Count all supervisor and executor tokens against the same limit. Check usage before and after every agent turn. Do not use a per-agent limit as a substitute for the shared limit.

Do not start an iteration unless the remaining budget covers its estimated implementation, review, and final reporting cost. Stop at 90% of `loop_token_limit` unless the remaining work only closes running tools and writes the final report. Never exceed `loop_token_limit`.

If Codex cannot read or enforce a shared weekly token limit, stop before the first code change and ask the human to provide a numeric limit. Do not estimate or guess the weekly allowance.

## Repository rules

- Work directly on `main`.
- Do not create a branch.
- Do not push commits.
- Preserve unrelated changes.
- Stop if an existing change overlaps files needed by the next experiment.
- Keep each implementation commit focused on one hypothesis.
- Add a regression test before or with each bug fix when practical.
- Run applicable tests, Ruff, formatting, and type checks before each commit.
- Use the runtimes and tools declared by `mise.toml`.
- Run `mise install` only if tool declarations change.
- Do not overwrite the starting run or any prior experiment output.

Before the loop, record:

- current commit,
- `git status --short`,
- baseline configuration,
- baseline metrics,
- weekly token limit,
- loop token limit,
- selected supervisor and executor models.

## Experiment record

Create one parent output directory for the unattended session:

```text
card_event_net/data/outputs/unattended-<timestamp>/
  loop-state.json
  iteration-01.md
  iteration-02.md
  ...
  final-report.md
```

Update `loop-state.json` atomically after every state change. It must contain:

- loop status,
- token limit and tokens used,
- current iteration,
- supervisor and executor model settings,
- baseline run,
- commit hashes,
- exact commands,
- output run paths,
- metrics before and after each iteration,
- accept or reject decisions,
- stop reason.

Each iteration report must include:

- hypothesis,
- evidence for the hypothesis,
- changed files,
- test-first evidence,
- commit hash and subject,
- training configuration and seed,
- train, evaluate, and diagnose commands,
- run artifact paths,
- metric comparison,
- token cost,
- supervisor decision.

Keep large command output in the run artifacts. Put only summaries and failure excerpts in the iteration report.

## Preflight

The supervisor performs these checks once:

1. Confirm that the repository is on `main`.
2. Inspect the worktree. Preserve unrelated changes.
3. Run the relevant existing unit tests and static checks.
4. Confirm that the baseline artifacts are readable.
5. Confirm that training can run locally with MPS or CPU.
6. Confirm enough disk space for four new runs.
7. Establish the shared token cap.
8. Create the unattended output directory and initial state file.

If the baseline tests fail, the first iteration may fix one relevant failure. Stop if the failure has unclear product semantics or overlaps unrelated human work.

## Loop protocol

Run at most four iterations. Use fewer when the stop rules apply.

### 1. Supervisor selects one hypothesis

Use the latest accepted diagnostics. Select the smallest change that can test the highest-value explanation.

The instruction to the executor must contain:

- one hypothesis,
- files or subsystem in scope,
- tests that must pass,
- metrics that must not regress,
- exact training seed or seed set,
- expected artifact paths,
- remaining iteration token budget,
- stop conditions.

Do not combine training-control, label, decoder, and architecture changes in one iteration.

### 2. Executor changes code and commits

The executor must:

1. Inspect the relevant code and tests.
2. Add or update a focused test.
3. Confirm that the test fails for the expected reason when practical.
4. Implement the smallest change.
5. Run the relevant tests and checks.
6. Review the diff for unrelated changes.
7. Commit the change on `main` with a focused message.

Do not amend an earlier commit. Do not train from an uncommitted code state. If generated run artifacts are ignored by Git, leave them uncommitted. Commit only source, tests, configuration, and intentional documentation.

### 3. Executor trains, evaluates, and diagnoses

After the commit, run a fresh training job with a new output directory. Use the same split and seed as the baseline unless the hypothesis requires a declared change.

Run the normal project commands for:

1. training,
2. validation evaluation,
3. train-versus-validation diagnostics.

Capture the exact commands and exit status. Do not evaluate the test partition during the loop.

For a long-running command:

- Start it once.
- Wait for completion notifications when the tool supports them.
- Otherwise, poll no more often than once every five minutes.
- Use a five-minute wait between checks. Do not poll every 30 seconds.
- Read only new output after each wait.
- Do not repeatedly parse partial metrics files.
- Do not start evaluation until training exits successfully and artifacts are complete.
- Apply the same rule to evaluation and diagnostics.

A little idle wall time is acceptable. Prefer fewer tool calls and fewer tokens over aggressive polling.

If a process exits, inspect it immediately. Retry one transient infrastructure failure without a code change. Do not retry a deterministic failure with the same command.

### 4. Executor returns a compact result package

Return only:

- commit hash,
- checks run and their result,
- output paths,
- selected epoch and stage,
- selected threshold,
- recall, precision, F1, false events/hour, and latency,
- per-video recall and false events/hour,
- train and validation loss trend,
- target-recall status,
- hard-negative and label-state counts,
- comparison with the baseline and latest accepted run,
- anomalies or suspected metric defects,
- tokens used.

### 5. Supervisor analyzes diagnostics

The supervisor must inspect the artifacts directly. Do not accept the executor summary without checking the run files.

Compare:

- target-recall attainment,
- false events/hour at target recall,
- maximum-F1 operating point,
- fixed-threshold behavior,
- worst-video recall,
- per-video false-event concentration,
- train and validation loss,
- selected-threshold stability,
- whether warm-up and fine-tune stages both ran,
- positive, clean-negative, ignored, and hard-negative counts,
- missed and high-confidence false events,
- timestamp error and actual emission latency,
- run reproducibility.

Use this decision order:

1. A run that misses 0.98 recall does not replace one that meets it, unless it exposes a confirmed evaluation defect.
2. Among runs that meet 0.98 recall, prefer fewer false events/hour.
3. Require no material regression in worst-video recall.
4. Use precision, F1, threshold stability, and loss trends as secondary evidence.
5. Treat a change of fewer than seven false events on this validation set as weak evidence unless another metric confirms it.

Record one decision:

- `accept`: keep the commit and use the run as the next baseline,
- `reject`: revert the commit with a new focused revert commit,
- `stop-success`: the goal or a clear local optimum was reached,
- `stop-human`: human input would materially improve the next step,
- `stop-budget`: the next safe step does not fit the token cap.

### 6. Supervisor decides whether to continue

Continue only when:

- a specific next hypothesis follows from the diagnostics,
- it can be tested with one small code change,
- the next iteration fits the remaining budget,
- no human decision would materially improve the experiment.

Otherwise, stop and write the final report.

## Initial experiment order

Use this order only while the latest diagnostics support it. The supervisor can skip an item, but it must record why.

### Candidate 1: Make early stopping stage-aware

Hypothesis: Global early stopping prevents backbone fine-tuning and leaves the model at the first warm-up epoch.

Test and change:

- Add a regression test that shows warm-up cannot stop the complete training schedule before fine-tuning starts.
- Reset or enable patience at the fine-tune boundary.
- Keep checkpoint ranking based on validation event behavior.

Acceptance evidence:

- Fine-tuning runs.
- All checks pass.
- Target recall remains at least 0.98.
- False events/hour improve, or diagnostics give clear evidence for the next hypothesis.

### Candidate 2: Use confirmed hard negatives

Hypothesis: High-confidence false triggers remain because ignored transition regions and difficult clean negatives do not contribute enough negative supervision.

Test and change:

- Ensure hard-negative mining produces reproducible, provenance-linked input.
- Mine only from training videos.
- Add the manifest to a new training configuration.
- Keep confirmed hard negatives out of positive windows.

Acceptance evidence:

- The run reports non-zero confirmed hard negatives.
- High-confidence false events decrease.
- Target recall and worst-video recall do not materially regress.

Stop for a human before this iteration if false triggers appear to be real but missing annotations. Do not train them as negatives without annotation review.

### Candidate 3: Test the decoder gap at the inference stride boundary

Hypothesis: With a 0.125-second inference stride, `min_event_gap_s: 0.6` still accepts peaks 0.625 seconds apart and permits duplicate detections.

Test and change:

- Add a regression test for peaks exactly 0.625 seconds apart.
- Test `min_event_gap_s: 0.625` as a declared configuration change.
- Recalibrate the threshold from validation streams.

Prior decoder-only evidence suggests this can reduce false events from 144 to 108 while keeping recall at 0.9875. Treat this as a hypothesis until the full new run confirms it.

### Candidate 4: Correct latency diagnostics

Hypothesis: The diagnostics report peak timestamp error as latency and omit the 0.125-second confirmation delay.

Test and change:

- Distinguish event timestamp error from emission latency.
- Add the configured confirmation delay to emission metrics.
- Keep event timestamps tied to the detected peak.

This change improves measurement. Do not treat it as a model-quality improvement.

## Human-stop rules

Stop all agents and running work when human interaction would meaningfully improve the next step.

Examples:

- A likely false event appears to be a real but missing card-state annotation.
- Product judgment is needed to choose between recall and false-event cost.
- The next useful step is manual annotation or video review.
- A requirement is ambiguous and different choices would change labels, metrics, or architecture.
- Existing human changes overlap the required code.
- A destructive action, external write, purchase, cloud job, or new authorization is required.
- Test data would need to be inspected to choose the next change.
- The token limit cannot be read or enforced.
- The next iteration does not fit the remaining token budget.
- Diagnostics are inconsistent and the cause cannot be established from code and saved artifacts.
- Two consecutive accepted iterations fail to produce a meaningful improvement.
- No single small code change follows from the evidence.

Before stopping a running train, evaluation, or diagnostics process, terminate it cleanly when possible. Record whether partial artifacts are valid. Do not analyze incomplete artifacts as a finished run.

Routine transient failures do not require human input. The executor can fix a deterministic local code issue when the correct behavior is clear and remains within the iteration scope.

## Success and final evaluation

Stop with success when all conditions hold:

- validation recall is at least 0.98,
- false events/hour improves materially from 1427.77,
- worst-video recall does not materially regress,
- fine-tuning runs as intended,
- relevant tests and static checks pass,
- the run is reproducible from committed code and recorded commands,
- remaining problems require a new product decision, annotation work, or a larger architectural experiment.

After the supervisor locks the final checkpoint, threshold, and decoder settings, evaluate the test partition exactly once. Do not use that result to start another unattended iteration. If the test result is poor, report it and stop for human review.

The final report must include:

- stop reason,
- token limit and actual token use,
- iteration and commit history,
- accepted and reverted changes,
- baseline, final validation, and final test metrics,
- exact reproduction commands,
- remaining risks,
- the best next human decision.

## Source

The model names and reasoning-effort settings follow the [official OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model).
