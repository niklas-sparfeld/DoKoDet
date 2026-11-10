# 0120 M8: recording HEAD list proof

Date: 2026-11-10. Baseline: `eb8d1fc9`. The code and tests in the commit that
contains this report are the measured revision. This is an opt-in proof, not a
production cutover.

## Result and decision

The real list route can read an explicitly maintained recording HEAD without node
history discovery. A real browser opened the list and the recording workspace after
a separate process imported two recordings, initialized HEAD, and edited selected
events through the state API. The list shows the selected event reference as data
available. It shows unavailable for a missing HEAD and for stage states that the
snapshot cannot establish. The analysis blocker still comes from the existing source
service. A reference is not proof that its content is valid.

Go for this limited proof. Stop before M9: this proof does not establish a finite M9
that preserves the whole existing list contract with at most one new persistent
contract. It does not prove that no such design exists. The measured remaining
sources and the old availability semantics need a concrete bounded publication and
recovery design before M9 can be assigned. Do not activate the proof for retained
data. M10 and M11 remain unstarted; the original performance outcome is unmet.

The proof uses `recording_list_head_proof`, false by default. An empty selection does
not establish an empty stage: an ordinary unselected node can be created without
changing HEAD. The proof therefore shows unavailable for empty selections, including
an initialized empty recording. A selected or stale reference maps to data available,
subject to existing active-run precedence. An active run can be shown even with an
empty selection; a partial or failed run cannot establish the old state when an
unselected revision might exist. Missing or corrupt HEAD or selected snapshot makes
all five stages unavailable. Existing analysis and package reads still determine the
blocker, counts, latest analysis and analysis stage. This mapping applies only while
the tested selected-state workflow maintains HEAD. Normal writers do not do so.

## Owners and remaining boundary

| Data | Current writer and authority | Remaining work |
| --- | --- | --- |
| Recording identity | `RecordingBundleStore`, repository-bundle intake | Initialize retained HEAD only from verified source state. |
| Selected events | State API and `RecordingStateWorkingEditor` publish `RecordingStateSnapshotStore` HEAD | Connect and verify ordinary node and selection writers before activation. `PipelineNodeStore.create/save` and `PipelineNodeSelectionStore.update_exact/publish_processor_revision` do not maintain this HEAD. |
| Historical availability | Node revisions and `PipelineWorkspaceService.get_statuses` | Preserve the old any-revision status for unselected outputs without scanning history. HEAD alone cannot distinguish them from an empty recording. |
| Run status | `ProcessorRunStore.create`, `update_state`, `update_progress` and lifecycle methods | Publish bounded status with interruption and restart semantics. |
| Analysis | `RoundAnalysisStore.create`, `update_progress`, `mark_complete`, `mark_failed` | Preserve precedence, counts and latest summary without reading all history. |
| Blocker and packages | `PipelineNodeSelectionStore` exact table-observation selection and `EvidencePackageStore.publish` with linked package lineage | Preserve the exact existing blocker, including package lineage and invalid metadata behavior, without a package-history scan. |

The existing HEAD transaction protects HEAD and its summary. It does not coordinate
the node, run, analysis, package and selection writers above. A selected reference
cannot replace an unselected historical availability result. Adding only more HEAD
reads cannot preserve that result. The removed catalog publication approach is not
evidence of a verified replacement. A proposal for M9 must identify the bounded
authority, source-to-publication crash handling, all finite writers and one contract;
it must not introduce a general multi-store transaction or move M11 qualification.

No retained schemas or source files were changed. The proof reads existing
`recording-head/v1`, `recording-state-snapshot/v1`, `recording-state-summary/v1`,
`pipeline-node/v1`, `event-data/v1`, and `repository-bundle/v1` data. Runs,
analyses, packages, selection and node histories remain authoritative and unchanged.
The old list remains the default and explicit detail and history paths remain.

## Measurements and checks

The disposable 1x/10x fixture holds recording count, active work and visible state
fixed. It independently counts source accesses. One instrumented request per size
gave the following results; these are not latency qualification.

| Read or result | 1x | 10x |
| --- | ---: | ---: |
| Node manifests | 0 | 0 |
| Node history records | 0 | 0 |
| Processor-run directories | 2 | 11 |
| Analysis rows | 2 | 20 |
| Package metadata rows | 1 | 10 |
| Response bytes | 1,101 | 1,103 |
| Elapsed milliseconds, one sample | 7.882 | 25.213 |

The node-manifest counter instruments node exact reads; the history counter
instruments node history. The fixture increases retained and unrelated records, not
the number of returned recordings. The remaining growth does not pass the epic's
bounded-read requirement. No comparable hard-corpus timing was taken: a valid HEAD
initialization for that corpus was not established, and initializing it as empty
would not be valid. No speedup is claimed from the disposable sample.

The browser fixture imports two `repository-bundle/v1` recordings via the real API,
with generated one-second video. Its source fixture manifest SHA-256 is
`8ddf0644c0e7d10ef0abc8c86f4b92e699e9edde0f1d6e76a27c64517322b946`.
The seed process exits before the browser backend starts on the same disposable
storage. Chromium loads `/recordings`, reloads, and opens the real workspace. The
legacy list-status method fails if called. A separate real API test makes node
discovery fail if called by the list.

The API tests cover selected and stale references, a no-change edit (which still
advances HEAD), stale expected version, empty and missing HEAD, corrupt HEAD, missing
and corrupt selected snapshot, and invalid historical and selected node payloads.
Opening corrupt selected content fails; the list does not read it. Existing
publication tests cover separate concurrent readers and writers, compare-and-swap,
restart and crash boundaries. The prior crash and concurrency regressions remain.

Checks: 86 targeted backend tests passed and five existing growth assertions xfailed;
the independent M8 growth check passed with the measurements above. Chromium passed
the real backend workflow. Web typecheck, lint, API generation verification, nine
App tests and changed-file formatting passed. Ruff and `git diff --check` passed.
The backend tests emit the existing Starlette/httpx deprecation warning.
