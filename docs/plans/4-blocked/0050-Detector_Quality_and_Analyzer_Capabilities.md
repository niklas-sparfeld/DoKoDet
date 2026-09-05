# Detector quality and analyzer capabilities

## Plan status

- **Summary:** Measure current detector and composed observation quality, then select only the
  optional analyzer capability work justified by observed failures.
- **Status:** Blocked
- **Depends on:** 0048, 0049, and 0051 complete; 0052 resolved when 0051 selects a follow-up
  response; plus reviewed real video-derived evidence for the selected measurement with
  source-group-safe development partitions
- **Blocker:** The new run/reference workflow, resilient visual identity baseline, and sufficient
  reviewed real coverage are not ready.
- **Supersedes:** The remaining detector and optional capability experiments from 0022
- **Outcome:** A reproducible baseline report and a bounded next capability decision, followed by
  at most one measured capability implementation. No automatic model promotion.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — freeze the baseline question, coverage, inputs, and metrics.
- **M1:** Not started — compare current detector and composed observation behavior.
- **M2:** Not started — specify one bounded response to the measured gap.
- **M3:** Not started — implement and evaluate only that selected response, if justified.

## 1. Keep the useful evidence questions

The old 0022 cloud-first implementation sequence is superseded. Local detection, identity models,
review editors, and storage already exist. Reuse them through 0048 and 0049. Use the fixed resilient
identity input and decision policy from 0051 and any required 0052 response. Do not repeat their
implementation or carry forward old model names, prices, capture offsets, or provisional quality
thresholds as current requirements.

Freeze the question before the run. Compare the configured local detector and an explicitly selected
existing baseline on identical video-derived frames and the same reviewed reference. Record model,
configuration, extraction policy, review coverage, source groups, and run identities. If a cloud
baseline is used, record its current measured usage and pricing assumptions at that time.

Measure instance recall, false and duplicate detections, visible-region overlap where comparable,
usable-crop recall, empty/unusable/failure rates, latency, and resource cost. Stratify by session,
table setup, deck design, card count, side, occlusion, blur, glare, and human-hand overlap. Report
geometry forms separately where a box-only provider cannot support a polygon-quality claim.

Measure reviewed-event and generated-event inputs separately. Compare classifier behavior on
reviewed and generated geometry without changing its model. Identity candidate training and the
local classifier quality decision remain in 0043. This epic measures how detection, timing, and
optional evidence affect composed table observations and reconstruction.

## 2. Candidate responses

Choose only from measured needs, not a predetermined architecture sequence:

- event-time or frame-selection policy changes when useful evidence is missed;
- detector correction or a bounded training recipe when localization is the limiting error;
- multi-frame association when repeated frames can reduce false or duplicate observed cards;
- presence evidence, distinct from identity confidence;
- transition evidence such as newly visible cards, without declaring a card play;
- active table area evidence without applying game rules;
- short card tracklets from video-derived snippets when simpler frame methods are insufficient.

Preserve the identity-only observation baseline. Keep optional capabilities absent when unavailable,
not zero. For a capability change, add a synthetic case where it helps and one where it misleads.
Compare reconstruction with and without the capability using the same observations and rules.
Do not infer persistent physical-card identity from a tracklet or manufacture hidden card pixels.

## 3. Milestones and readiness

### M0 — Freeze one baseline

Specify source-group coverage, sample count, reviewed frame scope, baseline processors, metrics,
matching rules, cost/time budget, and decision thresholds before execution. Use 0049 coverage to
report missing data. Thresholds must follow the declared feasibility question, not the old 0022
price projections. Do not mark this epic Ready until M0 has an actionable corpus and bounded recipe.

Acceptance: immutable manifests resolve to original videos and completed reference revisions;
protected holdout groups are excluded; unavailable and uncovered inputs have explicit treatment.

### M1 — Measure the baseline

Run the frozen paired comparisons through 0048. Publish sample-linked outcomes and failure slices.

Acceptance: every metric reproduces from stored results; input changes are distinguished from model
changes; composed errors are separated into event selection, detection, crop, identity, and engine
behavior. A data gap is an allowed result and does not trigger an undeclared experiment.

### M2 — Select one response

Choose one candidate response or close with a baseline-only outcome. Before M3, replace its outline
below with a small, concrete implementation and acceptance gate, or create a separate epic if the
response cannot fit one implementation phase.

Acceptance: the decision names the measured failure, expected effect, frozen comparison, budget,
and stop rule. Broader tracking, segmentation, or training work is not smuggled into M3.

### M3 — Prove the selected response

Implement only the response specified in M2, then run the paired baseline and capability ablation.

Acceptance: local fixtures pass; the report records improvement, regressions, coverage, latency,
and uncertainty. Preserve all baseline results. Publish the next bounded decision without automatic
promotion. If M2 selects no response, mark M3 not required and close with the recorded reason.
