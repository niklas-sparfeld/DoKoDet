# CardEventNet review workflow

Run these commands from `card_event_net/`.

## 1. Create a validation queue

Build a deterministic queue from a checkpoint. The command does not mark items as reviewed.

```bash
uv run cardevent review-queue \
  --checkpoint data/outputs/run/best.pt \
  --split data/splits/default.yaml \
  --partition val \
  --out data/outputs/run/review-val.json
```

## 2. Review and resume the queue

Review the queue in the source videos:

```bash
uv run cardevent review \
  --queue data/outputs/run/review-val.json \
  --out data/reviews/review-val-niklas.json \
  --videos-dir data/raw \
  --annotations-dir data/annotations \
  --reviewer niklas
```

The reviewed queue is a separate file. The source queue and source annotations stay unchanged.
The command writes the reviewed file after each decision. Run the same command again to resume.

New queues include one probability timeline per video. The review window shows the model
probability curve, threshold, predictions, source events, queue candidate, and current video
position below the video. Old queues still work, but show a hint to regenerate the queue.

Use `--video`, `--category`, or `--start-item` to narrow the first session. Use
`--include-reviewed` to include completed items when you need to revisit them.

The review keys are:

```text
Y  new confirmed positive       E  existing annotation is correct
H  confirmed hard negative      R  correct annotation timestamp
I  ignore                       U  clear the decision
M  add or edit a note            Q  save and exit
P  play or pause                A/D and J/L seek
C  before/after comparison      1-7 select the event type
N/B next or previous queue item   ,/. previous or next source annotation target
```

Near-event decisions:

- `E` means the candidate is the same physical event and the selected existing annotation time
  is good enough.
- `R` means the candidate is the same physical event, but correct the selected existing
  annotation to the current state-change time.
- `Y` means a distinct real event is missing. Add it as a new event.
- `H` means no real state change occurs in the model input context. Do not use `H` for a duplicate
  peak that belongs to a real event or for an uncertain event boundary.
- `I` means the evidence is unusable or ambiguous. Add a note when useful.

The selected source event is shown in the overlay with its signed and absolute time distance.
Use `,` and `.` to choose the previous or next source event before pressing `E` or `R`. This
choice controls which source annotation the decision changes. Use `Y` when the candidate is a
separate event between two source events; use `,` or `.` first when it is unclear whether it
belongs to the previous or next event.

## 3. Apply a complete validation queue

Inspect the application plan first:

```bash
uv run cardevent apply-review \
  --queue data/reviews/review-val-niklas.json \
  --annotations-dir data/annotations \
  --out-dir data/annotations-val-reviewed \
  --videos-dir data/raw \
  --dry-run
```

Apply it after the summary is correct:

```bash
uv run cardevent apply-review \
  --queue data/reviews/review-val-niklas.json \
  --annotations-dir data/annotations \
  --out-dir data/annotations-val-reviewed \
  --videos-dir data/raw
```

The command uses the reviewer stored in the queue. Pass `--reviewer` only when you want to
verify the same name explicitly. The output contains the derived annotations, the reviewed
queue, an application summary, and a hard-negative file.

Do not use `--allow-partial` for the final validation version. That option is for an intentional
intermediate output only.

## 4. Review the training queue

Create and review a training queue with the same model and source annotation version:

```bash
uv run cardevent review-queue \
  --checkpoint data/outputs/run/best.pt \
  --split data/splits/default.yaml \
  --partition train \
  --out data/outputs/run/review-train.json

uv run cardevent review \
  --queue data/outputs/run/review-train.json \
  --out data/reviews/review-train-niklas.json \
  --videos-dir data/raw \
  --annotations-dir data/annotations \
  --reviewer niklas
```

## 5. Apply training decisions on top of reviewed validation labels

Use the reviewed validation annotation version as the source for the training application. Write
to a new directory:

```bash
uv run cardevent apply-review \
  --queue data/reviews/review-train-niklas.json \
  --annotations-dir data/annotations-val-reviewed \
  --out-dir data/annotations-next \
  --videos-dir data/raw
```

Validation hard negatives are for validation analysis. They must not become training input.
Training hard negatives stay in the training hard-negative file and may be passed to training:

```bash
uv run cardevent train \
  --config configs/base.yaml \
  --split data/splits/default.yaml \
  --annotations-dir data/annotations-next \
  --hard-negative-manifest data/annotations-next/training-hard-negatives.json
```

Before training, validate the new annotation directory and prepare its frame cache:

```bash
uv run cardevent prepare \
  --videos data/raw/*.mov \
  --annotations-dir data/annotations-next \
  --cache-dir data/cache-next
```

The review command never writes annotation JSON. `apply-review` is the only command in this
workflow that derives annotation changes.
