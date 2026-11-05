# 0110 M12 — Calculation jobs

Calibration preview and counterfactual reconstruction use the shared job queue. Their browser
controls submit jobs and read the exact result after the job succeeds. Job details contain input
digests, progress, failure, and result paths. The synchronous counterfactual creation route is
removed.

The preview job stores the draft, proposal digest, calibration, and frame-scene evidence as one
snapshot. It publishes a result for that job only. The result endpoint compares the current snapshot
with the accepted snapshot and rejects a stale result. Apply remains a separate command. It checks
the current draft revision and recalculates the preview digest against current evidence before it
publishes a calibration revision.

A counterfactual job validates the complete correction request against the source analysis. It
stores the source input and result digests with the request. A retry keeps the same request and
counterfactual ID. Publication keeps the immutable result and rejects an identity conflict.

Both calculations stop before publication when cancellation is requested. The calculation itself
runs in process and does not stop until it reaches that boundary. The job manager arbitrates a
cancellation that races with publication. A restart uses the existing job recovery rules.

Local fixture checks cover preview result access, changed evidence, cancellation before publication,
counterfactual result integrity, linked retry after publication failure, and browser submission.
They do not measure calculation quality or hard interruption latency.
