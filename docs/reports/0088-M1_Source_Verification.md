# 0088 M1 source verification

Date: 2026-10-16

## Result

Exact source verification passed for all 20 recordings in the 0086 M5 DINO campaign handoff. For
each recording, the actual video bytes match the SHA-256 recorded in the handoff, intake bundle
manifest, source record, and source asset manifest. The actual byte length also matches both intake
records. This clears the source-fidelity prerequisite for M1 crop materialization.

The detailed per-recording SHA-256 values, byte lengths, and source paths are in the
[machine-readable receipt](0088-M1_Source_Verification.json). The check reads the original source
videos. It does not materialize crops, send Gemini requests, fit a model, or access final-test
predictions.

## Reproduction

From the repository root, run:

```sh
mise exec -- uv run --project operations python operations/scripts/verify_0088_m1_sources.py
```

The command checks each source video against its 0086 handoff digest, intake manifest, source
record, and recorded byte lengths. It fails if any source file is absent or changed.
