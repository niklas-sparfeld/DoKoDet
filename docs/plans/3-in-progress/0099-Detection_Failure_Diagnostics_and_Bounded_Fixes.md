# Detection failure diagnostics and bounded fixes

## Plan status

- **Status:** In Progress
- **Depends on:** Completed 0096 M1–M3 exact-frame outputs and comparison evidence.
- **Outcome:** Reproducible failure diagnoses and a bounded decision to retain the baseline or
  select a measured software fix. No new human review is required for the diagnostic path.

## Milestone status

- **M0:** Complete — froze the baseline, exact artifact and source digests, source-group subsets, candidate budget, and acceptance gates. See the [M0 report](../../reports/0099-M0_Baseline_and_Experiment_Freeze.md) and [manifest](../../reports/0099-M0_Experiment_Manifest.json).
- **M1:** Not started — classify failures and build regression fixtures.
- **M2:** Not started — test at most two justified software candidates, or record no-fix evidence.
- **M3:** Not started — decide once and publish measured results and remaining review needs.

## Scope and evidence

The [0096 M3 evaluation](../../reports/0096-M3_Exact_Reference_Evaluation.md) reports 90 false
proposals, 64 misses, and two duplicates across 323 scoreable frames outside the final refit-training
sources. Those are development measurements already inspected during 0096, not a fresh holdout.
The [M2 report](../../reports/0096-M2_Proposed_Scene_Results.md) records four calibration failures
and a separate terminal segmentation/backend failure. Published reference coverage does not
support pile, pose, stacking-order, or zero-card quality scores.

Diagnose segmentation postprocessing, geometry handoff, calibration, and the terminal runtime
failure separately. Use existing references and recorded outputs. Do not assume every unmatched
card is an algorithm defect; retain ambiguity about labels, coverage, and extraction provenance.
An evidence-backed no-fix decision is successful completion when improvement cannot be assessed.

No RF-DETR or identity training, new labels, broad parameter sweep, identification, reconstruction,
promotion, or default change belongs here. 0096 M4 and the 0097/0098 implementation paths are not
prerequisites. Do not consume pending human review as if it were completed ground truth.

## M0 — Freeze baseline and gates

Verify the exact corrected 0096 detector revisions, M2 run receipts, M3 evaluator, source-group
permissions, and comparison targets. Exclude protected test/system-holdout sources before media
access. Keep training-only diagnostic replay outside quality evaluation. Freeze code and artifact
digests, per-recording counts, calibration outcomes, and runtime evidence.

Define deterministic source-group-separated development and confirmation subsets from permitted
existing references before implementing candidates. Report that both subsets derive from previously
examined data. Use the full unchanged eligible corpus for final regression reporting; no claim of
new generalization follows. Keep M4 training-overlap results separate throughout.

Freeze the replay manifest and gates: no lower outside-refit-training aggregate card precision or
recall at IoU `>= 0.5`, no new previously passing calibration failure, and fixture correctness for
all changed paths. Record per-recording regressions even when aggregates pass. A selected fix must
improve a named measured failure and satisfy these gates. Freeze runtime comparison conditions and
an acceptable latency/memory budget before executing candidates.

Acceptance: a reproducible baseline report and a finite experiment manifest. Use at most two
independent software candidates, each with one declared failure hypothesis and exact changed policy.
No adaptive expansion or threshold sweep. A missing reproducible baseline blocks candidate work,
not unrelated epics.

## M1 — Diagnose and isolate failures

Classify recorded misses/extras by measurable geometry and context: size, edge, overlap, duplicates,
card/pile relations, and available confidence. These are diagnostic tags, not new reviewed labels.
Build minimal fixtures for reproducible postprocessing or handoff defects. Replay the four
calibration failures with exact detector inputs and keep their failure codes, fit diagnostics, and
evidence populations. Investigate the segmentation/backend failure from retained logs and a local
fixture where practical; do not retry the original 0096 run as part of diagnosis.

Acceptance: rank failure families with counts and concrete evidence. Separate runtime defects,
model limitations, comparison limitations, and calibration safety rejections. Name which failures
have sufficient reference evidence for an automated fix decision. Do not weaken calibration gates
or substitute manual geometry to make a failed recording pass.

## M2 — Test bounded candidates

Select at most two candidates supported by M1, within the M0 hypotheses and gates. Implement one
small candidate at a time, first with a regression fixture. Compare with the exact baseline using
the existing matching, ignore-region, and zero-card policies. Do not change the evaluator to favor
a candidate. Candidates needing new pose/pile/stacking-order truth remain proposals for later review.

Use saved detector outputs for geometry/postprocessing replay. Limit each candidate to one replay
of the frozen comparison corpus and four calibration-failure replays, with one active processor,
12 hours total active experiment time, 32 GiB process RSS, and zero cloud requests. Instrument
runtime and memory. If a specific defect requires fresh segmentation, record a separate bounded
plan amendment before running inference; do not rerun all recordings opportunistically.

Store candidate outputs separately from the 0096 baseline and review queue. Keep generated
selection pointers and all human drafts unchanged. At exhausted budget or insufficient evidence,
retain completed results and record no selected fix. Do not add another candidate or retry terminal
failures without a plan amendment.

Acceptance: paired reports include counts, precision/recall, per-recording regressions, calibration
outcomes, runtime, and all unsupported measures. A candidate that merely suppresses warnings or
publishes an unsafe calibration cannot pass.

## M3 — Decide and hand off

Select at most one candidate after the frozen comparison and confirmation checks. Keep only a
passing, supported fix in normal software; retain rejected candidate evidence without leaving
experimental defaults active. A runtime-only fix must pass its reproduction fixture and relevant
pipeline regressions; report that it makes no detector-quality claim. Keep the baseline when no
candidate passes, including when no candidate could be justified at M1.

Acceptance: publish exact before/after evidence, candidate dispositions, source and output digests,
reproduction commands, and unresolved human-review questions. Preserve all 0096 outputs and its
165-frame queue. Broad reprocessing with a selected fix needs a new explicit batch decision. Close
this epic on its diagnostic/fix decision without claiming completion of 0096 review.

## Verification

Run regression fixtures and focused segmentation, calibration, comparison, and runtime tests for
changed paths, plus applicable formatting/static checks. Verify report digests, Markdown links,
and `git diff --check`. Keep known baseline failures separate from failures introduced by a fix.
