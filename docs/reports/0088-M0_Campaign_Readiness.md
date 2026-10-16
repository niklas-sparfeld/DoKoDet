# 0088 M0 campaign readiness and frozen contract

Date: 2026-10-16

## Decision

M0 is complete. The user accepts the low `FACE_DOWN` sample size for iterative classifier work,
including annotation assistance. The handoff has 1,391 positive crops across 12 recordings and 20
source groups, but it does not support the frozen split floors. `FACE_DOWN` has only three positive
crops in three groups. The back design is unspecified for all three contributing recordings. Keep
these facts visible in every result; do not claim face-down precision, recall, calibration, or
generalization from this sample. Support floors constrain quality claims, not exploratory training.

The 0086 M5 source bytes are now verified against the intake receipts. The verification covers all
20 handoff recordings and is recorded in the
[M1 source verification report](0088-M1_Source_Verification.md). Keep the final test unopened until
M13. Exploratory results do not qualify a model or authorize promotion.

The exact source-group split and all gates are in the companion
[machine-readable manifest](0088-M0_Campaign_Readiness.json). It records the user's updated
support policy. It allows exploratory crop preparation and model fitting after exact source-byte
verification. The final group is named but remains unopened, and final-test predictions remain
unauthorized until M13.

## Evidence and exclusions

The manifest pins the 0086 M0 partition inventory and M5 campaign handoff, 0093 M5 input handoff,
0094 M9 recipe handoff, 0043 PoC evaluation, and the 0087 and 0092 pretest locks. The 0086
inventory confirms no source-group overlap with the five system-holdout recordings. The 0086
handoff reports 21 supported
positive classes and 362 pile targets. It also reports that M4 source bytes were not verified and
that 8 eligible recordings have no positive crops.

Exclude `cardeventnet-IMG_0654` from the 0087 sealed test, and exclude
`cardeventnet-IMG_0656` and `cardeventnet-IMG_0660` from the 0092 sealed test. The 0068 sealed
groups (`IMG_0646`, `IMG_0648`, and `IMG_0649`) and system-holdout group
`source-group-3fb2ef94de1f7f76` do not overlap the 0086 M5 candidate pool. Keep the permanent
0086 exclusion of `IMG_0092` and the deferred `IMG_0096` outside this campaign. The frozen split
keeps every source group separate, including groups with no current positive crops, and preserves
the prior 0043 DINO training assignments. The 0043 diagnostic evaluation uses `IMG_0090`; it does
not overlap this handoff. Do not reuse its 301 predictions as campaign results. Its report excludes
`FACE_DOWN` and four NINE classes.

The frozen planning split assigns 5 positive-crop groups to training, 2 to model selection, 1 to
confidence calibration, and 1 to the unopened final test. Eight no-crop groups are assigned to
training so later labels cannot leak into an evaluation partition. Three prior sealed-test groups
are excluded. This leaves 9 positive-crop groups. The split is group-safe, but its evaluation
support is below the frozen minimum.

| Gate | Frozen minimum | Current evidence | Result |
| --- | --- | --- | --- |
| Each face-up class, training | 20 crops in 5 groups | 9 groups remain before partitioning | Qualification limited |
| Each class, model selection | 10 crops in 3 groups | 2 groups assigned | Qualification limited |
| Each class, confidence calibration | 10 crops in 3 groups | 1 group assigned | Qualification limited |
| Each class, final test | 10 crops in 3 groups | 1 group assigned | Qualification limited |
| `FACE_DOWN`, every partition | Same per-class minimums | 3 crops in 3 groups total; one each in training, selection, and final; none in calibration | Claims limited; exploration allowed |
| Face-down back design | Known design for every contributor | Unknown for IMG_0651, IMG_0657, and IMG_0659 | Generalization limited |
| Source video bytes | Exact bytes match the intake and handoff receipts | All 20 source videos match their 0086 M5 and intake SHA-256 receipts and byte lengths | Passed; M1 unblocked |
| Crop lineage | Each materialized crop maps to its reviewed source frame and annotation | M1 will record this during materialization | Pending M1 |

The support gaps cannot be repaired by splitting adjacent frames or by synthetic examples. New
reviewed, independent positive back crops and known back-design metadata would improve measurement,
but they are no longer entry requirements for exploratory classifier work. The eight no-crop
recordings can add face-up evidence after completed reviews and exact source verification.

## Frozen quality and recipe contract

- Target classes: 20 face-up identities plus `FACE_DOWN`. `UNKNOWN` remains abstention. `NINE` is
  outside this recording pool and is not a support gap.
- Main quality targets: at least 98% top-1 on human-readable face-up cards, and at most a 1
  percentage point deficit to Gemini on identical reviewed cases. Also report top-3, macro F1,
  class confusion, per-group results, confident errors, usable coverage, and frames with all
  supported identities correct. Calibration cannot change raw top-1.
- Face-down gates: pixel-based precision and recall each at least 95%; false `FACE_DOWN` rate on
  face-up cards at most 1%. The readability authority is the positive human-reviewed identity
  outcome; unreadable and unusable evidence stays in coverage reporting and is not positive-class
  accuracy evidence.
- Confidence and runtime gates: among predictions with calibrated top-1 probability at least 0.90,
  error rate must be at most 1% and coverage at least 90%. Usable prediction coverage must be at
  least 90%. Local p95 crop latency must be at most 100 ms, model load at most 10 seconds, and peak
  memory at most 75% of physical RAM.
- Minimum support: each class needs 20 training crops in 5 groups and 10 crops in each evaluation
  view across 3 groups. Report uncertainty and group variation. Do not claim a gate when a floor
  fails.
- Report a Wilson 95% interval for each class and a source-group bootstrap 95% interval with 10,000
  replicates and seed 17088. Report group variation as insufficient when fewer than three groups
  contribute. Prefer a challenger only when its top-1 improves by at least 1 percentage point, the
  paired group-bootstrap interval excludes zero, and no class falls by more than 2 percentage
  points. Otherwise keep a qualifying control or report an inconclusive result.
- Input: reviewed source-frame crops with visible-region masks, `oracle_visible_region`, RGB 128
  letterbox fill, and Lanczos. Do not require full-card rectification. Keep automatic predicted
  crops as a separate evaluation condition. A reviewed side label must not bypass face-down pixel
  classification.
- Candidate order: one fresh 224 CLS frozen real-only control, then one matched 384 challenger.
  Consider one 448 challenger only if at least 80% of eligible training crops have native long
  sides at least 448 px and an MPS batch-1 preflight fits within 75% of physical memory. Then allow
  one CLS-plus-mean-patch fit at the selected size. Consider one last-two-block fit only if the
  best frozen recipe misses the main target and every support floor passes. Do not run a
  Cartesian search.
- Fits: seed 17 for primary recipes; seeds 101 and 202 for at most two finalists. Use 8 epochs,
  batch size 1, fp32, AdamW, head learning rate 0.001, weight decay 0, cosine schedule, and
  `class_source_weighted_with_replacement`. Adapted encoder learning rate is 0.0001. Use
  `source_safe_v2` augmentation. Maximum six primary fits and four stability fits; each fit has a
  2-hour wall limit. Keep resumable checkpoints. An OOM or timeout skips that candidate; do not
  change the frozen recipe or resolution.
- Synthetic branch: no synthetic data can satisfy a missing reviewed-class support floor. M8/M9
  stay skipped unless a measured training-only robustness gap and eligible training-only
  contributors are documented before the branch starts.
- Gemini reference: use model `gemini-3.8-flash`, the current configured model at the pinned
  source revision, with the existing identity-classification prompt and the same crop bytes as the
  local classifier. Make at most one request per development crop, no automatic retry, maximum
  250 requests and USD 10 total campaign spend. Count failures in coverage. Stop before another
  request if the cap would be exceeded. Do not send final-test images to Gemini before M13.
- Local device: MPS, fp32, batch size 1, local-only pretrained asset. The pinned DINOv3 weights
  digest is recorded in the manifest. The 0094 CPU forward measurement is feasibility evidence,
  not training-time or quality evidence. Run a fresh MPS resource preflight before any future fit.

## Frozen training command

This command template is frozen for M3 after M1 supplies the dataset, split, artifact index,
manifest, and recipe config. It was not run during M0.

```sh
RUN=.runtime/dinov3-identity-0088
WEIGHTS=data/operations/dinov3-identity-bundles/0043-m1-dinov3-identity-75000a5eec53a52f088f9e6e

mise exec -- uv run --project table_evidence_analyzer \
  --group training table-analyzer train-dinov3-identity \
  --dataset "$RUN/data/dataset.json" --split "$RUN/data/split.json" \
  --artifacts "$RUN/data/artifact-index.json" \
  --identity-config "$RUN/recipes/224-cls.json" \
  --weights-root "$WEIGHTS" --campaign-manifest "$RUN/manifest.json" \
  --output "$RUN/results/224-cls" --seed 17 --epochs 8 --batch-size 1 \
  --learning-rate 0.001 --weight-decay 0 --encoder-training frozen \
  --device mps --precision fp32
```

For resume, repeat the command with `--resume "$RUN/results/224-cls/checkpoint-last.pt"`.
The 384 challenger changes only the recipe config and output path. The 0094 M9 handoff pins the
reusable calibration, export, bundle evaluation, and local classification commands. The Gemini
reference uses the pinned `GeminiCardClassifier` implementation and request rules in the JSON
manifest; this repository has no campaign-specific Gemini comparison CLI.

The current split fails every evaluation support floor. Exact source verification passed, so M1 may
materialize the evaluation views. Exploratory training may proceed with the present class support, including the three
`FACE_DOWN` crops; report the support and limits with each result. Do not claim the frozen quality
gates or open the final test early. New reviewed back crops and known designs can improve later
measurement but are not prerequisites for iteration. This user decision updates the M0 policy.

## Reproduction

From the repository root, reproduce the manifest from its pinned inputs:

```sh
python operations/scripts/build_0088_m0_campaign_readiness.py
```

The builder checks split coverage, prior DINO partitions, and system-holdout group overlap. M0 used
read-only reports and artifact metadata only. No crops were materialized, no Gemini requests were
sent, and no model was fitted. Confirm input digests before any later campaign command.
