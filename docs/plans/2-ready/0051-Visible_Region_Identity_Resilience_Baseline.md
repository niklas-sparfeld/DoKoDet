# Visible-region identity resilience baseline

## Plan status

- **Summary:** Make visual identity processing safe under inaccurate predicted visible regions and
  measure whether visible-region exclusion can recover contaminated crops before any detector or
  identity-model change.
- **Status:** Ready
- **Depends on:** 0048 and 0049 complete
- **Readiness:** M0 can inventory coverage, freeze the reusable measurement contract, and report
  the exact review gap. Completed paired maintained visible-card and visual identity references
  from at least two source-lineage groups remain required before validation classification.
- **Builds on:** 0038 crop-policy evidence and the 0048 visual identity outcome, derived-view, and
  observation-assembly contracts
- **Outcome:** Publish a reproducible risk-versus-coverage baseline for the current identifier under
  actual and controlled visible-region errors. Select a simple crop policy, one bounded follow-up
  identity response in 0052, a later visible-region provider experiment, or more review work.
- **Next:** [0052 — Selected response to visible-region identity failures](0052-Selected_Visible_Region_Identity_Response.md)
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — inventory eligible recording groups, freeze the measurement contract, and
  report the exact paired-review coverage gap before validation classification.
- **M1:** Not started — preserve every visible-card proposal across classified, unusable, and failed
  visual identity outcomes.
- **M2:** Not started — add deterministic predicted-region and visible-region-exclusion crop
  conditions without changing stored geometry.
- **M3:** Not started — run the paired resilience comparison with the current identifier.
- **M4:** Not started — publish the decision and resolve the scope of 0052 and later detector work.

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
- derived boxes for the current raw condition; and
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
package routes that 0049 removes. Update the game engine so empty identity evidence is neutral and
does not create a card-play identity by itself.

## 4. Frozen crop conditions

Compare these conditions on the same items and source bytes:

1. `raw_rectangular`: the complete derived-box crop.
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

- Add a manifest that selects completed visible-card and visual identity reference revisions.
- Match generated regions to reviewed cards through recorded proposal and correction lineage.
- Freeze source-group partitions, corruption transforms and severities, crop conditions, classifier
  identity, cost budget, metrics, and decision gates.
- Add a sample-linked coverage report before any validation classification runs.

Acceptance:

- every target identity and reviewed visible region has complete lineage;
- development and validation source groups are disjoint and the system holdout is absent;
- generated geometry remains a prediction and never becomes a target;
- all corruption and crop parameters are immutable inputs to the run; and
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
- unit, property, digest, and malformed-input tests pass.

### M3 — Run the paired resilience comparison

- Materialize every frozen condition and execute the current identifier within the M0 budget.
- Calculate paired risk, coverage, recovery, and harm results.
- Retain item-level crops, outcomes, and diagnostics for UI inspection through 0049.
- Do not tune a condition after reading validation results.

Acceptance:

- every aggregate metric reproduces from retained paired rows;
- failures and unusable evidence stay in the denominator required by each metric;
- actual Gemini regions and synthetic corruptions are reported separately; and
- reviewed-region conditions are clearly marked as non-deployable upper bounds.

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
