# CardEventNet unattended improvement report

## Stop reason

Stop for human review. The locked run materially improves validation, but the one-time test
evaluation reaches only 0.8951 recall. Do not use the test result to start another unattended
iteration.

## Budget

Codex did not expose a shared weekly token allowance or token count. The user authorized a soft
budget. The loop stopped after two iterations, below the maximum of four.

## Locked result

- Run: `card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02`
- Checkpoint: `card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02/best.pt`
- Commit: `bd6fd481744f3bf1ea01bf7ebba153096b6f4cad`
- Seed: 42
- Device: MPS
- Best epoch: 8
- Best stage: fine-tune epoch 3
- Threshold: 0.966765
- Minimum event gap: 0.625 s

## Metric comparison

| Metric | Baseline validation | Final validation | Final test |
| --- | ---: | ---: | ---: |
| Real events | 160 | 160 | 162 |
| Detected events | 157 | 158 | 145 |
| Missed events | 3 | 2 | 17 |
| False events | 144 | 44 | 34 |
| Recall | 0.98125 | 0.98750 | 0.89506 |
| Precision | 0.52159 | 0.78218 | 0.81006 |
| F1 | 0.68113 | 0.87293 | 0.85044 |
| False events/hour | 1427.77 | 436.26 | 335.40 |
| Worst-video recall | 0.925 | 0.950 | 0.825 |
| Timestamp error median | 0.091 s | 0.062 s | 0.099 s |

Validation false events fell by 100, or 69.4%. Validation recall and worst-video recall also
improved.

## Test results by video

| Video | Recall | Misses | False events/hour |
| --- | ---: | ---: | ---: |
| IMG_0659 | 0.825 | 7 | 305.90 |
| IMG_0635 | 0.829 | 7 | 250.96 |
| IMG_0638 | 0.950 | 2 | 409.12 |
| IMG_0656 | 0.976 | 1 | 379.62 |

The test threshold came from validation. The evaluator did not tune on test data.

## Commit history

1. `51827c4 cardeventnet: make early stopping stage-aware`
   - Prevents warm-up patience from stopping the full schedule.
   - Resets early stopping when fine-tuning starts.
2. `002252f cardeventnet: keep augmented clips contiguous`
   - Fixes an MPS backward failure for non-contiguous augmented tensors.
3. `ae84966 cardeventnet: compare accelerator device types`
   - Corrects an MPS-only test assertion exposed by full device access.
4. `bd6fd48 cardeventnet: close decoder stride gap`
   - Changes the configured minimum event gap from 0.600 to 0.625 seconds.
   - Adds a boundary regression test.

No commit was reverted.

## Iteration decisions

### Iteration 1: Accept

Fine-tuning ran. The best checkpoint moved from warm-up epoch 1 to fine-tune epoch 11. Validation
false events fell from 144 to 63. Recall remained 0.98125, and worst-video recall improved to 0.95.

### Iteration 2: Accept and lock

The 0.625-second decoder gap reduced validation false events from 63 to 44. Recall improved to
0.9875. Worst-video recall remained 0.95.

Hard-negative training was skipped. Most remaining validation false events have high confidence,
so annotation review is required before treating them as negatives.

## Verification

- Final tests: 98 passed, 1 skipped.
- Ruff lint: passed.
- Repository-wide Ruff format: baseline failure; 14 files would be reformatted.
- MPS forward and backward regression: passed.
- Test partition evaluated once after the checkpoint and threshold were locked.

Unrelated worktree changes appeared during the long run. They were preserved and were not included
in the loop commits.

## Reproduction commands

```bash
mise exec -- uv run --project card_event_net cardevent train \
  --config card_event_net/configs/base.yaml \
  --split card_event_net/data/splits/new.yaml \
  --output-dir card_event_net/data/outputs/unattended-20260823-130344 \
  --run-name run-iteration-02 \
  --cache-dir card_event_net/data/cache \
  --annotations-dir card_event_net/data/annotations \
  --device mps

mise exec -- uv run --project card_event_net cardevent evaluate \
  --checkpoint card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02/best.pt \
  --split card_event_net/data/splits/new.yaml \
  --partition val \
  --cache-dir card_event_net/data/cache \
  --annotations-dir card_event_net/data/annotations \
  --out card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02/evaluation-val.json \
  --device mps

mise exec -- uv run --project card_event_net cardevent diagnose \
  --checkpoint card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02/best.pt \
  --split card_event_net/data/splits/new.yaml \
  --cache-dir card_event_net/data/cache \
  --annotations-dir card_event_net/data/annotations \
  --out card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02/diagnostics.json \
  --device mps
```

The test command is recorded for audit. Do not rerun it to tune the model.

```bash
mise exec -- uv run --project card_event_net cardevent evaluate \
  --checkpoint card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02/best.pt \
  --split card_event_net/data/splits/new.yaml \
  --partition test \
  --cache-dir card_event_net/data/cache \
  --annotations-dir card_event_net/data/annotations \
  --out card_event_net/data/outputs/unattended-20260823-130344/run-iteration-02/evaluation-test.json \
  --device mps
```

## Remaining risks

- Test recall is far below the 0.98 target. Two test videos contain 14 of 17 misses.
- The validation-selected threshold is split-specific. At this threshold, train recall is 0.933
  and validation recall is 0.988.
- Validation still has 44 false events. Twenty-seven have probability at least 0.99.
- The two validation misses are merged events. A wider decoder gap can increase this failure mode.
- The training set still has no confirmed hard negatives.
- The requested negative-to-positive ratio is still not reached.
- Reported emission latency remains incorrect. It omits the configured confirmation delay.
- Repository-wide formatting did not pass before the loop and still does not pass.

## Best next human decision

Audit annotations and session differences before another model change. Start with training and
validation high-confidence false events. Confirm whether they are true negatives or missing
events. Separately record new independent real-game sessions. Do not mine old test events as
training negatives.
