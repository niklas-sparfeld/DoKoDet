# Pipeline data and execution

## Plan status

- **Summary:** Store reusable pipeline results and maintained references, and run the development
  pipeline from original recording videos with explicit input selection.
- **Status:** Closed
- **Depends on:** Completed 0039, 0040, 0041, 0042, 0045, and 0046
- **Supersedes:** The data and execution direction of 0047 and the pipeline foundation work in 0022
- **Outcome:** Each processor can consume selected generated or reviewed data revisions, preserve
  its results, and feed the next processor without creating a review batch or using device packages.
- **Closure reason:** Complete
- **Closure note:** M0–M10 complete: recording-video pipeline execution, maintained reference lifecycle,
  coverage and downstream impact validation, immutable dataset consumer manifests, and the 0049
  cutover handoff are complete. Real-data quality measurement remains in 0043 and 0050.
- **Next:** [0049 — Recording pipeline review and comparison](0049-Recording_Pipeline_Review_and_Comparison.md)
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — define shared revision and run contracts with concrete event content.
- **M1:** Complete — persist runs, data revisions, and current selections.
- **M2:** Complete — resolve deterministic frames and crops from recording videos.
- **M3:** Complete — run, import, validate, and retain event results from recording video.
- **M4:** Complete — run and retain visible-card detector results.
- **M5:** Complete — run and retain visual card identity results.
- **M6:** Complete — assemble and store table observations from selected results.
- **M7:** Complete — run recording analysis from pinned table observations and explicit round context without evidence-package inputs; keep showcase package work independent.
- **M8:** Complete — add independent event, visible-card, and identity references with restart-safe drafts, immutable human revisions, stable correction lineage, and optimistic conflict handling.
- **M9:** Complete — validate full-recording event intervals, resolved-frame and upstream-card
  coverage; preserve matched draft decisions, track affected downstream work, and publish complete
  maintained references.
- **M10:** Complete — freeze selected references for existing dataset consumers and document the 0049
  cutover handoff.

## 1. Scope and ownership

The device is a recording collector for the current development and feasibility scope. Keep its
existing evidence packaging and upload as a showcase. Original recording video is the only visual
source for recording-based processing and review. Device-uploaded evidence packages, their frames,
and their snippets are never pipeline inputs or fallback media. Synthetic component fixtures remain
valid and must be identified as synthetic.

Reuse the filesystem helpers from 0046, the local detector and classifier interfaces, the existing
CardEventNet execution path, and the reconstruction engine. This epic owns application contracts,
concrete stores, processor execution, and dataset adapters. Epic 0049 owns the recording UI cutover,
interactive comparison, and removal of obsolete review routes. Do not build a general workflow
engine, graph editor, training platform, or another storage engine.

No model quality claim, training campaign, promotion, reconstruction search improvement, or complete
reconstruction editor belongs here. Those remain in 0043, 0044, 0050, 0023, and 0026. The completed
capability work of 0039 and 0041 is not reopened.

## 2. Data and run decisions

Use the [glossary](../../glossary.md). A pipeline data set has concrete content. A data revision is
an immutable version. A processor run binds exact inputs to outputs. A maintained reference is
human work with one current draft and one selected completed revision.

### Content boundaries

| Stage | Logical input | Stored content |
| --- | --- | --- |
| Event detection | Recording video | Events with type and source-relative timing |
| Visible-card detection | Event revision and video reference | Frame-linked card candidates and visible geometry |
| Identity classification | Visible-card revision and video reference | Card-linked visual identity candidates |
| Observation assembly | Selected event, visible-card, and identity revisions | Ordered table observations |
| Reconstruction | Selected table observations, rules, round context, optional correction constraints | Reconstruction hypotheses and analysis result |

The classifier result and observation assembly are separate application boundaries. Assembly reuses
existing behavior; it is not another learned model. It makes classifier predictions reusable before
reconstruction and keeps table observations independent of human review state.

For each content type, generated and human-authored or human-corrected data use the same schema and
validation of shared fields. Keep model scores optional and attributed to their producer; never
invent a confidence of 1 for a human decision. A reviewed identity can select one canonical identity
without fabricating a probability distribution. Preserve ranked model candidates in the original
result. Validate review-specific requirements at reference completion.

Do not reinterpret detector boxes as reviewed visible-region polygons. Record the geometry form a
provider actually produces and the normalization policy. A reviewed visible region retains the
existing visible-pixel meaning, including disconnected polygons and identity usability.

### Identity, lineage, and lifecycle

Every data revision records its identifier, content type and schema, recording and source digest,
content digest, exact input revision identifiers, producer or review lineage, and coverage. Stable
item identifiers preserve correction lineage within a reference. Different runs have different item
identifiers; comparison uses declared matching rules, not accidental identifier equality.

Every processor run records implementation and model identities, configuration, extraction and crop
policies, exact inputs, status, outputs, timing, and failures. Keep normal execution states separate
from review state. Failed or partial execution cannot appear as a complete result. Preserve explicit
per-item failures and successful results for diagnosis and retry. Retry of an incomplete operation
uses its frozen inputs; an intentional rerun creates a new run, including on identical inputs.

Use concrete content validators and stores with small shared filesystem helpers. Keep one selected
generated result per recording and stage for convenient defaults. Selection is a pointer; it does
not delete other results. A run resolves selection pointers once, at creation. Later selection or
reference changes cannot change that run's input or output. Persist completed results before
changing a selection pointer. A stale worker cannot replace newer work or a human draft.

Device event predictions may be imported as generated event data when their video timing and source
lineage can be validated. They are not an alternative visual source. Do not fabricate missing model
metadata for imported results. Event generation must also work from an uploaded video with no device
predictions or evidence packages.

### Visual input resolution

Resolve frame selection from video digest, event revision, extraction policy, and requested time.
Record the resolved frame index and presentation timestamp. Handle variable frame rates and boundary
conditions explicitly. Begin with the existing exact-event policy; do not change timing semantics
while moving ownership. Derive crops from resolved frames, selected geometry, and crop policy.

Cache keys include all inputs that affect bytes. Cache contents are disposable. A cold cache must
reproduce the same selection and derived content under the pinned decoder and transform versions.
Missing video or an unavailable frame is an explicit failure, never a fallback to device media or
a reviewed negative. Media files can remain cached for performance without becoming domain inputs.

### Maintained references and downstream use

Maintain one reference for events, one for visible cards, and one for visual identities per recording.
A reference can start empty or use a selected generated result as suggestions. Accepting, rejecting,
adding, or correcting suggestions changes only the reference draft. A rerun leaves reviewed work
unchanged. Completion publishes an immutable revision and updates the selected completed reference.
Further edits open or continue its single draft; no separately named review is required.

Full-recording event completion requires coverage of the whole video, including missing events.
Visible-card review covers explicit frames, including reviewed empty and unusable frames. Identity
review covers explicit visible cards and usability decisions. Accepting all supplied proposals is
not proof of complete source coverage. Review state does not propagate from inputs to predictions.

Changing an event time can select another frame. Changing a visible region can change the identity
crop. Track affected work by source and content dependencies. Preserve unchanged items. Require
review for changed evidence instead of silently copying a label onto new pixels. Old completed
revisions remain valid for their original evidence; they are not globally invalidated by a newer
reference. A current draft can show incomplete coverage while old pinned runs remain reproducible.

Dataset assembly freezes explicit source groups, reference revisions, and derivation policies.
Generated inputs are allowed for robustness experiments; unreviewed predictions are not reviewed
targets. Check target coverage and input-to-target alignment. Existing source permissions and
protected split rules remain in force. Never make all downstream runs require completed review.

## 3. Implementation specification

This section fixes the cross-milestone decisions. A milestone can add private helpers, but it must
not choose a different owner, storage layout, lifecycle, or public contract.

### Code ownership

| Boundary | Owner and intended location |
| --- | --- |
| Shared revision, source, run, selection, and event contracts | `operations/src/doko_operations/pipeline_data.py` |
| Visible-card and visual identity content contracts | `table_evidence_analyzer/src/table_evidence_analyzer/pipeline_data.py` |
| Frame and crop resolution | `operations/src/doko_operations/derived_view.py` |
| Immutable revisions, processor runs, and selection pointers | `backend/src/dokodetector_backend/pipeline_store.py` |
| Processor orchestration and maintained references | `backend/src/dokodetector_backend/pipeline_service.py` |
| Recording pipeline HTTP routes | `backend/src/dokodetector_backend/pipeline_api.py` |
| Observation payload validation | Existing `table_evidence_analyzer/table_observation.py`, revised in M6 |
| Reconstruction lifecycle | Existing `round_analysis_service.py` and `round_analysis_store.py` |

`doko_operations` owns application contracts that local commands and the backend can share. The
backend owns durable runtime stores because it already owns the 0046 filesystem helpers. The table
evidence analyzer owns vision-content validation. Do not import backend modules from either lower
package. Keep HTTP request models and generated-client models as translations of the application
contracts, not as alternate contracts.

M0 must add `docs/Pipeline_Data_Ownership.md`. Map each old event, visible-card, identity, and
observation operation to its retained validator/provider and to the milestone that replaces its
storage or orchestration. List the old review-batch and package entry points that remain until 0049.
This inventory is the cutover checklist; it is not a second architecture specification.

### Contract shapes

Use strict Pydantic models or frozen dataclasses with explicit parsers. Reject unknown fields,
non-finite numbers, booleans supplied as integers, unsafe identifiers, unsupported schema versions,
and timestamps without a UTC offset. Canonical JSON uses UTF-8, sorted keys, compact separators,
ASCII escaping, and rejects NaN. SHA-256 digests use lowercase hexadecimal.

A `data-revision/v1` envelope has these fields:

| Field | Type and rule |
| --- | --- |
| `revision_id` | Opaque safe identifier; unique within the pipeline root |
| `content_type` | `events`, `visible_cards`, `visual_identities`, or `table_observations` |
| `content_schema` | Exact schema identifier for `content.json` |
| `recording_id` | Recording bundle identifier, or absent only for a synthetic source |
| `source` | Tagged `recording-video/v1` or `synthetic-fixture/v1` reference |
| `content_sha256` | Digest of the canonical `content.json` bytes |
| `input_revision_ids` | Ordered unique upstream revision identifiers |
| `origin` | `processor`, `manual`, or `corrected` |
| `producer` | Tagged processor/import or human lineage; required fields depend on `origin` |
| `coverage` | Content-specific reviewed or processed scope; never inferred from item count |
| `created_at` | UTC timestamp used for display, never for identity |

A recording-video source contains `recording_id`, the accepted video's repository-relative path,
video SHA-256, byte length, and probed duration. A synthetic source contains a fixture identifier
and fixture digest and cannot carry a recording identifier. A manual or corrected revision records
review provenance and must not carry model metadata. A processor revision records `run_id` and may
carry attributed scores. A corrected revision also records its immediate base revision. The parser
checks that all items belong to the envelope source and recording.

Use `event-data/v1` in M0. Each item contains an opaque `event_id`, qualified event type, start and
end time in integer microseconds from the video start, and optional attributed model scores.
Require `0 <= start_us <= end_us <= duration_us`, stable order by `(start_us, end_us, event_id)`, and
unique item identifiers. Store workflow state, selections, draft commands, and review decisions
outside this payload.

A `processor-run-request/v1` contains a new `run_id`, processor type, recording-video source,
ordered exact input revision IDs, implementation identity, optional model identity, canonical
configuration, and named extraction/crop policies. The store resolves any requested selection to
exact IDs before it writes the request. A `processor-run-state/v1` contains status, attempt number,
timestamps, progress, per-item results or failures, terminal failure, and output revision IDs.
Configuration and policy values are complete values, not names whose meaning can change.

A `pipeline-selection/v1` document contains an integer `revision`, recording ID, content type,
optional selected generated revision ID, optional selected completed reference revision ID, and
`updated_at`. Every update supplies `expected_revision`; a mismatch is a conflict. Selection is a
convenience pointer and is never copied into a frozen run request.

### Filesystem layout and publication

Use this layout below the configured backend runtime and operations roots:

```text
.runtime/pipeline/
  revisions/<revision_id>/
    manifest.json                 data-revision/v1 envelope; publish last in staging
    content.json                  canonical content payload
  runs/<run_id>/
    request.json                  immutable after creation
    state.json                    mutable run state
  selections/<recording_id>/<content_type>.json
  derived-views/<cache_key>/      disposable frame or crop bytes plus manifest

data/operations/pipeline-references/<recording_id>/<content_type>/
  state.json                      mutable reference pointer and draft revision number
  draft.json                      mutable command-derived draft, absent when no draft exists
```

Completed reference content is published through the same immutable revision store as processor
content. `state.json` only points to the draft and the selected completed revision. It does not copy
completed content.

Use `staging_directory`, `commit_staged_directory`, `atomic_replace_json`, `contained_path`, and
`enumerate_resource_directories` from `backend/filesystem.py`. A revision becomes visible through
one staged-directory rename after both files validate and their digests agree. Publication of the
same ID and bytes is idempotent. The same ID with different bytes is a conflict. Ignore and report
staging or invalid directories on reads; never repair them during a read.

Create a run directory with its immutable request and initial state in one staged commit. Replace
only `state.json` under a per-run process lock. Write and validate an output revision before the
terminal run state references it. Update a generated selection only after the terminal state is
durable. Selection and reference mutations use a per-resource process lock plus expected revision.
The current local single-backend-process ownership rule from 0046 applies; do not add cross-process
or network-filesystem coordination.

Run states are `queued`, `running`, `complete`, `partial`, and `failed`. Transitions are
`queued -> running -> complete|partial|failed` and `partial|failed -> running` for an explicit retry.
A retry increments `attempt` and keeps the immutable request. It retains earlier per-item outcomes
for diagnosis and can replace only failed item outcomes. An intentional full rerun creates a new
run ID. Only `complete` can select an output revision. `partial` can retain successful item data in
the run state but cannot publish or select a data revision.

### Derived-view semantics

Move the reusable parts of `OpenCVVisibleCardFrameExtractor` and `FFmpegVisibleCardFrameExtractor`
out of `visible_card_review_batch.py`; keep temporary adapters there until 0049. The default resolver
uses FFmpeg/ffprobe and records their project-pinned versions. Keep OpenCV only as a tested provider
adapter when an existing local path needs it. Do not let the provider change within one run.

`exact-event/v1` resolves the first presentation timestamp at or after the requested event time,
subject to the source duration boundary. Record requested time, zero-based decoded frame index,
presentation timestamp in integer microseconds, source video digest, resolver name/version, and
policy. Use probed presentation timestamps for variable-frame-rate video; do not calculate them by
multiplying a nominal frame rate. An unavailable timestamp is a per-item failure.

`visible-region-crop/v1` accepts the resolved frame identity, stored geometry, image dimensions,
and the frozen crop-policy value. It returns bytes plus pixel bounds and transform metadata, or an
explicit unusable result. Detector boxes and reviewed polygons remain different tagged geometry
forms. The cache key is the SHA-256 of canonical source digest, view kind, request, policy,
decoder/transform versions, and output encoding. Verify the cached manifest and byte digest before
use. A missing or corrupt entry is a cache miss.

### Maintained-reference lifecycle

A reference state is `empty`, `draft`, or `complete`. `empty -> draft` creates one draft from no
suggestions or from one exact generated revision. `complete -> draft` creates the next draft from
the selected completed revision, with optional suggestions kept separately. Draft commands require
`expected_revision` and a unique command ID. Replaying the same command returns its earlier result;
reusing a command ID with different bytes is a conflict.

M8 supplies draft creation and editing for all three content types. M9 supplies coverage and affected
work, then enables completion. Completion validates content and coverage, publishes one immutable
manual or corrected data revision, atomically advances reference state, and finally updates the
selected completed-reference pointer. If pointer update fails, the published revision remains valid
and a retry can finish the pointer update. A generated selection change never mutates reference
state. A reference completion never changes the generated selection.

## 4. Delivery milestones

Implement one milestone per phase. Commit it, update this status and the board, and report all
milestone states. Use generated video, fake providers, and local filesystem fixtures for normal
checks. Each phase adds only the boundary named below.

### M0 — Shared contracts and ownership

Add the shared contracts and canonical JSON support described above to `pipeline_data.py`. Add
`event-data/v1` as the first concrete content type. Add the ownership inventory. Do not add stores,
HTTP routes, visible-card content, or processor execution.

Acceptance:

- strict byte fixtures round-trip generated, manual, corrected, and synthetic event revisions;
- invalid source digests, time bounds, input lineage, origin/producer combinations, unknown fields,
  and fabricated review or model metadata fail;
- run requests contain exact input IDs and complete configuration and policy values;
- selection parsing enforces its revision and the generated/reference pointer roles; and
- the ownership inventory names every retained implementation and every later cutover.

Run the operations contract tests and Ruff for `operations`.

### M1 — Revision, run, and selection stores

Add `PipelineRevisionStore`, `ProcessorRunStore`, and `PipelineSelectionStore` in
`pipeline_store.py`. Implement the fixed layout, publication order, validation, deterministic lists,
locks, state transitions, retries, and optimistic selection updates. Add no processor execution.

Acceptance:

- a new store instance finds all complete runs, revisions, and selections without an index rebuild;
- duplicate publication with identical bytes is idempotent and conflicting bytes fail;
- injected failures before each rename or atomic replace expose the old state or the complete new
  state, and staging or invalid directories remain invisible with a diagnostic;
- illegal transitions, stale expected revisions, output-before-publication, and selection of a
  partial or failed run fail;
- an explicit retry keeps request bytes and increments its attempt; and
- two intentional runs with identical inputs retain different run IDs and states.

Run focused backend store, restart, and failure-injection tests plus backend Ruff.

### M2 — Video-derived frame and crop resolution

Add `derived_view.py`, extract the existing FFmpeg and OpenCV media boundaries, and leave adapters in
the review-batch module. Implement `exact-event/v1`, `visible-region-crop/v1`, and the cache contract.
Pin the decoder and transform versions through the existing project toolchain or dependency files.

Acceptance:

- cold and warm resolutions produce equal identities and byte digests for constant-frame-rate and
  variable-frame-rate generated fixtures;
- a boundary request selects the defined presentation timestamp and records its actual frame index;
- time, geometry, source digest, policy, decoder version, transform version, or encoding changes the
  cache key;
- corrupt cache content regenerates from video and missing video is a failure; and
- a stored detector box and a disconnected reviewed polygon both resolve through their correct
  tagged geometry path without a review-batch directory or device package.

Run the operations derived-view tests, affected review-batch tests, and operations Ruff.

### M3 — Event processor execution and API

Add event orchestration to `pipeline_service.py`. Adapt the existing CardEventNet file inference path
behind one provider protocol; do not duplicate model loading or event decoding. Add import validation
for recording-bundle event predictions. Add start, get, list, retry, result, and generated-selection
routes under `/api/recordings/{recording_id}/pipeline/events` in `pipeline_api.py`.

The service creates and freezes the run before work starts. It validates that the accepted video
matches the request source. The worker publishes `event-data/v1`, completes the run, and then uses a
compare-and-swap selection update. Import creates a completed run whose producer records the source
artifact and known metadata; absent model fields stay absent.

Acceptance:

- a generated video with a fake local provider produces a stored event revision through the API;
- the backend restart preserves status and results, and startup marks an interrupted running event
  run failed with a restart reason;
- two configurations retain separate runs and outputs;
- a provider or import failure cannot change generated or completed-reference selections;
- imported and inferred events pass the same loader and content validator; and
- event inference works when the recording has no prediction file or evidence package.

Run operations CardEvent tests, focused backend pipeline API/service tests, generated OpenAPI/client
checks, and Ruff for both packages.

### M4 — Visible-card content and detector execution

Add `visible-card-data/v1` in the analyzer package. Each requested event outcome records the event ID,
resolved frame identity, status `detected|empty|failed`, and zero or more candidates. Each candidate
has a run-local stable card ID, tagged detector-box geometry, normalization dimensions/policy, and
optional attributed scores. `failed` requires an error and has no candidates; `empty` is successful
and has an empty candidate list.

Add a detector provider protocol and service path that accepts one exact event revision, resolves
frames through M2, and adapts the detector provider currently used by
`visible_card_review_batch.py`. Add matching start/status/result/retry/selection HTTP operations.

Acceptance:

- selected generated and completed-reference event inputs create valid detector runs;
- run request bytes contain the resolved event revision, provider, detector/model identity,
  configuration, and extraction policy before execution;
- two configurations retain distinct results and card identifiers;
- missing frames, provider failures, detected-empty frames, and detected candidates remain distinct
  after restart; and
- this path neither creates a visible-card review batch nor writes its latest-result artifact.

Run analyzer contract tests, operations provider tests, focused backend service/API tests, generated
client checks, and Ruff for affected packages.

### M5 — Visual identity content and classifier execution

Add `visual-identity-data/v1`. Each visible-card outcome records the upstream card ID, exact frame and
geometry identity, crop identity, status `classified|unusable|failed`, and the provider's ordered raw
candidates. A candidate has canonical visual card identity, optional score, score meaning, and
producer attribution. `unusable` is an input decision and `failed` is an execution error.

Add a classifier provider protocol. Adapt the 0041 local classifier and existing Gemini classifier
behind it with an explicit request provider. Resolve crops through M2. Add matching processor HTTP
operations.

Acceptance:

- detector and completed-reference geometry use the same classifier request and result contracts;
- every outcome retains its upstream card, frame, geometry, crop, provider, and model lineage;
- candidate order and supplied scores survive canonical storage without invented scores;
- unusable input, empty candidates, and provider failure remain distinct after restart;
- one frozen run never switches provider; and
- fake local tests require no credentials or model downloads.

Run local-identity, classifier-adapter, backend service/API, generated-client, and Ruff checks.

### M6 — Observation assembly and storage identity

Add a pure assembler that accepts exact compatible event, visible-card, and visual-identity revision
IDs and returns existing `TableObservation` values. Revise `ObservationSource` to reference the
recording video, assembly run, and ordered input revisions. Replace package/analyzer uniqueness in
`TableObservationStore` with observation ID uniqueness; list and filter by recording and input/run
lineage. Add an `observation-assembly` processor API. Do not infer gameplay state in the assembler.

Compatibility validation requires one recording/video digest across all inputs, event IDs referenced
by visible-card items, and card/frame/geometry identities referenced by identity items. Preserve the
existing meanings of identity-only evidence, detected-empty evidence, and insufficient evidence.

Acceptance:

- several assembly runs on one recording coexist and remain selectable;
- mismatched source digests, event associations, frames, cards, or geometry fail before publication;
- all observations trace to the recording video and exact input revisions with no package ID;
- identity-only, empty, failed-input, and insufficient observations round-trip distinctly; and
- existing synthetic reconstruction fixtures still parse the revised observation contract.

Run analyzer observation/assembly tests, backend observation store/API tests, reconstruction contract
tests, generated-client checks, and Ruff.

### M7 — Recording reconstruction execution

Change round-analysis creation to accept a table-observation revision ID, explicit round context,
rules version, and optional correction-constraint revision IDs. Resolve and copy those immutable
inputs into the analysis directory before queueing. Adapt `RoundAnalysisService` and its HTTP models;
reuse the existing worker, state transitions, result store, timeline, and counterfactual behavior.

Separate the iOS recording submission from evidence-package upload in the existing client boundary.
Recording acceptance completes when the original video bundle commits. Package generation and upload
remain an independently retryable showcase action. This milestone changes no recording UI.

Acceptance:

- a video-only fixture reaches completed analysis through exact observation and context inputs;
- package presence, absence, or upload failure cannot alter or block the analysis input;
- separate observation revisions produce separate pinned analysis inputs and results;
- recording boundaries never supply implicit game or round boundaries;
- restart and synthetic reconstruction lifecycle tests pass; and
- the iOS submission contract builds and its focused tests cover independent package failure.

Run engine, analyzer, round-analysis store/service/API, generated-client, and iOS contract/build
checks plus applicable formatting.

### M8 — Maintained-reference drafts

Add `MaintainedReferenceStore` and draft APIs for events, visible cards, and visual identities. Apply
the fixed lifecycle, locking, command replay, and source suggestions. Reuse content-specific edit
validation from `cardevent_review.py`, `visible_card_review_workflow.py`, and
`visual_card_identity_review_batch.py` through adapters; keep the old stores unchanged for 0049.
M8 does not expose completion because M9 owns its coverage rules.

Acceptance:

- each recording and content type permits at most one draft and returns a conflict for a second;
- a draft can start empty, from one exact generated revision, or from the selected completion;
- manual creation and correction use the same content item shapes as processor outputs;
- command replay is idempotent and stale revision or changed command bytes conflict;
- model reruns and generated-selection changes leave draft bytes and reference state unchanged; and
- restart preserves the draft, its base, suggestions, commands, and current draft revision.

Run old edit-validation tests through the adapters, new reference-store/API tests, generated-client
checks, and Ruff.

### M9 — Coverage, affected work, and reference completion

Add the three coverage validators and dependency projections before enabling completion APIs.
Event coverage is a normalized union of reviewed video intervals and full completion requires
`[0, duration_us]`. Visible-card coverage records every reviewed resolved-frame identity with
`cards|empty|unusable`; an absent frame is unreviewed. Identity coverage records every upstream card
and `identity|unusable`; an absent card is unreviewed.

For draft rebasing, match an event only by preserved item lineage plus unchanged event type and time
bounds. Match visible-card work only when event and frame identities are unchanged. Match identity
work only when card, frame, geometry, crop policy, and crop-byte digest are unchanged. Preserve a
matched decision and mark every unmatched downstream item as affected and incomplete. Never mutate
an old completed revision.

Acceptance:

- incomplete event intervals, absent visible-card frames, and absent identity decisions block
  completion with explicit gaps;
- accepting all suggestions cannot substitute for source coverage;
- a retimed event exposes its new frame, and changed geometry or crop bytes expose identity work;
- unrelated matched items retain their decisions and coverage;
- empty, unusable, failed, affected, and unreviewed states remain distinct; and
- completion publishes immutable content, advances reference state and the completed-reference
  selection in the defined order, and can recover from failure between those writes.

Run reference coverage/projection/completion tests, failure-injection and restart tests, API/client
checks, and Ruff.

### M10 — Dataset consumers and foundation proof

Adapt the existing event, detector, and identity dataset builders to accept explicit completed
reference revision IDs and full derived-view policy values. Freeze those IDs and policies in each
dataset manifest. Validate source-group permissions, protected splits, target coverage, and exact
input-to-target alignment before materialization. Keep generated revisions available only through
an explicit robustness-input option; they cannot supply reviewed targets.

Remove package reads from the new processor, reconstruction, and dataset paths. Add
`docs/Pipeline_Data_Cutover_Handoff.md` with the precise old routes/adapters for 0049 to remove, the
new API and storage entry points, commands used for the foundation proof, and measured real-data
gaps for 0043. Do not add compatibility migrations.

Acceptance:

- one generated local video passes event detection, visible-card detection, classification,
  observation assembly, and reconstruction with exact persisted lineage;
- completed event, visible-card, and identity reference fixtures feed their dataset builders;
- incomplete coverage, source mismatch, policy mismatch, permission failure, and protected-split
  leakage fail before dataset publication;
- an explicit generated-input robustness case works without labeling predictions as reviewed;
- file-access tracing proves that the flow reads no evidence-package media or manifest; and
- relevant operations, backend, analyzer, engine, generated API/client, and iOS checks pass from the
  project toolchain documented in `mise.toml`.
