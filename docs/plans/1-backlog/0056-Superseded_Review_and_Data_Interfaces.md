# Superseded review and data interfaces

## Plan status

- **Summary:** Remove proved-unused package-backed review and data orchestration. Keep pipeline
  contracts, active model-quality tools, and device-showcase validation.
- **Status:** Backlog
- **Depends on:** 0053 discovery complete
- **Outcome:** Supported component commands, reusable validators, and recording-pipeline workflows
  are distinct. Obsolete orchestration, exports, tests, and guides no longer consume agent context.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Complete — consumer proof and delivery boundaries specified.
- **M1:** Not started — remove the unconsumed CardEventNet package-review commands and their
  package-backed visual-event workflow.
- **M2:** Not started — remove the unconsumed CardEventNet table-observation dataset commands and
  their package-backed lifecycle helpers.
- **M3:** Not started — remove obsolete event and table-observation review adapters from
  operations after retaining any shared parsing or validation contract.
- **M4:** Not started — remove obsolete visible-card and visual-identity batch stores and exports
  after retaining the pipeline and 0051 validator seams.
- **M5:** Not started — remove obsolete command guidance and prove the reduced supported-command
  surface.

## Problem and candidate paths

The former backend review route modules are gone, but current command help, documentation, tests,
and large review modules still expose package-backed and review-batch workflows. The four legacy
operations stores contain 8,984 source lines. The related visible-card review, freeze, and dataset
helpers in TableEvidenceAnalyzer contain 3,415 more lines. The three command parsers declare 73
commands.

The recording pipeline does not directly use the old review stores. It uses pipeline contracts from
`doko_operations` and builds recording-video processor runs. Old store access remains through
operations exports, command handlers, focused tests, and transition-era documents. The old backend
review APIs are absent.

The candidate paths are `card_event_net/src/cardevent/cli.py` and its package-review and
package-dataset helpers; `operations/src/doko_operations/cardevent_review.py`,
`table_evidence.py`, `visible_card_review_batch.py`, and
`visual_card_identity_review_batch.py`; their exports and tests; and command guidance in
`card_event_net/README.md`, `docs/CardEventNet_ReviewWorkflow.md`,
`docs/CardEventNet_DataAndModelLifecycle.md`, `docs/Data_Lifecycle.md`, and
`table_evidence_analyzer/README.md`.

## Exclusions and overlap

Do not remove a command used by an agent, test, automation, runtime, operations, or recovery path.
Preserve reusable validation when the recording pipeline still uses its semantics. Preserve source
assets, reviewed data, fixtures, device evidence-package showcase behavior, and all 0051 behavior.
Keep training and evaluation interfaces required by 0043 or 0050. Do not change pipeline HTTP,
stored revision, dataset, model, or glossary contracts. Epic 0055 owns the documentation authority
map; this epic removes only guidance for removed interfaces.

## M0 consumer proof

| Surface | Current consumers | Decision |
| --- | --- | --- |
| CardEventNet `vision-import`, `vision-review`, and `vision-apply-review` | CLI tests and package-era lifecycle guides | Remove in M1. They import evidence packages as pipeline inputs, which the recording pipeline replaces. |
| CardEventNet `review-queue`, `review`, and `apply-review` | CLI tests and package-era review guides | Remove with M1 if no untracked recovery runbook names the command. Keep event-model training, inference, evaluation, and export commands. |
| CardEventNet `dataset-build`, `dataset-split`, `dataset-validate`, `dataset-coverage`, `training-receipt`, and `retire-source` | CLI tests and package-era lifecycle guides | Remove in M2. They build or maintain package-backed table-observation datasets. Do not remove source intake, model training, or export. |
| `CardEventReviewStore`, `TableEvidenceReviewAdapter`, and `TableObservationReviewAdapter` | Operations exports and the old `doko data review` path | Remove in M3 after preserving any standalone schema parser that a retained command needs. Pipeline references own review lifecycle validation. |
| `VisibleCardReviewBatchStore` and `VisualCardIdentityReviewBatchStore` | Operations exports and their focused tests | Remove in M4. The pipeline owns run, revision, and maintained-reference lifecycle. |
| TableEvidenceAnalyzer visible-card review workflow, freeze, and targeted-round validators | `visible_card_targeted_round.py`, CLI tests, and active 0051 work | Retain. They are not package-backed backend orchestration. Any M4 extraction must preserve their data contracts and 0051 behavior. |
| Device evidence-package acceptance and validation | Recording-bundle showcase, fixture tests, and recovery path | Retain. It is a showcase boundary, not a recording-pipeline input. |

Before M1 starts, check untracked operator and recovery instructions. A named consumer blocks only
its command or module; it does not block unrelated removals.

## Delivery milestones

### M1 — Remove package-review commands

Remove the CardEventNet package-review command group: `review-queue`, `review`,
`apply-review`, `vision-import`, `vision-review`, and `vision-apply-review`, including aliases,
handlers, package-only helpers, focused tests, and command guidance. Keep the event model's
annotation, preparation, split, train, infer, evaluate, diagnose, baseline, hard-negative, and
Core ML export paths.

Before removal, record the retained commands and check untracked recovery instructions. Run the
focused CardEventNet CLI and remaining review-independent tests, then Ruff for CardEventNet.

### M2 — Remove package dataset lifecycle commands

Remove `dataset-build`, `dataset-split`, `dataset-validate`, `dataset-coverage`,
`training-receipt`, and `retire-source`, with their aliases, package-only lifecycle helpers,
fixtures, tests, and guides. Keep source intake and inspection only if a current named consumer
remains. Do not remove pipeline datasets or model-training/evaluation commands.

Run the remaining CardEventNet CLI tests, source-intake tests that name a retained command, and
Ruff for CardEventNet.

### M3 — Remove old event and observation adapters

Remove the old operations event-review and package-observation orchestration, their exports, and
their tests: `cardevent_review.py`, the review adapters in `table_evidence.py`, and the obsolete
`doko data review` branch. Extract a small parser or validator only when a retained command proves
it needs one. Do not retain a compatibility wrapper.

Run focused operations CLI and pipeline-dataset tests, backend local-pipeline tests, and Ruff for
operations and backend.

### M4 — Remove old batch stores without changing active validators

Remove `VisibleCardReviewBatchStore` and `VisualCardIdentityReviewBatchStore`, their operations
exports, tests, and batch-only persistence helpers. Keep or move only the pure classifier,
geometry, crop, and review-contract validation that pipeline code or 0051 names as a consumer.
Do not alter TableEvidenceAnalyzer's visible-card review workflow, freeze, or targeted-round
behavior.

Run focused operations removal tests, TableEvidenceAnalyzer visible-card and targeted-round tests,
backend pipeline tests, and Ruff for operations and TableEvidenceAnalyzer.

### M5 — Remove obsolete guidance and prove retained commands

Remove or correct the package-route and review-batch guidance in current component documents. Do
not revise closed plans or reports. State the retained component commands in their owning README
and link to the recording workspace for pipeline review.

Check local Markdown links. Run each retained command with `--help`, the affected component test
suites, and Ruff. Confirm that no current guide advertises a removed command or old backend route.

Each milestone must keep the consumer ledger current. Close a blocked removal independently when a
necessary consumer remains; continue with unrelated proved-unused surfaces. Close the epic after
all retained-command proofs and the M5 documentation check pass.
