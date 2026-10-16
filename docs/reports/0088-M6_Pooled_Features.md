# 0088 M6 pooled-feature comparison

## Status

The single candidate is training. No selection results are available yet.

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
training peak or a system-wide memory measurement.

## Run artifacts

- Run ID: `dinov3-m1-1792139547`.
- Derived campaign manifest: `.runtime/dinov3-identity-0088/m6-224-cls-mean-patch/manifest.json`.
- Manifest digest: `d6d9a672ede8cbd05a70e26a2b059c67265250c4467bc050b1d6e5ff732a1d7d`.
- Training output: `.runtime/dinov3-identity-0088/m6-224-cls-mean-patch/candidate-run/`.
- Identity config SHA-256: `7775d6544cf001070d523e55b761524957333e6b7d559f322d8aa8da200a5dc9`.

The baseline comparison is the M3 224-pixel CLS candidate. The run uses the same 599 training crops
and 209 model-selection crops. Report paired results, per-class errors, group variation, reload
parity, and runtime cost before selecting a feature layout. The two-group evidence does not qualify
generalization. `FACE_DOWN` remains limited to iterative annotation assistance.
