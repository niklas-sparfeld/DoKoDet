# 0087 M0 reviewed RF-DETR campaign readiness

Date: 2026-10-13

## Decision

M0 is blocked. Do not materialize masks or train a candidate. The current source records do not
support a trustworthy 0087 manifest. Resume M0 after 0086 publishes its detection-only handoff and
the selected completed references pass a current-schema audit.

This audit did not read source video bytes, change review data, materialize a trainer view, or run
inference. The diagnostic used the existing 0068 read-only manifest builder with its frozen split
and expected inventory. Its result is evidence about reuse limits, not an 0087 selection.

## Evidence

- The 2026-10-11 0086 inventory reports 25 completed visible-card references, but no detection-only
  campaign handoff with current geometry, per-frame visible masks, ignore or frame-exclusion
  decisions, and source-group assignments. It also records that the `IMG_0095` pilot still needs
  refreshed proposals and human review.
- The live completed-corrected reference discovery found 31 references. The 0068 builder only
  selects its fixed 24 recording IDs and expects its historical totals. Against current data it
  reports 34 expected recording assignments, 24 audited recordings, 1,190 reviewed frames, 851
  retained frames, 226 excluded frames, 113 ineligible outcomes, 356 ignore regions, and 2,283
  individual targets. These counts are diagnostic and are not frozen 0087 counts.
- The 0068 diagnostic reports 571 coverage gaps, including current review outcome and schema
  mismatches, missing selected references, and fixed-corpus count drift. Therefore, its manifest
  validator cannot certify the current reference store for 0087.
- The 0067 decision used `IMG_0090`, `IMG_0091`, and `IMG_0661` for validation. Treat these as
  diagnostic evaluation data in 0087, not a fresh sealed test.
- Epic 0068 completed its sealed-test evaluation on `IMG_0646`, `IMG_0648`, and `IMG_0649`. Do not
  reuse those groups as a fresh sealed test. The 0086 inventory also marks its three RF-DETR sealed
  recordings as excluded from development selection.
- Follow-up environment verification in this main checkout confirms `rfdetr==1.9.4` is installed in
  both local Python environments. The pretrained checkpoint exists at
  `.runtime/rfdetr/1.9.4/rf-detr-seg-medium.pt` with SHA-256
  `3ad325094735f431aee9962a8d204d68eb5bfc393d53e7e836e70998fef5ea58`. Package and checkpoint
  availability are not current blockers; M0 must still record this exact initialization in its
  frozen recipe.
- 0091 completed two-class software support, but its handoff explicitly reports that no trained
  pile-capable model is selected. Software fixtures do not establish training readiness or model
  quality.

## Required next inputs

1. 0086 must publish an immutable detection-only handoff with eligible completed references,
   current geometry and masks, per-frame ignore or exclusion receipts, exact source-group
   assignments, and pile coverage decisions. Identity labels are not required.
2. The 0087 audit must read the current `visible-card-data/v2` references and validate source and
   frame lineage, target policy, and source-group isolation. It must independently select current
   development groups and record all prior evaluation use. Do not reuse the 0067 or 0068 split as
   the 0087 split.
3. Freeze an unopened eligible test only if independent eligible groups remain after the prior-use
   audit. Otherwise freeze the affected data as diagnostic evaluation and record why no sealed
   test is available. Never move a protected group into training.
4. Pin a retrievable RF-DETR 1.9.4 SegMedium initialization and its digest before training. Keep
   the M3 candidate count to one real-only control and one corrected-real-only candidate at most;
   use a paired control only when the common validation partition and source groups are unchanged.
   M4 may add one fixed real-plus-synthetic candidate.

## Frozen limits

- Maximum training candidates: two real-only candidates in M3 and one mixed candidate in M4.
- No ratio, seed, model-size, threshold, or recipe sweep.
- No protected test inference until the candidate and gate are locked.
- M1 mask materialization, M2 synthetic preparation, M3 training, M4 mixed training, and M5 bundle
  decision remain not started.

The machine-readable 0086 inventory is
[`0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json`](0086-M0_Reviewed_Virtual_Card_Corpus_Inventory.json).
The fixed historical 0068 campaign is documented in
[`0086`](../plans/3-in-progress/0086-Reviewed_Virtual_Card_Corpus.md) and the
[`0068 closure record`](../plans/5-closed/0068-Reviewed_RF_DETR_Local_Visible_Card_Detector.md).
