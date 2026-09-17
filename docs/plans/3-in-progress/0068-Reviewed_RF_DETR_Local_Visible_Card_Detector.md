# Reviewed RF-DETR local visible-card detector

## Plan status

- **Summary:** Train and evaluate one new RF-DETR segmentation candidate from the current
  human-corrected visible-card references. Make it a locally selectable visible-card detector only
  if it passes a frozen held-out quality gate.
- **Status:** In Progress
- **Depends on:** 0037, 0048, 0049, 0065, and 0067 complete
- **Readiness:** The selected completed references now contain 24 recordings, 1,180 reviewed
  outcomes, and 2,947 reviewed visible-card targets. After excluding 259 frames with
  visible-card ignore regions and 136 unusable frames, 785 positive frames with 2,208 targets are
  eligible for ordinary RF-DETR supervision. The existing RF-DETR SegMedium materializer,
  trainer, evaluator, bundle, and provider path are proven by 0067.
- **Outcome:** A retained RF-DETR segmentation bundle and a reproducible held-out report. If the
  gate passes, register the bundle as a local selectable provider. Do not change the default
  provider automatically.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Complete — discover and audit the selected completed corrected references, freeze the
  source-group-safe train, validation, and sealed-test partitions, and pin the RF-DETR recipe and
  held-out gate. The audit is blocked until the live 24-recording source snapshot and checkpoint
  are available locally.
- **M1:** Complete — materialize the frozen reviewed instance-segmentation dataset into
  deterministic train, validation, and sealed-test COCO views. The live run awaits the frozen
  24-recording M0 snapshot, which is not present in this checkout.
- **M2:** Not started — run one local RF-DETR SegMedium candidate from the frozen recipe.
- **M3:** Not started — evaluate the pretrained baseline and candidate on the frozen validation
  and sealed-test partitions.
- **M4:** Not started — make the bounded local-provider decision and register a passing bundle.

## 1. Corpus inspection

The active local review store contains a completed corrected visible-card reference for each of
these 24 recordings:

`IMG_0090`, `IMG_0091`, `IMG_0092`, `IMG_0095`, `IMG_0096`, `IMG_0097`, `IMG_0635`, `IMG_0636`,
`IMG_0637`, `IMG_0638`, `IMG_0639`, `IMG_0640`, `IMG_0641`, `IMG_0642`, `IMG_0643`, `IMG_0644`,
`IMG_0645`, `IMG_0646`, `IMG_0648`, `IMG_0649`, `IMG_0655`, `IMG_0661`, `IMG_0669`, and `IMG_0674`.

All 24 selected references have `origin: corrected`. Their reviewed outcomes are:

| Review result | Frames | Visible-card targets | Training treatment |
| --- | ---: | ---: | --- |
| Detected, no ignore region | 785 | 2,208 | One-class segmentation target |
| Detected, with ignore region | 259 | 739 | Exclude the complete frame |
| Unusable or failed | 136 | 0 | Exclude; never make background |
| Total | 1,180 | 2,947 | Keep in the frozen audit receipt |

The retained targets cover `face_up` (1,625), `unknown` (560), and `face_down` (23) sides. They
range from one to nine reviewed cards per frame. The targets are visible regions, not inferred full
cards. The trainer must derive each box from the reviewed polygon and must not include occluders,
hands, or hidden pixels.

The corpus has no reviewed empty-background frames. A result can measure matching, false and
duplicate detections on positive frames. It cannot claim background-only precision or full-video
false-positive performance. The 259 frames with ignore regions are also not background; the
standard RF-DETR loss cannot mask those pixels, so this campaign excludes those complete frames.

Epic 0067 already proved that `RFDETRSegMedium` with `rfdetr==1.9.4` can train locally on MPS,
reload through the local mask provider, and outperform its unchanged pretrained checkpoint on its
then-small corpus. Its result is an unpromoted PoC candidate, not the local detector this epic may
register.

## 2. Campaign rules

Train one `visible_card` instance-segmentation class. Start from the pinned RF-DETR SegMedium
pretrained checkpoint. Keep package version, checkpoint digest, resolution, augmentation policy,
seed, batch size, accumulation, epoch limit, early-stop rule, confidence threshold, device, and
wall-clock budget in the M0 manifest. Use MPS for the normal local run. A CPU or CUDA run needs a
recorded MPS failure and uses the same frozen recipe.

M0 must construct partitions by source group, not by individual frame. A group includes the
recording ID, session ID, source asset, video ID, source digest, and table setup. A group cannot
appear in more than one partition. It must reserve at least three distinct source groups for a
sealed test partition. The 0067 validation recordings are development evidence because the prior
candidate used them; they cannot be presented as an independent test result. M0 must select the
new sealed groups before any new candidate inference.

Use the held-out validation partition only for early stopping and selecting the frozen checkpoint.
Run the sealed test exactly once after selection. Do not alter the recipe, threshold, split,
checkpoint selection, or provider settings from validation or test failures.

The primary gate is instance-level mask AP 0.50:0.95 and recall. Report mask AP50, box AP
0.50:0.95, false detections, duplicate detections, and empty prediction rate as supporting
measures. Report all measures per recording, side, and visible-card-count bucket. Keep excluded
frames out of the score, but report them with their reasons and target counts.

A passing candidate must:

- reload from its retained bundle and return valid mask polygons and tight derived boxes through
  the local provider;
- reproduce all metrics from retained per-frame predictions;
- beat the unchanged pretrained baseline in held-out mask AP and recall;
- have nonzero recall in every sealed-test recording; and
- meet the M0 minimum held-out thresholds, which must be fixed before training and must be no
  weaker than the 0067 PoC gate.

Any other result is useful evidence. Stop after M4. Do not start a sweep, add pseudo-labels, or
turn failures into negative labels in this epic.

## 3. Delivery milestones

### M0 — Freeze the reviewed corpus and split

- Extend the 0067 audit so it reads the current selected completed corrected references instead
  of nine hard-coded recordings.
- Validate revision state, review coverage, source video and frame digests, source permission,
  geometry, card side, ignore regions, and outcomes.
- Construct deterministic train, validation, and sealed-test partitions using the source-group
  rules in section 2. Stop with item-level gaps if the corpus cannot provide three disjoint groups
  in every required partition.
- Pin the RF-DETR recipe, pretrained checkpoint digest, resource budget, metrics, matching rules,
  and passing thresholds in one immutable manifest.

Acceptance:

- repeated audits over unchanged sources produce the same manifest digest;
- no partition shares a recording, session, source asset, video ID, source digest, table setup, or
  reference revision with another partition;
- all 24 selected corrected references are accounted for as retained, excluded, or unavailable;
- no ignore-region or unusable frame enters ordinary supervision; and
- the manifest reports exact frames, targets, side counts, and exclusion receipts per partition.

### M1 — Materialize and verify the dataset

- Reuse the 0067 COCO materializer, generalized to consume only the M0 manifest.
- Extract the recorded exact source frames, verify their digests, and write disposable train,
  validation, and sealed-test COCO views.
- Write reviewed visible-region polygons and their tight derived boxes as the one `visible_card`
  category. Retain source, event, card, reference, and partition lineage for every image and
  annotation.
- Preserve a machine-readable exclusion receipt for ignore regions and unusable outcomes.

Acceptance:

- cold and warm materialization have identical image, COCO, split, and receipt digests;
- every retained COCO target has valid polygon area and a tight derived box;
- no source group crosses a trainer partition; and
- malformed geometry, changed source frames, stale references, and ignored frames have regression
  tests.

#### M1 implementation evidence — 2026-09-17

- Generalized the 0067 COCO materializer to validate the 0068 reviewed-detector M0 manifest only.
- Added a disposable `sealed_test/` COCO view beside RF-DETR `train/` and `valid/` views. The split
  receipt contains the three frozen partitions and per-partition sample counts.
- Added source-group lineage to every image and annotation. The materializer checks group keys,
  group fields, partition membership, and cross-partition overlap before it extracts frames.
- The exclusion receipt keeps every ignored frame and unusable outcome. The materializer never
  turns these outcomes into background targets.
- Fixture tests cover cold and warm digest equality, polygon and derived-box validation, changed
  frame bytes, stale reference lineage, stale source-group keys, ignore and unusable receipts,
  and the public CLI. Focused verification passes with 19 tests and Ruff checks.
- A live materialization cannot run yet because the frozen 0068 M0 manifest and its 24 source
  recording bundles are not available in this checkout.

### M2 — Run one bounded local candidate

- Reuse the proven RF-DETR SegMedium training adapter and local mask-provider bundle format.
- First run a small deterministic MPS smoke subset with a validation batch, finite loss, finite
  metrics, checkpoint reload, and one provider result.
- Run one full candidate on all M1 training images within the frozen local budget. Select the
  checkpoint only by the frozen validation rule.
- Retain commands, package and checkpoint facts, logs, resource facts, checkpoint, bundle, and
  resumable failure record.

Acceptance:

- the smoke run and full run consume only matching M0 and M1 digests;
- the emitted checkpoint differs from the pretrained checkpoint and reloads as RF-DETR SegMedium;
- MPS is explicit and never silently falls back to CPU; and
- a completed run is verified and reused rather than retrained.

### M3 — Lock validation and sealed-test evidence

- Run the unchanged pretrained checkpoint and selected candidate on the frozen validation view.
- Retain all predictions and calculate the frozen metrics overall and by the required slices.
- If the validation gate passes, run each checkpoint once on the sealed-test view and retain an
  independent report. Otherwise record the validation failure and do not inspect the test scores.
- Link false, duplicate, empty, and missed examples to their original recording and reviewed
  visible regions.

Acceptance:

- reports reproduce solely from their manifest, bundle, and prediction digests;
- every sealed-test recording has an item-level result and no test input entered training or
  checkpoint selection; and
- reports state the no-background-frame limitation and the excluded-frame count.

### M4 — Decide local availability

- Publish a concise decision report with corpus facts, baseline and candidate results, failure
  examples, resource cost, and the limits of the evidence.
- If the gate passes, register the bundle with the existing local visible-card provider as an
  explicit selectable candidate. Keep the existing provider default unchanged and record rollback
  as removal of that candidate selection.
- If the gate fails, retain the bundle as an experiment and close with the measured failure. Do not
  register it for normal local use.

Acceptance:

- a passing bundle can be selected on a local CPU or MPS device and returns its retained bundle
  identity with each result;
- the default provider and existing 0067 PoC artifact remain unchanged; and
- the decision neither claims background precision nor production readiness without newly reviewed
  negative frames and broader held-out coverage.
