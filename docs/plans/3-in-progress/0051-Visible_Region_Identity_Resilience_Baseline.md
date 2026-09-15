# Visible-region identity resilience baseline

## Plan status

- **Summary:** Make visual identity processing safe under inaccurate predicted visible regions and
  measure whether visible-region exclusion can recover contaminated crops before any detector or
  identity-model change.
- **Status:** In Progress
- **Depends on:** 0048 and 0049 complete; 0065 before freezing affected `IMG_0661` items
- **Readiness:** M0–M3 are complete. The M0 manifest is reconciled with durable operations storage,
  shared bundle validation, the current classifier and crop defaults, and the current reference
  lifecycle. Complete 0065 before ambiguous `IMG_0661` stacks enter the freeze. Completed paired
  maintained visible-card and visual identity references from the frozen development and validation
  groups remain required.
- **Builds on:** 0038 crop-policy evidence and the 0048 visual identity outcome, derived-view, and
  observation-assembly contracts
- **Outcome:** Publish a reproducible risk-versus-coverage baseline for the current identifier under
  actual and controlled visible-region errors. Select a simple crop policy, one bounded follow-up
  identity response in 0052, a later visible-region provider experiment, or more review work.
- **Next:** [0052 — Selected response to visible-region identity failures](../4-blocked/0052-Selected_Visible_Region_Identity_Response.md)
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — the manifest reads durable revisions, uses shared bundle validation, follows
  completed-reference producer lineage, freezes the current Gemini 3.8 request and runtime crop
  contract, assigns explicit development and validation recordings, records the full
  sample-condition-corruption request and cost preflight, and freezes the exact frame and geometry
  inputs needed by M3. The coverage gate is open after the completed `IMG_0661` visual identity
  review; four face-down items and one source-problem item remain explicit exclusions.
- **M1:** Complete — preserve every visible-card proposal across classified, unusable, and failed
  visual identity outcomes. Empty successful classifier output is normalized to unusable, and
  reconstruction treats empty identity evidence as neutral.
- **M2:** Complete — add deterministic predicted-region and visible-region-exclusion crop
  conditions without changing stored geometry. Crop lineage records the frozen exclusion policy,
  every input, every decision, and the original target geometry. Corruption generation records
  family, severity, seed, source digest, output digest, and transform version.
- **M3:** Complete — the dry-run planner, resumable crop materializer, classifier-result receipts,
  pinned-classifier executor, paired metrics, and immutable item-level output are implemented.
  Crop and classifier reuse require matching request and crop digests. The live Gemini execution is
  an explicit operator action because it consumes the frozen provider budget.
- **M4:** Not started — publish the decision and resolve the scope of 0052 and later detector work.

## Current evidence and partition intent — 2026-09-15

The reconciled M0 scan accepts 44 recording bundles through the shared repository validator. It
reads 164 pipeline revisions from `data/operations/pipeline/revisions` and 53 completed maintained
references. It does not read the retired `.runtime/pipeline/revisions` path.

`IMG_0090` and `IMG_0091` are one visually similar development comparison group. The manifest
assigns their recording IDs explicitly to development and preserves their separate source-lineage
groups for reporting. `IMG_0661` is the different validation recording and is assigned explicitly
to validation. The manifest does not infer validation from identifier order.

The development partition currently provides 200 paired samples. Completed `IMG_0661` review adds
100 validation samples. Four face-down cards and one source-problem card are excluded from the
identity matrix and remain explicit coverage gaps. Ignore-only regions from completed 0065 work are
not card samples.

The frozen matrix contains six crop conditions and 19 corruption variants for each selected sample.
The request budget selects 17 development samples and 24 validation samples, for 4,920 planned
classifier requests and an estimated cost of $4.7232. The full sample-linked coverage and preflight report is
`data/operations/visible-region-identity-resilience-m0.json`.

Untidy face-down stacks in `IMG_0661` do not support reliable card-instance geometry. Epic 0065
adds reviewed ignore regions for these pixels. Do not accept a stack polygon as one card, require
card-by-card correction, or let an omitted stack become background. Exclude ignore regions from the
identity sample matrix because they have no card or identity target.

## 1. Purpose and boundary

Test the visual identity pipeline before changing the visible-card detector or training another
identity model. A high-quality reviewed visible region is the upper bound. Generated Gemini visible
regions and deterministic corruptions represent the imperfect inputs that a deployable provider can
supply.

This epic answers four questions:

1. Which visible-region errors cause a wrong identity, an unusable identity, or an execution
   failure?
2. Can visible-region exclusion remove pixels from clearly separated neighboring cards and recover
   an otherwise contaminated identity crop?
3. Can the pipeline abstain without removing the visible-card proposal from the table observation?
4. Is one simple crop policy sufficient, or does the identifier need one further bounded response?

Do not train RF-DETR, revise a visible-card prompt, train or promote a local identity model, add
temporal association, or change reconstruction rules in this epic. Use the current configured
identifier as a fixed consumer. Keep all provider results, reviewed geometry, reviewed identities,
and source frames immutable.

## 2. Evidence and freeze

Use completed maintained references from 0048 and 0049. Every evaluation item must resolve to the
original recording video, one exact source frame, one reviewed visible card, and one reviewed visual
card identity. Keep generated visible regions as predictions with their original provider lineage.
They are never evaluation targets.

Require at least two source-lineage groups. Use one or more groups for bounded development and at
least one different group for validation. Do not use the system holdout. Do not select thresholds or
conditions from validation results. If this separation is not possible, publish the coverage gap and
stop before making a crop-policy decision.

Freeze these input families before classification:

- reviewed visible regions as the oracle condition;
- matched generated Gemini visible regions as the current deployable region condition;
- derived boxes for the rectangular comparison condition; and
- deterministic corruptions derived from reviewed visible regions.

The corruption manifest must include fixed severities for:

- erosion and missing boundary pixels;
- dilation into background or neighboring cards;
- position shift;
- holes and missing connected components;
- false disconnected components;
- pixels from another visible card in the same frame; and
- a complete derived-box fallback.

Generate corruptions without reading the validation identity label. Record the transformation,
severity, source geometry digest, output geometry digest, and seed. Use identical corrupted inputs
for every classifier or decision-policy condition.

## 3. Visual identity outcome semantics

Preserve the difference between visual evidence and execution state:

```text
classified  -> one or more ranked visual card identity candidates
unusable    -> no candidates; the pixels cannot support a reliable identity
failed      -> no candidates; the processor did not complete
```

An `UNKNOWN` response or an otherwise successful response with no candidates is unusable. It is not
an invalid response and not an execution failure. A provider timeout, malformed response, missing
crop, or unavailable implementation is failed.

Observation assembly must retain every upstream visible-card proposal. Add an explicit per-card
identity state to the active table-observation contract. A classified card requires non-empty
identity candidates. An unusable or failed card requires an empty candidate list and keeps its
anonymous observed-card evidence. Keep detailed processing errors in run diagnostics. Do not replace
missing identity evidence with a fabricated high-confidence identity or silently remove the card.

Revise the active schema directly. Do not add a compatibility layer for obsolete review-batch or
package routes that 0049 removed. Update the game engine so empty identity evidence is neutral and
does not create a card-play identity by itself.

## 4. Frozen crop conditions

Compare these conditions on the same items and source bytes:

1. `raw_rectangular`: the complete derived-box comparison crop.
2. `predicted_visible_region`: keep only the target generated visible region.
3. `generated_other_region_exclusion`: start with the target derived box and neutralize eligible
   interiors of other generated visible regions in the same frame.
4. `predicted_region_with_other_exclusion`: keep the target generated visible region and neutralize
   eligible interiors of other generated visible regions.
5. `reviewed_other_region_exclusion`: apply the same exclusion operation with reviewed neighboring
   regions as a non-deployable upper bound.
6. `oracle_visible_region`: keep only the reviewed target visible region.

Visible-region exclusion does not require stacking order. Reviewed visible regions describe visible
pixels, so a pixel assigned to one card cannot also be visible evidence for another card. Subtract
only the intersection between an eligible exclusion region and the target crop.

Define one conservative exclusion interior before validation. Erode each eligible other region by a
fixed amount relative to its derived-box size. This keeps uncertain boundaries out of the exclusion.
If eligible regions overlap materially, leave their disputed pixels unresolved. Deduplicate proposal
geometry before it can exclude pixels. Never let an exclusion result recursively become a new
exclusion region.

The deployable eligibility rule can use recorded provider confidence and geometry diagnostics. It
must not use reviewed acceptance, reviewed identity, validation correctness, game rules, or the
target classifier result. When a provider has no usable geometry confidence, record that limitation
and evaluate the declared deterministic fallback. Keep the reviewed exclusion condition separate as
an upper bound.

Every condition is a versioned crop policy. Its cache identity includes the complete frame and
geometry inputs, exclusion eligibility rule, erosion rule, fill value, encoding, and transform
version. Store derived crop lineage. Do not modify the source or predicted visible regions.

The current runtime chooses `predicted_visible_region` for generated visible-region geometry and
`oracle_visible_region` for reviewed visible-region geometry. Do not describe `raw_rectangular` as
the current default. Freeze the exact runtime policy and classifier identity in M0. Keep historical
identity results generated with an earlier explicit policy as predictions, not evaluation targets.

## 5. Evaluation and decision

Run the current configured identifier on every frozen crop condition. Reuse a cached result only
when its complete classifier request and crop digest match. Preserve `UNKNOWN`, unavailable, and
malformed results as different outcomes.

Report for development and validation:

- top-1 accuracy among classified outcomes;
- classified coverage and unusable rate;
- end-to-end correct-identity recall over all eligible visible cards;
- high-confidence error rate where the classifier provides a calibrated score;
- results by crop condition, corruption family and severity, source group, visible-card count,
  visible-area fraction, and neighboring-card overlap;
- identities recovered and identities harmed by each exclusion condition;
- operational failure, retry, latency, token, and estimated cost data; and
- paired sample rows with frame, geometry, crop, classifier, and reviewed-target lineage.

Do not call an uncalibrated score high confidence. For an uncalibrated single-candidate provider,
report agreement and correctness without treating `1.0` as probability calibration.

Freeze minimum acceptable classified accuracy, end-to-end recall, maximum harm from exclusion, and
minimum validation coverage in M0. End M4 with exactly one primary conclusion:

```text
adopt_simple_crop_policy
select_follow_up_identity_response
improve_visible_region_provider_later
collect_more_reviewed_data
keep_current_crop_policy
```

An adopted policy becomes an explicit candidate for later run configuration. This epic does not
change the backend default or promote a model. If `select_follow_up_identity_response` is chosen,
0052 must name one response and keep this baseline unchanged. If provider quality is the remaining
limit, later detector work must use this fixed identity baseline.

## 6. Delivery milestones

### M0 — Freeze corpus, conditions, and gates

- Read durable revisions from `data/operations/pipeline/revisions`; do not use the retired
  `.runtime/pipeline/revisions` default.
- Reuse the shared recording-bundle validator so M0 and repository validation select the same
  accepted inputs.
- Add a manifest that selects completed visible-card and visual identity reference revisions.
- Match generated regions to reviewed cards through revision producer lineage. Support the current
  completed-reference lifecycle, where the draft can use the selected completed revision as its
  edit source while the revision manifest preserves the generated base revision.
- Freeze source-group partitions, corruption transforms and severities, crop conditions, classifier
  identity, cost budget, metrics, and decision gates.
- Freeze the explicit development and validation recording groups and the exact
  sample-condition-corruption matrix. Calculate its classifier request and cost estimate before a
  classification request starts.
- Add a sample-linked coverage report before any validation classification runs.

Acceptance:

- every target identity and reviewed visible region has complete lineage;
- development and validation source groups are disjoint and the system holdout is absent;
- generated geometry remains a prediction and never becomes a target;
- all corruption and crop parameters are immutable inputs to the run; and
- the current configured classifier and runtime crop policy are recorded exactly;
- the planned experiment fits the frozen request, cost, and wall-clock budgets; and
- insufficient coverage stops the comparison with an explicit gap.

### M1 — Preserve cards across identity outcomes

- Normalize classifier `UNKNOWN` and empty successful output to an unusable visual identity outcome.
- Keep unusable distinct from operational failure through persistence, restart, retry, and API
  serialization.
- Revise table-observation and game-engine contracts so an observed card can carry no usable
  identity candidates without disappearing.
- Update assembly diagnostics and regression fixtures for mixed classified, unusable, and failed
  cards in one observation.

Acceptance:

- one unusable card does not fail its run or remove other successful outcomes;
- one failed identity outcome does not remove its visible-card proposal;
- reconstruction treats empty identity evidence as neutral and does not invent an identity; and
- contract, backend, generated-client, assembly, and game-engine tests pass.

### M2 — Add resilience crop conditions

- Add deterministic corruption generation from reviewed visible regions.
- Add predicted-region and visible-region-exclusion transforms through the shared derived-view
  boundary.
- Preserve original geometry and record all exclusion inputs and decisions.
- Add fixtures for a clean top card inside three neighboring derived boxes, over-segmentation,
  under-segmentation, duplicate regions, disputed overlap, and no eligible exclusion region.

Acceptance:

- a clean neighboring region is neutralized only inside the target crop;
- erosion keeps the declared uncertain boundary out of the exclusion;
- duplicate or disputed regions cannot erase pixels arbitrarily;
- a cold cache reproduces identical bytes and lineage; and
- unit, deterministic digest, and malformed-input tests pass.

### M3 — Run the paired resilience comparison

- Build a resumable executor that derives its work only from the frozen M0 manifest.
- Materialize every frozen condition and execute the current identifier within the M0 budget.
- Reuse a crop or classifier result only when its complete request and crop digest match.
- Calculate paired risk, coverage, recovery, and harm results.
- Retain item-level crops, outcomes, and diagnostics for UI inspection through 0049.
- Do not tune a condition after reading validation results.

Implementation note: the local M3 executor validates the frozen M0 manifest, reports the complete
work matrix before extraction, resolves exact source frames, writes item-level PPM crops and
resumable receipts, invokes the current classifier only for uncached usable crops, and calculates
deterministic paired metrics. It refuses to execute while `validation_classification_allowed` is
false. The implementation does not perform the live Gemini call automatically.

Acceptance:

- every aggregate metric reproduces from retained paired rows;
- a dry run reports the complete work matrix, cache reuse, request count, and estimated cost before
  execution;
- failures and unusable evidence stay in the denominator required by each metric;
- actual Gemini regions and synthetic corruptions are reported separately; and
- reviewed-region conditions are clearly marked as non-deployable upper bounds;
- crop and classifier receipts survive restart and reject changed request or crop digests.

### M4 — Publish the bounded decision

- Publish a concise report with the primary conclusion and failed gates.
- Record the selected crop policy without changing the runtime default.
- Update 0052 with one concrete response and gate, or close it as not required.
- Record whether later visible-region provider work is justified and which fixed identifier
  configuration it must use.

Acceptance:

- the decision follows the frozen M0 rules;
- harmful cases remain linked and inspectable;
- no detector, identity model, or default is changed implicitly; and
- 0043 and 0050 can consume the result without repeating this experiment.

## 7. Relationship to other epics

- 0048 and 0049 provide the active revision, run, review, comparison, and UI boundaries.
- 0043 consumes the selected identity input and crop contract when it evaluates local identity
  models. It does not repeat this crop-resilience selection.
- 0050 consumes the fixed resilient identity baseline when it measures visible-region providers and
  optional analyzer capabilities. Temporal association remains in 0050.
- 0052 exists only for one identity response selected by this epic. It does not start RF-DETR.
