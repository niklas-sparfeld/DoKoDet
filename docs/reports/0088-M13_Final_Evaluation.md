# 0088 M13 final evaluation

Date: 2026-10-16

## Status

**In progress.** The ignored `backend/.env` file supplied the key to the runner process without
printing it. The source and bundle checks passed. Crop materialization resolved exactly 108 eligible
samples from the locked recording and source group. The one-time paired scoring run has started for
M3, M6, and Gemini. Current request progress is in the runtime ledger at
`.runtime/dinov3-identity-0088/m13-final-evaluation/provider-request-ledger.json`.

## Runner

The one-time runner is
[`run_0088_m13_final_evaluation.py`](../../operations/scripts/run_0088_m13_final_evaluation.py).
It validates the M12 lock digest, M0/M1 membership receipts, both bundle digests and file hashes,
the source video, and the exact crop denominator before scoring. It runs M3 and M6 together and
sends one Gemini request per exact crop using the prompt and response schema stored in M12. It
records a durable start marker and request ledger so a partially completed run cannot be repeated.

The runner validates the locked classifier implementation and Gemini configuration hashes and both
candidate bundle file hashes before crop resolution.

## Verification

- Lock validation passed.
- Ruff check and Python syntax compilation passed.
- The focused M13 contract tests passed: 3 passed.
- The initial invocation without an environment key stopped before final-test access.
- The authorized invocation loaded the ignored key, resolved the locked 108-crop membership, and
  began the single scoring run. The run has not yet written a final result.

## Resume

Let the current run finish. Do not rerun it. The runner records each Gemini receipt and writes the
digest-backed final result when all crops are scored. It includes both M3 and M6 and stops without
scoring if the frozen recording or 108-crop membership differs.
