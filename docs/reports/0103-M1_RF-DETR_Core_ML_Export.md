# 0103 M1: RF-DETR Core ML export

## Result

M1 is complete with a bounded negative result. The exact 0092 M4 checkpoint loads and traces in
PyTorch, but Core ML conversion fails in the RF-DETR encoder. No Core ML package was produced, so
preprocessing, detection, mask, and score parity could not be measured. This result does not make a
model-quality claim.

## Frozen artifact and export setup

The checkpoint is
`.runtime/rfdetr-segmentation-0092-m4/bundle/checkpoint_best_total.pth`, SHA-256
`80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`. The containing bundle digest
is `05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c`. The attempt checks the
checkpoint digest before loading it. It uses the same retained weights and two-class map as M0.

The traced network input is a fixed `float32` tensor with shape `[1, 3, 432, 432]`. It represents
RGB pixels resized and normalized with the model's ImageNet mean and standard deviation. The three
raw outputs are boxes `[1, 200, 4]`, class logits `[1, 200, 3]` (including background), and mask
logits `[1, 200, 108, 108]`. The converter target is iOS 17, with float32 compute precision.

The export attempt used macOS 27.2 arm64 and Python 3.13.18. Package versions were:

| Package | Version |
| --- | ---: |
| coremltools | 9.0 |
| rfdetr | 1.9.4 |
| torch | 2.7.0 |
| torchvision | 0.22.0 |
| protobuf | 7.36.2 |
| attrs | 26.1.0 |
| cattrs | 26.2.1 |
| pyaml | 26.7.0 |
| sympy | 1.14.0 |
| tqdm | 4.70.1 |
| packaging | 26.3 |

The checkpoint bundle records its build versions as PyTorch 2.13.0 and torchvision 0.28.0. The
export attempt used the M0 reference runtime versions, as required. This runtime/build difference
may affect conversion. It was not changed silently.

## Reproduction and failure

Install the pinned exporter in the existing backend environment, then run the script from the
repository root:

```sh
uv pip install --python backend/.venv/bin/python coremltools==9.0
PYTHONWARNINGS=ignore \
  PYTHONPATH=table_evidence_analyzer/src:backend/src \
  backend/.venv/bin/python scripts/0103_m1_export_rfdetr.py
```

The script writes `.runtime/0103-m1/export-report.json`. The full failed trace is retained there.
The converter reports the first failing node as
`model/backbone/0/encoder/encoder/embeddings/84` while converting an `int` operation. It raises
`TypeError: only 0-dimensional arrays can be converted to Python scalars`. Tracing itself succeeds
and returns all three output tensors with the fixed shapes above. The expected Core ML package path
is `.runtime/0103-m1/rfdetr-seg-medium.mlpackage`; no package or package digest exists.

The Python mask matching checks already cover equal masks, shifted masks, a class mismatch, and an
unmatched detection in
[`test_epic_0103_model_parity.py`](../../table_evidence_analyzer/tests/test_epic_0103_model_parity.py).
They pass, but could not be applied to exported RF-DETR outputs because conversion did not produce
any.

## Limits and next step

No Core ML preprocessing or postprocessed output comparison ran. There are no parity results,
package-size results, or device measurements for RF-DETR. A future attempt needs an exporter path
that supports the failing encoder operation, or a narrowly scoped graph rewrite. Any rewrite must
load and verify the same checkpoint and pass the frozen M0 comparisons before device work. Do not
replace or retrain the checkpoint to bypass this failure.
