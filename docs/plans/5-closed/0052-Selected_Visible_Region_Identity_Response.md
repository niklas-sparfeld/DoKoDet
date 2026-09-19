# Selected response to visible-region identity failures

## Plan status

- **Summary:** Implement and evaluate at most one bounded visual identity response selected by the
  0051 resilience baseline.
- **Status:** Closed
- **Closure reason:** Won't Do
- **Closure note:** 0051 did not run the live comparison or select a measured follow-up response.
  No identity response is justified, and M0–M3 were not started. Record any future response as a
  new active epic only if later evidence shows a current identity failure that needs it.
- **Depends on:** 0051 complete with the `select_follow_up_identity_response` conclusion
- **Blocker:** 0051 must identify the measured failure, affected samples, fixed baseline, expected
  improvement, validation gate, and stop rule. No response is selected yet.
- **Builds on:** 0051 frozen corpus, corrupted-region conditions, crop policies, outcome semantics,
  paired predictions, and risk-versus-coverage report
- **Outcome:** Either prove one selected identity response against the unchanged 0051 baseline or
  reject it with retained evidence. Do not start an open-ended search or change the visible-region
  provider.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — replace the conditional outline with one concrete response selected by 0051.
- **M1:** Not started — implement the selected response with fixture and lineage coverage.
- **M2:** Not started — run the frozen paired comparison and risk-versus-coverage evaluation.
- **M3:** Not started — accept or reject the response and publish the next dependency decision.

## 1. Conditional scope

Do not start this epic merely because imperfect visible regions exist. Start it only when 0051 shows
that no simple frozen crop condition meets the declared identity accuracy, coverage, recall, and
harm gates, and that one bounded identifier response has a plausible measured benefit.

M0 must replace this section with one concrete implementation. Select at most one response from the
failure demonstrated by 0051. Examples include:

- deterministic agreement or fusion across a fixed set of crop conditions;
- a calibrated abstention rule based on fixed crop and geometry diagnostics;
- an explicit mask-aware identity input representation; or
- mask-error augmentation for the later local identity candidate recipe.

These are candidate response families, not permission to compare all of them. If the selected
response requires local model training, define its exact handoff to a later 0043-derived campaign
and do not create a second identity-training campaign here. If 0051 selects a simple crop policy, a
visible-region provider change, more reviewed data, or the current policy, close this epic as not
required.

Do not train RF-DETR, change Gemini visible-region instructions, add temporal association, change
game rules, or promote a model in this epic. Those actions have different evidence questions and
owners.

## 2. Fixed experiment rules

Keep the 0051 source frames, reference revisions, partitions, corruption conditions, baseline crop
policies, classifier baseline, and metrics unchanged. Add only the selected response and the minimum
new artifacts needed to reproduce it. Do not use the system holdout.

M0 must record:

- the exact 0051 failure and sample slice it addresses;
- one implementation and configuration;
- the permitted fitting inputs, if any;
- one cost and execution budget;
- minimum improvement and non-regression gates;
- a stop rule; and
- whether the result changes only an identity decision policy or becomes an input to a later local
  identity campaign after the first 0043 candidate.

Validation results cannot change the selected response or its thresholds. A failed gate rejects the
response. It does not authorize another candidate in this epic.

## 3. Delivery milestones

### M0 — Specify one response

- Read the completed 0051 report and paired failures.
- Replace the candidate outline with one concrete algorithm, configuration, and artifact contract.
- Freeze comparison membership, budget, gates, and stop rule.
- Update the epic board outcome text with the selected response.

Acceptance:

- every design choice traces to a measured 0051 failure;
- the baseline and validation inputs remain unchanged;
- only one response is selectable; and
- implementation fits in one Luna milestone.

### M1 — Implement the selected response

- Implement only the M0 response.
- Preserve complete crop, geometry, classifier, and decision lineage.
- Add a synthetic case where the response helps and one where it must abstain or remain neutral.
- Keep classified, unusable, and failed outcomes distinct.

Acceptance:

- deterministic inputs produce deterministic decisions;
- a bad segment cannot remove its visible-card proposal;
- unsupported or ambiguous evidence does not become a confident identity; and
- focused tests and applicable lint, format, type, and schema checks pass.

### M2 — Compare against 0051

- Run the response and unchanged baseline on the same development and validation items.
- Report accuracy, coverage, end-to-end recall, high-confidence errors, latency, cost, and results by
  0051 corruption family and actual generated-region quality.
- Preserve item-level disagreements and all unusable and failed outcomes.

Acceptance:

- metrics reproduce from stored paired rows;
- validation is evaluated once under the frozen configuration;
- no failed or abstained item disappears from a denominator; and
- the report states every improvement and regression.

### M3 — Accept or reject

- Apply the M0 decision gate without changing it.
- Accept the response as a later runtime or local-model candidate, or reject it and keep the 0051
  baseline.
- Record whether later visible-region provider work in 0050 is justified.
- Do not change a backend default or champion model implicitly.

Acceptance:

- the conclusion is one of `accept_response` or `reject_response`;
- rejected artifacts and failures remain reproducible;
- later local identity work receives one fixed identity input contract; and
- 0050 receives one fixed downstream identifier for provider comparisons.
