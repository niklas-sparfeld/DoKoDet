# 0120: node availability feasibility

Date: 2026-11-10. Inspected source: `591ed007`. This is a design and
counterexample review. It does not implement or prove a summary, change the list,
or qualify performance.

## Result and stop decision

Stop before implementing a summary. The existing list detects some damage to any
retained ancestor during each request. A bounded summary that does not read that
ancestor cannot also detect arbitrary changes to it after the summary was built.
This is a limit of the proposed input set, not a finding that all bounded designs
are impossible. No monitored storage or independent integrity authority was proved.
Do not silently change this error behavior or classify the failing case as debt.

In a disposable store, create an events node and save a second revision. Confirm
that `history()` returns both. Replace the first revision's JSON with invalid JSON.
The node manifest, head and authorized current revision still compare equal to their
earlier values; `history()` raises `JSONDecodeError`. The experiment used
`PipelineNodeStore` at source revision `591ed007` and a temporary directory. It
did not change retained application data. An algorithm that sees only those equal
inputs cannot distinguish the two states. A summary that is unchanged by the
external mutation has the same limitation. This is a concrete counterexample, not
a latency or concurrency benchmark.

The M0 report states that invalid nodes are omitted and logged. The current
`list_nodes()` and `history()` calls in the list path do not catch these node read
errors; they can fail the request. Record this discrepancy rather than treating the
M0 statement as evidence of actual handling. The test above establishes the store
behavior; it does not measure an HTTP response or every corruption case.

## Actual read and ownership

`GET /v1/recordings` calls `RoundAnalysisService.recording_catalog()` and then
`PipelineWorkspaceService.get_statuses()`. The latter calls
`_node_revisions_for_recordings()`. It lists all node manifests, selects nodes by
their source recording, reads lineage JSON records, traverses each selected node's
entire head ancestry and validates revision content and digest. It parses each
embedded `data_revision`, or constructs one from inherited metadata and lineage.
The resulting manifest recording and content type decide availability. An embedded
manifest can differ from the node source; the manifest or head alone is not an
equivalent shortcut. Even lineage that does not affect the final boolean can cause
an error while being read. Stage precedence still includes processor runs and
analyses. The blocker is separately owned by the selected table-observation
reference and valid linked packages; node availability is not its replacement.

`PipelineNodeStore.create` and `save` own ordinary node publication.
`PipelineNodeTransactions` owns coordinated node and selection changes; it uses a
pending locator and journal under the node transaction lock. Node creation and
save also use the recording revision history outbox. Writers include
`PipelineLineageWriter`, node edits and calibration, plus lineage import and draft
migration paths. Selection, lineage, run, package, and analysis stores remain
separate authorities. The history outbox and publication receipts do not attest
that every old revision remains readable or that a list summary is current. Do not
assume that they provide that guarantee.

## Candidate proof if the error boundary can be resolved

One candidate is a node-store-owned, per-recording set of available content types,
initialized from the actual old reader on a frozen retained snapshot. Its only
purpose would be stage availability. The source node and selection stores remain
authoritative. It would require one new durable summary and a defined atomic or
recoverable relationship to ordinary create/save and coordinated publication;
the existing transaction lock alone does not make a second file atomic with head
publication. The design must account for changes to metadata-derived recording and
content type, lineage inputs and errors, all initial source schemas, writer paths,
and both pre-commit and post-commit interruption. It must specify how it handles
unmanaged changes and corruption without pretending a stale value is verified.
No transaction design has been validated here.

Before any production cutover, a disposable proof must compare the old and new
results for empty and mixed recordings, all stage types, mismatched embedded
manifests, inherited metadata, invalid lineage and historical revisions, and
selection/blocker cases. It must initialize representative retained data, stop at
each publication boundary, retry in the same process and after restart, exercise
ordinary and coordinated writers against separate concurrent readers, and verify
that pending, missing, malformed and conflicting evidence fails correctly. It must
cover unrelated node growth and long histories separately, with the old node scan
disabled in the measured list path. A real API/browser workflow and comparable
hard-corpus measurements must show an improvement. Other source growth assertions
remain independently open; a node proof alone cannot establish the epic outcome.

The key unresolved decision is whether request-time detection of arbitrary
out-of-band historical damage is required, or whether another explicit integrity
mechanism and a defined detection window can satisfy the product's correctness
needs. This review does not choose a weaker requirement. If the existing behavior
must remain exact and no bounded integrity mechanism can be established, stop this
approach. If a different integrity boundary is authorized, specify it and a finite
proof before changing code. Any later retained-data activation needs a frozen
snapshot, validation, rollback and explicit recovery evidence; do not delete the
retired catalog data or source history as part of this review.

History is unchanged: M0–M2 are accepted as historical results, M3 is unaccepted
after two corrections, and the prior run retains its 1/10 re-planning count. This
review is not another M3 correction or a completed production workflow.
