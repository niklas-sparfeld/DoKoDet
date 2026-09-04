# Pipeline data and execution

## Plan status

- **Summary:** Store reusable pipeline results and maintained references, and run the development
  pipeline from original recording videos with explicit input selection.
- **Status:** Ready
- **Depends on:** Completed 0039, 0040, 0041, 0042, 0045, and 0046
- **Supersedes:** The data and execution direction of 0047 and the pipeline foundation work in 0022
- **Outcome:** Each processor can consume selected generated or reviewed data revisions, preserve
  its results, and feed the next processor without creating a review batch or using device packages.
- **Next:** [0049 — Recording pipeline review and comparison](../4-blocked/0049-Recording_Pipeline_Review_and_Comparison.md)
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — define shared revision and run contracts with concrete event content.
- **M1:** Not started — persist runs, data revisions, and current selections.
- **M2:** Not started — resolve visual inputs from recording videos.
- **M3:** Not started — run and retain CardEventNet event results.
- **M4:** Not started — run and retain visible-card detector results.
- **M5:** Not started — run and retain visual card identity results.
- **M6:** Not started — assemble and store table observations from selected results.
- **M7:** Not started — run recording analysis without evidence-package inputs.
- **M8:** Not started — implement maintained reference drafts and completion.
- **M9:** Not started — track review coverage and affected downstream reference work.
- **M10:** Not started — freeze selected references for existing dataset consumers.

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

## 3. Delivery milestones

Implement one milestone per phase. Commit it, update this status and the board, and report all
milestone states. Use generated video, fake providers, and local filesystem fixtures for normal
checks. Each phase adds only the boundary named below.

### M0 — Contracts

Define the common revision envelope, source references, run request/result, and selection records.
Use event content as the first concrete type. Record the ownership mapping for existing operations,
backend, and analyzer modules. Other concrete payloads are added in their processor milestones.

Acceptance: strict round-trip fixtures cover generated, manual, corrected, and synthetic events;
invalid source references and fake review metadata fail; no web-only or human-only event schema is
introduced. Record the content and workflow fields separately.

### M1 — Filesystem persistence

Add run and immutable revision publication plus atomic selection updates using 0046 helpers.

Acceptance: restart finds valid runs and revisions; duplicate publication is idempotent; conflicting
bytes, stale writes, and partial directories fail safely; intentional reruns retain both results.

### M2 — Video-derived views

Expose a reusable video frame and crop resolver around existing extraction implementations. Record
policies and resolved frame identity; make cache lookup and regeneration internal to the resolver.

Acceptance: cold and warm cache results agree; constant and variable-frame-rate fixtures select the
specified frame; time or crop changes miss the cache; missing video cannot use a supplied device
package. Resolve a crop from stored geometry without a review-batch directory.

### M3 — Event execution

Wrap existing CardEventNet inference in the run contract and import valid device event predictions
into the same event content schema. Expose start/status/result through application and backend APIs.

Acceptance: a video-only fixture produces an event revision; two configurations retain separate
results; failure does not replace selected results or reference work; imported and backend events
can be consumed by the same event loader.

### M4 — Detector execution

Add concrete visible-card content and a detector run that accepts any selected event revision.
Resolve images through M2 and reuse the current detector provider. Preserve normalized results,
provider metadata, empty results, and errors independently of review batches.

Acceptance: generated-event and reviewed-event inputs both run; two detector configurations on the
same input retain separate outputs; missing/failed frames remain distinct from detected-empty
frames; re-detection no longer overwrites a latest-result file in the new execution path.

### M5 — Identity execution

Add concrete identity content and a classifier run on selected generated or reviewed visible-card
geometry. Reuse 0041 local and existing Gemini adapters with explicit provider selection.

Acceptance: both geometry origins use the same classifier boundary; raw candidate lists and scores
survive storage; unusable input and classifier failure remain distinct; local fixtures require no
credentials or model downloads. The same run does not silently switch providers.

### M6 — Observation assembly

Assemble table observations from exact selected upstream revisions. Update observation source
references and storage identity to record run/input lineage rather than package/analyzer uniqueness.

Acceptance: multiple runs on the same recording coexist; identity-only, empty, and insufficient
observations keep their meanings; assembly rejects mismatched frames or card associations; all
observations trace back to video and input revisions without a device package ID.

### M7 — Recording reconstruction execution

Change recording analysis creation to select observation revisions and explicit round/rules context.
Reuse the engine and analysis lifecycle; source video provides diagnostic playback. Update the
existing client submission boundary where needed so recording analysis does not wait for package
upload. Keep the app's package generation and upload showcase available.

Acceptance: a video-only fixture reaches analysis; package presence cannot alter its input;
observation revisions produce separate pinned analyses; synthetic reconstruction checks pass;
recording boundaries do not silently become game or round boundaries. The iOS submission contract
builds and package-upload failure does not prevent independent recording submission.

### M8 — Maintained reference lifecycle

Add recording-owned drafts, suggestions, completion, and selected completed revisions for the three
concrete review stages. Reuse existing edit validation, revision guards, command replay, and
lifecycle receipts. Existing editors switch to these APIs in 0049.

Acceptance: manual creation and correction publish the same content types as processor runs;
completion without edits is valid; a second draft conflicts; old completions remain byte-identical;
a model rerun cannot modify a draft or its selected completed reference.

### M9 — Coverage and dependencies

Add explicit coverage and affected-item projections between event, visible-card, and identity
references. Reuse unchanged reviewed items only when their source and relevant content match.

Acceptance: a retimed event exposes new-frame review work; geometry changes expose affected identity
work; unrelated items retain review; empty, unusable, and unreviewed frames remain distinct; an old
pinned revision stays consumable for its original scope.

### M10 — Dataset consumers and foundation proof

Adapt existing event, detector, and identity dataset consumers to freeze selected reference revisions
and derived-view policies. Keep current source-group partition rules and crop-policy conditions.
Remove obsolete package requirements from the new execution and dataset paths. Record old review
adapters that 0049 removes when the UI switches; do not add compatibility migrations by default.

Acceptance: a generated local video passes events, detection, identity, observation assembly, and
reconstruction; completed reference fixtures feed all three dataset consumers; uncovered targets
fail eligibility; raw-input robustness cases stay possible; no device package is read. All relevant
operations/backend/analyzer tests, formatting, typing, generated API checks, and client contract
checks pass. Publish a concise handoff for 0049 and 0043, with remaining real-data gaps stated.
