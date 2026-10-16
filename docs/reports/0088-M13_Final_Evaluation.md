# 0088 M13 final evaluation

Date: 2026-10-16

## Status

**Blocked before final-test access.** The required `GEMINI_API_KEY` is not available in the local
shell or the project's `mise` environment. The locked runner stopped before it read the final
recording, resolved crop membership, or made any prediction. The final test remains unopened.

## Runner

The one-time runner is
[`run_0088_m13_final_evaluation.py`](../../operations/scripts/run_0088_m13_final_evaluation.py).
It validates the M12 lock digest, M0/M1 membership receipts, both bundle digests and file hashes,
the source video, and the exact crop denominator before scoring. It runs M3 and M6 together and
sends one Gemini request per exact crop using the prompt and response schema stored in M12. It
records a durable start marker and request ledger so a partially completed run cannot be repeated.

The runner validates the locked classifier implementation and Gemini configuration hashes before
it loads the candidates. Candidate bundle file hashes are checked before crop resolution once the
Gemini credential is available.

## Verification

- Lock validation passed.
- Ruff check and Python syntax compilation passed.
- The focused M13 contract tests passed: 3 passed.
- The locked command was invoked. It exited with status 2 and reported that `GEMINI_API_KEY` is
  missing. It created no M13 output directory and did not materialize crops or score predictions.

## Resume

Configure the locked Gemini credential in the local environment, then run the command in the
[M12 lock](0088-M12_Final_Evaluation_Lock.json). The run will include both M3 and M6 and will
stop without scoring if the frozen recording or 108-crop membership differs.
