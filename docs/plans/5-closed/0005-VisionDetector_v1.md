# DokoDetector VisionDetector — Local Pipeline PoC

## Plan status

- **Summary:** Prove the evidence-to-vision-result handoff with a scripted detector
- **Status:** Closed
- **Closure reason:** Complete
- **Closure note:** M0–M3 prove the local scripted pipeline. M4 records the real-recognition handoff
  and keeps recognition work gated because no real, human-labeled V1 event package exists.
- **Reviewed:** 2026-08-27 against the V1 evidence contract, the M3 pipeline proof, and the current repository
- **Depends on:** The local evidence backend from [plan 0004](../5-closed/0004-Backend_EvidenceUpload.md)
- **Starts with:** [Plan 0006 M0](0006-GameEngine_v1.md) to freeze one shared result contract
- **Unblocks:** The fake-detector integration in [plan 0016](0016-iOS_EvidenceUpload_Integration.md)
- **Parallel with:** [Plan 0020](../5-closed/0020-Data_Foundation.md) and
  [plan 0021](../2-ready/0021-Table_Evidence_Analyzer_Training_Pipeline.md)
- **Next:** [Plan 0022](../0-to-specify/0022-Table_Evidence_Analyzer_Development.md) replaces the scripted
  detector with measured models
- **Handoff report:** [M4 real-recognition handoff](../../reports/0005-VisionDetector_M4_Real_Recognition_Handoff.md)

## 1. Outcome

Build the smallest VisionDetector slice that proves the complete local handoff.

At the end of this plan, a developer can run this flow on a MacBook:

```text
stored V1 evidence package
  -> visual-only detector input
  -> scripted detector
  -> immutable ranked vision result
  -> SQLite and local result file
  -> HTTP result read-back
  -> game-engine contract fixture
```

This plan proves component boundaries, result semantics, persistence, and replay. It does not prove
that a model can recognize cards. [Plan 0022](../0-to-specify/0022-Table_Evidence_Analyzer_Development.md)
answers that separate question after the data and training foundations exist.

## 2. Current repository baseline

The current code already provides:

- the canonical V1 evidence manifest in `SERVER_CONTRACT.md`;
- complete and incomplete manifest fixtures under `fixtures/evidence/v1/`;
- a backend that validates, stores, and reads evidence packages;
- SQLite metadata and exact manifest/JPEG storage on the local filesystem;
- full-frame iOS evidence capture at six configured offsets;
- Python 3.13 and uv 0.12 in the root `mise.toml`.

The current code does not provide:

- a `vision_detector/` package;
- a visual-only input boundary;
- a vision-result contract or fixtures;
- detector execution or result persistence;
- a result read endpoint;
- real image bytes in the shared evidence fixtures.

Plan 0016 already refers to a local fake detector and result retrieval. This plan owns that missing
slice. Do not add the detector work to plan 0004 retroactively.

## 3. Scope boundary

### In scope

1. Freeze a small V1 vision-result contract.
2. Add a visual-only Python detector interface.
3. Add a deterministic scripted detector for fixtures and tests.
4. Adapt a stored backend package to detector input without player or game context.
5. Run one package or all pending packages from a local one-shot command.
6. Store immutable results in SQLite and as canonical JSON on disk.
7. Read stored results through HTTP.
8. Prove upload-to-result read-back with an automated local integration test.
9. Provide result fixtures that the game engine can consume before a real model exists.

### Out of scope

Do not add:

- object detection, tracking, card classification, or model training;
- synthetic card generation or annotation tools;
- claims about recognition accuracy or confidence calibration;
- GPU dependencies, PyTorch, OpenCV, or a model-serving framework;
- a daemon, queue, broker, scheduler, or multiple worker processes;
- cloud inference or a VLM API;
- automatic retries, leases, heartbeats, or distributed locking;
- player identity, seats, turn order, legal moves, or game state;
- production security, scaling, retention, or monitoring.

Do not hide the scripted detector behind language that suggests real visual recognition.

## 4. Fixed boundaries

### 4.1 Use the stored V1 evidence contract

The backend remains the owner of upload validation and stored evidence. The detector does not parse
multipart data and does not define a second evidence manifest.

The adapter reads the accepted package and creates this conceptual input:

```text
VisionEvidence
├── package_id
├── event_time_ms
└── frames[]
    ├── part_name
    ├── actual_offset_ms
    ├── width
    ├── height
    └── JPEG bytes or a read-only local reference
```

Do not pass these manifest fields into the detector:

- session identity or event sequence;
- CardEventNet model metadata or score trace;
- decoder configuration;
- client or device metadata;
- any future player, turn, or game-state field.

The orchestration layer may copy package and session identity into the stored result. The detector
itself must not use those values to infer a card. Event-relative frame timing is visual acquisition
context and is allowed.

### 4.2 Keep the PoC local and synchronous

Use one explicit command, for example:

```bash
cd backend
uv run python -m dokodetector_backend.run_vision --once
```

The command selects a stored package without a result for the configured detector version, invokes
the detector in the same process, stores the result, and exits. Add an explicit package-ID option
for deterministic tests and debugging.

Do not start detector work from an HTTP request. Do not add background task behavior to FastAPI.

### 4.3 Keep the detector replaceable

Scaffold `vision_detector/` as a small Python package. The PoC package has no ML runtime dependency.
Expose one interface:

```python
class VisionDetector(Protocol):
    def detect(self, evidence: VisionEvidence) -> VisionDetectionResult: ...
```

The backend depends on this interface and result model. It must not depend on future PyTorch,
OpenCV, detector, tracker, or classifier types.

Use a local editable package dependency during development. Keep the root `mise.toml` as the runtime
source of truth. Do not create a second Python version declaration that conflicts with it.

## 5. V1 vision-result contract

Create these canonical artifacts:

```text
VISION_CONTRACT.md
fixtures/vision/v1/example-ranked.json
fixtures/vision/v1/example-abstained.json
```

A result uses this common shape:

```json
{
  "schema_version": "vision-detection/v1",
  "result_id": "c648d0b8-f82f-4c50-9505-970907ea1f24",
  "package_id": "550e8400-e29b-41d4-a716-446655440000",
  "session": {
    "session_id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
    "event_sequence": 1
  },
  "status": "uncertain",
  "selected_card": null,
  "candidates": [
    {"card": "HEARTS_QUEEN", "probability": 0.58},
    {"card": "DIAMONDS_QUEEN", "probability": 0.42}
  ],
  "calibration": "fixture",
  "detector": {
    "name": "scripted",
    "version": "scripted-v1"
  },
  "observations": [],
  "diagnostics": {
    "frames_received": 6,
    "frames_decoded": 0
  },
  "created_at": "2026-08-26T18:12:00.000Z"
}
```

Allowed statuses are:

```text
confident
uncertain
no_card_found
insufficient_evidence
```

Contract rules:

- use the explicit card-set and deck manifests shared with plan 0006;
- map both physical copies of one card to the same visual identity;
- sort candidates by descending probability and do not include duplicates;
- keep every candidate probability finite and greater than zero;
- require each non-empty candidate list to sum to one within the contract tolerance;
- require a non-empty candidate list for `confident` and `uncertain`;
- set `selected_card` only for `confident`, and make it equal the first candidate;
- use an empty candidate list for `no_card_found` and `insufficient_evidence`;
- distinguish calibration states as `fixture`, `uncalibrated`, or `calibrated`;
- require an adapter to normalize model logits, distances, or arbitrary internal scores before it
  creates the result;
- keep observations optional and bounded;
- preserve the exact raw result when a later game engine selects another card.

Detector execution errors are not vision outcomes. If invocation or persistence fails, do not
write a result with `status: insufficient_evidence`. Exit with an error and retain the evidence for
another attempt.

## 6. Storage and idempotency

Add one migration with a `vision_results` table:

```text
result_id                 primary key
package_id                foreign key to evidence_packages
schema_version
detector_name
detector_version
status
selected_card             nullable
calibration
result_json               exact canonical JSON text
result_sha256
relative_path
created_at
```

Add a unique constraint on:

```text
(package_id, detector_name, detector_version)
```

Store the same canonical JSON bytes at:

```text
<evidence-root>/vision-results/<result-id>/result.json
```

Process and store one result atomically enough for the one-process PoC:

1. Confirm that the evidence row and package files still agree.
2. Invoke the detector.
3. Validate and serialize the result once.
4. Write a temporary result directory.
5. Insert the database row and rename the directory with compensation on failure.

An identical rerun for the same package and detector version returns the existing result. A
different result for the same key is a conflict and must not overwrite the first result. A new
detector version may create a new result for the same evidence package.

## 7. Scripted detector

The scripted detector loads a checked-in mapping from package ID to a valid result template. It
must support at least:

- a ranked ambiguous candidate list;
- a confident result;
- `no_card_found`;
- `insufficient_evidence` for an incomplete or metadata-only package.

The mapping is test control data. The detector may use the package ID only because it is explicitly
a fake. Production detectors must not do this.

When no mapping exists, return `insufficient_evidence`. Record `calibration: fixture`, report
zero decoded frames, and name the detector `scripted`. This makes fake output unmistakable in logs,
stored data, and the API.

The current shared evidence fixtures do not contain real JPEG files. The fixture upload command
generates deterministic bytes to prove transport and hashing. Do not decode those bytes or use them
for a recognition benchmark.

## 8. HTTP read API

Add read-only routes:

```http
GET /v1/evidence-packages/{package_id}/vision-results
GET /v1/vision-results/{result_id}
```

The package route returns all immutable results in deterministic creation order. It may return an
empty list. The result route returns `404 Not Found` for an unknown result ID.

Do not add a public result-write endpoint. The local runner owns creation after it loads accepted
evidence.

Use the backend's stable error envelope. Do not expose local file paths, detector configuration
paths, stack traces, or image bytes.

## 9. Small implementation milestones

### M0 — Contract and domain types

1. Add `VISION_CONTRACT.md` and the ranked and abstained fixtures.
2. Add the explicit card-set and deck-manifest configuration shared with plan 0006.
3. Add strict detector input and result domain types.
4. Test result status, candidate ordering, probability normalization, duplicate cards,
   selected-card rules, and unknown fields.

Acceptance:

- backend, detector, and future game-engine tests can load the same result fixtures;
- the result has no player, seat, turn, legal-move, or game-state field;
- fixture probabilities are labeled as fixture values, not calibrated model output.

### M1 — Detector boundary and scripted implementation

1. Scaffold the lightweight `vision_detector/` package.
2. Implement the protocol and visual-only `VisionEvidence` model.
3. Implement the configured scripted detector.
4. Test every result status and the default unmapped behavior.
5. Add a guard test that the detector input exposes none of the excluded context.

Acceptance:

- the package imports without an ML framework;
- scripted output is deterministic;
- evidence bytes remain read-only.

### M2 — Backend adapter, persistence, and read API

1. Load accepted evidence and verify stored hashes before invocation.
2. Strip the manifest down to `VisionEvidence`.
3. Add the result migration, repository, and atomic file storage.
4. Add the one-shot runner.
5. Add the two read endpoints.
6. Test rerun idempotency, conflict behavior, and a second detector version.

Acceptance:

- a failed detector call does not create a result;
- a failed database write does not expose an orphaned result directory;
- no accepted evidence or existing result is changed.

### M3 — Complete local pipeline proof

Use a temporary SQLite database and filesystem root. Test:

```text
shared evidence fixture
  -> HTTP upload
  -> stored package read-back
  -> one-shot scripted detector
  -> stored vision result
  -> HTTP result read-back
  -> parse with the game-engine-facing result model
```

Cover:

1. A complete package with an uncertain ranked result.
2. An incomplete package with `insufficient_evidence`.
3. An identical detector rerun.
4. A new detector version for the same package.
5. A detector exception followed by a successful retry.
6. Evidence file corruption detected before detector invocation.

This test supplies the fake-detector gate required by plan 0016. It does not need a phone, Docker,
a GPU, or network access.

### M4 — Handoff note for real recognition

Write a short report with:

- observed evidence package sizes and available frame offsets;
- whether actual iOS packages contain decodable complete-frame JPEGs;
- a list of labeled real evidence packages available for recognition work;
- gaps in deck, lighting, camera, and play-style coverage;
- any evidence-contract limitation found during the pipeline proof.

Do not start model training until at least one real, human-labeled event package exists. The two
shared upload fixtures are contract fixtures only.

## 10. Verification

Run the normal checks for each changed Python package. At minimum:

```bash
cd vision_detector
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .

cd ../backend
uv sync
uv run alembic upgrade head
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Run the complete local integration test with temporary storage. Ordinary tests must not require a
GPU, cloud account, camera, or valid gameplay JPEG.

## 11. Definition of done

- one command turns accepted evidence into an immutable scripted vision result;
- the detector receives visual evidence and event-relative timing only;
- the result preserves a ranked candidate list and explicit abstention states;
- fixture probabilities and scripted detector identity are unmistakable;
- a second detector version can process the same evidence without overwriting history;
- result files, database metadata, and HTTP read-back agree;
- the backend integration test proves upload through result retrieval;
- the game engine can consume the canonical result fixture;
- all relevant automated checks pass;
- no real-recognition, calibration, scale, or production-readiness claim is made.
