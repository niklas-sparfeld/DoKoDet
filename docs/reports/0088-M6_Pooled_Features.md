# 0088 M6 pooled-feature comparison

## Decision

Treat the one-crop gain as a useful exploratory signal for annotation assistance. The pooled-feature
candidate corrected one CLS error and introduced no new errors. The observed 0.48 percentage-point
gain does not establish a stable improvement on two source groups. Carry both M3's 224-pixel CLS
control and M6's pooled-feature candidate into M10 for the two additional-seed comparison.

Keep M0's 1-point threshold and uncertainty rules for formal qualification. Do not use the 1-point
floor alone to discard an exploratory candidate when one additional correct crop may help annotation.

## Results

The eight-epoch fit completed 4,792 steps in 977.095 seconds. The frozen model-selection view has
209 crops: 208 face-up and one `FACE_DOWN` crop.

| Measure | 224 CLS | 224 CLS plus mean patch |
| --- | ---: | ---: |
| Face-up top-1 | 206/208 (99.04%) | 207/208 (99.52%) |
| Face-up top-3 | 208/208 (100%) | 208/208 (100%) |
| All-crop top-1 | 207/209 (99.04%) | 208/209 (99.52%) |
| Macro F1, all supported classes | — | 99.43% |
| Mean crop inference latency | 41.54 ms | 43.26 ms |

Paired outcomes: 207 crops were correct for both candidates, one was wrong for CLS and correct for
pooled features, one was wrong for both, and none were correct only for CLS. Both candidates missed
the same `SPADES_ACE` crop from `IMG_0657`, predicted as `CLUBS_ACE`. The other `SPADES_ACE` error
from CLS was corrected by pooled features. The selection recordings scored 116/117 versus 115/117
for `IMG_0657`, and 92/92 for both candidates on `IMG_0662`.

The single `FACE_DOWN` crop was correct. It does not measure face-down precision, recall,
calibration, or generalization. Four NINE classes have no samples in this pool. The final test
remains sealed.

## Frozen candidate

- Input: 224 pixels, source-frame crop, masked visible region, Lanczos, grey letterbox.
- Encoder: frozen DINOv3 ViT-S/16.
- Feature layout: CLS plus mean patch features, with one linear identity head.
- Training data and selection split: the same frozen M1 views as M3.
- Seed: 17; eight epochs; batch size 1; AdamW learning rate 0.001; weight decay 0; MPS fp32.
- Augmentation and sampling: `source_safe_v2` and `class_source_weighted_with_replacement`.
- Checkpoint selection: frozen model-selection view only.

The fresh MPS batch-1 fp32 preflight at 224 pixels returned finite features. It used 83.3 MB of
currently allocated MPS memory after the forward pass. This is a single-forward observation, not a
training peak or a system-wide memory measurement. Bundle inference covered 209/209 crops; median
latency was 40.00 ms and p95 was 49.26 ms.

## Run artifacts

- Run ID: `dinov3-m1-1792139547`.
- Derived campaign manifest: `.runtime/dinov3-identity-0088/m6-224-cls-mean-patch/manifest.json`.
- Manifest digest: `d6d9a672ede8cbd05a70e26a2b059c67265250c4467bc050b1d6e5ff732a1d7d`.
- Training output: `.runtime/dinov3-identity-0088/m6-224-cls-mean-patch/candidate-run/`.
- Identity config SHA-256: `7775d6544cf001070d523e55b761524957333e6b7d559f322d8aa8da200a5dc9`.
- Best checkpoint SHA-256: `ff560c5a4e2fff70f7e6ab0ff0cef6e7fa8cab8bbdfbcd25af4c569ee4bdfb1a`.
- Bundle digest: `3bf7459c475101f53a05338380219bc2e39fa130a995868a28ffc47db26cd149`.
- Evaluation report SHA-256: `1f2bf358c0f8197544a9f11183713ecba3e8f27f80f8a5fac3954ceeca927395`.
- Bundle reload reproduced all 209 checkpoint rows with zero mismatches. Maximum probability
  delta was `4.23e-7` at a tolerance of `1e-5`.

The evaluation-only manifest adds exact crop hashes and source metadata for the same frozen M1
validation crops. The two-group evidence does not qualify generalization. `FACE_DOWN` remains
limited to iterative annotation assistance.
