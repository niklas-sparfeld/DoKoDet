# RF-DETR visible-region training campaign

## Plan status

- **Summary:** Fine-tune one RF-DETR instance-segmentation model on the current human-reviewed
  visible regions and decide whether the result is useful enough for a later provider comparison.
- **Status:** In Progress
- **Depends on:** 0037, 0048, 0049, and 0065 complete
- **Readiness:** Nine completed maintained visible-card references provide 425 reviewed source
  frames, 916 visible-card targets, and 137 visible-card ignore regions. M0 provides a
  deterministic read-only audit and immutable manifest contract. M1 provides the verified
  304-image COCO view. M2 now proves the pinned local training and mask-provider path. M3 now
  provides the retained MPS candidate and locked CPU validation report. M4 is next.
- **Outcome:** Produce one reproducible RF-DETR segmentation checkpoint and a locked validation
  report from source-group-separated human-reviewed data. Record whether fine-tuning learned useful
  visible-region localization. Do not promote or select a runtime default.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — audit the reviewed corpus and freeze the PoC question, split, recipe, and
  stop rules. The live audit reproduces the frozen snapshot with no coverage gaps and writes the
  immutable manifest.
- **M1:** Complete (2026-09-14) — materialize the frozen instance-segmentation trainer view with
  exact-frame verification, reviewed visible-region COCO targets, and exclusion receipts.
- **M2:** Complete (2026-09-14) — add the distinct RF-DETR SegMedium adapter and segmentation
  bundle/provider path. The one-epoch six-image MPS smoke run passes with one validation batch,
  finite loss and metrics, checkpoint reload, and a valid mask-derived polygon and tight box.
- **M3:** Complete (2026-09-15) — the full 219-image train and 85-image validation view produced
  one MPS candidate within budget. The locked CPU baseline and candidate validation report passes
  the frozen PoC gate with retained item-level predictions and aggregate/per-recording metrics.
- **M4:** Not started — publish the PoC decision and preserve the handoff to 0050.

## 1. Why this corpus is enough for a PoC

The current completed maintained references are sufficient to test whether RF-DETR can learn this
project's reviewed visible regions. They are not sufficient to claim production quality.

The local corpus snapshot on 2026-09-14 contains:

| Recording role | Recordings | Reviewed frames | Retained frames after `exclude_frame` | Retained targets |
| --- | ---: | ---: | ---: | ---: |
| Train | 6 | 304 | 219 | 703 |
| Validation | 3 | 121 | 85 | 213 |
| Total | 9 | 425 | 304 | 916 |

The frozen split uses the source permissions that already exist:

- train: `IMG_0096`, `IMG_0097`, `IMG_0637`, `IMG_0643`, `IMG_0655`, and `IMG_0669`;
- validation: `IMG_0090`, `IMG_0091`, and `IMG_0661`; and
- no test partition for this PoC.

Each recording has a distinct recorded session and table setup. M0 must still validate the exact
source, reference, coverage, permission, and group facts before it freezes the dataset. A later
quality or promotion claim needs broader table setups, reviewed negative frames, and a sealed test
partition.

The corpus has no reviewed empty frame. Fifty reviewed outcomes are failed or unusable and cannot
be treated as background. This campaign therefore measures positive-frame instance segmentation,
including false and duplicate predictions within those frames. It does not claim background-only
precision.

## 2. Frozen PoC boundaries

Train one one-class instance-segmentation candidate for `visible_card`. Use the reviewed visible
region as the mask target and its derived box as the matching box. Do not infer the hidden extent of
a card.

Use `exclude_frame` for every frame that contains a visible-card ignore region. The standard
RF-DETR trainer does not consume the repository's pixel loss mask. Adding a custom masked loss is
outside this PoC. The dataset receipt must retain every excluded frame, region, and target count.

M0 must pin one `RFDETRSegMedium` class, its valid input resolution, the installed RF-DETR package,
the pretrained checkpoint digest, augmentation defaults, batch size, accumulation, seed, epoch
limit, early-stop rule, device, and wall-clock budget. Use the current `rfdetr==1.9.4` installation
unless its segmentation checkpoint cannot pass the compatibility smoke test. A package or model
change requires a new frozen recipe before validation results are read.

Run one candidate only. Do not sweep model sizes, resolution, thresholds, augmentation, or seeds.
Use local MPS for the normal loop. A CUDA run is allowed only after a retained MPS failure proves
that the frozen recipe cannot complete locally; it must use the same dataset and recipe.

Primary validation metrics are mask AP at IoU 0.50:0.95, mask AP50, box AP at IoU 0.50:0.95,
instance recall, false detections, duplicate detections, and empty prediction rate. Report each
metric overall and by validation recording. Keep ignored frames outside the metric and report their
count separately.

The campaign passes its PoC gate when:

- the trained checkpoint reloads and produces valid masks through the existing local provider;
- every metric reproduces from retained validation predictions;
- validation mask AP and recall are finite and better than the unchanged pretrained baseline; and
- no validation recording has zero target recall.

Any result is a valid campaign outcome. Stop after the locked validation report. Do not tune on the
validation failures in this epic.

## 3. Scope

In scope:

- a read-only reviewed-corpus audit and immutable multi-recording dataset manifest;
- deterministic extraction of exact source frames from accepted recording videos;
- COCO instance-segmentation annotations from reviewed visible regions and derived boxes;
- explicit frame exclusions for visible-card ignore regions and unusable outcomes;
- one fixture-tested RF-DETR segmentation training adapter;
- one representative local smoke run, one full training run, and one locked validation run; and
- retained checkpoints, predictions, metrics, logs, environment facts, and a concise decision
  report.

Out of scope:

- new annotation work or treating generated proposals as targets;
- custom masked loss, dense full-video sampling, or background-only review;
- model, recipe, seed, or threshold sweeps;
- identity-model, crop-policy, observation, or reconstruction changes;
- provider promotion, backend-default changes, mobile export, or deployment; and
- sealed-test or production-quality claims.

## 4. Delivery milestones

### M0 — Freeze the corpus and campaign contract

- Add a read-only audit over completed maintained visible-card references and accepted recording
  source records.
- Validate selected revision IDs, complete frame coverage, source digests, allowed uses, group
  separation, geometry, ignore regions, and target counts.
- Freeze the nine recording IDs and the train/validation assignments in section 1.
- Record all excluded and ineligible outcomes without converting them to negative evidence.
- Verify the installed segmentation model API and pin the complete recipe and budgets.
- Write one immutable campaign manifest before any candidate training or validation inference.

Acceptance:

- the audit reproduces the source snapshot or stops with item-level drift;
- train and validation have no recording, session, table-setup, source-digest, or reference overlap;
- no protected group or disallowed use enters the campaign;
- the dry run reports 219 train frames with 703 targets and 85 validation frames with 213 targets,
  or stops before freezing when the maintained references changed; and
- repeated runs over unchanged inputs produce the same manifest digest.

### M1 — Materialize the instance-segmentation dataset

- Build a disposable COCO trainer view only from the M0 manifest.
- Extract each exact frame from its accepted recording video and verify the recorded frame digest.
- Convert each reviewed visible-region polygon to a one-class segmentation target and derive its
  box from the same geometry.
- Apply `exclude_frame` to ignore-region frames and retain exact exclusion receipts.
- Preserve empty, failed, and unusable distinctions. Do not create background targets implicitly.

Acceptance:

- cold and warm materialization produce identical image, annotation, split, and exclusion digests;
- every retained annotation links to its recording, event, frame, reference revision, and card ID;
- COCO validation accepts every polygon, area, derived box, and category;
- train and validation directories contain only their frozen source groups; and
- fixture, malformed-input, digest, ignore-region, and reproducibility tests pass.

#### M1 implementation evidence — 2026-09-14

- Added `doko data rfdetr-segmentation-materialize`. It accepts only a frozen M0 manifest and
  writes a disposable RF-DETR `train/` and `valid/` COCO view with extracted JPEG frames.
- The materializer verifies each accepted source video and each recorded exact-frame digest. It
  converts the reviewed visible-region polygons to one `visible_card` instance-segmentation
  category and derives the tight pixel box from the same polygon.
- `exclusions.json` preserves every M0 `exclude_frame` receipt and failed or unusable outcome.
  Empty or ineligible outcomes never become background targets. The view records source, event,
  frame, reference revision, card, split, and digest lineage for every annotation.
- Cold and warm fixture materialization has identical generated-file digests. Malformed geometry,
  changed frame bytes, and the CLI path have regression coverage.

#### M2 implementation evidence — 2026-09-14

- Added `table-analyzer train-rfdetr-segmentation`. It consumes only the verified M1 view, selects
  one deterministic image per train recording, and runs the frozen one-class
  `RFDETRSegMedium` recipe for one epoch with explicit MPS, batch, accumulation, seed, and
  augmentation arguments.
- Segmentation runs use `rfdetr-segmentation-training-run/v1` and
  `rfdetr-segmentation-bundle/v1`. The existing RF-DETR Large detection bundle and provider
  contracts remain unchanged. The segmentation provider accepts the RF-DETR one-class category
  ID and derives the normalized tight box from the predicted mask polygon.
- The real MPS smoke run used six train images and one validation image. It recorded finite loss
  and validation metrics, wrote a checkpoint different from the pretrained input, reloaded it as
  `RFDETRSegMedium`, and returned one valid segmentation polygon with a tight box through the
  local provider.
- Fixture, failure-record, bundle-integrity, provider-mask, full table-analyzer test, and Ruff
  checks pass. The smoke run is retained under the ignored `.runtime` root.

### M3 implementation evidence — 2026-09-15

- `table-analyzer train-rfdetr-segmentation-campaign` validated the immutable M0 manifest and
  checkpoint digest against the verified M1 materialization. It staged all 219 train images and
  85 validation images, then trained the one frozen `RFDETRSegMedium` candidate on MPS for
  6,721.232 seconds, within the 7,200-second budget.
- The retained candidate bundle is
  `.runtime/rfdetr-segmentation-0067-m3-training/bundle` with checkpoint digest
  `1a47791cb381725e5af4673f94e821b02e282bc11f9f16cc66347b59f5bb021c`.
- Added `table-analyzer evaluate-rfdetr-segmentation-campaign`. It validates the M0, M1,
  pretrained-checkpoint, and candidate-bundle digests, then retains exact baseline and candidate
  predictions for every validation frame. It calculates the frozen metrics from those predictions
  overall and by recording. A completed report is reused only when both prediction digests match.
- The MPS device was unavailable for the locked inference process. The report records CPU
  validation as an explicit runtime fact. It does not change the MPS-trained candidate or frozen
  recipe.
- The locked report is
  `.runtime/rfdetr-segmentation-0067-m3-validation-cpu/report.json`. The unchanged pretrained
  baseline had zero mask AP and zero recall. The candidate achieved mask AP 0.860661, mask AP50
  0.989772, box AP 0.875382, and recall 0.995305 over 213 targets. Each validation recording had
  nonzero recall. The frozen gate passes.

### M2 — Prove the segmentation training path

- Add the smallest adapter for the pinned RF-DETR segmentation class and pretrained checkpoint.
- Keep the detection-only 0037 artifact and contracts intact. Give segmentation runs and bundles
  distinct schemas and identities.
- Make device choice explicit. Do not fall back silently from MPS or CUDA to CPU.
- Run one epoch on a deterministic representative train subset and one validation batch.
- Reload the emitted checkpoint and run one real frame through the local provider mask path.

Acceptance:

- fixture tests verify the exact dataset, model, checkpoint, and training arguments without
  downloading weights;
- the real smoke run records finite loss and finite validation metrics;
- the checkpoint differs from the pretrained checkpoint and reloads successfully;
- inference returns a valid visible-region polygon and its tight derived box; and
- failure writes a complete resumable run record.

### M3 — Run the bounded campaign

- Run the frozen pretrained baseline on validation before training.
- Train the one frozen candidate on all M1 train samples within the M0 budget.
- Select the checkpoint only by the metric and rule frozen in M0.
- Run validation once for the selected checkpoint and retain item-level predictions.
- Calculate the frozen mask, box, recall, false, duplicate, and empty-output metrics.

Acceptance:

- the run consumes only the M0 manifest and M1 trainer-view digests;
- rerunning a completed step reuses its verified artifact instead of training or validating again;
- logs record package, checkpoint, code, device, seed, arguments, duration, and peak resource use;
- aggregate and per-recording metrics reproduce from retained predictions; and
- the campaign stops after one candidate and one locked candidate validation.

### M4 — Publish the PoC decision

- Publish a short report with corpus limits, exclusions, baseline and candidate metrics, harmful
  examples, runtime facts, and the pass or stop decision.
- Classify the checkpoint as `poc_candidate` or `unusable_poc_artifact`. Do not promote it.
- Record whether 0050 should later compare the segmenter as a visible-region provider.
- If the result fails, name one evidence-backed next action without implementing it.

Acceptance:

- the conclusion follows the frozen gate without post-hoc threshold or recipe changes;
- sample-linked failures remain inspectable from original recording video;
- the report states that the corpus has no reviewed background-only frames and no sealed test; and
- the board and 0050 handoff identify the completed result without making 0050 a dependency of
  this campaign.

## 5. Relationship to other epics

- 0037 supplies the retained RF-DETR training, bundle, and local-provider proof. This epic replaces
  its pseudo-label detector recipe only for the new segmentation campaign.
- 0048 and 0049 supply accepted recording videos, immutable revisions, maintained references, and
  exact source-frame lineage.
- 0065 supplies the required ignore-region contract. This epic uses its `exclude_frame` policy.
- 0051 and 0052 remain identity-input work. They do not block this component-level PoC.
- 0050 can later compare this segmenter with other visible-region providers after the fixed identity
  baseline is ready. This epic does not perform that composed comparison.
