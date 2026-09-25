# Visual identity crop inputs from virtual cards

## Plan status

- **Summary:** Let visual identity processing select a reviewed card-scene derived crop input,
  alongside generated Gemini polygons and RF-DETR segments.
- **Status:** Backlog
- **Depends on:** 0072 and 0073 complete
- **Outcome:** One visual identity run freezes exactly one selected crop input and one crop policy.
  It can classify crops derived from reviewed virtual-card scenes, generated Gemini polygons, or
  RF-DETR segments. Every outcome and crop preview retains exact source, geometry, and crop
  lineage. This epic does not change classifier ranking, review authority, card-scene editing, or
  default provider selection.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — freeze the crop-input contract, supported sources, availability rules,
  matching rules, and failure semantics.
- **M1:** Not started — resolve and validate each selected input through one backend crop-input
  boundary, then persist its lineage in visual identity run requests and outcomes.
- **M2:** Not started — make virtual-card derived visible regions a selectable visual identity
  input and materialize their deterministic identity crops.
- **M3:** Not started — expose clear input selection and inspectable provenance in the recording
  workspace, with focused integration and regression coverage.

## 1. Purpose

Reviewed card scenes are the canonical geometry authority when a recording has virtual cards. The
identity processor currently accepts one visible-card revision and derives crops directly from each
item's geometry. This couples the choice of input geometry to the crop policy. It also makes a
reviewed virtual-card scene difficult to select as the source of identity crops.

This epic separates these two decisions:

1. A **crop input** selects the immutable card and geometry view that supplies visual evidence.
2. A **crop policy** transforms that supplied evidence into one identity crop or an explicit
   unusable result.

The first supported crop inputs are:

| Input kind | Source | Geometry authority | Intended use |
| --- | --- | --- | --- |
| `gemini_polygon` | One generated Gemini visible-card revision | Processor-generated visible regions | Compare or run the existing Gemini path. |
| `rfdetr_segment` | One generated RF-DETR visible-card revision | Processor-generated visible regions | Compare or run local segmentation results. |
| `reviewed_virtual_card` | One completed maintained reference with a reviewed card scene | Deterministic visible regions derived from reviewed card poses and stacking order | Canonical identity crops where virtual cards exist. |

Input kind describes the source of geometry. It is not a classifier provider, a crop policy, or a
claim that generated geometry is reviewed. The virtual-card input must use the completed reference's
validated derived visible-region view. Do not crop from a proposed card scene, an incomplete draft,
or full-card outlines that include hidden pixels.

The processor remains a batch operation over one selected input. It must not silently combine input
kinds, fall back from a missing virtual-card input to a generated revision, or select the newest
result. A user must choose the input when more than one eligible input exists. The UI may preselect
the single eligible input and must show why other choices are unavailable.

## 2. Frozen contract and rules

### 2.1 Crop-input contract

Add a versioned crop-input value to the visual identity processor request. It must contain:

- input kind and exact immutable source revision or completed-reference revision;
- recording and accepted video identity;
- exact source-frame identities and card IDs selected from that source;
- source geometry and source-view digests;
- for `reviewed_virtual_card`, card-scene revision, calibration revision and digest, scene
  derivation receipt digest, and derived visible-region digest; and
- an ordered item manifest and a digest over all above values.

Keep crop policy as a separate frozen request value. A policy is compatible only with geometry it
can represent. The implementation may map a generic policy to an item-level policy where existing
mixed reviewed/generated geometry requires it, but the resolved policy and reason must be retained
per outcome. Do not let a policy alter the selected crop input's geometry.

Each visual identity outcome must retain crop-input provenance in addition to its existing frame,
geometry, crop identity, classifier, candidates, and status. Derived-view cache keys and browser
previews must include all geometry and crop-input lineage needed to reject changed inputs.

### 2.2 Eligibility and identity matching

An input is eligible only when it belongs to the selected recording, resolves to the accepted video,
has complete immutable lineage, and supplies a valid frame and card geometry for every selected
item. The service must reject a mixed recording, changed source bytes, stale scene derivation,
invalid calibration, duplicate card IDs in one frame, or a card without valid geometry before it
queues classification.

For `reviewed_virtual_card`, require a completed maintained reference with a valid reviewed card
scene and a current deterministic derived candidate view. Its card IDs, frame IDs, sides, identity
usability, and visible regions come from that derived view. The scene remains the geometry authority;
visual identity outcomes do not write back into it.

Generated input items keep the selected generated revision's card IDs and geometry. They do not
match or merge with virtual-card items by spatial overlap. Cross-input comparison is a later,
explicit operation. It must not be an implicit execution rule in this epic.

Face-down, identity-unusable, and failed crop semantics remain unchanged. A face-down item does not
invoke the classifier. An unusable crop publishes an unusable outcome. A missing input, invalid
lineage, or crop-resolution error fails the affected item or rejects the run according to whether
the defect was detectable before queueing. It never changes the selected input kind.

### 2.3 Selection and presentation

The recording workspace must list eligible crop inputs with a human-readable label, source type,
revision, frame/card count, source state, and exact provenance. Show the reviewed virtual-card input
as the canonical choice when it is eligible. Do not label a generated Gemini or RF-DETR result as
canonical.

The run form must submit the exact selected crop-input descriptor and crop policy. On the run result,
show the selected input and resolved per-item provenance beside the crop preview. Historical runs
must keep their original selection even if a later generated result or completed reference appears.

Unavailable options remain visible with actionable reasons, such as no completed reviewed card
scene, invalid or stale scene derivation, no RF-DETR result, or source-video mismatch. This epic
does not add editing actions to the visual identity screen.

## 3. Delivery milestones

### M0 — Freeze crop-input semantics and fixtures

- Inspect the current visual identity request, visible-card revisions, completed maintained
  references, card-scene derivation receipt, derived-view cache identity, and workspace run form.
- Define the versioned crop-input schema, the three input kinds, compatibility with crop policies,
  availability rules, item ordering, and lineage digest rules from section 2.
- Add contract fixtures for one Gemini polygon input, one RF-DETR segment input, one completed
  reviewed virtual-card input, mixed frames, face-down cards, unusable crops, and invalid inputs.
- Define the exact pre-queue rejection versus per-item failure boundary.

Acceptance:

- the fixtures distinguish crop input from crop policy and classifier provider;
- the same input manifest serializes and digests identically across repeated runs;
- a virtual-card fixture includes scene, calibration, derivation, source-frame, and visible-region
  lineage; and
- no fixture permits a draft, proposed scene, hidden full-card outline, or newest-result lookup to
  act as a reviewed virtual-card crop input.

### M1 — Resolve inputs through one visual identity boundary

- Add a resolver that validates and freezes one selected crop input before a run is queued.
- Adapt visual identity request, processor-run storage, API models, result serialization, and
  generated client contracts to retain crop-input provenance.
- Route Gemini and RF-DETR revision geometry through that resolver without changing their current
  crop bytes when the equivalent policy is selected.
- Make outcome and derived-preview resolution validate the frozen input and resolved geometry
  identity before returning a crop.

Acceptance:

- one run cannot contain multiple input kinds or implicit fallback input;
- restart, retry, result retrieval, and browser preview preserve the same input manifest and crop
  digest;
- changed revision bytes, source bytes, geometry digests, or selected input IDs are rejected rather
  than served from cache; and
- existing generated Gemini and RF-DETR paths retain their supported outcomes under equivalent
  explicit input selection.

### M2 — Materialize reviewed virtual-card identity crops

- Resolve a completed maintained reference's validated derived visible-card candidate view as the
  `reviewed_virtual_card` input.
- Reuse the shared scene derivation path; do not duplicate pose projection, rounded outlines,
  stacking-order occlusion, or source-frame clipping in the identity processor.
- Derive identity crops from the resulting visible regions, preserving side, identity usability,
  failure tags, crop policy, and exact crop identity.
- Add focused fixtures and API/service tests for isolated cards, front-over-back overlap,
  disconnected visible components, rounded corners, frame clipping, stale derivation, invalid
  calibration, fully hidden cards, face-down cards, and changed source frames.

Acceptance:

- cold and warm virtual-card crop resolution returns identical crop bytes, crop identity, and
  lineage digests;
- crop pixels exclude card regions hidden by a front card and do not use the hidden full-card
  extent;
- a stale or invalid scene cannot produce a crop or silently use generated geometry; and
- visual identity classification receives the same exact crop bytes exposed by the derived-view
  endpoint.

### M3 — Select and inspect crop inputs in the workspace

- Add crop-input availability and selection to visual identity run controls.
- Display the canonical reviewed virtual-card option when eligible, plus generated Gemini and
  RF-DETR options when present.
- Show unavailable reasons, the selected source revision, item count, crop policy, and per-item
  input provenance in run history and crop inspection.
- Add focused UI tests for single-input preselection, multiple-input explicit selection, unavailable
  virtual cards, historical-run stability, and source/crop provenance presentation.

Acceptance:

- a user can deliberately run visual identity from each eligible input kind without editing the
  card scene or changing the classifier;
- the UI does not claim generated input is canonical and does not select a different revision after
  a rerender or restart;
- crop previews identify the selected geometry input and resolved crop policy; and
- focused contract, service/API, generated-client, derived-view, and rendered workspace tests pass.

## 4. Non-goals

- Do not promote RF-DETR, Gemini, or any identity classifier as the global default.
- Do not revise visual identity ranking, thresholds, auto-approval, table observation assembly, or
  game reconstruction.
- Do not use proposed card scenes or draft virtual cards as canonical crop inputs.
- Do not merge card identities across generated and reviewed inputs or infer physical-card tracking.
- Do not change the reviewed card-scene editor, calibration fitting, or pose-generation algorithm.

## 5. Verification

Each milestone uses fixtures and deterministic digests first. Run focused operations derived-view
and geometry tests; backend visual identity service, API, persistence, and restart tests; generated
client checks; and focused rendered workspace tests. Run type checking, linting, formatting, and
build checks for changed packages. Record unrelated known failures separately.
