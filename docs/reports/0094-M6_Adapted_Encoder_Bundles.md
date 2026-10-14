# Epic 0094 M6: Adapted encoder bundles

## Result

The DINOv3 inference bundle is now `dinov3-identity-bundle/v4`. Export writes the exact encoder
and head states from the best completed checkpoint. The manifest records whether encoder weights
are pretrained or adapted, the trainable parameter names, training and inference recipes, and the
pretrained model identity and weight digest. Every bundle file is covered by a SHA-256 digest.

The runtime verifies the bundle before it constructs a model. It loads the encoder and head state
from local files and uses the bundled pretrained files with `local_files_only` enabled. Missing or
changed state files fail validation. A resumable checkpoint is not an inference bundle: export
requires a completed run.

The original pretrained files remain in the bundle as provenance. The exported encoder state is
separate, so an adapted checkpoint cannot be mistaken for the original weights. The M0 bundle
contract version is superseded by v4; prior source assets are not rewritten.

## Verification

Command, run from `table_evidence_analyzer`:

```text
mise exec -- uv run --project . --group training pytest -q tests/test_dinov3_training.py tests/test_dinov3_bundle.py tests/test_dinov3_bundle_contract.py tests/test_local_identity.py
```

Result: 60 passed. The fixtures cover both feature layouts at 224, 384, and 448 pixels, compare
reloaded encoder tensors with checkpoint tensors, verify the 25-class runtime output, and reject
missing or changed encoder state before constructing the runtime model. Interrupted runs cannot be
exported.

Ruff lint, formatting, and `git diff --check` pass for the changed implementation and test files.
The encoder is a generated fixture, not the licensed pretrained asset. These checks verify the
local bundle contract; they do not measure model quality, pretrained-model loading, memory, or
throughput.
