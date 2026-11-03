# 0103 M2: DINOv3 Core ML export

## Result

M2 is complete with a bounded negative result. The frozen encoder and classification head load in
the M0 Python runtime and reproduce both frozen 25-class logit vectors exactly. Core ML conversion
fails in the DINOv3 attention graph. No Core ML package was produced, so exported score, rank, and
`FACE_DOWN` parity could not be measured. This is an execution result, not a model-quality claim.

## Frozen model and export setup

The attempt checks the 0088 M6 candidate bundle digest
`a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`, encoder-state digest
`6fc86f473ceec4c8612c1c7341d878e3ecf96b1d182dbae7d47b02cf83a5fa24`, and classification-head
digest `baeae9d97b971cdfa60fa3f8c92e62c47cb5d7eb7074478322abda6ffca19979`. The bundle pins
DINOv3 ViT-S/16, 12 layers, 384 hidden units, four register tokens, and a 25-class linear head.
The head input uses the CLS token concatenated with the mean of spatial patch tokens. The target
map has 24 card identities and `FACE_DOWN`. The smoke bundle remains marked
`unusable_smoke_artifact`.

The fixed input is `[1,3,224,224]`, float32 RGB. The existing transform resizes with Lanczos,
preserves aspect ratio, pads to the center with RGB 128, and applies ImageNet normalization. The
attempt checks each transformed tensor digest against the M0 references before tracing. It exports
25 logits. Existing calibration uses temperature `0.6487642659364355`; it remains a postprocessing
step with the frozen class map.

The attempt ran on macOS 27.2 arm64 and Python 3.13.18. It used coremltools 9.0, PyTorch 2.7.0,
torchvision 0.22.0, Transformers 5.22.1, and safetensors 0.8.0. The bundle records PyTorch 2.13.0,
torchvision 0.28.0, and Transformers 5.16.1. This build/runtime difference may affect conversion;
the frozen M0 runtime was not changed.

## Reproduction and failure

From the repository root, run:

```sh
PYTHONWARNINGS=ignore PYTHONPATH=table_evidence_analyzer/src \
  backend/.venv/bin/python scripts/0103_m2_export_dinov3.py
```

The script writes `.runtime/0103-m2/export-report.json`, including the full trace. It loads the
exact encoder and head, checks both M0 crop tensor digests, confirms output shape `[25]`, and
compares Python logits with M0. Both crops match all 25 logits with zero absolute difference and
no rank changes.

Core ML conversion fails at `encoder/model/0/attention/160` while converting an integer operation.
It raises `TypeError: only 0-dimensional arrays can be converted to Python scalars`. The expected
package path is `.runtime/0103-m2/dinov3-identity.mlpackage`; it does not exist and has no digest.
The full error trace is in the ignored runtime report. M1 records a related converter error for
RF-DETR, but in a different model graph node.

## Limits and next step

No exported model was available for comparison. There are no Core ML score differences, changed
ranks, `FACE_DOWN` decisions, package-size results, or device measurements. The focused comparison
helper reports per-class score tolerance and rank changes. Its tests pass for equal, differing,
rank-changing, and invalid vectors. An exporter or narrow graph rewrite that supports this fixed
attention operation is needed before M3 device work can treat DINOv3 as exportable. Any rewrite must
preserve the exact frozen weights, input transform, feature layout, head, target map, and calibration.
