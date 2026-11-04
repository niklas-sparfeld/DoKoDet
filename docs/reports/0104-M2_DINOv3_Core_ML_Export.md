# 0104 M2: DINOv3 Core ML export

## Result

The frozen DINOv3 encoder and 25-class head exported to Core ML. Both frozen crops passed the
0103 comparison on this Mac with Core ML `CPU_ONLY`: every logit, raw probability, and calibrated
probability met `atol=1e-4`, `rtol=1e-4`; no class rank, top class, `FACE_DOWN` decision, or
review-threshold decision changed. The comparison record includes all 25 Core ML outputs and
per-class mismatch indices for both crops.

| Frozen crop | Maximum logit difference | Maximum calibrated probability difference | Top class |
| --- | ---: | ---: | --- |
| Face-up at 08 s | 0.000004530 | 0.0000000484 | `SPADES_QUEEN` |
| Face-down at 40 s | 0.000005722 | 0.0000001692 | `FACE_DOWN` |

The model uses the same encoder, head, feature layout, target map, and temperature
`0.6487642659364355`. The review threshold is `0.8235859761473482`. The threshold comparison
checks whether the top calibrated probability is at least that value; the runtime's `FACE_DOWN`
classification is based on the top class. This test does not measure model quality.

## Artifact and reproduction

The source bundle loader verified digest
`a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`; the exporter also checks
the frozen encoder and head digests. Both source crop byte digests and transformed input tensor
digests match M0. The input is float32 `[1,3,224,224]`, with the frozen RGB Lanczos letterbox
and normalization. The package outputs 25 logits. The version-guarded, process-local singleton
integer conversion fix is the M0 route. It does not change weights or the installed converter.

The package is outside Git at `.runtime/0104-m2/dinov3-identity.mlpackage`. It contains
86,721,162 bytes. The sorted relative-path-and-file-bytes directory SHA-256 is
`5e3af365eb1d0e7dd3543011a17189f68741dae926c3ec25e09c0fef358b1c25`.
The runtime export report records the complete installed dependency versions. Python was 3.13.18,
coremltools 9.0, NumPy 2.5.4, torch 2.7.0, torchvision 0.22.0, Transformers 5.22.1, and
safetensors 0.8.0.

From the repository root in the pinned 0103 backend environment:

```sh
PYTHONWARNINGS=ignore PYTHONPATH=scripts backend/.venv/bin/python -m pytest -q scripts/test_coreml_singleton_int.py
PYTHONWARNINGS=ignore PYTHONPATH=table_evidence_analyzer/src backend/.venv/bin/python scripts/0104_m2_export_dinov3.py
PYTHONWARNINGS=ignore PYTHONPATH=table_evidence_analyzer/src backend/.venv/bin/python scripts/0104_m2_compare_dinov3.py
```

The [comparison record](0104-M2_DINOv3_Core_ML_Parity.json) contains both crop results. The
ignored `.runtime/0104-m2/export-report.json` records the conversion and package digest. This is a
Mac comparison only. No iPhone measurement, sealed evaluation, retraining, promotion, or runtime
default change was performed. The underlying bundle remains an `unusable_smoke_artifact` for
model-quality purposes.
