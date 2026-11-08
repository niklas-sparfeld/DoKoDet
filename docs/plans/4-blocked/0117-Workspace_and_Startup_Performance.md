# Workspace and startup performance

## Plan status

- **Status:** Blocked
- **Depends on:** 0114 complete. Wait for 0115 M11 qualification and the final storage layout
  before M0. Coordinate any remaining storage changes before implementation.
- **Outcome:** Reduce measured workspace and backend startup delay without weakening content
  validation, exact lineage, review state, or restart behavior.

## Evidence and scope

The [0114 closure report](../../reports/0114-M13_Final_Qualification_and_Closure.md) records
about 30 groups above their planning targets. Hard workspace reads took 20.219 s cold median
and 20.293 s warm maximum. Hard startup to useful response took 8.041 s median. These are
measurements from revision `132987095cc7d5921ed9f7a6edd005574e81c442`, not current guarantees.
M12 reduced hard lineage time by about half. M13 found no safe bounded second change.

Five `node_store.history` traversals accounted for 14.325 s of a 20.351 s workspace request.
Those reads validate persisted revisions and their content. Removing validation or returning
incomplete history is not an accepted optimization. A new operation boundary needs an explicit
correctness contract. Do not repeat the same profile without a new hypothesis.

[0115](../3-in-progress/0115-Data_Cleanup.md) owns cleanup, worktree data access, and its selected
storage-format change. This epic owns delay that remains after that work. Compare code versions
on identical retained inputs. Report cleanup gains separately from runtime gains.

Prioritize workspace history and startup. M0 can reject either candidate if fresh evidence does
not justify it. Other slow groups remain a ranked handoff, not additional implementation cycles.
No model training, phone, cloud service, or review decision is required. The two malformed
`web/src/App.test.tsx` launch-modal fixtures are a separate bug fix.

## Execution contract

Use one focused implementation-and-plan commit per milestone. Update this epic and the board
together. Keep each milestone small enough for one Luna phase. No workers are authorized by
this plan alone. Split an oversized milestone before assignment.

Use the existing 0114 timing harness, route inventory, generated fixtures, and hard assets.
Preserve the original M11 baseline and raw evidence. Add versioned results for this epic.
Record code revision, machine/tool versions, fixture manifest digest, storage snapshot, cache
state, and exact commands. Do not call a generated-fixture result hard-corpus qualification.

At most two runtime candidates are in scope: workspace and startup. Freeze a numeric latency
target, operation-count target where relevant, correctness checks, reserved case, and finite
measurement budget before each implementation. Derive targets from M0 measurements and noise;
do not invent a percentage now. An unsuccessful change must be reverted and its evidence kept.
If no safe candidate exists, record that decision. Do not add cycles to extend the epic.

New persistent indexes, caches, or response contracts need explicit reader, writer, freshness,
validation, and recovery rules in M1 or M3 and a bounded implementation in M2 or M4. If this
requires more than one contract or conversion family, revise and split the plan before coding.
Do not hide a new store or migration in profiling or final qualification.

## Milestone status

| Milestone | Observable result / commit boundary | State |
| --- | --- | --- |
| M0 | Post-cleanup baseline, ranked debt, and two bounded candidate decisions | Not started |
| M1 | Workspace operation contract and disposable proof | Not started |
| M2 | One workspace optimization with measured correctness and gain | Not started |
| M3 | Startup operation contract and disposable proof | Not started |
| M4 | One startup optimization with measured correctness and gain | Not started |
| M5 | Combined qualification, debt handoff, and closure | Not started |

## M0 — Establish the post-cleanup baseline

Confirm 0115 M11 is complete. Record its final storage contract and retained corpus. Validate
the 57 frozen hard assets or an explicit verified replacement. Reconcile the 0114 route and
budget inventory with current code; list any changed cases before comparing results.

Run affected hard workspace, lineage, and startup profiles in three independent uncontended
sessions. Include empty, hard-populated, and interrupted-recovery startup. Measure time to useful
response, not only process readiness. Keep controlled-load results separate. Reuse unchanged
0114 evidence only with a written code/fixture applicability check.

Rank remaining slow groups by operator delay, frequency where measured, time, and operation
counts. Profile one exact workspace request and one leading startup path. Select at most one
validation-preserving workspace boundary and one startup boundary. Record stop reasons for
rejected candidates. Freeze the per-candidate targets and finite trial/runtime limits.

Checks: fixture and inventory validators, baseline comparator, exact response identities and
digests, bounded profiler counts, repeated cold/warm and process trials. Publish commands, raw
results, measured noise, and candidate decisions. Commit boundary: measurement tools and report,
epic, and board only; no optimization.

## M1 — Prove the workspace operation contract

For the selected workspace candidate, enumerate current readers/writers, representative resource
kinds and schema versions, and the exact repeated work to replace. Specify what each request
must validate and return. Preserve complete history, exact revision membership, copy ancestry,
missing/corrupt dependency errors, independent reviews, and selection behavior.

If a persistent index or cache is selected, define keys, validation authority, freshness across
processes, invalidation, atomic publication, restart, and recovery. If an API changes, list all
consumers and their replacement checks. Do not assume a file timestamp proves content validity.

Prove one full workflow through real services/APIs and disposable persistence with the replaced
path disabled. Use deterministic processor stubs where needed. Rehearse any conversion in
disposable storage. Record exact content and review state before and after edit/save/restart.

Checks: focused contract tests for stale, changed, missing, and corrupt data; concurrent readers
and writers separately from crash recovery when coordinated state changes. Commit boundary:
one bounded contract, its disposable proof, and report. If no workspace candidate was selected,
commit the evidence-based skip and mark M2 not applicable.

## M2 — Implement the workspace candidate

Implement only the M1 boundary. Remove the replaced runtime path and update its consumers.
For retained-data conversion, freeze the activation snapshot, verify exact dependencies, and
retain tested recovery evidence before activation. Do not alter immutable bytes behind a digest.

Checks: M1 regressions; real-backend workspace read, revision switch, edit/save, lineage and
restart; same-input cold/warm timing and operation counts; affected and reserved 0114 cases.
Run applicable backend/web tests, lint, format, types, and API generation checks. Accept only
the frozen gain with all correctness and regression gates passing. Commit boundary: one verified
workspace optimization and result report, or reverted candidate with a measured stop decision.

## M3 — Prove the startup operation contract

Use M0 and post-M2 evidence to select the exact startup work to reduce. State which work is
required before readiness and before each first useful response. Deferral must not merely move
the same delay to first use or hide recovery and resource failures.

Specify lifecycle, ownership, and failure handling for the selected boundary. A new persistent
cache or index requires the same explicit rules as M1. Avoid parallel initialization unless
evidence requires it and shared-resource behavior is tested.

Checks: disposable real-process proof for empty, populated, and interrupted-recovery storage;
first useful response content; failure visibility; repeated start/stop. Test concurrent first
requests and crash recovery separately when initialization or shared writes change. Commit
boundary: one startup contract, proof, and report. If no startup candidate was selected, commit
the stop evidence and mark M4 not applicable.

## M4 — Implement the startup candidate

Implement only the M3 boundary. Remove replaced initialization paths. Keep failures visible and
preserve exact workspace/review behavior after first use and restart.

Checks: M3 regressions; fresh process trials for all three startup profiles; readiness and useful
response timing; affected and reserved endpoint/browser cases. Measure CPU, memory, and I/O when
the change moves or overlaps work. Run applicable tests and static checks. Accept only the
frozen gain with all correctness and regression gates passing. Commit boundary: one verified
startup optimization and report, or reverted candidate with a measured stop decision.

## M5 — Qualify the combined result and close

Repeat affected M0 cases in three independent sessions on the same retained inputs and machine
profile. Run the current full 0114 qualification gates, all startup profiles, and the seven
browser/load workflows, adapted explicitly if current routes changed. Capture fresh evidence
for changed behavior; justify any reused unchanged suite families. Keep original budgets and
record stricter budgets separately when verified gains justify them.

Verify complete workspace history, revision switching, exact lineage, review editing/save,
Jobs status, media access, restart, and any activation/recovery path through real services and
disposable persistence. Run combined affected tests, lint, formatting, types, API generation,
and local Markdown link checks. Give remaining unrelated failures a named owner and evidence.

Publish before/after latency, operation counts, noise, suite cost, commands, fixture requirements,
and the remaining ranked debt. Distinguish a successful optimization from a documented stop.
Close as Complete only when each selected candidate meets its frozen target or was reverted
with an accepted evidence-based stop, and combined correctness and regression gates pass.
Commit boundary: combined qualification report, epic status/move, board, and mechanical links.
