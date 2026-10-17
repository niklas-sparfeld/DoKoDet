# Identity proposal batch

## Plan status

- **Status:** Ready
- **Depends on:** Completed 0096 M1/M2 outputs, 0088 M6 bundle, and 0085/0093 crop provenance.
- **Outcome:** Retained local identity proposals from the successful 0096 scenes, a coverage report,
  and a bounded identity review queue. Human geometry review is not an inference prerequisite.
- **Optional integration:** 0097 can display the resulting queue. Its completion does not block
  the batch or a file-based queue handoff.

## Milestone status

- **M0:** Not started — freeze permitted scene inputs, crops, model, and run budget.
- **M1:** Not started — run the fixed local identity batch.
- **M2:** Not started — report coverage, diagnostics, and supported identity comparisons.
- **M3:** Not started — publish a frozen identity review queue and handoff.

## Scope and evidence

[0096 M2](../../reports/0096-M2_Proposed_Scene_Results.md) retained 29 successful scene runs over
1,513 frames. Four calibration failures and one segmentation failure have no usable scene output.
Use the exact corrected detector and successful scene revisions, including their calibration and
frame receipts. Do not rerun upstream stages or substitute reviewed geometry for automatic crops.
Zero-card frames remain in coverage; piles never produce individual-card identity crops.

This is a diagnostic proposal batch with unreviewed geometry. Its outputs are not human labels.
It can complete while the user is unavailable. Geometry and identity review, new training, model
comparison campaigns, promotion, observation assembly, and reconstruction are outside scope.
Keep 0096 outputs and review selections fixed.

Use only [0088 M6 seed 17](../../reports/0088-M15_Qualification_Decision.md): bundle digest
`a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`, checkpoint SHA-256
`ff560c5a4e2fff70f7e6ab0ff0cef6e7fa8cab8bbdfbcd25af4c569ee4bdfb1a`, and temperature
`0.6487642659`. Preserve the locked 224-pixel RGB P6 PPM, aspect-preserving Lanczos resize,
centered `(128,128,128)` letterbox, and 25-output map. Use the existing `predicted_visible_region`
crop policy. Record its exact implementation and recipe; do not introduce rectification variants.
`FACE_DOWN` is a visual classification, not a card identity. Preserve raw output and probabilities.
M6 is unqualified; confidence is not permission for automatic acceptance. Do not run M3 or Gemini.

## M0 — Freeze inputs and eligibility

Verify all 29 scene receipts and their corrected 0096 M1 lineage in the primary pipeline store.
Check local model bytes and crop reproducibility before inference. Record source permission,
source-group exclusions for both detector and identity campaigns, model-training overlap, exact
frame/card/geometry/crop receipts, pre-existing drafts, and selection pointers. The 0096 list alone
is not proof of identity eligibility. Exclude protected test/system-holdout sources and related
groups before image or prediction access. Training-only sources may produce training-preparation
proposals where permitted; they must not enter quality evaluation.

Acceptance: a machine-readable manifest accounts for all 29 scene recordings plus the five upstream
failures. Freeze usable and unusable crop counts and reasons, source digests, software versions,
stable run IDs, and current comparison targets. No classifier runs during preflight. Missing
reviewed targets limit scoring but do not block permitted generation.

## M1 — Run local proposals

Run at most one identity processor per included recording, at most 29 runs and 1,513 source frames.
The crop cap is the exact eligible individual-card crop count frozen in M0; no extra crops or
candidates may be added during execution. Use one active run, zero cloud requests, eight hours of
active processing, and 32 GiB process RSS. Sample RSS every ten seconds and record timing.

Use the existing backend processor and immutable pipeline stores. Preserve canonical native crop
receipts separately from browser previews and model preprocessing. Reuse unchanged completed
stages on resume; do not retry terminal failures. Record failure and continue independent sources.
At budget exhaustion, stop new processing and publish incomplete coverage. Never replace an
active timed-out run silently. Restore only batch-created identity selection changes to their
recorded pre-batch values, after checking for intervening changes; preserve all runs and drafts.

Acceptance: account for every frozen crop as classified, face-down, unusable, failed, or unprocessed
under the existing result contract. Verify input/output digests and the model identity. Upstream
detector, scene, calibration, and maintained-reference bytes remain unchanged.

## M2 — Report diagnostics and comparisons

Report per-recording crop and prediction coverage, face-down outcomes, confidence distribution,
rank margins, failures, latency, and memory. Confidence and predicted class counts are diagnostic,
not correctness measures. Distinguish geometry/crop failures from classifier failures.

Score only permitted exact reviewed identity crop pairs with complete human-decision, card, frame,
geometry, and crop lineage. Do not transfer a reviewed label to a different automatic crop based
only on IoU or timestamp. If no valid pairs exist, publish zero comparison coverage and no accuracy
claim. Keep training-overlap, development comparisons, and all unpaired proposals separate. No
sealed-test rerun, normalization, threshold tuning, or auto-accept policy belongs here.

Acceptance: reproducible report and machine-readable lineage with explicit denominators. Lack of
quality targets is a valid diagnostic outcome, not a reason to collect labels autonomously.

## M3 — Freeze review work and hand off

Select at most five identity-bearing frames per eligible recording, at most 145 frames. Freeze
reasons and result lineage before human review. Prioritize low margins, low confidence, face-down
predictions, and crop diagnostics, with one deterministic control when available. Frame selection
uses proposals as routing evidence only. Name recordings with no reviewable identities.

Publish queue items that open the exact identity result in the existing maintained-reference editor.
Use the 0097 queue boundary if available; otherwise publish a documented file-based adapter input
and existing editor links. Do not implement another queue UI or require 0097 completion. Preserve
live drafts and record unavailable/conflicting editor targets. No review decisions are created.

Acceptance: publish the bounded queue, coverage report, and reproduction commands. The epic can
close after this autonomous handoff; identity review remains explicitly pending and separate from
0096's geometry review.

## Verification

Run focused eligibility, crop-lineage, identity processor, resume, and pointer-preservation tests
for changed code plus applicable static checks. Verify reports against stored artifact digests,
check Markdown links, and run `git diff --check`. No new training or human review is required.
