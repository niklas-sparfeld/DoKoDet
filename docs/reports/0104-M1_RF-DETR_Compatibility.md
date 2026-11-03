# 0104 M1: RF-DETR Core ML compatibility

## Result

M1 is complete with a reproducible conversion blocker. The selected singleton integer fix passes
the previous encoder failure. Conversion then fails at `model/transformer/1591` while converting
`meshgrid`, with `ValueError: meshgrid received non-1d tensor.` Two runs reached the same node
and error. The pinned M0 stop condition ends this route at the next unsupported operation.

No Core ML package was produced. No Core ML preprocessing, detection, mask, score, normalized
box, confidence decision, or unmatched-detection comparison could run on the six frozen frames.
Therefore there is no export parity or model-quality claim.

## Attempt and reproduction

The attempt verified RF-DETR bundle manifest digest
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c` and checkpoint SHA-256
`80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`. The traced Python
model returned boxes `[1,200,4]`, class logits `[1,200,3]`, and mask logits `[1,200,108,108]`
for the fixed `[1,3,432,432]` float32 input. The converter targets iOS 17 with float32 compute.

The process-local fix checks the SHA-256 of the pinned coremltools `_cast` source. It extracts
one element only for constant, non-scalar `aten::Int` inputs. It delegates scalar, dynamic,
other-type, and invalid-shape cases to the original converter and restores it after conversion.
It changes no model weights or installed packages. The focused checks cover scalar, singleton,
multi-element rejection, and dynamic singleton behavior.

Run from the repository root in the pinned 0103 backend environment:

```sh
PYTHONWARNINGS=ignore PYTHONPATH=scripts backend/.venv/bin/python -m pytest -q scripts/test_coreml_singleton_int.py
PYTHONWARNINGS=ignore PYTHONPATH=table_evidence_analyzer/src:backend/src backend/.venv/bin/python scripts/0104_m1_export_rfdetr.py
```

The runner verifies the M0 version pins, bundle digest, and checkpoint digest. It records the full
traceback, platform, all installed package versions, and output shapes in the ignored
`.runtime/0104-m1/export-report.json`. Python was 3.13.18, coremltools 9.0, NumPy 2.5.4,
torch 2.7.0, torchvision 0.22.0, and RF-DETR 1.9.4. The report records the remaining dependency
versions. The expected package path `.runtime/0104-m1/rfdetr-seg-medium.mlpackage` does not exist.

The error establishes the converter's rejection at this node. It does not establish why its input
has that shape or whether a safe further rewrite exists. Do not use a second route within this epic.
