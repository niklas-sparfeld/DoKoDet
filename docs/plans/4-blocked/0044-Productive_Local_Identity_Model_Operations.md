# Productive local identity model operations

## Plan status

- **Summary:** Make reviewed identity data, bounded training, comparison, promotion, and local
  runtime status productive in the web app after the quality proof succeeds.
- **Status:** Blocked
- **Depends on:** Plan 0043 locks a local candidate that passes its proof gates, and plan 0042
  provides completed identity review and dataset contracts
- **Builds on:** Plans 0028, 0039, 0040, 0041, 0042, and 0043
- **Outcome:** An operator can find priority identity work, publish reviewed data, launch and
  inspect a bounded local campaign, explicitly promote a passing bundle, and run the normal backend
  with local detection and local identity classification. The web app shows lineage, blockers,
  quality, and rollback state throughout.
- **Target architecture:**
  [Table Observation and Game Reconstruction](../../TableObservationReconstruction.md)

## Milestone status

- **M0:** Not started — add multi-recording identity work selection and data readiness status.
- **M1:** Not started — expose bounded local training and comparison campaigns in the web app.
- **M2:** Not started — add explicit promotion, backend cutover, and rollback.
- **M3:** Not started — measure the productive loop and close only the observed workflow gaps.

## 1. Purpose

Turn the proven local identity path into routine local operations. Keep human review, immutable
data, bounded recipes, deterministic gates, and explicit promotion as the source of truth. The web
app orchestrates existing application boundaries. It does not become a second training or
promotion implementation.

The productive loop is:

```text
eligible recordings
  -> bounded visual card identity review batch
  -> completed reviewed data
  -> group-safe dataset version
  -> bounded local campaign
  -> paired comparison and candidate lock
  -> explicit promotion
  -> local backend analysis
  -> measured low-confidence and error work for a later bounded batch
```

## 2. Scope

This epic includes:

- a multi-recording identity work list with eligibility, coverage, and priority reasons;
- bounded batch creation from completed visible-card reviews;
- dataset readiness and frozen-version status in the web app;
- start, resume, status, comparison, and report views for declared plan 0028 campaigns;
- explicit promotion confirmation with complete gate and rollback information;
- one champion registry entry for the visual card identity capability;
- local classifier startup, health, bundle identity, and latency status;
- a backend default change from Gemini to local only after successful promotion; and
- one measured productive exercise from new review work through local analysis.

This epic does not include:

- free-form architecture, hyperparameter, or prompt editing in the browser;
- automatic promotion, promotion from aggregate accuracy alone, or training from system-holdout
  feedback;
- remote workers, cloud training, multi-user accounts, or general job orchestration;
- silent Gemini fallback when the local classifier fails;
- automatic changes to visible-card geometry or human labels; or
- production deployment and broad system readiness from plan 0024.

## 3. Fixed decisions

1. Reuse the plan 0028 campaign commands and state machine as the only training, comparison,
   candidate-lock, sealed-test, and promotion implementation. The backend calls Python application
   boundaries directly. It does not parse CLI output or duplicate gate logic.
2. Offer only checked-in identity campaign recipes. The web app can select a recipe and declared
   dataset version. It cannot add candidates, edit thresholds, or raise budgets.
3. Build priority queues only from development data. Reasons can include class coverage gaps,
   low-confidence local results, local-versus-Gemini disagreement, and named reviewed failure tags.
   Freeze the reason and item budget before review begins.
4. Keep every classifier output as a proposal. A low-confidence result or disagreement can select
   work. It cannot write a human identity label.
5. Apply group-safe selection before crop generation. Exclude test and system-holdout lineage from
   review, training, priority calculation, and browser previews.
6. Promotion requires a locked candidate, required sealed-test authorization and result, passed
   gates, bundle load and smoke tests, and explicit operator confirmation.
7. Atomically update one `table-evidence-analyzer/identity-candidates` champion registry entry.
   Retain the prior champion and its configuration for rollback.
8. After successful promotion, make `local` the backend identity default. Keep explicit `gemini`
   mode for paired evaluation and diagnosis. Do not require a Gemini credential when both detector
   and identity settings are local.
9. If local startup or inference fails, produce an insufficient-evidence result with the bundle and
   failure provenance. Do not silently call Gemini.
10. Show all campaign, data, and model state through generated API types in the existing web app.
    Keep large logs and model bytes outside HTTP responses.

## 4. Web experience

Add a **Models and data** area with three focused views:

1. **Identity work** — eligible recordings, pending and completed review, class and source-group
   coverage, priority reason, and bounded batch creation.
2. **Identity campaigns** — resolved recipe, frozen data, progress, failed runs, comparison, gate
   results, candidate lock, and next action.
3. **Identity runtime** — champion and prior bundle, backend selection, load state, recent local
   latency, promotion receipt, and rollback action.

Lead with task state and the next action. Put digests, paths, code revisions, dependency versions,
and raw logs in diagnostic disclosures. Stream or poll concise status. Do not make the browser stay
open for a local training run.

## 5. Delivery milestones

### M0 — Add productive identity work selection

- Add development-only coverage and priority projections across recordings.
- Add preview and create operations for a bounded multi-recording review batch.
- Add an Identity work view with filters for state, identity coverage, failure tag, and priority
  reason.
- Reuse the plan 0042 item editor and completion path.

Acceptance:

- an operator can create one fixed-budget batch from eligible recordings and open its first item;
- every selected item records its priority reason and frozen source and proposal lineage;
- group-safe exclusion prevents test, holdout, and related protected items from appearing;
- repeated preview is deterministic for the same inputs; and
- an unreviewed proposal never enters a dataset.

### M1 — Add bounded campaign operations

- Add campaign readiness, recipe, start, resume, status, comparison, and report API projections.
- Add the Identity campaigns view and durable background execution.
- Show exact data versions, budgets, failures, metrics, gates, and candidate-lock state.

Acceptance:

- the web app starts only a checked-in recipe with an immutable eligible dataset version;
- restart and page reload resume status without repeating completed training or evaluation;
- a failed candidate and exhausted budget remain visible in the report;
- the UI cannot add an undeclared candidate or inspect system-holdout samples; and
- machine-readable campaign artifacts remain valid through the plan 0028 commands.

### M2 — Promote and cut over explicitly

- Add promotion preview and explicit confirmation with every required gate.
- Update the identity champion registry atomically through the existing promotion operation.
- Show champion, prior champion, local runtime health, and rollback state.
- Change the normal backend identity default to the promoted local bundle.

Acceptance:

- promotion is unavailable before candidate lock, required test, gate, export, and smoke evidence;
- promotion failure leaves the registry and backend configuration unchanged;
- a successful promotion survives restart and the prior champion stays loadable;
- the normal all-local backend path needs no Gemini credential and persists local provenance;
- local failure does not call Gemini silently; and
- rollback restores the prior registry selection through a new receipt.

### M3 — Exercise and measure the productive loop

- Run one new bounded priority batch through review, dataset publication, campaign, promotion
  decision, and normal backend analysis.
- Measure operator time, crop and label counts, proposal acceptance, correction rate, class and
  source coverage, training time, review rework, local latency, and terminal failures.
- Fix only gaps that block the loop, hide provenance, or make the next action unclear.
- Publish follow-up work as bounded epics from measured gaps.

Acceptance:

- the exercise can be reproduced locally from accepted recording data without cloud infrastructure;
- source, completed reviews, prior datasets, prior bundles, and prior receipts remain immutable;
- the report separates data, classifier, detector, crop, runtime, and operator failures;
- the web app shows the complete lineage from recording to current champion and analysis result;
  and
- broader automation or production work is deferred to a measured follow-up or plan 0024.

## 6. Verification

Run operations, backend, frontend, browser, campaign, promotion, registry, restart, rollback,
lifecycle, and end-to-end fixture checks. Use failure injection around long-running jobs, artifact
publication, registry replacement, backend startup, and promotion. Finish with one recorded local
operator exercise on real development data.
