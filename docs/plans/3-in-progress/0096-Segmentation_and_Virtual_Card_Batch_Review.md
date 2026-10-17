# Segmentation and virtual-card batch review

## Plan status

- **Summary:** Run the newest local segmentation bundle and proposed card scene processor on all
  eligible recordings, then evaluate and review the retained results.
- **Status:** In Progress
- **Depends on:** Completed 0083 batch operations, 0092 M4 segmentation bundle, 0073 proposed card
  scene processing, and 0050 scene and comparison corrections.
- **Outcome:** A reproducible batch with recording-level outcomes, separate segmentation and scene
  measurements, and bounded human review through the existing maintained references.

## Milestone status

- **M0:** Complete — froze 34 eligible recordings, exact event frames, comparison coverage, source overlap, run IDs, and processing limits. No inference ran.
- **M1:** In progress — preserve the first 34 run outcomes and rerun the 33 successful recordings
  with the frozen `end_us` input anchor under the recorded correction budget.
- **M2:** Not started — generate proposed card scenes from the exact M1 outputs.
- **M3:** Not started — evaluate the retained segmentation and scene outputs.
- **M4:** Not started — review results and publish the measured follow-up work.

## 1. Scope and current evidence

The user selected detection as the next focus. This epic includes visible-card and card-pile
segmentation, automatic table-plane calibration, card poses, card stacking order, and proposed card
scenes. Virtual cards are reviewed through the existing proposed card scene and maintained-reference
workflow.

Identification is outside this epic. Do not run an identity classifier, create identity proposals,
review identity labels, or measure identity quality. Event detection, observation assembly,
reconstruction, training, model promotion, and default changes are also outside scope. Reuse existing
selected events so that event-frame changes do not obscure detector and scene measurements.

The [0092 M4 report](../../reports/0092-M4_Final_Refit.md) publishes the newest final segmentation
bundle. It used 20 reviewed recordings and supports `visible_card` and `card_pile`. The M3 holdout
scores describe the pre-refit candidate. They do not establish final-refit quality. Report overlap
with M4 training sources explicitly; development review is not a new holdout test.

The [0050 M4 result](../../reports/0050-M4_Diagnostic_Result.md) records successful scene processing
for three recordings after the zero-card correction. The
[0050 M1 comparison](../../reports/0050-M1_Frame_Comparison_Correction.md) found only two shared
decoded images in that pilot. This epic must report exact-frame comparison coverage before scores.

## 2. Eligibility and input policy

The read-only inventory on 2026-10-17 found 52 accepted recordings with local video. It identified
39 preliminary run candidates after excluding four protected test recordings, five legacy-device
recordings, the non-flat recording, and three recordings without selected events. Of the 39,
36 have validation or evaluation permission and three are training-only. These counts are planning
evidence, not an execution manifest. M0 must verify the current catalog and source-group lineage.

- Include accepted local videos with selected, usable event revisions and permitted source use.
  Prefer the selected completed event reference; otherwise use the selected generated revision.
  Record that choice. Freeze all event frames and extraction policies before inference.
- Keep `cardeventnet-IMG_0092` excluded because its surface is not flat.
- Keep `cardeventnet-IMG_2777` through `cardeventnet-IMG_2781` outside this batch under the existing
  legacy-device diagnostic policy.
- Exclude protected test sources `cardeventnet-IMG_0654`, `cardeventnet-IMG_0659`,
  `cardeventnet-IMG_0656`, and `cardeventnet-IMG_0660`, their related protected source groups, and
  system-holdout sources. Do not read their media, references, or predictions for this batch.
- Keep training-only sources separate. Generation and human correction may prepare training data
  within the existing source permissions. Do not use them for evaluation or quality scores. If the
  permission policy does not permit the intended operation, record an exclusion instead.
- Treat `cardeventnet-IMG_0096` as an explicit diagnostic case. Its earlier calibration deferral
  does not by itself prevent segmentation. Attempt scene processing only when its normal processor
  prerequisites pass. Retain calibration failure or an unpublished fit candidate as such. Do not
  weaken calibration gates to produce a scene.
- Missing reviewed geometry does not prevent generation. It prevents quality scoring outside
  declared review coverage. Missing events prevent this batch from running that recording; event
  detection is separate future work.

Every catalog entry needs an inclusion or exclusion reason. Do not require a completed geometry
reference as a generation prerequisite. Do not silently reduce the batch to the 20 training sources
or the three pilot recordings.

## 3. Fixed processing and evidence rules

Use `local-rfdetr-segmentation` with the 0092 M4 bundle:

- bundle digest: `05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`;
- checkpoint SHA-256: `80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`;
- bundle manifest SHA-256: `826ccba533531c62a2059be5889b9c48aa44800df5d216997575a238c37f5816`;
- expected local bundle path: `.runtime/rfdetr-segmentation-0092-m4/bundle` in the primary worktree.

Verify the local assets before processing. Record the exact application commit, relevant source
digests, tool versions from `mise.toml`, provider configuration, thresholds, frame hashes, and
calibration policy. Freeze the current scene processor and its normal calibration gates. No model,
threshold, geometry algorithm, or calibration-gate tuning belongs in this batch.

Use the backend APIs and durable pipeline stores already used by the recording workspace. Reuse
the [0083 batch operations](../5-closed/0083-Manual_RF_DETR_Proposed_Card_Scene_Runs.md) where they
meet the frozen-input contract. Explicitly pass the M1 generated detector revision to M2; do not
substitute reviewed geometry or a different selected detector result.

Retain old processor runs, completed references, and live review drafts. Record generated selection
pointers before execution. Report changes to those pointers and leave completed batch results
accessible through the existing workspace. Do not reset or seed a live human draft automatically.
Store bulk output only in the existing pipeline stores. Commit concise reports and manifests with
paths, IDs, and digests rather than duplicate processor output.

Run locally with zero cloud requests. M0 froze at most 34 segmentation runs and 34 scene runs.
Use one active processor run at a time, a 24-hour active-processing budget across M1/M2, and a
32 GiB process-memory limit. Sample RSS and record the sampling interval. Human review time is
separate. M0 may reduce the frozen list or budget for verified exclusions; expansion needs a
recorded plan change before execution.

Reuse unchanged completed runs from this epic on resume. Record a partial or failed run and continue
independent recordings. Do not retry a terminal failure or silently replace a timed-out active run.
If a budget is reached, stop new work, retain evidence, and report incomplete coverage. Correctness
fixes that change the frozen algorithm need a separate measured scope and rerun decision.

## 4. Delivery milestones

### M0 — Freeze eligibility and execution inputs

Inventory the catalog, permissions, source groups, selected events, comparison references, existing
review drafts, and M4 training overlap. Verify source and model digests. Record frame extraction
policies and exact comparison coverage. Produce a machine-readable manifest and a short report.

Check that the batch commands honor frozen event and detector revisions and the pinned bundle.
If needed, make only small batch-control changes for exact inputs, durable status, or evidence
capture. Add focused fixture tests for those changes. Do not start inference during M0.

Acceptance:

- all 52 inventory entries, or the current verified catalog count, have a disposition;
- execution, evaluation, and training-preparation eligibility are separate;
- each included recording has a verified video, event revision, frame policy, and stable run IDs;
- protected-source checks occur before media or prediction access;
- missing assets and tooling gaps have explicit remedies; failed preflight starts no processors;
- the manifest freezes the exact list, model, implementation, limits, and selection-pointer policy.

### M1 — Run segmentation across the frozen list

Run the pinned M4 bundle on every frozen event frame. Retain per-recording and per-frame terminal
outcomes, input/output revisions, model lineage, counts, latency, memory samples, and failures.
Keep individual cards and piles separate. Verify the stored model digest for every output.

Acceptance: every eligible recording has one retained terminal segmentation outcome or an explicit
unprocessed reason. A failed recording does not hide other results. Zero-card frames remain in
coverage. No scene or later processor runs during this milestone.

#### Recorded correction plan (2026-10-17)

The M0 input freeze specifies the selected event's `end_us`. The first 34 planned run IDs were
started with the visible-card service's default `start_us` anchor. One run terminated after a
backend MPS crash with zero completed frames. The other 33 runs completed 1,707 frame outcomes;
1,407 matched the frozen frame identities and 300 did not. Keep all 34 original runs and outputs
for audit. Do not retry the terminal failure or use the 33 mismatched outputs in M2.

The service now records an explicit `event_time_anchor` in each request and supports `end_us` for
this batch. The correction manifest freezes one new deterministic run ID for each of the 33
completed recordings, their exact event revision, and their M0 frame identities. This changes the
M1 cap from 34 to 67 total run IDs: the 34 original IDs plus 33 corrective IDs. The M2 cap remains
34. The shared 24-hour processing limit and all model, threshold, memory, concurrency, source, and
selection-pointer constraints remain unchanged. Do not start corrective inference unless the
service change, regression check, and [correction manifest](../../reports/0096-M1_Input_Anchor_Correction.json)
are committed.

### M2 — Generate proposed card scenes

Use the exact usable M1 detector revisions with automatic calibration and scene processing. Keep
published calibrations, unpublished fit candidates, rejected calibration, unsupported frames, and
pose failures distinct. A pile must not produce an individual-card pose. Preserve explicit
`no_cards_detected` outcomes for empty individual-card frames, including frames with pile evidence.

Acceptance: every M1 recording has a retained scene outcome or a named dependency failure. The
report links event, detector, calibration, and scene lineage and accounts for every input frame.
Partial output remains inspectable. No human reference is overwritten.

### M3 — Evaluate retained outputs

Evaluate the frozen outputs against the pre-batch reviewed references where permissions and exact
frame coverage permit. Use decoded-image equality with the comparison provenance checks delivered
by 0050. Timestamp proximity alone is insufficient. Preserve each original frame receipt when two
extraction paths produce identical pixels.

Report per-recording coverage denominators before aggregates. Keep unpaired references uncovered,
not detector misses; exclude unpaired predictions from paired-frame scores. Separate in-sample
results from sources outside the final refit and keep training-only sources out of evaluation.

Measure visible-card and pile precision and recall at polygon IoU `>= 0.5`, false and duplicate
proposals, and zero-card outcomes within reviewed coverage. Use existing segmentation metrics when
their required targets are available. Do not infer a reviewed empty frame from missing labels.
Report calibration publication and failure rates separately from pose quality. For matched reviewed
scenes, report pose/outline agreement and stacking-order agreement only where the reference
supports those questions. Record crop-support failures as geometry diagnostics without running
identification. Freeze any additional measurement definitions in M0 before looking at predictions.

Acceptance: a reproducible report distinguishes segmentation, calibration, pose, stacking-order,
and coverage problems. Each score has a supported denominator. Unsupported quality questions are
explicit. Retained outputs are not rerun to improve scores.

### M4 — Review results and publish follow-up work

Prepare a deterministic review list from M3 outcomes. Cover every included recording with a result
or an explicit failure to inspect. Select at most five frames per recording, at most 195 frames,
for the initial human review. Prioritize calibration/pose failures, detector misses and extras,
duplicates, pile fragments, overlap, small cards, frame edges, and a successful control when present.
Freeze the selected frames, reasons, and result lineage before human review starts.

Use the existing recording workspace and maintained references. The operator accepts or corrects
card geometry, calibration, and stacking order. Record inspected coverage, corrections, unresolved
cases, and review time. Do not auto-accept results or invent completed reviews. Preserve pre-batch
comparison revisions; later human corrections do not retroactively change M3 scores.

Acceptance: publish the completed review receipts and coverage, or report the milestone as awaiting
human review. The final handoff ranks measured failure families and separates software fixes,
additional geometry review, and future training needs. Wider review needs an explicit new budget.
Identification remains separate future work. Close only when the bounded review and handoff are
complete; report any processing-budget gaps explicitly.

## 5. Verification

For documentation and manifests, check local Markdown links, status/folder consistency, exact
counts, digests, and `git diff --check`. For batch-control code, run focused preflight, frozen-input,
resume, failure-continuation, and pointer-preservation tests plus applicable static checks. Use
fixtures to prove that zero-card frames remain explicit and that piles cannot create card poses.
Verify outputs and request/state/revision digests after each batch milestone. Automated processor
success does not replace human scene review or establish generalization.
