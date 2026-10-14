# Epic 0094 M7: All-class and paired evaluation

## Result

The local DINOv3 evaluator now writes report schema v2. The report includes support, measured
state, precision, recall, F1, and confusion entries for all 25 visual classes. A class with no
validation examples stays unmeasured. The summary reports raw top-1, top-3, and prediction
coverage. Per-class results remain separate from model selection or promotion.

The report also groups results by source-lineage group, recording, frame, card side, and crop
policy. It retains each prediction with its top-1 probability, so FACE_DOWN errors remain visible.

The optional `--provider-receipts` input accepts retained Gemini outcomes only. Each outcome must
identify its sample, match the frozen crop digest, and include a request ID, model ID, prompt digest,
input digest, and generation-configuration digest. The evaluator retains paired decisions and
counts classified, failed, unusable, side-bypassed, and missing outcomes. It excludes side-bypassed
rows from Gemini classifier-credit metrics. It does not make live provider requests.

## Verification

Command, run from `table_evidence_analyzer`:

```text
mise exec -- uv run --project . --group training pytest -q tests/test_dinov3_bundle.py tests/test_cli.py
```

Result: 35 passed. The fixture checks checkpoint reproduction, all 25 class entries, source and
frame summaries, paired outcome retention, rejection of a request whose input digest does not match
the evaluated crop, and the CLI receipt option.

Ruff check, Ruff format check, and `git diff --check` pass for the changed files. The tests use
generated encoder and provider fixtures. They do not evaluate a real model, a retained production
Gemini receipt, or model quality. The current frozen campaign may not contain FACE_DOWN examples;
in that case FACE_DOWN remains explicitly unmeasured.
