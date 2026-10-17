# Detector quality and analyzer capabilities

## Plan status

- **Summary:** Correct two measured integration boundaries from the 0090 pilot, then measure
  downstream behavior with the same models and retained automatic inputs.
- **Status:** Ready
- **Depends on:** Completed 0048 and 0049; completed 0086 reviewed evidence; completed 0087 and
  0088 bundle decisions; completed 0092 M4 bundle; completed 0090 composed pilot report.
- **Readiness:** The three original videos, frozen references, and retained 0090 processor results
  are available in the main checkout. M0 can inventory these artifacts without inference or new
  human review. Missing reconstruction context and review targets are explicit coverage limits.
- **Supersedes:** The remaining detector and optional capability experiments from 0022.
- **Outcome:** Correct comparison coverage, explicit handling of frames with no individual-card
  detections, and a bounded report on identity and table observations. The report will select the
  next evidence question, if one is justified.
- **Target architecture:** [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — freeze retained inputs, comparison policy, stage contracts, and run budget.
- **M1:** Not started — compare identical decoded images and correct the geometry coverage report.
- **M2:** Not started — handle scene inputs with no individual-card detections.
- **M3:** Not started — verify identity, observation, and coordinator handling of those inputs.
- **M4:** Not started — run the bounded diagnostic and publish the next decision.

## 1. Evidence and question

The [0090 M3 report](../../reports/0090-M3_Composed_Pilot.md) retained event, detector, and scene
outputs for three recordings. All three sequences stopped on a partial scene result. Identity,
table observations, and reconstruction did not run.

Inspection after that report found two specific boundaries to correct:

1. All 19 unsupported scene frames have zero individual-card candidates. Ten contain pile-region
   detections and nine contain neither kind of detection. These are detector results. They do not
   establish that the images contain no individual cards.
2. Two `cardeventnet-IMG_0662` predictions use byte-identical decoded images from the reviewed
   geometry reference. All frame-identity fields agree except `requested_time_us`. Comparison of
   the complete frame-identity record excluded these pairs. The other two recordings have no
   shared decoded image hashes in the retained outputs and references.

The shared IMG_0662 frames have frame indices 300 and 375. Their predicted/reference requested
times are 5,000,000/5,004,836 us and 6,250,000/6,256,044 us. M0 must reproduce these facts from
stored revisions. The original 0090 report's statement about complete provenance equality is
insufficient to conclude that no images can be compared.

The question is: can the retained automatic detections produce valid identity and table-observation
outputs after these integration corrections, and what quality can the available references measure?
A model improvement decision requires comparable reviewed evidence after this diagnostic.

## 2. Frozen scope

Use the exact source groups, source hashes, reviewed revision IDs, exclusions, model digests, crop
policy, and extraction versions in the [0090 M0 freeze](../../reports/0090-M0_Composed_Pilot_Freeze.json).
Use the 0092 M4 two-class detector and 0088 M6 diagnostic identity bundle. M6 remains unqualified;
all identity predictions require human review. Preserve the frozen event settings and polygon-IoU
threshold of 0.5.

Reuse these immutable automatic outputs. Resolve each full revision ID from the
[0090 M3 artifact table](../../reports/0090-M3_Composed_Pilot.md) and verify its content hash.

| Recording | Event processor run | Detector processor run | Original scene processor run |
| --- | --- | --- | --- |
| `cardeventnet-IMG_0657` | `coord-d991572cdb65618247c1` | `coord-07d852bb91cfc6b19f7a` | `coord-3c10c8bdaa3a72b0c361` |
| `cardeventnet-IMG_0662` | `coord-08c097cc5f1b4024e867` | `coord-aa2ab2751f97e23f4dd2` | `coord-20c6e5e069cd8c74a97b` |
| `game-2026-08-20-01-001` | `coord-adf623bae2f082065bba` | `coord-d7821eb650044d5b3606` | `coord-d0e13247e47284a18828` |

Use original video and automatic upstream results for execution. Reviewed geometry and identity
revisions remain comparison targets. Preserve all original data revisions and processor states.
Changed implementations must use new processor run IDs and record their implementation identity.
Do not reuse old scene results as results from corrected code.

This scope includes comparison, scene outcome handling, downstream integration, and measurement.
New model training, threshold tuning, alternative providers, temporal association, tracking, UI,
cloud calls, promotion, and default changes require a separate decision. The 0067 candidate remains
available through its [historical handoff](../../reports/0067-RF_DETR_Visible_Region_PoC_Decision.md);
it is outside this diagnostic's provider recipe.

## 3. Delivery milestones

Each milestone is one Luna phase. Complete and commit one milestone, update this epic and the board,
and stop with the next milestone identified.

### M0 — Freeze retained evidence and contracts

Create `docs/reports/0050-M0_Diagnostic_Freeze.md` and a machine-readable companion. Record the
exact source and reference hashes, the nine original processor requests and states, output revision
IDs and hashes, model digests, code revision, and the new execution budget. Use deterministic local
inspection only. Do not start models or rewrite selections during this phase.

Reproduce the 19 unsupported frame IDs and their candidate/pile counts. Reproduce decoded-image
pairing for all three recordings and the two IMG_0662 pairs. Inventory candidate-bearing frames
with real fit or calibration failures separately from frames with no individual-card candidates.
Missing local assets must produce an actionable preflight result, not an automatic substitute.

Freeze the implementation contract for M1–M3:

- Comparison may pair frames when source video hash, decoded image hash, frame index and presentation
  timestamp, dimensions, and decoding/transform/encoding fields agree. `requested_time_us` may differ.
  Record both complete identities and event IDs. Reject every other identity mismatch. This policy
  applies to comparison only; revision lineage, crop authority, cache keys, and mutation checks keep
  their own strict contracts.
- A successful detector result with zero individual-card candidates needs no card pose. Preserve
  pile regions separately. Record that no cards were detected without asserting reviewed absence.
  Failed or unusable detector results must retain their failure state.
- A mixed recording must still enforce calibration and fitting requirements for frames that have
  individual-card candidates. A recording with no such candidates must not manufacture calibration
  or invoke pose fitting only to produce an empty result.
- Identity must perform no crop or model work for zero-card frames. Observation assembly must retain
  the frame/event coverage and pile evidence according to existing contracts. Missing or failed
  upstream evidence must not become an empty success or a gameplay assertion.
- Actual calibration, crop-authority, pose, and source/lineage failures still stop dependent work.

Identify the smallest files and meaningful regression cases for the next phases. Relevant starting
points include the proposed-scene processor/service, pipeline comparison, visual identity service,
observation assembly, and coordinator tests. Confirm how existing local stage APIs accept the
retained event and detector revisions for M4; a new generic coordinator import feature is outside
scope.

Acceptance: reproducible freeze; exact three-recording manifest; no inference; explicit comparison
key and zero-card outcome semantics; budget and stop rules below recorded; M1 has concrete files,
fixtures, and expected results. All later milestones remain unstarted.

### M1 — Correct decoded-image comparison

Implement the M0 comparison policy with tests for the two known pairs, a request-time-only change,
and rejection of changed source, pixels, frame location, dimensions, or transform. Preserve the
original provenance and counts of excluded frames. Do not weaken crop or revision authority checks.

Compare geometry only on paired images, with actual polygon IoU at 0.5. Handle polygon unions and
reviewed ignore regions according to the existing geometry contract. A bounding-box substitute
cannot support a polygon score. If existing polygon tooling cannot support a geometry form, report
that form as unsupported and preserve its coverage count.

Report cards and pile regions separately. Unpaired reviewed frames remain uncovered, not misses;
unpaired predictions remain outside that quality scope. Report coverage denominators beside every
score. Two shared images cannot support a three-recording detector quality claim.

Publish `docs/reports/0050-M1_Frame_Comparison_Correction.md`. Add a dated correction and link to
that report in the 0090 M3 report while preserving its original run results. Do not rewrite the
closed 0090 epic.

Acceptance: deterministic pairing and metrics from retained outputs, meaningful comparison tests,
no inference, and a precise correction to the earlier coverage conclusion.

### M2 — Handle scene inputs with no card candidates

Implement the frozen scene outcome contract at the processor and service boundaries. Successful
zero-card frames and pile-only frames must finish with an explicit valid outcome, without card
poses or invented calibration. Preserve their source identity and pile evidence. Keep normal pose
fitting and calibration gates for frames that have card candidates.

Cover empty and pile-only recordings, mixed recordings, and a genuine calibration/fit failure.
Test that failed or unusable detector outcomes remain failures. Preserve the original 0090 artifacts.
Do not convert arbitrary partial scene runs into successful runs in the coordinator.

Acceptance: focused processor and backend tests pass; zero-card inputs no longer produce
`no_initialized_candidates` solely because there was no candidate to initialize; actual failures
remain actionable and blocking; revised outputs have explicit implementation lineage.

### M3 — Verify downstream and coordinator behavior

Verify and repair only the downstream contracts needed for M2 outputs. Zero-card frames must invoke
no identity model or crop extraction. Retain event/frame coverage and separate pile evidence in
table observations. Do not fabricate component-card identities, card plays, trick winners, or
reviewed empty-table facts from pile or missing detections.

Use local fixtures for a mixed recording and a recording with no individual-card candidates. Prove
that a successful scene result lets the coordinator continue with exact retained input revisions,
and that real calibration, pose, crop-authority, or lineage failures still block dependants. Verify
resume and reuse for any changed coordinator behavior. Prefer existing empty-output contracts;
change a contract only when M0 identifies a concrete gap.

Acceptance: focused identity, observation, and coordinator tests pass; no model calls for zero-card
frames; preserved pile and coverage evidence; no broad relaxation of terminal failure handling.

### M4 — Run the bounded diagnostic and decide the next step

Preflight against the M0 freeze, then use existing local stage APIs with the retained event and
detector revisions. Run corrected scene processing, identity, and observation assembly in order.
Record the scene gate beside the exact event/detector/identity lineage consumed by observations.
This is a diagnostic from retained automatic upstream results. Label its execution scope explicitly.

Use new run IDs for every changed stage and preserve all original 0090 results. Run reconstruction
only if an existing trusted source supplies explicit active players, dealer, first-trick leader,
round/session identity, and rules/search settings. Otherwise record an explicit skip. Missing round
context does not prevent identity or observation measurement. No reviewed reconstruction target is
available in the frozen batch, so any reconstruction output is operational evidence only.

Publish `docs/reports/0050-M4_Diagnostic_Result.md`. Report stage completion, failed frames, event
coverage, cards and piles separately, exact reviewed-crop identity coverage, observation output,
reconstruction execution/skip, wall time, memory, and operator intervention. Missing reviewed
observation or reconstruction targets cannot support quality claims. Reuse the recorded event
scores without rerunning event inference. Preserve uncertainty when no card was detected.

Compare the corrected behavior with the retained 0090 baseline. Identify whether the next limiting
boundary is coverage, detection, crop, classification, observation assembly, or reconstruction.
Select at most one bounded next question, or close with no additional capability selected. A larger
implementation needs a new epic with its own measurements and budget.

Acceptance: all three recordings have terminal, reproducible outcomes; every claim has matching
review coverage; no hidden model/recipe change; run budget holds; next decision is recorded.

## 4. Execution budget and stop rules

M0–M3 use artifact inspection and local fixtures. M4 has a new budget, separate from the completed
0090 pilot:

- Three fixed recordings; reuse all original event and detector results with zero new event or
  detector inference executions.
- At most one new scene, one identity, and one observation execution per recording: nine stage
  executions in total. At most one reconstruction execution for the real round when context exists.
- Six hours total execution wall time, 32 GiB peak process memory, and zero cloud requests.
- Resume only unchanged durable work with the same exact request and inputs. A failed preflight
  starts no stages. A terminal failure stops dependent stages for that recording; other recordings
  may continue. Do not replace a failed run with an undeclared retry or different model.
- No sealed holdout sources, predictions, or scores. The protected exclusions from 0090 M0 apply.
- No new manual annotation or collection is required for the implementation phases. Report missing
  review coverage and reconstruction context as limits rather than inventing targets or setup.

## 5. Verification and Luna handoff

Use targeted regression tests for changed contracts, applicable formatting/lint/type checks, local
Markdown link checks after moves, and `git diff --check`. Keep commits focused and follow AGENTS.md
for worktree integration. Do not push.

The first Luna task is **M0 only**. Start with the main checkout's retained artifacts at
`d2948615df53527c6e8139c83bad7047d85d40a2` and this plan. It must produce the diagnostic freeze,
verify the two findings, identify exact implementation boundaries, update the board, and commit.
It must finish with an M1 handoff and stop before changing runtime code or starting model stages.
