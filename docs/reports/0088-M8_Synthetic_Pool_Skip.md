# 0088 M8 synthetic-pool skip

## Decision

M8 is not required under the frozen M0 gate. Do not prepare a synthetic pool.

M0 allows synthetic data only when a measured training-only robustness gap and eligible
training-only contributors are declared before M8. The frozen campaign has no such declaration.
M6's one additional correct selection crop is a useful exploratory signal for annotation
assistance, but it does not establish a training-only robustness gap. The accepted low `FACE_DOWN`
sample count limits quality claims; it does not by itself authorize synthetic training data.

No synthetic assets were materialized or inspected. Evaluation remains real-data only. This skip
does not prevent M10 from comparing the M3 CLS control and M6 pooled-feature candidate for
annotation assistance.

## Evidence

- [M0 readiness contract](0088-M0_Campaign_Readiness.md): synthetic data requires a declared
  training-only robustness gap and eligible training-only contributors before M8.
- [M6 pooled-feature report](0088-M6_Pooled_Features.md): the candidate corrected one selection
  crop without introducing errors; this is not a robustness-gap measurement.
