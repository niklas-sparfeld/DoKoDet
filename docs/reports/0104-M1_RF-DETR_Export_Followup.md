# 0104 M1: RF-DETR export follow-up

The user requested continued export work after the first blocker. The RF-DETR model now converts
and runs as a Core ML package. It has **not passed the full frozen parity comparison** and is not
yet eligible for device measurement under this epic.

## Export

The process-local conversion fixes extract singleton integer constants and correct the extra
singleton dimensions produced by constant `linspace`. For inference tracing, the RF-DETR custom
depthwise autograd operation is replaced by the same module's standard convolution. The original
forward operation calls `conv2d` with the same weights and parameters; the focused CPU test
produces exactly equal block outputs. The code checks the original converter and RF-DETR method
source digests and restores both changes after the attempt. It does not modify the frozen weights
or the installed packages. Tests also cover singleton `linspace` and integer conversion.

The frozen 0092 M4 bundle and checkpoint pass the existing digest checks. The input is
`[1,3,432,432]`; outputs are boxes `[1,200,4]`, class logits `[1,200,3]`, and mask logits
`[1,200,108,108]`. The iOS 17 float32 package is outside Git at
`.runtime/0104-m1/rfdetr-seg-medium.mlpackage`. Its directory digest, using the exporter’s
sorted relative-path-and-file-bytes algorithm, is
`425ec4edeaed510743778229c2d03b6ef3fa727e5c182f50b2e8336b63916947`.
The runtime report records all installed versions and the pinned bundle identity. Package
construction does not establish deployment readiness.

## Frozen comparison

All six frame byte digests and dimensions match the M0 manifest. The comparison uses the same RGB
conversion, tensor resize with `antialias=False`, and ImageNet normalization as the RF-DETR
runtime. The frozen M0 record does not include preprocessed-tensor digests; therefore an independent
comparison of those tensors to stored M0 tensors is not possible. The comparison records current
tensor digests and reuses one tensor for the current Python and Core ML models.

On the Mac with `CPU_AND_GPU` allowed, all 14 reference detections above 0.5 matched by class and
polygon mask; their mask IoUs were 1.0, scores and normalized boxes met the frozen tolerances,
and no threshold decisions changed. This setting permits GPU use; it does not establish which
compute unit executed each operation. With `CPU_ONLY`, one above-threshold score at 70 seconds
was `0.9152789712` versus Python `0.9149074554`, outside the score tolerance. The current Python
output matches the frozen score. No threshold decision changed.

The threshold-free comparison processes all 200 candidates per frame. It has substantial
unmatched counts, including empty or degenerate polygons that cannot enter the polygon matcher.
Among matched candidates, `CPU_AND_GPU` has two out-of-tolerance box comparisons at 8 seconds,
and 17 score and 62 box comparisons at 70 seconds. These discrepancies are below the operating
threshold, but the frozen comparison did not waive them. The full per-match differences and
unmatched indices are in the [comparison record](0104-M1_RF-DETR_Core_ML_Parity.json). A separate
`CPU_AND_NE` allowed run also had low-confidence mismatches and is retained in the local runtime
report. Compute-unit selection alone therefore does not establish full parity.

| Frame | Matched | Unmatched reference | Unmatched candidate |
| --- | ---: | ---: | ---: |
| 02 s | 6 | 194 | 194 |
| 08 s | 158 | 42 | 42 |
| 12 s | 169 | 31 | 31 |
| 20 s | 184 | 16 | 16 |
| 40 s | 105 | 95 | 95 |
| 70 s | 93 | 107 | 107 |

The matcher is the frozen greedy, same-class polygon mask IoU rule at `>= 0.5`, with a 1000×1000
raster. Unmatched indices do not by themselves prove a model difference. Empty or degenerate
polygons cannot be matched. Threshold-free candidates are not additional accepted detections.
Raw output arrays also differ between the current Python model and Core ML; those maxima are in
the comparison record and can include different query ordering.

Reproduce in the pinned 0103 backend environment:

```sh
PYTHONWARNINGS=ignore PYTHONPATH=scripts backend/.venv/bin/python -m pytest -q scripts/test_coreml_singleton_int.py scripts/test_coreml_rfdetr_fixes.py
PYTHONWARNINGS=ignore PYTHONPATH=table_evidence_analyzer/src:backend/src backend/.venv/bin/python scripts/0104_m1_export_rfdetr.py
RFDETR_COREML_COMPUTE=CPU_AND_GPU PYTHONWARNINGS=ignore PYTHONPATH=table_evidence_analyzer/src:backend/src backend/.venv/bin/python scripts/0104_m1_compare_rfdetr.py
```

No sealed test, retraining, model-selection change, runtime-default change, or iPhone measurement
was performed. Parity does not measure model quality.
