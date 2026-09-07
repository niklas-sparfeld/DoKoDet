# Superseded review and data interfaces

## Plan status

- **Summary:** Prove which package-backed review and data interfaces have no necessary consumer,
  then remove only those obsolete surfaces.
- **Status:** To Specify
- **Depends on:** 0053 discovery complete
- **Outcome:** Supported component commands, reusable validators, and recording-pipeline workflows
  are distinct. Obsolete orchestration no longer consumes agent context.
- **Discovery evidence:** [Epic 0053 report](../../reports/0053-Agent_Navigation_Cleanup_Discovery.md)

## Milestone status

- **M0:** Not started — one `gpt-5.6-terra` agent builds the consumer proof and specifies
  Luna-sized delivery milestones.

## Problem and candidate paths

The former backend review route modules are gone, but current command help, documentation, tests,
and large review modules still expose package-backed and review-batch workflows. Candidate paths
include `card_event_net/src/cardevent/cli.py`, old review and data helpers in `card_event_net/`,
`operations/src/doko_operations/cardevent_review.py`, `visible_card_review_batch.py`,
`visual_card_identity_review_batch.py`, `table_evidence.py`, and old review/data helpers and command
definitions in `table_evidence_analyzer/`.

## Exclusions and overlap

Do not remove a command used by an agent, test, automation, runtime, operations, or recovery path.
Preserve reusable validation when the recording pipeline still uses its semantics. Preserve source
assets, reviewed data, fixtures, device evidence-package showcase behavior, and all 0051 behavior.
Keep training and evaluation interfaces required by 0043 or 0050.

## M0 specification questions

- Who consumes each candidate command, alias, module, export, schema, and fixture?
- Which interface is obsolete orchestration and which code is a reusable contract validator?
- Which current documentation makes an obsolete path appear supported?
- Can related removals share one component test and lint boundary?
- Which external or untracked recovery instructions must remain usable?

M0 must replace this outline with small delivery milestones. Each delivery milestone must fit one
`gpt-5.6-luna` phase and name focused Python tests, lint checks, and retained-command proofs. Close
this epic without delivery when a necessary consumer remains or the navigation benefit is weak.
