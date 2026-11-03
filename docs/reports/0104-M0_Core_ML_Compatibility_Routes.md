# 0104 M0: Core ML compatibility routes

## Evidence

The retained 0103 M1 and M2 tracebacks both end in coremltools 9.0 Torch frontend `_cast`,
called for an `int` node. The converter explicitly accepts scalar or all-one tensor shapes.
For a constant it calls `int(x.val)`. With NumPy 2.5.4, that call raises the recorded TypeError
for a one-element non-scalar array. The check and traceback together identify the failing
constant as non-scalar with one element; they do not record its value or full dimensions.

Run the reduced operator example from the repository root:

```sh
PYTHONWARNINGS=ignore backend/.venv/bin/python scripts/0104_m0_cast_probe.py
```

It invokes the actual converter function on a MIL constant with shape `(1,)` and value `7`.
The original call reproduces `TypeError: only 0-dimensional arrays can be converted to Python
scalars`. Extracting the only element with `np.asarray(x.val).item()` and converting it to an
integer produces the scalar MIL constant `7`. This proves the local failure and candidate
operation, not conversion or parity of either full model.

The bundle loaders verified the frozen manifest digests on this machine: RF-DETR
`05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c` and DINOv3
`a6c1aa2a8911aef7371b8123e39a2e7534f4a88ed9303cb047d2515da604ed79`. The RF-DETR
checkpoint SHA-256 is `80accf8a7c55ec65fdd346c0cd2cbfdd28b936260c242c30f1c39ced6043179e`.
These are bundle manifest digests, not a hash of the bundle directory bytes.

## Selected routes and stop conditions

Both models have one selected route: retain the 0103 TorchScript-to-Core ML path and apply a
local, version-guarded converter fix for the constant `aten::Int` conversion only. For a
compile-time constant with exactly one element, extract that element before the existing integer
cast. Preserve the converter's rejection of multi-element inputs and its dynamic-input path.
Do not alter the model graph, weights, preprocessing, or other converter operations. Check the
converter implementation before patching; fail if it differs from the pinned implementation.
Test scalar and singleton values, invalid multi-element inputs, and dynamic inputs against the
unmodified behavior where it is defined. Do not patch the installed package permanently.

Pin Python 3.13.18, coremltools 9.0, NumPy 2.5.4, torch 2.7.0, torchvision 0.22.0,
RF-DETR 1.9.4, Transformers 5.22.1, and safetensors 0.8.0. Other observed converter dependencies:
protobuf 7.36.2, attrs 26.1.0, cattrs 26.2.1, pyaml 26.7.0, sympy 1.14.0, tqdm 4.70.1,
and packaging 26.3. Record all actual versions in each attempt. Keep iOS 17 and float32.

For M1, preserve fixed `[1,3,432,432]` input and boxes `[1,200,4]`, class logits `[1,200,3]`,
and mask logits `[1,200,108,108]`. For M2, preserve fixed `[1,3,224,224]` input and 25 logits,
the frozen crop transform, feature layout, target map, and calibration. Each attempt must verify
the frozen bundle and inputs and run its complete 0103 parity checks if conversion succeeds.

Stop that model's attempt if version or artifact checks fail, the patch cannot be limited to the
specified operation, focused checks fail, conversion reaches another unsupported operation, or
frozen output comparisons fail. Record the exact failure and do not try a second route under this
epic. A successfully converted package with failed parity is not eligible for device measurement.
No model quality, device performance, or full-model compatibility is established by this probe.
