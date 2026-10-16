# Epic 0090 M1: Retained Pipeline Coordinator

## Result

M1 adds a local CLI coordinator for the frozen stage order. It sends one request at a
time to the existing backend APIs and waits for a terminal result before it starts the next
dependent stage. It records each request, request digest, processor run ID, input revisions,
output revisions, state, and failure in an atomic JSON manifest under
`.runtime/pipeline-coordinators/runs/`.

The coordinator derives stable run IDs from the coordinator ID and stage name. A completed
stage is reused only when its request digest and resolved input revisions match. Later stages
refer to actual output revisions from earlier stages. A failed or partial stage stops the
recording sequence. Other recordings can run in separate invocations under the M0 batch policy.

The `dokodetector-pipeline-coordinator` command requires a local backend and a JSON request
file. The request file must define all six names in M0 `stage_order`. The five retained
processor requests are passed as request objects. `reconstruction` must either contain explicit
`round_id`, `session_id`, `round_context`, `rules_version`, and `search` values, or an explicit
skip decision such as:

```json
"reconstruction": {
  "skip": true,
  "skip_reason": "staged sequence has no game round setup"
}
```

Do not use the skip form for a real round with available setup. Do not invent seat, dealer, or
leader values. The CLI submits reconstruction only when the request has explicit round context.

Example:

```sh
dokodetector-pipeline-coordinator cardeventnet-IMG_0657 \
  --api-url http://127.0.0.1:8765 \
  --requests /path/to/0090-cardeventnet-IMG_0657-requests.json
```

The command prints the durable run manifest. Request acceptance alone is never reported as
completion.

## Verification

- Focused coordinator tests: passed (5 tests).
- Ruff check and format: passed.
- `git diff --check`: passed.
- No model stages were run for M1.

## Limits

The request file supplies the frozen per-stage request settings. M1 does not select models,
review inputs, or infer game setup. Backend restart recovery, cancellation, and stale-input
failure injection remain in M2. The pilot execution and quality report remain in M3.
