# 0107 M7: lineage graph

`PipelineLineage` produces a deterministic graph with one entry for each node and exact revision.
It includes typed revision, copy, restore, run input, and run output edges. Nodes retain their source
records. Copies retain their actor, time, and reason. Runs retain every typed input and output,
implementation, model, configuration, policies, and context. External artifacts use an explicit
identity and SHA-256 digest. Analysis runs require recorded round context, rules, and search settings.
The graph reports accepted, successful, failed, and cancelled runs. A successful run records an
explicit empty or nonempty result; a failed run has no successful output. The producer supplies that
result classification and artifact digest. This service does not recalculate the artifact bytes or
infer whether a result is empty.

Before a worker reads its inputs, the caller must first register accepted node uses with
`PipelineNodeUses.accept`, then call `PipelineLineage.start` to freeze all typed inputs and execution
context. A bare accepted use is visible as an accepted run with unknown context. `finish` records the
terminal status against that exact request. Failed and cancelled runs keep their accepted uses.
Requests and terminal records are immutable and idempotent. Publication checks that revision inputs
match the accepted uses, all node revisions exist, exact outputs have at most one producer, and the
complete graph is acyclic. Graph reads also reject missing revision references and cycles. Artifact
identities and hashes must be verified by the caller that supplies them.

The graph returns compact node and revision summaries without content payloads. Multiple edges can
refer to one node. It does not choose a display parent or change processor selection. It is a local
foundation; existing processor and analysis services do not yet call it. Epic 0108 owns integration.
Migration must preserve or report unavailable context and external artifact verification rather than
invent values. Low-level node writes can contain arbitrary metadata; graph reads reject invalid
lineage, and callers must use the graph service to validate processor output publication.

Verification: focused tests cover three-input observations, an analysis with an external input and
result, two copies, alternate runs, accepted and failed runs, empty output, idempotency, restore and
revision edges, duplicate producers, mismatched accepted inputs, and cycle rejection. Ruff check and
format passed for the new files.
